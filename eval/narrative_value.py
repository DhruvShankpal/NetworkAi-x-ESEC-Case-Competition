"""How much is narrative detail worth? Sensitivity analysis on REAL LA data.

LAPD Mocodes are coarse (median 3-4 codes, the top codes on most burglaries). Narratives hold finer detail
(exact tool, entry technique, specific items taken, offender behaviour). We add k such detail fields per
case and ask how much the detective-facing metric (hit@3) improves.

Model of a detail field (assumptions, stated):
  * each field has 20 possible values with a skewed (Zipf-like) frequency, like real MO vocabularies;
  * a serial offender has one usual value per field;
  * a case's narrative yields that field with probability r (offender consistency x officer wrote it down
    x extractor got it right), and when it is captured it is the offender's usual value 85% of the time;
  * unrelated cases get values from the same frequency distribution, also captured with probability r.
Model: the L2 configuration (rarity-weighted MO + closest-neighbour ranks). Train 2022, test 2023.
Run: uv run python eval/narrative_value.py
"""
from __future__ import annotations

import json
import pickle
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

from final_la import CACHE, top_k  # noqa: E402
from improve import fit  # noqa: E402
from improve_la import LA22, LA23  # noqa: E402
from seriesdesk.features import mo_tokens, rarity_weights, weighted_jaccard  # noqa: E402
from seriesdesk.ranking import rank_features  # noqa: E402
from seriesdesk.synth_real import generate_real, load_lapd  # noqa: E402

V = 20
ZIPF = np.array([1 / (k + 1) for k in range(V)]); ZIPF = ZIPF / ZIPF.sum()
COLS = [0, 1, 5, 3, 4, 6, 7]


def augment(ds, base_tokens, k, r, seed):
    """Return a copy of ds.X with MO columns recomputed after adding k narrative detail fields."""
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    usual = {}
    toks = []
    for cid, base in zip(ds["ids"], base_tokens):
        off = ds["key"][cid]["offender_id"]
        is_series = ds["key"][cid]["true_series_id"] is not None
        t = set(base)
        for f in range(k):
            if rng.random() >= r:
                continue  # not captured for this case
            if is_series:
                u = usual.setdefault((off, f), int(nrng.choice(V, p=ZIPF)))
                v = u if rng.random() < 0.85 else int(nrng.choice(V, p=ZIPF))
            else:
                v = int(nrng.choice(V, p=ZIPF))
            t.add(f"nd:{f}:{v}")
        toks.append(t)
    w = rarity_weights(toks)
    X = ds["X"].copy()
    X[:, 5] = [weighted_jaccard(toks[i], toks[j], w) for i, j in zip(ds["I"], ds["J"])]
    rk = rank_features(ds["I"], ds["J"], np.expm1(X[:, 0]), np.expm1(X[:, 1]), X[:, 5], len(ds["ids"]))
    X[:, 7] = rk[:, 1]
    return X


def main():
    d = pickle.loads(CACHE.read_bytes())
    r22, r23 = load_lapd(LA22), load_lapd(LA23)
    regen = {"train0": generate_real(r22, 20261106), "train1": generate_real(r22, 11), "test": generate_real(r23, 777)}
    base = {name: [mo_tokens(i["mo"]) for i in g.incidents] for name, g in regen.items()}
    for name, ds in (("train0", d["train"][0]), ("train1", d["train"][1]), ("test", d["test"])):
        assert [i["case_id"] for i in regen[name].incidents] == ds["ids"], "cache/regen mismatch"
    results = []
    for k, r in [(0, 0.0), (1, 0.5), (2, 0.5), (3, 0.5), (1, 0.8), (2, 0.8), (3, 0.8)]:
        Xs = [augment(d["train"][0], base["train0"], k, r, 1), augment(d["train"][1], base["train1"], k, r, 2)]
        m = fit(Xs, [d["train"][0]["y"], d["train"][1]["y"]], COLS)
        Xt = augment(d["test"], base["test"], k, r, 3)
        p = m.predict_proba(Xt[:, COLS])[:, 1]
        tk = top_k({**d["test"], "X": Xt}, p)
        order = np.argsort(-p)
        row = {"detail_fields": k, "capture_rate": r, "hit_at_3": round(tk["hit_at_3"], 3),
               "hit_at_1": round(top_k({**d["test"], "X": Xt}, p, k=1)["hit_at_1"], 3),
               "top3_precision": round(tk["precision_of_top3_suggestions"], 4),
               "precision_at_100": round(float(d["test"]["y"][order[:100]].mean()), 2)}
        results.append(row)
        print(row, flush=True)
    (ROOT / "eval/narrative_value_report.json").write_text(json.dumps(
        {"method": __doc__.strip(), "results": results}, indent=2))


if __name__ == "__main__":
    main()
