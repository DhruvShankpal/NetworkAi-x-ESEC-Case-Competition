from seriesdesk.verifier import verify_brief

REC = {
    "C-1": {"entry_method": "glass_broken", "target_type": "commercial", "property_categories": ["cash", "gift_cards"],
            "narrative_name": "Riverside Market"},
    "C-2": {"entry_method": "glass_broken", "target_type": "commercial", "property_categories": ["cash"]},
}


def S(text, *cites):
    return {"sentence": text, "citations": [dict(zip(("case_id", "field", "value"), c)) for c in cites]}


def test_good_brief_passes():
    r = verify_brief([
        S("Both cases involved glass broken entries.", ("C-1", "entry_method", "glass_broken"), ("C-2", "entry_method", "glass_broken")),
        S("C-1 lost cash and gift cards.", ("C-1", "property_categories", ["cash", "gift_cards"])),
    ], REC)
    assert r.ok, [s.errors for s in r.failures]


def test_injected_bad_citation_rejected():
    r = verify_brief([S("C-2 involved a pry entry.", ("C-2", "entry_method", "pry"))], REC)
    assert not r.ok and "value mismatch" in r.failures[0].errors[0]


def test_unknown_case_and_missing_field():
    r = verify_brief([S("C-9 was commercial.", ("C-9", "target_type", "commercial")),
                      S("C-2 had tools.", ("C-2", "tools", "rock"))], REC)
    assert not r.ok and len(r.failures) == 2


def test_uncited_sentence_rejected():
    assert not verify_brief([S("These look like the same offender.")], REC).ok


def test_value_must_be_stated_in_sentence():
    r = verify_brief([S("C-1 was similar.", ("C-1", "target_type", "commercial"))], REC)
    assert not r.ok and "not stated" in r.failures[0].errors[0]


def test_name_not_in_cited_field_blocked():
    r = verify_brief([S("C-1 was a commercial burglary near John Smith's shop.", ("C-1", "target_type", "commercial"))], REC)
    assert not r.ok and any("John" in e for e in r.failures[0].errors)


def test_name_present_in_cited_field_allowed():
    r = verify_brief([S("C-1 occurred at Riverside Market.", ("C-1", "narrative_name", "Riverside Market"))], REC)
    assert r.ok, r.failures and r.failures[0].errors


def test_empty_brief_fails():
    assert not verify_brief([], REC).ok
