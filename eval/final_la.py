"""Final LA (real MO) evaluation with detective-facing operating modes. Datasets cached.

Adds two things to improve_la.py:
  * a wider threshold grid (true pairs are ~1 in 3,000+ candidates, so useful thresholds are low or very high);
  * a TOP-3 mode, which is how a detective uses the tool: for each case, the 3 strongest candidates.
    hit@3 = among series cases, the share whose top-3 list contains at least one true series partner.
Every choice (threshold, tau) is made on validation; test and stress are scored once.
Run: uv run python eval/final_la.py
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

from improve import evaluate, fit  # noqa: E402
from improve_la import COLS, LA22, LA23, build  # noqa: E402
from seriesdesk.synth_real import load_lapd  # noqa: E402

CACHE = ROOT / "data/lapd/cache.pkl"


def datasets():
    if CACHE.exists():
        return pickle.loads(CACHE.read_bytes())
    r22, r23 = load_lapd(LA22), load_lapd(LA23)
    d = {"train": [build(r22, s) for s in (20261106, 11)], "val": build(r22, 13),
         "test": build(r23, 777), "stress": build(r23, 778, keep=0.6, add=0.7)}
    CACHE.write_bytes(pickle.dumps(d))
    return d


def top_k(ds, p, k=3) -> dict:
    """Per-case top-k candidate lists."""
    n = len(ds["ids"])
    lists: list[list[tuple[float, int]]] = [[] for _ in range(n)]
    for a, b, pr, yy in zip(ds["I"], ds["J"], p, ds["y"]):
        lists[a].append((pr, yy)); lists[b].append((pr, yy))
    series_idx = [i for i, c in enumerate(ds["ids"]) if ds["key"][c]["true_series_id"]]
    hit = sum(1 for i in series_idx if any(yy for _, yy in sorted(lists[i], reverse=True)[:k]))
    shown = [x for l in lists for x in sorted(l, reverse=True)[:k]]
    return {f"hit_at_{k}": hit / len(series_idx), f"precision_of_top{k}_suggestions": float(np.mean([y for _, y in shown])),
            "series_cases": len(series_idx), "cases": n}


def pick(ds, p, thr_grid, tau_grid):
    best = None
    for t in thr_grid:
        for tau in tau_grid:
            f = evaluate(ds, p, t, tau)["member_f1"]
            if best is None or f > best[0]:
                best = (f, t, tau)
    return best[1], best[2]


def main():
    d = datasets()
    thr = [0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    plan = [("L0 Seattle-style model on real MO", [0, 1, 2, 3, 4], False),
            ("L1 + rare behaviours count more", [0, 1, 5, 3, 4], False),
            ("L2 + 'closest neighbour' ranks", [0, 1, 5, 3, 4, 6, 7], False),
            ("L3 + series-level evidence", [0, 1, 5, 3, 4, 6, 7], True)]
    out = {"protocol": __doc__.strip(),
           "test_size": {"cases": len(d["test"]["ids"]), "candidate_pairs": int(len(d["test"]["y"])),
                         "true_pairs": int(d["test"]["y"].sum())}, "steps": []}
    for name, cols, grow in plan:
        m = fit([t["X"] for t in d["train"]], [t["y"] for t in d["train"]], cols)
        pv = m.predict_proba(d["val"]["X"][:, cols])[:, 1]
        t, tau = pick(d["val"], pv, thr if not grow else thr[3:], (None,) if not grow else (0.3, 0.5, 0.7, 0.9))
        res = {"step": name, "threshold": t, "grow_tau": tau,
               "coef": dict(zip([COLS[c] for c in cols], np.round(m.coef_[0], 3).tolist()))}
        for split in ("test", "stress"):
            p = m.predict_proba(d[split]["X"][:, cols])[:, 1]
            res[split] = {**evaluate(d[split], p, t, tau), **top_k(d[split], p)}
        out["steps"].append(res)
        x = res["test"]
        print(f"{name:34s} thr {t} tau {tau} | AUC {x['auc']:.3f} P@50 {x['precision_at_50']:.2f} "
              f"hit@3 {x['hit_at_3']:.2f} top3prec {x['precision_of_top3_suggestions']:.3f} | "
              f"members {x['member_recall']:.2f} prec {x['member_precision']:.2f} F1 {x['member_f1']:.2f} "
              f"false {x['false_members']} | stress hit@3 {res['stress']['hit_at_3']:.2f} F1 {res['stress']['member_f1']:.2f}",
              flush=True)
    (ROOT / "eval/final_report_la.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
