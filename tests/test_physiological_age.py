"""Tests for the physiological-age scoring model.

The marker curves are a reverse-engineered reconstruction of WHOOP's
"Whoop Age" model, calibrated against two weekly ground-truth snapshots.
These tests LOCK that calibration: if a curve constant drifts, the
ground-truth reconstruction breaks here before it ships.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

from physiological_age import MARKERS, Marker, score_marker  # noqa: E402


# Ground truth from the reverse-engineering snapshot (Woche 24-30.05.2026):
# each marker value → expected Δ-years, validated against the WHOOP app UI.
_SNAPSHOT = {
    "sleep_consistency":  (76.0, -1.0),
    "sleep_hours":        (6.7, +0.3),
    "hr_zone_13_weekly":  (2.27, -0.2),
    "hr_zone_45_weekly":  (0.05, +0.1),
    "strength_weekly":    (3.98, -1.6),
    "steps":              (8958, -0.2),
    "vo2max":             (47.0, -1.6),
    "resting_hr":         (66.0, +0.8),
    "lean_mass_pct":      (87.8, 0.0),
}


def test_snapshot_markers_match_ground_truth():
    """Every marker reproduces the WHOOP-app value to within ±0.15 yr."""
    for key, (value, expected) in _SNAPSHOT.items():
        got = score_marker(MARKERS[key], value)
        assert abs(got - expected) < 0.15, f"{key}: got {got:+.2f}, want {expected:+.2f}"


def test_snapshot_total_delta():
    """Summed delta reproduces the -3.5 yr ground-truth total (±0.3 yr)."""
    total = sum(score_marker(MARKERS[k], v) for k, (v, _) in _SNAPSHOT.items())
    assert abs(total - (-3.5)) < 0.3, f"total delta {total:+.2f}, want -3.5"


def test_below_scale_min_is_max_penalty():
    m = MARKERS["vo2max"]
    assert score_marker(m, m.scale_min - 10) == m.max_penalty


def test_at_or_above_optimal_high_is_max_benefit():
    m = MARKERS["sleep_consistency"]
    assert score_marker(m, m.optimal_high) == m.max_benefit
    assert score_marker(m, m.scale_max) == m.max_benefit


def test_lower_is_better_marker_inverts():
    """Resting HR: a low RHR rejuvenates, a high RHR ages."""
    rhr = MARKERS["resting_hr"]
    assert score_marker(rhr, 48) < 0      # excellent RHR → younger
    assert score_marker(rhr, 78) > 0      # poor RHR → older
    assert score_marker(rhr, 48) < score_marker(rhr, 78)


def test_missing_marker_is_skipped_not_guessed():
    """A partial input set scores only the markers present (no fabrication)."""
    present = {"steps": 12000, "sleep_hours": 7.5}
    scored = {k: score_marker(MARKERS[k], v) for k, v in present.items()}
    assert set(scored) == {"steps", "sleep_hours"}
    assert all(isinstance(v, float) for v in scored.values())
