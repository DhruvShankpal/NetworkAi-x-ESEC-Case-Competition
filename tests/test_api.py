"""CaseWeb API tests. Pure helpers always run; endpoint tests need the local DB with synthetic data."""
import uuid

import pytest

from api.app import _reasons


def test_missing_and_none_noted_are_never_agreement():
    a = {"entry_method": "pry", "tools": ["none_noted"], "vehicle_mentioned": False, "occupancy": None}
    b = {"entry_method": "pry", "tools": ["pry_bar"], "vehicle_mentioned": False, "occupancy": "unoccupied"}
    agree, differ = _reasons(a, b, {"days_apart": 3.2, "distance_km": 1.04})
    assert "Same entry method: pry" in agree
    assert not any("vehicle" in x.lower() or "tools" in x.lower() or "occupancy" in x.lower() for x in agree + differ)
    assert agree[-1] == "3 days apart · 1.0 km"


def test_disagreement_is_listed_as_does_not_fit():
    _, differ = _reasons({"target_type": "residential"}, {"target_type": "commercial"}, {"days_apart": 1, "distance_km": 1})
    assert differ == ["Target: residential vs commercial"]


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from api.app import app
    c = TestClient(app)
    sid = f"T-{uuid.uuid4().hex[:8]}"
    try:
        r = c.post(f"/api/sessions/{sid}", json={"analyst": "anon-7"})
    except Exception as e:  # pragma: no cover
        pytest.skip(f"db unavailable: {e}")
    if r.status_code != 200:
        pytest.skip("db unavailable")
    return c, sid


def test_replay_clock_hides_future_cases(client):
    c, sid = client
    q = c.get(f"/api/sessions/{sid}/queue").json()
    day = q["day"]
    assert all(r["reported"] <= day for r in q["full"])
    g = c.get(f"/api/sessions/{sid}/graph").json()
    assert all(n["id"] in {r["case_id"] for r in q["full"]} for n in g["nodes"])


def test_cannot_skip_ahead(client):
    c, sid = client
    assert c.post(f"/api/sessions/{sid}/day", json={"to": "2018-11-01"}).status_code == 400


def test_decision_requires_matching_reason_and_undo_works(client):
    c, sid = client
    for d in ("2018-04-02", "2018-04-03", "2018-04-04", "2018-04-05", "2018-04-06", "2018-04-07"):
        c.post(f"/api/sessions/{sid}/day", json={"to": d})
    edges = c.get(f"/api/sessions/{sid}/graph?min_prob=0.05").json()["edges"]
    if not edges:
        pytest.skip("no visible links yet")
    e = edges[0]
    body = {"case_a": e["source"], "case_b": e["target"], "decision": "accept", "reason_code": "R2_TOO_FAR",
            "clicks": 2, "ms_since_shown": 1200, "prob_shown": e["prob"], "contributions_shown": {}}
    assert c.post(f"/api/sessions/{sid}/decisions", json=body).status_code == 400  # reject reason on an accept
    body["reason_code"] = "A1_MO_SIGNATURE"
    r = c.post(f"/api/sessions/{sid}/decisions", json=body)
    assert r.status_code == 200
    g = c.get(f"/api/sessions/{sid}/graph?min_prob=0.05").json()
    assert next(x for x in g["edges"] if x["id"] == e["id"])["status"] == "accept"
    assert c.post(f"/api/sessions/{sid}/decisions/{r.json()['decision_id']}/undo").status_code == 200
    g = c.get(f"/api/sessions/{sid}/graph?min_prob=0.05").json()
    assert next(x for x in g["edges"] if x["id"] == e["id"])["status"] == "suggested"


def test_no_answer_key_fields_in_responses(client):
    c, sid = client
    blob = c.get(f"/api/sessions/{sid}/queue").text + c.get(f"/api/sessions/{sid}/graph").text
    for banned in ("true_series", "is_decoy", "offender_id", "answer_key"):
        assert banned not in blob
