#!/usr/bin/env python3
"""
whoop_sync.py — Fetches latest data from WHOOP API and writes to whoop_raw.db.
Reads token from $OPENCLAW_BIOHUB_HOME/secrets/whoop_credentials.json.
Run after OAuth flow or on a schedule while token is valid.
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# Allow standalone execution: put pipeline/ on sys.path so we can import paths.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from paths import HEALTH_DB, WHOOP_CREDS_FILE, WHOOP_DB

CREDS_FILE = WHOOP_CREDS_FILE
DB_FILE = WHOOP_DB
BASE_URL = "https://api.prod.whoop.com/developer/v1"
BASE_URL_V2 = "https://api.prod.whoop.com/developer/v2"
REFRESH_URL = os.environ.get("WHOOP_REFRESH_URL", "http://127.0.0.1:8893/refresh")
REFRESH_THRESHOLD_S = 300  # auto-refresh when ≤5 min remaining (covers stale-token + clock-skew)


def _read_creds_remaining():
    creds = json.loads(CREDS_FILE.read_text())
    obtained_at = creds.get("obtained_at", 0)
    expires_in = creds.get("expires_in", 3600)
    remaining = (obtained_at + expires_in) - datetime.now(timezone.utc).timestamp()
    return creds, int(remaining)


def load_token():
    if not CREDS_FILE.exists():
        print("ERROR: No credentials file found at", CREDS_FILE)
        sys.exit(1)
    creds, remaining = _read_creds_remaining()
    if remaining < REFRESH_THRESHOLD_S:
        print(f"Token at {remaining}s remaining; calling {REFRESH_URL}")
        try:
            r = requests.get(REFRESH_URL, timeout=10)
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                print(f"ERROR: refresh endpoint returned not-ok: {data}")
                sys.exit(1)
            creds, remaining = _read_creds_remaining()
            print(f"Refreshed: token valid {remaining}s")
        except Exception as e:
            print(f"ERROR: Auto-refresh failed ({e}). Is whoop-oauth-handler.service up on 127.0.0.1:8893?")
            sys.exit(1)
    print(f"Token valid for {remaining}s")
    return creds.get("access_token")

def whoop_get(token, path, params=None):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}{path}"
    all_records = []
    while url:
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            print(f"  API error {resp.status_code} for {path}: {resp.text[:200]}")
            break
        data = resp.json()
        records = data.get("records", [data] if "id" in data or "user_id" in data else [])
        all_records.extend(records)
        next_token = data.get("next_token")
        if next_token:
            url = f"{BASE_URL}{path}"
            params = {"nextToken": next_token, "limit": 25}
        else:
            url = None
        params = None  # clear params after first page
    return all_records

def upsert(conn, table, pk_col, rows, now_str):
    if not rows:
        return 0
    cur = conn.cursor()
    count = 0
    for row in rows:
        cols = list(row.keys())
        placeholders = ", ".join("?" * len(cols))
        update_pairs = ", ".join(f"{c}=excluded.{c}" for c in cols if c != pk_col)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT({pk_col}) DO UPDATE SET {update_pairs}"
        cur.execute(sql, list(row.values()))
        count += 1
    return count

def sync_profile(conn, token):
    print("Syncing profile...")
    data = whoop_get(token, "/user/profile/basic")
    if not data:
        print("  No profile data")
        return
    p = data[0] if isinstance(data, list) else data
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO user_profile (user_id, first_name, last_name, email, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET first_name=excluded.first_name,
        last_name=excluded.last_name, email=excluded.email, updated_at=excluded.updated_at
    """, (p.get("user_id"), p.get("first_name"), p.get("last_name"), p.get("email"), now))
    print(f"  Profile: {p.get('first_name')} {p.get('last_name')}")

def sync_body_measurements(conn, token):
    print("Syncing body measurements...")
    data = whoop_get(token, "/user/measurement/body")
    if not data:
        print("  No body data")
        return
    bm = data[0] if isinstance(data, list) else data
    now = datetime.now(timezone.utc).isoformat()
    # Get user_id from profile
    cur = conn.execute("SELECT user_id FROM user_profile LIMIT 1")
    row = cur.fetchone()
    user_id = row[0] if row else None
    conn.execute("""
        INSERT INTO body_measurements (user_id, height_meter, weight_kilogram, max_heart_rate, updated_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, bm.get("height_meter"), bm.get("weight_kilogram"), bm.get("max_heart_rate"), now))
    print(f"  Height: {bm.get('height_meter')}m, Weight: {bm.get('weight_kilogram')}kg")

def sync_cycles(conn, token):
    print("Syncing cycles...")
    # Find last cycle to sync only new ones
    cur = conn.execute("SELECT MAX(created_at) FROM cycles_data")
    last = cur.fetchone()[0]
    params = {"limit": 25}
    if last:
        params["start"] = last
    print(f"  Fetching since {last or 'beginning'}...")
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL_V2}/cycle"
    count = 0
    while url:
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            print(f"  API error {resp.status_code}: {resp.text[:200]}")
            break
        data = resp.json()
        records = data.get("records", [])
        for r in records:
            score = r.get("score") or {}
            conn.execute("""
                INSERT OR REPLACE INTO cycles_data
                (id, user_id, created_at, updated_at, start_time, end_time, timezone_offset,
                 score_state, strain, kilojoule, average_heart_rate, max_heart_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (r.get("id"), r.get("user_id"), r.get("created_at"), r.get("updated_at"),
                  r.get("start"), r.get("end"), r.get("timezone_offset"),
                  r.get("score_state"), score.get("strain"), score.get("kilojoule"),
                  score.get("average_heart_rate"), score.get("max_heart_rate")))
            count += 1
        next_token = data.get("next_token")
        if next_token and count < 200:
            params = {"nextToken": next_token, "limit": 25}
        else:
            url = None
        params = params if next_token else None
        if not next_token:
            break
    print(f"  Synced {count} cycles")
    return count

def sync_recovery(conn, token):
    print("Syncing recovery...")
    cur = conn.execute("SELECT MAX(created_at) FROM recovery_data")
    last = cur.fetchone()[0]
    params = {"limit": 25}
    if last:
        params["start"] = last
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL_V2}/recovery"
    count = 0
    while url:
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            print(f"  API error {resp.status_code}: {resp.text[:200]}")
            break
        data = resp.json()
        records = data.get("records", [])
        for r in records:
            score = r.get("score") or {}
            conn.execute("""
                INSERT OR REPLACE INTO recovery_data
                (cycle_id, sleep_id, user_id, created_at, updated_at, score_state,
                 user_calibrating, recovery_score, resting_heart_rate, hrv_rmssd_milli,
                 spo2_percentage, skin_temp_celsius)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (r.get("cycle_id"), r.get("sleep_id"), r.get("user_id"),
                  r.get("created_at"), r.get("updated_at"), r.get("score_state"),
                  r.get("user_calibrating"), score.get("recovery_score"),
                  score.get("resting_heart_rate"), score.get("hrv_rmssd_milli"),
                  score.get("spo2_percentage"), score.get("skin_temp_celsius")))
            count += 1
        next_token = data.get("next_token")
        if next_token and count < 200:
            params = {"nextToken": next_token, "limit": 25}
        else:
            break
    print(f"  Synced {count} recovery records")
    return count

def sync_sleep(conn, token):
    print("Syncing sleep...")
    cur = conn.execute("SELECT MAX(created_at) FROM sleep_data")
    last = cur.fetchone()[0]
    params = {"limit": 25}
    if last:
        params["start"] = last
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL_V2}/activity/sleep"
    count = 0
    while url:
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            print(f"  API error {resp.status_code}: {resp.text[:200]}")
            break
        data = resp.json()
        records = data.get("records", [])
        for r in records:
            score = r.get("score") or {}
            stages = score.get("stage_summary") or {}
            # Sleep-Need-Block: baseline, debt, recent_strain, recent_nap. Vorher wurden
            # diese Felder gar nicht persistiert → Sleep-Need-vs-Got Chart leer. Fix 2026-05-14.
            needed = score.get("sleep_needed") or {}
            conn.execute("""
                INSERT OR REPLACE INTO sleep_data
                (id, cycle_id, v1_id, user_id, created_at, updated_at, start_time, end_time,
                 timezone_offset, nap, score_state, total_in_bed_time_milli, total_awake_time_milli,
                 total_no_data_time_milli, total_light_sleep_time_milli, total_slow_wave_sleep_time_milli,
                 total_rem_sleep_time_milli, sleep_cycle_count, disturbance_count,
                 baseline_milli, need_from_sleep_debt_milli, need_from_recent_strain_milli,
                 need_from_recent_nap_milli,
                 respiratory_rate, sleep_performance_percentage, sleep_consistency_percentage,
                 sleep_efficiency_percentage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (r.get("id"), r.get("cycle_id"), r.get("v1_id"), r.get("user_id"),
                  r.get("created_at"), r.get("updated_at"), r.get("start"), r.get("end"),
                  r.get("timezone_offset"), r.get("nap"), r.get("score_state"),
                  stages.get("total_in_bed_time_milli"), stages.get("total_awake_time_milli"),
                  stages.get("total_no_data_time_milli"), stages.get("total_light_sleep_time_milli"),
                  stages.get("total_slow_wave_sleep_time_milli"), stages.get("total_rem_sleep_time_milli"),
                  stages.get("sleep_cycle_count"), stages.get("disturbance_count"),
                  needed.get("baseline_milli"), needed.get("need_from_sleep_debt_milli"),
                  needed.get("need_from_recent_strain_milli"), needed.get("need_from_recent_nap_milli"),
                  score.get("respiratory_rate"), score.get("sleep_performance_percentage"),
                  score.get("sleep_consistency_percentage"), score.get("sleep_efficiency_percentage")))
            count += 1
        next_token = data.get("next_token")
        if next_token and count < 200:
            params = {"nextToken": next_token, "limit": 25}
        else:
            break
    print(f"  Synced {count} sleep records")
    return count

def sync_workouts(conn, token):
    print("Syncing workouts...")
    cur = conn.execute("SELECT MAX(created_at) FROM workout_data")
    last = cur.fetchone()[0]
    params = {"limit": 25}
    if last:
        params["start"] = last
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL_V2}/activity/workout"
    count = 0
    while url:
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            print(f"  API error {resp.status_code}: {resp.text[:200]}")
            break
        data = resp.json()
        records = data.get("records", [])
        for r in records:
            score = r.get("score") or {}
            # Whoop V2 nennt das Feld 'zone_durations' (Plural). Vorher war 'zone_duration' (Tippfehler) → alle HR-Zonen-Daten waren NULL. Fix 2026-05-14.
            zones = score.get("zone_durations") or score.get("zone_duration") or {}
            conn.execute("""
                INSERT OR REPLACE INTO workout_data
                (id, v1_id, user_id, created_at, updated_at, start_time, end_time,
                 timezone_offset, sport_name, sport_id, score_state, strain,
                 average_heart_rate, max_heart_rate, kilojoule, percent_recorded,
                 distance_meter, altitude_gain_meter, altitude_change_meter,
                 zone_zero_milli, zone_one_milli, zone_two_milli, zone_three_milli,
                 zone_four_milli, zone_five_milli)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (r.get("id"), r.get("v1_id"), r.get("user_id"),
                  r.get("created_at"), r.get("updated_at"), r.get("start"), r.get("end"),
                  r.get("timezone_offset"), r.get("sport_name"), r.get("sport_id"), r.get("score_state"),
                  score.get("strain"), score.get("average_heart_rate"), score.get("max_heart_rate"),
                  score.get("kilojoule"), score.get("percent_recorded"), score.get("distance_meter"),
                  score.get("altitude_gain_meter"), score.get("altitude_change_meter"),
                  zones.get("zone_zero_milli"), zones.get("zone_one_milli"), zones.get("zone_two_milli"),
                  zones.get("zone_three_milli"), zones.get("zone_four_milli"), zones.get("zone_five_milli")))
            count += 1
        next_token = data.get("next_token")
        if next_token and count < 200:
            params = {"nextToken": next_token, "limit": 25}
        else:
            break
    print(f"  Synced {count} workout records")
    return count

def log_sync(conn, data_type, count, success, error=None):
    conn.execute("""
        INSERT INTO download_log (data_type, download_date, records_count, success, error_message)
        VALUES (?, ?, ?, ?, ?)
    """, (data_type, datetime.now(timezone.utc).isoformat(), count, success, error))

MC_DB_FILE = HEALTH_DB
SOURCE = "whoop"  # value written to daily_metrics.source

def sync_daily_aggregates():
    """Roll up daily WHOOP aggregates from whoop_raw.db into health.db's
    source-agnostic `daily_metrics` table (one row per (source, date))."""
    print("Syncing WHOOP daily aggregates -> daily_metrics...")
    if not MC_DB_FILE.exists():
        print(f"  health.db not found at {MC_DB_FILE}")
        return 0

    src = sqlite3.connect(DB_FILE)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(MC_DB_FILE)

    # Find latest WHOOP-sourced date already in daily_metrics
    cur = dst.execute("SELECT MAX(date) FROM daily_metrics WHERE source = ?", (SOURCE,))
    last_date = cur.fetchone()[0] or "2000-01-01"
    print(f"  Updating from {last_date}...")

    # Join recovery + sleep + cycles by date (using recovery.created_at as anchor date)
    rows = src.execute("""
        SELECT
            date(r.created_at) AS date,
            r.recovery_score,
            r.hrv_rmssd_milli AS hrv_ms,
            r.resting_heart_rate AS resting_hr,
            r.spo2_percentage AS spo2,
            r.skin_temp_celsius AS skin_temp_c,
            s.sleep_performance_percentage AS sleep_performance,
            ROUND(s.total_in_bed_time_milli / 3600000.0, 2) AS sleep_hours,
            s.sleep_efficiency_percentage AS sleep_efficiency,
            ROUND(s.total_rem_sleep_time_milli / 3600000.0, 2) AS rem_hours,
            ROUND(s.total_slow_wave_sleep_time_milli / 3600000.0, 2) AS deep_sleep_hours,
            ROUND(s.total_light_sleep_time_milli / 3600000.0, 2) AS light_sleep_hours,
            c.strain AS day_strain,
            CAST(c.kilojoule * 238.846 AS INTEGER) AS calories_burned
        FROM recovery_data r
        LEFT JOIN sleep_data s ON s.id = r.sleep_id AND s.nap = 0
        LEFT JOIN cycles_data c ON c.id = r.cycle_id
        WHERE r.score_state = 'SCORED'
          AND date(r.created_at) > ?
        ORDER BY date DESC
    """, (last_date,)).fetchall()

    count = 0
    now_ts = int(datetime.now(timezone.utc).timestamp())
    for row in rows:
        dst.execute("""
            INSERT INTO daily_metrics
                (source, date, recovery_score, hrv_ms, resting_hr, spo2, skin_temp_c,
                 sleep_performance, sleep_hours, sleep_efficiency, rem_hours,
                 deep_sleep_hours, light_sleep_hours, day_strain, calories_burned, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, date) DO UPDATE SET
                recovery_score=excluded.recovery_score, hrv_ms=excluded.hrv_ms,
                resting_hr=excluded.resting_hr, spo2=excluded.spo2,
                skin_temp_c=excluded.skin_temp_c, sleep_performance=excluded.sleep_performance,
                sleep_hours=excluded.sleep_hours, sleep_efficiency=excluded.sleep_efficiency,
                rem_hours=excluded.rem_hours, deep_sleep_hours=excluded.deep_sleep_hours,
                light_sleep_hours=excluded.light_sleep_hours, day_strain=excluded.day_strain,
                calories_burned=excluded.calories_burned
        """, (SOURCE, row["date"], row["recovery_score"], row["hrv_ms"], row["resting_hr"],
              row["spo2"], row["skin_temp_c"], row["sleep_performance"], row["sleep_hours"],
              row["sleep_efficiency"], row["rem_hours"], row["deep_sleep_hours"],
              row["light_sleep_hours"], row["day_strain"], row["calories_burned"], now_ts))
        count += 1

    dst.commit()
    src.close()
    dst.close()
    print(f"  Updated {count} rows in daily_metrics (source={SOURCE})")
    return count


from adapters.base import BiometricAdapter, SyncResult


class WhoopAdapter(BiometricAdapter):
    """Reference implementation of `BiometricAdapter` for the WHOOP API.

    OAuth credentials live in `$OPENCLAW_BIOHUB_HOME/secrets/whoop.json`
    (or, on production deploys, in `/etc/openclaw-biohub/secrets.env`
    consumed by the `whoop-oauth-handler.service` systemd unit). Tokens
    are refreshed automatically by that OAuth handler on port 8893.
    """

    slug = "whoop"
    display_name = "WHOOP"
    raw_db_name = "whoop_raw.db"
    stability = "stable"
    requires_oauth = True

    def setup_instructions(self) -> str:
        return """\
**WHOOP** pulls recovery score, HRV (rmssd), resting heart rate, SpO₂,
skin temperature, sleep stages, daily strain, and workouts (with HR
zones) from the official WHOOP Developer API.

Setup involves three steps:

1. **Create a WHOOP developer app.** Sign in with your WHOOP athlete
   account at <https://developer.whoop.com> and click *Create App*.
   Note the `client_id` and `client_secret`.

2. **Set the redirect URI** in the app settings. For a local-only
   install use `http://localhost:8893/callback`. For a production
   deploy with a public reverse proxy, use
   `https://YOUR_HOST/whoop/callback`.

3. **Install + start the OAuth handler service.**
   `whoop-oauth-handler.service` (see `systemd/`) listens on port
   8893 and refreshes access tokens on demand. Once running, visit
   `http://localhost:8893/login` (or the public callback URL) in a
   browser to complete the OAuth grant.

After authorization, tokens are cached at
`$OPENCLAW_BIOHUB_HOME/secrets/whoop_credentials.json` and refreshed
automatically before each sync.
"""

    def configure_interactive(self) -> None:
        import getpass
        import json
        print("Enter your WHOOP developer app credentials:")
        client_id = input("  client_id: ").strip()
        client_secret = getpass.getpass("  client_secret: ").strip()
        redirect_uri = input(
            "  redirect_uri [http://localhost:8893/callback]: "
        ).strip() or "http://localhost:8893/callback"
        self.secrets_path.parent.mkdir(parents=True, exist_ok=True)
        self.secrets_path.write_text(json.dumps({
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }))
        self.secrets_path.chmod(0o600)
        print(f"Saved to {self.secrets_path}")
        print(
            "\nNext: install the OAuth handler systemd unit "
            "(see CONFIGURATION.md) and complete the browser OAuth flow."
        )

    def sync(self, since: str | None = None, limit: int | None = None) -> SyncResult:
        token = load_token()
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        inserted = 0
        try:
            try:
                sync_profile(conn, token)
                conn.commit()
            except Exception as e:
                print(f"  Profile sync error: {e}")

            for name, fn in [("cycles", sync_cycles), ("recovery", sync_recovery),
                             ("sleep", sync_sleep), ("workouts", sync_workouts)]:
                try:
                    count = fn(conn, token)
                    inserted += count
                    log_sync(conn, name, count, True)
                    conn.commit()
                except Exception as e:
                    print(f"  {name} sync error: {e}")
                    log_sync(conn, name, 0, False, str(e))
                    conn.commit()
                    return SyncResult(rows_inserted=inserted, error=f"{name}: {e}")
            return SyncResult(rows_inserted=inserted)
        finally:
            conn.close()

    def rollup_to_health_db(self) -> int:
        return sync_daily_aggregates()


def main():
    print(f"WHOOP Sync — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    adapter = WhoopAdapter()
    result = adapter.sync()
    try:
        adapter.rollup_to_health_db()
    except Exception as e:
        print(f"  Daily aggregate sync error: {e}")
    print(f"\nDone. {result}")


if __name__ == "__main__":
    main()
