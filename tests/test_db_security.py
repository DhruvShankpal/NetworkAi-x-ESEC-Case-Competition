"""Integration tests against the local Postgres. Skipped if the DB isn't reachable.
These check the guarantees the spec puts in the DATABASE, not the MCP layer."""
import os
import pytest

psycopg = pytest.importorskip("psycopg")
from seriesdesk.db import load_env
from seriesdesk.audit import AuditWriter, make_event, verify_chain

load_env()


def _conn(var):
    try:
        return psycopg.connect(os.environ[var], autocommit=True)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"db unavailable: {e}")


def test_readonly_can_read_views():
    with _conn("SD_READONLY_DSN") as c:
        assert c.execute("select count(*) from app.v_cases").fetchone()[0] > 0


@pytest.mark.parametrize("sql", [
    "insert into app.incidents (case_id, source, replay_visible_on) values ('X-1','synthetic','2018-01-01')",
    "select * from app.incidents limit 1",                 # base table, not view
    "select * from audit.audit_log limit 1",
    "select pg_read_file('/etc/passwd')",                  # the CVE-style bypass
    "copy (select 1) to '/tmp/x'",
    "create table app.evil (x int)",
    "set transaction read write; update app.incidents set narrative='x'",
])
def test_readonly_blocked(sql):
    with _conn("SD_READONLY_DSN") as c:
        with pytest.raises(psycopg.Error):
            c.execute(sql)


def test_readonly_cannot_connect_to_sealed_db():
    dsn = os.environ["SD_READONLY_DSN"].rsplit("/", 1)[0] + "/sealed_db"
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(dsn)


def test_app_cannot_connect_to_sealed_db():
    dsn = os.environ["DATABASE_URL"].rsplit("/", 1)[0] + "/sealed_db"
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(dsn)


def test_audit_writer_insert_only_and_chain_valid():
    w = AuditWriter(os.environ["SD_AUDIT_DSN"])
    seq = w.append(make_event("pytest", "system", tool="test", args={"k": 1}))
    assert seq > 0
    with _conn("SD_AUDIT_DSN") as c:
        for sql in ["select * from audit.audit_log", f"update audit.audit_log set actor='x' where seq={seq}",
                    f"delete from audit.audit_log where seq={seq}"]:
            with pytest.raises(psycopg.Error):
                c.execute(sql)


def test_app_role_cannot_touch_audit_and_trigger_blocks_owner():
    with _conn("DATABASE_URL") as c:
        with pytest.raises(psycopg.Error):
            c.execute("delete from audit.audit_log")


def test_chain_verifies_end_to_end():
    from psycopg.rows import dict_row
    import subprocess, json
    out = subprocess.run(["sudo", "-u", "postgres", "psql", "-d", "seriesdesk", "-Atc",
                          "select json_agg(t order by seq) from (select seq, event_id, ts, actor, actor_type, tool, args, "
                          "result_count, fact_source, inferred, human_checked, action_taken, "
                          "encode(prev_hash,'hex') prev_hash, encode(row_hash,'hex') row_hash from audit.audit_log) t"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("no superuser psql")
    rows = json.loads(out.stdout.strip() or "null") or []
    for r in rows:
        r["prev_hash"], r["row_hash"] = bytes.fromhex(r["prev_hash"]), bytes.fromhex(r["row_hash"])
    assert rows and verify_chain(rows) == (True, None)
