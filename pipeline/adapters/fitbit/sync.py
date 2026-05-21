#!/usr/bin/env python3
"""Fitbit adapter — pulls sleep, heart-rate summary, activity, SpO₂,
HRV, skin temperature, and body weight via the Fitbit Web API.

Auth: OAuth 2.0. The user registers an app at
<https://dev.fitbit.com/apps>, picks "Personal" application type,
sets the callback URL to `http://localhost:8894/fitbit/callback`,
then runs `biohub connect fitbit` which:

  1. Opens the authorize URL in a browser
  2. Spins a one-shot localhost HTTP server on :8894 to catch the
     redirect with the auth code
  3. Exchanges the code for tokens (HTTP Basic + client_secret)
  4. Saves credentials to $OPENCLAW_BIOHUB_HOME/secrets/fitbit.json

Subsequent syncs auto-refresh the access token (8h TTL; refresh
tokens rotate on each refresh).
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sqlite3
import sys
import urllib.parse
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Put pipeline/ on sys.path for paths + adapters.base
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from adapters._oauth_helpers import (
    build_authorize_url,
    exchange_code_for_tokens,
    save_credentials,
)
from adapters.base import BiometricAdapter, SyncResult
from paths import FITBIT_DB, HEALTH_DB

from .client import AUTHORIZE_URL, DEFAULT_SCOPES, TOKEN_URL, FitbitClient

SOURCE = "fitbit"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"
DEFAULT_CALLBACK_PORT = 8894


# ─── Schema + DB helpers ─────────────────────────────────────────────────────


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_FILE.read_text())


def _upsert(conn: sqlite3.Connection, table: str, cols: list[str], row: dict) -> None:
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
        [row.get(c) for c in cols],
    )


# ─── Per-endpoint parsers ────────────────────────────────────────────────────
# Each takes raw Fitbit JSON and returns a list of rows ready for _upsert.


def parse_sleep(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for entry in payload.get("sleep", []) or []:
        levels = entry.get("levels", {}) or {}
        summary = levels.get("summary", {}) or {}
        # Fitbit emits either {deep,light,rem,wake} (advanced) or
        # {asleep,awake,restless} (classic). Use whichever exists.
        rem = (summary.get("rem") or {}).get("minutes")
        deep = (summary.get("deep") or {}).get("minutes")
        light = (summary.get("light") or {}).get("minutes")
        wake = (summary.get("wake") or {}).get("minutes")
        rows.append({
            "date": entry.get("dateOfSleep"),
            "log_id": str(entry.get("logId")) if entry.get("logId") else None,
            "duration_ms": entry.get("duration"),
            "minutes_asleep": entry.get("minutesAsleep"),
            "minutes_awake": entry.get("minutesAwake"),
            "minutes_to_fall_asleep": entry.get("minutesToFallAsleep"),
            "minutes_after_wakeup": entry.get("minutesAfterWakeup"),
            "time_in_bed": entry.get("timeInBed"),
            "efficiency": entry.get("efficiency"),
            "rem_minutes": rem,
            "deep_minutes": deep,
            "light_minutes": light,
            "wake_minutes": wake,
            "is_main_sleep": 1 if entry.get("isMainSleep") else 0,
            "start_time": entry.get("startTime"),
            "end_time": entry.get("endTime"),
        })
    return rows


def parse_heart_rate(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for entry in payload.get("activities-heart", []) or []:
        value = entry.get("value", {}) or {}
        zones = {z.get("name"): z for z in (value.get("heartRateZones") or [])}
        def _zone(name: str, key: str) -> Any:
            return (zones.get(name) or {}).get(key)
        rows.append({
            "date": entry.get("dateTime"),
            "resting_heart_rate": value.get("restingHeartRate"),
            "out_of_range_minutes": _zone("Out of Range", "minutes"),
            "fat_burn_minutes":      _zone("Fat Burn", "minutes"),
            "cardio_minutes":        _zone("Cardio", "minutes"),
            "peak_minutes":          _zone("Peak", "minutes"),
            "out_of_range_calories": _zone("Out of Range", "caloriesOut"),
            "fat_burn_calories":     _zone("Fat Burn", "caloriesOut"),
            "cardio_calories":       _zone("Cardio", "caloriesOut"),
            "peak_calories":         _zone("Peak", "caloriesOut"),
        })
    return rows


def parse_activity(payload: dict) -> list[dict]:
    """The single-day activity endpoint returns a fat dict; we map only
    the daily-summary fields. We synthesize the date from a `dateTime`
    field at the top level if present, otherwise the caller supplies it."""
    summary = payload.get("summary", {}) or {}
    distances = {d.get("activity"): d.get("distance") for d in (summary.get("distances") or [])}
    return [{
        # `dateTime` is not in /activities/date/{date}.json — caller fills it
        "date": payload.get("_date") or payload.get("dateTime"),
        "steps": summary.get("steps"),
        "calories_out": summary.get("caloriesOut"),
        "activity_calories": summary.get("activityCalories"),
        "sedentary_minutes": summary.get("sedentaryMinutes"),
        "lightly_active_minutes": summary.get("lightlyActiveMinutes"),
        "fairly_active_minutes": summary.get("fairlyActiveMinutes"),
        "very_active_minutes": summary.get("veryActiveMinutes"),
        "distance_total": distances.get("total"),
        "floors": summary.get("floors"),
        "elevation": summary.get("elevation"),
    }]


def parse_spo2(payload: dict) -> list[dict]:
    """Both per-day and range responses come as a list (or single dict)."""
    items = payload if isinstance(payload, list) else [payload]
    rows: list[dict] = []
    for item in items:
        v = item.get("value", {}) or {}
        rows.append({
            "date": item.get("dateTime"),
            "avg": v.get("avg"),
            "min": v.get("min"),
            "max": v.get("max"),
        })
    return rows


def parse_hrv(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for entry in payload.get("hrv", []) or []:
        v = entry.get("value", {}) or {}
        rows.append({
            "date": entry.get("dateTime"),
            "daily_rmssd": v.get("dailyRmssd"),
            "deep_rmssd": v.get("deepRmssd"),
        })
    return rows


def parse_temp(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for entry in payload.get("tempSkin", []) or []:
        v = entry.get("value", {}) or {}
        rows.append({
            "date": entry.get("dateTime"),
            "nightly_relative": v.get("nightlyRelative"),
        })
    return rows


# ─── Column lists (match schema.sql) ─────────────────────────────────────────
_SLEEP_COLS = [
    "date", "log_id", "duration_ms", "minutes_asleep", "minutes_awake",
    "minutes_to_fall_asleep", "minutes_after_wakeup", "time_in_bed",
    "efficiency", "rem_minutes", "deep_minutes", "light_minutes",
    "wake_minutes", "is_main_sleep", "start_time", "end_time",
]
_HEART_COLS = [
    "date", "resting_heart_rate",
    "out_of_range_minutes", "fat_burn_minutes", "cardio_minutes", "peak_minutes",
    "out_of_range_calories", "fat_burn_calories", "cardio_calories", "peak_calories",
]
_ACTIVITY_COLS = [
    "date", "steps", "calories_out", "activity_calories",
    "sedentary_minutes", "lightly_active_minutes", "fairly_active_minutes",
    "very_active_minutes", "distance_total", "floors", "elevation",
]
_SPO2_COLS = ["date", "avg", "min", "max"]
_HRV_COLS = ["date", "daily_rmssd", "deep_rmssd"]
_TEMP_COLS = ["date", "nightly_relative"]


# ─── Rollup to daily_metrics ─────────────────────────────────────────────────


_ROLLUP_SQL = """
    SELECT
        s.date                                  AS date,
        NULL                                     AS recovery_score,   -- Fitbit Readiness needs Premium
        hrv.daily_rmssd                         AS hrv_ms,
        h.resting_heart_rate                    AS resting_hr,
        sp.avg                                  AS spo2,
        t.nightly_relative                      AS skin_temp_c,
        s.efficiency                            AS sleep_performance,
        s.minutes_asleep / 60.0                 AS sleep_hours,
        s.efficiency / 100.0                    AS sleep_efficiency,
        s.rem_minutes / 60.0                    AS rem_hours,
        s.deep_minutes / 60.0                   AS deep_sleep_hours,
        s.light_minutes / 60.0                  AS light_sleep_hours,
        NULL                                     AS day_strain,
        a.calories_out                          AS calories_burned,
        a.steps                                 AS steps,
        (COALESCE(a.lightly_active_minutes, 0)
         + COALESCE(a.fairly_active_minutes, 0)
         + COALESCE(a.very_active_minutes, 0)) AS active_minutes
    FROM sleep_summary s
    LEFT JOIN heart_summary h    ON h.date = s.date
    LEFT JOIN activity_summary a ON a.date = s.date
    LEFT JOIN spo2_summary sp    ON sp.date = s.date
    LEFT JOIN hrv_summary hrv    ON hrv.date = s.date
    LEFT JOIN temp_summary t     ON t.date = s.date
    WHERE s.date > ? AND s.is_main_sleep = 1
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


# ─── One-shot localhost callback server for the OAuth dance ──────────────────


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Captures the ?code=... from Fitbit's redirect to our localhost
    callback, then shuts the server down so configure_interactive can
    continue."""

    captured: dict[str, str | None] = {"code": None, "error": None}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]
        _OAuthCallbackHandler.captured["code"] = code
        _OAuthCallbackHandler.captured["error"] = error
        body = (
            b"<html><body><h2>Fitbit authorization received.</h2>"
            b"<p>You can close this tab and return to your terminal.</p>"
            b"</body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Silence the noisy default access log.
        return


def _capture_auth_code(port: int) -> tuple[str | None, str | None]:
    """Run a single-request HTTP server on localhost:port; return (code, error)."""
    _OAuthCallbackHandler.captured = {"code": None, "error": None}
    server = HTTPServer(("127.0.0.1", port), _OAuthCallbackHandler)
    server.handle_request()  # blocks until the first request
    server.server_close()
    return (_OAuthCallbackHandler.captured["code"], _OAuthCallbackHandler.captured["error"])


# ─── Adapter ─────────────────────────────────────────────────────────────────


class FitbitAdapter(BiometricAdapter):
    slug = "fitbit"
    display_name = "Fitbit"
    raw_db_name = "fitbit_raw.db"
    stability = "stable"
    requires_oauth = True

    def setup_instructions(self) -> str:
        return f"""\
**Fitbit** pulls daily sleep (with REM/Deep/Light stage minutes),
resting heart rate + HR-zone breakdown, activity (steps, calories,
active minutes), SpO₂, nightly HRV (rmssd), and skin temperature via
the Fitbit Web API.

Setup involves:

1. **Register an app at <https://dev.fitbit.com/apps>**:
   - Application Type: **Personal**
   - Callback URL: `http://localhost:{DEFAULT_CALLBACK_PORT}/fitbit/callback`
     (the adapter spins up a one-shot localhost server on this port
     during connect)
   - OAuth 2.0 Application Type: **Server**
   - Default Access Type: **Read-Only** is fine

2. Copy the `OAuth 2.0 Client ID` and `Client Secret` — you'll paste
   them in the next step.

3. The adapter will open the authorize URL in your browser; click
   **Allow** to grant the listed scopes (activity, heartrate, sleep,
   weight, respiratory_rate, oxygen_saturation, temperature, profile).

**Rate limit**: Fitbit allows 150 requests/hour per user. The adapter
uses range endpoints where possible to stay well under that.
"""

    def configure_interactive(self) -> None:
        print("Paste the credentials from <https://dev.fitbit.com/apps>:")
        client_id = input("  OAuth 2.0 Client ID: ").strip()
        client_secret = getpass.getpass("  Client Secret: ").strip()
        if not (client_id and client_secret):
            raise SystemExit("Missing client_id/client_secret; aborting.")

        port_env = os.environ.get("FITBIT_CALLBACK_PORT")
        port = int(port_env) if port_env else DEFAULT_CALLBACK_PORT
        redirect_uri = f"http://localhost:{port}/fitbit/callback"

        auth_url = build_authorize_url(
            AUTHORIZE_URL, client_id, redirect_uri,
            scopes=DEFAULT_SCOPES,
        )
        print()
        print("Opening browser to:")
        print(f"  {auth_url}")
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass
        print(f"\nWaiting for Fitbit to redirect to localhost:{port} ...")
        code, error = _capture_auth_code(port)
        if error or not code:
            raise SystemExit(f"Authorization failed: {error or 'no code returned'}")
        print("Got authorization code; exchanging for tokens...")
        creds = exchange_code_for_tokens(
            TOKEN_URL, client_id, client_secret, code, redirect_uri,
            use_basic_auth=True,
        )
        # Persist credentials + the app's client_id/secret (we need them later for refresh)
        creds["client_id"] = client_id
        creds["client_secret"] = client_secret
        save_credentials(self.secrets_path, creds)
        print(f"\nSaved to {self.secrets_path}.")
        print(
            f"Run `python3 pipeline/adapters/fitbit/sync.py` to do a "
            f"first data pull."
        )

    def _client(self) -> FitbitClient:
        if not self.secrets_path.exists():
            raise FileNotFoundError(
                f"No Fitbit credentials at {self.secrets_path}. "
                "Run `biohub connect fitbit` first."
            )
        cfg = json.loads(self.secrets_path.read_text())
        return FitbitClient(self.secrets_path, cfg["client_id"], cfg["client_secret"])

    def _range(self, since: str | None) -> tuple[str, str]:
        end = datetime.now(timezone.utc).date().isoformat()
        if since:
            start = since
        else:
            start = (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()
        return start, end

    def sync(self, since: str | None = None, limit: int | None = None) -> SyncResult:
        client = self._client()
        self.raw_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.raw_db_path)
        try:
            _ensure_schema(conn)
            inserted = 0
            start, end = self._range(since)

            # 1. Sleep (range endpoint)
            try:
                payload = client.get(f"/1.2/user/-/sleep/date/{start}/{end}.json")
                rows = parse_sleep(payload)
                if limit:
                    rows = rows[:limit]
                for r in rows:
                    if r["date"]:
                        _upsert(conn, "sleep_summary", _SLEEP_COLS, r)
                conn.execute(
                    "INSERT INTO download_log (data_type, records_count, success) VALUES (?,?,?)",
                    ("sleep", len(rows), True),
                )
                inserted += len(rows)
            except Exception as e:
                conn.execute(
                    "INSERT INTO download_log (data_type, records_count, success, error_message) "
                    "VALUES (?,?,?,?)", ("sleep", 0, False, str(e)),
                )
                conn.commit()
                return SyncResult(rows_inserted=inserted, error=f"sleep: {e}")

            # 2. Heart rate summary (range)
            try:
                payload = client.get(f"/1/user/-/activities/heart/date/{start}/{end}.json")
                rows = parse_heart_rate(payload)
                if limit:
                    rows = rows[:limit]
                for r in rows:
                    if r["date"]:
                        _upsert(conn, "heart_summary", _HEART_COLS, r)
                conn.execute(
                    "INSERT INTO download_log (data_type, records_count, success) VALUES (?,?,?)",
                    ("heart", len(rows), True),
                )
                inserted += len(rows)
            except Exception as e:
                conn.execute(
                    "INSERT INTO download_log (data_type, records_count, success, error_message) "
                    "VALUES (?,?,?,?)", ("heart", 0, False, str(e)),
                )

            # 3. Activity (must call per-day; no range endpoint exists for full summary)
            try:
                d = datetime.fromisoformat(start).date()
                end_d = datetime.fromisoformat(end).date()
                n = 0
                while d <= end_d:
                    iso = d.isoformat()
                    payload = client.get(f"/1/user/-/activities/date/{iso}.json")
                    payload["_date"] = iso
                    rows = parse_activity(payload)
                    for r in rows:
                        _upsert(conn, "activity_summary", _ACTIVITY_COLS, r)
                    n += len(rows)
                    if limit and n >= limit:
                        break
                    d += timedelta(days=1)
                conn.execute(
                    "INSERT INTO download_log (data_type, records_count, success) VALUES (?,?,?)",
                    ("activity", n, True),
                )
                inserted += n
            except Exception as e:
                conn.execute(
                    "INSERT INTO download_log (data_type, records_count, success, error_message) "
                    "VALUES (?,?,?,?)", ("activity", 0, False, str(e)),
                )

            # 4. SpO₂ (range)
            try:
                payload = client.get(f"/1/user/-/spo2/date/{start}/{end}.json")
                rows = parse_spo2(payload)
                if limit:
                    rows = rows[:limit]
                for r in rows:
                    if r["date"]:
                        _upsert(conn, "spo2_summary", _SPO2_COLS, r)
                conn.execute(
                    "INSERT INTO download_log (data_type, records_count, success) VALUES (?,?,?)",
                    ("spo2", len(rows), True),
                )
                inserted += len(rows)
            except Exception as e:
                conn.execute(
                    "INSERT INTO download_log (data_type, records_count, success, error_message) "
                    "VALUES (?,?,?,?)", ("spo2", 0, False, str(e)),
                )

            # 5. HRV (range)
            try:
                payload = client.get(f"/1/user/-/hrv/date/{start}/{end}.json")
                rows = parse_hrv(payload)
                if limit:
                    rows = rows[:limit]
                for r in rows:
                    if r["date"]:
                        _upsert(conn, "hrv_summary", _HRV_COLS, r)
                conn.execute(
                    "INSERT INTO download_log (data_type, records_count, success) VALUES (?,?,?)",
                    ("hrv", len(rows), True),
                )
                inserted += len(rows)
            except Exception as e:
                conn.execute(
                    "INSERT INTO download_log (data_type, records_count, success, error_message) "
                    "VALUES (?,?,?,?)", ("hrv", 0, False, str(e)),
                )

            # 6. Skin temperature (range)
            try:
                payload = client.get(f"/1/user/-/temp/skin/date/{start}/{end}.json")
                rows = parse_temp(payload)
                if limit:
                    rows = rows[:limit]
                for r in rows:
                    if r["date"]:
                        _upsert(conn, "temp_summary", _TEMP_COLS, r)
                conn.execute(
                    "INSERT INTO download_log (data_type, records_count, success) VALUES (?,?,?)",
                    ("temp", len(rows), True),
                )
                inserted += len(rows)
            except Exception as e:
                conn.execute(
                    "INSERT INTO download_log (data_type, records_count, success, error_message) "
                    "VALUES (?,?,?,?)", ("temp", 0, False, str(e)),
                )

            conn.commit()
            return SyncResult(rows_inserted=inserted)
        finally:
            conn.close()

    def rollup_to_health_db(self) -> int:
        return _rollup(self.raw_db_path, HEALTH_DB)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fitbit sync")
    parser.add_argument("--since", help="ISO date YYYY-MM-DD to start from")
    parser.add_argument("--limit", type=int, help="Max records per resource (debugging)")
    args = parser.parse_args()

    print(f"Fitbit Sync — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    adapter = FitbitAdapter()
    result = adapter.sync(since=args.since, limit=args.limit)
    try:
        rolled = adapter.rollup_to_health_db()
        print(f"  Rolled up {rolled} rows to daily_metrics (source=fitbit)")
    except Exception as e:
        print(f"  Rollup error: {e}")
    print(f"\nDone. {result}")
    return 0 if not result.error else 1


if __name__ == "__main__":
    sys.exit(main())
