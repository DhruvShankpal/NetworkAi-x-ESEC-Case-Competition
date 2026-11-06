"""geo — distances and radius lookups (haversine on the same lat/lon the linkage engine uses)."""
from _common import audit, parse_day, ro
from fastmcp import FastMCP

from seriesdesk.features import haversine_km

mcp = FastMCP("geo")


@mcp.tool
@audit("geo")
def distance(case_a: str, case_b: str, replay_date: str) -> dict | None:
    """Great-circle distance in km between two visible cases."""
    with ro() as c:
        rows = c.execute("select case_id, lat, lon from app.v_cases where case_id = any(%s) and replay_visible_on <= %s",
                         ([case_a, case_b], parse_day(replay_date))).fetchall()
    if len(rows) != 2:
        return None
    return {"case_a": case_a, "case_b": case_b,
            "distance_km": round(haversine_km(rows[0]["lat"], rows[0]["lon"], rows[1]["lat"], rows[1]["lon"]), 3)}


@mcp.tool
@audit("geo")
def within(case_id: str, km: float, replay_date: str, limit: int = 100) -> list[dict]:
    """Visible cases within `km` (max 60) of a case, nearest first."""
    km = min(max(km, 0.0), 60.0)
    with ro() as c:
        return c.execute(
            "select o.case_id, o.offense_start, "
            "round((st_distance(st_makepoint(o.lon,o.lat)::geography, st_makepoint(x.lon,x.lat)::geography)/1000)::numeric,3) km "
            "from app.v_cases x join app.v_cases o on o.case_id <> x.case_id and o.replay_visible_on <= %(d)s "
            "where x.case_id=%(c)s and x.replay_visible_on <= %(d)s "
            "and st_dwithin(st_makepoint(o.lon,o.lat)::geography, st_makepoint(x.lon,x.lat)::geography, %(m)s) "
            "order by km limit %(l)s",
            {"c": case_id, "d": parse_day(replay_date), "m": km * 1000, "l": min(max(limit, 1), 500)}).fetchall()


if __name__ == "__main__":
    mcp.run()
