#!/usr/bin/env python3
"""One-shot migration from the legacy OpenClaw workspace health tooling
into biohub's per-adapter database layout.

The private OpenClaw wellness setup kept everything in two databases:
  • whoop_analytics.db — WHOOP raw tables + a `cgm_glucose` table
  • healthkit.db       — a flat `metrics` table (one row per sample)

biohub instead uses per-adapter raw DBs under $OPENCLAW_BIOHUB_HOME/data/.
This script populates them, then rolls up into the source-agnostic
health.db via the adapters' own rollup logic (so the projection is
identical to a normal sync). Idempotent-ish: it INSERT OR IGNOREs, so
re-running won't duplicate, but it does not delete.

Usage:
    OPENCLAW_BIOHUB_HOME=~/openclaw-biohub-data \
    python3 scripts/migrate_from_openclaw_workspace.py \
        --whoop-analytics ~/.openclaw/workspace/whoop_analytics.db \
        --healthkit       ~/.openclaw/workspace/data/healthkit/healthkit.db

Run from the repo root (needs pipeline/ + db/schema.sql on disk).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

from paths import (  # noqa: E402
    APPLE_HEALTH_DB, HEALTH_DB, LIBRE_DB, WHOOP_DB,
)

SCHEMA = REPO_ROOT / "db" / "schema.sql"
LIBRE_SCHEMA = REPO_ROOT / "pipeline" / "adapters" / "libre" / "schema.sql"
APPLE_SCHEMA = REPO_ROOT / "pipeline" / "adapters" / "apple_health" / "schema.sql"

# WHOOP tables that are column-identical between the legacy DB and biohub's
# whoop_raw.db (biohub's schema was derived from these).
_WHOOP_TABLES = [
    "user_profile", "body_measurements", "recovery_data",
    "sleep_data", "workout_data", "cycles_data",
]


def _db2_ddl() -> str:
    """The whoop_raw.db section of schema.sql. Splitting on the marker leaves
    the tail of that comment line ('whoop_raw.db (was …)') as non-comment
    text, so drop it — the remaining lines are valid DDL / SQL comments."""
    tail = SCHEMA.read_text().split("-- DB 2:", 1)[1]
    return tail.split("\n", 1)[1]


def snapshot(src: Path, tmpdir: Path) -> Path:
    """Consistent read-only copy of a live SQLite DB via the online backup API.

    The legacy source DBs (whoop_analytics.db, healthkit.db) are written by the
    running OpenClaw sync jobs. Reading them directly with ATTACH holds a lock
    that can make a concurrent writer fail with "database is locked". The backup
    API copies a consistent snapshot in chunks, yielding to writers, so the live
    sync is never blocked. Migrations then read from the copy — zero contention.
    """
    dst = tmpdir / (src.stem + "-snap.db")
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        d = sqlite3.connect(dst)
        try:
            s.backup(d)
        finally:
            d.close()
    finally:
        s.close()
    return dst


def _init(db_path: Path, ddl: str) -> sqlite3.Connection:
    # Make the DDL idempotent so the migration is safe to re-run (e.g. to pull
    # in a newly-added source). Guard against double-inserting IF NOT EXISTS on
    # schemas that already have it (libre / apple_health).
    import re
    ddl = re.sub(r"CREATE TABLE (?!IF NOT EXISTS)", "CREATE TABLE IF NOT EXISTS ", ddl)
    ddl = re.sub(r"CREATE INDEX (?!IF NOT EXISTS)", "CREATE INDEX IF NOT EXISTS ", ddl)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(ddl)
    return conn


def _cols(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def migrate_whoop(src: Path) -> dict:
    conn = _init(WHOOP_DB, _db2_ddl())
    conn.execute("ATTACH DATABASE ? AS src", (str(src),))
    counts = {}
    for t in _WHOOP_TABLES:
        exists = conn.execute(
            "SELECT 1 FROM src.sqlite_master WHERE type='table' AND name=?", (t,)
        ).fetchone()
        if not exists:
            continue
        # Intersect columns so a schema drift on either side can't break the copy.
        common = [c for c in _cols(conn, t) if c in set(
            r[1] for r in conn.execute(f"PRAGMA src.table_info({t})"))]
        collist = ",".join(common)
        conn.execute(f"INSERT OR IGNORE INTO {t} ({collist}) SELECT {collist} FROM src.{t}")
        counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    conn.commit()
    conn.execute("DETACH DATABASE src")
    conn.close()
    return counts


def migrate_glucose(src: Path) -> dict:
    conn = _init(LIBRE_DB, LIBRE_SCHEMA.read_text())
    conn.execute("ATTACH DATABASE ? AS src", (str(src),))
    if not conn.execute(
        "SELECT 1 FROM src.sqlite_master WHERE type='table' AND name='cgm_glucose'"
    ).fetchone():
        conn.execute("DETACH DATABASE src")
        conn.close()
        return {"glucose_data": 0}
    # Copy the raw dual-column table verbatim for fidelity.
    conn.execute(
        "INSERT OR IGNORE INTO cgm_glucose "
        "(device, serial_number, timestamp, record_type, glucose_history_mgdl, glucose_scan_mgdl) "
        "SELECT device, serial_number, timestamp, record_type, glucose_history_mgdl, glucose_scan_mgdl "
        "FROM src.cgm_glucose"
    )
    # Project into the single-value glucose_data that glucose_analytics.py reads.
    conn.execute(
        "INSERT OR IGNORE INTO glucose_data "
        "(device, serial_number, timestamp, record_type, glucose_mgdl, source) "
        "SELECT device, serial_number, timestamp, record_type, "
        "       COALESCE(glucose_history_mgdl, glucose_scan_mgdl), 'libreview' "
        "FROM src.cgm_glucose "
        "WHERE COALESCE(glucose_history_mgdl, glucose_scan_mgdl) IS NOT NULL"
    )
    n = conn.execute("SELECT COUNT(*) FROM glucose_data").fetchone()[0]
    conn.commit()
    conn.execute("DETACH DATABASE src")
    conn.close()
    return {"glucose_data": n}


def migrate_healthkit(src: Path) -> dict:
    conn = _init(APPLE_HEALTH_DB, APPLE_SCHEMA.read_text())
    conn.execute("ATTACH DATABASE ? AS src", (str(src),))
    # Legacy `metrics(metric_name, ts, value, unit, source)` →
    # biohub `metric_samples(id, metric_name, date, value, unit, source)`.
    conn.execute(
        "INSERT OR IGNORE INTO metric_samples (id, metric_name, date, value, unit, source) "
        "SELECT metric_name || ':' || ts, metric_name, ts, value, unit, source "
        "FROM src.metrics WHERE value IS NOT NULL"
    )
    n = conn.execute("SELECT COUNT(*) FROM metric_samples").fetchone()[0]
    conn.commit()
    conn.execute("DETACH DATABASE src")
    conn.close()
    return {"metric_samples": n}


def migrate_body_composition(src: Path) -> dict:
    """The legacy healthkit.db carries a `body_composition` table whose schema
    is identical to biohub's (date-keyed, skinfolds + BF% + lean/fat mass).
    Copy it straight into health.db so the physiological-age lean-mass marker
    and the body-comp simulator have history. No-op if the source lacks it."""
    conn = _init(HEALTH_DB, SCHEMA.read_text().split("-- DB 2:")[0])
    conn.execute("ATTACH DATABASE ? AS src", (str(src),))
    has = conn.execute(
        "SELECT 1 FROM src.sqlite_master WHERE type='table' AND name='body_composition'"
    ).fetchone()
    n = 0
    if has:
        cols = ("date, method, body_fat_pct, weight_kg, lean_mass_kg, fat_mass_kg, "
                "chest_mm, abdominal_mm, thigh_mm, tricep_mm, subscapular_mm, "
                "suprailiac_mm, midaxillary_mm, notes")
        conn.execute(
            f"INSERT OR IGNORE INTO body_composition ({cols}) SELECT {cols} FROM src.body_composition"
        )
        n = conn.execute("SELECT COUNT(*) FROM body_composition").fetchone()[0]
    conn.commit()
    conn.execute("DETACH DATABASE src")
    conn.close()
    return {"body_composition": n}


def migrate_mission_control(src: Path) -> dict:
    """Blood panels + supplements live in the legacy mission-control.db, whose
    schemas are identical to biohub's health.db. Copy them straight in. No-op
    for tables the source lacks."""
    conn = _init(HEALTH_DB, SCHEMA.read_text().split("-- DB 2:")[0])
    conn.execute("ATTACH DATABASE ? AS mc", (str(src),))
    out = {}
    specs = {
        "blood_panels": "id, panel_date, lab_name, notes, source_filename, raw_text, created_at",
        "blood_markers": "id, panel_id, marker_name, value, unit, ref_low, ref_high, status, created_at",
        "supplements": ("id, name, active_ingredient, brand, dose_mg, dose_unit, form, "
                        "amazon_asin, default_lag_hours, notes, created_at"),
        "supplement_log": ("id, supplement_id, taken_at, dose_mg, dose_unit, notes, source, "
                           "intake_start, intake_end, duration_days, is_period, amazon_order_id, created_at"),
    }
    for table, cols in specs.items():
        has = conn.execute(
            "SELECT 1 FROM mc.sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not has:
            continue
        conn.execute(f"INSERT OR IGNORE INTO {table} ({cols}) SELECT {cols} FROM mc.{table}")
        out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.commit()
    conn.execute("DETACH DATABASE mc")
    conn.close()
    return out


def migrate_phases(src: Path) -> dict:
    """The legacy healthkit.db models user-defined windows as two tables:
    `training_blocks` (periodisation blocks) and `interventions` (supplement /
    medication courses). biohub unifies them as `tracking_phases`. Map both.
    Deduped on (name, start_date); rows without a start_date are skipped
    (tracking_phases.start_date is NOT NULL)."""
    conn = _init(HEALTH_DB, SCHEMA.read_text().split("-- DB 2:")[0])
    conn.execute("ATTACH DATABASE ? AS hk", (str(src),))

    def _has(t: str) -> bool:
        return bool(conn.execute(
            "SELECT 1 FROM hk.sqlite_master WHERE type='table' AND name=?", (t,)
        ).fetchone())

    def _add(name, category, start_date, end_date, notes) -> int:
        if not name or not start_date:
            return 0
        if conn.execute(
            "SELECT 1 FROM tracking_phases WHERE name=? AND start_date=?",
            (name, start_date),
        ).fetchone():
            return 0
        conn.execute(
            "INSERT INTO tracking_phases (name, category, start_date, end_date, notes) "
            "VALUES (?,?,?,?,?)",
            (name, category, start_date, end_date or None, notes or None),
        )
        return 1

    n = 0
    if _has("training_blocks"):
        for name, sd, ed, goal, notes in conn.execute(
            "SELECT name, start_date, end_date, goal, notes FROM hk.training_blocks"
        ).fetchall():
            note = " · ".join(x for x in (goal, notes) if x)
            n += _add(name, "training", sd, ed, note)
    if _has("interventions"):
        for compound, cat, sd, ed, dose, notes in conn.execute(
            "SELECT compound, category, start_date, end_date, dose, notes FROM hk.interventions"
        ).fetchall():
            note = " · ".join(x for x in (dose, notes) if x)
            n += _add(compound or cat or "intervention", cat or "intervention", sd, ed, note)

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM tracking_phases").fetchone()[0]
    conn.execute("DETACH DATABASE hk")
    conn.close()
    return {"tracking_phases_added": n, "tracking_phases_total": total}


def rollup() -> dict:
    """Project raw DBs into health.db using each adapter's own rollup."""
    _init(HEALTH_DB, SCHEMA.read_text().split("-- DB 2:")[0]).close()
    sys.path.insert(0, str(REPO_ROOT))
    from biohub.registry import get_adapter
    out = {}
    for slug in ("whoop", "apple-health"):
        try:
            out[slug] = get_adapter(slug).rollup_to_health_db()
        except Exception as e:  # noqa: BLE001
            out[slug] = f"ERROR: {e}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--whoop-analytics", type=Path, required=True)
    ap.add_argument("--healthkit", type=Path)
    ap.add_argument("--mission-control", type=Path,
                    help="Legacy mission-control.db (blood panels + supplements)")
    ap.add_argument("--snapshot", action="store_true",
                    help="Copy each source DB (online backup) before reading, so a "
                         "concurrent live writer is never locked. Use for scheduled re-syncs.")
    ap.add_argument("--skip-rollup", action="store_true")
    args = ap.parse_args()

    tmpctx = tempfile.TemporaryDirectory(prefix="biohub-snap-") if args.snapshot else None
    tmpdir = Path(tmpctx.name) if tmpctx else None

    def src(p: Path | None) -> Path | None:
        if p is None or not p.exists():
            return p
        return snapshot(p, tmpdir) if tmpdir else p

    try:
        whoop_src = src(args.whoop_analytics)
        print(f"→ whoop_raw.db  : {WHOOP_DB}" + ("  (snapshot)" if args.snapshot else ""))
        print("  " + str(migrate_whoop(whoop_src)))
        print(f"→ libre_raw.db  : {LIBRE_DB}")
        print("  " + str(migrate_glucose(whoop_src)))
        if args.healthkit and args.healthkit.exists():
            hk_src = src(args.healthkit)
            print(f"→ apple_health_raw.db : {APPLE_HEALTH_DB}")
            print("  " + str(migrate_healthkit(hk_src)))
            print(f"→ health.db body_composition : {HEALTH_DB}")
            print("  " + str(migrate_body_composition(hk_src)))
            print(f"→ health.db tracking_phases : {HEALTH_DB}")
            print("  " + str(migrate_phases(hk_src)))
        if args.mission_control and args.mission_control.exists():
            print(f"→ health.db blood + supplements : {HEALTH_DB}")
            print("  " + str(migrate_mission_control(src(args.mission_control))))
        if not args.skip_rollup:
            print(f"→ health.db rollup : {HEALTH_DB}")
            print("  " + str(rollup()))
        print("done.")
    finally:
        if tmpctx:
            tmpctx.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
