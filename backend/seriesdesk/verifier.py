"""Citation Verifier — deterministic, no LLM.

A brief is a list of sentences, each with citations {case_id, field, value}.
A brief passes only if every sentence passes:
  1. at least one citation;
  2. each citation resolves: case_id is in the brief's case set and field exists, non-null;
  3. the cited value equals the record value (normalized string, or set equality for lists);
  4. the cited value is actually stated in the sentence (each list item, normalized);
  5. no proper-noun-like token appears unless it occurs verbatim in a cited field value.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

# Capitalised words that are not names: domain vocabulary, months, weekdays, IDs.
ALLOWED_CAPS = {
    "the", "a", "an", "in", "on", "at", "both", "all", "each", "these", "this", "case", "cases",
    "series", "entry", "property", "mo", "no", "none", "one", "two", "three", "four", "five",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "district", "nibrs", "suspect", "victim", "offender", "night",
    "residential", "commercial", "between", "within", "across", "of", "and", "or", "for",
}
CASE_ID_RE = re.compile(r"^[A-Z]{1,3}-\d+[A-Za-z0-9]*$")
DISTRICT_RE = re.compile(r"^[A-Z]\d{1,2}$")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*|[A-Z]{1,3}-\d+\w*")


def normalize(v: Any) -> str:
    s = unicodedata.normalize("NFKC", str(v)).casefold().replace("_", " ")
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class SentenceResult:
    index: int
    sentence: str
    ok: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class VerifyResult:
    ok: bool
    sentences: list[SentenceResult]

    @property
    def failures(self) -> list[SentenceResult]:
        return [s for s in self.sentences if not s.ok]


def _values_equal(cited: Any, actual: Any) -> bool:
    if isinstance(actual, (list, tuple, set)):
        cited_list = cited if isinstance(cited, (list, tuple, set)) else [cited]
        # citing a subset of a multi-valued field is allowed
        return bool(cited_list) and {normalize(c) for c in cited_list} <= {normalize(a) for a in actual}
    return normalize(cited) == normalize(actual)


def _stated_in(sentence: str, cited: Any) -> bool:
    s = normalize(sentence)
    items = cited if isinstance(cited, (list, tuple, set)) else [cited]
    return all(normalize(i) in s for i in items)


def _proper_nouns(sentence: str) -> list[str]:
    toks = TOKEN_RE.findall(sentence)
    out = []
    for k, t in enumerate(toks):
        if k == 0 or not t[0].isupper():
            continue
        if t.casefold() in ALLOWED_CAPS or CASE_ID_RE.match(t) or DISTRICT_RE.match(t):
            continue
        out.append(t)
    return out


def verify_brief(sentences: Sequence[Mapping[str, Any]],
                 records: Mapping[str, Mapping[str, Any]]) -> VerifyResult:
    """records: {case_id: {field: value}} — only the cases in this series."""
    results: list[SentenceResult] = []
    for idx, item in enumerate(sentences):
        text = item.get("sentence", "")
        cites = item.get("citations") or []
        errs: list[str] = []
        if not text.strip():
            errs.append("empty sentence")
        if not cites:
            errs.append("no citations")
        cited_strings: list[str] = []
        for c in cites:
            cid, fld = c.get("case_id"), c.get("field")
            if cid not in records:
                errs.append(f"unknown case_id {cid!r}")
                continue
            rec = records[cid]
            if fld not in rec or rec[fld] in (None, "", []):
                errs.append(f"{cid}.{fld} missing or null")
                continue
            actual = rec[fld]
            cited_strings.extend(map(str, actual) if isinstance(actual, (list, tuple, set)) else [str(actual)])
            if "value" not in c:
                errs.append(f"{cid}.{fld} citation has no value")
                continue
            if not _values_equal(c["value"], actual):
                errs.append(f"{cid}.{fld} value mismatch: cited {c['value']!r}, record {actual!r}")
            elif not _stated_in(text, c["value"]):
                errs.append(f"{cid}.{fld} value {c['value']!r} not stated in sentence")
        haystack = " ".join(cited_strings)
        for noun in _proper_nouns(text):
            if noun not in haystack:
                errs.append(f"uncited proper noun {noun!r}")
        results.append(SentenceResult(idx, text, not errs, errs))
    return VerifyResult(ok=bool(results) and all(r.ok for r in results), sentences=results)
