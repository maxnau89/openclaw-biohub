#!/usr/bin/env python3
"""Garmin adapter — EXPERIMENTAL.

Uses the unofficial `garth` library (https://github.com/matin/garth)
which authenticates against the consumer Garmin Connect Web site,
NOT the official Garmin Health API (the latter requires a commercial
partnership). Garmin can change their internal endpoints at any time
and this adapter will break — `stability="experimental"` accordingly.

Auth: Garmin Connect email + password (no public OAuth). MFA is
handled by `garth.login()` interactively if your account has it
enabled. Tokens are cached to
$OPENCLAW_BIOHUB_HOME/secrets/garmin/ (a directory, not a single
file — garth writes multiple token files there).

Endpoints currently synced:
- Sleep (with stages + sleep score)
- Daily activity (steps, calories, intensity minutes)
- Resting heart rate
- Stress + body battery
- HRV (where available — recent watches only)
"""
from __future__ import annotations

import argparse
import getpass
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Put pipeline/ on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from adapters.base import BiometricAdapter, SyncResult
from paths import GARMIN_DB, HEALTH_DB

from .client import GarminClient

SOURCE = "garmin"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"


# ─── Schema + upserts ────────────────────────────────────────────────────────


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_FILE.read_text())


def _upsert(conn: sqlite3.Connection, table: str, cols: list[str], row: dict) -> None:
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
        [row.get(c) for c in cols],
    )


# ─── Per-endpoint parsers ────────────────────────────────────────────────────
# Garmin Connect's JSON is heavily nested and verbose. Parsers extract
# the daily fields we care about into a flat row dict.


def parse_sleep(payload: dict) -> dict | None:
    """`/wellness-service/wellness/dailySleepData/{user}` returns a dict
    with `dailySleepDTO` (totals) and `sleepLevels` (per-stage)."""
    if not payload:
        return None
    dto = payload.get("dailySleepDTO", {}) or {}
    date_str = dto.get("calendarDate")
    if not date_str:
        return None
    # Stage durations may be top-level seconds fields or nested under sleepLevels.
    return {
        "date": date_str,
        "sleep_score": (dto.get("sleepScores") or {}).get("overall", {}).get("value")
            if isinstance(dto.get("sleepScores"), dict) else None,
        "total_sleep_seconds": dto.get("sleepTimeSeconds"),
        "deep_sleep_seconds": dto.get("deepSleepSeconds"),
        "light_sleep_seconds": dto.get("lightSleepSeconds"),
        "rem_sleep_seconds": dto.get("remSleepSeconds"),
        "awake_seconds": dto.get("awakeSleepSeconds"),
        "sleep_start_gmt": dto.get("sleepStartTimestampGMT"),
        "sleep_end_gmt": dto.get("sleepEndTimestampGMT"),
        "average_respiration": dto.get("averageRespirationValue"),
        "average_spo2": dto.get("averageSpO2Value"),
        "average_hrv": dto.get("avgOvernightHrv") or dto.get("averageHrv"),
        "average_stress_during_sleep": dto.get("averageSleepStress"),
    }


def parse_activity(payload: dict) -> dict | None:
    """`/usersummary-service/usersummary/daily/{user}?calendarDate=...`
    returns a flat-ish dict per day."""
    if not payload:
        return None
    date_str = payload.get("calendarDate")
    if not date_str:
        return None
    return {
        "date": date_str,
        "total_steps": payload.get("totalSteps"),
        "total_distance_meters": payload.get("totalDistanceMeters"),
        "active_kilocalories": payload.get("activeKilocalories"),
        "bmr_kilocalories": payload.get("bmrKilocalories"),
        "sedentary_minutes": payload.get("sedentaryMinutes"),
        "moderate_intensity_minutes": payload.get("moderateIntensityMinutes"),
        "vigorous_intensity_minutes": payload.get("vigorousIntensityMinutes"),
        "floors_climbed": payload.get("floorsAscended") or payload.get("floorsClimbed"),
    }


def parse_heart_rate(payload: dict) -> dict | None:
    """Heart rate comes from the user-summary endpoint too, but separated
    here for schema clarity."""
    if not payload:
        return None
    date_str = payload.get("calendarDate")
    if not date_str:
        return None
    return {
        "date": date_str,
        "resting_heart_rate": payload.get("restingHeartRate"),
        "min_heart_rate": payload.get("minHeartRate"),
        "max_heart_rate": payload.get("maxHeartRate"),
        "last_seven_days_avg_resting_hr": payload.get("lastSevenDaysAvgRestingHeartRate"),
    }


def parse_stress(payload: dict) -> dict | None:
    """`/wellness-service/wellness/dailyStress/{date}` — average + max stress
    + body battery deltas."""
    if not payload:
        return None
    date_str = payload.get("calendarDate")
    if not date_str:
        return None
    return {
        "date": date_str,
        "average_stress_level": payload.get("avgStressLevel") or payload.get("overallStressLevel"),
        "max_stress_level": payload.get("maxStressLevel"),
        "body_battery_charged": payload.get("bodyBatteryChargedValue"),
        "body_battery_drained": payload.get("bodyBatteryDrainedValue"),
        "body_battery_highest": payload.get("bodyBatteryHighestValue"),
        "body_battery_lowest": payload.get("bodyBatteryLowestValue"),
    }


def parse_hrv(payload: dict) -> dict | None:
    """`/hrv-service/hrv/{date}` — HRV summary (rmssd) for the night."""
    if not payload:
        return None
    summary = payload.get("hrvSummary", {}) or {}
    # Some accounts return calendarDate at top level; others under hrvSummary.
    date_str = summary.get("calendarDate") or payload.get("calendarDate")
    if not date_str:
        return None
    return {
        "date": date_str,
        "weekly_avg": summary.get("weeklyAvg"),
        "last_night_avg": summary.get("lastNightAvg"),
        "last_night_5_min_high": summary.get("lastNight5MinHigh"),
        "status": summary.get("status"),
        "feedback_phrase": summary.get("feedbackPhrase"),
    }


_SLEEP_COLS = [
    "date", "sleep_score", "total_sleep_seconds", "deep_sleep_seconds",
    "light_sleep_seconds", "rem_sleep_seconds", "awake_seconds",
    "sleep_start_gmt", "sleep_end_gmt", "average_respiration",
    "average_spo2", "average_hrv", "average_stress_during_sleep",
]
_ACTIVITY_COLS = [
    "date", "total_steps", "total_distance_meters", "active_kilocalories",
    "bmr_kilocalories", "sedentary_minutes", "moderate_intensity_minutes",
    "vigorous_intensity_minutes", "floors_climbed",
]
_HEART_COLS = [
    "date", "resting_heart_rate", "min_heart_rate", "max_heart_rate",
    "last_seven_days_avg_resting_hr",
]
_STRESS_COLS = [
    "date", "average_stress_level", "max_stress_level",
    "body_battery_charged", "body_battery_drained",
    "body_battery_highest", "body_battery_lowest",
]
_HRV_COLS = [
    "date", "weekly_avg", "last_night_avg", "last_night_5_min_high",
    "status", "feedback_phrase",
]


# ─── Rollup to daily_metrics ─────────────────────────────────────────────────


_ROLLUP_SQL = """
    SELECT
        s.date                                          AS date,
        NULL                                             AS recovery_score,   -- no direct Garmin equivalent
        hrv.last_night_avg                              AS hrv_ms,
        h.resting_heart_rate                            AS resting_hr,
        s.average_spo2                                  AS spo2,
        NULL                                             AS skin_temp_c,       -- Garmin doesn't expose this in the consumer API
        s.sleep_score                                   AS sleep_performance,
        s.total_sleep_seconds / 3600.0                  AS sleep_hours,
        CASE
            WHEN (s.total_sleep_seconds + COALESCE(s.awake_seconds, 0)) > 0
            THEN CAST(s.total_sleep_seconds AS REAL) /
                 (s.total_sleep_seconds + COALESCE(s.awake_seconds, 0))
            ELSE NULL
        END                                              AS sleep_efficiency,
        s.rem_sleep_seconds / 3600.0                    AS rem_hours,
        s.deep_sleep_seconds / 3600.0                   AS deep_sleep_hours,
        s.light_sleep_seconds / 3600.0                  AS light_sleep_hours,
        NULL                                             AS day_strain,        -- not exposed
        (COALESCE(a.active_kilocalories, 0)
         + COALESCE(a.bmr_kilocalories, 0))             AS calories_burned,
        a.total_steps                                   AS steps,
        (COALESCE(a.moderate_intensity_minutes, 0)
         + COALESCE(a.vigorous_intensity_minutes, 0))   AS active_minutes
    FROM sleep_summary s
    LEFT JOIN activity_summary a    ON a.date = s.date
    LEFT JOIN heart_rate_summary h  ON h.date = s.date
    LEFT JOIN hrv_summary hrv       ON hrv.date = s.date
    WHERE s.date > ?
    ORDER BY s.date
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
            dst.execute(
                f"INSERT OR REPLACE INTO daily_metrics ({','.join(_ROLLUP_DEST_COLS)}) "
                f"VALUES ({placeholders})",
                [SOURCE] + [r[c] for c in _ROLLUP_DEST_COLS[1:]],
            )
            count += 1
        dst.commit()
        return count
    finally:
        src.close()
        dst.close()


# ─── Adapter ─────────────────────────────────────────────────────────────────


class GarminAdapter(BiometricAdapter):
    slug = "garmin"
    display_name = "Garmin Connect (experimental)"
    raw_db_name = "garmin_raw.db"
    stability = "experimental"
    requires_oauth = False  # username/password, not OAuth

    # Override secrets_path: garth writes a *directory* of token files,
    # not a single JSON file like other adapters.
    @property
    def secrets_path(self) -> Path:
        from paths import BIOHUB_HOME
        return BIOHUB_HOME / "secrets" / "garmin"

    def setup_instructions(self) -> str:
        return """\
**Garmin Connect** (⚠️ EXPERIMENTAL)

This adapter uses the unofficial `garth` library, which authenticates
against the **consumer Garmin Connect Web site** — not the official
Garmin Health API (the latter is partnership-gated). Garmin can change
their internal endpoints at any time, and this adapter will break.

**Prerequisite**: install garth.

    pip install garth

Auth flow: you'll provide your Garmin Connect email + password (not
stored on disk — only the resulting auth tokens are cached). If your
account has MFA enabled, garth will prompt for the code interactively.

Tokens are cached to `$OPENCLAW_BIOHUB_HOME/secrets/garmin/` and
refresh automatically.

Pulls sleep (with stages + sleep score), activity (steps, calories,
intensity minutes), resting heart rate, stress + body battery, and
HRV (where the watch supports it).
"""

    def configure_interactive(self) -> None:
        # Verify garth is installed up-front rather than failing during sync
        try:
            import garth  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            raise SystemExit(
                "The `garth` package is not installed. "
                "Run: pip install garth"
            )

        print("Garmin Connect credentials are used once to obtain auth tokens,")
        print("then discarded. Tokens are cached at:")
        print(f"  {self.secrets_path}")
        print()
        email = input("  Garmin Connect email: ").strip()
        password = getpass.getpass("  Password: ")
        if not (email and password):
            raise SystemExit("Missing email/password; aborting.")

        client = GarminClient(self.secrets_path)
        try:
            client.login(email, password)
        except Exception as e:
            raise SystemExit(f"Garmin login failed: {e}")
        print(f"\nSaved auth tokens to {self.secrets_path}")

    def _client(self) -> GarminClient:
        if not self.secrets_path.exists():
            raise FileNotFoundError(
                f"No Garmin tokens at {self.secrets_path}. "
                "Run `biohub connect garmin` first."
            )
        client = GarminClient(self.secrets_path)
        client.resume()
        return client

    def _date_range(self, since: str | None) -> list[date]:
        end = datetime.now(timezone.utc).date()
        if since:
            start = datetime.fromisoformat(since).date()
        else:
            start = end - timedelta(days=30)
        days: list[date] = []
        d = start
        while d <= end:
            days.append(d)
            d += timedelta(days=1)
        return days

    def sync(self, since: str | None = None, limit: int | None = None) -> SyncResult:
        client = self._client()
        # Garmin's `/usersummary-service` endpoints need the user's display name.
        # garth caches it; fetch via socialProfile.
        try:
            profile = client.connectapi("/userprofile-service/userprofile/user-profile")
            user_name = profile.get("displayName") or profile.get("userName") or ""
        except Exception:
            user_name = ""

        self.raw_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.raw_db_path)
        try:
            _ensure_schema(conn)
            inserted = 0
            days = self._date_range(since)
            if limit:
                days = days[-limit:]   # most-recent N

            for d in days:
                iso = d.isoformat()
                # Sleep
                try:
                    payload = client.connectapi(
                        f"/wellness-service/wellness/dailySleepData/{user_name}",
                        date=iso, nonSleepBufferMinutes=60,
                    )
                    row = parse_sleep(payload or {})
                    if row:
                        _upsert(conn, "sleep_summary", _SLEEP_COLS, row)
                        inserted += 1
                except Exception as e:
                    self._log(conn, "sleep", 0, False, f"{iso}: {e}")
                # Daily activity + heart rate (same endpoint payload)
                try:
                    payload = client.connectapi(
                        f"/usersummary-service/usersummary/daily/{user_name}",
                        calendarDate=iso,
                    )
                    if payload:
                        a = parse_activity(payload)
                        if a:
                            _upsert(conn, "activity_summary", _ACTIVITY_COLS, a)
                            inserted += 1
                        h = parse_heart_rate(payload)
                        if h:
                            _upsert(conn, "heart_rate_summary", _HEART_COLS, h)
                            inserted += 1
                except Exception as e:
                    self._log(conn, "activity", 0, False, f"{iso}: {e}")
                # Stress + body battery
                try:
                    payload = client.connectapi(
                        f"/wellness-service/wellness/dailyStress/{iso}",
                    )
                    row = parse_stress(payload or {})
                    if row:
                        _upsert(conn, "stress_summary", _STRESS_COLS, row)
                        inserted += 1
                except Exception as e:
                    self._log(conn, "stress", 0, False, f"{iso}: {e}")
                # HRV (recent watches only; 404 is normal)
                try:
                    payload = client.connectapi(f"/hrv-service/hrv/{iso}")
                    row = parse_hrv(payload or {})
                    if row:
                        _upsert(conn, "hrv_summary", _HRV_COLS, row)
                        inserted += 1
                except Exception:
                    # HRV endpoint 404s on devices that don't track HRV
                    pass
                conn.commit()
            self._log(conn, "all", inserted, True)
            conn.commit()
            return SyncResult(rows_inserted=inserted)
        finally:
            conn.close()

    def _log(self, conn: sqlite3.Connection, data_type: str, count: int,
             success: bool, error: str | None = None) -> None:
        conn.execute(
            "INSERT INTO download_log (data_type, records_count, success, error_message) "
            "VALUES (?,?,?,?)",
            (data_type, count, success, error),
        )

    def rollup_to_health_db(self) -> int:
        return _rollup(self.raw_db_path, HEALTH_DB)


def main() -> int:
    parser = argparse.ArgumentParser(description="Garmin Connect sync (experimental)")
    parser.add_argument("--since", help="ISO date YYYY-MM-DD to start from")
    parser.add_argument("--limit", type=int, help="Max days (debugging)")
    args = parser.parse_args()

    print("⚠️  Garmin adapter is EXPERIMENTAL. Garmin may break this at any time.")
    print(f"Garmin Sync — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    adapter = GarminAdapter()
    result = adapter.sync(since=args.since, limit=args.limit)
    try:
        rolled = adapter.rollup_to_health_db()
        print(f"  Rolled up {rolled} rows to daily_metrics (source=garmin)")
    except Exception as e:
        print(f"  Rollup error: {e}")
    print(f"\nDone. {result}")
    return 0 if not result.error else 1


if __name__ == "__main__":
    sys.exit(main())
