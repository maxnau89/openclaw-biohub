"""Tests for the FreeStyle Libre 3 / LibreView adapter."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

from adapters.libre.sync import LibreAdapter, _parse_ts, _to_float  # noqa: E402

_CSV_EN = """Glucose Data,Generated 07-02-2026
Device,Serial Number,Device Timestamp,Record Type,Historic Glucose mg/dL,Scan Glucose mg/dL,Notes,Carbohydrates (grams)
FreeStyle Libre 3,ABC,07-01-2026 08:15,0,102,,,
FreeStyle Libre 3,ABC,07-01-2026 13:00,1,,145,,
FreeStyle Libre 3,ABC,07-01-2026 13:05,6,,,Lunch,60
"""

# German locale: semicolon delimiter, mmol/L, DE headers.
_CSV_DE = """Glukosedaten
Gerät;Seriennummer;Gerätezeitstempel;Aufzeichnungstyp;Historische Glukose mmol/L;Gescannte Glukose mmol/L
Libre;XYZ;01.07.2026 09:00;0;5,5;
"""


def _fresh_db(tmp_path) -> tuple[LibreAdapter, sqlite3.Connection]:
    a = LibreAdapter()
    conn = sqlite3.connect(tmp_path / "libre_raw.db")
    a._ensure_schema(conn)
    return a, conn


def test_parse_timestamp_formats():
    assert _parse_ts("07-01-2026 08:15") is not None
    assert _parse_ts("01.07.2026 09:00") is not None
    assert _parse_ts("2026-07-01T22:00:00") is not None
    assert _parse_ts("garbage") is None


def test_to_float_handles_comma_decimal():
    assert _to_float("5,5") == 5.5
    assert _to_float("102") == 102.0
    assert _to_float("") is None


def test_csv_english_import(tmp_path):
    a, conn = _fresh_db(tmp_path)
    fp = tmp_path / "libre.csv"
    fp.write_text(_CSV_EN)
    n = a._ingest_file(conn, fp)
    assert n == 3
    rows = conn.execute(
        "SELECT record_type, glucose_mgdl, carbohydrates_g FROM glucose_data ORDER BY timestamp"
    ).fetchall()
    assert rows[0] == (0, 102.0, None)      # historic
    assert rows[1] == (1, 145.0, None)      # scan
    assert rows[2] == (6, None, 60.0)       # meal with carbs


def test_csv_german_mmol_converted(tmp_path):
    a, conn = _fresh_db(tmp_path)
    fp = tmp_path / "libre_de.csv"
    fp.write_text(_CSV_DE)
    n = a._ingest_file(conn, fp)
    assert n == 1
    g = conn.execute("SELECT glucose_mgdl FROM glucose_data").fetchone()[0]
    assert 98 < g < 101              # 5.5 mmol/L → ~99 mg/dL


def test_json_import(tmp_path):
    a, conn = _fresh_db(tmp_path)
    fp = tmp_path / "libre.json"
    fp.write_text('{"data":[{"timestamp":"2026-07-01T22:00:00","glucose_mgdl":98},'
                  '{"timestamp":"2026-07-01T22:15:00","value":92}]}')
    n = a._ingest_file(conn, fp)
    assert n == 2


def test_reimport_same_file_is_deduped(tmp_path):
    a, conn = _fresh_db(tmp_path)
    fp = tmp_path / "libre.csv"
    fp.write_text(_CSV_EN)
    assert a._ingest_file(conn, fp) == 3
    assert a._ingest_file(conn, fp) == 0     # import_log mtime guard


def test_rollup_is_noop():
    # Glucose is sub-daily and lives in its own analytics, not daily_metrics.
    assert LibreAdapter().rollup_to_health_db() == 0
