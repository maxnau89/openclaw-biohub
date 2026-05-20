#!/usr/bin/env python3
"""Generate deterministic synthetic data for openclaw-biohub.

Creates two SQLite files:
  - $OPENCLAW_BIOHUB_HOME/data/health.db
  - $OPENCLAW_BIOHUB_HOME/data/whoop_raw.db

…matching the schema in `db/schema.sql` and populated with ~90 days of
plausible (but invented) biometrics, a couple of blood panels, a small
supplement stack, and a few weeks of nutrition logs.

Patterns are deliberately realistic so that the analytics surface
behaves the same as it would on real data:
  - HRV correlates positively with recovery_score
  - Sleep hours correlates positively with sleep_performance_percentage
  - High daily_strain on day N → lower recovery_score on day N+1
  - One injected anomaly window (5 days of low recovery + low HRV)

Run:
    OPENCLAW_BIOHUB_HOME=/tmp/oh python3 fixtures/seed.py

Idempotent: drops and recreates the DBs on each run.
"""
from __future__ import annotations

import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 42
DAYS = 90
USER_ID = 1
SCHEMA_FILE = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def resolve_paths() -> tuple[Path, Path]:
    home = Path(os.environ.get("OPENCLAW_BIOHUB_HOME", "/opt/openclaw-biohub"))
    data_dir = home / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "health.db", data_dir / "whoop_raw.db"


def split_schema(text: str) -> tuple[str, str]:
    """Schema file contains both DBs separated by the '-- DB 2:' marker line."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.lstrip().startswith("-- DB 2:"):
            return "".join(lines[:i]), "".join(lines[i + 1:])
    raise RuntimeError("Schema marker '-- DB 2:' not found")


def apply_schema(conn: sqlite3.Connection, ddl: str) -> None:
    conn.executescript(ddl)


def _walk(start_value: float, drift: float, noise: float, length: int,
          lo: float, hi: float) -> list[float]:
    """Random-walk a metric within bounds. Deterministic given SEED."""
    rng = random.Random(SEED + int(start_value * 1000))
    out: list[float] = []
    v = start_value
    for _ in range(length):
        v += rng.gauss(drift, noise)
        v = max(lo, min(hi, v))
        out.append(v)
    return out


def generate_whoop(conn: sqlite3.Connection) -> list[dict]:
    rng = random.Random(SEED)
    # User profile + body measurements
    conn.execute(
        "INSERT INTO user_profile (user_id, first_name, last_name, email) VALUES (?,?,?,?)",
        (USER_ID, "Test", "User", "test@example.com"),
    )
    conn.execute(
        "INSERT INTO body_measurements (user_id, height_meter, weight_kilogram, max_heart_rate) "
        "VALUES (?,?,?,?)",
        (USER_ID, 1.78, 75.0, 190),
    )

    # Generate correlated baseline series
    hrv_series = _walk(58, 0.0, 4.0, DAYS, 30, 90)
    rhr_series = [max(50, min(80, 65 - 0.2 * (h - 58) + rng.gauss(0, 2))) for h in hrv_series]
    spo2_series = [max(93, min(100, 97 + rng.gauss(0, 0.6))) for _ in range(DAYS)]
    skin_temp = [rng.gauss(34.5, 0.3) for _ in range(DAYS)]
    strain_series = _walk(11, 0.0, 2.5, DAYS, 4, 19)
    sleep_hours_series = _walk(7.2, 0.0, 0.6, DAYS, 4.5, 9.5)

    # Inject a 5-day anomaly window (day 60..64): HRV crash + low recovery
    for i in range(60, 65):
        hrv_series[i] = max(25, hrv_series[i] - 22)
        sleep_hours_series[i] = max(4, sleep_hours_series[i] - 1.5)

    # Yesterday's strain bleeds into today's recovery (centered ~60% on baseline)
    recovery: list[float] = []
    for i in range(DAYS):
        base = 60 + 0.5 * (hrv_series[i] - 58) + 4.0 * (sleep_hours_series[i] - 7)
        prev_strain = strain_series[i - 1] if i > 0 else strain_series[i]
        adj = base - 1.2 * (prev_strain - 11)
        recovery.append(max(5, min(99, adj + rng.gauss(0, 5))))

    start = datetime.now(timezone.utc).replace(tzinfo=None).replace(hour=8, minute=0, second=0, microsecond=0) \
        - timedelta(days=DAYS - 1)

    daily_rollup: list[dict] = []
    for i in range(DAYS):
        dt = start + timedelta(days=i)
        cycle_id = 1000 + i

        # cycles_data
        conn.execute(
            "INSERT INTO cycles_data (id, user_id, created_at, updated_at, start_time, "
            "end_time, timezone_offset, score_state, strain, kilojoule, "
            "average_heart_rate, max_heart_rate) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (cycle_id, USER_ID, dt.isoformat(), dt.isoformat(),
             dt.isoformat(), (dt + timedelta(hours=16)).isoformat(),
             "+00:00", "SCORED", round(strain_series[i], 2),
             round(strain_series[i] * 500 + rng.gauss(0, 200), 1),
             round(rhr_series[i] + 15, 1), round(rhr_series[i] + 80, 1)),
        )

        # recovery_data
        conn.execute(
            "INSERT INTO recovery_data (cycle_id, sleep_id, user_id, created_at, updated_at, "
            "score_state, user_calibrating, recovery_score, resting_heart_rate, "
            "hrv_rmssd_milli, spo2_percentage, skin_temp_celsius) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (cycle_id, f"sleep-{cycle_id}", USER_ID, dt.isoformat(), dt.isoformat(),
             "SCORED", 0, round(recovery[i]), round(rhr_series[i]),
             round(hrv_series[i], 2), round(spo2_series[i], 2), round(skin_temp[i], 2)),
        )

        # sleep_data
        in_bed_ms = int(sleep_hours_series[i] * 3600 * 1000)
        rem_ms = int(in_bed_ms * 0.22)
        deep_ms = int(in_bed_ms * 0.18)
        light_ms = int(in_bed_ms * 0.55)
        awake_ms = in_bed_ms - rem_ms - deep_ms - light_ms
        sleep_perf = int(min(100, max(20, sleep_hours_series[i] / 8 * 100 + rng.gauss(0, 5))))
        sleep_eff = max(70, min(99, 92 + rng.gauss(0, 3)))
        conn.execute(
            "INSERT INTO sleep_data (id, cycle_id, user_id, created_at, updated_at, "
            "start_time, end_time, timezone_offset, nap, score_state, "
            "total_in_bed_time_milli, total_awake_time_milli, total_no_data_time_milli, "
            "total_light_sleep_time_milli, total_slow_wave_sleep_time_milli, "
            "total_rem_sleep_time_milli, sleep_cycle_count, disturbance_count, "
            "respiratory_rate, sleep_performance_percentage, sleep_consistency_percentage, "
            "sleep_efficiency_percentage) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"sleep-{cycle_id}", cycle_id, USER_ID, dt.isoformat(), dt.isoformat(),
             (dt - timedelta(hours=8)).isoformat(), dt.isoformat(),
             "+00:00", 0, "SCORED",
             in_bed_ms, awake_ms, 0, light_ms, deep_ms, rem_ms,
             5, rng.randint(0, 12),
             round(rng.gauss(15, 1), 1), sleep_perf,
             rng.randint(60, 95), round(sleep_eff, 1)),
        )

        # workouts: sometimes
        if rng.random() < 0.5:
            wo_id = f"wo-{cycle_id}-{rng.randint(0, 999)}"
            zones = [rng.randint(0, 1800000) for _ in range(6)]
            conn.execute(
                "INSERT INTO workout_data (id, user_id, created_at, updated_at, start_time, "
                "end_time, timezone_offset, sport_name, sport_id, score_state, strain, "
                "average_heart_rate, max_heart_rate, kilojoule, percent_recorded, "
                "distance_meter, altitude_gain_meter, altitude_change_meter, "
                "zone_zero_milli, zone_one_milli, zone_two_milli, zone_three_milli, "
                "zone_four_milli, zone_five_milli) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (wo_id, USER_ID, dt.isoformat(), dt.isoformat(),
                 dt.isoformat(), (dt + timedelta(hours=1)).isoformat(),
                 "+00:00", rng.choice(["Running", "Cycling", "Strength"]), 0, "SCORED",
                 round(strain_series[i] * 0.6, 2),
                 round(rhr_series[i] + 50, 1), round(rhr_series[i] + 90, 1),
                 round(rng.uniform(200, 800), 1), 100.0,
                 round(rng.uniform(0, 12000), 1), 0.0, 0.0, *zones),
            )

        daily_rollup.append({
            "date": dt.strftime("%Y-%m-%d"),
            "recovery_score": round(recovery[i]),
            "hrv_ms": round(hrv_series[i], 2),
            "resting_hr": round(rhr_series[i]),
            "spo2": round(spo2_series[i], 2),
            "skin_temp_c": round(skin_temp[i], 2),
            "sleep_performance": sleep_perf,
            "sleep_hours": round(sleep_hours_series[i], 2),
            "sleep_efficiency": round(sleep_eff, 1),
            "rem_hours": round(rem_ms / 3600000, 2),
            "deep_sleep_hours": round(deep_ms / 3600000, 2),
            "light_sleep_hours": round(light_ms / 3600000, 2),
            "day_strain": round(strain_series[i], 2),
            "calories_burned": int(strain_series[i] * 250),
        })

    return daily_rollup


def generate_health(conn: sqlite3.Connection, daily_rollup: list[dict]) -> None:
    rng = random.Random(SEED + 1)

    # daily_metrics rollup (source-agnostic; WHOOP is the source here)
    for row in daily_rollup:
        conn.execute(
            "INSERT INTO daily_metrics (source, date, recovery_score, hrv_ms, resting_hr, spo2, "
            "skin_temp_c, sleep_performance, sleep_hours, sleep_efficiency, rem_hours, "
            "deep_sleep_hours, light_sleep_hours, day_strain, calories_burned) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("whoop", row["date"], row["recovery_score"], row["hrv_ms"], row["resting_hr"],
             row["spo2"], row["skin_temp_c"], row["sleep_performance"],
             row["sleep_hours"], row["sleep_efficiency"], row["rem_hours"],
             row["deep_sleep_hours"], row["light_sleep_hours"],
             row["day_strain"], row["calories_burned"]),
        )

    # Two blood panels (60 days apart)
    base = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=90)
    for panel_idx, days_ago in enumerate([60, 5]):
        panel_date = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        cur = conn.execute(
            "INSERT INTO blood_panels (panel_date, lab_name, notes, source_filename, raw_text) "
            "VALUES (?,?,?,?,?)",
            (panel_date, "Synthetic Lab Co.", "Sample data — not real",
             f"sample-panel-{panel_idx}.pdf", "(synthetic)"),
        )
        panel_id = cur.lastrowid

        # Representative marker set (small selection across categories)
        markers = [
            ("Hemoglobin", "g/dl",  13.5, 17.5, lambda: rng.uniform(14.0, 16.5)),
            ("WBC",        "/nl",    4.0, 10.0, lambda: rng.uniform(5.0, 8.0)),
            ("Glucose",    "mg/dl", 70,  100,   lambda: rng.uniform(75, 95)),
            ("HbA1c (DCCT)", "%",    4.0, 5.7,  lambda: rng.uniform(4.8, 5.3)),
            ("Cholesterol", "mg/dl", 0,   200,  lambda: rng.uniform(150, 195)),
            ("LDL",        "mg/dl",  0,  130,   lambda: rng.uniform(80, 125)),
            ("HDL",        "mg/dl", 40,  100,   lambda: rng.uniform(50, 70)),
            ("Triglycerides", "mg/dl", 0, 150,  lambda: rng.uniform(70, 140)),
            ("ALT (GPT)",  "U/l",    0,  45,    lambda: rng.uniform(15, 35)),
            ("Creatinine", "mg/dl",  0.6, 1.2,  lambda: rng.uniform(0.7, 1.1)),
            ("Vitamin D",  "ng/ml", 30,  100,   lambda: rng.uniform(28, 55)),
            ("Testosterone", "ng/ml", 2.5, 8.4, lambda: rng.uniform(4.5, 7.0)),
            ("TSH",        "mU/l",   0.4, 4.0,  lambda: rng.uniform(1.0, 2.5)),
        ]
        for name, unit, lo, hi, gen in markers:
            v = round(gen(), 2)
            status = "normal"
            if v < lo: status = "low"
            elif v > hi: status = "high"
            conn.execute(
                "INSERT INTO blood_markers (panel_id, marker_name, value, unit, "
                "ref_low, ref_high, status) VALUES (?,?,?,?,?,?,?)",
                (panel_id, name, v, unit, lo, hi, status),
            )

    # Supplement stack
    supplements = [
        ("Magnesium Glycinate", "magnesium", "Now Foods", 400, "mg", "capsule", 2),
        ("Vitamin D3",          "vitamin d", "Generic",   5000, "IU", "softgel", 168),
        ("Creatine Monohydrate","creatine",  "Bulk",      5000, "mg", "powder",  24),
        ("Omega-3",             "epa+dha",   "Nordic",    2000, "mg", "softgel", 48),
    ]
    supplement_ids: list[int] = []
    for name, ai, brand, dose, unit, form, lag in supplements:
        cur = conn.execute(
            "INSERT INTO supplements (name, active_ingredient, brand, dose_mg, "
            "dose_unit, form, default_lag_hours) VALUES (?,?,?,?,?,?,?)",
            (name, ai, brand, dose, unit, form, lag),
        )
        supplement_ids.append(cur.lastrowid)

    # Log intakes: each supplement taken ~5/7 days
    log_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=DAYS)
    for i in range(DAYS):
        dt = log_start + timedelta(days=i)
        for sid, (name, _, _, dose, unit, _, _) in zip(supplement_ids, supplements):
            if rng.random() < 5 / 7:
                conn.execute(
                    "INSERT INTO supplement_log (supplement_id, taken_at, dose_mg, "
                    "dose_unit, source) VALUES (?,?,?,?,?)",
                    (sid, dt.replace(hour=8).isoformat(), dose, unit, "fixture"),
                )

    # Nutrition logs: last 30 days
    for i in range(30):
        dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=i)
        conn.execute(
            "INSERT INTO nutrition_logs (log_date, meal_type, calories, protein_g, "
            "carbs_g, fat_g, fiber_g, water_ml) VALUES (?,?,?,?,?,?,?,?)",
            (dt.strftime("%Y-%m-%d"), "day_total",
             rng.randint(1800, 2800),
             round(rng.uniform(110, 180), 1),
             round(rng.uniform(180, 320), 1),
             round(rng.uniform(60, 110), 1),
             round(rng.uniform(20, 45), 1),
             rng.randint(1800, 3500)),
        )


def main() -> int:
    health_db_path, whoop_db_path = resolve_paths()
    for p in (health_db_path, whoop_db_path):
        if p.exists():
            p.unlink()

    schema_text = SCHEMA_FILE.read_text()
    db1_ddl, db2_ddl = split_schema(schema_text)

    with sqlite3.connect(whoop_db_path) as wconn:
        apply_schema(wconn, db2_ddl)
        rollup = generate_whoop(wconn)
        wconn.commit()

    with sqlite3.connect(health_db_path) as hconn:
        apply_schema(hconn, db1_ddl)
        generate_health(hconn, rollup)
        hconn.commit()

    print(f"Wrote {DAYS} days of synthetic data:")
    print(f"  {health_db_path}")
    print(f"  {whoop_db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
