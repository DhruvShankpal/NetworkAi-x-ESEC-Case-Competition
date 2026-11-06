"""Pairwise linkage features. Pure functions, no I/O."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Mapping

from .schema import MULTI_FIELDS, SINGLE_FIELDS

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _midpoint(start: datetime, end: datetime | None) -> datetime:
    end = end or start
    if end < start:
        start, end = end, start
    return start + (end - start) / 2


def days_apart(a_start: datetime, a_end: datetime | None,
               b_start: datetime, b_end: datetime | None) -> float:
    """Absolute difference between offense-window midpoints, in days."""
    delta = _midpoint(a_start, a_end) - _midpoint(b_start, b_end)
    return abs(delta.total_seconds()) / 86400.0


def mo_tokens(mo: Mapping[str, Any]) -> set[str]:
    """Categorical MO tokens as 'field:value'. 'unknown'/None values are dropped,
    so missing information never counts as agreement."""
    toks: set[str] = set()
    for f in SINGLE_FIELDS:
        v = mo.get(f)
        if v and v != "unknown":
            toks.add(f"{f}:{v}")
    for f in MULTI_FIELDS:
        for v in mo.get(f) or []:
            if v and v not in ("unknown", "none_noted"):
                toks.add(f"{f}:{v}")
    # Real-MO records (e.g. LAPD Mocodes): coded behaviours + premise type.
    for c in mo.get("codes") or []:
        toks.add(f"code:{c}")
    if mo.get("premise"):
        toks.add(f"premise:{mo['premise']}")
    return toks


def weighted_jaccard(a: set[str], b: set[str], weight: Mapping[str, float]) -> float:
    """Jaccard where each token counts by its rarity weight (e.g. -log frequency).
    Sharing a behaviour 80% of burglaries have says little; sharing a rare one says a lot."""
    union = a | b
    if not union:
        return 0.0
    return sum(weight.get(t, 0.0) for t in a & b) / sum(weight.get(t, 0.0) for t in union)


def rarity_weights(token_sets) -> dict[str, float]:
    """Unsupervised token weights from the visible case set: w = -log(share of cases with token)."""
    from collections import Counter
    sets = list(token_sets)
    n = max(len(sets), 1)
    c = Counter(t for s in sets for t in s)
    return {t: -math.log(k / n) for t, k in c.items()}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_night(start: datetime, end: datetime | None) -> bool:
    """True if the window midpoint falls between 20:00 and 06:00 local."""
    h = _midpoint(start, end).hour
    return h >= 20 or h < 6


def pair_features(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, float]:
    """Raw (untransformed) features for one pair of incidents.

    Each incident needs: lat, lon, offense_start, offense_end, mo (dict).
    """
    ma, mb = a["mo"], b["mo"]
    return {
        "distance_km": haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]),
        "days_apart": days_apart(a["offense_start"], a.get("offense_end"),
                                 b["offense_start"], b.get("offense_end")),
        "mo_jaccard": jaccard(mo_tokens(ma), mo_tokens(mb)),
        "same_target_type": float(bool(ma.get("target_type")) and ma.get("target_type") == mb.get("target_type")),
        "both_night": float(is_night(a["offense_start"], a.get("offense_end"))
                            and is_night(b["offense_start"], b.get("offense_end"))),
    }
