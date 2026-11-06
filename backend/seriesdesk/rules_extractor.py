"""Rule-based MO extractor: the no-API baseline, and the fallback if the LLM is unavailable.

Phrase lexicon -> the same MO schema the LLM extractor fills. Every value carries the character span
it came from. Negations ("no tool marks") and planted instructions are ignored: rules only map
phrases to fixed categories, so text cannot instruct them.
"""
from __future__ import annotations

import re
from typing import Any

LEX: dict[str, dict[str, list[str]]] = {
    "entry_method": {
        "pry": [r"pr(y|ied|ying)\b", r"\bjimm(y|ied)", r"leverage", r"crowbar", r"forced with a pry"],
        "glass_broken": [r"(smash|broke|shatter)\w*( out)? (the )?(glass|pane|window)", r"glass (was )?broken"],
        "lock_pick": [r"pick(ed)? the lock", r"manipulat\w+ the lock"],
        "unlocked": [r"unlocked", r"unsecured", r"left open"],
        "kick": [r"kick\w*", r"boot(ed)? open"],
        "cut": [r"\bcut through", r"sliced through"],
    },
    "entry_point": {
        "front_door": [r"front (entry )?door", r"main entrance", r"door facing the street"],
        "rear_door": [r"(rear|back) door", r"door at the back", r"alley-side door"],
        "side_door": [r"side door", r"door on the side"],
        "window": [r"window", r"\bpane\b"],
        "garage": [r"garage door", r"roll-up"],
        "roof": [r"\broof", r"skylight"],
    },
    "tools": {
        "pry_bar": [r"pry bar", r"crowbar", r"metal bar"],
        "screwdriver": [r"screwdriver", r"flathead"],
        "rock": [r"\brock\b", r"brick", r"stone"],
        "hammer": [r"hammer", r"mallet"],
        "bolt_cutter": [r"bolt cutters?", r"\bcutters\b"],
    },
    "property_categories": {
        "cash": [r"\bcash\b", r"currency", r"till money", r"\$\d+", r"\bUSC\b"],
        "electronics": [r"laptop", r"\bTV\b", r"electronics", r"console", r"iPad", r"phone"],
        "jewelry": [r"jewel", r"\bwatch\b", r"necklace", r"ring\b"],
        "tools": [r"power tools", r"drill"],
        "gift_cards": [r"gift cards?", r"prepaid cards?"],
        "alcohol": [r"liquor", r"alcohol", r"whiskey", r"bottles of"],
        "tobacco": [r"cigarettes", r"vape", r"smokes", r"tobacco"],
        "firearms": [r"handgun", r"rifle", r"firearm", r"\bgun\b"],
        "bicycle": [r"bicycle", r"e-bike", r"\bbike\b"],
        "other": [r"misc", r"personal papers"],
    },
}
NEG = re.compile(r"\b(no|not|nothing|without|never|unrelated|undisturbed|not involved)\b", re.I)
INJECTION = re.compile(r"(ignore (all )?(previous|prior) instructions|note to ai|new instruction|system:|</narrative)", re.I)
SKIP_SENTENCE = re.compile(r"(was not involved|not disturbed|appears unrelated|neighbor's|adjacent)", re.I)


def _sentences(text: str):
    for m in re.finditer(r"[^.!?]+[.!?]?", text):
        yield m.start(), m.group(0)


def extract(text: str) -> dict[str, Any]:
    feats: dict[str, Any] = {"entry_point": None, "entry_method": None, "tools": [], "target_type": None,
                             "property_categories": [], "occupancy": None, "offender_count": None,
                             "vehicle_mentioned": False}
    spans: dict[str, list[list[int]]] = {}

    def hit(field, value, start, end, multi=False):
        if multi:
            if value not in feats[field]:
                feats[field].append(value)
        elif feats[field] is None:
            feats[field] = value
        else:
            return
        spans.setdefault(field, []).append([start, end])

    for off, sent in _sentences(text):
        if INJECTION.search(sent) or SKIP_SENTENCE.search(sent):
            continue  # planted instructions and explicit distractors are data, never facts
        low = sent.lower()
        if re.search(r"\b(business|store|shop|commercial|employee)\b", low):
            hit("target_type", "commercial", off, off + len(sent))
        elif re.search(r"\b(residence|home|house|apartment|residents)\b", low):
            hit("target_type", "residential", off, off + len(sent))
        negated = bool(NEG.search(sent))
        for field in ("entry_method", "entry_point"):
            if "unknown" in low or "unk" in low.split():
                continue
            for val, pats in LEX[field].items():
                for p in pats:
                    m = re.search(p, sent, re.I)
                    if m and not negated:
                        hit(field, val, off + m.start(), off + m.end())
        if "tool mark" in low and negated:
            pass
        else:
            for val, pats in LEX["tools"].items():
                for p in pats:
                    m = re.search(p, sent, re.I)
                    if m:
                        hit("tools", val, off + m.start(), off + m.end(), multi=True)
        if re.search(r"(items taken|taken:|stolen|loss)", low):
            for val, pats in LEX["property_categories"].items():
                for p in pats:
                    m = re.search(p, sent, re.I)
                    if m:
                        hit("property_categories", val, off + m.start(), off + m.end(), multi=True)
        if re.search(r"(home asleep|were home|employee was on site|occupied)", low):
            hit("occupancy", "occupied", off, off + len(sent))
        elif re.search(r"(nobody was present|unoccupied|no one (was )?home)", low):
            hit("occupancy", "unoccupied", off, off + len(sent))
        m = re.search(r"\b(\d+) (suspects?|S/1s?)\b", sent, re.I)
        if m:
            hit("offender_count", int(m.group(1)), off + m.start(), off + m.end())
        if re.search(r"\b(sedan|vehicle|veh|truck|van|car)\b", low) and re.search(r"(leaving|fled|seen)", low):
            feats["vehicle_mentioned"] = True
            spans.setdefault("vehicle_mentioned", []).append([off, off + len(sent)])
    # Window counted as entry point only when no door matched in the entry sentence (glass of a door).
    return {"features": feats, "evidence_spans": spans, "model_id": "rules-v1"}
