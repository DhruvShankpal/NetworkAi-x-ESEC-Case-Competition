"""Pull SPD burglaries (NIBRS 220) for a window to data/spd/*.jsonl. Public data, no narratives."""
import argparse, json, os, secrets, sys
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "backend"))
from seriesdesk.db import load_env
from seriesdesk.soda import burglary_where, fetch, to_incident

load_env()
ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2018-04-01"); ap.add_argument("--end", default="2018-11-30")
a = ap.parse_args()
salt = os.environ.get("SD_HASH_SALT") or secrets.token_hex(16)
out = ROOT / "data/spd"; out.mkdir(parents=True, exist_ok=True)
path = out / f"spd_220_{a.start}_{a.end}.jsonl"
kept = dropped = 0
with path.open("w") as f:
    for row in fetch(burglary_where(date.fromisoformat(a.start), date.fromisoformat(a.end))):
        inc = to_incident(row, salt)
        if inc is None:
            dropped += 1; continue
        kept += 1; f.write(json.dumps(inc, default=str) + "\n")
print(f"{path.relative_to(ROOT)}: kept {kept}, dropped {dropped} (no usable coordinates/date)")
