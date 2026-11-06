import numpy as np
from seriesdesk.ranking import rank_features
from seriesdesk.series import grow_series


def test_mutual_rank_one_is_zero_and_ties_average():
    # case 0 partners: 1 (closest), 2; case 1 partners: 0, 2
    I = np.array([0, 0, 1]); J = np.array([1, 2, 2])
    dist = np.array([0.5, 2.0, 1.0]); days = np.zeros(3); mo = np.array([0.5, 0.5, 0.1])
    r = rank_features(I, J, dist, days, mo, n_cases=3)
    assert r[0, 0] == 0.0                      # 0<->1 is mutually closest
    assert r[1, 0] > 0                         # 0<->2: 2 is not 0's closest, and 0 isn't 2's closest
    assert r[0, 1] == 0.0                      # mutual: case 1 ranks 0 first by MO, so best side wins


def test_ties_share_average_rank():
    from seriesdesk.ranking import _group_ranks
    owner = np.array([0, 0, 0, 1]); score = np.array([0.5, 0.5, 0.1, 0.2])
    assert _group_ranks(owner, score, 2, ascending=False).tolist() == [1.5, 1.5, 3.0, 1.0]


def test_growth_needs_combined_evidence():
    seeds = [{"A", "B", "C"}]
    pairs = [{"case_a": "A", "case_b": "X", "prob": 0.3}, {"case_a": "B", "case_b": "X", "prob": 0.3},
             {"case_a": "C", "case_b": "X", "prob": 0.3},          # 1-0.7^3 = 0.657
             {"case_a": "A", "case_b": "Y", "prob": 0.3}]          # single weak link = 0.3
    out = grow_series(seeds, pairs, tau=0.6)
    assert out == [{"A", "B", "C", "X"}]


def test_growth_ignores_rejected_links():
    seeds = [{"A", "B"}]
    pairs = [{"case_a": "A", "case_b": "X", "prob": 0.9, "decision": "reject"}]
    assert grow_series(seeds, pairs, tau=0.5) == [{"A", "B"}]


def test_case_joins_strongest_group_only():
    seeds = [{"A", "B"}, {"C", "D"}]
    pairs = [{"case_a": "A", "case_b": "X", "prob": 0.6}, {"case_a": "C", "case_b": "X", "prob": 0.9}]
    out = grow_series(seeds, pairs, tau=0.5)
    assert {"C", "D", "X"} in out and {"A", "B"} in out
