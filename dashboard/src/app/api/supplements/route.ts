import { NextRequest, NextResponse } from 'next/server';
import Database from 'better-sqlite3';
import { getLagHours } from '@/lib/supplement-lags';
import { HEALTH_DB as MC_DB } from '@/lib/paths';

export const dynamic = 'force-dynamic';

function openDb(readonly = false) {
  return new Database(MC_DB, { readonly });
}

// ─── GET: list supplements + recent logs ───────────────────────────────────
export async function GET() {
  try {
    const db = openDb(true);
    const tables = (db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all() as { name: string }[]).map(t => t.name);

    if (!tables.includes('supplements')) {
      db.close();
      return NextResponse.json({ supplements: [], recent_logs: [] });
    }

    const supplements = db.prepare(`
      SELECT s.*,
        (SELECT taken_at FROM supplement_log WHERE supplement_id = s.id ORDER BY taken_at DESC LIMIT 1) AS last_taken_at,
        (SELECT COUNT(*) FROM supplement_log WHERE supplement_id = s.id) AS total_logs
      FROM supplements s
      ORDER BY s.name ASC
    `).all();

    const recent_logs = tables.includes('supplement_log') ? db.prepare(`
      SELECT sl.*, s.name AS supplement_name
      FROM supplement_log sl
      JOIN supplements s ON s.id = sl.supplement_id
      WHERE sl.is_period = 0
      ORDER BY sl.taken_at DESC
      LIMIT 30
    `).all() : [];

    db.close();
    return NextResponse.json({ supplements, recent_logs });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}

// ─── POST: add_supplement | log_intake | suggest | log_period ─────────────
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { action } = body;

    if (action === 'suggest') {
      const { name } = body as { name: string };
      const lagHours = getLagHours(name);

      const suggestion = await callClaudeForSuggestion(name, lagHours);
      return NextResponse.json(suggestion);
    }

    if (action === 'add_supplement') {
      const {
        name, active_ingredient = null, brand = null,
        dose_mg = null, dose_unit = 'mg', form = null,
        amazon_asin = null, default_lag_hours = null, notes = null,
      } = body;

      if (!name) return NextResponse.json({ error: 'name required' }, { status: 400 });

      const lag = default_lag_hours ?? getLagHours(name);
      const db = openDb();

      const existing = db.prepare('SELECT id FROM supplements WHERE name = ? LIMIT 1').get(name) as { id: number } | undefined;
      if (existing) {
        db.close();
        return NextResponse.json({ ok: true, id: existing.id, existed: true });
      }

      const result = db.prepare(
        `INSERT INTO supplements (name, active_ingredient, brand, dose_mg, dose_unit, form, amazon_asin, default_lag_hours, notes)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
      ).run(name, active_ingredient, brand, dose_mg, dose_unit, form, amazon_asin, lag, notes);

      db.close();
      return NextResponse.json({ ok: true, id: Number(result.lastInsertRowid) });
    }

    if (action === 'log_intake') {
      const {
        supplement_id, taken_at, dose_mg = null, dose_unit = null,
        notes = null, source = 'manual',
      } = body;

      if (!supplement_id || !taken_at) {
        return NextResponse.json({ error: 'supplement_id and taken_at required' }, { status: 400 });
      }

      const db = openDb();
      const result = db.prepare(
        `INSERT INTO supplement_log (supplement_id, taken_at, dose_mg, dose_unit, notes, source, is_period)
         VALUES (?, ?, ?, ?, ?, ?, 0)`
      ).run(supplement_id, taken_at, dose_mg, dose_unit, notes, source);

      db.close();
      return NextResponse.json({ ok: true, id: Number(result.lastInsertRowid) });
    }

    if (action === 'log_period') {
      // Insert period-based intake (from Amazon import)
      const {
        supplement_id, intake_start, intake_end, duration_days,
        dose_mg = null, dose_unit = null, source = 'amazon_csv',
        amazon_order_id = null, notes = null,
      } = body;

      if (!supplement_id || !intake_start || !intake_end) {
        return NextResponse.json({ error: 'supplement_id, intake_start, intake_end required' }, { status: 400 });
      }

      const db = openDb();

      // Deduplicate: skip if same supplement + overlapping period already exists
      const overlap = db.prepare(`
        SELECT id FROM supplement_log
        WHERE supplement_id = ? AND is_period = 1
          AND intake_start = ? AND source LIKE 'amazon%'
        LIMIT 1
      `).get(supplement_id, intake_start);

      if (overlap) {
        db.close();
        return NextResponse.json({ ok: true, skipped: true });
      }

      const result = db.prepare(
        `INSERT INTO supplement_log
           (supplement_id, taken_at, dose_mg, dose_unit, notes, source, intake_start, intake_end, duration_days, is_period, amazon_order_id)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)`
      ).run(supplement_id, intake_start, dose_mg, dose_unit, notes, source, intake_start, intake_end, duration_days, amazon_order_id);

      db.close();
      return NextResponse.json({ ok: true, id: Number(result.lastInsertRowid) });
    }

    return NextResponse.json({ error: 'unknown action' }, { status: 400 });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}

// ─── DELETE: remove supplement ────────────────────────────────────────────
export async function DELETE(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const id = searchParams.get('id');
    if (!id) return NextResponse.json({ error: 'id required' }, { status: 400 });

    const db = openDb();
    db.prepare('DELETE FROM supplements WHERE id = ?').run(Number(id));
    db.close();
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}

// ─── Claude API: suggest dose + lag for a supplement name ─────────────────
async function callClaudeForSuggestion(name: string, defaultLag: number) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return { active_ingredient: null, dose_mg: null, dose_unit: 'mg', default_lag_hours: defaultLag, form: null, evidence: null };
  }

  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 256,
        messages: [{
          role: 'user',
          content: `For the supplement "${name}", provide a JSON object with:
- active_ingredient (string): the main active compound
- dose_mg (number): typical daily dose in the dose_unit
- dose_unit (string): "mg", "mcg", "IU", "g", etc.
- form (string): "capsule", "powder", "tablet", "liquid", "softgel"
- default_lag_hours (number): hours until measurable effect on recovery/HRV
- evidence (string): one sentence explaining the lag time evidence

Respond with ONLY valid JSON, no explanation.`,
        }],
      }),
    });

    if (!res.ok) throw new Error(`Claude API ${res.status}`);
    const data = await res.json();
    const text = data.content?.[0]?.text || '{}';
    const suggestion = JSON.parse(text.match(/\{[\s\S]*\}/)?.[0] || '{}');
    return {
      active_ingredient: suggestion.active_ingredient || null,
      dose_mg: suggestion.dose_mg || null,
      dose_unit: suggestion.dose_unit || 'mg',
      form: suggestion.form || null,
      default_lag_hours: suggestion.default_lag_hours || defaultLag,
      evidence: suggestion.evidence || null,
    };
  } catch {
    return { active_ingredient: null, dose_mg: null, dose_unit: 'mg', default_lag_hours: defaultLag, form: null, evidence: null };
  }
}
