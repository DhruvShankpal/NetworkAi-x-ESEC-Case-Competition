"""Exercise MCP tools in-process via FastMCP's client. Requires the local DB with synthetic-777 loaded."""
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

SRV = Path(__file__).resolve().parents[1] / "backend" / "mcp_servers"
sys.path.insert(0, str(SRV))


def load(name):
    spec = importlib.util.spec_from_file_location(f"mcp_{name}", SRV / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m.mcp


def call(server, tool, **args):
    from fastmcp import Client
    async def go():
        async with Client(server) as c:
            return await c.call_tool(tool, args)
    return asyncio.run(go())


def _audit_count():
    import subprocess
    return int(subprocess.check_output(["sudo", "-u", "postgres", "psql", "-d", "seriesdesk", "-Atc",
                                        "select count(*) from audit.audit_log"], text=True))


@pytest.fixture(scope="module")
def some_case():
    from seriesdesk.db import connect
    with connect("SD_READONLY_DSN") as c:
        r = c.execute("select case_id, replay_visible_on from app.v_cases order by replay_visible_on limit 1").fetchone()
    if not r:
        pytest.skip("no data loaded")
    return r


def test_tools_listed():
    from fastmcp import Client
    async def go():
        async with Client(load("rms_readonly")) as c:
            return {t.name for t in await c.list_tools()}
    assert asyncio.run(go()) == {"get_case", "search_cases"}


def test_get_case_respects_replay_clock_and_audits(some_case):
    before = _audit_count()
    srv = load("rms_readonly")
    seen = call(srv, "get_case", case_id=some_case["case_id"], replay_date=str(some_case["replay_visible_on"]))
    assert seen.structured_content["result"]["case_id"] == some_case["case_id"]
    hidden = call(srv, "get_case", case_id=some_case["case_id"], replay_date="2000-01-01")
    assert hidden.structured_content["result"] is None
    assert _audit_count() == before + 2


def test_linkage_top_pairs():
    r = call(load("linkage"), "top_pairs", replay_date="2019-12-31", min_prob=0.9, limit=5)
    rows = r.structured_content["result"]
    assert 0 < len(rows) <= 5 and all(x["prob"] >= 0.9 for x in rows)


def test_notify_refuses_without_accept():
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError):
        call(load("notify"), "queue_notification", decision_id="00000000-0000-0000-0000-000000000000",
             recipient_role="sergeant", message="x")
