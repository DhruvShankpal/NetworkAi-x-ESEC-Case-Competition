"""SPD Crime Data (Socrata tazs-3rd5) pager. Plain httpx, no sodapy.

Field names verified against columns.json on 2026-11-06:
report_number, report_date_time, offense_id, offense_date, nibrs_offense_code ('220' = burglary),
nibrs_offense_code_description, block_address, latitude/longitude (TEXT), beat, precinct, sector,
neighborhood, reporting_area. There is no narrative field.
"""
from __future__ import annotations

import hashlib
import os
import time
from datetime import date, datetime
from typing import Any, Iterator

import httpx

BASE = "https://data.seattle.gov/resource/tazs-3rd5.json"
PAGE = 50_000


def fetch(where: str, order: str = "offense_id", page: int = PAGE, max_rows: int | None = None,
          token: str | None = None, client: httpx.Client | None = None) -> Iterator[dict[str, Any]]:
    token = token if token is not None else os.environ.get("SOCRATA_APP_TOKEN") or None
    headers = {"X-App-Token": token} if token else {}
    own = client is None
    client = client or httpx.Client(timeout=60)
    offset = got = 0
    try:
        while True:
            params = {"$where": where, "$order": order, "$limit": page, "$offset": offset}
            for attempt in range(4):
                r = client.get(BASE, params=params, headers=headers)
                if r.status_code in (429, 500, 502, 503) and attempt < 3:
                    time.sleep(2 ** (attempt + 1)); continue
                r.raise_for_status(); break
            rows = r.json()
            for row in rows:
                yield row
                got += 1
                if max_rows and got >= max_rows:
                    return
            if len(rows) < page:
                return
            offset += page
    finally:
        if own:
            client.close()


def burglary_where(start: date, end: date) -> str:
    return (f"nibrs_offense_code='220' AND offense_date between "
            f"'{start:%Y-%m-%d}T00:00:00' and '{end:%Y-%m-%d}T23:59:59'")


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v not in (0.0, -1.0) else None


def to_incident(row: dict[str, Any], salt: str) -> dict[str, Any] | None:
    """Normalize one SODA row. Report numbers are salted-hashed, never stored raw.
    Rows without usable coordinates are dropped (returned None) and should be counted."""
    lat, lon = _f(row.get("latitude")), _f(row.get("longitude"))
    if lat is None or lon is None or not row.get("offense_date"):
        return None
    od = datetime.fromisoformat(row["offense_date"])
    rd = datetime.fromisoformat(row["report_date_time"]) if row.get("report_date_time") else od
    return {
        "case_id": f"SPD-{row['offense_id']}",
        "source": "spd_open",
        "report_number_hash": hashlib.sha256((salt + row.get("report_number", "")).encode()).hexdigest(),
        "offense_start": od, "offense_end": od, "reported_at": rd,
        "nibrs_code": row.get("nibrs_offense_code"), "nibrs_desc": row.get("nibrs_offense_code_description"),
        "beat": row.get("beat"), "sector": row.get("sector"), "precinct": row.get("precinct"),
        "mcpp": row.get("neighborhood"),
        "lat": lat, "lon": lon, "replay_visible_on": rd.date(),
    }


def load_backdrop(path) -> list[dict[str, Any]]:
    """Read a pull_spd.py JSONL file into backdrop rows for synth.SynthConfig(backdrop=...)."""
    import json
    out = []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            out.append({"lat": r["lat"], "lon": r["lon"],
                        "offense_start": datetime.fromisoformat(r["offense_start"]),
                        "reported_at": datetime.fromisoformat(r["reported_at"])})
    return out
