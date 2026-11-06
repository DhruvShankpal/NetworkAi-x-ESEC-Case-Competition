"""Shared plumbing for Series Desk MCP servers: read-only DB, audit-on-every-call."""
from __future__ import annotations

import functools
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seriesdesk.audit import AuditWriter, make_event  # noqa: E402
from seriesdesk.db import connect, load_env  # noqa: E402

load_env()
_writer: AuditWriter | None = None


def ro():
    """Connection as sd_readonly (SELECT on views only, read-only transactions)."""
    return connect("SD_READONLY_DSN", autocommit=True)


def audit(server: str):
    """Decorator: every tool call writes one audit row (args + result count), success or failure."""
    def deco(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            global _writer
            _writer = _writer or AuditWriter(os.environ["SD_AUDIT_DSN"])
            try:
                out = fn(*args, **kwargs)
            except Exception as e:
                _writer.append(make_event(os.environ.get("SD_ACTOR", "agent:unknown"), "agent",
                                          tool=f"{server}.{fn.__name__}", args=kwargs,
                                          action_taken=f"error:{type(e).__name__}"))
                raise
            n = len(out) if isinstance(out, list) else (0 if out is None else 1)
            _writer.append(make_event(os.environ.get("SD_ACTOR", "agent:unknown"), "agent",
                                      tool=f"{server}.{fn.__name__}", args=kwargs, result_count=n,
                                      action_taken="read"))
            return out
        return inner
    return deco


def parse_day(s: str) -> date:
    return date.fromisoformat(s)
