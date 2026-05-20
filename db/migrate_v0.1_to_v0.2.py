#!/usr/bin/env python3
"""Migrate an openclaw-biohub v0.1 health.db to v0.2.

v0.1 had a single `whoop_daily` table. v0.2 renames it to `daily_metrics`
with a `source` column (primary key `(source, date)`) so that future
adapters (Oura, Fitbit, …) can write to the same table.

This script is idempotent — running it twice is a no-op.

Usage:
    python3 db/migrate_v0.1_to_v0.2.py [path-to-health.db]

Default path: $OPENCLAW_BIOHUB_HOME/data/health.db (or /opt/openclaw-biohub/data/health.db).
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path


def default_db_path() -> Path:
    home = Path(os.environ.get("OPENCLAW_BIOHUB_HOME", "/opt/openclaw-biohub"))
    return home / "data" / "health.db"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def migrate(db_path: Path) -> int:
    """Run the v0.1 → v0.2 migration. Returns rows migrated."""
    if not db_path.exists():
        print(f"  No DB at {db_path}; nothing to migrate.")
        return 0

    conn = sqlite3.connect(db_path)
    try:
        has_old = _table_exists(conn, "whoop_daily")
        has_new = _table_exists(conn, "daily_metrics")

        if has_new and not has_old:
            print("  Already on v0.2 schema (daily_metrics exists, no whoop_daily). Skipping.")
            return 0

        if not has_old:
            print(f"  No `whoop_daily` table in {db_path}; nothing to migrate.")
            return 0

        print(f"  Migrating {db_path}: whoop_daily → daily_metrics")
        conn.execute("BEGIN")

        if not has_new:
            conn.execute("""
                CREATE TABLE daily_metrics (
                    source TEXT NOT NULL,
                    date TEXT NOT NULL,
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
                    steps INTEGER,
                    active_minutes INTEGER,
                    notes TEXT,
                    created_at INTEGER DEFAULT (strftime('%s','now') * 1000),
                    PRIMARY KEY (source, date)
                )
            """)
            conn.execute("CREATE INDEX idx_daily_metrics_date ON daily_metrics(date DESC)")
            conn.execute("CREATE INDEX idx_daily_metrics_source ON daily_metrics(source)")

        rows = conn.execute("""
            INSERT OR IGNORE INTO daily_metrics
                (source, date, recovery_score, hrv_ms, resting_hr, spo2, skin_temp_c,
                 sleep_performance, sleep_hours, sleep_efficiency, rem_hours,
                 deep_sleep_hours, light_sleep_hours, day_strain, calories_burned,
                 notes, created_at)
            SELECT 'whoop', date, recovery_score, hrv_ms, resting_hr, spo2, skin_temp_c,
                   sleep_performance, sleep_hours, sleep_efficiency, rem_hours,
                   deep_sleep_hours, light_sleep_hours, day_strain, calories_burned,
                   notes, created_at
            FROM whoop_daily
        """).rowcount

        conn.execute("DROP TABLE whoop_daily")
        conn.commit()
        print(f"  Migrated {rows} rows; dropped whoop_daily.")
        return rows
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_db_path()
    print(f"openclaw-biohub: v0.1 → v0.2 migration")
    print(f"Target: {db_path}")
    rows = migrate(db_path)
    print(f"Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
