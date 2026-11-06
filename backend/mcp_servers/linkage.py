"""linkage — read pre-computed pair scores and their exact per-feature contributions."""
from _common import audit, parse_day, ro
from fastmcp import FastMCP

mcp = FastMCP("linkage")
VIS = ("join app.v_cases a on a.case_id=p.case_a and a.replay_visible_on <= %(d)s "
       "join app.v_cases b on b.case_id=p.case_b and b.replay_visible_on <= %(d)s")


@mcp.tool
@audit("linkage")
def get_pair(case_a: str, case_b: str, replay_date: str) -> dict | None:
    """Score, features and log-odds contributions for one pair (order-insensitive)."""
    a, b = sorted((case_a, case_b))
    with ro() as c:
        return c.execute(f"select p.* from app.v_pair_scores p {VIS} where p.case_a=%(a)s and p.case_b=%(b)s "
                         "order by p.scored_at desc limit 1", {"a": a, "b": b, "d": parse_day(replay_date)}).fetchone()


@mcp.tool
@audit("linkage")
def top_pairs(replay_date: str, min_prob: float = 0.5, limit: int = 50) -> list[dict]:
    """Highest-probability candidate links among cases visible on replay_date."""
    with ro() as c:
        return c.execute(f"select p.case_a, p.case_b, p.block, p.prob, p.distance_km, p.days_apart, p.mo_jaccard, "
                         f"p.contributions from app.v_pair_scores p {VIS} where p.prob >= %(m)s "
                         "order by p.prob desc limit %(l)s",
                         {"d": parse_day(replay_date), "m": min_prob, "l": min(max(limit, 1), 200)}).fetchall()


if __name__ == "__main__":
    mcp.run()
