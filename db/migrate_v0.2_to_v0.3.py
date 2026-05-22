#!/usr/bin/env python3
"""Migrate an openclaw-biohub v0.2 health.db to v0.3.

v0.3 adds two tables to `health.db`:

  - `body_composition` — daily caliper / scale / Apple-Health weight
  - `tracking_phases` — user-defined windows (bulks, cuts, training
    blocks, supplement cycles, medication courses, lifestyle phases)

This script is idempotent — running it twice is a no-op. It does not
touch any data; it only creates the two new tables if they don't yet
exist.

Usage:
    python3 db/migrate_v0.2_to_v0.3.py [path-to-health.db]

Default path: $OPENCLAW_BIOHUB_HOME/data/health.db
              (or /opt/openclaw-biohub/data/health.db).
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


_BODY_COMPOSITION_DDL = """
CREATE TABLE body_composition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    method TEXT,
    body_fat_pct REAL,
    weight_kg REAL,
    lean_mass_kg REAL,
    fat_mass_kg REAL,
    chest_mm REAL,
    abdominal_mm REAL,
    thigh_mm REAL,
    tricep_mm REAL,
    subscapular_mm REAL,
    suprailiac_mm REAL,
    midaxillary_mm REAL,
    notes TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
)
"""

_TRACKING_PHASES_DDL = """
CREATE TABLE tracking_phases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT,
    color TEXT,
    notes TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
)
"""


def migrate(db_path: Path) -> dict[str, bool]:
    """Run the v0.2 → v0.3 migration. Returns a dict of {table_name: created_now}."""
    result = {"body_composition": False, "tracking_phases": False}

    if not db_path.exists():
        print(f"  No DB at {db_path}; nothing to migrate.")
        return result

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN")
        if not _table_exists(conn, "body_composition"):
            conn.execute(_BODY_COMPOSITION_DDL)
            conn.execute("CREATE INDEX idx_body_composition_date ON body_composition(date)")
            result["body_composition"] = True
            print("  Created body_composition table + idx_body_composition_date")
        else:
            print("  body_composition already exists; skipping")

        if not _table_exists(conn, "tracking_phases"):
            conn.execute(_TRACKING_PHASES_DDL)
            conn.execute(
                "CREATE INDEX idx_tracking_phases_dates "
                "ON tracking_phases(start_date, end_date)"
            )
            result["tracking_phases"] = True
            print("  Created tracking_phases table + idx_tracking_phases_dates")
        else:
            print("  tracking_phases already exists; skipping")
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_db_path()
    print(f"openclaw-biohub: v0.2 → v0.3 migration")
    print(f"Target: {db_path}")
    migrate(db_path)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
