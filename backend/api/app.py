"""CaseWeb API (FastAPI). Serves the replay page.

Rules this file enforces:
- The replay clock: every read is filtered to cases with replay_visible_on <= the session's current day.
- No answer-key data exists in this database or in any response (labels live only in sealed_db / files).
- A human decides: links change only through POST /decisions, which requires a reason code.
- Every event is written to the append-only audit log with SERVER time.
Run: uv run uvicorn api.app:app --app-dir backend --port 8000
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from seriesdesk.audit import AuditWriter, make_event
from seriesdesk.db import connect, load_env
from seriesdesk.linkage import band
from seriesdesk.series import build_series

load_env()
app = FastAPI(title="CaseWeb API")
_audit: AuditWriter | None = None
THRESHOLD = float(os.environ.get("SD_LINK_THRESHOLD", "0.3"))
SERIES_SEED = 0.5  # undecided links at or above this form candidate series

REASONS = {
    "accept": ["A1_MO_SIGNATURE", "A2_SPACE_TIME", "A3_EVIDENCE_LINK"],
    "reject": ["R1_MO_MISMATCH", "R2_TOO_FAR", "R3_TIME_GAP", "R4_DIFFERENT_TARGET"],
    "defer": ["D1_NEED_MORE_INFO"],
}
FIELD_LABEL = {"entry_point": "Entry point", "entry_method": "Entry method", "tools": "Tools",
               "target_type": "Target", "property_categories": "Property taken", "occupancy": "Occupancy",
               "offender_count": "Offenders seen", "vehicle_mentioned": "Vehicle mentioned"}


def audit(actor: str, tool: str, args: Any, action: str, n: int | None = None) -> None:
    global _audit
    _audit = _audit or AuditWriter(os.environ["SD_AUDIT_DSN"])
    _audit.append(make_event(actor, "human" if actor.startswith("anon") else "system", tool=tool,
                             args=args, result_count=n, action_taken=action))


def ro():
    return connect("SD_READONLY_DSN", autocommit=True)


def rw():
    return connect("DATABASE_URL", autocommit=True)


# ---------------------------------------------------------------- sessions
class SessionIn(BaseModel):
    analyst: str = Field(pattern=r"^anon-[0-9]{1,3}$")


def _session(sid: str) -> dict:
    with rw() as c:
        s = c.execute("select * from app.replay_state where session_id=%s", (sid,)).fetchone()
    if not s:
        raise HTTPException(404, "Session not found. Start a new session.")
    return s


@app.post("/api/sessions/{sid}")
def start_session(sid: str, body: SessionIn) -> dict:
    with ro() as c:
        start = c.execute("select min(replay_visible_on) d from app.v_cases").fetchone()["d"]
    with rw() as c:
        created = c.execute("insert into app.replay_state (session_id, current_replay_date, start_date, analyst) "
                            "values (%s,%s,%s,%s) on conflict (session_id) do nothing returning session_id",
                            (sid, start, start, body.analyst)).fetchone()
    if created:  # resuming an existing session is not a new start
        audit(body.analyst, "session_start", {"session": sid, "day": str(start)}, "session_start")
    return session_view(sid)


@app.get("/api/sessions/{sid}")
def session_view(sid: str) -> dict:
    s = _session(sid)
    return {"session_id": sid, "analyst": s["analyst"], "day": str(s["current_replay_date"]),
            "day_number": (s["current_replay_date"] - s["start_date"]).days + 1,
            "ended": s["ended_at"] is not None}


class AdvanceIn(BaseModel):
    to: date


@app.post("/api/sessions/{sid}/day")
def set_day(sid: str, body: AdvanceIn) -> dict:
    s = _session(sid)
    if s["ended_at"]:
        raise HTTPException(409, "This session has ended.")
    if body.to < s["start_date"] or body.to > s["current_replay_date"] + timedelta(days=1):
        raise HTTPException(400, "You can go back, or forward one day at a time.")
    with rw() as c:
        c.execute("update app.replay_state set current_replay_date=%s, updated_at=now() where session_id=%s",
                  (body.to, sid))
    audit(s["analyst"], "day_advanced", {"from": str(s["current_replay_date"]), "to": str(body.to)}, "day_changed")
    return session_view(sid)


@app.post("/api/sessions/{sid}/end")
def end_session(sid: str) -> dict:
    s = _session(sid)
    with rw() as c:
        c.execute("update app.replay_state set ended_at=now() where session_id=%s and ended_at is null", (sid,))
    audit(s["analyst"], "session_end", {"session": sid, "day": str(s["current_replay_date"])}, "session_end")
    return {"saved": True}


# ---------------------------------------------------------------- decisions
def _decisions(sid: str) -> dict[tuple[str, str], dict]:
    """Latest non-undone decision per pair for this session."""
    with rw() as c:
        rows = c.execute(
            "select distinct on (case_a, case_b) decision_id, case_a, case_b, decision, reason_code, decided_at "
            "from app.link_decisions where session_id=%s and undone_at is null "
            "order by case_a, case_b, decided_at desc", (sid,)).fetchall()
    return {(r["case_a"], r["case_b"]): r for r in rows}


class DecisionIn(BaseModel):
    case_a: str
    case_b: str
    decision: Literal["accept", "reject", "defer"]
    reason_code: str
    clicks: int = Field(ge=1, le=500)
    ms_since_shown: int = Field(ge=0)
    prob_shown: float
    contributions_shown: dict[str, float]


@app.post("/api/sessions/{sid}/decisions")
def decide(sid: str, d: DecisionIn) -> dict:
    s = _session(sid)
    if s["ended_at"]:
        raise HTTPException(409, "This session has ended.")
    if d.reason_code not in REASONS[d.decision]:
        raise HTTPException(400, f"Pick a reason for this {d.decision}.")
    a, b = sorted((d.case_a, d.case_b))
    now = datetime.now(timezone.utc)
    shown = now - timedelta(milliseconds=d.ms_since_shown)
    did = str(uuid.uuid4())
    from psycopg.types.json import Jsonb
    with rw() as c:
        c.execute("insert into app.link_decisions (decision_id, case_a, case_b, model_version, prob_shown, "
                  "contributions_shown, decision, reason_code, decided_by, decided_at, ui_shown_at, clicks, session_id) "
                  "values (%s,%s,%s,'lr-v1',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (did, a, b, d.prob_shown, Jsonb(d.contributions_shown), d.decision, d.reason_code,
                   s["analyst"], now, shown, d.clicks, sid))
    audit(s["analyst"], "decision", {"pair": [a, b], "decision": d.decision, "reason": d.reason_code,
                                     "clicks": d.clicks, "ms_since_shown": d.ms_since_shown}, d.decision)
    return {"decision_id": did, "saved_at": now.isoformat()}


@app.post("/api/sessions/{sid}/decisions/{did}/undo")
def undo(sid: str, did: str) -> dict:
    s = _session(sid)
    with rw() as c:
        r = c.execute("update app.link_decisions set undone_at=now() where decision_id=%s and session_id=%s "
                      "and undone_at is null and decided_at > now() - interval '30 seconds' returning decision_id",
                      (did, sid)).fetchone()
    if not r:
        raise HTTPException(409, "This decision can no longer be undone. Reopen the link to change it.")
    audit(s["analyst"], "undo", {"decision_id": did}, "undo")
    return {"undone": True}


class EventIn(BaseModel):
    event: Literal["suggestion_shown", "view_changed", "brief_viewed"]
    data: dict[str, Any]


@app.post("/api/sessions/{sid}/events")
def event(sid: str, e: EventIn) -> dict:
    s = _session(sid)
    audit(s["analyst"], e.event, e.data, e.event)
    return {"ok": True}


# ---------------------------------------------------------------- reads
def _visible_pairs(day: date, min_prob: float) -> list[dict]:
    with ro() as c:
        return c.execute(
            "select p.case_a, p.case_b, p.prob, p.distance_km, p.days_apart, p.mo_jaccard, p.contributions "
            "from app.v_pair_scores p join app.v_cases a on a.case_id=p.case_a and a.replay_visible_on <= %(d)s "
            "join app.v_cases b on b.case_id=p.case_b and b.replay_visible_on <= %(d)s where p.prob >= %(m)s",
            {"d": day, "m": min_prob}).fetchall()


def _series(sid: str, day: date) -> tuple[list[dict], dict[str, str]]:
    dec = _decisions(sid)
    pairs = [{**p, "decision": dec.get((p["case_a"], p["case_b"]), {}).get("decision")}
             for p in _visible_pairs(day, min(THRESHOLD, SERIES_SEED))]
    accepted = {k for k, v in dec.items() if v["decision"] == "accept"}
    for a, b in accepted:  # an accepted link always counts, even below threshold
        if not any((p["case_a"], p["case_b"]) == (a, b) for p in pairs):
            pairs.append({"case_a": a, "case_b": b, "prob": 0.0, "decision": "accept"})
    groups = build_series(pairs, threshold=SERIES_SEED)
    with ro() as c:
        vis = {r["case_id"]: r["replay_visible_on"] for r in c.execute(
            "select case_id, replay_visible_on from app.v_cases where case_id = any(%s)",
            ([x for g in groups for x in g],)).fetchall()}
    start = _session(sid)["start_date"]
    out, member_of = [], {}
    for g in sorted(groups, key=lambda g: min(vis[x] for x in g)):
        sid_label = f"S-{len(out) + 1:02d}"
        strongest = max((p["prob"] for p in pairs if p["case_a"] in g and p["case_b"] in g), default=0.0)
        has_accept = any(a in g and b in g for a, b in accepted)
        out.append({"series_id": sid_label, "members": sorted(g), "size": len(g),
                    "status": "active" if has_accept else "candidate", "strongest": round(strongest, 3),
                    "first_seen_day": (min(vis[x] for x in g) - start).days + 1})
        for x in g:
            member_of[x] = sid_label
    out.sort(key=lambda s: -s["strongest"])
    return out, member_of


@app.get("/api/sessions/{sid}/queue")
def queue(sid: str) -> dict:
    s = _session(sid)
    day = s["current_replay_date"]
    series, member_of = _series(sid, day)
    with ro() as c:
        cases = c.execute("select case_id, offense_start, district_fictional, mo->>'target_type' target_type, "
                          "replay_visible_on from app.v_cases where replay_visible_on <= %s "
                          "order by replay_visible_on desc, case_id", (day,)).fetchall()
    linked_today_before = {x for p in _visible_pairs(day - timedelta(days=1), THRESHOLD) for x in (p["case_a"], p["case_b"])}
    linked_now = {x for p in _visible_pairs(day, THRESHOLD) for x in (p["case_a"], p["case_b"])}
    full, sleepers = [], []
    for r in cases:
        row = {"case_id": r["case_id"], "district": r["district_fictional"], "target_type": r["target_type"],
               "reported": str(r["replay_visible_on"]), "new_today": r["replay_visible_on"] == day,
               "series_id": member_of.get(r["case_id"])}
        full.append(row)
        woke = r["case_id"] in linked_now and r["case_id"] not in linked_today_before and r["replay_visible_on"] < day
        if r["case_id"] not in linked_now or woke:
            sleepers.append({**row, "woke_today": woke})
    sleepers.sort(key=lambda x: (not x["woke_today"], x["reported"]), reverse=False)
    return {"day": str(day), "series": series, "sleeper": sleepers[:300], "full": full[:500],
            "counts": {"visible_cases": len(full), "series": len(series), "sleeper": len(sleepers)}}


@app.get("/api/sessions/{sid}/cases/{case_id}")
def case_detail(sid: str, case_id: str) -> dict:
    day = _session(sid)["current_replay_date"]
    with ro() as c:
        r = c.execute("select case_id, offense_start, offense_end, reported_at, district_fictional, lat, lon, "
                      "narrative, narrative_origin, mo, evidence_spans, model_id from app.v_cases "
                      "where case_id=%s and replay_visible_on <= %s", (case_id, day)).fetchone()
    if not r:
        raise HTTPException(404, "That case is not visible on this replay day.")
    mo = r["mo"] or {}
    spans = r["evidence_spans"] or {}
    facts = []
    for f, label in FIELD_LABEL.items():
        v = mo.get(f)
        missing = v in (None, [], "unknown", ["none_noted"])
        facts.append({"field": f, "label": label, "value": None if missing else v,
                      "source": {"case_id": case_id, "field": f, "spans": spans.get(f, [])}})
    return {"case_id": r["case_id"], "district": r["district_fictional"],
            "window": [r["offense_start"].isoformat(), r["offense_end"].isoformat() if r["offense_end"] else None],
            "reported": r["reported_at"].isoformat() if r["reported_at"] else None,
            "lat": round(r["lat"], 3), "lon": round(r["lon"], 3),  # generalized
            "narrative": r["narrative"], "narrative_origin": r["narrative_origin"],
            "extracted_by": r["model_id"], "facts": facts, "data_label": "Synthetic data"}


def _reasons(a: dict, b: dict, p: dict) -> tuple[list[str], list[str]]:
    agree, differ = [], []
    for f, label in FIELD_LABEL.items():
        va, vb = a.get(f), b.get(f)
        # missing or "nothing noted" is never agreement (or disagreement)
        if va in (None, [], "unknown", False, ["none_noted"]) or vb in (None, [], "unknown", False, ["none_noted"]):
            continue
        if isinstance(va, list):
            shared = sorted(set(va) & set(vb) - {"none_noted"})
            if shared:
                agree.append(f"Same {label.lower()}: {', '.join(x.replace('_', ' ') for x in shared)}")
            elif set(va) != set(vb):
                differ.append(f"{label}: {', '.join(va).replace('_', ' ')} vs {', '.join(vb).replace('_', ' ')}")
        elif va == vb:
            agree.append(f"Same {label.lower()}: {str(va).replace('_', ' ')}")
        else:
            differ.append(f"{label}: {str(va).replace('_', ' ')} vs {str(vb).replace('_', ' ')}")
    agree.append(f"{p['days_apart']:.0f} days apart · {p['distance_km']:.1f} km")
    return agree, differ


LABELS = {"log_distance_km": "distance", "log_days_apart": "time gap", "mo_jaccard": "method",
          "same_target_type": "target", "both_night": "night"}


@app.get("/api/sessions/{sid}/cases/{case_id}/suggestions")
def suggestions(sid: str, case_id: str, k: int = 3) -> dict:
    day = _session(sid)["current_replay_date"]
    dec = _decisions(sid)
    _, member_of = _series(sid, day)
    with ro() as c:
        rows = c.execute(
            "select p.*, a.mo mo_a, b.mo mo_b from app.v_pair_scores p "
            "join app.v_cases a on a.case_id=p.case_a and a.replay_visible_on <= %(d)s "
            "join app.v_cases b on b.case_id=p.case_b and b.replay_visible_on <= %(d)s "
            "where (p.case_a=%(c)s or p.case_b=%(c)s) order by p.prob desc limit %(k)s",
            {"d": day, "c": case_id, "k": min(max(k, 1), 10)}).fetchall()
    out = []
    for r in rows:
        other = r["case_b"] if r["case_a"] == case_id else r["case_a"]
        mine, theirs = (r["mo_a"], r["mo_b"]) if r["case_a"] == case_id else (r["mo_b"], r["mo_a"])
        agree, differ = _reasons(mine or {}, theirs or {}, r)
        contrib = sorted(((LABELS.get(f, f), round(v, 2)) for f, v in r["contributions"].items()),
                         key=lambda kv: -abs(kv[1]))[:3]
        d = dec.get((r["case_a"], r["case_b"]))
        out.append({"case_a": r["case_a"], "case_b": r["case_b"], "other": other, "prob": round(r["prob"], 3),
                    "band": f"{band(r['prob'])} link", "distance_km": round(r["distance_km"], 2),
                    "days_apart": round(r["days_apart"], 1), "method_overlap": round(r["mo_jaccard"], 2),
                    "reasons": agree, "dont_fit": differ, "contributions": contrib,
                    "contributions_raw": {k2: round(v, 4) for k2, v in r["contributions"].items()},
                    "other_series": member_of.get(other),
                    "decision": {"decision_id": str(d["decision_id"]), "decision": d["decision"],
                                 "reason_code": d["reason_code"]} if d else None})
    return {"case_id": case_id, "suggestions": out, "reasons": REASONS,
            "limits": "Uses only place, time and method. It does not know who did it."}


@app.get("/api/sessions/{sid}/graph")
def graph(sid: str, min_prob: float = THRESHOLD, show_rejected: bool = True) -> dict:
    day = _session(sid)["current_replay_date"]
    dec = _decisions(sid)
    series, member_of = _series(sid, day)
    pairs = _visible_pairs(day, max(0.05, min_prob))
    edges = []
    for p in pairs:
        d = dec.get((p["case_a"], p["case_b"]))
        status = d["decision"] if d else "suggested"
        if status == "reject" and not show_rejected:
            continue
        edges.append({"id": f"{p['case_a']}__{p['case_b']}", "source": p["case_a"], "target": p["case_b"],
                      "prob": round(p["prob"], 3), "band": f"{band(p['prob'])} link", "status": status,
                      "distance_km": round(p["distance_km"], 2), "days_apart": round(p["days_apart"], 1),
                      "method_overlap": round(p["mo_jaccard"], 2)})
    ids = sorted({x for e in edges for x in (e["source"], e["target"])})
    with ro() as c:
        meta = {r["case_id"]: r for r in c.execute(
            "select case_id, district_fictional, mo->>'target_type' tt, lat, lon, replay_visible_on "
            "from app.v_cases where case_id = any(%s)", (ids,)).fetchall()}
    nodes = [{"id": i, "district": meta[i]["district_fictional"], "target_type": meta[i]["tt"],
              "lat": round(meta[i]["lat"], 3), "lon": round(meta[i]["lon"], 3),
              "series_id": member_of.get(i), "new_today": meta[i]["replay_visible_on"] == day} for i in ids]
    return {"day": str(day), "nodes": nodes, "edges": edges,
            "series": [s for s in series if any(m in meta for m in s["members"])],
            "data_label": "Synthetic data"}
