import { NextRequest, NextResponse } from 'next/server';
import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import Database from 'better-sqlite3';
import os from 'os';
import { HEALTH_DB as MC_DB, PIPELINE_DIR } from '@/lib/paths';

const PARSER = path.join(PIPELINE_DIR, 'parse_blood_panel.py');

export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();
    const file = formData.get('file') as File | null;
    let panelDate = formData.get('panel_date') as string || new Date().toISOString().slice(0, 10);
    const labName = formData.get('lab_name') as string || null;
    const notes = formData.get('notes') as string || null;

    if (!file) {
      return NextResponse.json({ error: 'No file uploaded' }, { status: 400 });
    }

    // Auto-detect date from filename pattern: *_DDMMYYYY_*
    if (panelDate === new Date().toISOString().slice(0, 10)) {
      const dateMatch = file.name.match(/_(\d{2})(\d{2})(\d{4})_/);
      if (dateMatch) {
        panelDate = `${dateMatch[3]}-${dateMatch[2]}-${dateMatch[1]}`;
      }
    }

    // Save uploaded file temporarily
    const tmpDir = os.tmpdir();
    const tmpPath = path.join(tmpDir, `blood_panel_${Date.now()}.pdf`);
    const buffer = Buffer.from(await file.arrayBuffer());
    fs.writeFileSync(tmpPath, buffer);

    let markers: Array<{
      marker_name: string;
      value: number | null;
      unit: string | null;
      ref_low: number | null;
      ref_high: number | null;
      status: string;
    }> = [];
    let rawTextPreview = '';

    // Always extract raw text first — used for parsing and debug
    let rawText = '';
    try {
      rawText = execSync(
        `python3 -c "from pdfminer.high_level import extract_text; print(extract_text('${tmpPath}'))" 2>/dev/null`,
        { timeout: 30000, encoding: 'utf-8' }
      );
      rawTextPreview = rawText.slice(0, 3000);
      // Save to /tmp for offline debugging
      fs.writeFileSync('/tmp/last_blood_panel_text.txt', rawText);
    } catch {
      try { fs.unlinkSync(tmpPath); } catch {}
      return NextResponse.json({ error: 'Failed to extract text from PDF' }, { status: 422 });
    }

    try {
      const output = execSync(`python3 "${PARSER}" --stdin 2>/dev/null`, {
        input: rawText,
        timeout: 30000,
        encoding: 'utf-8',
      });
      markers = JSON.parse(output);
    } catch (parseErr: unknown) {
      try { fs.unlinkSync(tmpPath); } catch {}
      const msg = parseErr instanceof Error ? parseErr.message : String(parseErr);
      return NextResponse.json({
        error: 'Failed to parse markers',
        detail: msg.slice(0, 500),
        raw_text_preview: rawTextPreview,
      }, { status: 422 });
    }

    // Clean up temp file
    try { fs.unlinkSync(tmpPath); } catch {}

    // Store in database — merge-aware: reuse existing panel for same date
    const db = new Database(MC_DB);

    // Check if a panel for this date already exists
    const existingPanel = db.prepare(
      'SELECT id FROM blood_panels WHERE panel_date = ? ORDER BY id ASC LIMIT 1'
    ).get(panelDate) as { id: number } | undefined;

    let panelId: number | bigint;
    let isNewPanel: boolean;

    if (existingPanel) {
      panelId = existingPanel.id;
      isNewPanel = false;
    } else {
      const result = db.prepare(
        `INSERT INTO blood_panels (panel_date, lab_name, notes, source_filename, created_at)
         VALUES (?, ?, ?, ?, strftime('%s','now') * 1000)`
      ).run(panelDate, labName, notes, file.name);
      panelId = result.lastInsertRowid;
      isNewPanel = true;
    }

    // Find which marker names already exist for this panel
    const existingMarkerNames = new Set(
      (db.prepare('SELECT marker_name FROM blood_markers WHERE panel_id = ?').all(panelId) as { marker_name: string }[])
        .map(r => r.marker_name.toLowerCase())
    );

    const newMarkers = markers.filter(m => !existingMarkerNames.has(m.marker_name.toLowerCase()));
    const skippedMarkers = markers.filter(m => existingMarkerNames.has(m.marker_name.toLowerCase()));

    // Insert only new markers
    const insertMarker = db.prepare(
      `INSERT INTO blood_markers (panel_id, marker_name, value, unit, ref_low, ref_high, status, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%s','now') * 1000)`
    );
    const insertMany = db.transaction((items: typeof newMarkers) => {
      for (const m of items) {
        insertMarker.run(panelId, m.marker_name, m.value, m.unit, m.ref_low, m.ref_high, m.status || 'unknown');
      }
    });
    insertMany(newMarkers);

    // Run post-insert cleanup (fix marker names, deduplicate)
    try {
      execSync(`python3 "${path.join(PIPELINE_DIR, 'fix_blood_markers.py')}" 2>/dev/null`, {
        timeout: 10000, encoding: 'utf-8',
      });
    } catch { /* cleanup is best-effort */ }

    db.close();

    return NextResponse.json({
      panel_id: panelId,
      panel_date: panelDate,
      lab_name: labName,
      filename: file.name,
      is_new_panel: isNewPanel,
      markers_extracted: markers.length,
      markers_inserted: newMarkers.length,
      markers_skipped: skippedMarkers.length,
      new_markers: newMarkers,
      skipped_markers: skippedMarkers.map(m => m.marker_name),
      ...(markers.length === 0 ? { raw_text_preview: rawTextPreview } : {}),
    });
  } catch (e: unknown) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}

// DELETE: wipe all panels (for re-import)
export async function DELETE() {
  try {
    if (!fs.existsSync(MC_DB)) {
      return NextResponse.json({ deleted: 0 });
    }
    const db = new Database(MC_DB);
    const panelCount = (db.prepare('SELECT COUNT(*) as c FROM blood_panels').get() as { c: number }).c;
    db.exec('DELETE FROM blood_markers');
    db.exec('DELETE FROM blood_panels');
    db.close();
    return NextResponse.json({ deleted: panelCount, message: `Wiped ${panelCount} panels and all markers` });
  } catch (e: unknown) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}

// GET: list all panels
export async function GET() {
  try {
    if (!fs.existsSync(MC_DB)) {
      return NextResponse.json({ panels: [] });
    }
    const db = new Database(MC_DB, { readonly: true });
    const panels = db.prepare(
      'SELECT id, panel_date, lab_name, notes, source_filename, created_at FROM blood_panels ORDER BY panel_date DESC'
    ).all() as Array<{ id: number; panel_date: string; lab_name: string | null; notes: string | null; source_filename: string | null; created_at: number }>;

    const markerStmt = db.prepare(
      'SELECT id, panel_id, marker_name, value, unit, ref_low, ref_high, status FROM blood_markers WHERE panel_id = ? ORDER BY marker_name'
    );

    const result = panels.map(p => ({
      ...p,
      markers: markerStmt.all(p.id),
    }));

    db.close();
    return NextResponse.json({ panels: result });
  } catch (e: unknown) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
