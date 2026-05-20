#!/usr/bin/env python3
"""
blood_marker_analytics.py
Reads blood_panels + blood_markers from health.db and outputs JSON for the dashboard.
Returns: panels_count, markers_count, time_series, correlations, categories, flagged, panel_dates
"""
import json
import math
import sqlite3
from datetime import datetime, timedelta

from paths import HEALTH_DB

MC_DB = HEALTH_DB

# ─── Category map ────────────────────────────────────────────────
CATEGORIES: dict[str, list[str]] = {
    "Blood Count":    ["WBC", "RBC", "Hemoglobin", "Hematocrit", "MCV", "MCH", "MCHC",
                       "Platelets", "Neutrophils", "Lymphocytes", "Monocytes",
                       "Eosinophils", "Basophils"],
    "Metabolic":      ["Glucose", "HbA1c (DCCT)", "HbA1c (IFCC)", "Cholesterol",
                       "Triglycerides", "LDL", "HDL", "LDL-C", "HDL-C"],
    "Liver":          ["ALT (GPT)", "AST (GOT)", "GGT", "Bilirubin", "Albumin",
                       "AP", "Alkaline Phosphatase"],
    "Kidney":         ["Creatinine", "BUN", "Uric Acid", "eGFR", "Cystatin C"],
    "Hormones":       ["Cortisol", "Testosterone", "Free Testosterone", "Estradiol", "Prolactin",
                       "TSH", "T3", "T4", "Free T3", "Free T4", "DHEA", "DHEA-S",
                       "LH", "FSH", "IGF-1"],
    "Inflammation":   ["CRP (hs)", "CRP", "Ferritin", "Iron", "Transferrin",
                       "Fibrinogen", "IL-6", "TNF-alpha"],
    "Vitamins & Minerals": ["Vitamin D", "25-OH Vitamin D", "Vitamin B12", "Folate",
                             "Zinc", "Magnesium", "Calcium", "Potassium", "Sodium",
                             "Phosphate"],
    "Other":          ["PSA", "INR", "PTT"],
}

def categorize(marker_name: str) -> str:
    for cat, markers in CATEGORIES.items():
        if marker_name in markers:
            return cat
    # fuzzy: check if any category keyword appears
    ml = marker_name.lower()
    if any(k in ml for k in ["hba1c", "glucose", "cholesterol", "triglycerid"]):
        return "Metabolic"
    if any(k in ml for k in ["alt", "ast", "ggt", "bilirubin", "albumin"]):
        return "Liver"
    if any(k in ml for k in ["creatinin", "bun", "egfr", "uric"]):
        return "Kidney"
    if any(k in ml for k in ["cortisol", "testosteron", "estradiol", "prolactin", "tsh"]):
        return "Hormones"
    if any(k in ml for k in ["crp", "ferritin", "iron", "transferrin"]):
        return "Inflammation"
    if any(k in ml for k in ["vitamin", "zinc", "magnesium", "calcium", "potassium"]):
        return "Vitamins & Minerals"
    if any(k in ml for k in ["wbc", "rbc", "hemoglobin", "hematocrit", "platelet",
                               "neutrophil", "lymphocyte", "monocyte", "eosinophil",
                               "basophil", "mcv", "mch", "mchc"]):
        return "Blood Count"
    return "Other"

def calc_trend(points: list[dict]) -> dict | None:
    """Return trend from first to last non-null value."""
    valued = [p for p in points if p["value"] is not None]
    if len(valued) < 2:
        return None
    first_val = valued[0]["value"]
    last_val = valued[-1]["value"]
    if first_val == 0:
        return None
    change_pct = round((last_val - first_val) / abs(first_val) * 100, 1)
    direction = "up" if change_pct > 1 else ("down" if change_pct < -1 else "stable")
    return {"direction": direction, "change_pct": change_pct,
            "first": round(first_val, 3), "last": round(last_val, 3)}

def main():
    if not MC_DB.exists():
        print(json.dumps({"error": "mission-control.db not found", "panels_count": 0,
                          "markers_count": 0, "time_series": {}, "correlations": [],
                          "categories": {}, "flagged": [], "panel_dates": []}))
        return

    conn = sqlite3.connect(MC_DB)
    conn.row_factory = sqlite3.Row

    # ─── Load all panels ─────────────────────────────────────────
    panels = conn.execute(
        "SELECT id, panel_date, lab_name FROM blood_panels ORDER BY panel_date"
    ).fetchall()

    panel_dates = sorted(set(p["panel_date"] for p in panels))

    # ─── Load all markers joined with panel date ──────────────────
    rows = conn.execute("""
        SELECT bp.panel_date, bp.lab_name,
               bm.marker_name, bm.value, bm.unit,
               bm.ref_low, bm.ref_high, bm.status
        FROM blood_markers bm
        JOIN blood_panels bp ON bp.id = bm.panel_id
        ORDER BY bp.panel_date, bm.marker_name
    """).fetchall()

    # Build time series: marker → sorted list of data points
    ts: dict[str, list] = {}
    for r in rows:
        name = r["marker_name"]
        if name not in ts:
            ts[name] = []
        ts[name].append({
            "date": r["panel_date"],
            "value": r["value"],
            "unit": r["unit"],
            "ref_low": r["ref_low"],
            "ref_high": r["ref_high"],
            "status": r["status"] or "unknown",
            "lab": r["lab_name"],
        })

    # Deduplicate same-date entries (keep latest panel's value if duplicated)
    for name in ts:
        seen_dates: dict[str, dict] = {}
        for pt in ts[name]:
            seen_dates[pt["date"]] = pt  # last write wins for same date
        ts[name] = sorted(seen_dates.values(), key=lambda x: x["date"])

    # Build enriched time_series output
    time_series_out: dict[str, dict] = {}
    for name, points in ts.items():
        trend = calc_trend(points)
        # Use latest non-null ref_low/ref_high/unit
        latest_pt = next((p for p in reversed(points) if p["value"] is not None), None)
        unit = latest_pt["unit"] if latest_pt else None
        ref_low = latest_pt["ref_low"] if latest_pt else None
        ref_high = latest_pt["ref_high"] if latest_pt else None
        current_status = latest_pt["status"] if latest_pt else None

        time_series_out[name] = {
            "category": categorize(name),
            "points": points,
            "trend": trend,
            "unit": unit,
            "ref_low": ref_low,
            "ref_high": ref_high,
            "current_status": current_status,
        }

    # ─── Categories index ────────────────────────────────────────
    categories_out: dict[str, list[str]] = {}
    for name, data in time_series_out.items():
        cat = data["category"]
        categories_out.setdefault(cat, [])
        if name not in categories_out[cat]:
            categories_out[cat].append(name)
    for cat in categories_out:
        categories_out[cat].sort()

    # ─── Flagged markers (latest panel, abnormal or trending bad) ──
    flagged = []
    latest_panel_date = panel_dates[-1] if panel_dates else None
    if latest_panel_date:
        for name, data in time_series_out.items():
            latest = next((p for p in reversed(data["points"]) if p["date"] == latest_panel_date and p["value"] is not None), None)
            if latest and latest["status"] in ("high", "low", "critical"):
                flagged.append({
                    "marker": name,
                    "status": latest["status"],
                    "value": latest["value"],
                    "unit": latest["unit"],
                    "ref_low": latest["ref_low"],
                    "ref_high": latest["ref_high"],
                    "trend": data["trend"],
                    "category": data["category"],
                    "panel_date": latest_panel_date,
                })
        flagged.sort(key=lambda x: (0 if x["status"] == "critical" else 1 if x["status"] in ("high", "low") else 2, x["marker"]))

    # ─── Correlations with WHOOP metrics (partial, adjusted for sleep + strain) ─
    correlations = []
    try:
        whoop_rows = conn.execute(
            "SELECT date, recovery_score, hrv_ms, resting_hr, sleep_hours, "
            "sleep_performance, day_strain "
            "FROM daily_metrics WHERE recovery_score IS NOT NULL ORDER BY date"
        ).fetchall()

        if len(whoop_rows) >= 3:

            def _pearson(xs: list, ys: list) -> float | None:
                n = len(xs)
                if n < 3:
                    return None
                mx, my = sum(xs)/n, sum(ys)/n
                num    = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
                dx     = sum((x-mx)**2 for x in xs) ** 0.5
                dy     = sum((y-my)**2 for y in ys) ** 0.5
                return round(num/(dx*dy), 3) if dx and dy else None

            def _ols_residuals(y, z1, z2):
                """OLS residuals of y on z1+z2; returns list or None."""
                n = len(y)
                if n < 5:
                    return None
                my, mz1, mz2 = sum(y)/n, sum(z1)/n, sum(z2)/n
                yc  = [v-my  for v in y]
                z1c = [v-mz1 for v in z1]
                z2c = [v-mz2 for v in z2]
                a11 = sum(v**2      for v in z1c)
                a12 = sum(v1*v2     for v1, v2 in zip(z1c, z2c))
                a22 = sum(v**2      for v in z2c)
                b1  = sum(v1*vy     for v1, vy in zip(z1c, yc))
                b2  = sum(v2*vy     for v2, vy in zip(z2c, yc))
                det = a11*a22 - a12**2
                if abs(det) < 1e-12:
                    return None
                b1f = (a22*b1 - a12*b2) / det
                b2f = (a11*b2 - a12*b1) / det
                return [yc[i] - b1f*z1c[i] - b2f*z2c[i] for i in range(n)]

            def _ci95(r, n):
                if r is None or n < 4:
                    return None
                r = max(-0.9999, min(0.9999, r))
                z  = 0.5 * math.log((1+r)/(1-r))
                se = 1.0 / math.sqrt(n-3)
                return (round(math.tanh(z-1.96*se), 3), round(math.tanh(z+1.96*se), 3))

            def _significant(r, n):
                if r is None or n < 4:
                    return False
                r = max(-0.9999, min(0.9999, r))
                t  = r * math.sqrt(n-2) / math.sqrt(1-r**2)
                df = n-2
                tc = (12.7 if df<2 else 4.3 if df<5 else 2.78 if df<10
                      else 2.23 if df<20 else 2.09 if df<30 else 2.0)
                return abs(t) > tc

            # ── Pre-compute WHOOP residuals across all days ───────────────────
            # Only rows with both confounders (sleep_performance + day_strain) present
            full_rows = [
                (r["date"], float(r["recovery_score"]),
                 float(r["hrv_ms"])     if r["hrv_ms"]     is not None else None,
                 float(r["resting_hr"]) if r["resting_hr"] is not None else None,
                 float(r["sleep_performance"]), float(r["day_strain"]))
                for r in whoop_rows
                if r["sleep_performance"] is not None and r["day_strain"] is not None
            ]

            # date → adjusted residuals for each metric
            whoop_residuals: dict[str, dict] = {}
            adjusted = False

            if len(full_rows) >= 10:
                dates_u   = [x[0] for x in full_rows]
                rec_v     = [x[1] for x in full_rows]
                hrv_v     = [x[2] if x[2] is not None else 0.0 for x in full_rows]
                rhr_v     = [x[3] if x[3] is not None else 0.0 for x in full_rows]
                sleep_v   = [x[4] for x in full_rows]
                strain_v  = [x[5] for x in full_rows]

                rec_res = _ols_residuals(rec_v, sleep_v, strain_v)
                hrv_res = _ols_residuals(hrv_v, sleep_v, strain_v)
                rhr_res = _ols_residuals(rhr_v, sleep_v, strain_v)

                if rec_res:
                    for i, d in enumerate(dates_u):
                        whoop_residuals[d] = {"recovery_resid": rec_res[i]}
                    if hrv_res:
                        for i, d in enumerate(dates_u):
                            whoop_residuals[d]["hrv_resid"] = hrv_res[i]
                    if rhr_res:
                        for i, d in enumerate(dates_u):
                            whoop_residuals[d]["resting_hr_resid"] = rhr_res[i]
                    adjusted = True

            def _avg_resid_around(target_date: str, key: str, window: int = 7) -> float | None:
                dt   = datetime.strptime(target_date, "%Y-%m-%d")
                vals = [v[key] for d, v in whoop_residuals.items()
                        if key in v and abs((datetime.strptime(d, "%Y-%m-%d")-dt).days) <= window]
                return sum(vals)/len(vals) if vals else None

            def _avg_raw_around(target_date: str, metric: str, window: int = 7) -> float | None:
                dt   = datetime.strptime(target_date, "%Y-%m-%d")
                vals = [r[metric] for r in whoop_rows
                        if r[metric] is not None
                        and abs((datetime.strptime(r["date"], "%Y-%m-%d")-dt).days) <= window]
                return sum(vals)/len(vals) if vals else None

            # Metrics to test: recovery/HRV/resting-HR are adjusted when possible;
            # sleep_hours is a confounder itself, so left raw
            whoop_metrics = [
                ("recovery_resid"    if adjusted else "recovery_score",
                 "Recovery (adj.)"   if adjusted else "Recovery Score",
                 True                if adjusted else False),
                ("hrv_resid"         if adjusted else "hrv_ms",
                 "HRV (adj.)"        if adjusted else "HRV",
                 True                if adjusted else False),
                ("resting_hr_resid"  if adjusted else "resting_hr",
                 "Resting HR (adj.)" if adjusted else "Resting HR",
                 True                if adjusted else False),
                ("sleep_hours", "Sleep Hours", False),
            ]

            for marker_name, data in time_series_out.items():
                mvals = [(p["value"], p["date"]) for p in data["points"] if p["value"] is not None]
                if len(mvals) < 3:
                    continue
                for wm_key, wm_label, is_adj in whoop_metrics:
                    xs, ys = [], []
                    for mv, md in mvals:
                        wa = (_avg_resid_around(md, wm_key) if is_adj
                              else _avg_raw_around(md, wm_key))
                        if wa is not None:
                            xs.append(mv)
                            ys.append(wa)
                    r = _pearson(xs, ys)
                    if r is not None and abs(r) >= 0.5:
                        ci = _ci95(r, len(xs))
                        correlations.append({
                            "marker":         marker_name,
                            "whoop_metric":   wm_key,
                            "whoop_label":    wm_label,
                            "correlation":    r,
                            "strength":       "strong" if abs(r) >= 0.7 else "moderate",
                            "direction":      "positive" if r > 0 else "negative",
                            "data_points":    len(xs),
                            "ci_low":         ci[0] if ci else None,
                            "ci_high":        ci[1] if ci else None,
                            "significant":    _significant(r, len(xs)),
                            "adjusted":       is_adj,
                            "interpretation": (f"Higher {marker_name} → higher {wm_label}"
                                               if r > 0 else
                                               f"Higher {marker_name} → lower {wm_label}"),
                        })

            correlations.sort(key=lambda x: -abs(x["correlation"]))
            correlations = correlations[:15]  # top 15

    except Exception:
        pass  # correlations are best-effort

    conn.close()

    result = {
        "panels_count": len(panel_dates),
        "markers_count": len(ts),
        "time_series": time_series_out,
        "correlations": correlations,
        "categories": categories_out,
        "flagged": flagged,
        "panel_dates": panel_dates,
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
