"""'Closest neighbour' features: how a candidate ranks among a case's other candidates.

Raw distance means different things downtown and in the suburbs: 800 m apart is unremarkable
where burglaries are dense and striking where they are sparse. Ranking fixes that. For each pair
(a, b) we ask "among all of a's candidate partners, how close is b?" and take the better of the two
directions (mutual ranks). Rank 1 = b is a's single closest burglary.

  st_rank = rank by space-time closeness (km + weeks; one km ~ one week)
  mo_rank = rank by method similarity (ties share the average rank)

Features are log1p(rank) so the drop from 1st to 2nd matters more than from 40th to 41st.
Unsupervised: uses only the candidate set, never labels. Recompute per replay day.
"""
from __future__ import annotations

import numpy as np


def _group_ranks(owner: np.ndarray, score: np.ndarray, n_cases: int, ascending: bool) -> np.ndarray:
    """Average rank (1 = best) of each row within its owner group. Vectorized."""
    s = np.asarray(score, dtype=float) if ascending else -np.asarray(score, dtype=float)
    owner = np.asarray(owner)
    order = np.lexsort((s, owner))
    o, v = owner[order], s[order]
    n = len(order)
    if n == 0:
        return np.empty(0)
    idx = np.arange(n)
    new_group = np.r_[True, o[1:] != o[:-1]]
    group_start = np.maximum.accumulate(np.where(new_group, idx, 0))
    pos = idx - group_start                                  # 0-based position inside the owner's block
    new_run = new_group | np.r_[True, v[1:] != v[:-1]]       # run of tied scores within a block
    run_id = np.cumsum(new_run) - 1
    run_sum = np.bincount(run_id, weights=pos)
    run_len = np.bincount(run_id)
    ranks = np.empty(n)
    ranks[order] = run_sum[run_id] / run_len[run_id] + 1
    return ranks


def rank_features(I: np.ndarray, J: np.ndarray, dist_km: np.ndarray, days: np.ndarray,
                  mo_sim: np.ndarray, n_cases: int) -> np.ndarray:
    """Returns an (n_pairs, 2) array: log1p(mutual space-time rank), log1p(mutual MO rank)."""
    I, J = np.asarray(I), np.asarray(J)
    owner = np.concatenate([I, J])                     # each pair appears once per endpoint
    st = np.concatenate([dist_km + days / 7.0] * 2)
    mo = np.concatenate([mo_sim] * 2)
    n = len(I)
    st_r = _group_ranks(owner, st, n_cases, ascending=True)
    mo_r = _group_ranks(owner, mo, n_cases, ascending=False)
    st_best = np.minimum(st_r[:n], st_r[n:])
    mo_best = np.minimum(mo_r[:n], mo_r[n:])
    return np.column_stack([np.log1p(st_best - 1), np.log1p(mo_best - 1)])  # rank 1 -> 0
