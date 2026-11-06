"""notify — queue a notification ONLY for a link a human has already accepted.
Prototype: writes an audit event + outbox line; it sends nothing externally."""
import json
import os
from pathlib import Path

from _common import AuditWriter, make_event
from fastmcp import FastMCP

from seriesdesk.db import connect

mcp = FastMCP("notify")
OUTBOX = Path(__file__).resolve().parents[2] / "data" / "outbox.jsonl"
_w = None


@mcp.tool
def queue_notification(decision_id: str, recipient_role: str, message: str) -> dict:
    """recipient_role in {'case_detective','sergeant'}. Refuses unless decision_id is a human 'accept'."""
    global _w
    if recipient_role not in ("case_detective", "sergeant"):
        raise ValueError("recipient_role must be case_detective or sergeant")
    with connect("DATABASE_URL") as c:
        row = c.execute("select decision, decided_by from app.link_decisions where decision_id=%s",
                        (decision_id,)).fetchone()
    if not row or row["decision"] != "accept":
        raise PermissionError("notification requires a human-accepted link decision")
    _w = _w or AuditWriter(os.environ["SD_AUDIT_DSN"])
    seq = _w.append(make_event(os.environ.get("SD_ACTOR", "agent:unknown"), "agent", tool="notify.queue",
                               args={"decision_id": decision_id, "recipient_role": recipient_role},
                               human_checked=[row["decided_by"]], action_taken="notification_queued"))
    with OUTBOX.open("a") as f:
        f.write(json.dumps({"seq": seq, "decision_id": decision_id, "to": recipient_role, "message": message[:1000]}) + "\n")
    return {"queued": True, "audit_seq": seq}


if __name__ == "__main__":
    mcp.run()
