"""Write eval/thresholds.json and print its SHA-256. Commit both BEFORE the blind session."""
import hashlib, json, sys
from dataclasses import asdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "backend"))
from seriesdesk.blocking import BlockingConfig
from seriesdesk.linkage import LinkageModel

model = LinkageModel.from_json((ROOT / "eval/models/lr-v1.json").read_text())
doc = {"blocking": asdict(BlockingConfig()), "link_threshold": 0.3, "series_min_size": 2,
       "model_version": model.version, "model_sha256": model.sha256()}
body = json.dumps(doc, sort_keys=True, indent=2)
(ROOT / "eval/thresholds.json").write_text(body + "\n")
print(hashlib.sha256((body + "\n").encode()).hexdigest())
