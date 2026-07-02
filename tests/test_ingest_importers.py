"""Tests for the automated blood-panel and supplement-log importers."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

SCHEMA = REPO_ROOT / "db" / "schema.sql"


def _health_db(tmp_path) -> Path:
    """A fresh health.db from the DB-1 section of the canonical schema."""
    ddl = SCHEMA.read_text().split("-- DB 2:")[0]
    db = tmp_path / "health.db"
    conn = sqlite3.connect(db)
    conn.executescript(ddl)
    conn.close()
    return db


# ─── Supplement importer ─────────────────────────────────────────────────────

def test_supplement_csv_import_creates_supplement_and_logs(tmp_path, monkeypatch):
    db = _health_db(tmp_path)
    import paths
    monkeypatch.setattr(paths, "HEALTH_DB", db)
    import supplement_import
    monkeypatch.setattr(supplement_import, "HEALTH_DB", db)

    fp = tmp_path / "log.csv"
    fp.write_text("date,supplement,dose_mg,dose_unit,notes\n"
                  "2026-07-01 08:00,Creatine,5000,mg,morning\n"
                  "2026-07-02 08:00,Creatine,5000,mg,\n"
                  "2026-07-01 08:00,Vitamin D,25,mcg,\n")
    conn = sqlite3.connect(db)
    conn.executescript(supplement_import._IMPORT_LOG_DDL)
    n = supplement_import.ingest_file(conn, fp)
    assert n == 3
    supps = conn.execute("SELECT name FROM supplements ORDER BY name").fetchall()
    assert [s[0] for s in supps] == ["Creatine", "Vitamin D"]
    logs = conn.execute("SELECT COUNT(*) FROM supplement_log").fetchone()[0]
    assert logs == 3
    conn.close()


def test_supplement_reimport_is_deduped(tmp_path, monkeypatch):
    db = _health_db(tmp_path)
    import supplement_import
    monkeypatch.setattr(supplement_import, "HEALTH_DB", db)
    fp = tmp_path / "log.csv"
    fp.write_text("date,supplement,dose_mg\n2026-07-01 08:00,Creatine,5000\n")
    conn = sqlite3.connect(db)
    conn.executescript(supplement_import._IMPORT_LOG_DDL)
    assert supplement_import.ingest_file(conn, fp) == 1
    assert supplement_import.ingest_file(conn, fp) == 0     # file mtime guard
    conn.close()


def test_supplement_json_and_dedup_on_timestamp(tmp_path, monkeypatch):
    db = _health_db(tmp_path)
    import supplement_import
    monkeypatch.setattr(supplement_import, "HEALTH_DB", db)
    fp = tmp_path / "log.json"
    # Two entries at the SAME (supplement, timestamp) → second is deduped.
    fp.write_text('[{"date":"2026-07-01 08:00","supplement":"Zinc","dose_mg":15},'
                  '{"date":"2026-07-01 08:00","supplement":"Zinc","dose_mg":15}]')
    conn = sqlite3.connect(db)
    conn.executescript(supplement_import._IMPORT_LOG_DDL)
    assert supplement_import.ingest_file(conn, fp) == 1
    conn.close()


# ─── Blood-panel importer ────────────────────────────────────────────────────

def test_blood_panel_text_import(tmp_path, monkeypatch):
    db = _health_db(tmp_path)
    import blood_panel_import
    monkeypatch.setattr(blood_panel_import, "HEALTH_DB", db)

    # Tight value+unit + ref-range format, as extracted from real lab PDFs
    # (parse_blood_panel is German-lab-oriented). Date in the header.
    fp = tmp_path / "labs-2026-07-01.txt"
    fp.write_text(
        "Befund 2026-07-01\n"
        "Hämoglobin 15.2g/dl 13.5-17.5\n"
        "Ferritin 120ng/ml 30-400\n"
    )
    conn = sqlite3.connect(db)
    conn.executescript(blood_panel_import._IMPORT_LOG_DDL)
    panel_id, n_markers = blood_panel_import.ingest_file(conn, fp)
    assert panel_id > 0 and n_markers == 2
    pdate = conn.execute("SELECT panel_date FROM blood_panels WHERE id = ?", (panel_id,)).fetchone()[0]
    assert pdate == "2026-07-01"
    markers = conn.execute(
        "SELECT marker_name, value, status FROM blood_markers WHERE panel_id = ? ORDER BY marker_name",
        (panel_id,),
    ).fetchall()
    assert ("Ferritin", 120.0, "normal") in markers
    conn.close()


def test_blood_panel_reimport_is_deduped(tmp_path, monkeypatch):
    db = _health_db(tmp_path)
    import blood_panel_import
    monkeypatch.setattr(blood_panel_import, "HEALTH_DB", db)
    fp = tmp_path / "labs.txt"
    fp.write_text("2026-07-01\nGlucose 92 mg/dL (70 - 100)\n")
    conn = sqlite3.connect(db)
    conn.executescript(blood_panel_import._IMPORT_LOG_DDL)
    blood_panel_import.ingest_file(conn, fp)
    # Second run: mtime unchanged → skipped regardless of marker match.
    assert blood_panel_import.ingest_file(conn, fp) == (0, 0)
    conn.close()


def test_blood_panel_date_fallback_to_filename(tmp_path, monkeypatch):
    db = _health_db(tmp_path)
    import blood_panel_import
    monkeypatch.setattr(blood_panel_import, "HEALTH_DB", db)
    # No date in text → falls back to the filename date.
    d = blood_panel_import._panel_date_from("Glucose 92", Path("panel-2026-03-15.txt"))
    assert d == "2026-03-15"
