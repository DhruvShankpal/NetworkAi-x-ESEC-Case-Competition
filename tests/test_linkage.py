import math
import pytest
from seriesdesk.linkage import LinkageModel, DESIGN_FEATURES, band
from seriesdesk.schema import EXCLUDED_FEATURES


def _toy():
    raws, y = [], []
    for k in range(60):
        raws.append({"distance_km": 0.5 + k % 3, "days_apart": 1 + k % 4, "mo_jaccard": 0.8, "same_target_type": 1,
                     "both_night": 1}); y.append(1)
        raws.append({"distance_km": 2 + k % 5, "days_apart": 10 + k % 9, "mo_jaccard": 0.1 * (k % 4), "same_target_type": k % 2,
                     "both_night": k % 2}); y.append(0)
    return raws, y


def test_contributions_are_exact_log_odds():
    raws, y = _toy()
    m = LinkageModel.fit(raws, y, version="t")
    for r in raws[:10]:
        p, c = m.score(r)
        logit = m.intercept + sum(c.values())
        assert p == pytest.approx(1 / (1 + math.exp(-logit)))
        assert m.score_many([r])[0] == pytest.approx(p)


def test_signs_make_sense():
    m = LinkageModel.fit(*_toy(), version="t")
    coef = dict(zip(DESIGN_FEATURES, m.coef))
    assert coef["mo_jaccard"] > 0
    assert coef["log_days_apart"] < 0


def test_json_roundtrip_and_hash_stable():
    m = LinkageModel.fit(*_toy(), version="lr-v1")
    m2 = LinkageModel.from_json(m.to_json())
    assert m2.coef == m.coef and m2.sha256() == m.sha256()


def test_no_excluded_features_in_design():
    assert not (set(DESIGN_FEATURES) & EXCLUDED_FEATURES)
    for f in DESIGN_FEATURES:
        assert not any(x in f for x in ("beat", "precinct", "district", "race", "sex", "age"))


def test_single_class_rejected():
    raws, y = _toy()
    with pytest.raises(ValueError):
        LinkageModel.fit(raws, [1] * len(raws), version="t")


def test_band():
    assert band(0.9) == "Strong" and band(0.5) == "Possible" and band(0.1) == "Weak"


def test_top_reasons_plain_language():
    m = LinkageModel.fit(*_toy(), version="t")
    _, c = m.score(_toy()[0][0])
    reasons = m.top_reasons(c)
    assert len(reasons) == 3
    assert {n for n, _ in reasons} <= {"distance", "time gap", "MO overlap", "same target type", "both at night"}
