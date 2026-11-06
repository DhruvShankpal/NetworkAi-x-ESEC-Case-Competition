"""Seeded synthetic burglary generator.

Step 1 (here): sample a structured MO "truth" record per incident.
Step 2 (here, template) or llm.render_narrative (Haiku 5.5): verbalize the truth.
The LLM never invents MO facts.

Output is split: incidents (what the app sees) vs answer key (offender/series labels,
decoy flags). The answer key is written to a separate file for the sealed DB.
"""
from __future__ import annotations

import math
import random
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from .schema import ENTRY_METHOD, ENTRY_POINT, OCCUPANCY, PROPERTY, TARGET_TYPE, TOOLS

# Fictional region (roughly city-sized box). District = 4x4 grid label, never a feature.
CENTER = (47.60, -122.33)
HALF_SPAN_DEG = (0.22, 0.30)
KM_PER_DEG_LAT = 111.32


@dataclass
class SynthConfig:
    seed: int = 20261106
    start: date = date(2018, 4, 1)
    days: int = 240
    n_noise: int = 1500
    n_series: int = 10
    series_len: tuple[int, int] = (4, 12)
    n_corridor_series: int = 2
    n_decoys: int = 2
    decoy_len: tuple[int, int] = (4, 6)
    mo_mutation: float = 0.15
    # Optional real space-time backdrop (e.g. SPD open data rows with lat, lon, offense_start,
    # reported_at). When set, noise rows use these real locations/times/report lags instead of
    # uniform random points, and series anchor on real burglary locations. MO + narrative stay synthetic.
    backdrop: list[dict[str, Any]] | None = None


@dataclass
class Dataset:
    incidents: list[dict[str, Any]]
    answer_key: list[dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "uncommitted"


def _district(lat: float, lon: float) -> str:
    r = min(3, max(0, int((lat - (CENTER[0] - HALF_SPAN_DEG[0])) / (2 * HALF_SPAN_DEG[0]) * 4)))
    c = min(3, max(0, int((lon - (CENTER[1] - HALF_SPAN_DEG[1])) / (2 * HALF_SPAN_DEG[1]) * 4)))
    return f"{'SMCN'[r]}{c + 1}"  # south, mid, central, north bands x 4 columns


def _offset_km(lat: float, lon: float, dn_km: float, de_km: float) -> tuple[float, float]:
    return (lat + dn_km / KM_PER_DEG_LAT,
            lon + de_km / (KM_PER_DEG_LAT * math.cos(math.radians(lat))))


class _Gen:
    def __init__(self, cfg: SynthConfig):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.np = np.random.default_rng(cfg.seed)
        self.n = 0

    # --- sampling primitives -------------------------------------------
    def point(self) -> tuple[float, float]:
        return (CENTER[0] + self.rng.uniform(-1, 1) * HALF_SPAN_DEG[0],
                CENTER[1] + self.rng.uniform(-1, 1) * HALF_SPAN_DEG[1])

    def window(self, day: datetime, night_bias: float) -> tuple[datetime, datetime]:
        if self.rng.random() < night_bias:
            start_h = self.rng.choice([21, 22, 23, 0, 1, 2, 3])
        else:
            start_h = self.rng.randint(7, 18)
        start = day.replace(hour=start_h % 24, minute=self.rng.choice([0, 15, 30, 45]))
        return start, start + timedelta(hours=self.rng.choice([1, 2, 3, 4, 6, 8]))

    def marginal_mo(self) -> dict[str, Any]:
        r = self.rng
        tt = r.choices(TARGET_TYPE, [0.7, 0.3])[0]
        return {
            "entry_point": r.choices(ENTRY_POINT, [25, 25, 10, 20, 10, 2, 3, 5])[0],
            "entry_method": r.choices(ENTRY_METHOD, [30, 20, 5, 20, 10, 5, 10])[0],
            "tools": r.sample(TOOLS[:-1], r.choice([0, 0, 1, 1, 2])) or ["none_noted"],
            "target_type": tt,
            "property_categories": r.sample(PROPERTY, r.choice([1, 2, 2, 3])),
            "occupancy": r.choices(OCCUPANCY, [15, 70, 15])[0],
            "offender_count": r.choices([None, 1, 2, 3], [50, 30, 15, 5])[0],
            "vehicle_mentioned": r.random() < 0.15,
        }

    def mutate(self, sig: dict[str, Any]) -> dict[str, Any]:
        """Series member: signature with per-field noise (extractor/report variability)."""
        mo = {k: (list(v) if isinstance(v, list) else v) for k, v in sig.items()}
        fresh = self.marginal_mo()
        for k in ("entry_point", "entry_method", "tools", "property_categories", "occupancy"):
            if self.rng.random() < self.cfg.mo_mutation:
                mo[k] = fresh[k]
        if self.rng.random() < 0.3:
            mo["offender_count"] = None
        return mo

    def case_id(self) -> str:
        self.n += 1
        return f"C-{self.n:05d}"

    def incident(self, lat, lon, day, mo, night_bias, offender, series_id, is_decoy=False,
                 fixed_start=None, fixed_reported=None):
        start, end = self.window(day, night_bias)
        if fixed_start is not None:  # real backdrop row: keep its time and report lag
            start, end = fixed_start, fixed_start + (end - start)
        reported = fixed_reported or end + timedelta(hours=self.rng.choice([1, 3, 8, 14, 30]))
        reported = max(reported, start)
        inc = {
            "case_id": None, "source": "synthetic",
            "offense_start": start, "offense_end": end, "reported_at": reported,
            "nibrs_code": "220", "nibrs_desc": "Burglary/Breaking & Entering",
            "lat": round(lat, 6), "lon": round(lon, 6),
            "district_fictional": _district(lat, lon),
            "replay_visible_on": reported.date(),
            "mo": mo,
        }
        return inc, {"offender_id": offender, "true_series_id": series_id, "is_decoy": is_decoy}


def generate(cfg: SynthConfig = SynthConfig()) -> Dataset:
    g = _Gen(cfg)
    rows: list[tuple[dict, dict]] = []
    t0 = datetime.combine(cfg.start, datetime.min.time())

    # Noise: one offender per case.
    if cfg.backdrop:
        bd = sorted(cfg.backdrop, key=lambda r: r["offense_start"])
        t0 = datetime.combine(bd[0]["offense_start"].date(), datetime.min.time())
        cfg = SynthConfig(**{**cfg.__dict__, "days": (bd[-1]["offense_start"] - t0).days + 1})
        for r in bd:
            rows.append(g.incident(r["lat"], r["lon"], r["offense_start"], g.marginal_mo(), 0.45,
                                   f"O-noise-{len(rows)}", None, fixed_start=r["offense_start"],
                                   fixed_reported=r.get("reported_at")))
        g.point = lambda: (lambda r: (r["lat"], r["lon"]))(g.rng.choice(bd))  # anchors on real locations
    else:
        for _ in range(cfg.n_noise):
            lat, lon = g.point()
            day = t0 + timedelta(days=g.rng.randrange(cfg.days))
            rows.append(g.incident(lat, lon, day, g.marginal_mo(), 0.45, f"O-noise-{len(rows)}", None))

    # True series.
    for s in range(cfg.n_series):
        corridor = s < cfg.n_corridor_series
        sig = g.marginal_mo()
        sig["target_type"] = "commercial" if corridor else sig["target_type"]
        sig["entry_method"] = g.rng.choice(["glass_broken", "pry", "kick", "cut"])
        lat, lon = g.point()
        heading = g.rng.uniform(0, 2 * math.pi)
        day = t0 + timedelta(days=g.rng.randrange(max(1, cfg.days - 60)))
        sid, oid = f"TS-{s:02d}", f"O-series-{s:02d}"
        for _ in range(g.rng.randint(*cfg.series_len)):
            rows.append(g.incident(lat, lon, day, g.mutate(sig), 0.85, oid, sid))
            if corridor:  # spree along a road corridor: big steps, consistent heading
                step = g.rng.uniform(4, 12)
                lat, lon = _offset_km(lat, lon, step * math.cos(heading), step * math.sin(heading))
                if abs(lat - CENTER[0]) > HALF_SPAN_DEG[0] * 1.6:
                    heading = math.pi - heading
            else:
                lat, lon = _offset_km(lat, lon, g.np.normal(0, 1.2), g.np.normal(0, 1.2))
            day += timedelta(days=g.rng.randint(1, 6) if not corridor else g.rng.randint(1, 4))

    # Decoys: look like a series on one axis only. Every case is a different offender.
    for d in range(cfg.n_decoys):
        sig = g.marginal_mo()
        lat, lon = g.point()
        day = t0 + timedelta(days=g.rng.randrange(max(1, cfg.days - 60)))
        for k in range(g.rng.randint(*cfg.decoy_len)):
            oid = f"O-decoy-{d}-{k}"
            if d % 2 == 0:  # shared MO, implausible space-time
                plat, plon = g.point()
                pday = t0 + timedelta(days=g.rng.randrange(cfg.days))
                rows.append(g.incident(plat, plon, pday, g.mutate(sig), 0.85, oid, None, True))
            else:  # plausible space-time, divergent MO
                plat, plon = _offset_km(lat, lon, g.np.normal(0, 0.8), g.np.normal(0, 0.8))
                rows.append(g.incident(plat, plon, day + timedelta(days=k * 2), g.marginal_mo(),
                                       0.5, oid, None, True))

    # Shuffle so case_id order carries no signal, then assign IDs.
    g.rng.shuffle(rows)
    incidents, key = [], []
    for inc, lab in rows:
        inc["case_id"] = g.case_id()
        inc["narrative"], inc["evidence_spans"] = render_template(inc, g.rng)
        inc["narrative_origin"] = "synthetic_template"
        incidents.append(inc)
        key.append({"case_id": inc["case_id"], **lab})
    meta = {"seed": cfg.seed, "generator_sha": _git_sha(), "n": len(incidents),
            "backdrop": "spd_open" if cfg.backdrop else "uniform",
            "n_series": cfg.n_series, "n_decoys": cfg.n_decoys}
    return Dataset(incidents, key, meta)


# ---------------------------------------------------------------------------
# Template narrative renderer with exact evidence spans.
_PHRASES = {
    "entry_point": {"front_door": "the front door", "rear_door": "the rear door",
                    "side_door": "a side door", "window": "a window", "garage": "the garage door",
                    "roof": "the roof", "other": "an unusual opening", "unknown": "an undetermined point"},
    "entry_method": {"pry": "pried open", "glass_broken": "broke the glass of", "lock_pick": "manipulated the lock on",
                     "unlocked": "walked in through unlocked", "kick": "kicked in", "cut": "cut through",
                     "unknown": "gained entry via"},
    "tools": {"pry_bar": "a pry bar", "screwdriver": "a screwdriver", "rock": "a rock",
              "hammer": "a hammer", "bolt_cutter": "bolt cutters"},
    "property": {"cash": "cash", "electronics": "electronics", "jewelry": "jewelry", "tools": "power tools",
                 "gift_cards": "gift cards", "alcohol": "alcohol", "tobacco": "tobacco products",
                 "firearms": "a firearm", "bicycle": "a bicycle", "other": "miscellaneous items"},
}


def render_template(inc: dict[str, Any], rng: random.Random) -> tuple[str, dict[str, list[list[int]]]]:
    mo = inc["mo"]
    spans: dict[str, list[list[int]]] = {}
    parts: list[str] = []

    def add(text: str, fld: str | None = None) -> None:
        pos = sum(len(p) for p in parts)
        if fld:
            spans.setdefault(fld, []).append([pos, pos + len(text)])
        parts.append(text)

    place = "business" if mo["target_type"] == "commercial" else "residence"
    add(rng.choice(["Officers responded to a report of a burglary at a ", "R/P reported a break-in at a "]))
    add(place, "target_type")
    add(f". Between {inc['offense_start']:%H%M} and {inc['offense_end']:%H%M} hours, the suspect ")
    add(_PHRASES["entry_method"][mo["entry_method"]], "entry_method")
    add(" ")
    add(_PHRASES["entry_point"][mo["entry_point"]], "entry_point")
    add(" to gain entry. ")
    tools = [t for t in mo["tools"] if t != "none_noted"]
    if tools:
        add("Marks consistent with ")
        for k, t in enumerate(tools):
            if k:
                add(" and ")
            add(_PHRASES["tools"][t], "tools")
        add(" were observed. ")
    else:
        add("No tool marks were noted. ")
    add("Reported loss: ")
    for k, p in enumerate(mo["property_categories"]):
        if k:
            add(", ")
        add(_PHRASES["property"][p], "property_categories")
    add(". ")
    occ = {"occupied": "The premises were occupied at the time. ",
           "unoccupied": "The premises were unoccupied. ", "unknown": ""}[mo["occupancy"]]
    if occ:
        add(occ, "occupancy")
    if mo.get("offender_count"):
        add(f"A witness described {mo['offender_count']} suspect(s). ", "offender_count")
    if mo.get("vehicle_mentioned"):
        add("A vehicle was seen leaving the area. ", "vehicle_mentioned")
    add("No further information at this time.")
    return "".join(parts), spans
