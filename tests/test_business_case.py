import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("bc", Path(__file__).resolve().parents[1] / "eval" / "business_case.py")
import sys
bc = importlib.util.module_from_spec(spec); sys.modules["bc"] = bc; spec.loader.exec_module(bc)


def test_case_given_baseline():
    assert bc.BASELINE_COST == 3_050_000 and bc.TARGET_NET == 457_500
    assert abs(bc.TARGET_CLEARANCE - 0.1625) < 1e-12


def test_scenarios_are_ordered():
    r = bc.report()
    nets = [r[s]["cost"]["net_savings_per_year"] for s in ("conservative", "base", "optimistic")]
    lifts = [r[s]["clearance"]["extra_cleared_cases"] for s in ("conservative", "base", "optimistic")]
    assert nets == sorted(nets) and lifts == sorted(lifts)


def test_no_lift_when_model_finds_nothing_new():
    a = bc.SCENARIOS["base"].__class__(**{**bc.SCENARIOS["base"].__dict__, "model_recall": 0.0, "arrest_uplift": 0.0})
    assert bc.clearance(a)["extra_cleared_cases"] == 0


def test_payback_matches_definition():
    c = bc.cost_benefit(bc.SCENARIOS["base"])
    assert abs(c["payback_months"] - 12 * c["build_cost"] / c["net_savings_per_year"]) < 0.1
