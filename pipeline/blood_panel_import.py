#!/usr/bin/env python3
"""Automated blood-panel ingest — a watch-folder importer.

Until now blood panels arrived only via manual dashboard upload. This scans
a folder for lab-result files (PDF, or .txt/.md for already-extracted text),
parses them with the existing `parse_blood_panel` extractor, and writes the
panel + markers into health.db. Deduped per file via a small import_log so
re-scanning is a no-op; safe to run from cron.

    python3 blood_panel_import.py --watch-dir ~/biohub-inbox/blood
    python3 blood_panel_import.py --file ~/Downloads/labcorp-2026-07.pdf

Marker reference-range flags (low/normal/high) come straight from the parser.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

from paths import HEALTH_DB
from parse_blood_panel import extract_text_from_pdf, parse_text

_IMPORT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS blood_import_log (
    file_path TEXT,
    file_mtime REAL,
    panel_id INTEGER,
    markers INTEGER,
    imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(file_path, file_mtime)
)
"""

_DATE_RE = re.compile(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})|(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})")


def _panel_date_from(text: str, fp: Path) -> str:
    """Best-effort panel date: first date-like token in the text, else the
    filename, else today."""
    for hay in (text[:2000], fp.name):
        m = _DATE_RE.search(hay or "")
        if m:
            g = m.groups()
            if g[0]:
                return f"{g[0]}-{int(g[1]):02d}-{int(g[2]):02d}"
            return f"{g[5]}-{int(g[4]):02d}-{int(g[3]):02d}"
    return date.today().isoformat()


def _extract_text(fp: Path) -> str:
    if fp.suffix.lower() == ".pdf":
        return extract_text_from_pdf(str(fp))
    return fp.read_text(encoding="utf-8", errors="ignore")


def ingest_file(conn: sqlite3.Connection, fp: Path) -> tuple[int, int]:
    """Parse one file → (panel_id, markers). (0, 0) if skipped/duplicate."""
    try:
        mtime = int(fp.stat().st_mtime)
    except OSError:
        return 0, 0
    if conn.execute(
        "SELECT 1 FROM blood_import_log WHERE file_path = ? AND file_mtime = ?",
        (str(fp), mtime),
    ).fetchone():
        return 0, 0

    text = _extract_text(fp)
    markers = parse_text(text)
    if not markers:
        conn.execute(
            "INSERT OR REPLACE INTO blood_import_log (file_path, file_mtime, panel_id, markers) "
            "VALUES (?,?,NULL,0)",
            (str(fp), mtime),
        )
        conn.commit()
        return 0, 0

    panel_date = _panel_date_from(text, fp)
    cur = conn.execute(
        "INSERT INTO blood_panels (panel_date, lab_name, source_filename, raw_text) "
        "VALUES (?,?,?,?)",
        (panel_date, None, fp.name, text[:20000]),
    )
    panel_id = cur.lastrowid
    for m in markers:
        conn.execute(
            "INSERT INTO blood_markers "
            "(panel_id, marker_name, value, unit, ref_low, ref_high, status) "
            "VALUES (?,?,?,?,?,?,?)",
            (panel_id, m.get("marker_name") or m.get("name"), m.get("value"),
             m.get("unit"), m.get("ref_low"), m.get("ref_high"),
             m.get("status", "unknown")),
        )
    conn.execute(
        "INSERT OR REPLACE INTO blood_import_log (file_path, file_mtime, panel_id, markers) "
        "VALUES (?,?,?,?)",
        (str(fp), mtime, panel_id, len(markers)),
    )
    conn.commit()
    return panel_id, len(markers)


def scan(watch_dir: Path) -> dict:
    conn = sqlite3.connect(HEALTH_DB)
    conn.executescript(_IMPORT_LOG_DDL)
    panels = markers = 0
    files = sorted(
        f for f in watch_dir.iterdir()
        if f.is_file() and f.suffix.lower() in (".pdf", ".txt", ".md")
    ) if watch_dir.exists() else []
    for fp in files:
        try:
            pid, n = ingest_file(conn, fp)
            if pid:
                panels += 1
                markers += n
        except Exception as e:  # noqa: BLE001 — one bad file shouldn't halt the batch
            print(f"[warn] {fp.name}: {e}", file=sys.stderr)
    conn.close()
    return {"panels_imported": panels, "markers_imported": markers, "files_seen": len(files)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Import blood-panel files into health.db")
    ap.add_argument("--watch-dir", help="Folder to scan for PDF/txt lab results")
    ap.add_argument("--file", help="Import a single file")
    args = ap.parse_args()
    if args.file:
        conn = sqlite3.connect(HEALTH_DB)
        conn.executescript(_IMPORT_LOG_DDL)
        pid, n = ingest_file(conn, Path(args.file).expanduser())
        conn.close()
        print(json.dumps({"panel_id": pid, "markers": n}))
        return 0
    watch = Path(args.watch_dir).expanduser() if args.watch_dir else Path.home() / "biohub-inbox" / "blood"
    print(json.dumps(scan(watch)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
