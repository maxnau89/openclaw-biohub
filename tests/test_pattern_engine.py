"""End-to-end tests for whoop_pattern_engine.py against fixture data.

Validates the public API shape (`generate_actionable_insights`) and that
the analytic helpers handle small / empty datasets without exploding.
"""
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from whoop_pattern_engine import WhoopPatternEngine


@pytest.fixture
def engine(openclaw_home):
    db = openclaw_home / "data" / "whoop_raw.db"
    return WhoopPatternEngine(str(db))


def test_dataset_loaded(engine):
    df = engine.get_comprehensive_dataset(days=90)
    assert df is not None
    assert len(df) == 90
    for col in ("recovery_score", "hrv", "rhr", "sleep_hours", "daily_strain"):
        assert col in df.columns


def test_insights_have_expected_shape(engine):
    insights = engine.generate_actionable_insights(days=90)
    assert "data_summary" in insights
    assert "correlations" in insights
    assert "anomalies" in insights
    assert "predictions" in insights
    assert "recommendations" in insights

    summary = insights["data_summary"]
    assert summary["days_analyzed"] == 90
    assert "from" in summary["date_range"]
    assert "to" in summary["date_range"]


def test_correlations_sorted_by_abs(engine):
    df = engine.get_comprehensive_dataset(days=90)
    corrs = engine.correlation_analysis(df)
    assert isinstance(corrs, list)
    assert corrs, "correlation analysis returned empty list"
    abs_vals = [abs(c["correlation"]) for c in corrs]
    assert abs_vals == sorted(abs_vals, reverse=True)


def test_correlation_strength_thresholds(engine):
    assert engine._correlation_strength(0.85) == "Very strong"
    assert engine._correlation_strength(0.55) == "Moderate"
    assert engine._correlation_strength(0.15) == "Weak"


def test_recommendations_have_priority_and_action(engine):
    insights = engine.generate_actionable_insights(days=90)
    recs = insights["recommendations"]
    assert isinstance(recs, list)
    for r in recs:
        assert r.get("priority") in ("low", "medium", "high")
        assert r.get("action")
        assert r.get("category")


def test_anomaly_detection_returns_list_with_enough_data(engine):
    df = engine.get_comprehensive_dataset(days=90)
    anomalies = engine.anomaly_detection(df)
    assert isinstance(anomalies, list)
    for a in anomalies:
        assert "metric" in a
        assert "z_score" in a
        assert "interpretation" in a


def test_too_small_dataset_returns_error_dict(engine):
    # synthetic 5-row df → correlation/anomaly both refuse
    df = pd.DataFrame({
        "recovery_score": [60, 62, 58, 65, 70],
        "hrv": [55, 56, 50, 58, 62],
        "rhr": [60, 61, 62, 59, 58],
        "sleep_hours": [7, 7.2, 6.8, 7.5, 8],
        "daily_strain": [10, 11, 9, 12, 8],
    })
    assert "error" in engine.correlation_analysis(df)
    assert "error" in engine.anomaly_detection(df)


def test_predictive_modeling_emits_recommendations(engine):
    df = engine.get_comprehensive_dataset(days=90)
    preds = engine.predictive_modeling(df)
    assert isinstance(preds, dict)
    # At least one sub-model should have fit successfully on 90 days
    assert any(
        isinstance(v, dict) and "recommendation" in v
        for v in preds.values()
    )
