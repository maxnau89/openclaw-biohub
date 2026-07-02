#!/usr/bin/env python3
"""
Glucose (CGM) analytics for FreeStyle Libre 3 / LibreView data.

Reads libre_raw.db (populated by the Libre adapter) and produces JSON:
  - overview: readings, mean, SD, CV %, GMI (estimated HbA1c), and
    time-in-range / hypo / hyper percentages using the standard 70-180 mg/dL
    target band.
  - daily: per-day day-glucose and overnight-glucose means (the overnight
    window 23:00-07:00 is what best tracks next-day recovery).
  - recovery_correlation: Pearson r between overnight mean glucose and the
    next day's recovery_score from health.db's source-agnostic daily_metrics
    (so it works whatever wearable supplies recovery).

Logic adapted from the openclaw workspace `glucose_analysis.py`, generalized
to biohub's multi-source daily_metrics.

Usage: python3 glucose_analytics.py [--days N]
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime, timedelta

from paths import HEALTH_DB, LIBRE_DB

TARGET_LOW, TARGET_HIGH = 70, 180   # standard CGM time-in-range band (mg/dL)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 5:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 3)


def _overview(conn: sqlite3.Connection, since: str) -> dict:
    r = conn.execute(
        """
        SELECT
            COUNT(glucose_mgdl) AS readings,
            AVG(glucose_mgdl) AS mean,
            MIN(glucose_mgdl) AS min_g,
            MAX(glucose_mgdl) AS max_g,
            SQRT(AVG(glucose_mgdl*glucose_mgdl) - AVG(glucose_mgdl)*AVG(glucose_mgdl)) AS sd,
            100.0*COUNT(CASE WHEN glucose_mgdl BETWEEN ? AND ? THEN 1 END)
                 /NULLIF(COUNT(glucose_mgdl),0) AS tir_pct,
            100.0*COUNT(CASE WHEN glucose_mgdl < ? THEN 1 END)
                 /NULLIF(COUNT(glucose_mgdl),0) AS hypo_pct,
            100.0*COUNT(CASE WHEN glucose_mgdl > ? THEN 1 END)
                 /NULLIF(COUNT(glucose_mgdl),0) AS hyper_pct
        FROM glucose_data
        WHERE timestamp >= ? AND glucose_mgdl IS NOT NULL
        """,
        (TARGET_LOW, TARGET_HIGH, TARGET_LOW, TARGET_HIGH, since),
    ).fetchone()
    if not r or not r["readings"]:
        return {"readings": 0}
    mean = r["mean"]
    sd = r["sd"] or 0.0
    return {
        "readings": r["readings"],
        "mean_mgdl": round(mean, 1),
        "min_mgdl": round(r["min_g"], 1),
        "max_mgdl": round(r["max_g"], 1),
        "sd_mgdl": round(sd, 1),
        "cv_pct": round(100 * sd / mean, 1) if mean else None,
        # ADA Glucose Management Indicator (estimated HbA1c) from mean mg/dL.
        "gmi_pct": round(3.31 + 0.02392 * mean, 2),
        "time_in_range_pct": round(r["tir_pct"], 1) if r["tir_pct"] is not None else None,
        "hypo_pct": round(r["hypo_pct"], 1) if r["hypo_pct"] is not None else None,
        "hyper_pct": round(r["hyper_pct"], 1) if r["hyper_pct"] is not None else None,
        "target_low": TARGET_LOW,
        "target_high": TARGET_HIGH,
    }


def _daily(conn: sqlite3.Connection, days: int) -> list[dict]:
    base = datetime.now().date()
    out = []
    for d in range(days):
        day = base - timedelta(days=d)
        night_start = f"{day - timedelta(days=1)}T23:00:00"
        night_end = f"{day}T07:00:00"
        day_start, day_end = f"{day}T07:00:00", f"{day}T22:59:59"

        def _avg(a: str, b: str) -> tuple[float | None, int]:
            row = conn.execute(
                "SELECT AVG(glucose_mgdl), COUNT(glucose_mgdl) FROM glucose_data "
                "WHERE timestamp BETWEEN ? AND ? AND glucose_mgdl IS NOT NULL",
                (a, b),
            ).fetchone()
            return (round(row[0], 1) if row and row[0] is not None else None,
                    row[1] if row else 0)

        night_avg, night_n = _avg(night_start, night_end)
        day_avg, day_n = _avg(day_start, day_end)
        if night_n == 0 and day_n == 0:
            continue
        out.append({
            "date": str(day),
            "night_glucose_avg": night_avg,
            "day_glucose_avg": day_avg,
            "readings": night_n + day_n,
        })
    return sorted(out, key=lambda x: x["date"])


def _recovery_correlation(daily: list[dict]) -> dict:
    """Correlate overnight glucose with the same date's recovery_score from
    health.db daily_metrics (source-agnostic)."""
    if not HEALTH_DB.exists() or not daily:
        return {"r": None, "n": 0}
    hc = sqlite3.connect(f"file:{HEALTH_DB}?mode=ro", uri=True)
    try:
        recov = {
            row[0]: row[1]
            for row in hc.execute(
                "SELECT date, recovery_score FROM daily_metrics "
                "WHERE recovery_score IS NOT NULL"
            ).fetchall()
        }
    finally:
        hc.close()
    xs, ys = [], []
    for d in daily:
        if d["night_glucose_avg"] is not None and d["date"] in recov:
            xs.append(d["night_glucose_avg"])
            ys.append(recov[d["date"]])
    return {
        "r": _pearson(xs, ys),
        "n": len(xs),
        "interpretation": "negative r = higher overnight glucose tracks lower next-day recovery",
    }


def compute(days: int = 90) -> dict:
    if not LIBRE_DB.exists():
        return {"overview": {"readings": 0}, "daily": [], "recovery_correlation": {"r": None, "n": 0},
                "error": "no libre_raw.db — connect the Libre adapter and sync a CSV export"}
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(f"file:{LIBRE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        daily = _daily(conn, days)
        return {
            "days": days,
            "overview": _overview(conn, since),
            "daily": daily,
            "recovery_correlation": _recovery_correlation(daily),
        }
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()
    print(json.dumps(compute(args.days), indent=2))
