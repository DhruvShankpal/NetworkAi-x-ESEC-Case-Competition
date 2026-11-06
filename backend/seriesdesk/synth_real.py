"""Real-MO dataset builder (LAPD Mocodes).

Background: every real LAPD burglary in the window, with its REAL location, time, premise and MO codes.
Series: injected (no public data says which burglaries share an offender). Each series starts from a
real LAPD case and reuses that case's real code set as the offender's signature. Each later member
keeps each code with prob `keep` and adds a code drawn from the real code frequencies with prob `add`
(officer-to-officer recording variability, an assumption). Locations step from real burglary
locations; timing follows the same rules as synth.py.
"""
from __future__ import annotations

import json
import math
import random
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from .synth import Dataset, _offset_km


def load_lapd(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            r["offense_start"] = datetime.fromisoformat(r["offense_start"])
            r["reported_at"] = datetime.fromisoformat(r["reported_at"])
            rows.append(r)
    return rows


def _mo(codes, target, premise):
    return {"codes": sorted(set(codes)), "target_type": target, "premise": premise}


def generate_real(rows: list[dict[str, Any]], seed: int, n_series: int = 12, n_corridor: int = 2,
                  series_len: tuple[int, int] = (4, 12), n_decoys: int = 2,
                  keep: float = 0.75, add: float = 0.5) -> Dataset:
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    codes = Counter(c for r in rows for c in r["mo_codes"])
    code_list, code_w = zip(*codes.items())
    t0 = min(r["offense_start"] for r in rows)
    span = (max(r["offense_start"] for r in rows) - t0).days
    out: list[tuple[dict, dict]] = []

    def inc(lat, lon, start, mo, offender, sid, decoy=False, reported=None):
        rep = reported or start + timedelta(hours=rng.choice([2, 6, 12, 24, 48]))
        return ({"case_id": None, "source": "lapd_open+synthetic_series", "lat": lat, "lon": lon,
                 "offense_start": start, "offense_end": start, "reported_at": max(rep, start),
                 "replay_visible_on": max(rep, start).date(), "mo": mo, "narrative": "",
                 "narrative_origin": None, "evidence_spans": {}},
                {"offender_id": offender, "true_series_id": sid, "is_decoy": decoy})

    for k, r in enumerate(rows):  # real background, one offender each (unknown in reality)
        out.append(inc(r["lat"], r["lon"], r["offense_start"], _mo(r["mo_codes"], r["target_type"], r["premise"]),
                       f"O-real-{k}", None, reported=r["reported_at"]))

    def member_codes(sig):
        cs = [c for c in sig if rng.random() < keep]
        if rng.random() < add:
            cs.append(rng.choices(code_list, code_w)[0])
        return cs or list(sig[:1])

    for s in range(n_series):
        corridor = s < n_corridor
        pool = [r for r in rows if r["target_type"] == "commercial"] if corridor else rows
        anchor = rng.choice(pool)
        sig, tt, prem = anchor["mo_codes"], anchor["target_type"], anchor["premise"]
        lat, lon = anchor["lat"], anchor["lon"]
        heading = rng.uniform(0, 2 * math.pi)
        day = t0 + timedelta(days=rng.randrange(max(1, span - 60)))
        hour = anchor["offense_start"].hour
        for _ in range(rng.randint(*series_len)):
            start = day.replace(hour=int(hour + nrng.normal(0, 1.5)) % 24, minute=rng.choice([0, 15, 30, 45]))
            p = prem if rng.random() < 0.7 else rng.choice(pool)["premise"]
            out.append(inc(lat, lon, start, _mo(member_codes(sig), tt, p), f"O-series-{s}", f"TS-{s:02d}"))
            if corridor:
                step = rng.uniform(4, 12)
                lat, lon = _offset_km(lat, lon, step * math.cos(heading), step * math.sin(heading))
                day += timedelta(days=rng.randint(1, 4))
            else:
                lat, lon = _offset_km(lat, lon, nrng.normal(0, 1.2), nrng.normal(0, 1.2))
                day += timedelta(days=rng.randint(1, 6))

    for d in range(n_decoys):  # shared real MO, implausible space-time; or plausible space-time, unrelated MO
        anchor = rng.choice(rows)
        for k in range(rng.randint(4, 6)):
            if d % 2 == 0:
                r = rng.choice(rows)
                out.append(inc(r["lat"], r["lon"], t0 + timedelta(days=rng.randrange(span), hours=rng.randrange(24)),
                               _mo(member_codes(anchor["mo_codes"]), anchor["target_type"], anchor["premise"]),
                               f"O-decoy-{d}-{k}", None, True))
            else:
                r = rng.choice(rows)
                lat, lon = _offset_km(anchor["lat"], anchor["lon"], nrng.normal(0, 0.8), nrng.normal(0, 0.8))
                out.append(inc(lat, lon, anchor["offense_start"] + timedelta(days=2 * k),
                               _mo(r["mo_codes"], r["target_type"], r["premise"]), f"O-decoy-{d}-{k}", None, True))

    rng.shuffle(out)
    incidents, key = [], []
    for n, (i, lab) in enumerate(out, 1):
        i["case_id"] = f"C-{n:05d}"
        incidents.append(i)
        key.append({"case_id": i["case_id"], **lab})
    return Dataset(incidents, key, {"seed": seed, "backdrop": "lapd_open", "n": len(incidents),
                                    "keep": keep, "add": add})
