#!/usr/bin/env python3
"""
fix_blood_markers.py
Post-import cleanup for blood_markers table.
Fixes known parser ambiguities: marker names that can refer to different compounds
depending on unit/reference range.

Run after each PDF import via the blood-panel API route.
"""
import sqlite3

from paths import HEALTH_DB

MC_DB = HEALTH_DB


def fix_markers(conn: sqlite3.Connection):
    fixes = 0

    # ─── Testosterone vs Free Testosterone ───────────────────────
    # Total Testosterone: ng/ml, ref ~2.5–8.4  → keep as "Testosterone"
    # Free Testosterone:  ng/l,  ref ~55–233   → rename to "Free Testosterone"
    r = conn.execute("""
        UPDATE blood_markers
        SET marker_name = 'Free Testosterone'
        WHERE marker_name = 'Testosterone'
          AND unit = 'ng/l'
          AND ref_low IS NOT NULL AND ref_low >= 40 AND ref_low <= 80
    """)
    fixes += r.rowcount

    # Reverse: if incorrectly labeled "Free Testosterone" but unit is ng/ml → Total
    r = conn.execute("""
        UPDATE blood_markers
        SET marker_name = 'Testosterone'
        WHERE marker_name = 'Free Testosterone'
          AND unit = 'ng/ml'
          AND ref_low IS NOT NULL AND ref_low <= 5
    """)
    fixes += r.rowcount

    # ─── HbA1c DCCT vs IFCC ──────────────────────────────────────
    # DCCT: % unit, ref ~4.4–5.6
    # IFCC: mmol/mol unit, ref ~22–38
    r = conn.execute("""
        UPDATE blood_markers
        SET marker_name = 'HbA1c (IFCC)'
        WHERE marker_name = 'HbA1c (DCCT)'
          AND unit = 'mmol/mol'
    """)
    fixes += r.rowcount

    r = conn.execute("""
        UPDATE blood_markers
        SET marker_name = 'HbA1c (DCCT)'
        WHERE marker_name = 'HbA1c (IFCC)'
          AND unit = '%'
    """)
    fixes += r.rowcount

    # ─── Remove duplicate panels (same source_filename imported twice) ──
    dup_result = conn.execute("""
        SELECT MIN(id) as keep_id, source_filename, panel_date, COUNT(*) as cnt
        FROM blood_panels
        WHERE source_filename IS NOT NULL
        GROUP BY source_filename, panel_date
        HAVING cnt > 1
    """).fetchall()

    for row in dup_result:
        keep_id = row[0]
        filename = row[1]
        # Delete markers for duplicate panels, then the panels themselves
        conn.execute("""
            DELETE FROM blood_markers WHERE panel_id IN (
                SELECT id FROM blood_panels
                WHERE source_filename = ? AND id != ?
            )
        """, (filename, keep_id))
        conn.execute("""
            DELETE FROM blood_panels
            WHERE source_filename = ? AND id != ?
        """, (filename, keep_id))
        fixes += 1

    return fixes


if __name__ == "__main__":
    if not MC_DB.exists():
        print("DB not found")
        exit(1)
    conn = sqlite3.connect(MC_DB)
    fixes = fix_markers(conn)
    conn.commit()
    conn.close()
    print(f"Fixed {fixes} marker issues")
