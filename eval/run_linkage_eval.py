"""Train on one synthetic seed, evaluate on a different held-out seed.

Every number printed here is labelled SYNTHETIC. It is not an effectiveness claim.
Usage: uv run python eval/run_linkage_eval.py [--train-seed N] [--test-seed M]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import numpy as np
from sklearn.metrics import roc_auc_score

from seriesdesk.blocking import BlockingConfig
from seriesdesk.linkage import LinkageModel
from seriesdesk.pipeline import labelled_pairs, true_pair_count
from seriesdesk.series import build_series
from seriesdesk.synth import SynthConfig, generate

ROOT = Path(__file__).resolve().parent


def bootstrap_auc(y, p, n=1000, seed=0):
    rng = np.random.default_rng(seed)
    y, p = np.asarray(y), np.asarray(p)
    vals = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        if y[idx].min() != y[idx].max():
            vals.append(roc_auc_score(y[idx], p[idx]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-seed", type=int, default=20261106)
    ap.add_argument("--test-seed", type=int, default=777)
    ap.add_argument("--threshold", type=float, default=0.3)
    ap.add_argument("--train-backdrop", help="SPD jsonl for the training set (default: uniform noise)")
    ap.add_argument("--test-backdrop", help="SPD jsonl for the test set (default: uniform noise)")
    args = ap.parse_args()
    cfg = BlockingConfig()

    from seriesdesk.soda import load_backdrop
    bd = lambda p: load_backdrop(p) if p else None  # noqa: E731
    train = generate(SynthConfig(seed=args.train_seed, backdrop=bd(args.train_backdrop)))
    tkey = {k["case_id"]: k for k in train.answer_key}
    _, raws, y = labelled_pairs(train.incidents, tkey, cfg)
    model = LinkageModel.fit(raws, y, version="lr-v1")
    (ROOT / "models" / "lr-v1.json").write_text(model.to_json())

    test = generate(SynthConfig(seed=args.test_seed, backdrop=bd(args.test_backdrop)))
    key = {k["case_id"]: k for k in test.answer_key}
    pairs, raws_t, y_t = labelled_pairs(test.incidents, key, cfg)
    p = model.score_many(raws_t)
    auc = roc_auc_score(y_t, p)
    lo, hi = bootstrap_auc(y_t, p)

    total_true = true_pair_count(key)
    kept_true = int(sum(y_t))
    order = np.argsort(-p)
    prec = {k: float(np.mean(np.asarray(y_t)[order[:k]])) for k in (10, 25, 50, 100)}

    # Series-member recall at threshold (no human decisions: model-only upper/lower bound)
    comps = build_series([{"case_a": a, "case_b": b, "prob": pr, "decision": None}
                          for (a, b, _), pr in zip(pairs, p)], args.threshold)
    members = defaultdict(set)
    for cid, k in key.items():
        if k["true_series_id"]:
            members[k["true_series_id"]].add(cid)
    per_series = {}
    for sid, mem in sorted(members.items()):
        best = max((len(mem & c) for c in comps), default=0)
        per_series[sid] = f"{best}/{len(mem)}"
    flagged = {c for comp in comps for c in comp}
    decoy_ids = {cid for cid, k in key.items() if k["is_decoy"]}
    noise_in_series = sum(1 for c in flagged if not key[c]["true_series_id"])

    report = {
        "data_source": "SYNTHETIC MO/narratives/series; space-time backdrop: "
                       f"train={args.train_backdrop or 'uniform'}, test={args.test_backdrop or 'uniform'}",
        "train_seed": args.train_seed, "test_seed": args.test_seed,
        "model_sha256": model.sha256(),
        "coef": dict(zip(model.features, [round(c, 3) for c in model.coef])),
        "intercept": round(model.intercept, 3),
        "candidate_pairs": len(y_t), "true_pairs_total": total_true, "true_pairs_in_candidates": kept_true,
        "blocking_recall_loss": round(1 - kept_true / total_true, 4),
        "auc": round(auc, 4), "auc_95ci": [round(lo, 4), round(hi, 4)],
        "precision_at_k": prec,
        "threshold": args.threshold,
        "series_member_recall_best_component": per_series,
        "non_series_cases_in_flagged_components": noise_in_series,
        "decoy_cases_flagged": len(flagged & decoy_ids), "decoy_cases_total": len(decoy_ids),
    }
    (ROOT / "linkage_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
