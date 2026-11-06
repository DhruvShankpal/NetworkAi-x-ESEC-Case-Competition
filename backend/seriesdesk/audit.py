"""Append-only audit log with a SHA-256 hash chain for tamper evidence.

row_hash = sha256(prev_hash || canonical_json(row_without_hashes)).
The DB enforces append-only via grants + trigger; the chain lets anyone verify
after the fact that no row was edited, removed, or reordered.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

GENESIS = b"\x00" * 32
HASHED_FIELDS = ("event_id", "ts", "actor", "actor_type", "tool", "args", "result_count",
                 "fact_source", "inferred", "human_checked", "action_taken")


def _norm_ts(ts: Any) -> str:
    """Fixed-width UTC timestamp so Python- and Postgres-rendered values hash identically."""
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return ts.astimezone(timezone.utc).isoformat(timespec="microseconds")


def canonical(row: Mapping[str, Any]) -> bytes:
    body = {k: row.get(k) for k in HASHED_FIELDS}
    body["ts"] = _norm_ts(body["ts"])
    body["event_id"] = str(body["event_id"])
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()


def chain_hash(prev_hash: bytes, row: Mapping[str, Any]) -> bytes:
    return hashlib.sha256(prev_hash + canonical(row)).digest()


def make_event(actor: str, actor_type: str, tool: str | None = None, args: Any = None,
               result_count: int | None = None, action_taken: str | None = None,
               **extra: Any) -> dict[str, Any]:
    if actor_type not in ("human", "agent", "system"):
        raise ValueError(actor_type)
    return {"event_id": str(uuid.uuid4()), "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor, "actor_type": actor_type, "tool": tool, "args": args,
            "result_count": result_count, "action_taken": action_taken,
            "fact_source": extra.get("fact_source"), "inferred": extra.get("inferred"),
            "human_checked": extra.get("human_checked")}


def verify_chain(rows: Iterable[Mapping[str, Any]]) -> tuple[bool, int | None]:
    """Rows in seq order with prev_hash/row_hash bytes. Returns (ok, first_bad_index)."""
    prev = GENESIS
    for k, r in enumerate(rows):
        if bytes(r["prev_hash"]) != prev or bytes(r["row_hash"]) != chain_hash(prev, r):
            return False, k
        prev = bytes(r["row_hash"])
    return True, None


class AuditWriter:
    """Writes through the INSERT-only sd_audit_writer role. Serializes appends with an
    advisory lock so the chain stays linear under concurrency."""

    LOCK_KEY = 0x5D_A0D1

    def __init__(self, dsn: str):
        import psycopg
        self._conn = psycopg.connect(dsn, autocommit=False)

    def append(self, event: Mapping[str, Any]) -> int:
        from psycopg.types.json import Jsonb
        with self._conn.cursor() as cur:
            cur.execute("select pg_advisory_xact_lock(%s)", (self.LOCK_KEY,))
            cur.execute("select audit.last_hash()")
            prev = bytes(cur.fetchone()[0] or GENESIS)
            rh = chain_hash(prev, event)
            cur.execute(
                """insert into audit.audit_log (event_id, ts, actor, actor_type, tool, args, result_count,
                       fact_source, inferred, human_checked, action_taken, prev_hash, row_hash)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (event["event_id"], event["ts"], event["actor"], event["actor_type"], event.get("tool"),
                 Jsonb(event.get("args")), event.get("result_count"), Jsonb(event.get("fact_source")),
                 Jsonb(event.get("inferred")), Jsonb(event.get("human_checked")),
                 event.get("action_taken"), prev, rh))
            cur.execute("select currval('audit.audit_log_seq_seq')")  # writer has no SELECT on the table
            seq = cur.fetchone()[0]
        self._conn.commit()
        return seq
