#!/usr/bin/env python3
"""Automated supplement-log ingest — CSV/JSON bulk importer.

Complements the dashboard's one-at-a-time quick-log with a watch-folder
importer for intake history (e.g. exported from a habit tracker or a
spreadsheet). Each row is a single intake:

    CSV header:  date,supplement,dose_mg,dose_unit,notes
    or JSON:     [{"date": "...", "supplement": "...", "dose_mg": 5000, ...}]

Unknown supplement names are auto-created in the `supplements` table.
Deduped on (supplement_id, taken_at) so re-importing the same history is a
no-op. Safe to run from cron over a watch folder.

    python3 supplement_import.py --watch-dir ~/biohub-inbox/supplements
    python3 supplement_import.py --file ~/Downloads/creatine-log.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from paths import HEALTH_DB

_IMPORT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS supplement_import_log (
    file_path TEXT,
    file_mtime REAL,
    rows_inserted INTEGER,
    imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(file_path, file_mtime)
)
"""

_TS_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%d.%m.%Y")


def _norm_ts(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(raw, fmt).isoformat(sep=" ", timespec="minutes")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).isoformat(sep=" ", timespec="minutes")
    except ValueError:
        return None


def _to_float(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def _resolve_supplement(conn: sqlite3.Connection, name: str) -> int:
    name = name.strip()
    row = conn.execute(
        "SELECT id FROM supplements WHERE LOWER(name) = LOWER(?)", (name,)
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute("INSERT INTO supplements (name) VALUES (?)", (name,))
    return cur.lastrowid


def _rows_from(fp: Path) -> list[dict]:
    if fp.suffix.lower() == ".json":
        payload = json.loads(fp.read_text())
        return payload if isinstance(payload, list) else payload.get("data", [])
    with open(fp, encoding="utf-8-sig", newline="") as f:
        return [{k.strip().lower(): v for k, v in r.items() if k} for r in csv.DictReader(f)]


def ingest_file(conn: sqlite3.Connection, fp: Path) -> int:
    try:
        mtime = int(fp.stat().st_mtime)
    except OSError:
        return 0
    if conn.execute(
        "SELECT 1 FROM supplement_import_log WHERE file_path = ? AND file_mtime = ?",
        (str(fp), mtime),
    ).fetchone():
        return 0
    inserted = 0
    for row in _rows_from(fp):
        name = row.get("supplement") or row.get("name")
        taken_at = _norm_ts(str(row.get("date") or row.get("taken_at") or ""))
        if not name or not taken_at:
            continue
        sid = _resolve_supplement(conn, str(name))
        # Dedup: one intake per (supplement, timestamp).
        if conn.execute(
            "SELECT 1 FROM supplement_log WHERE supplement_id = ? AND taken_at = ?",
            (sid, taken_at),
        ).fetchone():
            continue
        conn.execute(
            "INSERT INTO supplement_log (supplement_id, taken_at, dose_mg, dose_unit, notes, source) "
            "VALUES (?,?,?,?,?,'import')",
            (sid, taken_at, _to_float(row.get("dose_mg")),
             row.get("dose_unit") or "mg", row.get("notes")),
        )
        inserted += 1
    conn.execute(
        "INSERT OR REPLACE INTO supplement_import_log (file_path, file_mtime, rows_inserted) "
        "VALUES (?,?,?)",
        (str(fp), mtime, inserted),
    )
    conn.commit()
    return inserted


def scan(watch_dir: Path) -> dict:
    conn = sqlite3.connect(HEALTH_DB)
    conn.executescript(_IMPORT_LOG_DDL)
    total = 0
    files = sorted(
        f for f in watch_dir.iterdir()
        if f.is_file() and f.suffix.lower() in (".csv", ".json")
    ) if watch_dir.exists() else []
    for fp in files:
        try:
            total += ingest_file(conn, fp)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {fp.name}: {e}", file=sys.stderr)
    conn.close()
    return {"logs_imported": total, "files_seen": len(files)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Import supplement-log CSV/JSON into health.db")
    ap.add_argument("--watch-dir", help="Folder to scan for CSV/JSON supplement logs")
    ap.add_argument("--file", help="Import a single file")
    args = ap.parse_args()
    if args.file:
        conn = sqlite3.connect(HEALTH_DB)
        conn.executescript(_IMPORT_LOG_DDL)
        n = ingest_file(conn, Path(args.file).expanduser())
        conn.close()
        print(json.dumps({"logs_imported": n}))
        return 0
    watch = Path(args.watch_dir).expanduser() if args.watch_dir else Path.home() / "biohub-inbox" / "supplements"
    print(json.dumps(scan(watch)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
