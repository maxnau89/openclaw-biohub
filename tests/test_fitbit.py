"""Tests for the Fitbit adapter.

Bypasses the network: load fixture JSON files directly through the
parsers + raw-DB upsert helpers, then exercise the rollup path.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from adapters.fitbit import FitbitAdapter
from adapters.fitbit.sync import (
    _ACTIVITY_COLS,
    _HEART_COLS,
    _HRV_COLS,
    _SLEEP_COLS,
    _SPO2_COLS,
    _TEMP_COLS,
    _ensure_schema,
    _upsert,
    parse_activity,
    parse_heart_rate,
    parse_hrv,
    parse_sleep,
    parse_spo2,
    parse_temp,
)


FIXTURES = (
    Path(__file__).resolve().parent.parent
    / "pipeline" / "adapters" / "fitbit" / "fixtures"
)


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


def _populate_fitbit_raw(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    _ensure_schema(conn)
    for r in parse_sleep(_load("sleep.json")):
        _upsert(conn, "sleep_summary", _SLEEP_COLS, r)
    for r in parse_heart_rate(_load("heart.json")):
        _upsert(conn, "heart_summary", _HEART_COLS, r)
    # Activity: per-day fixtures (only one provided; iterate any *.json that exists)
    for f in FIXTURES.glob("activity_*.json"):
        payload = _load(f.name)
        payload["_date"] = f.stem.replace("activity_", "")
        for r in parse_activity(payload):
            _upsert(conn, "activity_summary", _ACTIVITY_COLS, r)
    for r in parse_spo2(_load("spo2.json")):
        _upsert(conn, "spo2_summary", _SPO2_COLS, r)
    for r in parse_hrv(_load("hrv.json")):
        _upsert(conn, "hrv_summary", _HRV_COLS, r)
    for r in parse_temp(_load("temp.json")):
        _upsert(conn, "temp_summary", _TEMP_COLS, r)
    conn.commit()
    conn.close()


# ─── Identity / config ───────────────────────────────────────────────────────


def test_fitbit_adapter_identity():
    a = FitbitAdapter()
    assert a.slug == "fitbit"
    assert a.display_name == "Fitbit"
    assert a.raw_db_name == "fitbit_raw.db"
    assert a.stability == "stable"
    assert a.requires_oauth is True


def test_fitbit_setup_instructions_mention_portal_and_callback():
    txt = FitbitAdapter().setup_instructions()
    assert "dev.fitbit.com/apps" in txt
    assert "Personal" in txt        # Application Type
    assert "callback" in txt.lower()
    assert "Rate limit" in txt
    # Mentions the default callback port
    assert "8894" in txt


# ─── Parsers ─────────────────────────────────────────────────────────────────


def test_parse_sleep_extracts_stage_minutes():
    rows = parse_sleep(_load("sleep.json"))
    assert len(rows) == 3
    r15 = next(r for r in rows if r["date"] == "2026-05-15")
    assert r15["minutes_asleep"] == 425
    assert r15["rem_minutes"] == 95
    assert r15["deep_minutes"] == 95
    assert r15["light_minutes"] == 235
    assert r15["wake_minutes"] == 35
    assert r15["efficiency"] == 88
    assert r15["is_main_sleep"] == 1


def test_parse_heart_rate_zone_lookup():
    rows = parse_heart_rate(_load("heart.json"))
    r17 = next(r for r in rows if r["date"] == "2026-05-17")
    assert r17["resting_heart_rate"] == 53
    assert r17["cardio_minutes"] == 38
    assert r17["fat_burn_minutes"] == 250
    assert r17["peak_calories"] == pytest.approx(22.0)


def test_parse_activity_pulls_summary_fields():
    payload = _load("activity_2026-05-15.json")
    payload["_date"] = "2026-05-15"
    rows = parse_activity(payload)
    assert len(rows) == 1
    r = rows[0]
    assert r["date"] == "2026-05-15"
    assert r["steps"] == 9420
    assert r["calories_out"] == 2700
    assert r["very_active_minutes"] == 38
    assert r["fairly_active_minutes"] == 18
    assert r["lightly_active_minutes"] == 165
    assert r["distance_total"] == 7.2
    assert r["floors"] == 12


def test_parse_spo2_handles_list_response():
    rows = parse_spo2(_load("spo2.json"))
    assert len(rows) == 3
    r = next(r for r in rows if r["date"] == "2026-05-15")
    assert r["avg"] == 96.5
    assert r["min"] == 93.0


def test_parse_hrv():
    rows = parse_hrv(_load("hrv.json"))
    assert len(rows) == 3
    r = next(r for r in rows if r["date"] == "2026-05-15")
    assert r["daily_rmssd"] == 48.2
    assert r["deep_rmssd"] == 52.4


def test_parse_temp():
    rows = parse_temp(_load("temp.json"))
    r = next(r for r in rows if r["date"] == "2026-05-15")
    assert r["nightly_relative"] == pytest.approx(-0.18)


# ─── End-to-end rollup ───────────────────────────────────────────────────────


@pytest.fixture
def fitbit_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(tmp_path))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "secrets").mkdir(parents=True, exist_ok=True)

    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import adapters.base as base_mod
    importlib.reload(base_mod)
    import adapters.fitbit.sync as fb_sync_mod
    importlib.reload(fb_sync_mod)

    # Build the health.db (DB 1 block)
    repo_schema = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
    schema_text = repo_schema.read_text()
    db1, _ = schema_text.split("-- DB 2:", 1) if "-- DB 2:" in schema_text else (schema_text, "")
    hconn = sqlite3.connect(tmp_path / "data" / "health.db")
    hconn.executescript(db1)
    hconn.close()

    return {"biohub_home": tmp_path, "module": fb_sync_mod}


def test_rollup_produces_fitbit_daily_metrics(fitbit_env):
    mod = fitbit_env["module"]
    raw_db = fitbit_env["biohub_home"] / "data" / "fitbit_raw.db"
    _populate_fitbit_raw(raw_db)

    adapter = mod.FitbitAdapter()
    n = adapter.rollup_to_health_db()
    # 3 sleep_summary rows → 3 daily_metrics rows
    assert n == 3

    with sqlite3.connect(fitbit_env["biohub_home"] / "data" / "health.db") as conn:
        rows = conn.execute(
            "SELECT date, hrv_ms, resting_hr, spo2, sleep_hours, sleep_efficiency, "
            "       rem_hours, deep_sleep_hours, light_sleep_hours, "
            "       steps, calories_burned, active_minutes "
            "FROM daily_metrics WHERE source = 'fitbit' ORDER BY date"
        ).fetchall()
    assert len(rows) == 3
    r15 = rows[0]
    # date
    assert r15[0] == "2026-05-15"
    # hrv_ms: 48.2 from hrv fixture
    assert r15[1] == pytest.approx(48.2)
    # resting_hr: 56 from heart fixture
    assert r15[2] == 56
    # spo2: 96.5 from spo2 fixture
    assert r15[3] == pytest.approx(96.5)
    # sleep_hours: 425 minutes asleep / 60 = ~7.083
    assert r15[4] == pytest.approx(7.083, abs=0.005)
    # sleep_efficiency: 88 / 100 = 0.88
    assert r15[5] == pytest.approx(0.88)
    # rem_hours: 95 / 60 = ~1.583
    assert r15[6] == pytest.approx(1.583, abs=0.005)
    # deep_sleep_hours: 95 / 60 ≈ 1.583
    assert r15[7] == pytest.approx(1.583, abs=0.005)
    # light_sleep_hours: 235 / 60 ≈ 3.917
    assert r15[8] == pytest.approx(3.917, abs=0.005)
    # steps: 9420 from activity fixture
    assert r15[9] == 9420
    # calories_burned: 2700
    assert r15[10] == 2700
    # active_minutes: lightly(165) + fairly(18) + very(38) = 221
    assert r15[11] == 221


def test_rollup_skips_main_sleep_false(fitbit_env):
    """The rollup SQL filters is_main_sleep = 1; verify nap rows don't
    duplicate the daily row."""
    mod = fitbit_env["module"]
    raw_db = fitbit_env["biohub_home"] / "data" / "fitbit_raw.db"
    _populate_fitbit_raw(raw_db)

    # Inject a nap row for 2026-05-15
    with sqlite3.connect(raw_db) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sleep_summary "
            "(date, log_id, is_main_sleep, minutes_asleep, efficiency) "
            "VALUES (?,?,?,?,?)",
            ("2026-05-15-nap", "nap-1", 0, 30, 80),
        )

    adapter = mod.FitbitAdapter()
    n = adapter.rollup_to_health_db()
    # Still just 3 main-sleep days; the nap is filtered out
    assert n == 3


def test_rollup_idempotent(fitbit_env):
    mod = fitbit_env["module"]
    raw_db = fitbit_env["biohub_home"] / "data" / "fitbit_raw.db"
    _populate_fitbit_raw(raw_db)

    adapter = mod.FitbitAdapter()
    adapter.rollup_to_health_db()
    second = adapter.rollup_to_health_db()
    assert second == 0
    with sqlite3.connect(fitbit_env["biohub_home"] / "data" / "health.db") as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM daily_metrics WHERE source='fitbit'"
        ).fetchone()[0]
    assert n == 3
