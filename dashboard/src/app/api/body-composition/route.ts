import { NextResponse } from 'next/server';
import Database from 'better-sqlite3';
import { HEALTH_DB } from '@/lib/paths';

export const dynamic = 'force-dynamic';

type CompEntry = {
  id: number;
  date: string;
  method: string | null;
  body_fat_pct: number | null;
  weight_kg: number | null;
  lean_mass_kg: number | null;
  fat_mass_kg: number | null;
  chest_mm: number | null;
  abdominal_mm: number | null;
  thigh_mm: number | null;
  tricep_mm: number | null;
  subscapular_mm: number | null;
  suprailiac_mm: number | null;
  midaxillary_mm: number | null;
};

type TaggedCompEntry = CompEntry & {
  active_phases: string[];   // names of phases active on this row's date
};

type TrackingPhase = {
  id: number;
  name: string;
  category: string | null;
  start_date: string;
  end_date: string | null;     // NULL = currently active
  color: string | null;
  notes: string | null;
};

type WeightPoint = { day: string; kg: number };
type IntakePoint = { day: string; kcal: number; p: number; c: number; f: number };

type PhaseStats = {
  id: number;
  name: string;
  category: string | null;
  color: string | null;
  start: string;
  end: string;                  // resolved to `today` if end_date is NULL
  days: number;
  weight_start: number | null;
  weight_end: number | null;
  weight_delta: number | null;
  weight_delta_per_week: number | null;
  avg_kcal: number | null;
  avg_protein: number | null;
  avg_carbs: number | null;
  avg_fat: number | null;
  recovery: number | null;       // mean across `daily_metrics` (any source)
  hrv: number | null;
  rhr: number | null;
  lean_mass_change: number | null;
  bf_change: number | null;
};

let cache: { data: unknown; ts: number } | null = null;
const IS_DEV = process.env.NODE_ENV !== 'production';

export async function GET() {
  try {
    const now = Date.now();
    // 10-minute response cache in prod (cheap re-fetch in dev so changes
    // to body_composition / tracking_phases show up immediately).
    if (!IS_DEV && cache && now - cache.ts < 600_000) {
      return NextResponse.json(cache.data);
    }
    const db = new Database(HEALTH_DB, { readonly: true });

    // ─── 1. Body composition entries (caliper + scale + Apple Health) ──────
    const entries = db.prepare(`
      SELECT id, date, method, body_fat_pct, weight_kg, lean_mass_kg, fat_mass_kg,
             chest_mm, abdominal_mm, thigh_mm, tricep_mm,
             subscapular_mm, suprailiac_mm, midaxillary_mm
      FROM body_composition ORDER BY date
    `).all() as CompEntry[];

    // ─── 2. Tracking phases (user-defined; bulks / cuts / supplement cycles / …) ─
    const tracking_phases = db.prepare(`
      SELECT id, name, category, start_date, end_date, color, notes
      FROM tracking_phases ORDER BY start_date
    `).all() as TrackingPhase[];

    const today = new Date().toISOString().slice(0, 10);

    // Tag each body-comp entry with the phases active on its date.
    const taggedEntries: TaggedCompEntry[] = entries.map(c => {
      const active = tracking_phases.filter(p => {
        const end = p.end_date ?? today;
        return c.date >= p.start_date && c.date <= end;
      });
      return { ...c, active_phases: active.map(p => p.name) };
    });

    // ─── 3. Weight series from body_composition (Apple Health adapter writes
    //        per-day scale weight here; caliper rows also carry weight_kg).
    const weights = db.prepare(`
      SELECT date AS day, ROUND(weight_kg, 2) AS kg
      FROM body_composition
      WHERE weight_kg IS NOT NULL
      ORDER BY date
    `).all() as WeightPoint[];

    // ─── 4. Daily intake from nutrition_logs.
    //   Filter out implausible days (likely partial logging) — same threshold the
    //   VPS used. Keep 500 < kcal < 6000.
    const intake = db.prepare(`
      SELECT log_date AS day,
             ROUND(SUM(calories), 0)  AS kcal,
             ROUND(SUM(protein_g), 0) AS p,
             ROUND(SUM(carbs_g),   0) AS c,
             ROUND(SUM(fat_g),     0) AS f
      FROM nutrition_logs
      GROUP BY log_date
      HAVING kcal > 500 AND kcal < 6000
      ORDER BY day
    `).all() as IntakePoint[];

    // ─── 5. Per-phase aggregates: weight delta, avg macros, avg WHOOP/Oura/etc.
    //        metrics (any source, from daily_metrics — was WHOOP-only on the VPS).
    const recoveryStmt = db.prepare(`
      SELECT ROUND(AVG(recovery_score), 1) AS r,
             ROUND(AVG(hrv_ms),         1) AS h,
             ROUND(AVG(resting_hr),     1) AS rhr
      FROM daily_metrics
      WHERE date BETWEEN ? AND ?
    `);

    const avg = (arr: number[]): number | null =>
      arr.length > 0 ? +(arr.reduce((s, x) => s + x, 0) / arr.length).toFixed(0) : null;

    const phases: PhaseStats[] = tracking_phases.map(p => {
      const start = p.start_date;
      const end = p.end_date ?? today;

      const ws = weights.find(w => w.day >= start && w.day <= end);
      const we = [...weights].reverse().find(w => w.day <= end && w.day >= start);
      const weight_start = ws ? ws.kg : null;
      const weight_end = we ? we.kg : null;
      const weight_delta = (weight_start !== null && weight_end !== null)
        ? +(weight_end - weight_start).toFixed(2) : null;

      const dayMs = 1000 * 86400;
      const phaseDays = (ws && we && ws.day !== we.day)
        ? Math.max(1, (new Date(we.day).getTime() - new Date(ws.day).getTime()) / dayMs)
        : Math.max(1, (new Date(end).getTime() - new Date(start).getTime()) / dayMs);
      const weight_delta_per_week = weight_delta !== null
        ? +(weight_delta / (phaseDays / 7)).toFixed(2) : null;

      const phaseIntake = intake.filter(i => i.day >= start && i.day <= end);
      const avg_kcal    = avg(phaseIntake.map(i => i.kcal));
      const avg_protein = avg(phaseIntake.map(i => i.p));
      const avg_carbs   = avg(phaseIntake.map(i => i.c));
      const avg_fat     = avg(phaseIntake.map(i => i.f));

      const rec = recoveryStmt.get(start, end) as {
        r: number | null; h: number | null; rhr: number | null;
      };

      const cs = entries.find(c => c.date >= start && c.date <= end);
      const ce = [...entries].reverse().find(c => c.date <= end && c.date >= start);
      const lean_mass_change = (cs && ce && cs.lean_mass_kg !== null && ce.lean_mass_kg !== null)
        ? +(ce.lean_mass_kg - cs.lean_mass_kg).toFixed(2) : null;
      const bf_change = (cs && ce && cs.body_fat_pct !== null && ce.body_fat_pct !== null)
        ? +(ce.body_fat_pct - cs.body_fat_pct).toFixed(2) : null;

      return {
        id: p.id,
        name: p.name,
        category: p.category,
        color: p.color,
        start, end,
        days: Math.round(phaseDays),
        weight_start, weight_end, weight_delta, weight_delta_per_week,
        avg_kcal, avg_protein, avg_carbs, avg_fat,
        recovery: rec?.r ?? null,
        hrv: rec?.h ?? null,
        rhr: rec?.rhr ?? null,
        lean_mass_change, bf_change,
      };
    });

    // ─── 6. Insights ───────────────────────────────────────────────────────
    const peakLean = taggedEntries.reduce<TaggedCompEntry | null>(
      (best, c) =>
        c.lean_mass_kg !== null
        && (best === null || (best.lean_mass_kg ?? -Infinity) < c.lean_mass_kg)
          ? c : best,
      null,
    );
    const lowestBF = taggedEntries.reduce<TaggedCompEntry | null>(
      (best, c) =>
        c.body_fat_pct !== null
        && (best === null || (best.body_fat_pct ?? Infinity) > c.body_fat_pct)
          ? c : best,
      null,
    );
    const lastMeasurement = taggedEntries[taggedEntries.length - 1] ?? null;
    const weight_all_time_low = weights.reduce<number | null>(
      (m, w) => m === null || w.kg < m ? w.kg : m, null,
    );
    const weight_all_time_high = weights.reduce<number | null>(
      (m, w) => m === null || w.kg > m ? w.kg : m, null,
    );

    db.close();

    const data = {
      entries: taggedEntries,
      tracking_phases,
      weights,
      intake,
      phases,
      insights: {
        peak_lean: peakLean,
        lowest_bf: lowestBF,
        last_measurement: lastMeasurement,
        weight_all_time_low,
        weight_all_time_high,
        weight_current: weights[weights.length - 1]?.kg ?? null,
      },
      computed_at: new Date().toISOString(),
    };

    cache = { data, ts: now };
    return NextResponse.json(data);
  } catch (e: unknown) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
