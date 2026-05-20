"""Tests for the Garmin adapter.

The Garmin adapter is `stability="experimental"` and depends on the
unofficial `garth` library. These tests:

- Do NOT require garth installed (parsers + rollup are pure-Python)
- Do NOT make any network calls (we monkeypatch GarminClient.connectapi
  to return fixture JSON)
"""
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from adapters.garmin import GarminAdapter
from adapters.garmin.sync import (
    _ACTIVITY_COLS,
    _HEART_COLS,
    _HRV_COLS,
    _SLEEP_COLS,
    _STRESS_COLS,
    _ensure_schema,
    _upsert,
    parse_activity,
    parse_heart_rate,
    parse_hrv,
    parse_sleep,
    parse_stress,
)


FIXTURES = (
    Path(__file__).resolve().parent.parent
    / "pipeline" / "adapters" / "garmin" / "fixtures"
)


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


def _populate_garmin_raw(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    _ensure_schema(conn)
    s = parse_sleep(_load("sleep.json"))
    if s:
        _upsert(conn, "sleep_summary", _SLEEP_COLS, s)
    a = parse_activity(_load("activity.json"))
    if a:
        _upsert(conn, "activity_summary", _ACTIVITY_COLS, a)
    h = parse_heart_rate(_load("activity.json"))
    if h:
        _upsert(conn, "heart_rate_summary", _HEART_COLS, h)
    st = parse_stress(_load("stress.json"))
    if st:
        _upsert(conn, "stress_summary", _STRESS_COLS, st)
    hr = parse_hrv(_load("hrv.json"))
    if hr:
        _upsert(conn, "hrv_summary", _HRV_COLS, hr)
    conn.commit()
    conn.close()


# ─── Identity ────────────────────────────────────────────────────────────────


def test_garmin_adapter_identity():
    a = GarminAdapter()
    assert a.slug == "garmin"
    assert a.display_name == "Garmin Connect (experimental)"
    assert a.raw_db_name == "garmin_raw.db"
    assert a.stability == "experimental"
    assert a.requires_oauth is False


def test_garmin_setup_instructions_warn_experimental():
    txt = GarminAdapter().setup_instructions()
    assert "EXPERIMENTAL" in txt
    assert "garth" in txt
    assert "Garmin Connect" in txt


def test_garmin_secrets_path_is_a_directory(monkeypatch, tmp_path):
    """Unlike other adapters which use a single JSON file, garth caches
    multiple token files — so secrets_path is a directory."""
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(tmp_path))
    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import adapters.garmin.sync as gs
    importlib.reload(gs)
    a = gs.GarminAdapter()
    assert a.secrets_path == tmp_path / "secrets" / "garmin"
    assert a.secrets_path.suffix == ""   # directory, not .json


# ─── Parsers ─────────────────────────────────────────────────────────────────


def test_parse_sleep_extracts_score_and_stages():
    row = parse_sleep(_load("sleep.json"))
    assert row is not None
    assert row["date"] == "2026-05-15"
    assert row["sleep_score"] == 82
    assert row["total_sleep_seconds"] == 26100
    assert row["deep_sleep_seconds"] == 5400
    assert row["rem_sleep_seconds"] == 6300
    assert row["light_sleep_seconds"] == 14400
    assert row["awake_seconds"] == 1800
    assert row["average_spo2"] == 96.5
    assert row["average_hrv"] == 51.2


def test_parse_sleep_empty_payload_returns_none():
    assert parse_sleep({}) is None
    assert parse_sleep({"dailySleepDTO": {}}) is None  # no calendarDate


def test_parse_activity_handles_floors_field_aliases():
    """Garmin sometimes returns floorsClimbed, sometimes floorsAscended."""
    row = parse_activity(_load("activity.json"))
    assert row["floors_climbed"] == 8   # fixture uses floorsAscended


def test_parse_heart_rate_extracts_from_user_summary():
    row = parse_heart_rate(_load("activity.json"))
    assert row["resting_heart_rate"] == 54
    assert row["min_heart_rate"] == 48
    assert row["max_heart_rate"] == 162
    assert row["last_seven_days_avg_resting_hr"] == 56


def test_parse_stress_with_body_battery():
    row = parse_stress(_load("stress.json"))
    assert row["average_stress_level"] == 28
    assert row["body_battery_charged"] == 65
    assert row["body_battery_highest"] == 88


def test_parse_hrv_extracts_nested_summary():
    row = parse_hrv(_load("hrv.json"))
    assert row["date"] == "2026-05-15"
    assert row["last_night_avg"] == 51.2
    assert row["status"] == "BALANCED"


# ─── End-to-end rollup ───────────────────────────────────────────────────────


@pytest.fixture
def garmin_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(tmp_path))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import adapters.base as base_mod
    importlib.reload(base_mod)
    import adapters.garmin.sync as gs
    importlib.reload(gs)

    # Build health.db (DB 1 block)
    repo_schema = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
    schema_text = repo_schema.read_text()
    db1, _ = schema_text.split("-- DB 2:", 1) if "-- DB 2:" in schema_text else (schema_text, "")
    hconn = sqlite3.connect(tmp_path / "data" / "health.db")
    hconn.executescript(db1)
    hconn.close()

    return {"biohub_home": tmp_path, "module": gs}


def test_rollup_produces_garmin_daily_metrics(garmin_env):
    mod = garmin_env["module"]
    raw_db = garmin_env["biohub_home"] / "data" / "garmin_raw.db"
    _populate_garmin_raw(raw_db)

    adapter = mod.GarminAdapter()
    n = adapter.rollup_to_health_db()
    assert n == 1   # one day in fixtures

    with sqlite3.connect(garmin_env["biohub_home"] / "data" / "health.db") as conn:
        r = conn.execute(
            "SELECT date, hrv_ms, resting_hr, spo2, sleep_performance, "
            "       sleep_hours, sleep_efficiency, rem_hours, deep_sleep_hours, "
            "       light_sleep_hours, calories_burned, steps, active_minutes "
            "FROM daily_metrics WHERE source = 'garmin'"
        ).fetchone()
    assert r[0] == "2026-05-15"
    # hrv_ms: lastNightAvg from hrv fixture
    assert r[1] == pytest.approx(51.2)
    assert r[2] == 54                    # resting_hr from activity fixture
    assert r[3] == pytest.approx(96.5)   # spo2 from sleep fixture
    assert r[4] == 82                    # sleep_performance = sleep_score
    assert r[5] == pytest.approx(7.25)   # 26100/3600
    # sleep_efficiency: 26100 / (26100 + 1800) = 0.9355
    assert r[6] == pytest.approx(0.9355, abs=0.001)
    assert r[7] == pytest.approx(1.75)   # rem 6300/3600
    assert r[8] == pytest.approx(1.5)    # deep 5400/3600
    assert r[9] == pytest.approx(4.0)    # light 14400/3600
    # calories: 720 active + 1750 bmr = 2470
    assert r[10] == 2470
    assert r[11] == 9420
    # active_minutes: 35 moderate + 12 vigorous = 47
    assert r[12] == 47


def test_rollup_is_idempotent(garmin_env):
    mod = garmin_env["module"]
    raw_db = garmin_env["biohub_home"] / "data" / "garmin_raw.db"
    _populate_garmin_raw(raw_db)

    adapter = mod.GarminAdapter()
    adapter.rollup_to_health_db()
    second = adapter.rollup_to_health_db()
    assert second == 0


# ─── Sync flow with GarminClient.connectapi mocked ───────────────────────────


def test_sync_uses_connectapi_and_writes_raw_rows(garmin_env, monkeypatch):
    """Bypasses garth: monkeypatches GarminClient.{resume,connectapi} to
    return fixture data for the expected endpoint paths."""
    mod = garmin_env["module"]

    # Create the secrets directory so the adapter doesn't bail
    (garmin_env["biohub_home"] / "secrets" / "garmin").mkdir(parents=True)

    sleep = _load("sleep.json")
    activity = _load("activity.json")
    stress = _load("stress.json")
    hrv = _load("hrv.json")
    profile = {"displayName": "testuser"}

    def fake_connectapi(self, path, **params):
        if path.endswith("/user-profile"):
            return profile
        if path.startswith("/wellness-service/wellness/dailySleepData"):
            return sleep
        if path.startswith("/usersummary-service/usersummary/daily/"):
            return activity
        if path.startswith("/wellness-service/wellness/dailyStress"):
            return stress
        if path.startswith("/hrv-service/hrv/"):
            return hrv
        raise RuntimeError(f"Unexpected path: {path}")

    monkeypatch.setattr(
        "adapters.garmin.sync.GarminClient.resume", lambda self: None,
    )
    monkeypatch.setattr(
        "adapters.garmin.sync.GarminClient.connectapi", fake_connectapi,
    )

    adapter = mod.GarminAdapter()
    # Limit to 1 day so we don't hit the 30-day default range
    result = adapter.sync(limit=1)
    # 1 day × 5 row-writes (sleep, activity, heart, stress, hrv) = 5
    assert result.rows_inserted == 5
    assert result.error is None

    with sqlite3.connect(adapter.raw_db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sleep_summary").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM activity_summary").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM heart_rate_summary").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM stress_summary").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM hrv_summary").fetchone()[0] == 1
