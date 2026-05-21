"""Body-composition + tracking-phase helpers backing the biohub CLI.

Public surface:
- compute_bf_jp7(sites, sex, age)         → body-fat % (Jackson-Pollock 7-site + Siri)
- log_measurement(...)                    → INSERT OR REPLACE into body_composition
- start_phase / end_phase / list_phases   → tracking_phases CRUD

These functions resolve health.db via paths.HEALTH_DB (the same env-driven
location every other adapter uses). They raise FileNotFoundError if the
DB is missing and RuntimeError if the v0.3 tables aren't there yet
(pointing the user at db/migrate_v0.2_to_v0.3.py).
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date as date_cls
from pathlib import Path
from typing import Any

# Make `paths` importable
_PIPELINE_DIR = Path(__file__).resolve().parent.parent / "pipeline"
if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))
from paths import HEALTH_DB  # noqa: E402


# ─── Body-fat math ───────────────────────────────────────────────────────────


def compute_bf_jp7(sites: dict[str, float], sex: str, age: int) -> float:
    """Jackson-Pollock 7-site skinfold formula → body density → Siri → BF%.

    sites: dict with these 7 keys in mm:
        chest, abdominal, thigh, tricep, subscapular, suprailiac, midaxillary
    sex: 'm' or 'f' (case-insensitive)
    age: years

    Returns body-fat percentage (0-100).
    """
    required = ("chest", "abdominal", "thigh", "tricep",
                "subscapular", "suprailiac", "midaxillary")
    missing = [k for k in required if k not in sites]
    if missing:
        raise ValueError(f"compute_bf_jp7 missing site(s): {missing}")
    total = float(sum(sites[k] for k in required))
    s = sex.strip().lower()
    if s == "m":
        density = 1.112 - 0.00043499 * total + 0.00000055 * total * total \
            - 0.00028826 * age
    elif s == "f":
        density = 1.097 - 0.00046971 * total + 0.00000056 * total * total \
            - 0.00012828 * age
    else:
        raise ValueError(f"sex must be 'm' or 'f', got {sex!r}")
    # Siri equation
    bf_pct = (495.0 / density) - 450.0
    return round(bf_pct, 2)


def derive_mass(weight_kg: float, body_fat_pct: float) -> tuple[float, float]:
    """Return (lean_mass_kg, fat_mass_kg) given weight + BF%."""
    fat_mass = weight_kg * body_fat_pct / 100.0
    lean_mass = weight_kg - fat_mass
    return round(lean_mass, 2), round(fat_mass, 2)


# ─── DB helpers ──────────────────────────────────────────────────────────────


def _open_health_db() -> sqlite3.Connection:
    if not HEALTH_DB.exists():
        raise FileNotFoundError(
            f"No health.db at {HEALTH_DB}. "
            "Set OPENCLAW_BIOHUB_HOME or run `fixtures/seed.py` first."
        )
    conn = sqlite3.connect(HEALTH_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _require_v03_schema(conn: sqlite3.Connection) -> None:
    for table in ("body_composition", "tracking_phases"):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"health.db is missing the v0.3 table {table!r}. "
                "Run `python3 db/migrate_v0.2_to_v0.3.py` first."
            )


# ─── log-measurement ─────────────────────────────────────────────────────────


def log_measurement(
    *,
    date: str,
    method: str,
    weight_kg: float | None,
    body_fat_pct: float | None,
    lean_mass_kg: float | None,
    fat_mass_kg: float | None,
    skinfolds: dict[str, float] | None = None,
    notes: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """INSERT OR REPLACE one row into body_composition. If skinfolds are
    provided but body_fat_pct/lean/fat are not, the caller is expected to
    have already computed them via compute_bf_jp7 + derive_mass."""
    sf = skinfolds or {}
    row = {
        "date": date,
        "method": method,
        "body_fat_pct": body_fat_pct,
        "weight_kg": weight_kg,
        "lean_mass_kg": lean_mass_kg,
        "fat_mass_kg": fat_mass_kg,
        "chest_mm":       sf.get("chest"),
        "abdominal_mm":   sf.get("abdominal"),
        "thigh_mm":       sf.get("thigh"),
        "tricep_mm":      sf.get("tricep"),
        "subscapular_mm": sf.get("subscapular"),
        "suprailiac_mm":  sf.get("suprailiac"),
        "midaxillary_mm": sf.get("midaxillary"),
        "notes": notes,
    }
    if dry_run:
        return {"action": "dry-run", "row": row}

    conn = _open_health_db()
    try:
        _require_v03_schema(conn)
        cols = list(row.keys())
        placeholders = ",".join("?" for _ in cols)
        conn.execute(
            f"INSERT OR REPLACE INTO body_composition ({','.join(cols)}) "
            f"VALUES ({placeholders})",
            [row[c] for c in cols],
        )
        conn.commit()
        return {"action": "inserted", "row": row}
    finally:
        conn.close()


# ─── log-phase ───────────────────────────────────────────────────────────────


# Sensible color presets — used when the user doesn't pass --color.
_CATEGORY_DEFAULT_COLORS = {
    "training":   "#34d399",   # emerald
    "diet":       "#fbbf24",   # amber
    "supplement": "#a78bfa",   # violet
    "medication": "#f87171",   # rose
    "lifestyle":  "#38bdf8",   # sky
}


def default_color(category: str) -> str:
    return _CATEGORY_DEFAULT_COLORS.get(category.strip().lower(), "#94a3b8")


def start_phase(
    *,
    name: str,
    category: str,
    start_date: str | None = None,
    color: str | None = None,
    notes: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    start = start_date or date_cls.today().isoformat()
    chosen_color = color or default_color(category)
    row = {
        "name": name,
        "category": category,
        "start_date": start,
        "end_date": None,
        "color": chosen_color,
        "notes": notes,
    }
    if dry_run:
        return {"action": "dry-run", "row": row}

    conn = _open_health_db()
    try:
        _require_v03_schema(conn)
        cur = conn.execute(
            "INSERT INTO tracking_phases "
            "(name, category, start_date, end_date, color, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (row["name"], row["category"], row["start_date"],
             row["end_date"], row["color"], row["notes"]),
        )
        conn.commit()
        return {"action": "inserted", "id": cur.lastrowid, "row": row}
    finally:
        conn.close()


def end_phase(
    *,
    name: str,
    end_date: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Close the most-recently-started OPEN phase whose name matches `name`.

    Returns {"action": "closed", "row": <phase>} on success, or
    {"action": "no-match"} if there's no open phase by that name.
    """
    end = end_date or date_cls.today().isoformat()
    conn = _open_health_db()
    try:
        _require_v03_schema(conn)
        match = conn.execute("""
            SELECT id, name, category, start_date, end_date, color
            FROM tracking_phases
            WHERE name = ? AND end_date IS NULL
            ORDER BY start_date DESC
            LIMIT 1
        """, (name,)).fetchone()
        if match is None:
            return {"action": "no-match", "name": name}
        row_dict = {k: match[k] for k in match.keys()}
        row_dict["end_date"] = end
        if dry_run:
            return {"action": "dry-run", "row": row_dict}
        conn.execute(
            "UPDATE tracking_phases SET end_date = ? WHERE id = ?",
            (end, match["id"]),
        )
        conn.commit()
        return {"action": "closed", "row": row_dict}
    finally:
        conn.close()


def list_phases(*, only_open: bool = False) -> list[dict[str, Any]]:
    conn = _open_health_db()
    try:
        _require_v03_schema(conn)
        where = "WHERE end_date IS NULL" if only_open else ""
        rows = conn.execute(f"""
            SELECT id, name, category, start_date, end_date, color, notes
            FROM tracking_phases
            {where}
            ORDER BY start_date DESC
        """).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]
    finally:
        conn.close()
