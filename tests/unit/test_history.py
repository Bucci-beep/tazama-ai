from tazama.clinical.history import (
    CompareHistoryRequest,
    TimedObservation,
    compare_with_history,
)
from tazama.mcp.contracts import PatientObservations

T1 = "2026-10-13T08:10:00+00:00"
T2 = "2026-10-13T09:30:00+00:00"


def timed(obs_id, taken, **vals):
    return TimedObservation(
        obs_id=obs_id, taken_utc=taken, observations=PatientObservations(**vals)
    )


def request(before, after):
    return CompareHistoryRequest(case_id="SYN-001", before=before, after=after)


def test_differences_are_reported_with_evidence():
    r = compare_with_history(
        request(
            timed("OBS-1", T1, respiratory_rate_bpm=18.0, spo2_percent=97.0),
            timed("OBS-2", T2, respiratory_rate_bpm=26.0, spo2_percent=97.0),
        )
    )
    assert r.status == "differences_found"
    assert [c.field for c in r.changes] == ["respiratory_rate_bpm"]
    assert (r.changes[0].before, r.changes[0].after) == (18.0, 26.0)
    assert (r.changes[0].before_obs_id, r.changes[0].after_obs_id) == ("OBS-1", "OBS-2")


def test_identical_readings_show_no_differences():
    r = compare_with_history(
        request(
            timed("OBS-1", T1, heart_rate_bpm=80.0),
            timed("OBS-2", T2, heart_rate_bpm=80.0),
        )
    )
    assert r.status == "no_differences" and r.changes == []


def test_no_baseline_is_insufficient_history_not_stable():
    r = compare_with_history(request(None, timed("OBS-2", T2, heart_rate_bpm=80.0)))
    assert r.status == "insufficient_history" and r.reason == "NO_BASELINE"


def test_new_reading_without_timestamp_is_refused():
    r = compare_with_history(
        request(
            timed("OBS-1", T1, spo2_percent=97.0),
            timed("OBS-2", None, spo2_percent=89.0),
        )
    )
    assert r.status == "untrusted_reading" and r.changes == []


def test_timestamp_without_timezone_is_refused():
    r = compare_with_history(
        request(
            timed("OBS-1", T1, spo2_percent=97.0),
            timed("OBS-2", "2026-10-13T09:30:00", spo2_percent=89.0),
        )
    )
    assert r.status == "untrusted_reading"


def test_reading_not_after_baseline_is_refused():
    r = compare_with_history(
        request(
            timed("OBS-1", T2, spo2_percent=97.0),
            timed("OBS-2", T1, spo2_percent=89.0),
        )
    )
    assert r.status == "untrusted_reading"
    assert r.reason == "NEW_READING_NOT_AFTER_BASELINE"


def test_field_present_on_one_side_only_is_flagged_not_compared():
    r = compare_with_history(
        request(
            timed("OBS-1", T1, heart_rate_bpm=80.0),
            timed("OBS-2", T2, heart_rate_bpm=80.0, spo2_percent=89.0),
        )
    )
    assert r.not_comparable == ["spo2_percent"]
