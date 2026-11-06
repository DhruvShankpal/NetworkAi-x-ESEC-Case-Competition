"""Score an MO extractor on the practice set, per field and per difficulty tag.

Single-value fields: exact match (null counts: predicting a value when the truth is null is wrong).
Multi-value fields (tools, property_categories): set F1.
Usage: uv run python eval/run_extract_eval.py --extractor rules [--split heldout]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

SINGLE = ["entry_point", "entry_method", "target_type", "occupancy", "offender_count", "vehicle_mentioned"]
MULTI = ["tools", "property_categories"]


def set_f1(pred, truth):
    p, t = set(pred or []), set(truth or [])
    if not p and not t:
        return 1.0
    if not p or not t:
        return 0.0
    tp = len(p & t)
    return 2 * tp / (len(p) + len(t))


def score(records, extract_fn):
    per_field = defaultdict(list)
    per_tag = defaultdict(list)
    for r in records:
        pred = extract_fn(r["narrative"])["features"]
        row = {}
        for f in SINGLE:
            row[f] = float(pred.get(f) == r["truth"][f])
        for f in MULTI:
            row[f] = set_f1(pred.get(f), r["truth"][f])
        for f, v in row.items():
            per_field[f].append(v)
        mean = sum(row.values()) / len(row)
        for t in r["tags"] or ["clean"]:
            per_tag[t].append(mean)
    avg = lambda xs: round(sum(xs) / len(xs), 3)  # noqa: E731
    return {"n": len(records), "per_field": {f: avg(v) for f, v in per_field.items()},
            "overall": avg([x for v in per_field.values() for x in v]),
            "per_tag": {t: avg(v) for t, v in sorted(per_tag.items())},
            "fields_at_or_above_0.90": sum(avg(v) >= 0.9 for v in per_field.values())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", default="rules", choices=["rules", "llama"])
    ap.add_argument("--split", default="heldout", choices=["dev", "heldout", "all"])
    a = ap.parse_args()
    recs = [json.loads(l) for l in open(ROOT / "eval/practice_set.jsonl")]
    if a.split != "all":
        recs = [r for r in recs if r["split"] == a.split]
    if a.extractor == "rules":
        from seriesdesk.rules_extractor import extract
    else:
        from seriesdesk.llama_extractor import extract
    res = {"extractor": a.extractor, "split": a.split, **score(recs, extract)}
    (ROOT / f"eval/extract_report_{a.extractor}_{a.split}.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
