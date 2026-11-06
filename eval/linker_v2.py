"""Linker v2 on REAL LA data: additive spline model (GAM) + same-event merge. Compared with v1 (L2 logistic).

v1  logistic regression, straight-line effects (the L2 configuration).
v2a GAM: each continuous fact gets a smooth curve (cubic splines, 5 knots) instead of a straight line;
    still additive, so the score is exactly the sum of one contribution per fact.
v2b same-event merge: pairs < 150 m apart and < 24 h apart are one EVENT (e.g. several units hit in one
    night). They are shown to the detective as "same event" and are not scored as cross-day links.
    All metrics below are for cross-event links, which is where linkage work is needed.
Train: 2 seeds over LAPD 2022; test: seed 777 over LAPD 2023; stress: seed 778 (noisier recording).
Metrics: hit@1 / hit@3 (series case has a true partner in its top-1 / top-3), precision@100 of the
highest-scoring cross-event links, AUC.
Run: uv run python eval/linker_v2.py
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import SplineTransformer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
from final_la import CACHE  # noqa: E402

COLS = [0, 1, 5, 3, 4, 6, 7]            # log_dist, log_days, rarity-MO, same_target, both_night, st_rank, mo_rank
CONT = [0, 1, 2, 5, 6]                  # positions (within COLS) of continuous facts
BIN = [3, 4]


def same_event(ds):
    return (np.expm1(ds["X"][:, 0]) < 0.15) & (np.expm1(ds["X"][:, 1]) < 1.0)


def topk(ds, p, mask, k):
    n = len(ds["ids"])
    best: list[list[tuple[float, int]]] = [[] for _ in range(n)]
    for a, b, pr, yy in zip(ds["I"][mask], ds["J"][mask], p[mask], ds["y"][mask]):
        best[a].append((pr, yy)); best[b].append((pr, yy))
    series = [i for i, c in enumerate(ds["ids"]) if ds["key"][c]["true_series_id"]]
    return sum(any(y for _, y in sorted(best[i], reverse=True)[:k]) for i in series) / len(series)


def metrics(ds, p, mask):
    y = ds["y"][mask]; pm = p[mask]
    o = np.argsort(-pm)
    return {"auc": round(float(roc_auc_score(y, pm)), 4), "hit_at_1": round(topk(ds, p, mask, 1), 3),
            "hit_at_3": round(topk(ds, p, mask, 3), 3), "precision_at_100": round(float(y[o[:100]].mean()), 3),
            "precision_at_25": round(float(y[o[:25]].mean()), 3)}


def v1():
    return LogisticRegression(C=1.0, max_iter=5000)


def v2():
    ct = ColumnTransformer([("s", SplineTransformer(n_knots=5, degree=3, extrapolation="linear"), CONT),
                            ("b", "passthrough", BIN)])
    return make_pipeline(ct, LogisticRegression(C=1.0, max_iter=5000))


def main():
    d = pickle.loads(CACHE.read_bytes())
    out = {"method": __doc__.strip(), "rows": []}
    for name, make, merge in [("v1 logistic (current)", v1, False), ("v2a GAM splines", v2, False),
                              ("v1 + same-event merge", v1, True), ("v2 GAM + same-event merge", v2, True)]:
        Xs, ys = [], []
        for t in d["train"]:
            keep = ~same_event(t) if merge else np.ones(len(t["y"]), bool)
            Xs.append(t["X"][keep][:, COLS]); ys.append(t["y"][keep])
        m = make().fit(np.vstack(Xs), np.concatenate(ys))
        row = {"model": name}
        for split in ("test", "stress"):
            ds = d[split]
            mask = ~same_event(ds) if merge else np.ones(len(ds["y"]), bool)
            p = m.predict_proba(ds["X"][:, COLS])[:, 1]
            row[split] = metrics(ds, p, mask)
            if merge:
                row[split]["same_event_pairs_merged"] = int((~mask).sum())
        out["rows"].append(row)
        print(json.dumps(row), flush=True)
    (ROOT / "eval/linker_v2_report.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
