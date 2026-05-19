#!/usr/bin/env python3
"""WHOOP Pattern Recognition Engine.

Reconstructed from bytecode (the original `.py` source was lost; only a
Python 3.12 `.pyc` survived). Public API and method signatures preserved.

Reads the `whoop_raw.db` schema produced by `whoop_sync.py` and produces
JSON-serializable insights via `generate_actionable_insights(days=N)`.

Implements:
  - Pairwise correlation analysis (sleep ↔ HRV ↔ performance ↔ strain)
  - Anomaly detection (IsolationForest + per-metric z-scores)
  - Lightweight predictive modeling (linear regression on sleep → recovery)
  - Consolidated, prioritized recommendations
"""
from __future__ import annotations

import sqlite3
import warnings
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")


# Pairs that get a human-readable interpretation when their correlation
# is meaningful. Order matters: (cause, effect).
_INTERPRETATIONS: dict[tuple[str, str], str] = {
    ("hrv", "recovery_score"):                          "Higher HRV leads to better recovery",
    ("sleep_performance_percentage", "recovery_score"): "Better sleep improves recovery",
    ("rhr", "hrv"):                                     "Lower resting HR correlates with higher HRV",
    ("sleep_hours", "recovery_score"):                  "More sleep leads to better recovery",
    ("daily_strain", "recovery_score"):                 "Higher strain may impair recovery",
    ("daily_strain", "sleep_hours"):                    "Intense workouts can affect sleep",
}

# Per-metric population means used to classify anomalies as "low" or "high".
_METRIC_MEANS: dict[str, float] = {
    "recovery_score": 60,
    "hrv": 70,
    "rhr": 60,
    "sleep_performance_percentage": 70,
}

_ANOMALY_INTERPRETATIONS: dict[str, dict[str, str]] = {
    "recovery_score": {
        "low":  "Unusually low recovery — possible overtraining or stress",
        "high": "Exceptionally high recovery — optimal state",
    },
    "hrv": {
        "low":  "Severely reduced HRV — signs of stress or overtraining",
        "high": "Very high HRV — excellent autonomic balance",
    },
    "rhr": {
        "low":  "Unusually low resting heart rate — possible overtraining",
        "high": "Elevated resting HR — stress, illness, or overtraining",
    },
    "sleep_performance_percentage": {
        "low":  "Very poor sleep quality — review sleep hygiene",
        "high": "Exceptionally good sleep",
    },
    "spo2_percentage": {
        "low":  "Low blood oxygen — monitor respiratory health",
        "high": "SpO₂ reading variance — sensor may need repositioning",
    },
}

# Columns considered when running pairwise correlations.
_CORRELATION_COLS = [
    "recovery_score", "hrv", "rhr", "spo2_percentage",
    "sleep_performance_percentage", "sleep_efficiency_percentage",
    "sleep_hours", "rem_hours", "deep_sleep_hours",
    "daily_strain", "avg_hr", "max_hr", "kilojoule", "respiratory_rate",
]


class WhoopPatternEngine:
    def __init__(self, db_file: str):
        self.db_file = db_file
        self.conn = sqlite3.connect(db_file)
        self.conn.row_factory = sqlite3.Row

    # ─── Data loading ────────────────────────────────────────────────────

    def get_comprehensive_dataset(self, days: int = 90) -> Optional[pd.DataFrame]:
        """Join recovery + sleep + cycles into one daily row per `created_at`."""
        try:
            df = pd.read_sql_query(
                """
                WITH daily_data AS (
                    SELECT
                        DATE(r.created_at) as date,
                        -- Recovery
                        r.recovery_score,
                        r.resting_heart_rate as rhr,
                        r.hrv_rmssd_milli as hrv,
                        r.spo2_percentage,
                        r.skin_temp_celsius,

                        -- Sleep (joined on cycle_id, exclude naps)
                        s.sleep_performance_percentage,
                        s.sleep_efficiency_percentage,
                        s.total_in_bed_time_milli / 3600000.0 as sleep_hours,
                        s.total_rem_sleep_time_milli / 3600000.0 as rem_hours,
                        s.total_slow_wave_sleep_time_milli / 3600000.0 as deep_sleep_hours,
                        s.disturbance_count,
                        s.respiratory_rate,

                        -- Strain (from daily cycle)
                        c.strain as daily_strain,
                        c.average_heart_rate as avg_hr,
                        c.max_heart_rate as max_hr,
                        c.kilojoule
                    FROM recovery_data r
                    LEFT JOIN sleep_data s
                        ON s.cycle_id = r.cycle_id AND (s.nap = 0 OR s.nap IS NULL)
                    LEFT JOIN cycles_data c ON c.id = r.cycle_id
                    WHERE r.score_state = 'SCORED'
                    ORDER BY date DESC
                    LIMIT ?
                )
                SELECT * FROM daily_data ORDER BY date ASC
                """,
                self.conn,
                params=[days],
            )
            if len(df) == 0:
                return df
            df["date"] = pd.to_datetime(df["date"])
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            df[numeric_cols] = df[numeric_cols].ffill().bfill()
            return df
        except Exception as e:
            print(f"Error creating comprehensive dataset: {e}")
            return None

    # ─── Correlation analysis ────────────────────────────────────────────

    def correlation_analysis(self, df: pd.DataFrame) -> Any:
        """Pairwise Pearson correlations across key WHOOP metrics.

        Returns a list of dicts sorted by |correlation| desc, or an
        error dict if the dataset is too small.
        """
        if len(df) < 7:
            return {"error": "Insufficient data for correlation analysis"}

        available = [c for c in _CORRELATION_COLS if c in df.columns]
        results: list[dict[str, Any]] = []
        seen: set[frozenset[str]] = set()

        for m1 in available:
            for m2 in available:
                if m1 == m2:
                    continue
                key = frozenset((m1, m2))
                if key in seen:
                    continue
                seen.add(key)

                xs = df[m1].dropna()
                ys = df[m2].dropna()
                common = xs.index.intersection(ys.index)
                if len(common) < 7:
                    continue

                try:
                    r, p = pearsonr(df.loc[common, m1], df.loc[common, m2])
                except Exception:
                    continue
                if np.isnan(r):
                    continue

                results.append({
                    "metric1": m1,
                    "metric2": m2,
                    "correlation": round(float(r), 3),
                    "p_value": round(float(p), 4),
                    "strength": self._correlation_strength(abs(r)),
                    "interpretation": self._interpret_correlation(m1, m2, r),
                    "n": int(len(common)),
                })

        results.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        return results

    def _correlation_strength(self, abs_corr: float) -> str:
        if abs_corr > 0.7:
            return "Very strong"
        if abs_corr > 0.4:
            return "Moderate"
        return "Weak"

    def _interpret_correlation(self, metric1: str, metric2: str, corr_value: float) -> str:
        interpretation = _INTERPRETATIONS.get((metric1, metric2)) \
            or _INTERPRETATIONS.get((metric2, metric1))
        if interpretation:
            return interpretation
        direction = "positive" if corr_value > 0 else "negative"
        return f"Relationship between {metric1} and {metric2} ({direction} correlation)"

    # ─── Anomaly detection ───────────────────────────────────────────────

    def anomaly_detection(self, df: pd.DataFrame) -> Any:
        """IsolationForest over the last `df` window + per-row z-score callouts.

        Returns a list of recent (last 14d) anomaly events, each with the
        metric, value, z-score, and a plain-language interpretation.
        """
        if len(df) < 14:
            return {"error": "Insufficient data for anomaly detection"}

        feature_cols = [c for c in _METRIC_MEANS.keys() if c in df.columns]
        if not feature_cols:
            return []

        features = df[feature_cols].dropna()
        if len(features) < 14:
            return []

        # IsolationForest flag (overall multivariate outlier)
        scaler = StandardScaler()
        scaled = scaler.fit_transform(features)
        iso = IsolationForest(contamination=0.1, random_state=42)
        iso_flags = iso.fit_predict(scaled)  # -1 = outlier

        # Per-metric z-scores, used to label which metric drove the anomaly
        means = features.mean()
        stds = features.std(ddof=0).replace(0, np.nan)
        z = (features - means) / stds

        anomalies: list[dict[str, Any]] = []
        recent_idx = features.tail(14).index
        for i, idx in enumerate(features.index):
            if idx not in recent_idx:
                continue
            row_z = z.loc[idx]
            # Pick the metric with the largest |z| that crosses 2σ
            top_metric = row_z.abs().idxmax()
            top_z = float(row_z[top_metric])
            if abs(top_z) < 2 and iso_flags[i] != -1:
                continue
            value = float(features.loc[idx, top_metric])
            anomalies.append({
                "date": str(df.loc[idx, "date"]) if "date" in df.columns else str(idx),
                "metric": top_metric,
                "value": round(value, 2),
                "z_score": round(top_z, 2),
                "interpretation": self._interpret_anomaly(top_metric, value, top_z),
            })
        return anomalies

    def _interpret_anomaly(self, metric: str, value: float, z_score: float) -> str:
        mean = _METRIC_MEANS.get(metric, 50)
        direction = "low" if value < mean else "high"
        metric_interp = _ANOMALY_INTERPRETATIONS.get(metric, {})
        return metric_interp.get(direction, f"{direction.title()} {metric}")

    # ─── Predictive modeling ─────────────────────────────────────────────

    def predictive_modeling(self, df: pd.DataFrame) -> Any:
        """Fit lightweight models and emit sleep / strain / timing guidance.

        Returns a dict with one entry per sub-model:
          - sleep_to_recovery: LinearRegression coefficient (β)
          - strain_to_recovery: Pearson r over the window
          - optimal_recovery_threshold: 75th percentile of recovery_score
        Each sub-model also carries its own human-readable recommendation.
        """
        out: dict[str, Any] = {}
        if df is None or len(df) < 14:
            return {"error": "Insufficient data for predictive modeling"}

        # Sleep → recovery
        try:
            sub = df[["sleep_hours", "recovery_score"]].dropna()
            if len(sub) >= 14:
                model = LinearRegression()
                model.fit(sub[["sleep_hours"]], sub["recovery_score"])
                out["sleep_to_recovery"] = {
                    "beta": round(float(model.coef_[0]), 3),
                    "intercept": round(float(model.intercept_), 2),
                    "n": int(len(sub)),
                    "recommendation": self._generate_sleep_recommendation(model, df),
                }
        except Exception as e:
            out["sleep_to_recovery"] = {"error": str(e)}

        # Strain → recovery
        try:
            sub = df[["daily_strain", "recovery_score"]].dropna()
            if len(sub) >= 14:
                r, _ = pearsonr(sub["daily_strain"], sub["recovery_score"])
                out["strain_to_recovery"] = {
                    "correlation": round(float(r), 3),
                    "n": int(len(sub)),
                    "recommendation": self._generate_strain_recommendation(r, df),
                }
        except Exception as e:
            out["strain_to_recovery"] = {"error": str(e)}

        # Recovery threshold for training timing
        if "recovery_score" in df.columns and df["recovery_score"].notna().any():
            threshold = float(df["recovery_score"].quantile(0.75))
            out["optimal_recovery_threshold"] = {
                "value": round(threshold, 1),
                "recommendation": self._generate_timing_recommendation(threshold, df),
            }

        return out

    def _generate_sleep_recommendation(self, model: LinearRegression, df: pd.DataFrame) -> str:
        recent_sleep = df["sleep_hours"].tail(7).mean()
        beta = float(model.coef_[0])
        if pd.isna(recent_sleep):
            return "Insufficient recent sleep data to make a recommendation."
        # +1h sleep predicts +β recovery score points
        if recent_sleep < 7 and beta > 0:
            extra = max(0.5, round(7 - recent_sleep, 1))
            gain = round(beta * extra, 1)
            return (
                f"Recent average is {recent_sleep:.1f}h. Adding {extra}h "
                f"predicts ~+{gain} recovery points based on your data."
            )
        if recent_sleep >= 7.5:
            return f"Sleep duration ({recent_sleep:.1f}h) is already well-supported."
        return "Sleep duration is in a healthy range; focus on consistency."

    def _generate_strain_recommendation(self, correlation: float, df: pd.DataFrame) -> str:
        recent_hrv = df["hrv"].tail(3).mean()
        hrv_mean = df["hrv"].mean()
        if pd.isna(recent_hrv) or pd.isna(hrv_mean) or hrv_mean == 0:
            return "Insufficient HRV history to tune training load."
        if recent_hrv < hrv_mean * 0.85:
            return "HRV low — reduce training intensity for better recovery"
        if recent_hrv > hrv_mean * 1.15:
            return "HRV high — can handle higher training load"
        if abs(correlation) > 0.3:
            return "HRV within normal range — moderate training recommended"
        return "HRV–strain relationship is not yet clear — collect more data"

    def _generate_timing_recommendation(self, optimal_recovery: float, df: pd.DataFrame) -> str:
        current_recovery = float(df["recovery_score"].tail(1).mean())
        if pd.isna(current_recovery):
            return "No recent recovery reading."
        cr = round(current_recovery)
        if current_recovery >= optimal_recovery:
            return f"Recovery at {cr}% — ideal time for training!"
        if current_recovery >= optimal_recovery * 0.8:
            return f"Recovery at {cr}% — light training possible"
        return f"{cr}% — recovery day recommended (target: ≥{round(optimal_recovery)}%)"

    # ─── Top-level entry point ───────────────────────────────────────────

    def generate_actionable_insights(self, days: int = 90) -> dict[str, Any]:
        df = self.get_comprehensive_dataset(days)
        if df is None or len(df) == 0:
            return {"error": "No data available for analysis"}

        insights: dict[str, Any] = {
            "data_summary": {
                "days_analyzed": int(len(df)),
                "date_range": {
                    "from": df["date"].min().strftime("%Y-%m-%d"),
                    "to": df["date"].max().strftime("%Y-%m-%d"),
                },
                "metrics_available": list(df.columns),
            },
            "correlations": self.correlation_analysis(df),
            "anomalies": self.anomaly_detection(df),
            "predictions": self.predictive_modeling(df),
            "recommendations": [],
        }
        insights["recommendations"] = self._generate_consolidated_recommendations(insights, df)
        return insights

    def _generate_consolidated_recommendations(
        self, insights: dict[str, Any], df: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        """Distill the analytic outputs into a short, prioritized action list."""
        recs: list[dict[str, Any]] = []
        recent = df.tail(7)
        avg_recovery = recent["recovery_score"].mean() if "recovery_score" in recent.columns else None
        avg_sleep = recent["sleep_performance_percentage"].mean() \
            if "sleep_performance_percentage" in recent.columns else None
        avg_hrv = recent["hrv"].mean() if "hrv" in recent.columns else None
        full_hrv = df["hrv"].mean() if "hrv" in df.columns else None

        # Recent recovery trending poor
        if avg_recovery is not None and not pd.isna(avg_recovery) and avg_recovery < 40:
            recs.append({
                "priority": "high",
                "category": "recovery",
                "action": f"7-day recovery averaging {round(avg_recovery)}% — schedule a rest day",
            })

        # Sleep performance lagging
        if avg_sleep is not None and not pd.isna(avg_sleep) and avg_sleep < 70:
            recs.append({
                "priority": "high",
                "category": "sleep",
                "action": f"Sleep performance averaging {round(avg_sleep)}% — review sleep hygiene and bedtime consistency",
            })

        # HRV regressed vs baseline
        if (
            avg_hrv is not None and full_hrv is not None
            and not pd.isna(avg_hrv) and not pd.isna(full_hrv)
            and full_hrv > 0 and avg_hrv < full_hrv * 0.85
        ):
            recs.append({
                "priority": "medium",
                "category": "hrv",
                "action": f"HRV ({avg_hrv:.0f}ms) is ~{round((1 - avg_hrv/full_hrv) * 100)}% below baseline — reduce intensity for 2–3 days",
            })

        # Surface the strongest correlation as an FYI
        corrs = insights.get("correlations")
        if isinstance(corrs, list) and corrs:
            top = corrs[0]
            if abs(top.get("correlation", 0)) >= 0.4:
                recs.append({
                    "priority": "low",
                    "category": "insight",
                    "action": f"{top['interpretation']} (r={top['correlation']}, {top['strength']})",
                })

        # Surface a recent multivariate anomaly
        anomalies = insights.get("anomalies")
        if isinstance(anomalies, list) and anomalies:
            latest = anomalies[-1]
            recs.append({
                "priority": "medium",
                "category": "anomaly",
                "action": f"{latest['date']}: {latest['interpretation']} (z={latest['z_score']})",
            })

        # Promote the timing rec if recovery is currently high
        preds = insights.get("predictions") or {}
        timing = preds.get("optimal_recovery_threshold") if isinstance(preds, dict) else None
        if isinstance(timing, dict) and timing.get("recommendation"):
            recs.append({
                "priority": "low",
                "category": "training",
                "action": timing["recommendation"],
            })

        return recs


def main():
    import os
    import sys

    db = os.environ.get("WHOOP_DB_PATH")
    if not db:
        # Fall back to the standard layout
        from paths import WHOOP_DB
        db = str(WHOOP_DB)

    print("WHOOP Pattern Recognition Engine")
    print("=" * 50)
    try:
        engine = WhoopPatternEngine(db)
        insights = engine.generate_actionable_insights(days=90)
        summary = insights.get("data_summary", {})
        print(f"Analyzed {summary.get('days_analyzed', 0)} days of data")
        print(f"Range: {summary.get('date_range', {})}")
        correlations = insights.get("correlations", [])
        if isinstance(correlations, list) and correlations:
            print("\nTop correlations:")
            for c in correlations[:5]:
                print(f"  - {c.get('interpretation')} (r={c.get('correlation')})")
        anomalies = insights.get("anomalies", [])
        if isinstance(anomalies, list) and anomalies:
            print("\nRecent anomalies:")
            for a in anomalies[:5]:
                print(f"  - {a.get('date')}: {a.get('interpretation')}")
        recs = insights.get("recommendations", [])
        if recs:
            print("\nActionable recommendations:")
            for r in recs:
                print(f"  - [{r.get('priority')}] {r.get('action')}")
        print("\nDone.")
        return 0
    except Exception as e:
        print(f"Pattern analysis failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
