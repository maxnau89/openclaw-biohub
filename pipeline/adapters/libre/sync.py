"""FreeStyle Libre 3 / LibreView adapter — continuous glucose monitoring.

File-based, like the Apple Health adapter: LibreView has no public developer
API, so the user exports their data and biohub ingests it from a watch
directory. Two formats are supported:

  • LibreView CSV export (Account → "Download glucose data") — the canonical
    format. Row 1 is the device name, row 2 the header; delimiter and column
    names vary by locale (English / German), and glucose may be mg/dL or
    mmol/L. All handled here.
  • JSON dumps (e.g. a Health-Auto-Export or LibreLinkUp shortcut) — a list
    of `{timestamp, glucose_mgdl|value, record_type?, ...}` objects, or an
    object with a `"data"` list of the same.

Both land in `libre_raw.db` (glucose is sub-daily, so it is NOT rolled into
the daily_metrics table; `glucose_analytics.py` + the dashboard "Glucose"
tab read libre_raw.db directly). Idempotent per file via import_log(mtime).

CSV parsing logic adapted from the openclaw workspace `libre_import.py`.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from adapters.base import BiometricAdapter, Stability, SyncResult

MMOL_TO_MGDL = 18.01559
RECORD_HISTORIC = 0
RECORD_SCAN = 1
_SCHEMA = Path(__file__).with_name("schema.sql")

_TS_FORMATS = (
    "%m/%d/%Y %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M",
    "%m/%d/%Y %I:%M %p", "%d-%m-%Y %H:%M", "%Y-%m-%dT%H:%M:%S",
)


def _parse_ts(ts: str) -> datetime | None:
    ts = (ts or "").strip()
    if not ts:
        return None
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _to_float(raw: str | float | None) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw).replace(",", "."))
    except ValueError:
        return None


def _detect_delimiter(fp: Path) -> str:
    with open(fp, encoding="utf-8-sig") as f:
        f.readline()               # skip device-name line
        header = f.readline()
    return ";" if header.count(";") > header.count(",") else ","


def _first(row: dict, *keys: str) -> str:
    for k in keys:
        if row.get(k):
            return row[k]
    return ""


class LibreAdapter(BiometricAdapter):
    slug = "libre"
    display_name = "FreeStyle Libre 3"
    raw_db_name = "libre_raw.db"
    stability: Stability = "experimental"
    requires_oauth = False

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def setup_instructions(self) -> str:
        return (
            "## FreeStyle Libre 3 (LibreView)\n\n"
            "LibreView has no public API, so biohub ingests your exported data "
            "from a folder you choose.\n\n"
            "1. Sign in at https://www.libreview.com → your profile.\n"
            "2. **Download glucose data** — you get a CSV export.\n"
            "3. Drop the CSV (or a JSON dump from a Libre shortcut) into a "
            "watch folder, e.g. `~/biohub-inbox/libre/`.\n"
            "4. Re-export and drop new files whenever you want to refresh; "
            "`biohub sync libre` picks up anything new (deduped by file mtime).\n\n"
            "CSV locale/units (mg/dL vs mmol/L, `,` vs `;`, EN/DE headers) are "
            "auto-detected."
        )

    def configure_interactive(self) -> None:
        watch_dir = input(
            "Folder to watch for LibreView CSV/JSON exports "
            "[~/biohub-inbox/libre]: "
        ).strip() or "~/biohub-inbox/libre"
        watch = Path(watch_dir).expanduser()
        watch.mkdir(parents=True, exist_ok=True)
        self.secrets_path.parent.mkdir(parents=True, exist_ok=True)
        self.secrets_path.write_text(json.dumps({"watch_dir": str(watch)}))
        self.secrets_path.chmod(0o600)
        print(f"Libre watch folder set to {watch}")

    def _watch_dir(self) -> Path:
        if not self.secrets_path.exists():
            raise FileNotFoundError(
                f"No Libre config at {self.secrets_path}. Run `biohub connect libre`."
            )
        return Path(json.loads(self.secrets_path.read_text())["watch_dir"]).expanduser()

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(_SCHEMA.read_text())

    # ── Parsing ────────────────────────────────────────────────────────────
    def _rows_from_csv(self, fp: Path) -> list[tuple]:
        delimiter = _detect_delimiter(fp)
        rows: list[tuple] = []
        with open(fp, encoding="utf-8-sig") as f:
            device_line = f.readline().strip()
            reader = csv.DictReader(f, delimiter=delimiter)
            for raw in reader:
                row = {k.strip(): (v.strip() if v else "") for k, v in raw.items() if k}
                ts = _parse_ts(_first(row, "Device Timestamp", "Gerätezeitstempel", "Date/Time"))
                if not ts:
                    continue
                try:
                    rtype = int(_first(row, "Record Type", "Aufzeichnungstyp") or "0")
                except ValueError:
                    rtype = -1
                glucose = None
                if rtype in (RECORD_HISTORIC, RECORD_SCAN):
                    glucose = _to_float(_first(
                        row, "Historic Glucose mg/dL", "Historische Glukose mg/dL",
                        "Scan Glucose mg/dL", "Gescannte Glukose mg/dL"))
                    if glucose is None:
                        mmol = _to_float(_first(
                            row, "Historic Glucose mmol/L", "Scan Glucose mmol/L",
                            "Historische Glukose mmol/L", "Gescannte Glukose mmol/L"))
                        if mmol is not None:
                            glucose = round(mmol * MMOL_TO_MGDL, 1)
                carbs = _to_float(_first(row, "Carbohydrates (grams)", "Kohlenhydrate (Gramm)"))
                notes = _first(row, "Notes", "Notizen") or None
                device = _first(row, "Device", "Gerät") or device_line[:50]
                serial = _first(row, "Serial Number", "Seriennummer") or "unknown"
                rows.append((device, serial, ts.isoformat(), rtype, glucose, notes, carbs))
        return rows

    def _rows_from_json(self, fp: Path) -> list[tuple]:
        payload = json.loads(fp.read_text())
        items = payload.get("data", payload) if isinstance(payload, dict) else payload
        rows: list[tuple] = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            ts = _parse_ts(str(it.get("timestamp") or it.get("time") or it.get("date") or ""))
            if not ts:
                continue
            glucose = _to_float(it.get("glucose_mgdl") or it.get("value") or it.get("glucose"))
            if glucose is None and (mmol := _to_float(it.get("glucose_mmol"))) is not None:
                glucose = round(mmol * MMOL_TO_MGDL, 1)
            rtype = int(it.get("record_type", RECORD_HISTORIC))
            rows.append((
                it.get("device", "libre-json"), it.get("serial_number", "unknown"),
                ts.isoformat(), rtype, glucose, it.get("notes"),
                _to_float(it.get("carbohydrates_g")),
            ))
        return rows

    def _ingest_file(self, conn: sqlite3.Connection, fp: Path) -> int:
        try:
            mtime = int(fp.stat().st_mtime)
        except OSError:
            return 0
        seen = conn.execute(
            "SELECT 1 FROM import_log WHERE file_path = ? AND file_mtime = ? AND success = 1",
            (str(fp), mtime),
        ).fetchone()
        if seen:
            return 0
        try:
            rows = self._rows_from_json(fp) if fp.suffix.lower() == ".json" \
                else self._rows_from_csv(fp)
            n = 0
            for r in rows:
                conn.execute(
                    "INSERT OR IGNORE INTO glucose_data "
                    "(device, serial_number, timestamp, record_type, glucose_mgdl, "
                    " notes, carbohydrates_g) VALUES (?,?,?,?,?,?,?)",
                    r,
                )
                n += conn.execute("SELECT changes()").fetchone()[0]
            conn.execute(
                "INSERT OR REPLACE INTO import_log "
                "(file_path, file_mtime, records_count, success) VALUES (?,?,?,1)",
                (str(fp), mtime, n),
            )
            conn.commit()
            return n
        except Exception as e:  # noqa: BLE001 — record the failure, keep going
            conn.execute(
                "INSERT OR REPLACE INTO import_log "
                "(file_path, file_mtime, records_count, success, error_message) "
                "VALUES (?,?,0,0,?)",
                (str(fp), mtime, str(e)),
            )
            conn.commit()
            return 0

    def sync(self, since: str | None = None, limit: int | None = None) -> SyncResult:
        watch = self._watch_dir()
        conn = sqlite3.connect(self.raw_db_path)
        try:
            self._ensure_schema(conn)
            if not watch.exists():
                return SyncResult(error=f"watch dir {watch} not found")
            files = sorted(
                f for f in watch.iterdir()
                if f.is_file() and f.suffix.lower() in (".csv", ".json")
            )
            if limit:
                files = files[:limit]
            inserted = sum(self._ingest_file(conn, fp) for fp in files)
            return SyncResult(rows_inserted=inserted)
        finally:
            conn.close()

    def rollup_to_health_db(self) -> int:
        # Glucose is sub-daily; there is no glucose column in daily_metrics.
        # It is surfaced through glucose_analytics.py + the dashboard "Glucose"
        # tab, which read libre_raw.db directly. Nothing to roll up.
        return 0


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="Sync FreeStyle Libre data")
    p.add_argument("--file", help="Import a single CSV/JSON file directly")
    args = p.parse_args()
    adapter = LibreAdapter()
    if args.file:
        conn = sqlite3.connect(adapter.raw_db_path)
        adapter._ensure_schema(conn)
        n = adapter._ingest_file(conn, Path(args.file).expanduser())
        conn.close()
        print(f"Imported {n} readings from {args.file}")
        return 0
    print(adapter.sync())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
