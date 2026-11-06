from datetime import datetime
import math
import pytest
from seriesdesk.features import haversine_km, days_apart, mo_tokens, jaccard, pair_features, is_night


def test_haversine_known_distance():
    # Seattle (47.6062,-122.3321) to Tacoma (47.2529,-122.4443) ~ 40 km
    assert haversine_km(47.6062, -122.3321, 47.2529, -122.4443) == pytest.approx(40.1, abs=0.5)
    assert haversine_km(47.6, -122.3, 47.6, -122.3) == 0.0


def test_days_apart_uses_midpoints_and_is_symmetric():
    a = (datetime(2018, 7, 1, 0), datetime(2018, 7, 1, 4))   # mid 02:00
    b = (datetime(2018, 7, 4, 1), datetime(2018, 7, 4, 3))   # mid 02:00
    assert days_apart(*a, *b) == pytest.approx(3.0)
    assert days_apart(*b, *a) == pytest.approx(3.0)
    assert days_apart(a[0], None, a[0], None) == 0.0


def test_unknown_values_never_count_as_agreement():
    m1 = {"entry_point": "unknown", "entry_method": "unknown", "tools": ["none_noted"], "target_type": None,
          "property_categories": []}
    assert mo_tokens(m1) == set()
    assert jaccard(mo_tokens(m1), mo_tokens(m1)) == 0.0


def test_jaccard_bounds():
    a = {"entry_method:pry", "target_type:commercial"}
    assert jaccard(a, a) == 1.0
    assert jaccard(a, {"entry_method:pry"}) == 0.5
    assert jaccard(a, {"x"}) == 0.0


def test_is_night():
    assert is_night(datetime(2018, 1, 1, 23), datetime(2018, 1, 2, 3))
    assert not is_night(datetime(2018, 1, 1, 10), datetime(2018, 1, 1, 14))


def test_pair_features_flags():
    mo = {"entry_point": "front_door", "entry_method": "glass_broken", "tools": ["rock"],
          "target_type": "commercial", "property_categories": ["cash"]}
    a = {"lat": 47.6, "lon": -122.3, "offense_start": datetime(2018, 7, 1, 1), "offense_end": datetime(2018, 7, 1, 3), "mo": mo}
    f = pair_features(a, dict(a))
    assert f["mo_jaccard"] == 1.0 and f["same_target_type"] == 1.0 and f["both_night"] == 1.0


def test_coded_mo_tokens_and_rarity():
    from seriesdesk.features import weighted_jaccard, rarity_weights
    a = mo_tokens({"codes": ["0344", "1307"], "premise": "501", "target_type": "residential"})
    assert {"code:0344", "code:1307", "premise:501", "target_type:residential"} == a
    sets = [{"x", "common"}, {"common"}, {"common"}, {"y", "common"}]
    w = rarity_weights(sets)
    assert w["common"] == 0.0 and w["x"] > 0
    assert weighted_jaccard({"common", "x"}, {"common", "x"}, w) == 1.0
    assert weighted_jaccard({"common", "x"}, {"common", "y"}, w) == 0.0   # only the uninformative token shared
