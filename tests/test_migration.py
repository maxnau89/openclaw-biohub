"""Round-trip test for the v0.1 → v0.2 migration script."""
import importlib.util
import sqlite3
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = REPO_ROOT / "db" / "migrate_v0.1_to_v0.2.py"


def _load_migrate_module():
    spec = importlib.util.spec_from_file_location("migrate_v0_1_to_v0_2", MIGRATE_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# v0.1 schema for `whoop_daily` (verbatim from the v0.1 schema.sql)
V0_1_SCHEMA = """
CREATE TABLE whoop_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    recovery_score INTEGER,
    hrv_ms REAL,
    resting_hr INTEGER,
    spo2 REAL,
    skin_temp_c REAL,
    sleep_performance INTEGER,
    sleep_hours REAL,
    sleep_efficiency REAL,
    rem_hours REAL,
    deep_sleep_hours REAL,
    light_sleep_hours REAL,
    day_strain REAL,
    calories_burned INTEGER,
    notes TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
"""


def _make_v01_db(tmp_path: Path, n_rows: int = 5) -> Path:
    db = tmp_path / "health.db"
    conn = sqlite3.connect(db)
    conn.executescript(V0_1_SCHEMA)
    for i in range(n_rows):
        conn.execute(
            "INSERT INTO whoop_daily (date, recovery_score, hrv_ms, sleep_hours) "
            "VALUES (?, ?, ?, ?)",
            (f"2026-04-{i + 1:02d}", 60 + i, 55.0 + i, 7.0 + i * 0.1),
        )
    conn.commit()
    conn.close()
    return db


def test_migration_creates_daily_metrics_and_preserves_rows(tmp_path):
    mod = _load_migrate_module()
    db = _make_v01_db(tmp_path, n_rows=10)

    migrated = mod.migrate(db)
    assert migrated == 10

    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "daily_metrics" in tables
        assert "whoop_daily" not in tables  # dropped

        rows = conn.execute(
            "SELECT source, date, recovery_score FROM daily_metrics ORDER BY date"
        ).fetchall()
        assert len(rows) == 10
        for source, date, recovery in rows:
            assert source == "whoop"
            assert date
            assert recovery is not None


def test_migration_is_idempotent(tmp_path):
    """Running migration twice on the same DB must not lose or duplicate rows."""
    mod = _load_migrate_module()
    db = _make_v01_db(tmp_path, n_rows=5)
    assert mod.migrate(db) == 5
    # Second run: whoop_daily is gone, daily_metrics is present
    assert mod.migrate(db) == 0
    with sqlite3.connect(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0]
        assert n == 5


def test_migration_on_fresh_db_is_noop(tmp_path):
    """A DB that never had v0.1 schema should pass through cleanly."""
    mod = _load_migrate_module()
    # Empty DB
    db = tmp_path / "fresh.db"
    sqlite3.connect(db).close()
    assert mod.migrate(db) == 0


def test_migration_on_missing_db(tmp_path):
    mod = _load_migrate_module()
    assert mod.migrate(tmp_path / "does-not-exist.db") == 0
