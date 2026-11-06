"""Cost-benefit and clearance model for Series Desk. Every input is a named, stated assumption.

Case-given facts (fictional Cascade City baseline): 10,000 burglaries/yr, 13% cleared,
officer $50/h, detective $70/h, detective analysis 90 min/case, $305/case, $3.05M/yr.
Everything else is an ASSUMPTION, shown with a conservative / base / optimistic value.
Run: uv run python eval/business_case.py
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

CASES = 10_000
DET_RATE = 70.0
OFF_RATE = 50.0
BASELINE_COST = CASES * (4 * OFF_RATE + 1.5 * DET_RATE)   # $3.05M
TARGET_NET = 0.15 * BASELINE_COST                          # $457,500
BASE_CLEARANCE = 0.13
TARGET_CLEARANCE = BASE_CLEARANCE * 1.25                   # 16.25%


@dataclass(frozen=True)
class Assumptions:
    # --- time (detective stage 6 only; Series Desk does not touch officer stages) ---
    search_min_saved: float          # cross-referencing replaced by reviewing ranked suggestions
    share_cases_linked: float        # share of all cases that end up in an accepted series
    consolidation_min_saved: float   # per linked case: one shared follow-up instead of N separate ones
    # --- costs ---
    build_cost: float                # one-time: RMS integration, CJIS hosting setup, policy/SIR, training dev
    run_cost: float                  # per year: GovCloud hosting, LLM, 0.25 FTE support, audits, training
    # --- clearance ---
    share_series: float              # share of burglaries committed by offenders with 2+ cases
    arrest_rate_series: float        # share of series whose offender is arrested (baseline)
    arrest_uplift: float             # relative lift in arrests from pooled leads across linked cases
    attached_before: float           # share of a series' cases detectives attach today when arrest happens
    model_recall: float              # share of series cases attached because of Series Desk =
                                     #   hit@3 (measured, real LAPD data, leave-one-year-out 2020-23)
                                     #   x share of correct suggestions a detective confirms (assumption)
    conversion: float                # share of attached cases that end up formally cleared


SCENARIOS = {
    # model_recall: conservative = worst year hit@3 0.884 x 50% confirmed; base = mean hit@3 0.917 x 67%;
    # optimistic = hit@3 0.933 with 3 narrative detail fields captured 80% of the time x 80%.
    "conservative": Assumptions(15, 0.08, 15, 260_000, 130_000, 0.20, 0.30, 0.10, 0.35, 0.44, 0.5),
    "base":         Assumptions(25, 0.12, 20, 180_000, 92_000, 0.25, 0.30, 0.20, 0.35, 0.61, 0.6),
    "optimistic":   Assumptions(32, 0.15, 30, 130_000, 70_000, 0.30, 0.30, 0.30, 0.35, 0.75, 0.7),
}


def cost_benefit(a: Assumptions) -> dict:
    min_saved = a.search_min_saved + a.share_cases_linked * a.consolidation_min_saved
    gross = CASES * min_saved / 60 * DET_RATE
    net = gross - a.run_cost
    return {
        "minutes_saved_per_case": round(min_saved, 1),
        "detective_hours_freed_per_year": round(CASES * min_saved / 60),
        "gross_savings": round(gross),
        "running_cost": a.run_cost,
        "net_savings_per_year": round(net),
        "net_pct_of_baseline": round(100 * net / BASELINE_COST, 1),
        "hits_15pct_target": net >= TARGET_NET,
        "build_cost": a.build_cost,
        "payback_months": round(12 * a.build_cost / net, 1) if net > 0 else None,
        "roi_3yr_pct": round(100 * (3 * gross - a.build_cost - 3 * a.run_cost) / (a.build_cost + 3 * a.run_cost)),
        "year1_net_after_build": round(net - a.build_cost),
        "minutes_needed_for_15pct": round((TARGET_NET + a.run_cost) / DET_RATE / CASES * 60, 1),
    }


def clearance(a: Assumptions) -> dict:
    series_cases = CASES * a.share_series
    attached_after = 1 - (1 - a.attached_before) * (1 - a.model_recall)   # detective OR model finds it
    cleared_before = series_cases * a.arrest_rate_series * a.attached_before * a.conversion
    cleared_after = series_cases * a.arrest_rate_series * (1 + a.arrest_uplift) * attached_after * a.conversion
    extra = cleared_after - cleared_before
    rate = BASE_CLEARANCE + extra / CASES
    return {
        "series_cases": round(series_cases),
        "attached_share_before": a.attached_before,
        "attached_share_after": round(attached_after, 3),
        "series_clearances_before": round(cleared_before),
        "series_clearances_after": round(cleared_after),
        "extra_cleared_cases": round(extra),
        "clearance_rate_pct": round(100 * rate, 2),
        "relative_lift_pct": round(100 * (rate / BASE_CLEARANCE - 1), 1),
        "hits_25pct_target": rate >= TARGET_CLEARANCE - 1e-9,
        "extra_needed_for_target": round(CASES * (TARGET_CLEARANCE - BASE_CLEARANCE)),
    }


def report() -> dict:
    return {name: {"assumptions": asdict(a), "cost": cost_benefit(a), "clearance": clearance(a)}
            for name, a in SCENARIOS.items()}


if __name__ == "__main__":
    print(json.dumps({"baseline_cost": BASELINE_COST, "target_net_savings": TARGET_NET,
                      "target_clearance_pct": 100 * TARGET_CLEARANCE, **report()}, indent=2))
