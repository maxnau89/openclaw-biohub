"""Tests that fixtures/seed.py produces the expected DB shape."""
import sqlite3


def test_seed_creates_both_dbs(openclaw_home):
    assert (openclaw_home / "data" / "health.db").exists()
    assert (openclaw_home / "data" / "whoop_raw.db").exists()


def test_seed_row_counts_are_reasonable(openclaw_home):
    health_db = openclaw_home / "data" / "health.db"
    whoop_db = openclaw_home / "data" / "whoop_raw.db"

    with sqlite3.connect(health_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM whoop_daily").fetchone()[0] == 90
        assert conn.execute("SELECT COUNT(*) FROM blood_panels").fetchone()[0] == 2
        n_markers = conn.execute("SELECT COUNT(*) FROM blood_markers").fetchone()[0]
        assert 20 < n_markers < 40
        assert conn.execute("SELECT COUNT(*) FROM supplements").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM nutrition_logs").fetchone()[0] == 30

    with sqlite3.connect(whoop_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM recovery_data").fetchone()[0] == 90
        assert conn.execute("SELECT COUNT(*) FROM sleep_data").fetchone()[0] == 90
        assert conn.execute("SELECT COUNT(*) FROM cycles_data").fetchone()[0] == 90
        # workouts: ~50% of days; allow generous slack
        n_workouts = conn.execute("SELECT COUNT(*) FROM workout_data").fetchone()[0]
        assert 25 < n_workouts < 65


def test_recovery_in_plausible_range(openclaw_home):
    """The calibrated formula should keep recovery centered around 60-75%."""
    health_db = openclaw_home / "data" / "health.db"
    with sqlite3.connect(health_db) as conn:
        avg = conn.execute("SELECT AVG(recovery_score) FROM whoop_daily").fetchone()[0]
    assert 50 < avg < 85, f"avg recovery {avg} outside plausible band"


def test_blood_markers_have_reference_ranges(openclaw_home):
    """Every marker should carry ref_low/ref_high and a status."""
    health_db = openclaw_home / "data" / "health.db"
    with sqlite3.connect(health_db) as conn:
        rows = conn.execute(
            "SELECT marker_name, value, ref_low, ref_high, status FROM blood_markers"
        ).fetchall()
    assert rows, "no blood markers seeded"
    for name, value, lo, hi, status in rows:
        assert value is not None, name
        assert lo is not None, name
        assert hi is not None, name
        assert status in ("low", "normal", "high", "unknown"), name
