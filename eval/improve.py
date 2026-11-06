"""Accuracy-improvement experiments on the realistic set (real SPD space-time backdrop).

Protocol (no test-set peeking):
  train      = 3 synthetic seeds over SPD 2022 burglaries
  validation = 1 more seed over SPD 2022  -> every threshold is chosen here (max member-F1)
  test       = seed 777 over SPD 2023     -> scored once per step, never used for choices
  stress     = seed 778 over SPD 2023 with noisier MO (mo_mutation 0.25) -> robustness check

Detective-facing metrics (what a judge should look at):
  member recall    = share of true series cases placed in their series' group
  member precision = share of cases in flagged groups that truly belong to that group's series
  member F1, plus link precision (share of shown links that are true) and AUC.
Run: uv run python eval/improve.py   (takes several minutes)
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from seriesdesk.blocking import candidate_pairs  # noqa: E402
from seriesdesk.features import pair_features  # noqa: E402
from seriesdesk.linkage import design_row  # noqa: E402
from seriesdesk.ranking import rank_features  # noqa: E402
from seriesdesk.series import build_series, grow_series  # noqa: E402
from seriesdesk.soda import load_backdrop  # noqa: E402
from seriesdesk.synth import SynthConfig, generate  # noqa: E402

SPD22 = ROOT / "data/spd/spd_220_2022-04-01_2022-11-30.jsonl"
SPD23 = ROOT / "data/spd/spd_220_2023-04-01_2023-11-30.jsonl"


def build(seed: int, backdrop_path: Path, mo_mutation: float = 0.15) -> dict:
    d = generate(SynthConfig(seed=seed, backdrop=load_backdrop(backdrop_path), mo_mutation=mo_mutation))
    key = {k["case_id"]: k for k in d.answer_key}
    I, J, base = [], [], []
    for i, j, _ in candidate_pairs(d.incidents):
        I.append(i); J.append(j)
        base.append(design_row(pair_features(d.incidents[i], d.incidents[j])))
    I, J, base = np.array(I), np.array(J), np.array(base)
    ranks = rank_features(I, J, dist_km=np.expm1(base[:, 0]), days=np.expm1(base[:, 1]),
                          mo_sim=base[:, 2], n_cases=len(d.incidents))
    ids = [inc["case_id"] for inc in d.incidents]
    y = np.array([int(key[ids[i]]["offender_id"] == key[ids[j]]["offender_id"]) for i, j in zip(I, J)])
    members = defaultdict(set)
    for cid, k in key.items():
        if k["true_series_id"]:
            members[k["true_series_id"]].add(cid)
    return {"ids": ids, "I": I, "J": J, "X": np.hstack([base, ranks]), "y": y, "key": key, "members": members}


def member_scores(groups: list[set[str]], key: dict, members: dict) -> dict:
    total = sum(len(m) for m in members.values())
    found = sum(max((len(m & g) for g in groups), default=0) for m in members.values())
    flagged = correct = 0
    for g in groups:
        sids = Counter(key[c]["true_series_id"] for c in g if key[c]["true_series_id"])
        flagged += len(g)
        correct += sids.most_common(1)[0][1] if sids else 0
    r = found / total if total else 0.0
    p = correct / flagged if flagged else 0.0
    return {"member_recall": r, "member_precision": p, "member_f1": 2 * p * r / (p + r) if p + r else 0.0,
            "cases_flagged": flagged, "false_members": flagged - correct}


def groups_for(ds, p, thr, grow_tau=None):
    pairs = [{"case_a": ds["ids"][i], "case_b": ds["ids"][j], "prob": float(pr), "decision": None}
             for i, j, pr in zip(ds["I"], ds["J"], p) if pr >= min(thr, 0.02)]
    seeds = build_series([q for q in pairs if q["prob"] >= thr], thr)
    return grow_series(seeds, pairs, grow_tau) if grow_tau is not None else seeds


def evaluate(ds, p, thr, grow_tau=None) -> dict:
    g = groups_for(ds, p, thr, grow_tau)
    shown = p >= thr
    order = np.argsort(-p)
    return {**member_scores(g, ds["key"], ds["members"]), "auc": float(roc_auc_score(ds["y"], p)),
            "link_precision": float(ds["y"][shown].mean()) if shown.any() else 0.0,
            "links_shown": int(shown.sum()), "precision_at_50": float(ds["y"][order[:50]].mean())}


def pick(ds, p, grid, grow_grid=(None,)):
    """Choose the operating point that maximizes member-F1 on VALIDATION data."""
    best = None
    for thr in grid:
        for tau in grow_grid:
            f = evaluate(ds, p, thr, tau)["member_f1"]
            if best is None or f > best[0]:
                best = (f, thr, tau)
    return best[1], best[2]


def fit(Xs, ys, cols):
    X = np.vstack([x[:, cols] for x in Xs]); y = np.concatenate(ys)
    return LogisticRegression(C=1.0, max_iter=5000).fit(X, y)


def main():
    print("building datasets (slow: ~1M candidate pairs each)...", file=sys.stderr)
    train = [build(s, SPD22) for s in (20261106, 11, 12)]
    val = build(13, SPD22)
    test = build(777, SPD23)
    stress = build(778, SPD23, mo_mutation=0.25)
    print("datasets built", file=sys.stderr)

    BASE, RANK = [0, 1, 2, 3, 4], [0, 1, 2, 3, 4, 5, 6]
    grid = [0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6]
    steps = {}

    # S0: model as shipped last round (1 training seed, threshold 0.3 picked by looking at test)
    m0 = fit([train[0]["X"]], [train[0]["y"]], BASE)
    steps["S0 shipped model"] = dict(model=m0, cols=BASE, thr=0.3, tau=None,
                                     how="1 training set; threshold 0.3 (chosen on test last round)")
    # S1: more training data + threshold chosen on validation
    m1 = fit([t["X"] for t in train], [t["y"] for t in train], BASE)
    t1, _ = pick(val, m1.predict_proba(val["X"][:, BASE])[:, 1], grid)
    steps["S1 more data + honest threshold"] = dict(model=m1, cols=BASE, thr=t1, tau=None,
                                                    how=f"3 training sets; threshold {t1} chosen on validation")
    # S2: neighbour-rank features
    m2 = fit([t["X"] for t in train], [t["y"] for t in train], RANK)
    t2, _ = pick(val, m2.predict_proba(val["X"][:, RANK])[:, 1], grid)
    steps["S2 + 'closest neighbour' features"] = dict(model=m2, cols=RANK, thr=t2, tau=None,
                                                      how=f"adds space-time rank and MO rank; threshold {t2}")
    # S3: series-level growth (case-to-series evidence)
    pv = m2.predict_proba(val["X"][:, RANK])[:, 1]
    t3, tau3 = pick(val, pv, [0.3, 0.4, 0.5, 0.6, 0.7], (0.3, 0.4, 0.5, 0.6, 0.7))
    steps["S3 + series-level evidence"] = dict(model=m2, cols=RANK, thr=t3, tau=tau3,
                                               how=f"seed groups at p>={t3}; add a case if combined evidence to the group >= {tau3}")

    out = {"protocol": __doc__.split("Detective-facing")[0].strip(), "steps": []}
    for name, s in steps.items():
        pt = s["model"].predict_proba(test["X"][:, s["cols"]])[:, 1]
        ps = s["model"].predict_proba(stress["X"][:, s["cols"]])[:, 1]
        out["steps"].append({"step": name, "how": s["how"], "threshold": s["thr"], "grow_tau": s["tau"],
                             "coef": dict(zip(["log_dist", "log_days", "mo_jaccard", "same_target", "both_night",
                                               "st_rank", "mo_rank"][:len(s["cols"])],
                                              np.round(s["model"].coef_[0], 3).tolist())),
                             "test": evaluate(test, pt, s["thr"], s["tau"]),
                             "stress": evaluate(stress, ps, s["thr"], s["tau"])})
    (ROOT / "eval/improvement_report.json").write_text(json.dumps(out, indent=2))
    for s in out["steps"]:
        t, st = s["test"], s["stress"]
        print(f"{s['step']:38s} recall {t['member_recall']:.2f} prec {t['member_precision']:.2f} "
              f"F1 {t['member_f1']:.2f} false {t['false_members']:4d} linkP {t['link_precision']:.2f} "
              f"AUC {t['auc']:.3f} | stress F1 {st['member_f1']:.2f} recall {st['member_recall']:.2f}")


if __name__ == "__main__":
    main()
