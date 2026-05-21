#!/usr/bin/env python3
"""Oura Ring adapter — pulls daily sleep / readiness / activity / SpO₂ /
sleep sessions / workouts via the official Oura API v2.

Auth: Personal Access Token (PAT) from
<https://cloud.ouraring.com/personal-access-tokens>. No OAuth flow.
The PAT is saved to $OPENCLAW_BIOHUB_HOME/secrets/oura.json.

Run as a standalone sync (cron-friendly):
    python3 pipeline/adapters/oura/sync.py [--since YYYY-MM-DD] [--limit N]

Or import and use as an adapter:
    from pipeline.adapters.oura import OuraAdapter
    OuraAdapter().sync()
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Put pipeline/ on sys.path so we can import paths.py + adapters.base
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from adapters.base import BiometricAdapter, SyncResult
from paths import HEALTH_DB, OURA_DB

from .client import OuraClient

SOURCE = "oura"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"


# ─── Mapping helpers ─────────────────────────────────────────────────────────

def _flatten_contributors(row: dict) -> dict:
    """Promote `row['contributors']` keys into the top-level dict under
    `contributors_<key>` so column names match the schema."""
    out = dict(row)
    contribs = out.pop("contributors", {}) or {}
    for k, v in contribs.items():
        out[f"contributors_{k}"] = v
    return out


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Apply schema.sql; idempotent thanks to `IF NOT EXISTS`."""
    conn.executescript(SCHEMA_FILE.read_text())


def _upsert(conn: sqlite3.Connection, table: str, columns: list[str], row: dict) -> int:
    """INSERT OR REPLACE one row into `table`. Missing columns become NULL."""
    values = [row.get(c) for c in columns]
    placeholders = ",".join("?" for _ in columns)
    col_list = ",".join(columns)
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})",
        values,
    )
    return 1


# Column lists per table (match schema.sql; created_at is auto-populated)
_DAILY_SLEEP_COLS = [
    "id", "day", "score", "timestamp",
    "contributors_deep_sleep", "contributors_efficiency", "contributors_latency",
    "contributors_rem_sleep", "contributors_restfulness", "contributors_timing",
    "contributors_total_sleep",
]
_SLEEP_SESSION_COLS = [
    "id", "day", "bedtime_start", "bedtime_end", "type",
    "total_sleep_duration", "awake_time", "light_sleep_duration",
    "rem_sleep_duration", "deep_sleep_duration", "time_in_bed",
    "sleep_efficiency", "latency", "average_breath", "average_heart_rate",
    "lowest_heart_rate", "average_hrv", "restless_periods",
]
_DAILY_READINESS_COLS = [
    "id", "day", "score", "temperature_deviation",
    "temperature_trend_deviation", "timestamp",
    "contributors_activity_balance", "contributors_body_temperature",
    "contributors_hrv_balance", "contributors_previous_day_activity",
    "contributors_previous_night", "contributors_recovery_index",
    "contributors_resting_heart_rate", "contributors_sleep_balance",
]
_DAILY_ACTIVITY_COLS = [
    "id", "day", "score", "steps", "active_calories", "total_calories",
    "target_calories", "equivalent_walking_distance", "high_activity_time",
    "medium_activity_time", "low_activity_time", "sedentary_time",
    "non_wear_time", "resting_time", "average_met_minutes", "timestamp",
]
_DAILY_SPO2_COLS = [
    "id", "day", "spo2_percentage_average", "spo2_percentage_lowest",
    "breathing_disturbance_index",
]
_WORKOUT_COLS = [
    "id", "day", "activity", "start_datetime", "end_datetime",
    "distance", "calories", "intensity", "label", "source",
]


def _resync_endpoint(
    conn: sqlite3.Connection,
    client: OuraClient,
    path: str,
    table: str,
    columns: list[str],
    flatten: bool,
    params: dict,
    limit: int | None = None,
) -> int:
    """Pull all rows from one Oura endpoint into `table`. Returns count."""
    count = 0
    for raw in client.get(path, params):
        row = _flatten_contributors(raw) if flatten else raw
        # /daily_spo2 nests spo2_percentage as a dict — flatten that one too
        if path == "daily_spo2" and isinstance(row.get("spo2_percentage"), dict):
            sp = row.pop("spo2_percentage")
            row["spo2_percentage_average"] = sp.get("average")
            row["spo2_percentage_lowest"] = sp.get("lowest")
        _upsert(conn, table, columns, row)
        count += 1
        if limit and count >= limit:
            break
    return count


# ─── Rollup to daily_metrics ─────────────────────────────────────────────────

_ROLLUP_SQL = """
    SELECT
        ds.day                              AS date,
        dr.score                            AS recovery_score,
        ss.average_hrv                      AS hrv_ms,
        ss.lowest_heart_rate                AS resting_hr,
        sp.spo2_percentage_average          AS spo2,
        dr.temperature_deviation            AS skin_temp_c,
        ds.score                            AS sleep_performance,
        ss.total_sleep_duration / 3600.0    AS sleep_hours,
        ss.sleep_efficiency                 AS sleep_efficiency,
        ss.rem_sleep_duration / 3600.0      AS rem_hours,
        ss.deep_sleep_duration / 3600.0     AS deep_sleep_hours,
        ss.light_sleep_duration / 3600.0    AS light_sleep_hours,
        NULL                                AS day_strain,    -- Oura has no direct strain analogue
        da.total_calories                   AS calories_burned,
        da.steps                            AS steps,
        ((COALESCE(da.high_activity_time, 0)
           + COALESCE(da.medium_activity_time, 0)
           + COALESCE(da.low_activity_time, 0)) / 60.0) AS active_minutes
    FROM daily_sleep ds
    LEFT JOIN daily_readiness dr ON dr.day = ds.day
    LEFT JOIN daily_activity  da ON da.day = ds.day
    LEFT JOIN daily_spo2      sp ON sp.day = ds.day
    LEFT JOIN sleep_session   ss ON ss.day = ds.day AND ss.type = 'long_sleep'
    WHERE ds.day > ?
    ORDER BY ds.day
"""

_ROLLUP_DEST_COLS = [
    "source", "date", "recovery_score", "hrv_ms", "resting_hr", "spo2",
    "skin_temp_c", "sleep_performance", "sleep_hours", "sleep_efficiency",
    "rem_hours", "deep_sleep_hours", "light_sleep_hours", "day_strain",
    "calories_burned", "steps", "active_minutes",
]


def _rollup(raw_db: Path, health_db: Path) -> int:
    if not raw_db.exists() or not health_db.exists():
        return 0
    src = sqlite3.connect(raw_db)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(health_db)
    try:
        last = dst.execute(
            "SELECT MAX(date) FROM daily_metrics WHERE source = ?", (SOURCE,)
        ).fetchone()[0] or "2000-01-01"
        rows = src.execute(_ROLLUP_SQL, (last,)).fetchall()
        count = 0
        for r in rows:
            placeholders = ",".join("?" for _ in _ROLLUP_DEST_COLS)
            col_list = ",".join(_ROLLUP_DEST_COLS)
            dst.execute(
                f"INSERT OR REPLACE INTO daily_metrics ({col_list}) VALUES ({placeholders})",
                [SOURCE] + [r[c] for c in _ROLLUP_DEST_COLS[1:]],
            )
            count += 1
        dst.commit()
        return count
    finally:
        src.close()
        dst.close()


# ─── Adapter ─────────────────────────────────────────────────────────────────

class OuraAdapter(BiometricAdapter):
    slug = "oura"
    display_name = "Oura Ring"
    raw_db_name = "oura_raw.db"
    stability = "stable"
    requires_oauth = False

    def setup_instructions(self) -> str:
        return """\
**Oura Ring** pulls daily readiness, sleep score + stages, HRV,
resting heart rate, SpO₂, activity (steps + calories), and workout
sessions via the official Oura API v2.

Setup is one step:

1. Go to <https://cloud.ouraring.com/personal-access-tokens> and click
   *Create New Personal Access Token*. Give it any name (e.g.
   "openclaw-biohub"). Copy the token — it is shown only once.

That's it — no OAuth flow, no app registration. The PAT is your
personal credential and grants access to your own data only.
"""

    def configure_interactive(self) -> None:
        token = getpass.getpass("  Paste your Oura Personal Access Token: ").strip()
        if not token:
            raise SystemExit("No token provided; aborting.")
        self.secrets_path.parent.mkdir(parents=True, exist_ok=True)
        self.secrets_path.write_text(json.dumps({"access_token": token}))
        self.secrets_path.chmod(0o600)
        print(f"Saved to {self.secrets_path}")

    def _load_token(self) -> str:
        if not self.secrets_path.exists():
            raise FileNotFoundError(
                f"No Oura credentials at {self.secrets_path}. "
                "Run `biohub connect oura` first."
            )
        return json.loads(self.secrets_path.read_text())["access_token"]

    def sync(self, since: str | None = None, limit: int | None = None) -> SyncResult:
        token = self._load_token()
        client = OuraClient(token)

        self.raw_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.raw_db_path)
        try:
            _ensure_schema(conn)

            # If no `since` given, default to last sync's max(day) per table,
            # else 30 days back as a safe initial.
            cur = conn.execute("SELECT MAX(day) FROM daily_sleep")
            last_day = since or cur.fetchone()[0] or (
                (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()
            )
            today = datetime.now(timezone.utc).date().isoformat()
            params = {"start_date": last_day, "end_date": today}

            inserted = 0
            for path, table, cols, flatten in [
                ("daily_sleep",     "daily_sleep",     _DAILY_SLEEP_COLS,     True),
                ("sleep",           "sleep_session",   _SLEEP_SESSION_COLS,   False),
                ("daily_readiness", "daily_readiness", _DAILY_READINESS_COLS, True),
                ("daily_activity",  "daily_activity",  _DAILY_ACTIVITY_COLS,  False),
                ("daily_spo2",      "daily_spo2",      _DAILY_SPO2_COLS,      False),
                ("workout",         "workout",         _WORKOUT_COLS,         False),
            ]:
                try:
                    n = _resync_endpoint(conn, client, path, table, cols, flatten, params, limit)
                    inserted += n
                    conn.execute(
                        "INSERT INTO download_log (data_type, records_count, success) VALUES (?,?,?)",
                        (path, n, True),
                    )
                    conn.commit()
                except Exception as e:
                    conn.execute(
                        "INSERT INTO download_log (data_type, records_count, success, error_message) "
                        "VALUES (?,?,?,?)",
                        (path, 0, False, str(e)),
                    )
                    conn.commit()
                    return SyncResult(rows_inserted=inserted, error=f"{path}: {e}")

            return SyncResult(rows_inserted=inserted)
        finally:
            conn.close()

    def rollup_to_health_db(self) -> int:
        return _rollup(self.raw_db_path, HEALTH_DB)


def main() -> int:
    parser = argparse.ArgumentParser(description="Oura Ring sync")
    parser.add_argument("--since", help="ISO date YYYY-MM-DD to start from")
    parser.add_argument("--limit", type=int, help="Max records per endpoint (debugging)")
    args = parser.parse_args()

    print(f"Oura Sync — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    adapter = OuraAdapter()
    result = adapter.sync(since=args.since, limit=args.limit)
    try:
        rolled = adapter.rollup_to_health_db()
        print(f"  Rolled up {rolled} rows to daily_metrics (source=oura)")
    except Exception as e:
        print(f"  Rollup error: {e}")
    print(f"\nDone. {result}")
    return 0 if not result.error else 1


if __name__ == "__main__":
    sys.exit(main())
