"""Direct tests for the `biohub.body_comp` module.

Covers semantics that the CLI tests don't exercise on their own:
- INSERT OR REPLACE on the `date` UNIQUE key (re-logging replaces, not duplicates)
- start_phase / end_phase return-shape contract
- default_color fallback for unknown categories
- _require_v03_schema raises a useful RuntimeError on a pre-v0.3 health.db
- _open_health_db raises FileNotFoundError when the DB doesn't exist
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Make pipeline importable so `paths` reloads pick up the tmp env
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))


def _reload_body_comp(home: Path, monkeypatch):
    """Reload paths + body_comp against a fresh OPENCLAW_BIOHUB_HOME."""
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(home))
    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import biohub.body_comp as bc
    importlib.reload(bc)
    return bc, paths_mod


def _apply_v03_health_schema(db_path: Path) -> None:
    schema = (REPO_ROOT / "db" / "schema.sql").read_text()
    # health.db block is everything before '-- DB 2:'
    db1 = schema.split("-- DB 2:")[0]
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(db1)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def fresh_v03_home(tmp_path):
    """A clean OPENCLAW_BIOHUB_HOME with an empty v0.3 health.db."""
    (tmp_path / "data").mkdir()
    _apply_v03_health_schema(tmp_path / "data" / "health.db")
    return tmp_path


# ─── default_color ───────────────────────────────────────────────────────────


def test_default_color_known_categories(monkeypatch, tmp_path):
    bc, _ = _reload_body_comp(tmp_path, monkeypatch)
    assert bc.default_color("training") == "#34d399"
    assert bc.default_color("diet") == "#fbbf24"
    assert bc.default_color("supplement") == "#a78bfa"
    assert bc.default_color("medication") == "#f87171"
    assert bc.default_color("lifestyle") == "#38bdf8"


def test_default_color_unknown_category_falls_back(monkeypatch, tmp_path):
    bc, _ = _reload_body_comp(tmp_path, monkeypatch)
    # CONTRIBUTING.md documents slate (#94a3b8) as the fallback
    assert bc.default_color("PRP injection") == "#94a3b8"
    assert bc.default_color("") == "#94a3b8"


def test_default_color_is_case_insensitive(monkeypatch, tmp_path):
    bc, _ = _reload_body_comp(tmp_path, monkeypatch)
    assert bc.default_color("TRAINING") == "#34d399"
    assert bc.default_color(" Diet ") == "#fbbf24"


# ─── log_measurement upsert ──────────────────────────────────────────────────


def test_log_measurement_replaces_existing_row_for_same_date(
    fresh_v03_home, monkeypatch
):
    bc, paths_mod = _reload_body_comp(fresh_v03_home, monkeypatch)

    bc.log_measurement(
        date="2026-05-19", method="scale",
        weight_kg=80.0, body_fat_pct=15.0,
        lean_mass_kg=68.0, fat_mass_kg=12.0,
        skinfolds=None, notes="first",
    )
    # Re-log same date with different numbers — should REPLACE
    bc.log_measurement(
        date="2026-05-19", method="jackson-pollock-7",
        weight_kg=81.0, body_fat_pct=14.0,
        lean_mass_kg=69.66, fat_mass_kg=11.34,
        skinfolds={"chest": 8, "abdominal": 12, "thigh": 14, "tricep": 7,
                   "subscapular": 12, "suprailiac": 12, "midaxillary": 8},
        notes="second",
    )
    conn = sqlite3.connect(paths_mod.HEALTH_DB)
    try:
        rows = conn.execute(
            "SELECT method, weight_kg, body_fat_pct, notes, chest_mm "
            "FROM body_composition WHERE date = ?",
            ("2026-05-19",),
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    method, weight, bf, notes, chest_mm = rows[0]
    assert method == "jackson-pollock-7"
    assert weight == 81.0
    assert bf == 14.0
    assert notes == "second"
    assert chest_mm == 8


def test_log_measurement_dry_run_does_not_write(fresh_v03_home, monkeypatch):
    bc, paths_mod = _reload_body_comp(fresh_v03_home, monkeypatch)
    result = bc.log_measurement(
        date="2026-05-19", method="scale",
        weight_kg=80.0, body_fat_pct=15.0,
        lean_mass_kg=68.0, fat_mass_kg=12.0,
        skinfolds=None, notes=None,
        dry_run=True,
    )
    assert result["action"] == "dry-run"
    conn = sqlite3.connect(paths_mod.HEALTH_DB)
    try:
        n = conn.execute("SELECT COUNT(*) FROM body_composition").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


# ─── start_phase / end_phase / list_phases ───────────────────────────────────


def test_start_phase_returns_inserted_id(fresh_v03_home, monkeypatch):
    bc, paths_mod = _reload_body_comp(fresh_v03_home, monkeypatch)
    result = bc.start_phase(
        name="Test Cut", category="diet",
        start_date="2026-05-01", color=None, notes=None,
    )
    assert result["action"] == "inserted"
    assert isinstance(result["id"], int) and result["id"] > 0
    # color falls back to category default
    assert result["row"]["color"] == "#fbbf24"


def test_end_phase_no_match_returns_no_match(fresh_v03_home, monkeypatch):
    bc, _ = _reload_body_comp(fresh_v03_home, monkeypatch)
    result = bc.end_phase(name="Nonexistent Phase")
    assert result["action"] == "no-match"
    assert result["name"] == "Nonexistent Phase"


def test_end_phase_closes_most_recent_open_match(fresh_v03_home, monkeypatch):
    """If two phases share a name, `end` closes the most-recently started one."""
    bc, paths_mod = _reload_body_comp(fresh_v03_home, monkeypatch)
    bc.start_phase(name="Creatine", category="supplement",
                   start_date="2026-01-01")
    bc.start_phase(name="Creatine", category="supplement",
                   start_date="2026-04-01")
    result = bc.end_phase(name="Creatine", end_date="2026-05-19")
    assert result["action"] == "closed"
    assert result["row"]["start_date"] == "2026-04-01"

    # The 2026-01-01 one is still open
    open_phases = bc.list_phases(only_open=True)
    assert len(open_phases) == 1
    assert open_phases[0]["start_date"] == "2026-01-01"


def test_list_phases_orders_by_start_desc(fresh_v03_home, monkeypatch):
    bc, _ = _reload_body_comp(fresh_v03_home, monkeypatch)
    bc.start_phase(name="A", category="diet", start_date="2026-01-01")
    bc.start_phase(name="B", category="diet", start_date="2026-05-01")
    bc.start_phase(name="C", category="diet", start_date="2026-03-01")
    names = [p["name"] for p in bc.list_phases()]
    assert names == ["B", "C", "A"]


# ─── schema guards ───────────────────────────────────────────────────────────


def test_log_measurement_raises_filenotfound_when_db_missing(tmp_path, monkeypatch):
    """No `data/health.db` at all — error should point users at seed.py."""
    bc, _ = _reload_body_comp(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError, match="No health.db"):
        bc.log_measurement(
            date="2026-05-19", method="scale",
            weight_kg=80.0, body_fat_pct=15.0,
            lean_mass_kg=68.0, fat_mass_kg=12.0,
            skinfolds=None, notes=None,
        )


def test_log_measurement_raises_runtime_error_on_pre_v03_schema(
    tmp_path, monkeypatch
):
    """A health.db that's missing the body_composition table — error
    should point users at migrate_v0.2_to_v0.3.py."""
    (tmp_path / "data").mkdir()
    # Create a stub health.db with only daily_metrics (v0.2 shape, no body_comp)
    conn = sqlite3.connect(tmp_path / "data" / "health.db")
    try:
        conn.execute(
            "CREATE TABLE daily_metrics (source TEXT, date TEXT, "
            "PRIMARY KEY (source, date))"
        )
        conn.commit()
    finally:
        conn.close()
    bc, _ = _reload_body_comp(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="v0\\.3"):
        bc.log_measurement(
            date="2026-05-19", method="scale",
            weight_kg=80.0, body_fat_pct=15.0,
            lean_mass_kg=68.0, fat_mass_kg=12.0,
            skinfolds=None, notes=None,
        )


def test_start_phase_raises_on_pre_v03_schema(tmp_path, monkeypatch):
    """Same guard — start_phase touches `tracking_phases` so the error
    should mention the missing table name."""
    (tmp_path / "data").mkdir()
    conn = sqlite3.connect(tmp_path / "data" / "health.db")
    try:
        # Has body_composition but NOT tracking_phases
        conn.execute(
            "CREATE TABLE body_composition (id INTEGER PRIMARY KEY, "
            "date TEXT UNIQUE)"
        )
        conn.commit()
    finally:
        conn.close()
    bc, _ = _reload_body_comp(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="tracking_phases"):
        bc.start_phase(name="X", category="diet", start_date="2026-05-19")
