from datetime import datetime, date
from seriesdesk.blocking import candidate_pairs, BlockingConfig
from seriesdesk.series import build_series


def inc(cid, lat, lon, day, tt="residential", em="pry", vis=None):
    s = datetime(2018, 7, day, 1)
    return {"case_id": cid, "lat": lat, "lon": lon, "offense_start": s, "offense_end": s,
            "replay_visible_on": vis or s.date(), "mo": {"target_type": tt, "entry_method": em}}


def test_local_block():
    xs = [inc("C-1", 47.60, -122.33, 1), inc("C-2", 47.61, -122.33, 3)]  # ~1.1 km, 2 days
    assert list(candidate_pairs(xs)) == [(0, 1, "local")]


def test_far_pair_needs_mo_gate():
    a = inc("C-1", 47.60, -122.33, 1, "commercial", "glass_broken")
    b = inc("C-2", 47.90, -122.20, 5, "commercial", "glass_broken")   # ~35 km
    c = inc("C-3", 47.90, -122.20, 5, "commercial", "pry")
    pairs = list(candidate_pairs([a, b, c]))
    assert (0, 1, "corridor") in pairs
    assert not any({p[0], p[1]} == {0, 2} for p in pairs)


def test_unknown_entry_method_does_not_open_corridor():
    a = inc("C-1", 47.60, -122.33, 1, "commercial", "unknown")
    b = inc("C-2", 47.90, -122.20, 5, "commercial", "unknown")
    assert list(candidate_pairs([a, b])) == []


def test_time_window():
    # 27 days: outside local (21d); corridor needs MO gate
    xs = [inc("C-1", 47.60, -122.33, 1, em="pry"), inc("C-2", 47.60, -122.33, 28, em="kick")]
    assert list(candidate_pairs(xs)) == []
    xs[1]["mo"]["entry_method"] = "pry"
    assert list(candidate_pairs(xs)) == [(0, 1, "corridor")]


def test_replay_visibility_hides_future_rows():
    xs = [inc("C-1", 47.60, -122.33, 1), inc("C-2", 47.61, -122.33, 3, vis=date(2018, 7, 10))]
    assert list(candidate_pairs(xs, replay_date=date(2018, 7, 5))) == []
    assert len(list(candidate_pairs(xs, replay_date=date(2018, 7, 10)))) == 1


def test_case_id_ordering():
    xs = [inc("C-9", 47.60, -122.33, 1), inc("C-2", 47.61, -122.33, 3)]
    (i, j, _), = candidate_pairs(xs)
    assert xs[i]["case_id"] < xs[j]["case_id"]


def test_series_components_respect_rejections():
    pairs = [
        {"case_a": "A", "case_b": "B", "prob": 0.9, "decision": None},
        {"case_a": "B", "case_b": "C", "prob": 0.95, "decision": "reject"},
        {"case_a": "C", "case_b": "D", "prob": 0.1, "decision": "accept"},
        {"case_a": "E", "case_b": "F", "prob": 0.2, "decision": None},
    ]
    assert build_series(pairs, threshold=0.5) == [{"A", "B"}, {"C", "D"}]


def test_coded_corridor_gate_needs_two_shared_codes():
    a = inc("C-1", 47.60, -122.33, 1, "commercial"); b = inc("C-2", 47.90, -122.20, 5, "commercial")
    a["mo"]["codes"], b["mo"]["codes"] = ["0344", "1307"], ["0344"]
    assert list(candidate_pairs([a, b])) == []
    b["mo"]["codes"] = ["0344", "1307"]
    assert list(candidate_pairs([a, b])) == [(0, 1, "corridor")]
