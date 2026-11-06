"""Candidate generation (blocking). Union of a local block and an MO-gated corridor block.

Thresholds are design choices to tune on synthetic data, not literature values.
Pre-register them (eval/thresholds.json + hash) before the blind session.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterator, Mapping, Sequence

from .features import days_apart, haversine_km


@dataclass(frozen=True)
class BlockingConfig:
    local_km: float = 3.0
    local_days: float = 21.0
    corridor_km: float = 60.0
    corridor_days: float = 45.0


def _corridor_gate(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    ma, mb = a["mo"], b["mo"]
    if not ma.get("target_type") or ma.get("target_type") != mb.get("target_type"):
        return False
    if ma.get("codes") is not None and mb.get("codes") is not None:  # coded MO: need 2+ shared codes
        return len(set(ma["codes"]) & set(mb["codes"])) >= 2
    em_a, em_b = ma.get("entry_method"), mb.get("entry_method")
    return bool(em_a) and em_a != "unknown" and em_a == em_b


def candidate_pairs(incidents: Sequence[Mapping[str, Any]], cfg: BlockingConfig = BlockingConfig(),
                    replay_date: date | None = None) -> Iterator[tuple[int, int, str]]:
    """Yield (i, j, block) index pairs with i < j by case_id ordering.

    Sorted sweep on time so this is O(n * window) rather than O(n^2).
    `block` is 'local' or 'corridor' (local wins when both apply).
    """
    visible = [k for k, inc in enumerate(incidents)
               if replay_date is None or inc["replay_visible_on"] <= replay_date]
    order = sorted(visible, key=lambda k: incidents[k]["offense_start"])
    max_days = max(cfg.local_days, cfg.corridor_days)
    for p, i in enumerate(order):
        a = incidents[i]
        for j in order[p + 1:]:
            b = incidents[j]
            if (b["offense_start"] - a["offense_start"]).total_seconds() / 86400.0 > max_days + 2:
                break  # sorted by start; windows are short so +2d slack covers midpoints
            dt = days_apart(a["offense_start"], a.get("offense_end"), b["offense_start"], b.get("offense_end"))
            if dt > max_days:
                continue
            dkm = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            block = None
            if dkm <= cfg.local_km and dt <= cfg.local_days:
                block = "local"
            elif dkm <= cfg.corridor_km and dt <= cfg.corridor_days and _corridor_gate(a, b):
                block = "corridor"
            if block:
                lo, hi = (i, j) if a["case_id"] < b["case_id"] else (j, i)
                yield lo, hi, block


# Equivalent SQL for the database path (uses GIST + time indexes).
CANDIDATE_SQL = """
with vis as (
  select i.case_id, i.geom, i.offense_start, i.offense_end, m.features
  from app.incidents i join app.mo_features m on m.case_id = i.case_id and m.is_current
  where i.replay_visible_on <= %(replay_date)s
)
select a.case_id as case_a, b.case_id as case_b,
       case when st_dwithin(a.geom, b.geom, %(local_m)s)
             and abs(extract(epoch from (a.offense_start - b.offense_start))) <= %(local_s)s
            then 'local' else 'corridor' end as block
from vis a join vis b on a.case_id < b.case_id
where (st_dwithin(a.geom, b.geom, %(local_m)s)
       and abs(extract(epoch from (a.offense_start - b.offense_start))) <= %(local_s)s)
   or (st_dwithin(a.geom, b.geom, %(corridor_m)s)
       and abs(extract(epoch from (a.offense_start - b.offense_start))) <= %(corridor_s)s
       and a.features->>'target_type' = b.features->>'target_type'
       and a.features->>'entry_method' = b.features->>'entry_method'
       and a.features->>'entry_method' <> 'unknown')
"""


def sql_params(cfg: BlockingConfig, replay_date: date) -> dict[str, Any]:
    return {"replay_date": replay_date,
            "local_m": cfg.local_km * 1000, "local_s": cfg.local_days * 86400,
            "corridor_m": cfg.corridor_km * 1000, "corridor_s": cfg.corridor_days * 86400}
