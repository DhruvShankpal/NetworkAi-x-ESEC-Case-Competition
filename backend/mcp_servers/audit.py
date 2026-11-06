"""audit — lets an agent record what it treated as fact vs inference. Append-only."""
import os

from _common import AuditWriter, make_event
from fastmcp import FastMCP

mcp = FastMCP("audit")
_w = None


@mcp.tool
def log(action: str, fact_source: list[dict] | None = None, inferred: list[str] | None = None,
        human_checked: list[str] | None = None) -> dict:
    """Append one audit event. fact_source = [{case_id, field}], inferred = statements not directly in a field."""
    global _w
    _w = _w or AuditWriter(os.environ["SD_AUDIT_DSN"])
    seq = _w.append(make_event(os.environ.get("SD_ACTOR", "agent:unknown"), "agent", tool="audit.log",
                               action_taken=action[:500], fact_source=fact_source, inferred=inferred,
                               human_checked=human_checked))
    return {"seq": seq}


if __name__ == "__main__":
    mcp.run()
