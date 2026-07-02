#!/usr/bin/env python3
"""
Physiological Age — a WHOOP-Age-style biological-age estimate.

Estimates how many years "younger" or "older" the user's habits make them
versus their chronological age, by scoring nine health markers on
piecewise-linear benefit/penalty curves and summing the year contributions:

    physiological_age = chronological_age + Σ marker_contributions

Markers (all derived from data biohub already ingests):
    sleep_consistency, sleep_hours, hr_zone_13_weekly, hr_zone_45_weekly,
    strength_weekly, steps, vo2max, resting_hr, lean_mass_pct.

VO₂max is estimated with the Uth–Sørensen formula (VO₂max = 15 · HRmax / RHR),
the same estimator WHOOP uses when no lab measurement is available.

── Calibration provenance ────────────────────────────────────────────────
The marker curves (optimal ranges, max benefit/penalty) were reverse-
engineered from WHOOP "Whoop Age / Pace of Aging" screenshots and validated
to ±0.15 yr per marker against two weekly ground-truth snapshots. WHOOP does
not publish its model, so these curves are a best-effort reconstruction, not
an official formula — treat the output as a directional wellness score, not a
clinical measurement. Chronological age is read from `user_profile.date_of_birth`;
if that is unset the module still returns the delta + per-marker breakdown
(which need no birth date) and flags `needs_date_of_birth`.

Reads health.db (daily_metrics, body_composition, user_profile) and, when
present, whoop_raw.db (sleep_data, workout_data, body_measurements). Markers
whose inputs are unavailable are skipped and reported in `data_completeness`
rather than guessed.

Usage:
    python3 physiological_age.py            # prints JSON to stdout
    from physiological_age import compute_physiological_age
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from paths import HEALTH_DB, WHOOP_DB

# Trailing windows (days). WHOOP scores RHR/VO₂max over ~6 months and
# behavioural markers over recent weeks; we mirror that.
LONG_WINDOW = 180   # RHR average, HRmax observation (for VO₂max)
RECENT_WINDOW = 30  # sleep, steps averages
WEEKLY_WINDOW = 7   # HR-zone and strength "per week" markers

# Sport names WHOOP/biohub label as resistance training. Matched case-
# insensitively as substrings so "Functional Fitness", "Weightlifting",
# "Powerlifting", "Strength Trainer" all count.
STRENGTH_SPORTS = ("weightlifting", "strength", "powerlifting", "functional fitness")


@dataclass
class Marker:
    name: str
    scale_min: float
    scale_max: float
    optimal_low: float
    optimal_high: float
    max_benefit: float       # negative → younger
    max_penalty: float       # positive → older
    higher_is_better: bool = True


def score_marker(m: Marker, value: float) -> float:
    """Piecewise-linear score → Δ-years. Negative rejuvenates, positive ages."""
    if not m.higher_is_better:
        # Mirror the scale so "lower is better" reuses the same logic.
        v = m.scale_min + (m.scale_max - value)
        opt_low_mir = m.scale_min + (m.scale_max - m.optimal_high)
        opt_high_mir = m.scale_min + (m.scale_max - m.optimal_low)
        return score_marker(
            Marker(m.name, m.scale_min, m.scale_max, opt_low_mir, opt_high_mir,
                   m.max_benefit, m.max_penalty, True),
            v,
        )
    v = value
    if v <= m.scale_min:
        return m.max_penalty
    if v >= m.optimal_high:
        return m.max_benefit
    if v >= m.optimal_low:
        t = (v - m.optimal_low) / (m.optimal_high - m.optimal_low)
        return t * m.max_benefit
    t = (v - m.scale_min) / (m.optimal_low - m.scale_min)
    return m.max_penalty * (1.0 - t)


# ── Calibrated marker curves (see "Calibration provenance" above) ────────────
MARKERS: dict[str, Marker] = {
    "sleep_consistency": Marker("Sleep Consistency [%]", 40, 100, 70, 95, -4.17, +2.0),
    "sleep_hours":       Marker("Sleep Hours [h]", 5.0, 8.0, 7.0, 8.0, -1.2, +1.33),
    "hr_zone_13_weekly": Marker("HR Zone 1-3 weekly [h]", 0, 4, 1.5, 3.5, -0.60, +1.0),
    "hr_zone_45_weekly": Marker("HR Zone 4-5 weekly [h]", 0, 1.0, 0.3, 1.0, -1.0, +0.12),
    "strength_weekly":   Marker("Strength weekly [h]", 0, 4, 2.5, 2.5, -1.6, +1.0),
    "steps":             Marker("Steps daily", 0, 16000, 8000, 14000, -1.25, +1.5),
    "vo2max":            Marker("VO2max [ml/kg/min]", 15, 70, 42, 60, -5.8, +3.0),
    "resting_hr":        Marker("Resting HR [bpm]", 40, 80, 50, 60, -1.5, +2.5, higher_is_better=False),
    "lean_mass_pct":     Marker("Lean Mass [%]", 60, 95, 87.5, 93, -1.5, +1.5),
}

# Human-readable grouping for the UI.
MARKER_GROUP = {
    "sleep_consistency": "Sleep", "sleep_hours": "Sleep",
    "hr_zone_13_weekly": "Cardio", "hr_zone_45_weekly": "Cardio",
    "strength_weekly": "Strength", "steps": "Activity",
    "vo2max": "Fitness", "resting_hr": "Fitness", "lean_mass_pct": "Body",
}


# ─── Input derivation from the DBs ───────────────────────────────────────────

def _chronological_age() -> float | None:
    # user_profile lives in whoop_raw.db (the only profile store today). A
    # non-WHOOP user simply has no DOB → delta-only score, honestly flagged.
    if not WHOOP_DB.exists():
        return None
    try:
        wc = sqlite3.connect(f"file:{WHOOP_DB}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = wc.execute(
            "SELECT date_of_birth FROM user_profile WHERE date_of_birth IS NOT NULL "
            "ORDER BY user_id LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        wc.close()
    if not row or not row[0]:
        return None
    try:
        dob = datetime.strptime(str(row[0])[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    today = date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    # Fractional age for a smoother estimate.
    return round(years + (today - date(today.year, dob.month, dob.day)).days / 365.25, 1) \
        if (today.month, today.day) >= (dob.month, dob.day) else float(years)


def _avg(hconn: sqlite3.Connection, col: str, window: int) -> float | None:
    row = hconn.execute(
        f"SELECT AVG({col}) FROM daily_metrics "
        f"WHERE {col} IS NOT NULL AND date >= date('now', ?)",
        (f"-{window} day",),
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def _lean_mass_pct(hconn: sqlite3.Connection) -> float | None:
    row = hconn.execute(
        "SELECT lean_mass_kg, weight_kg, body_fat_pct FROM body_composition "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    lean_kg, weight_kg, bf_pct = row
    if lean_kg and weight_kg:
        return round(lean_kg / weight_kg * 100, 1)
    if bf_pct is not None:
        return round(100 - bf_pct, 1)
    return None


def _whoop_inputs(inputs: dict, sources: dict) -> None:
    """Fill sleep_consistency, HR zones, strength, and HRmax from whoop_raw.db.

    Silently no-ops if whoop_raw.db is absent — those markers are then simply
    skipped (a non-WHOOP user gets a partial score, honestly reported).
    """
    if not WHOOP_DB.exists():
        return
    try:
        wc = sqlite3.connect(f"file:{WHOOP_DB}?mode=ro", uri=True)
    except sqlite3.Error:
        return
    try:
        row = wc.execute(
            "SELECT AVG(sleep_consistency_percentage) FROM sleep_data "
            "WHERE sleep_consistency_percentage IS NOT NULL AND nap = 0 "
            "AND start_time >= datetime('now', ?)",
            (f"-{RECENT_WINDOW} day",),
        ).fetchone()
        if row and row[0] is not None:
            inputs["sleep_consistency"] = round(float(row[0]), 1)
            sources["sleep_consistency"] = "whoop:sleep_consistency_percentage"

        # HR-zone hours per week: sum zone milli-buckets over the trailing week.
        z = wc.execute(
            "SELECT "
            " COALESCE(SUM(zone_one_milli+zone_two_milli+zone_three_milli),0), "
            " COALESCE(SUM(zone_four_milli+zone_five_milli),0) "
            "FROM workout_data WHERE start_time >= datetime('now', ?)",
            (f"-{WEEKLY_WINDOW} day",),
        ).fetchone()
        if z:
            inputs["hr_zone_13_weekly"] = round(z[0] / 3_600_000, 2)
            inputs["hr_zone_45_weekly"] = round(z[1] / 3_600_000, 2)
            sources["hr_zone_13_weekly"] = "whoop:workout zone_1-3"
            sources["hr_zone_45_weekly"] = "whoop:workout zone_4-5"

        # Strength hours per week from resistance-training workout durations.
        like = " OR ".join(["LOWER(sport_name) LIKE ?"] * len(STRENGTH_SPORTS))
        s = wc.execute(
            f"SELECT COALESCE(SUM((julianday(end_time)-julianday(start_time))*24),0) "
            f"FROM workout_data WHERE start_time >= datetime('now', ?) AND ({like})",
            (f"-{WEEKLY_WINDOW} day", *[f"%{s}%" for s in STRENGTH_SPORTS]),
        ).fetchone()
        if s:
            inputs["strength_weekly"] = round(float(s[0]), 2)
            sources["strength_weekly"] = "whoop:strength workout duration"

        # HRmax over the long window for the Uth-Sørensen VO₂max estimate.
        hr = wc.execute(
            "SELECT MAX(max_heart_rate) FROM workout_data "
            "WHERE max_heart_rate IS NOT NULL AND start_time >= datetime('now', ?)",
            (f"-{LONG_WINDOW} day",),
        ).fetchone()
        hrmax = hr[0] if hr and hr[0] else None
        if not hrmax:
            bm = wc.execute(
                "SELECT max_heart_rate FROM body_measurements "
                "WHERE max_heart_rate IS NOT NULL ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            hrmax = bm[0] if bm else None
        if hrmax:
            inputs["_hrmax"] = float(hrmax)
    finally:
        wc.close()


def compute_physiological_age() -> dict:
    hconn = sqlite3.connect(f"file:{HEALTH_DB}?mode=ro", uri=True)
    try:
        inputs: dict[str, float] = {}
        sources: dict[str, str] = {}

        rhr = _avg(hconn, "resting_hr", LONG_WINDOW)
        if rhr is not None:
            inputs["resting_hr"] = round(rhr, 1)
            sources["resting_hr"] = f"daily_metrics.resting_hr ({LONG_WINDOW}d avg)"

        sh = _avg(hconn, "sleep_hours", RECENT_WINDOW)
        if sh is not None:
            inputs["sleep_hours"] = round(sh, 2)
            sources["sleep_hours"] = f"daily_metrics.sleep_hours ({RECENT_WINDOW}d avg)"

        st = _avg(hconn, "steps", RECENT_WINDOW)
        if st is not None:
            inputs["steps"] = round(st)
            sources["steps"] = f"daily_metrics.steps ({RECENT_WINDOW}d avg)"

        lmp = _lean_mass_pct(hconn)
        if lmp is not None:
            inputs["lean_mass_pct"] = lmp
            sources["lean_mass_pct"] = "body_composition (latest)"

        _whoop_inputs(inputs, sources)

        # VO₂max via Uth-Sørensen once we have both HRmax and RHR.
        hrmax = inputs.pop("_hrmax", None)
        if hrmax and rhr and rhr > 0:
            inputs["vo2max"] = round(15.0 * hrmax / rhr, 1)
            sources["vo2max"] = f"Uth-Sørensen 15·HRmax({hrmax:.0f})/RHR({rhr:.0f})"

        # Score every available marker.
        contributions = []
        total_delta = 0.0
        for key, marker in MARKERS.items():
            if key not in inputs:
                continue
            delta = round(score_marker(marker, inputs[key]), 2)
            total_delta += delta
            contributions.append({
                "key": key,
                "name": marker.name,
                "group": MARKER_GROUP.get(key, "Other"),
                "value": inputs[key],
                "delta_years": delta,
                "source": sources.get(key, ""),
            })
        contributions.sort(key=lambda c: c["delta_years"])
        total_delta = round(total_delta, 2)

        chrono = _chronological_age()
        whoop_age = round(chrono + total_delta, 1) if chrono is not None else None

        n_scored = len(contributions)
        return {
            "chronological_age": chrono,
            "physiological_age": whoop_age,
            "delta_years": total_delta,
            # Pace of Aging is a smoothed WHOOP trend we can't reproduce exactly;
            # we expose the best-effort delta/7 proxy the reverse-engineering used.
            "pace_of_aging": round(total_delta / 7.0, 2),
            "contributions": contributions,
            "markers_scored": n_scored,
            "markers_total": len(MARKERS),
            "data_completeness": round(n_scored / len(MARKERS), 2),
            "missing_markers": [k for k in MARKERS if k not in inputs],
            "needs_date_of_birth": chrono is None,
            "note": "Reverse-engineered WHOOP-Age-style estimate; directional, not clinical.",
        }
    finally:
        hconn.close()


if __name__ == "__main__":
    print(json.dumps(compute_physiological_age(), indent=2))
