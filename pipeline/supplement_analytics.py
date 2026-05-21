#!/usr/bin/env python3
"""
Supplement ↔ Recovery Correlation Analytics
Reads supplement_log + daily_metrics from health.db and computes
partial correlations between supplement intake and recovery/HRV,
controlling for sleep performance and day strain (same approach WHOOP uses
in their multivariate journal-based analysis).
"""

import json
import sqlite3
import math
from datetime import timedelta, datetime

from paths import HEALTH_DB

DB_PATH = str(HEALTH_DB)


# ─── Statistics helpers ───────────────────────────────────────────────────────

def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 3)


def ols_residuals(y: list[float], z1: list[float], z2: list[float]) -> list[float] | None:
    """
    Return residuals of y after OLS regression on z1 and z2 (with intercept).
    Uses centered normal equations — exact, no external deps.
    Returns None if the confounder matrix is (near-)singular or n < 5.
    """
    n = len(y)
    if n < 5:
        return None
    my  = sum(y)  / n
    mz1 = sum(z1) / n
    mz2 = sum(z2) / n
    yc  = [v - my  for v in y]
    z1c = [v - mz1 for v in z1]
    z2c = [v - mz2 for v in z2]
    # 2×2 normal equations
    a11 = sum(v**2      for v in z1c)
    a12 = sum(v1*v2     for v1, v2 in zip(z1c, z2c))
    a22 = sum(v**2      for v in z2c)
    b1  = sum(v1*vy     for v1, vy in zip(z1c, yc))
    b2  = sum(v2*vy     for v2, vy in zip(z2c, yc))
    det = a11 * a22 - a12 ** 2
    if abs(det) < 1e-12:
        return None  # collinear confounders — fall back to bivariate
    beta1 = (a22 * b1 - a12 * b2) / det
    beta2 = (a11 * b2 - a12 * b1) / det
    return [yc[i] - beta1 * z1c[i] - beta2 * z2c[i] for i in range(n)]


def ci95(r: float | None, n: int) -> tuple[float, float] | None:
    """Fisher z-transform 95% CI for Pearson r."""
    if r is None or n < 4:
        return None
    r = max(-0.9999, min(0.9999, r))
    z  = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(n - 3)
    return (round(math.tanh(z - 1.96 * se), 3),
            round(math.tanh(z + 1.96 * se), 3))


def is_significant(r: float | None, n: int) -> bool:
    """Two-tailed p < 0.05 via t-statistic with conservative critical values."""
    if r is None or n < 4:
        return False
    r = max(-0.9999, min(0.9999, r))
    t  = r * math.sqrt(n - 2) / math.sqrt(1 - r ** 2)
    df = n - 2
    t_crit = (12.7 if df < 2 else
              4.3  if df < 5  else
              2.78 if df < 10 else
              2.23 if df < 20 else
              2.09 if df < 30 else 2.0)
    return abs(t) > t_crit


def strength(r: float | None) -> str:
    if r is None:
        return 'insufficient'
    a = abs(r)
    if a >= 0.6:
        return 'strong'
    if a >= 0.35:
        return 'moderate'
    return 'weak'


# ─── Data loading ─────────────────────────────────────────────────────────────

def load_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    tables = {row['name'] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'supplement_log' not in tables or 'supplements' not in tables or 'daily_metrics' not in tables:
        conn.close()
        return {}, {}

    # Load WHOOP daily — include confounders (sleep_performance, day_strain)
    whoop = {}
    for row in cur.execute(
        'SELECT date, recovery_score, hrv_ms, sleep_performance, day_strain '
        'FROM daily_metrics WHERE recovery_score IS NOT NULL'
    ):
        whoop[row['date']] = {
            'recovery':    row['recovery_score'],
            'hrv':         row['hrv_ms'],
            'sleep_perf':  row['sleep_performance'],   # may be None
            'strain':      row['day_strain'],           # may be None
        }

    # Load all supplements
    supplements = {}
    for row in cur.execute('SELECT id, name, default_lag_hours FROM supplements'):
        supplements[row['id']] = {
            'name':      row['name'],
            'lag_hours': row['default_lag_hours'] or 24,
        }

    # Load supplement logs — expand period entries to daily intake dates
    intake_dates: dict[int, set[str]] = {}
    for row in cur.execute(
        'SELECT supplement_id, taken_at, intake_start, intake_end, is_period FROM supplement_log'
    ):
        sid = row['supplement_id']
        if sid not in intake_dates:
            intake_dates[sid] = set()

        if row['is_period'] == 1 and row['intake_start'] and row['intake_end']:
            try:
                start   = datetime.strptime(row['intake_start'], '%Y-%m-%d').date()
                end     = datetime.strptime(row['intake_end'],   '%Y-%m-%d').date()
                current = start
                while current <= end:
                    intake_dates[sid].add(current.strftime('%Y-%m-%d'))
                    current += timedelta(days=1)
            except ValueError:
                pass
        else:
            if row['taken_at']:
                intake_dates[sid].add(row['taken_at'][:10])

    conn.close()
    return whoop, intake_dates, supplements


# ─── Main analysis ────────────────────────────────────────────────────────────

def analyze():
    try:
        result = load_data()
    except Exception as e:
        print(json.dumps({'supplements': [], 'error': str(e)}))
        return

    if len(result) == 2:
        print(json.dumps({'supplements': []}))
        return

    whoop, intake_dates, supplements = result

    if not whoop:
        print(json.dumps({'supplements': []}))
        return

    all_dates  = sorted(whoop.keys())
    correlations = []

    for sup_id, info in supplements.items():
        if sup_id not in intake_dates:
            continue

        dates_taken = intake_dates[sup_id]
        lag_days    = max(0, info['lag_hours'] // 24)

        # ── Collect aligned series ────────────────────────────────
        # "full" rows: all WHOOP days (for bivariate fallback)
        # "partial" rows: days where both confounders are non-NULL
        full_flags,    full_recovery   = [], []
        part_flags,    part_recovery   = [], []
        part_sleep,    part_strain     = [], []
        recovery_with, recovery_without = [], []

        for d in all_dates:
            w          = whoop[d]
            check_date = (datetime.strptime(d, '%Y-%m-%d') - timedelta(days=lag_days)).strftime('%Y-%m-%d')
            was_taken  = check_date in dates_taken
            flag       = 1.0 if was_taken else 0.0

            full_flags.append(flag)
            full_recovery.append(float(w['recovery']))

            if w['sleep_perf'] is not None and w['strain'] is not None:
                part_flags.append(flag)
                part_recovery.append(float(w['recovery']))
                part_sleep.append(float(w['sleep_perf']))
                part_strain.append(float(w['strain']))

            if was_taken:
                recovery_with.append(w['recovery'])
            else:
                recovery_without.append(w['recovery'])

        total_with = len(recovery_with)
        if total_with < 7:
            continue  # Not enough intake days

        # ── Compute correlation: partial if possible, else bivariate ──
        adjusted = False
        if len(part_flags) >= 10:
            res_flags    = ols_residuals(part_flags,    part_sleep, part_strain)
            res_recovery = ols_residuals(part_recovery, part_sleep, part_strain)
            if res_flags is not None and res_recovery is not None:
                r_recovery = pearson(res_flags, res_recovery)
                n_used     = len(part_flags)
                adjusted   = True

        if not adjusted:
            r_recovery = pearson(full_flags, full_recovery)
            n_used     = len(full_flags)

        if r_recovery is None:
            continue

        # ── HRV correlation (partial if possible) ─────────────────
        full_hrv_flags, full_hrv_vals = [], []
        part_hrv_flags, part_hrv_vals = [], []
        part_hrv_sleep, part_hrv_str  = [], []

        for d in all_dates:
            w          = whoop[d]
            if w['hrv'] is None:
                continue
            check_date = (datetime.strptime(d, '%Y-%m-%d') - timedelta(days=lag_days)).strftime('%Y-%m-%d')
            was_taken  = check_date in dates_taken
            flag       = 1.0 if was_taken else 0.0

            full_hrv_flags.append(flag)
            full_hrv_vals.append(float(w['hrv']))

            if w['sleep_perf'] is not None and w['strain'] is not None:
                part_hrv_flags.append(flag)
                part_hrv_vals.append(float(w['hrv']))
                part_hrv_sleep.append(float(w['sleep_perf']))
                part_hrv_str.append(float(w['strain']))

        r_hrv = None
        if len(part_hrv_flags) >= 10:
            res_hrv_flags = ols_residuals(part_hrv_flags, part_hrv_sleep, part_hrv_str)
            res_hrv_vals  = ols_residuals(part_hrv_vals,  part_hrv_sleep, part_hrv_str)
            if res_hrv_flags is not None and res_hrv_vals is not None:
                r_hrv = pearson(res_hrv_flags, res_hrv_vals)
        if r_hrv is None and len(full_hrv_flags) >= 5:
            r_hrv = pearson(full_hrv_flags, full_hrv_vals)

        # ── Metadata ──────────────────────────────────────────────
        avg_with    = round(sum(recovery_with)    / len(recovery_with),    1) if recovery_with    else 0
        avg_without = round(sum(recovery_without) / len(recovery_without), 1) if recovery_without else 0
        ci          = ci95(r_recovery, n_used)

        correlations.append({
            'name':                  info['name'],
            'lag_hours':             info['lag_hours'],
            'correlation_recovery':  r_recovery,
            'correlation_hrv':       r_hrv,
            'strength':              strength(r_recovery),
            'direction':             'positive' if (r_recovery or 0) >= 0 else 'negative',
            'avg_recovery_with':     avg_with,
            'avg_recovery_without':  avg_without,
            'recovery_delta':        round(avg_with - avg_without, 1),
            'data_points':           total_with,
            'total_days':            len(full_flags),
            'ci_low':                ci[0] if ci else None,
            'ci_high':               ci[1] if ci else None,
            'significant':           is_significant(r_recovery, n_used),
            'adjusted':              adjusted,   # True = partial correlation (sleep+strain controlled)
        })

    correlations.sort(key=lambda x: abs(x['correlation_recovery']), reverse=True)
    print(json.dumps({'supplements': correlations}))


if __name__ == '__main__':
    analyze()
