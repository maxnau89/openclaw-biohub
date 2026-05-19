#!/usr/bin/env python3
"""
whoop_backfill_sleep.py — One-off: backfill sleep_data for a date range.

Why: Sleep records prior to 2024-12-21 are missing from whoop_raw.db,
even though recovery/cycles/workouts go back to 2024-09/10. This walks the
WHOOP v2 sleep endpoint with explicit start/end window and pages with
nextToken until exhausted.

Usage:
    python3 whoop_backfill_sleep.py 2024-09-01 2024-12-22

Idempotent: uses INSERT OR REPLACE on sleep_data.id.
"""
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from paths import WHOOP_CREDS_FILE, WHOOP_DB

CREDS_FILE = WHOOP_CREDS_FILE
DB_FILE = WHOOP_DB
BASE_URL_V2 = "https://api.prod.whoop.com/developer/v2"


def load_token() -> str:
    creds = json.loads(CREDS_FILE.read_text())
    token = creds.get("access_token")
    obtained_at = creds.get("obtained_at", 0)
    expires_in = creds.get("expires_in", 3600)
    remaining = (obtained_at + expires_in) - datetime.now(timezone.utc).timestamp()
    if remaining < 60:
        print(f"ERROR: Token expired ({int(remaining)}s). Run /whoop/refresh first.")
        sys.exit(1)
    print(f"Token valid for {int(remaining)}s")
    return token


def insert_sleep(conn, r):
    score = r.get("score") or {}
    stages = score.get("stage_summary") or {}
    conn.execute(
        """
        INSERT OR REPLACE INTO sleep_data
        (id, cycle_id, v1_id, user_id, created_at, updated_at, start_time, end_time,
         timezone_offset, nap, score_state, total_in_bed_time_milli, total_awake_time_milli,
         total_no_data_time_milli, total_light_sleep_time_milli, total_slow_wave_sleep_time_milli,
         total_rem_sleep_time_milli, sleep_cycle_count, disturbance_count,
         respiratory_rate, sleep_performance_percentage, sleep_consistency_percentage,
         sleep_efficiency_percentage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            r.get("id"), r.get("cycle_id"), r.get("v1_id"), r.get("user_id"),
            r.get("created_at"), r.get("updated_at"), r.get("start"), r.get("end"),
            r.get("timezone_offset"), r.get("nap"), r.get("score_state"),
            stages.get("total_in_bed_time_milli"), stages.get("total_awake_time_milli"),
            stages.get("total_no_data_time_milli"), stages.get("total_light_sleep_time_milli"),
            stages.get("total_slow_wave_sleep_time_milli"), stages.get("total_rem_sleep_time_milli"),
            stages.get("sleep_cycle_count"), stages.get("disturbance_count"),
            score.get("respiratory_rate"), score.get("sleep_performance_percentage"),
            score.get("sleep_consistency_percentage"), score.get("sleep_efficiency_percentage"),
        ),
    )


def main():
    if len(sys.argv) != 3:
        print("Usage: whoop_backfill_sleep.py YYYY-MM-DD YYYY-MM-DD")
        sys.exit(2)

    start_date, end_date = sys.argv[1], sys.argv[2]
    start_iso = f"{start_date}T00:00:00.000Z"
    end_iso = f"{end_date}T23:59:59.999Z"

    token = load_token()
    headers = {"Authorization": f"Bearer {token}"}
    conn = sqlite3.connect(DB_FILE)

    url = f"{BASE_URL_V2}/activity/sleep"
    params = {"limit": 25, "start": start_iso, "end": end_iso}
    inserted = 0
    pages = 0
    next_token = None

    while True:
        if next_token:
            params = {"limit": 25, "nextToken": next_token}
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            print(f"API error {resp.status_code}: {resp.text[:300]}")
            break
        data = resp.json()
        records = data.get("records", []) or []
        for r in records:
            insert_sleep(conn, r)
            inserted += 1
        conn.commit()
        pages += 1
        print(f"  page {pages}: +{len(records)} records (total inserted: {inserted})")
        next_token = data.get("next_token")
        if not next_token:
            break
        # gentle pacing to avoid rate-limits
        time.sleep(0.3)

    conn.close()
    print(f"\nDone. Backfilled {inserted} sleep records across {pages} pages "
          f"for window {start_date} → {end_date}.")


if __name__ == "__main__":
    main()
