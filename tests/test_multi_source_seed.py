"""Integration tests for `fixtures/seed.py --source` modes.

Each test runs seed.py in a subprocess against a fresh tmp BIOHUB_HOME,
then asserts the resulting DBs are shaped correctly. These are the
acceptance tests for the multi-source story in v0.2.
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_SCRIPT = REPO_ROOT / "fixtures" / "seed.py"


def _run_seed(home: Path, source: str | None = None) -> None:
    env = {**os.environ, "OPENCLAW_BIOHUB_HOME": str(home)}
    args = [sys.executable, str(SEED_SCRIPT)]
    if source:
        args += ["--source", source]
    result = subprocess.run(args, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(
            f"seed.py failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


@pytest.fixture
def fresh_home():
    home = Path(tempfile.mkdtemp(prefix="biohub-multisource-"))
    yield home
    shutil.rmtree(home, ignore_errors=True)


# ─── --source whoop (default) ────────────────────────────────────────────────


def test_default_source_only_writes_whoop(fresh_home):
    _run_seed(fresh_home)
    assert (fresh_home / "data" / "health.db").exists()
    assert (fresh_home / "data" / "whoop_raw.db").exists()
    assert not (fresh_home / "data" / "oura_raw.db").exists()

    with sqlite3.connect(fresh_home / "data" / "health.db") as conn:
        rows = conn.execute(
            "SELECT source, COUNT(*) FROM daily_metrics GROUP BY source"
        ).fetchall()
    assert rows == [("whoop", 90)]


# ─── --source oura ──────────────────────────────────────────────────────────


def test_source_oura_writes_only_oura(fresh_home):
    _run_seed(fresh_home, source="oura")
    assert (fresh_home / "data" / "oura_raw.db").exists()
    assert not (fresh_home / "data" / "whoop_raw.db").exists()

    with sqlite3.connect(fresh_home / "data" / "health.db") as conn:
        rows = conn.execute(
            "SELECT source, COUNT(*) FROM daily_metrics GROUP BY source"
        ).fetchall()
    assert rows == [("oura", 90)]


def test_source_oura_populates_raw_tables(fresh_home):
    _run_seed(fresh_home, source="oura")
    with sqlite3.connect(fresh_home / "data" / "oura_raw.db") as conn:
        for table in ("daily_sleep", "sleep_session", "daily_readiness",
                      "daily_activity", "daily_spo2"):
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert n == 90, f"{table} has {n} rows, expected 90"


def test_source_oura_seeds_blood_and_supplements(fresh_home):
    """When only --source oura is used, blood/supplements/nutrition still
    appear in health.db (they're source-agnostic)."""
    _run_seed(fresh_home, source="oura")
    with sqlite3.connect(fresh_home / "data" / "health.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM blood_panels").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM supplements").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM nutrition_logs").fetchone()[0] == 30


# ─── --source all ───────────────────────────────────────────────────────────


def test_source_all_writes_both_raw_dbs(fresh_home):
    _run_seed(fresh_home, source="all")
    assert (fresh_home / "data" / "whoop_raw.db").exists()
    assert (fresh_home / "data" / "oura_raw.db").exists()


def test_source_all_health_db_has_both_sources(fresh_home):
    _run_seed(fresh_home, source="all")
    with sqlite3.connect(fresh_home / "data" / "health.db") as conn:
        rows = conn.execute(
            "SELECT source, COUNT(*) FROM daily_metrics GROUP BY source ORDER BY source"
        ).fetchall()
    assert rows == [("oura", 90), ("whoop", 90)]


def test_source_all_dashboard_query_returns_multiple_sources_per_date(fresh_home):
    """The dashboard's daily-trend chart joins by date and shows both
    sources. Verify that for the most recent date, both whoop and oura
    contribute rows."""
    _run_seed(fresh_home, source="all")
    with sqlite3.connect(fresh_home / "data" / "health.db") as conn:
        # Most-recent date that has both sources
        row = conn.execute("""
            SELECT date, COUNT(DISTINCT source) AS n_sources
            FROM daily_metrics
            GROUP BY date
            HAVING n_sources = 2
            ORDER BY date DESC LIMIT 1
        """).fetchone()
    assert row is not None
    assert row[1] == 2


# ─── body_composition + tracking_phases (source-agnostic) ───────────────────


def test_default_source_seeds_body_composition_and_phases(fresh_home):
    """body_composition + tracking_phases are seeded regardless of source."""
    _run_seed(fresh_home)
    with sqlite3.connect(fresh_home / "data" / "health.db") as conn:
        n_caliper = conn.execute("SELECT COUNT(*) FROM body_composition").fetchone()[0]
        n_phases = conn.execute("SELECT COUNT(*) FROM tracking_phases").fetchone()[0]
    assert n_caliper == 8
    assert n_phases == 2


def test_seeded_body_composition_has_caliper_method_and_full_skinfolds(fresh_home):
    _run_seed(fresh_home)
    with sqlite3.connect(fresh_home / "data" / "health.db") as conn:
        row = conn.execute("""
            SELECT method, weight_kg, body_fat_pct, lean_mass_kg, fat_mass_kg,
                   chest_mm, abdominal_mm, thigh_mm, tricep_mm,
                   subscapular_mm, suprailiac_mm, midaxillary_mm
            FROM body_composition
            ORDER BY date DESC LIMIT 1
        """).fetchone()
    assert row[0] == "jackson-pollock-7"
    # Every numeric field populated
    for i, v in enumerate(row[1:]):
        assert v is not None and v > 0, f"column index {i} is empty: {v}"


def test_seeded_phases_include_one_open_and_one_closed(fresh_home):
    """The Bulk phase stays open (end_date NULL); the Cut phase is closed."""
    _run_seed(fresh_home)
    with sqlite3.connect(fresh_home / "data" / "health.db") as conn:
        rows = conn.execute(
            "SELECT name, category, end_date IS NULL AS is_open, color "
            "FROM tracking_phases ORDER BY start_date"
        ).fetchall()
    names = [r[0] for r in rows]
    assert names == ["Sample Cut", "Sample Bulk"]
    # Cut closed, Bulk open
    assert rows[0][2] == 0
    assert rows[1][2] == 1
    # Category-default colors
    assert rows[0][1] == "diet" and rows[0][3] == "#fbbf24"
    assert rows[1][1] == "training" and rows[1][3] == "#34d399"


def test_seeded_caliper_arc_shows_fat_loss_then_recovery(fresh_home):
    """Caliper arc: BF drops through the Cut window, then rises on the Bulk."""
    _run_seed(fresh_home)
    with sqlite3.connect(fresh_home / "data" / "health.db") as conn:
        bf_series = [r[0] for r in conn.execute(
            "SELECT body_fat_pct FROM body_composition ORDER BY date"
        )]
    assert len(bf_series) == 8
    # Highest BF early; lowest BF mid-late; final BF is in between
    assert bf_series[0] == max(bf_series)
    assert bf_series[5] == min(bf_series)
    assert bf_series[-1] > min(bf_series)


def test_source_all_oura_and_whoop_have_distinct_averages(fresh_home):
    """Sanity check that the two sources aren't accidentally identical —
    they're generated with different RNG offsets so a real visualization
    can tell them apart."""
    _run_seed(fresh_home, source="all")
    with sqlite3.connect(fresh_home / "data" / "health.db") as conn:
        whoop_avg = conn.execute(
            "SELECT AVG(recovery_score) FROM daily_metrics WHERE source='whoop'"
        ).fetchone()[0]
        oura_avg = conn.execute(
            "SELECT AVG(recovery_score) FROM daily_metrics WHERE source='oura'"
        ).fetchone()[0]
    assert abs(whoop_avg - oura_avg) > 1.0, (
        f"whoop and oura averages too close ({whoop_avg} vs {oura_avg}) — "
        "double-check the RNG offsets"
    )
