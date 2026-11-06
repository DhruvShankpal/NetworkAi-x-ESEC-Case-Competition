"""Thin psycopg helpers. DSNs always come from the environment (.env)."""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | Path | None = None) -> None:
    p = Path(path) if path else Path(__file__).resolve().parents[2] / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def connect(var: str = "DATABASE_URL", **kw):
    import psycopg
    from psycopg.rows import dict_row
    load_env()
    return psycopg.connect(os.environ[var], row_factory=dict_row, **kw)
