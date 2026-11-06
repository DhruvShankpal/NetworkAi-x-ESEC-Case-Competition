"""Generate a seeded synthetic dataset and load it into app.* (sd_app role).

The MO features loaded here are the generator's TRUTH (model_id='synthetic-truth'),
so the replay UI can run before the extractor exists. Run the extractor to replace them.
Synthetic labels go to data/synthetic/ (never the DB). Blind data never goes through here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from psycopg.types.json import Jsonb  # noqa: E402

from seriesdesk.db import connect  # noqa: E402
from seriesdesk.linkage import LinkageModel  # noqa: E402
from seriesdesk.pipeline import score_pairs  # noqa: E402
from seriesdesk.synth import SynthConfig, generate  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=777)
    ap.add_argument("--model", default=str(ROOT / "eval/models/lr-v1.json"))
    args = ap.parse_args()
    ds = generate(SynthConfig(seed=args.seed))
    dataset_id = f"synthetic-{args.seed}"
    out = ROOT / "data/synthetic"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"synthetic_labels_{args.seed}.jsonl", "w") as f:
        f.write(json.dumps({"_meta": ds.meta}) + "\n")
        for k in ds.answer_key:
            f.write(json.dumps(k) + "\n")

    model = LinkageModel.from_json(Path(args.model).read_text())
    pairs = score_pairs(model, ds.incidents)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from app.pair_scores where case_a in (select case_id from app.incidents where dataset_id=%s)", (dataset_id,))
        cur.execute("delete from app.mo_features where case_id in (select case_id from app.incidents where dataset_id=%s)", (dataset_id,))
        cur.execute("delete from app.incidents where dataset_id=%s", (dataset_id,))
        cur.execute("insert into app.datasets (dataset_id, seed, generator_sha, meta) values (%s,%s,%s,%s) "
                    "on conflict (dataset_id) do update set meta=excluded.meta",
                    (dataset_id, args.seed, ds.meta["generator_sha"], Jsonb(ds.meta)))
        with cur.copy("copy app.incidents (case_id, source, dataset_id, offense_start, offense_end, reported_at, "
                      "nibrs_code, nibrs_desc, district_fictional, geom, narrative, narrative_origin, replay_visible_on) from stdin") as cp:
            for i in ds.incidents:
                cp.write_row((i["case_id"], "synthetic", dataset_id, i["offense_start"], i["offense_end"], i["reported_at"],
                              i["nibrs_code"], i["nibrs_desc"], i["district_fictional"],
                              f"SRID=4326;POINT({i['lon']} {i['lat']})", i["narrative"], i["narrative_origin"],
                              i["replay_visible_on"]))
        with cur.copy("copy app.mo_features (case_id, features, evidence_spans, model_id, prompt_version, schema_version) from stdin") as cp:
            for i in ds.incidents:
                cp.write_row((i["case_id"], json.dumps(i["mo"]), json.dumps(i["evidence_spans"]),
                              "synthetic-truth", "n/a", "mo-v1"))
        with cur.copy("copy app.pair_scores (case_a, case_b, block, distance_km, days_apart, mo_jaccard, prob, contributions, model_version) from stdin") as cp:
            for p in pairs:
                cp.write_row((p["case_a"], p["case_b"], p["block"], p["distance_km"], p["days_apart"], p["mo_jaccard"],
                              p["prob"], json.dumps(p["contributions"]), p["model_version"]))
    print(f"loaded {len(ds.incidents)} incidents, {len(pairs)} scored pairs into {dataset_id}")


if __name__ == "__main__":
    main()
