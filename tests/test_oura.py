"""Tests for the Oura adapter.

These tests bypass the HTTP client (no network) by populating
`oura_raw.db` directly from the fixture JSON files, then exercising
the rollup → daily_metrics path.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from adapters.oura import OuraAdapter
from adapters.oura.sync import (
    _DAILY_ACTIVITY_COLS,
    _DAILY_READINESS_COLS,
    _DAILY_SLEEP_COLS,
    _DAILY_SPO2_COLS,
    _SLEEP_SESSION_COLS,
    _ensure_schema,
    _flatten_contributors,
    _upsert,
)


FIXTURES = Path(__file__).resolve().parent.parent / "pipeline" / "adapters" / "oura" / "fixtures"


def _load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())["data"]


def _populate_oura_raw(db_path: Path) -> None:
    """Mirror what `sync()` does, but read fixtures from disk instead of
    hitting the network."""
    conn = sqlite3.connect(db_path)
    _ensure_schema(conn)
    # daily_sleep, daily_readiness — need contributors flattened
    for raw in _load("daily_sleep.json"):
        _upsert(conn, "daily_sleep", _DAILY_SLEEP_COLS, _flatten_contributors(raw))
    for raw in _load("daily_readiness.json"):
        _upsert(conn, "daily_readiness", _DAILY_READINESS_COLS, _flatten_contributors(raw))
    # daily_activity, sleep_session — no flatten needed
    for row in _load("daily_activity.json"):
        _upsert(conn, "daily_activity", _DAILY_ACTIVITY_COLS, row)
    for row in _load("sleep_session.json"):
        _upsert(conn, "sleep_session", _SLEEP_SESSION_COLS, row)
    # daily_spo2 — nested spo2_percentage dict needs manual flatten
    for raw in _load("daily_spo2.json"):
        row = dict(raw)
        sp = row.pop("spo2_percentage", {}) or {}
        row["spo2_percentage_average"] = sp.get("average")
        row["spo2_percentage_lowest"] = sp.get("lowest")
        _upsert(conn, "daily_spo2", _DAILY_SPO2_COLS, row)
    conn.commit()
    conn.close()


def test_oura_adapter_identity():
    a = OuraAdapter()
    assert a.slug == "oura"
    assert a.display_name == "Oura Ring"
    assert a.raw_db_name == "oura_raw.db"
    assert a.stability == "stable"
    assert a.requires_oauth is False


def test_oura_setup_instructions_mention_pat_portal():
    txt = OuraAdapter().setup_instructions()
    assert "cloud.ouraring.com/personal-access-tokens" in txt
    assert "Personal Access Token" in txt
    assert "OAuth" in txt  # to make clear no OAuth dance is required


def test_oura_fixtures_parse_into_raw_db(tmp_path):
    """All fixture rows land in their tables, with the contributor-flatten
    + spo2 nested-flatten cases handled."""
    db = tmp_path / "oura_raw.db"
    _populate_oura_raw(db)

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM daily_sleep").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM daily_readiness").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM daily_activity").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM sleep_session").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM daily_spo2").fetchone()[0] == 3
        # Contributor flatten worked
        r = conn.execute(
            "SELECT contributors_deep_sleep, contributors_total_sleep "
            "FROM daily_sleep WHERE day = '2026-05-15'"
        ).fetchone()
        assert r == (85, 80)
        # SpO2 nested flatten worked
        r = conn.execute(
            "SELECT spo2_percentage_average, spo2_percentage_lowest "
            "FROM daily_spo2 WHERE day = '2026-05-15'"
        ).fetchone()
        assert r == (97.2, 95.0)


def test_oura_rollup_to_daily_metrics(tmp_path, monkeypatch):
    """End-to-end: populate oura_raw.db from fixtures, run rollup, assert
    daily_metrics gets source='oura' rows with sensible joined values."""
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(tmp_path))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    # Reload paths + adapter modules so they pick up the env override
    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import adapters.base as base_mod
    importlib.reload(base_mod)
    import adapters.oura.sync as oura_sync_mod
    importlib.reload(oura_sync_mod)

    # Create health.db with daily_metrics table (use repo schema.sql for fidelity)
    repo_schema = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
    schema_text = repo_schema.read_text()
    db1, _ = schema_text.split("-- DB 2:", 1) if "-- DB 2:" in schema_text else (schema_text, "")
    hconn = sqlite3.connect(tmp_path / "data" / "health.db")
    hconn.executescript(db1)
    hconn.close()

    # Populate oura_raw.db from fixtures
    raw_db = tmp_path / "data" / "oura_raw.db"
    _populate_oura_raw(raw_db)

    # Run rollup
    adapter = oura_sync_mod.OuraAdapter()
    n = adapter.rollup_to_health_db()
    assert n == 3

    # Verify daily_metrics rows
    with sqlite3.connect(tmp_path / "data" / "health.db") as conn:
        rows = conn.execute(
            "SELECT source, date, recovery_score, hrv_ms, sleep_hours, steps "
            "FROM daily_metrics ORDER BY date"
        ).fetchall()
    assert len(rows) == 3
    for src, day, recovery, hrv, sleep, steps in rows:
        assert src == "oura"
        assert recovery is not None
        assert hrv is not None
        assert sleep is not None and sleep > 0
        assert steps is not None and steps > 0

    # Spot-check one specific day's join: 2026-05-15
    with sqlite3.connect(tmp_path / "data" / "health.db") as conn:
        r = conn.execute(
            "SELECT recovery_score, hrv_ms, sleep_performance, steps "
            "FROM daily_metrics WHERE source='oura' AND date='2026-05-15'"
        ).fetchone()
    assert r[0] == 78           # daily_readiness.score
    assert r[1] == pytest.approx(62.4)   # sleep_session.average_hrv
    assert r[2] == 82           # daily_sleep.score
    assert r[3] == 9420         # daily_activity.steps


def test_oura_rollup_is_idempotent(tmp_path, monkeypatch):
    """Running rollup twice on the same raw data inserts no duplicates
    (relies on INSERT OR REPLACE on the composite (source, date) PK)."""
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(tmp_path))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import adapters.oura.sync as oura_sync_mod
    importlib.reload(oura_sync_mod)

    repo_schema = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
    schema_text = repo_schema.read_text()
    db1, _ = schema_text.split("-- DB 2:", 1) if "-- DB 2:" in schema_text else (schema_text, "")
    hconn = sqlite3.connect(tmp_path / "data" / "health.db")
    hconn.executescript(db1)
    hconn.close()

    raw_db = tmp_path / "data" / "oura_raw.db"
    _populate_oura_raw(raw_db)

    adapter = oura_sync_mod.OuraAdapter()
    adapter.rollup_to_health_db()
    second = adapter.rollup_to_health_db()
    assert second == 0  # last_date filter excludes already-rolled days

    with sqlite3.connect(tmp_path / "data" / "health.db") as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM daily_metrics WHERE source='oura'"
        ).fetchone()[0]
    assert n == 3
