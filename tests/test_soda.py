from seriesdesk.soda import to_incident, burglary_where
from datetime import date

ROW = {"report_number": "2019-417828", "report_date_time": "2019-11-09T13:01:40.000", "offense_id": "11697415271",
       "offense_date": "2019-11-09T00:30:00.000", "latitude": "47.62393445", "longitude": "-122.358019952483",
       "beat": "Q3", "precinct": "West", "sector": "Q", "neighborhood": "QUEEN ANNE",
       "nibrs_offense_code": "220", "nibrs_offense_code_description": "Burglary/Breaking & Entering"}


def test_to_incident_hashes_report_number():
    inc = to_incident(ROW, salt="s")
    assert inc["case_id"] == "SPD-11697415271" and "2019-417828" not in str(inc)
    assert inc["replay_visible_on"] == date(2019, 11, 9) and inc["lat"] > 47


def test_redacted_coordinates_dropped():
    assert to_incident({**ROW, "latitude": "REDACTED"}, "s") is None
    assert to_incident({**ROW, "latitude": "-1", "longitude": "-1"}, "s") is None


def test_where_clause_uses_verified_field_names():
    w = burglary_where(date(2018, 4, 1), date(2018, 11, 30))
    assert "nibrs_offense_code='220'" in w and "offense_date between" in w
