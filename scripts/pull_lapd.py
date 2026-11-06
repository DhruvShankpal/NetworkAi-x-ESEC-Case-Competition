"""Pull LAPD burglaries (crm_cd 310) with real MO codes from data.lacity.org (2nrs-mtv8, 2020–2024).
Fetches ONLY the fields the model uses: no victim age/sex/descent, no address text.
Report numbers are salted-hashed. Output: data/lapd/lapd_310_<start>_<end>.jsonl"""
import argparse, hashlib, json, os, secrets, sys, time
from datetime import datetime
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://data.lacity.org/resource/2nrs-mtv8.json"
FIELDS = "dr_no,date_rptd,date_occ,time_occ,crm_cd,mocodes,premis_cd,premis_desc,weapon_used_cd,status,lat,lon"
RESIDENTIAL = ("DWELLING", "RESIDENCE", "HOUSE", "APARTMENT", "CONDO", "MOBILE HOME", "GARAGE/CARPORT", "YARD", "PORCH")


def target_type(premis_desc: str | None) -> str | None:
    if not premis_desc:
        return None
    return "residential" if any(k in premis_desc.upper() for k in RESIDENTIAL) else "commercial"


def to_row(r: dict, salt: str) -> dict | None:
    try:
        lat, lon = float(r["lat"]), float(r["lon"])
    except (KeyError, ValueError):
        return None
    if lat == 0 or lon == 0 or not r.get("date_occ"):
        return None
    t = (r.get("time_occ") or "0000").zfill(4)
    occ = datetime.fromisoformat(r["date_occ"][:10]).replace(hour=int(t[:2]) % 24, minute=int(t[2:]) % 60)
    rptd = datetime.fromisoformat(r["date_rptd"][:10]) if r.get("date_rptd") else occ
    codes = sorted(set((r.get("mocodes") or "").split()))
    return {"case_id": "LA-" + hashlib.sha256((salt + r["dr_no"]).encode()).hexdigest()[:12],
            "lat": lat, "lon": lon, "offense_start": occ.isoformat(), "reported_at": max(rptd, occ).isoformat(),
            "mo_codes": codes, "premise": r.get("premis_cd"), "premise_desc": r.get("premis_desc"),
            "target_type": target_type(r.get("premis_desc")), "weapon": r.get("weapon_used_cd"),
            "status": r.get("status")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2022-04-01"); ap.add_argument("--end", default="2022-11-30")
    a = ap.parse_args()
    salt = os.environ.get("SD_HASH_SALT") or secrets.token_hex(16)
    where = f"crm_cd='310' AND date_occ between '{a.start}T00:00:00' and '{a.end}T23:59:59'"
    out = ROOT / "data/lapd"; out.mkdir(parents=True, exist_ok=True)
    path = out / f"lapd_310_{a.start}_{a.end}.jsonl"
    kept = dropped = offset = 0
    with httpx.Client(timeout=120) as c, path.open("w") as f:
        while True:
            for attempt in range(4):
                resp = c.get(BASE, params={"$select": FIELDS, "$where": where, "$order": "dr_no",
                                           "$limit": 50000, "$offset": offset})
                if resp.status_code >= 500 and attempt < 3:
                    time.sleep(2 ** (attempt + 1)); continue
                resp.raise_for_status(); break
            rows = resp.json()
            for r in rows:
                x = to_row(r, salt)
                if x is None:
                    dropped += 1; continue
                kept += 1; f.write(json.dumps(x) + "\n")
            if len(rows) < 50000:
                break
            offset += 50000
    print(f"{path.relative_to(ROOT)}: kept {kept}, dropped {dropped}")


if __name__ == "__main__":
    main()
