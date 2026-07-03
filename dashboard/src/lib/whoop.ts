import Database from 'better-sqlite3';
import fs from 'fs';
import { WHOOP_DB, HEALTH_DB as MC_DB } from '@/lib/paths';

// ─── Types ───────────────────────────────────────────────────────

interface RecoveryRow {
  cycle_id: number;
  created_at: string;
  score_state: string;
  recovery_score: number | null;
  resting_heart_rate: number | null;
  hrv_rmssd_milli: number | null;
  spo2_percentage: number | null;
  skin_temp_celsius: number | null;
}

interface SleepRow {
  id: string;
  created_at: string;
  start_time?: string | null;
  end_time?: string | null;
  nap: number;
  sleep_performance_percentage: number | null;
  sleep_efficiency_percentage: number | null;
  sleep_consistency_percentage?: number | null;
  total_in_bed_time_milli: number | null;
  total_rem_sleep_time_milli: number | null;
  total_slow_wave_sleep_time_milli: number | null;
  total_light_sleep_time_milli: number | null;
  total_awake_time_milli: number | null;
  baseline_milli?: number | null;
  need_from_sleep_debt_milli?: number | null;
  need_from_recent_strain_milli?: number | null;
  need_from_recent_nap_milli?: number | null;
  respiratory_rate?: number | null;
  sleep_cycle_count?: number | null;
  disturbance_count?: number | null;
}

interface WorkoutRow {
  id: string;
  created_at: string;
  start_time?: string | null;
  end_time?: string | null;
  sport_name: string;
  strain: number | null;
  average_heart_rate: number | null;
  max_heart_rate: number | null;
  kilojoule: number | null;
  distance_meter?: number | null;
  altitude_gain_meter?: number | null;
  zone_zero_milli?: number | null;
  zone_one_milli?: number | null;
  zone_two_milli?: number | null;
  zone_three_milli?: number | null;
  zone_four_milli?: number | null;
  zone_five_milli?: number | null;
}

export interface CycleRow {
  id: number;
  created_at: string;
  start_time: string | null;
  end_time: string | null;
  strain: number | null;
  kilojoule: number | null;
  average_heart_rate: number | null;
  max_heart_rate: number | null;
}

export interface DailyRow {
  date: string;
  recovery_score: number | null;
  hrv_ms: number | null;
  resting_hr: number | null;
  spo2: number | null;
  skin_temp_c: number | null;
  sleep_performance: number | null;
  sleep_hours: number | null;
  sleep_efficiency: number | null;
  rem_hours: number | null;
  deep_sleep_hours: number | null;
  light_sleep_hours: number | null;
  day_strain: number | null;
  calories_burned: number | null;
  // Enriched (joined from raw DB)
  awake_hours?: number | null;
  sleep_consistency?: number | null;
  respiratory_rate?: number | null;
  sleep_cycle_count?: number | null;
  disturbance_count?: number | null;
  sleep_baseline_hours?: number | null;
  sleep_debt_hours?: number | null;
  sleep_strain_need_hours?: number | null;
  bedtime?: string | null;
  waketime?: string | null;
}

export interface BloodPanel {
  id: number;
  panel_date: string;
  lab_name: string | null;
  notes: string | null;
  source_filename: string | null;
  created_at: number;
  markers: BloodMarker[];
}

export interface BloodMarker {
  id: number;
  panel_id: number;
  marker_name: string;
  value: number | null;
  unit: string | null;
  ref_low: number | null;
  ref_high: number | null;
  status: string;
}

export interface Supplement {
  id: number;
  name: string;
  active_ingredient: string | null;
  brand: string | null;
  dose_mg: number | null;
  dose_unit: string;
  form: string | null;
  amazon_asin: string | null;
  default_lag_hours: number;
  notes: string | null;
  created_at: number;
  last_taken_at?: string | null;
  total_logs?: number;
}

export interface SupplementLog {
  id: number;
  supplement_id: number;
  taken_at: string;
  dose_mg: number | null;
  dose_unit: string | null;
  notes: string | null;
  source: string;
  intake_start: string | null;
  intake_end: string | null;
  duration_days: number | null;
  is_period: number;
  amazon_order_id: string | null;
  created_at: number;
  supplement_name?: string;
}

export interface SupplementCorrelation {
  name: string;
  lag_hours: number;
  correlation_recovery: number;
  correlation_hrv: number | null;
  strength: string;
  direction: string;
  avg_recovery_with: number;
  avg_recovery_without: number;
  recovery_delta: number;
  data_points: number;
  total_days: number;
  ci_low: number | null;
  ci_high: number | null;
  significant: boolean;
  adjusted: boolean;  // true = partial correlation (sleep+strain controlled)
}

export interface SupplementsData {
  supplements: Supplement[];
  recent_logs: (SupplementLog & { supplement_name: string })[];
}

export interface WhoopData {
  profile: { first_name: string; last_name: string; email: string; height_meter: number; weight_kilogram: number; max_heart_rate: number } | null;
  recovery: RecoveryRow[];
  sleep: SleepRow[];
  workouts: WorkoutRow[];
  cycles: CycleRow[];
  daily: DailyRow[];
  bloodPanels: BloodPanel[];
  stats: {
    avgRecovery: number | null;
    avgHRV: number | null;
    avgRestingHR: number | null;
    avgSleepPerformance: number | null;
    avgSleepHours: number | null;
    avgDayStrain: number | null;
    totalWorkouts: number;
    totalDays: number;
    dateRange: { from: string; to: string } | null;
  };
}

function openDb(path: string, readonly = true): Database.Database | null {
  if (!fs.existsSync(path)) return null;
  try {
    return new Database(path, { readonly });
  } catch (e) {
    console.error(`[whoop] Failed to open ${path}:`, e);
    return null;
  }
}

export function getWhoopData(): WhoopData {
  const empty: WhoopData = {
    profile: null, recovery: [], sleep: [], workouts: [], cycles: [], daily: [], bloodPanels: [],
    stats: { avgRecovery: null, avgHRV: null, avgRestingHR: null, avgSleepPerformance: null, avgSleepHours: null, avgDayStrain: null, totalWorkouts: 0, totalDays: 0, dateRange: null },
  };

  // ─── Raw Whoop API DB (recovery, sleep, workouts, cycles) ───
  const whoopDb = openDb(WHOOP_DB);
  let recovery: RecoveryRow[] = [];
  let sleep: SleepRow[] = [];
  let workouts: WorkoutRow[] = [];
  let cycles: CycleRow[] = [];
  let profile: WhoopData['profile'] = null;

  // Maps for enriching DailyRow
  const sleepByDate = new Map<string, SleepRow>();
  const cyclesByDate = new Map<string, CycleRow>();

  if (whoopDb) {
    try {
      const p = whoopDb.prepare('SELECT * FROM user_profile LIMIT 1').get() as any;
      const b = whoopDb.prepare('SELECT * FROM body_measurements LIMIT 1').get() as any;
      if (p && b) {
        profile = { first_name: p.first_name, last_name: p.last_name, email: p.email, height_meter: b.height_meter, weight_kilogram: b.weight_kilogram, max_heart_rate: b.max_heart_rate };
      }

      // Pull more recovery columns
      recovery = whoopDb.prepare(`
        SELECT cycle_id, created_at, score_state, recovery_score, resting_heart_rate, hrv_rmssd_milli, spo2_percentage, skin_temp_celsius
        FROM recovery_data WHERE score_state = 'SCORED' ORDER BY created_at DESC LIMIT 180
      `).all() as RecoveryRow[];

      // Detect column names
      const sleepCols = (whoopDb.prepare("PRAGMA table_info(sleep_data)").all() as any[]).map(c => c.name);
      const sleepFields: string[] = ['id', 'created_at', 'nap', 'score_state'];
      const sleepOptional = [
        'start_time', 'end_time',
        'sleep_performance_percentage', 'sleep_efficiency_percentage', 'sleep_consistency_percentage',
        'total_in_bed_time_milli', 'total_rem_sleep_time_milli', 'total_slow_wave_sleep_time_milli',
        'total_light_sleep_time_milli', 'total_awake_time_milli',
        'baseline_milli', 'need_from_sleep_debt_milli', 'need_from_recent_strain_milli', 'need_from_recent_nap_milli',
        'respiratory_rate', 'sleep_cycle_count', 'disturbance_count',
      ];
      sleepOptional.forEach(c => { if (sleepCols.includes(c)) sleepFields.push(c); });
      sleep = whoopDb.prepare(
        `SELECT ${sleepFields.join(', ')} FROM sleep_data WHERE score_state = 'SCORED' AND nap = 0 ORDER BY created_at DESC LIMIT 180`
      ).all() as SleepRow[];

      const workoutCols = (whoopDb.prepare("PRAGMA table_info(workout_data)").all() as any[]).map(c => c.name);
      const wFields: string[] = ['id', 'created_at', 'sport_name', 'score_state'];
      const wOptional = [
        'start_time', 'end_time',
        'strain', 'average_heart_rate', 'max_heart_rate', 'kilojoule', 'distance_meter', 'altitude_gain_meter',
        'zone_zero_milli', 'zone_one_milli', 'zone_two_milli', 'zone_three_milli', 'zone_four_milli', 'zone_five_milli',
      ];
      wOptional.forEach(c => { if (workoutCols.includes(c)) wFields.push(c); });
      workouts = whoopDb.prepare(`SELECT ${wFields.join(', ')} FROM workout_data ORDER BY created_at DESC LIMIT 180`).all() as WorkoutRow[];

      // Cycles (day strain comes from here)
      cycles = whoopDb.prepare(`
        SELECT id, created_at, start_time, end_time, strain, kilojoule, average_heart_rate, max_heart_rate
        FROM cycles_data WHERE score_state = 'SCORED' ORDER BY created_at DESC LIMIT 180
      `).all() as CycleRow[];

      // Build date-keyed maps for daily enrichment.
      // Sleep is keyed by end_time's date (when user woke up = which calendar day).
      for (const s of sleep) {
        const dateKey = (s.end_time ?? s.created_at ?? '').slice(0, 10);
        if (dateKey && !sleepByDate.has(dateKey)) sleepByDate.set(dateKey, s);
      }
      // Cycles keyed by start_time's date (= the actual day)
      for (const c of cycles) {
        const dateKey = (c.start_time ?? c.created_at ?? '').slice(0, 10);
        if (dateKey && !cyclesByDate.has(dateKey)) cyclesByDate.set(dateKey, c);
      }

      whoopDb.close();
    } catch (e) {
      console.error('[whoop] Error reading whoop DB:', e);
      try { whoopDb.close(); } catch {}
    }
  }

  // ─── Mission Control DB (daily aggregates, blood panels) ───
  let daily: DailyRow[] = [];
  let bloodPanels: BloodPanel[] = [];
  const mcDb = openDb(MC_DB);

  if (mcDb) {
    try {
      const tables = (mcDb.prepare("SELECT name FROM sqlite_master WHERE type='table'").all() as any[]).map(t => t.name);

      if (tables.includes('daily_metrics')) {
        // daily_metrics is source-agnostic and can hold MORE THAN ONE row per
        // date (e.g. a WHOOP row + an Apple Health row for the same day). The
        // charts assume one row per date, so merge here: WHOOP first, then fill
        // any remaining nulls from the other sources. Without this, overlapping
        // dates produce duplicate points with null sleep metrics — gaps in the
        // Sleep Performance bars and a broken Sleep Efficiency line.
        const rows = mcDb.prepare(
          "SELECT * FROM daily_metrics ORDER BY date DESC, (source = 'whoop') DESC"
        ).all() as DailyRow[];
        const byDate = new Map<string, DailyRow>();
        for (const r of rows) {
          const existing = byDate.get(r.date);
          if (!existing) { byDate.set(r.date, { ...r }); continue; }
          const dst = existing as unknown as Record<string, unknown>;
          const srcRow = r as unknown as Record<string, unknown>;
          for (const k of Object.keys(srcRow)) {
            if (dst[k] == null && srcRow[k] != null) dst[k] = srcRow[k];
          }
        }
        daily = Array.from(byDate.values());
      }

      if (tables.includes('blood_panels')) {
        const panels = mcDb.prepare('SELECT id, panel_date, lab_name, notes, source_filename, created_at FROM blood_panels ORDER BY panel_date DESC').all() as any[];
        const hasMarkers = tables.includes('blood_markers');
        bloodPanels = panels.map(p => ({
          ...p,
          markers: hasMarkers ? mcDb.prepare('SELECT * FROM blood_markers WHERE panel_id = ? ORDER BY marker_name').all(p.id) as BloodMarker[] : [],
        }));
      }

      mcDb.close();
    } catch (e) {
      console.error('[whoop] Error reading MC DB:', e);
      try { mcDb.close(); } catch {}
    }
  }

  // ─── Enrich daily rows with raw-DB fields ───────
  for (const d of daily) {
    const s = sleepByDate.get(d.date);
    if (s) {
      d.awake_hours = s.total_awake_time_milli != null ? s.total_awake_time_milli / 3600000 : null;
      d.sleep_consistency = s.sleep_consistency_percentage ?? null;
      d.respiratory_rate = s.respiratory_rate ?? null;
      d.sleep_cycle_count = s.sleep_cycle_count ?? null;
      d.disturbance_count = s.disturbance_count ?? null;
      d.sleep_baseline_hours = s.baseline_milli != null ? s.baseline_milli / 3600000 : null;
      d.sleep_debt_hours = s.need_from_sleep_debt_milli != null ? s.need_from_sleep_debt_milli / 3600000 : null;
      d.sleep_strain_need_hours = s.need_from_recent_strain_milli != null ? s.need_from_recent_strain_milli / 3600000 : null;
      d.bedtime = s.start_time ?? null;
      d.waketime = s.end_time ?? null;
    }
    const c = cyclesByDate.get(d.date);
    if (c && c.strain != null && (d.day_strain == null || d.day_strain < 0.1)) {
      d.day_strain = c.strain;
    }
  }

  // ─── Compute stats from daily data (larger dataset) ───
  const source = daily.length > 0 ? daily : [];
  const scored = source.filter(d => d.recovery_score != null);
  const avgRecovery = scored.length ? Math.round(scored.reduce((s, d) => s + d.recovery_score!, 0) / scored.length) : (recovery.length ? Math.round(recovery.filter(r => r.recovery_score != null).reduce((s, r) => s + r.recovery_score!, 0) / recovery.filter(r => r.recovery_score != null).length) : null);

  const hrvData = source.filter(d => d.hrv_ms != null);
  const avgHRV = hrvData.length ? Math.round(hrvData.reduce((s, d) => s + d.hrv_ms!, 0) / hrvData.length * 10) / 10 : null;

  const hrData = source.filter(d => d.resting_hr != null);
  const avgRestingHR = hrData.length ? Math.round(hrData.reduce((s, d) => s + d.resting_hr!, 0) / hrData.length) : null;

  const sleepPerf = source.filter(d => d.sleep_performance != null);
  const avgSleepPerformance = sleepPerf.length ? Math.round(sleepPerf.reduce((s, d) => s + d.sleep_performance!, 0) / sleepPerf.length) : null;

  const sleepH = source.filter(d => d.sleep_hours != null);
  const avgSleepHours = sleepH.length ? Math.round(sleepH.reduce((s, d) => s + d.sleep_hours!, 0) / sleepH.length * 10) / 10 : null;

  const strainData = source.filter(d => d.day_strain != null && d.day_strain > 0);
  const avgDayStrain = strainData.length ? Math.round(strainData.reduce((s, d) => s + d.day_strain!, 0) / strainData.length * 10) / 10 : null;

  const dates = source.map(d => d.date).sort();
  const dateRange = dates.length ? { from: dates[0], to: dates[dates.length - 1] } : null;

  return {
    profile,
    recovery,
    sleep,
    workouts,
    cycles,
    daily,
    bloodPanels,
    stats: {
      avgRecovery,
      avgHRV,
      avgRestingHR,
      avgSleepPerformance,
      avgSleepHours,
      avgDayStrain,
      totalWorkouts: workouts.length,
      totalDays: daily.length,
      dateRange,
    },
  };
}
