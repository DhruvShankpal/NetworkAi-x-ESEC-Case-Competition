from seriesdesk.synth import generate, SynthConfig
from seriesdesk.audit import make_event, chain_hash, verify_chain, GENESIS


def small(seed=7):
    return generate(SynthConfig(seed=seed, n_noise=200, n_series=3, n_decoys=2))


def test_seeded_determinism():
    a, b = small(), small()
    assert [i["narrative"] for i in a.incidents] == [i["narrative"] for i in b.incidents]
    assert a.answer_key == b.answer_key
    assert [i["narrative"] for i in small(8).incidents] != [i["narrative"] for i in a.incidents]


def test_incidents_carry_no_labels():
    d = small()
    for inc in d.incidents:
        assert not {"offender_id", "true_series_id", "is_decoy"} & set(inc)


def test_evidence_spans_point_at_text():
    d = small()
    for inc in d.incidents[:50]:
        for fld, spans in inc["evidence_spans"].items():
            for s, e in spans:
                assert 0 <= s < e <= len(inc["narrative"])


def test_answer_key_has_series_and_decoys():
    key = small().answer_key
    assert sum(1 for k in key if k["true_series_id"]) >= 3 * 4
    assert any(k["is_decoy"] for k in key)
    assert all(k["true_series_id"] is None for k in key if k["is_decoy"])


def test_hash_chain_detects_tampering():
    rows, prev = [], GENESIS
    for n in range(5):
        ev = make_event("anon-1", "human", tool="decision", args={"n": n})
        h = chain_hash(prev, ev)
        rows.append({**ev, "prev_hash": prev, "row_hash": h}); prev = h
    assert verify_chain(rows) == (True, None)
    rows[2]["args"] = {"n": 99}
    assert verify_chain(rows) == (False, 2)
    del rows[2]
    assert verify_chain(rows)[0] is False


def test_backdrop_rows_keep_real_space_time():
    from datetime import datetime
    bd = [{"lat": 47.61 + k * 1e-3, "lon": -122.33, "offense_start": datetime(2023, 5, 1 + k % 20, 2),
           "reported_at": datetime(2023, 5, 1 + k % 20, 9)} for k in range(60)]
    d = generate(SynthConfig(seed=3, n_series=2, n_decoys=0, backdrop=bd))
    key = {k["case_id"]: k for k in d.answer_key}
    noise = [i for i in d.incidents if key[i["case_id"]]["true_series_id"] is None]
    assert len(noise) == 60 and d.meta["backdrop"] == "spd_open"
    real = {(b["lat"], b["offense_start"]) for b in bd}
    assert all((round(i["lat"], 6), i["offense_start"]) in {(round(a, 6), t) for a, t in real} for i in noise)
