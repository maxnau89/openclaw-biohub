#!/usr/bin/env python3
"""Apple Health adapter — file-based ingest.

Apple Health doesn't expose a server-side API. The two reasonable
ingestion paths are:

1. **Health Auto Export iOS app** (recommended) — a paid iOS app that
   writes daily / on-change JSON dumps to a folder. The user
   configures the app to write to a directory that this adapter
   watches. Format documented at: https://www.healthexportapp.com/
2. **Native Health.app export** — Settings → Health → Export All
   Health Data produces `export.zip` containing `export.xml`. One-shot,
   parsed by `sync()` if the user drops it into the watch directory.

The watch directory path is stored in
`$OPENCLAW_BIOHUB_HOME/secrets/apple-health.json`.

Run as a standalone sync:
    python3 pipeline/adapters/apple_health/sync.py
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Put pipeline/ on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from adapters.base import BiometricAdapter, SyncResult
from paths import APPLE_HEALTH_DB, HEALTH_DB

SOURCE = "apple-health"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"


# ─── Metric-name normalization ───────────────────────────────────────────────
# Health Auto Export sometimes uses HK identifiers, sometimes slugged names.
# Normalize to slugs we use in the rollup.
_HK_TO_SLUG = {
    "HKQuantityTypeIdentifierHeartRate": "heart_rate",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_heart_rate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "heart_rate_variability",
    "HKQuantityTypeIdentifierOxygenSaturation": "blood_oxygen_saturation",
    "HKQuantityTypeIdentifierStepCount": "step_count",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "active_energy_burned",
    "HKQuantityTypeIdentifierBasalEnergyBurned": "basal_energy_burned",
    "HKQuantityTypeIdentifierAppleExerciseTime": "apple_exercise_time",
    "HKQuantityTypeIdentifierBodyMass": "body_mass",
    "HKQuantityTypeIdentifierBodyTemperature": "body_temperature",
    "HKQuantityTypeIdentifierAppleSleepingWristTemperature": "wrist_temperature",
    "HKCategoryTypeIdentifierSleepAnalysis": "sleep_analysis",
    # v0.3: nutrition (consumed) — rolls up into health.db nutrition_logs.
    "HKQuantityTypeIdentifierDietaryEnergyConsumed": "dietary_energy",
    "HKQuantityTypeIdentifierDietaryProtein":       "protein",
    "HKQuantityTypeIdentifierDietaryCarbohydrates": "carbohydrates",
    "HKQuantityTypeIdentifierDietaryFatTotal":      "total_fat",
    "HKQuantityTypeIdentifierDietaryFiber":         "dietary_fiber",
    "HKQuantityTypeIdentifierDietaryWater":         "dietary_water",
}


def normalize_metric_name(name: str) -> str:
    return _HK_TO_SLUG.get(name, name.lower().replace(" ", "_"))


# ─── JSON parser (Health Auto Export-style) ──────────────────────────────────


import re

_TZ_NO_COLON = re.compile(r"([+\-])(\d{2})(\d{2})$")


def _date_str(dt_str: str) -> str:
    """Apple Health timestamps come as 'YYYY-MM-DD HH:MM:SS +ZZZZ'.
    SQLite's date/time functions require '+ZZ:ZZ' for the timezone
    offset — insert the colon if it's missing, otherwise julianday()
    returns NULL and our duration math breaks silently.
    """
    s = dt_str.strip()
    return _TZ_NO_COLON.sub(r"\1\2:\3", s)


def _date_only(dt_str: str) -> str:
    """Extract YYYY-MM-DD prefix for daily grouping."""
    return _date_str(dt_str)[:10]


def parse_health_export_json(payload: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Parse a Health Auto Export JSON dump into:
      - metric_samples rows (heart_rate, hrv, spo2, steps, energy, ...)
      - sleep_samples rows
      - workout_samples rows
    The payload's top level is `{"data": {"metrics": [...], "workouts": [...]}}`.
    """
    data = payload.get("data", {})
    metric_rows: list[dict] = []
    sleep_rows: list[dict] = []
    workout_rows: list[dict] = []

    for metric in data.get("metrics", []) or []:
        name = normalize_metric_name(metric.get("name", ""))
        unit = metric.get("units")

        if name == "sleep_analysis":
            for s in metric.get("data", []) or []:
                start = s.get("startDate") or s.get("sleepStart") or s.get("date")
                end = s.get("endDate") or s.get("sleepEnd")
                value = s.get("value") or "Asleep"  # default if app emits just "Asleep" rows
                if not start or not end:
                    continue
                sid = s.get("uuid") or f"sleep:{start}:{value}"
                sleep_rows.append({
                    "id": sid,
                    "sleep_start": _date_str(start),
                    "sleep_end": _date_str(end),
                    "value": value,
                    "source": s.get("source"),
                })
        else:
            for s in metric.get("data", []) or []:
                d = s.get("date")
                qty = s.get("qty")
                if d is None or qty is None:
                    continue
                sid = s.get("uuid") or f"{name}:{d}"
                metric_rows.append({
                    "id": sid,
                    "metric_name": name,
                    "date": _date_str(d),
                    "value": qty,
                    "unit": unit,
                    "source": s.get("source"),
                })

    for w in data.get("workouts", []) or []:
        start = w.get("start") or w.get("startDate")
        end = w.get("end") or w.get("endDate")
        wid = w.get("uuid") or f"workout:{start}:{w.get('name','')}"
        workout_rows.append({
            "id": wid,
            "workout_type": w.get("name") or w.get("activity") or w.get("workoutType"),
            "start_date": _date_str(start) if start else None,
            "end_date": _date_str(end) if end else None,
            "total_energy_burned": (w.get("totalEnergyBurned") or {}).get("qty")
                if isinstance(w.get("totalEnergyBurned"), dict) else w.get("totalEnergyBurned"),
            "total_distance": (w.get("totalDistance") or {}).get("qty")
                if isinstance(w.get("totalDistance"), dict) else w.get("totalDistance"),
            "source": w.get("source"),
        })

    return metric_rows, sleep_rows, workout_rows


def parse_health_export_csv(fp: "Path") -> tuple[list[dict], list[dict], list[dict]]:
    """Parse a Health Auto Export "Aggregated" CSV into metric rows.

    HAE CSV has a Date column plus one column per metric, headers carrying
    the unit in brackets, e.g. `Heart Rate [count/min]`, `Step Count [count]`.
    Each non-empty numeric cell becomes a metric_sample. Sleep and workouts
    aren't representable in the aggregate CSV, so only metrics are returned
    (JSON push remains the richer path).
    """
    import csv

    metric_rows: list[dict] = []
    with open(fp, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return [], [], []
        date_col = next(
            (c for c in reader.fieldnames if c and c.strip().lower() in ("date", "date/time", "timestamp")),
            reader.fieldnames[0],
        )
        # Pre-parse (metric_name, unit) for each value column.
        cols: dict[str, tuple[str, str | None]] = {}
        for c in reader.fieldnames:
            if not c or c == date_col:
                continue
            m = re.match(r"^\s*(.*?)\s*(?:\[(.*?)\])?\s*$", c)
            raw_name, unit = (m.group(1), m.group(2)) if m else (c, None)
            cols[c] = (normalize_metric_name(raw_name), unit)
        for row in reader:
            d = (row.get(date_col) or "").strip()
            if not d:
                continue
            date_iso = _date_str(d)
            for col, (name, unit) in cols.items():
                raw = (row.get(col) or "").strip().replace(",", ".")
                if not raw:
                    continue
                try:
                    value = float(raw)
                except ValueError:
                    continue
                metric_rows.append({
                    "id": f"{name}:{date_iso}",
                    "metric_name": name,
                    "date": date_iso,
                    "value": value,
                    "unit": unit,
                    "source": "health-auto-export-csv",
                })
    return metric_rows, [], []


# ─── DB helpers ──────────────────────────────────────────────────────────────


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_FILE.read_text())


def _upsert_many(conn: sqlite3.Connection, table: str, cols: list[str], rows: list[dict]) -> int:
    if not rows:
        return 0
    placeholders = ",".join("?" for _ in cols)
    col_list = ",".join(cols)
    sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"
    conn.executemany(sql, [[r.get(c) for c in cols] for r in rows])
    return len(rows)


_METRIC_COLS = ["id", "metric_name", "date", "value", "unit", "source"]
_SLEEP_COLS = ["id", "sleep_start", "sleep_end", "value", "source"]
_WORKOUT_COLS = ["id", "workout_type", "start_date", "end_date",
                 "total_energy_burned", "total_distance", "source"]


# ─── Rollup to daily_metrics ─────────────────────────────────────────────────
# Apple Health's stream model means rollup is Python aggregation, not a
# single SQL view. We group by YYYY-MM-DD of the sample timestamp.


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

        # ── Aggregate metric samples by day ────────────────────────────
        # SQLite's substr() gives us reliable YYYY-MM-DD prefix even when
        # the timestamp uses a space separator (not ISO T).
        metric_aggs = src.execute("""
            SELECT
                substr(date, 1, 10) AS day,
                metric_name,
                AVG(value)          AS avg_val,
                MIN(value)          AS min_val,
                MAX(value)          AS max_val,
                SUM(value)          AS sum_val,
                COUNT(*)            AS n
            FROM metric_samples
            WHERE substr(date, 1, 10) > ?
            GROUP BY day, metric_name
        """, (last,)).fetchall()

        per_day: dict[str, dict] = defaultdict(dict)
        for r in metric_aggs:
            day = r["day"]
            name = r["metric_name"]
            per_day[day][name] = dict(r)

        # ── Aggregate sleep samples ────────────────────────────────────
        sleep_aggs = src.execute("""
            SELECT
                substr(sleep_start, 1, 10) AS day,
                value,
                SUM((julianday(sleep_end) - julianday(sleep_start)) * 86400.0) AS seconds
            FROM sleep_samples
            WHERE substr(sleep_start, 1, 10) > ?
            GROUP BY day, value
        """, (last,)).fetchall()

        for r in sleep_aggs:
            day = r["day"]
            per_day[day].setdefault("_sleep", {})[r["value"]] = r["seconds"]

        # ── Build daily_metrics rows ───────────────────────────────────
        count = 0
        for day in sorted(per_day):
            m = per_day[day]
            sleep = m.get("_sleep", {})

            # Sum of all "asleep-ish" phases. Different Apple Watch firmware
            # emits different label sets; cover the major ones.
            asleep_phases = ("Asleep", "REM", "Deep", "Core", "Light", "Awake")
            asleep_secs = sum(sleep.get(p, 0) or 0
                              for p in asleep_phases if p != "Awake")
            in_bed_secs = sum(sleep.get(p, 0) or 0 for p in asleep_phases)
            sleep_hours = round(asleep_secs / 3600.0, 2) if asleep_secs else None
            sleep_efficiency = round(asleep_secs / in_bed_secs, 3) if in_bed_secs else None
            rem_hours = round((sleep.get("REM") or 0) / 3600.0, 2) if sleep.get("REM") else None
            deep_hours = round((sleep.get("Deep") or 0) / 3600.0, 2) if sleep.get("Deep") else None
            light_hours = round((sleep.get("Core") or 0) / 3600.0, 2) if sleep.get("Core") else None

            hrv_avg = m.get("heart_rate_variability", {}).get("avg_val") if "heart_rate_variability" in m else None
            spo2_avg = m.get("blood_oxygen_saturation", {}).get("avg_val") if "blood_oxygen_saturation" in m else None
            rhr_val = m.get("resting_heart_rate", {}).get("avg_val") if "resting_heart_rate" in m else None
            # Fallback: if no resting_heart_rate samples, use MIN of regular HR.
            if rhr_val is None and "heart_rate" in m:
                rhr_val = m["heart_rate"]["min_val"]
            steps = int(m["step_count"]["sum_val"]) if "step_count" in m else None
            active_cal = m.get("active_energy_burned", {}).get("sum_val") if "active_energy_burned" in m else 0
            basal_cal = m.get("basal_energy_burned", {}).get("sum_val") if "basal_energy_burned" in m else 0
            calories = int((active_cal or 0) + (basal_cal or 0)) if (active_cal or basal_cal) else None
            active_min = (m.get("apple_exercise_time", {}).get("sum_val")
                           if "apple_exercise_time" in m else None)
            skin_temp = (m.get("wrist_temperature", {}).get("avg_val")
                          if "wrist_temperature" in m else
                          (m.get("body_temperature", {}).get("avg_val")
                           if "body_temperature" in m else None))

            # Skip days with no actually-useful data (e.g. only an "Awake"
            # sleep interval spilling over from the night before).
            if not any([sleep_hours, hrv_avg, rhr_val, spo2_avg, steps, calories]):
                continue

            dst.execute("""
                INSERT INTO daily_metrics
                    (source, date, recovery_score, hrv_ms, resting_hr, spo2, skin_temp_c,
                     sleep_performance, sleep_hours, sleep_efficiency, rem_hours,
                     deep_sleep_hours, light_sleep_hours, day_strain, calories_burned,
                     steps, active_minutes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source, date) DO UPDATE SET
                    hrv_ms=excluded.hrv_ms, resting_hr=excluded.resting_hr,
                    spo2=excluded.spo2, skin_temp_c=excluded.skin_temp_c,
                    sleep_hours=excluded.sleep_hours,
                    sleep_efficiency=excluded.sleep_efficiency,
                    rem_hours=excluded.rem_hours, deep_sleep_hours=excluded.deep_sleep_hours,
                    light_sleep_hours=excluded.light_sleep_hours,
                    calories_burned=excluded.calories_burned, steps=excluded.steps,
                    active_minutes=excluded.active_minutes
            """, (
                SOURCE, day,
                None,             # recovery_score: Apple Health has none
                hrv_avg, rhr_val, spo2_avg, skin_temp,
                None,             # sleep_performance: no equivalent
                sleep_hours, sleep_efficiency,
                rem_hours, deep_hours, light_hours,
                None,             # day_strain: no equivalent
                calories, steps, active_min,
            ))
            count += 1

        # ─── v0.3: weight → body_composition (filtered upsert) ───────────────
        # Don't clobber rows from caliper / DEXA / manual entries — those win
        # over Apple-Health scale readings. Same-day apple-health rows update.
        last_weight = dst.execute(
            "SELECT MAX(date) FROM body_composition WHERE method = 'apple-health'"
        ).fetchone()[0] or "2000-01-01"
        weight_rows = src.execute("""
            SELECT substr(date, 1, 10) AS day,
                   AVG(value) AS avg_kg
            FROM metric_samples
            WHERE metric_name = 'body_mass'
              AND substr(date, 1, 10) > ?
            GROUP BY day
        """, (last_weight,)).fetchall()
        for r in weight_rows:
            dst.execute("""
                INSERT INTO body_composition (date, method, weight_kg)
                VALUES (?, 'apple-health', ROUND(?, 2))
                ON CONFLICT(date) DO UPDATE SET
                    weight_kg = excluded.weight_kg,
                    method = excluded.method
                WHERE body_composition.method IS NULL
                   OR body_composition.method = 'apple-health'
            """, (r["day"], r["avg_kg"]))

        # ─── v0.3: macros → nutrition_logs (one day_total row per date) ──────
        # Assumes dietary_energy is in kcal (Apple Health's most common unit).
        # If the export uses kJ, divide by 4.184 here — left as a v0.4 TODO.
        last_nutrition = dst.execute(
            "SELECT MAX(log_date) FROM nutrition_logs"
        ).fetchone()[0] or "2000-01-01"
        macro_rows = src.execute("""
            SELECT substr(date, 1, 10) AS day,
                   metric_name,
                   SUM(value) AS total
            FROM metric_samples
            WHERE metric_name IN (
                'dietary_energy', 'protein', 'carbohydrates',
                'total_fat', 'dietary_fiber', 'dietary_water'
            )
              AND substr(date, 1, 10) > ?
            GROUP BY day, metric_name
        """, (last_nutrition,)).fetchall()
        nutrition_per_day: dict[str, dict] = defaultdict(dict)
        for r in macro_rows:
            nutrition_per_day[r["day"]][r["metric_name"]] = r["total"]
        for day, m in nutrition_per_day.items():
            # nutrition_logs has no UNIQUE constraint on (log_date, meal_type);
            # delete-then-insert to keep one day_total row per date.
            dst.execute(
                "DELETE FROM nutrition_logs WHERE log_date = ? AND meal_type = 'day_total'",
                (day,),
            )
            water_ml = m.get("dietary_water")
            dst.execute("""
                INSERT INTO nutrition_logs
                    (log_date, meal_type, calories, protein_g, carbs_g, fat_g, fiber_g, water_ml)
                VALUES (?, 'day_total', ?, ?, ?, ?, ?, ?)
            """, (
                day,
                int(m["dietary_energy"]) if "dietary_energy" in m else None,
                m.get("protein"),
                m.get("carbohydrates"),
                m.get("total_fat"),
                m.get("dietary_fiber"),
                int(water_ml * 1000) if water_ml is not None else None,  # litres → ml
            ))

        dst.commit()
        return count
    finally:
        src.close()
        dst.close()


# ─── Native Health.app XML export support ────────────────────────────────────


def parse_native_xml_export(xml_path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """Parse the `export.xml` from Settings → Health → Export All Health Data.

    Uses iterparse for memory-efficiency — the export is often hundreds
    of MB.
    """
    from xml.etree import ElementTree as ET
    metric_rows: list[dict] = []
    sleep_rows: list[dict] = []
    workout_rows: list[dict] = []

    for _, elem in ET.iterparse(str(xml_path), events=("end",)):
        tag = elem.tag
        if tag == "Record":
            type_ = elem.get("type") or ""
            start = elem.get("startDate")
            end = elem.get("endDate")
            value = elem.get("value")
            source = elem.get("sourceName")
            unit = elem.get("unit")
            if type_ == "HKCategoryTypeIdentifierSleepAnalysis":
                sleep_rows.append({
                    "id": f"sleep:{start}:{value}",
                    "sleep_start": start,
                    "sleep_end": end,
                    "value": (value or "").replace("HKCategoryValueSleepAnalysis", ""),
                    "source": source,
                })
            else:
                name = normalize_metric_name(type_)
                try:
                    fval = float(value) if value is not None else None
                except ValueError:
                    fval = None
                if fval is not None and start:
                    metric_rows.append({
                        "id": f"{name}:{start}",
                        "metric_name": name,
                        "date": start,
                        "value": fval,
                        "unit": unit,
                        "source": source,
                    })
            elem.clear()
        elif tag == "Workout":
            workout_rows.append({
                "id": f"workout:{elem.get('startDate')}:{elem.get('workoutActivityType')}",
                "workout_type": elem.get("workoutActivityType"),
                "start_date": elem.get("startDate"),
                "end_date": elem.get("endDate"),
                "total_energy_burned": float(elem.get("totalEnergyBurned"))
                    if elem.get("totalEnergyBurned") else None,
                "total_distance": float(elem.get("totalDistance"))
                    if elem.get("totalDistance") else None,
                "source": elem.get("sourceName"),
            })
            elem.clear()

    return metric_rows, sleep_rows, workout_rows


# ─── Adapter ─────────────────────────────────────────────────────────────────


class AppleHealthAdapter(BiometricAdapter):
    slug = "apple-health"
    display_name = "Apple Health"
    raw_db_name = "apple_health_raw.db"
    stability = "stable"
    requires_oauth = False

    def setup_instructions(self) -> str:
        return """\
**Apple Health** doesn't expose a server-side API, so this adapter
reads files dropped into a watch directory you configure. Two
ingestion modes are supported:

1. **Health Auto Export iOS app** (recommended for ongoing sync)

   Buy the app from the App Store, configure it to write JSON dumps
   to a folder you can reach from this host (iCloud Drive, Dropbox,
   a self-hosted WebDAV mount, etc.). The adapter will pick up new
   files on each `biohub sync apple-health`.

   App store: <https://apps.apple.com/app/health-auto-export/id1115567069>

2. **Native Health.app export** (one-shot bulk import)

   On your iPhone: Settings → Health → tap your profile → Export
   All Health Data. AirDrop / share the resulting `export.zip` to
   this host and drop it into the same watch directory.

You'll be asked for the watch directory path next.
"""

    def configure_interactive(self) -> None:
        watch_dir = input(
            "  Path to watch for Apple Health exports "
            "(e.g. ~/Documents/AppleHealthExports): "
        ).strip()
        if not watch_dir:
            raise SystemExit("No path provided; aborting.")
        watch = Path(watch_dir).expanduser()
        watch.mkdir(parents=True, exist_ok=True)
        self.secrets_path.parent.mkdir(parents=True, exist_ok=True)
        self.secrets_path.write_text(json.dumps({"watch_dir": str(watch)}))
        self.secrets_path.chmod(0o600)
        print(f"Saved watch directory: {watch}")

    def _watch_dir(self) -> Path:
        if not self.secrets_path.exists():
            raise FileNotFoundError(
                f"No Apple Health config at {self.secrets_path}. "
                "Run `biohub connect apple-health` first."
            )
        d = json.loads(self.secrets_path.read_text())["watch_dir"]
        return Path(d).expanduser()

    def _ingest_file(self, conn: sqlite3.Connection, fp: Path) -> int:
        """Parse one file (JSON or export.zip/xml) into the raw DB.
        Returns count of rows inserted across all 3 sample tables.
        Skips files we've already imported at this mtime."""
        try:
            mtime = int(fp.stat().st_mtime)
        except OSError:
            return 0

        # Idempotency check
        seen = conn.execute(
            "SELECT 1 FROM import_log WHERE file_path = ? AND file_mtime = ? AND success = 1",
            (str(fp), mtime),
        ).fetchone()
        if seen:
            return 0

        try:
            metrics: list[dict] = []
            sleeps: list[dict] = []
            workouts: list[dict] = []
            if fp.suffix.lower() == ".json":
                payload = json.loads(fp.read_text())
                metrics, sleeps, workouts = parse_health_export_json(payload)
            elif fp.suffix.lower() == ".csv":
                metrics, sleeps, workouts = parse_health_export_csv(fp)
            elif fp.suffix.lower() == ".xml":
                metrics, sleeps, workouts = parse_native_xml_export(fp)
            elif fp.suffix.lower() == ".zip":
                with zipfile.ZipFile(fp) as zf:
                    for name in zf.namelist():
                        if name.endswith("export.xml"):
                            with zf.open(name) as xf:
                                tmp = fp.with_suffix(".tmp.xml")
                                tmp.write_bytes(xf.read())
                                try:
                                    metrics, sleeps, workouts = parse_native_xml_export(tmp)
                                finally:
                                    tmp.unlink(missing_ok=True)
                            break
            else:
                return 0

            n = (_upsert_many(conn, "metric_samples", _METRIC_COLS, metrics)
                 + _upsert_many(conn, "sleep_samples", _SLEEP_COLS, sleeps)
                 + _upsert_many(conn, "workout_samples", _WORKOUT_COLS, workouts))
            conn.execute(
                "INSERT INTO import_log (file_path, file_mtime, records_count, success) "
                "VALUES (?, ?, ?, 1)",
                (str(fp), mtime, n),
            )
            conn.commit()
            return n
        except Exception as e:
            conn.execute(
                "INSERT INTO import_log "
                "(file_path, file_mtime, records_count, success, error_message) "
                "VALUES (?, ?, 0, 0, ?)",
                (str(fp), mtime, str(e)),
            )
            conn.commit()
            raise

    def sync(self, since: str | None = None, limit: int | None = None) -> SyncResult:
        watch = self._watch_dir()
        self.raw_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.raw_db_path)
        try:
            _ensure_schema(conn)
            inserted = 0
            files = sorted(
                f for f in watch.iterdir()
                if f.is_file() and f.suffix.lower() in (".json", ".csv", ".xml", ".zip")
            )
            if limit:
                files = files[:limit]
            for fp in files:
                try:
                    inserted += self._ingest_file(conn, fp)
                except Exception as e:
                    return SyncResult(rows_inserted=inserted, error=f"{fp.name}: {e}")
            return SyncResult(rows_inserted=inserted)
        finally:
            conn.close()

    def rollup_to_health_db(self) -> int:
        return _rollup(self.raw_db_path, HEALTH_DB)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apple Health import")
    parser.add_argument("--limit", type=int, help="Max files to ingest")
    args = parser.parse_args()

    print(f"Apple Health Sync — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    adapter = AppleHealthAdapter()
    result = adapter.sync(limit=args.limit)
    try:
        rolled = adapter.rollup_to_health_db()
        print(f"  Rolled up {rolled} rows to daily_metrics (source=apple-health)")
    except Exception as e:
        print(f"  Rollup error: {e}")
    print(f"\nDone. {result}")
    return 0 if not result.error else 1


if __name__ == "__main__":
    sys.exit(main())
