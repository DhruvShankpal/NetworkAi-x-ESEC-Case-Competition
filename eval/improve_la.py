"""Accuracy steps on REAL MO data (LAPD Mocodes over real LA locations/times; injected series).

Protocol: train = 2 seeds over LAPD 2022; validation = 1 seed over LAPD 2022 (all thresholds chosen here);
test = seed 777 over LAPD 2023 (scored once per step); stress = seed 778 over 2023 with noisier
recording (keep 0.6, add 0.7). Run: uv run python eval/improve_la.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

from improve import evaluate, fit, pick  # noqa: E402
from seriesdesk.blocking import candidate_pairs  # noqa: E402
from seriesdesk.features import mo_tokens, pair_features, rarity_weights, weighted_jaccard  # noqa: E402
from seriesdesk.linkage import design_row  # noqa: E402
from seriesdesk.ranking import rank_features  # noqa: E402
from seriesdesk.synth_real import generate_real, load_lapd  # noqa: E402

LA22 = ROOT / "data/lapd/lapd_310_2022-04-01_2022-11-30.jsonl"
LA23 = ROOT / "data/lapd/lapd_310_2023-04-01_2023-11-30.jsonl"
COLS = ["log_dist", "log_days", "mo_jaccard", "same_target", "both_night", "mo_rarity_jaccard",
        "st_rank", "mo_rank"]


def build(rows, seed, **kw) -> dict:
    d = generate_real(rows, seed, **kw)
    key = {k["case_id"]: k for k in d.answer_key}
    toks = [mo_tokens(i["mo"]) for i in d.incidents]
    w = rarity_weights(toks)                       # unsupervised, from the visible case set only
    I, J, X = [], [], []
    for i, j, _ in candidate_pairs(d.incidents):
        I.append(i); J.append(j)
        X.append(design_row(pair_features(d.incidents[i], d.incidents[j])) + [weighted_jaccard(toks[i], toks[j], w)])
    I, J, X = np.array(I), np.array(J), np.array(X)
    ranks = rank_features(I, J, np.expm1(X[:, 0]), np.expm1(X[:, 1]), X[:, 5], len(d.incidents))
    ids = [i["case_id"] for i in d.incidents]
    y = np.array([int(key[ids[a]]["offender_id"] == key[ids[b]]["offender_id"]) for a, b in zip(I, J)])
    members = defaultdict(set)
    for cid, k in key.items():
        if k["true_series_id"]:
            members[k["true_series_id"]].add(cid)
    return {"ids": ids, "I": I, "J": J, "X": np.hstack([X, ranks]), "y": y, "key": key, "members": members}


def main():
    r22, r23 = load_lapd(LA22), load_lapd(LA23)
    print("building LA datasets...", file=sys.stderr)
    train = [build(r22, s) for s in (20261106, 11)]
    val = build(r22, 13)
    test = build(r23, 777)
    stress = build(r23, 778, keep=0.6, add=0.7)
    grid = [0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6]
    plan = [
        ("L0 baseline model on real MO", [0, 1, 2, 3, 4], None),
        ("L1 + rare behaviours count more", [0, 1, 5, 3, 4], None),
        ("L2 + 'closest neighbour' ranks", [0, 1, 5, 3, 4, 6, 7], None),
        ("L3 + series-level evidence", [0, 1, 5, 3, 4, 6, 7], "grow"),
    ]
    out = {"protocol": __doc__.strip(), "n_pairs": {"test": int(len(test["y"])), "test_true": int(test["y"].sum())},
           "steps": []}
    for name, cols, mode in plan:
        m = fit([t["X"] for t in train], [t["y"] for t in train], cols)
        pv = m.predict_proba(val["X"][:, cols])[:, 1]
        if mode == "grow":
            thr, tau = pick(val, pv, [0.3, 0.4, 0.5, 0.6, 0.7], (0.3, 0.4, 0.5, 0.6, 0.7))
        else:
            thr, tau = pick(val, pv, grid)
        pt = m.predict_proba(test["X"][:, cols])[:, 1]
        ps = m.predict_proba(stress["X"][:, cols])[:, 1]
        step = {"step": name, "threshold": thr, "grow_tau": tau,
                "coef": dict(zip([COLS[c] for c in cols], np.round(m.coef_[0], 3).tolist())),
                "validation": evaluate(val, pv, thr, tau),
                "test": evaluate(test, pt, thr, tau), "stress": evaluate(stress, ps, thr, tau)}
        out["steps"].append(step)
        t, s = step["test"], step["stress"]
        print(f"{name:36s} thr {thr} tau {tau} | recall {t['member_recall']:.2f} prec {t['member_precision']:.2f} "
              f"F1 {t['member_f1']:.2f} false {t['false_members']:4d} linkP {t['link_precision']:.2f} "
              f"AUC {t['auc']:.3f} | stress F1 {s['member_f1']:.2f}", flush=True)
    (ROOT / "eval/improvement_report_la.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
