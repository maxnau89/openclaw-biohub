"""Tests for the Apple Health adapter.

Apple Health is file-based, so these tests run end-to-end:
copy a fixture JSON into a tmp watch directory, run `sync()`, run
`rollup_to_health_db()`, assert the daily_metrics rows are right.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from adapters.apple_health import AppleHealthAdapter
from adapters.apple_health.sync import (
    normalize_metric_name,
    parse_health_export_json,
)


FIXTURE_FILE = (
    Path(__file__).resolve().parent.parent
    / "pipeline" / "adapters" / "apple_health"
    / "fixtures" / "health_auto_export_sample.json"
)


# ─── Unit: metric-name normalization ─────────────────────────────────────────

def test_normalize_metric_name_hk_identifier_to_slug():
    assert normalize_metric_name("HKQuantityTypeIdentifierHeartRate") == "heart_rate"
    assert normalize_metric_name(
        "HKQuantityTypeIdentifierHeartRateVariabilitySDNN"
    ) == "heart_rate_variability"
    assert normalize_metric_name(
        "HKCategoryTypeIdentifierSleepAnalysis"
    ) == "sleep_analysis"


def test_normalize_metric_name_already_slug_passthrough():
    assert normalize_metric_name("heart_rate") == "heart_rate"
    assert normalize_metric_name("step_count") == "step_count"


def test_normalize_metric_name_unknown_lowercased_with_underscores():
    assert normalize_metric_name("Some Custom Metric") == "some_custom_metric"


# ─── Unit: JSON parser ───────────────────────────────────────────────────────

def test_parse_health_export_json_splits_into_three_buckets():
    payload = json.loads(FIXTURE_FILE.read_text())
    metrics, sleeps, workouts = parse_health_export_json(payload)
    # Sample counts from the fixture
    # v0.2 metrics: 7 + 2 + 5 + 3 + 5 + 5 + 2 + 2 = 31
    # v0.3 nutrition + body_mass additions: 2 (body_mass) + 5 (dietary_energy)
    #   + 5 (protein) + 5 (carbs) + 5 (fat) + 5 (fiber) + 3 (water) = 30
    assert len(metrics) == 31 + 30
    assert len(sleeps) == 5 + 4                          # 9 sleep intervals
    assert len(workouts) == 1


def test_parse_health_export_json_normalizes_hk_identifier_in_input():
    """The fixture uses 'HKQuantityTypeIdentifierRestingHeartRate' for RHR.
    It must end up as 'resting_heart_rate' in the parsed rows."""
    payload = json.loads(FIXTURE_FILE.read_text())
    metrics, _, _ = parse_health_export_json(payload)
    names = {r["metric_name"] for r in metrics}
    assert "resting_heart_rate" in names
    assert "HKQuantityTypeIdentifierRestingHeartRate" not in names


def test_parse_workout_handles_nested_quantity_units():
    payload = json.loads(FIXTURE_FILE.read_text())
    _, _, workouts = parse_health_export_json(payload)
    w = workouts[0]
    assert w["workout_type"] == "Running"
    assert w["total_energy_burned"] == 380   # extracted from {"qty": 380, ...}
    assert w["total_distance"] == 6500


# ─── Identity / config ───────────────────────────────────────────────────────

def test_apple_health_adapter_identity():
    a = AppleHealthAdapter()
    assert a.slug == "apple-health"
    assert a.display_name == "Apple Health"
    assert a.raw_db_name == "apple_health_raw.db"
    assert a.stability == "stable"
    assert a.requires_oauth is False


def test_apple_health_setup_instructions_mention_both_modes():
    txt = AppleHealthAdapter().setup_instructions()
    assert "Health Auto Export" in txt
    assert "export.zip" in txt or "export.xml" in txt.lower()
    assert "watch directory" in txt.lower()


# ─── End-to-end: file ingest + rollup ────────────────────────────────────────

@pytest.fixture
def apple_health_env(tmp_path, monkeypatch):
    """Set up a tmp BIOHUB_HOME with watch-dir + secrets pointing at it,
    drop the fixture JSON into the watch dir, and return paths."""
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(tmp_path))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "secrets").mkdir(parents=True, exist_ok=True)
    watch = tmp_path / "watch"
    watch.mkdir()
    # Place secrets pointing at the watch dir
    (tmp_path / "secrets" / "apple-health.json").write_text(
        json.dumps({"watch_dir": str(watch)})
    )
    # Copy the fixture into the watch dir
    (watch / "export-2026-05-16.json").write_text(FIXTURE_FILE.read_text())

    # Reload paths + adapter so they pick up the tmp BIOHUB_HOME
    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import adapters.base as base_mod
    importlib.reload(base_mod)
    import adapters.apple_health.sync as ah_sync_mod
    importlib.reload(ah_sync_mod)

    # Build the health.db (DB 1 block of schema.sql)
    repo_schema = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
    schema_text = repo_schema.read_text()
    db1, _ = schema_text.split("-- DB 2:", 1) if "-- DB 2:" in schema_text else (schema_text, "")
    hconn = sqlite3.connect(tmp_path / "data" / "health.db")
    hconn.executescript(db1)
    hconn.close()

    return {
        "biohub_home": tmp_path,
        "watch": watch,
        "module": ah_sync_mod,
    }


def test_sync_ingests_fixture_into_raw_db(apple_health_env):
    mod = apple_health_env["module"]
    a = mod.AppleHealthAdapter()
    result = a.sync()
    # 31 metrics + 9 sleeps + 1 workout = 41 samples
    # 61 metric_samples + 9 sleep_samples + 1 workout = 71
    assert result.rows_inserted == 71
    assert result.error is None
    with sqlite3.connect(a.raw_db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM metric_samples").fetchone()[0] == 31 + 30
        assert conn.execute("SELECT COUNT(*) FROM sleep_samples").fetchone()[0] == 9
        assert conn.execute("SELECT COUNT(*) FROM workout_samples").fetchone()[0] == 1


def test_sync_is_idempotent_on_unchanged_files(apple_health_env):
    mod = apple_health_env["module"]
    a = mod.AppleHealthAdapter()
    a.sync()
    second = a.sync()
    # mtime hasn't changed → import_log skips → no new inserts
    assert second.rows_inserted == 0


def test_rollup_produces_apple_health_daily_metrics(apple_health_env):
    mod = apple_health_env["module"]
    a = mod.AppleHealthAdapter()
    a.sync()
    n = a.rollup_to_health_db()
    assert n == 2  # 2 days in the fixture

    with sqlite3.connect(apple_health_env["biohub_home"] / "data" / "health.db") as conn:
        rows = conn.execute(
            "SELECT date, hrv_ms, resting_hr, spo2, sleep_hours, rem_hours, "
            "       deep_sleep_hours, light_sleep_hours, steps, calories_burned, "
            "       active_minutes "
            "FROM daily_metrics WHERE source = 'apple-health' ORDER BY date"
        ).fetchall()
    assert len(rows) == 2

    d15 = rows[0]
    assert d15[0] == "2026-05-15"
    # HRV: avg of (42.5, 45.2, 48.1) = 45.27
    assert d15[1] == pytest.approx(45.27, abs=0.01)
    # Resting HR: 51 from RestingHeartRate sample (preferred over heart_rate min)
    assert d15[2] == 51
    # SpO₂: avg of (0.972, 0.968) = 0.970
    assert d15[3] == pytest.approx(0.97, abs=0.005)
    # Sleep hours: Core(1h45) + Deep(1h30) + REM(1h30) + Core(2h30) = 7h15 = 7.25h
    assert d15[4] == pytest.approx(7.25, abs=0.05)
    # REM hours: 1h30 = 1.5h
    assert d15[5] == pytest.approx(1.5, abs=0.05)
    # Deep hours: 1h30 = 1.5h
    assert d15[6] == pytest.approx(1.5, abs=0.05)
    # Light/Core hours: 1h45 + 2h30 = 4h15 = 4.25h
    assert d15[7] == pytest.approx(4.25, abs=0.05)
    # Steps: 2400 + 3100 + 2900 = 8400
    assert d15[8] == 8400
    # Calories: 180+210+240 + 1800 (basal) = 2430
    assert d15[9] == 2430
    # Active min: 42
    assert d15[10] == pytest.approx(42)


def test_rollup_skips_already_rolled_days(apple_health_env):
    mod = apple_health_env["module"]
    a = mod.AppleHealthAdapter()
    a.sync()
    a.rollup_to_health_db()
    second = a.rollup_to_health_db()
    # Last-date filter excludes everything we already rolled
    assert second == 0


# ─── v0.3: body composition + nutrition_logs rollup ──────────────────────────


def _has_body_composition_schema(health_db_path):
    """Check whether the schema applied during setup has the v0.3 tables.
    Required for the rollup tests; tests that don't need it can skip via
    a marker on the fixture."""
    import sqlite3
    with sqlite3.connect(health_db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='body_composition'"
        ).fetchone()
        return row is not None


def test_rollup_writes_body_composition_weight_with_apple_health_method(apple_health_env):
    mod = apple_health_env["module"]
    a = mod.AppleHealthAdapter()
    a.sync()
    a.rollup_to_health_db()
    health_db = apple_health_env["biohub_home"] / "data" / "health.db"
    if not _has_body_composition_schema(health_db):
        pytest.skip("body_composition table not in this test's schema")
    with sqlite3.connect(health_db) as conn:
        rows = conn.execute(
            "SELECT date, method, weight_kg FROM body_composition ORDER BY date"
        ).fetchall()
    # Fixture has 2 body_mass samples (one per day, 2026-05-15 and 2026-05-16)
    assert len(rows) == 2
    for date, method, kg in rows:
        assert method == "apple-health"
        assert kg is not None and 60 < kg < 100
    # Spot-check the values match the fixture
    assert rows[0] == ("2026-05-15", "apple-health", 75.4)
    assert rows[1] == ("2026-05-16", "apple-health", 75.1)


def test_rollup_does_not_clobber_caliper_weight(apple_health_env):
    """If a row already exists with method='jackson-pollock-7', the
    Apple-Health rollup must NOT overwrite its weight or method."""
    mod = apple_health_env["module"]
    health_db = apple_health_env["biohub_home"] / "data" / "health.db"
    if not _has_body_composition_schema(health_db):
        pytest.skip("body_composition table not in this test's schema")

    # Pre-seed a caliper row for 2026-05-15
    with sqlite3.connect(health_db) as conn:
        conn.execute("""
            INSERT INTO body_composition (date, method, weight_kg, body_fat_pct, lean_mass_kg)
            VALUES (?, 'jackson-pollock-7', 76.5, 14.2, 65.6)
        """, ("2026-05-15",))
        conn.commit()

    a = mod.AppleHealthAdapter()
    a.sync()
    a.rollup_to_health_db()

    with sqlite3.connect(health_db) as conn:
        rows = conn.execute(
            "SELECT date, method, weight_kg, body_fat_pct FROM body_composition ORDER BY date"
        ).fetchall()

    # 2026-05-15 caliper row preserved (76.5 kg, jackson-pollock-7, BF kept).
    # 2026-05-16 newly written by apple-health rollup.
    d15 = next(r for r in rows if r[0] == "2026-05-15")
    assert d15 == ("2026-05-15", "jackson-pollock-7", 76.5, 14.2)
    d16 = next(r for r in rows if r[0] == "2026-05-16")
    assert d16 == ("2026-05-16", "apple-health", 75.1, None)


def test_rollup_writes_nutrition_logs(apple_health_env):
    mod = apple_health_env["module"]
    a = mod.AppleHealthAdapter()
    a.sync()
    a.rollup_to_health_db()
    health_db = apple_health_env["biohub_home"] / "data" / "health.db"
    with sqlite3.connect(health_db) as conn:
        rows = conn.execute("""
            SELECT log_date, calories, protein_g, carbs_g, fat_g, fiber_g, water_ml
            FROM nutrition_logs WHERE meal_type = 'day_total'
            ORDER BY log_date
        """).fetchall()
    # Fixture has 2 days of macros (2026-05-15 and 2026-05-16)
    by_day = {r[0]: r for r in rows}
    assert "2026-05-15" in by_day
    assert "2026-05-16" in by_day
    # Day 15: kcal = 480 + 720 + 1050 = 2250
    assert by_day["2026-05-15"][1] == 2250
    # Day 15: protein = 35 + 50 + 65 = 150
    assert by_day["2026-05-15"][2] == 150
    # Day 15: carbs = 55 + 90 + 130 = 275
    assert by_day["2026-05-15"][3] == 275
    # Day 15: fat = 18 + 24 + 36 = 78
    assert by_day["2026-05-15"][4] == 78
    # Day 15: fiber = 8 + 11 + 9 = 28
    assert by_day["2026-05-15"][5] == 28
    # Day 15: water = (1.2 + 1.3) L → 2500 ml
    assert by_day["2026-05-15"][6] == 2500


def test_rollup_nutrition_no_duplicate_day_total_on_re_run(apple_health_env):
    """Re-running rollup must replace the day_total row, not append a duplicate."""
    mod = apple_health_env["module"]
    a = mod.AppleHealthAdapter()
    a.sync()
    a.rollup_to_health_db()
    a.rollup_to_health_db()

    health_db = apple_health_env["biohub_home"] / "data" / "health.db"
    with sqlite3.connect(health_db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM nutrition_logs "
            "WHERE log_date = '2026-05-15' AND meal_type = 'day_total'"
        ).fetchone()[0]
    assert n == 1
