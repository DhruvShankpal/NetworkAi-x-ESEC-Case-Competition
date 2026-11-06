"""Leave-one-year-out test on REAL LA data, 2020-2023 (Apr-Nov each year).

For each test year Y: train on the OTHER three years (one synthetic-series seed per year), test on Y.
2020 is the COVID year (very different burglary mix), so it is the hardest generalization check.
2024 is excluded: LAPD's move to NIBRS in March 2024 leaves only ~1,000 records in the window.
Models compared every year:
  baseline  = distance, time, plain MO overlap, same target, both night (the Seattle-style model)
  final     = rare-behaviour MO weighting + closest-neighbour ranks + same-event merge
Run: uv run python eval/multiyear.py
"""
from __future__ import annotations

import json
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

YEARS = [2020, 2021, 2022, 2023]
TRAIN_SEED, TEST_SEED = 11, 777


def path(y):
    return ROOT / f"data/lapd/lapd_310_{y}-04-01_{y}-11-30.jsonl"


def cached_build(args):
    y, seed = args
    cache = ROOT / f"data/lapd/cache_{y}_{seed}.pkl"
    if not cache.exists():
        from improve_la import build
        from seriesdesk.synth_real import load_lapd
        cache.write_bytes(pickle.dumps(build(load_lapd(path(y)), seed)))
    return str(cache)


def main():
    from improve import fit
    from linker_v2 import COLS, metrics, same_event
    jobs = [(y, s) for y in YEARS for s in (TRAIN_SEED, TEST_SEED)]
    with ProcessPoolExecutor(max_workers=4) as ex:
        paths = dict(zip(jobs, ex.map(cached_build, jobs)))
    load = lambda y, s: pickle.loads(Path(paths[(y, s)]).read_bytes())  # noqa: E731
    BASE = [0, 1, 2, 3, 4]
    rows = []
    for y in YEARS:
        tr = [load(o, TRAIN_SEED) for o in YEARS if o != y]
        te = load(y, TEST_SEED)
        row = {"test_year": y, "train_years": [o for o in YEARS if o != y],
               "cases": len(te["ids"]), "candidate_pairs": int(len(te["y"]))}
        for name, cols, merge in (("baseline", BASE, False), ("final", COLS, True)):
            keep = [~same_event(t) if merge else np.ones(len(t["y"]), bool) for t in tr]
            m = fit([t["X"][k] for t, k in zip(tr, keep)], [t["y"][k] for t, k in zip(tr, keep)], cols)
            mask = ~same_event(te) if merge else np.ones(len(te["y"]), bool)
            row[name] = metrics(te, m.predict_proba(te["X"][:, cols])[:, 1], mask)
        rows.append(row)
        print(json.dumps(row), flush=True)
        del tr, te
    summ = {}
    for name in ("baseline", "final"):
        for k in ("hit_at_1", "hit_at_3", "auc"):
            v = [r[name][k] for r in rows]
            summ[f"{name}_{k}"] = {"mean": round(float(np.mean(v)), 3), "min": min(v), "max": max(v)}
    out = {"method": __doc__.strip(), "rows": rows, "summary": summ}
    (ROOT / "eval/multiyear_report.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(summ, indent=2))


if __name__ == "__main__":
    main()
