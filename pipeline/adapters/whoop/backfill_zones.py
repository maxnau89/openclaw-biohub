#!/usr/bin/env python3
"""Backfill HR-Zonen + Sleep-Need block.

Bug-Fix Hintergrund:
  - whoop_sync.py: 'zone_duration' (Singular) statt 'zone_durations' (Plural) → alle zone_*_milli NULL
  - whoop_sync.py: sleep_needed Block (baseline, debt, recent_strain, recent_nap) wurde nie persistiert

Beide gefixt 2026-05-14. Dieses Script holt alte Records nach. Idempotent.
"""
import json, os, sqlite3, sys, time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from paths import WHOOP_CREDS_FILE, WHOOP_DB

DB = WHOOP_DB
CRED = WHOOP_CREDS_FILE
BASE = "https://api.prod.whoop.com/developer/v2"
REFRESH_URL = os.environ.get("WHOOP_REFRESH_URL", "http://127.0.0.1:8893/refresh")


def get_token():
    try:
        r = requests.get(REFRESH_URL, timeout=10)
        if r.ok and r.json().get("access_token"):
            return r.json()["access_token"]
    except Exception:
        pass
    return json.load(CRED.open())["access_token"]


def backfill(conn, token, endpoint, missing_query, update_fn, label):
    cur = conn.execute(f"SELECT COUNT(*) FROM ({missing_query})")
    before = cur.fetchone()[0]
    print(f"  {label} missing: {before}")
    if before == 0:
        return 0, 0
    cur = conn.execute(f"SELECT MIN(start_time) FROM ({missing_query})")
    min_t = cur.fetchone()[0]
    print(f"  Starting from: {min_t}")
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE}/{endpoint}"
    params = {"limit": 25, "start": min_t} if min_t else {"limit": 25}
    processed = 0
    while True:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code != 200:
            print(f"  API error {r.status_code}: {r.text[:200]}")
            break
        data = r.json()
        recs = data.get("records", [])
        for rec in recs:
            update_fn(conn, rec)
        processed += len(recs)
        conn.commit()
        if processed and processed % 100 == 0:
            print(f"    processed {processed}")
        nxt = data.get("next_token")
        if nxt:
            params = {"nextToken": nxt, "limit": 25}
        else:
            break
        time.sleep(0.3)
    cur = conn.execute(f"SELECT COUNT(*) FROM ({missing_query})")
    after = cur.fetchone()[0]
    return before, after


def update_workout_zones(conn, w):
    score = w.get("score") or {}
    z = score.get("zone_durations") or score.get("zone_duration") or {}
    if not z:
        return
    conn.execute("""
        UPDATE workout_data SET
            zone_zero_milli = COALESCE(zone_zero_milli, ?),
            zone_one_milli = COALESCE(zone_one_milli, ?),
            zone_two_milli = COALESCE(zone_two_milli, ?),
            zone_three_milli = COALESCE(zone_three_milli, ?),
            zone_four_milli = COALESCE(zone_four_milli, ?),
            zone_five_milli = COALESCE(zone_five_milli, ?)
        WHERE id = ?
    """, (z.get("zone_zero_milli"), z.get("zone_one_milli"),
          z.get("zone_two_milli"), z.get("zone_three_milli"),
          z.get("zone_four_milli"), z.get("zone_five_milli"),
          w.get("id")))


def update_sleep_need(conn, s):
    score = s.get("score") or {}
    n = score.get("sleep_needed") or {}
    if not n:
        return
    conn.execute("""
        UPDATE sleep_data SET
            baseline_milli = COALESCE(baseline_milli, ?),
            need_from_sleep_debt_milli = COALESCE(need_from_sleep_debt_milli, ?),
            need_from_recent_strain_milli = COALESCE(need_from_recent_strain_milli, ?),
            need_from_recent_nap_milli = COALESCE(need_from_recent_nap_milli, ?)
        WHERE id = ?
    """, (n.get("baseline_milli"), n.get("need_from_sleep_debt_milli"),
          n.get("need_from_recent_strain_milli"), n.get("need_from_recent_nap_milli"),
          s.get("id")))


def main():
    print("Whoop Backfill — Zones & Sleep Need")
    token = get_token()
    conn = sqlite3.connect(DB)

    print("\n[1/2] Workouts (HR-Zones)…")
    b, a = backfill(conn, token, "activity/workout",
                    "SELECT * FROM workout_data WHERE zone_zero_milli IS NULL",
                    update_workout_zones, "Workouts")
    print(f"  Done: {b} → {a} (filled {b-a})")

    print("\n[2/2] Sleep (sleep_needed)…")
    b, a = backfill(conn, token, "activity/sleep",
                    "SELECT * FROM sleep_data WHERE baseline_milli IS NULL",
                    update_sleep_need, "Sleep")
    print(f"  Done: {b} → {a} (filled {b-a})")

    conn.close()
    print("\nBackfill complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
