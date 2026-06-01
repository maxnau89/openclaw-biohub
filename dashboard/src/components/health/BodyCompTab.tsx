'use client';

import { useEffect, useState } from 'react';
import { GlassCard, CardHeader } from '@/components/cards/GlassCard';
import { Activity, TrendingDown, TrendingUp, Trophy, Calendar, Target, Calculator, AlertTriangle, User } from 'lucide-react';
import { BodyModel3D } from './body-sim/BodyModel3D';
import type { Sex, Skinfolds } from './body-sim/anthropometrics';

type BodyCompEntry = {
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
  active_phases: string[];   // names of tracking_phases active on this row's date
};

type TrackingPhase = {
  id: number;
  name: string;
  category: string | null;
  start_date: string;
  end_date: string | null;
  color: string | null;
  notes: string | null;
};

type Weight = { day: string; kg: number };
type Intake = { day: string; kcal: number; p: number; c: number; f: number };

type Phase = {
  id: number;
  name: string;
  category: string | null;
  color: string | null;
  start: string;
  end: string;
  days: number;
  weight_start: number | null;
  weight_end: number | null;
  weight_delta: number | null;
  weight_delta_per_week: number | null;
  avg_kcal: number | null;
  avg_protein: number | null;
  avg_carbs: number | null;
  avg_fat: number | null;
  recovery: number | null;
  hrv: number | null;
  rhr: number | null;
  lean_mass_change: number | null;
  bf_change: number | null;
};

type ApiData = {
  entries: BodyCompEntry[];
  tracking_phases: TrackingPhase[];
  weights: Weight[];
  intake: Intake[];
  phases: Phase[];
  insights: {
    peak_lean: BodyCompEntry | null;
    lowest_bf: BodyCompEntry | null;
    last_measurement: BodyCompEntry | null;
    weight_all_time_low: number | null;
    weight_all_time_high: number | null;
    weight_current: number | null;
  };
  computed_at: string;
};

// ─── PhaseChip ──────────────────────────────────────────────────────────────
// Replaces v0.2's "natty vs enhanced" star with a generic colored pill
// per tracking phase. `phases` is the full list (for color lookup by name).

function colorForPhase(name: string, phases: TrackingPhase[]): string {
  return phases.find(p => p.name === name)?.color ?? '#6b7280';   // slate-500 default
}

function PhaseChips({ names, phases }: { names: string[]; phases: TrackingPhase[] }) {
  if (!names || names.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap gap-1 ml-1">
      {names.map(n => {
        const c = colorForPhase(n, phases);
        return (
          <span
            key={n}
            className="px-1.5 py-0.5 rounded text-[10px] font-medium border"
            style={{ backgroundColor: `${c}22`, color: c, borderColor: `${c}55` }}
            title={n}
          >
            {n}
          </span>
        );
      })}
    </span>
  );
}

// ─── Charts + tables ────────────────────────────────────────────────────────

function MultiSeriesChart({ data, height = 240 }: {
  data: { weights: Weight[]; entries: BodyCompEntry[]; phases: TrackingPhase[] };
  height?: number;
}) {
  const allDates = data.weights.map(w => w.day);
  if (allDates.length < 2) return null;

  const firstDate = new Date(allDates[0]).getTime();
  const lastDate = new Date(allDates[allDates.length - 1]).getTime();
  const span = lastDate - firstDate || 1;

  const minKg = Math.min(...data.weights.map(w => w.kg)) - 1;
  const maxKg = Math.max(...data.weights.map(w => w.kg)) + 1;
  const kgRange = maxKg - minKg || 1;

  const W = 800;
  const H = height;
  const padL = 50;
  const padR = 50;
  const padT = 20;
  const padB = 30;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const x = (d: string) => padL + ((new Date(d).getTime() - firstDate) / span) * innerW;
  const yKg = (kg: number) => padT + ((maxKg - kg) / kgRange) * innerH;

  const minBF = 5;
  const maxBF = 35;
  const yBF = (bf: number) => padT + ((maxBF - bf) / (maxBF - minBF)) * innerH;

  // 7-point rolling mean for the weight line.
  const rolling: { day: string; kg: number }[] = [];
  for (let i = 0; i < data.weights.length; i++) {
    const start = Math.max(0, i - 3);
    const end = Math.min(data.weights.length, i + 4);
    const window = data.weights.slice(start, end);
    rolling.push({ day: data.weights[i].day, kg: window.reduce((s, w) => s + w.kg, 0) / window.length });
  }

  const weightLine = rolling.map(p => `${x(p.day)},${yKg(p.kg)}`).join(' L ');
  const years = Array.from(new Set(allDates.map(d => d.substring(0, 4))));

  // Entries that have body_fat_pct (caliper / DEXA) — Apple-Health-only rows skipped here.
  const bfEntries = data.entries.filter(c => c.body_fat_pct !== null);

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="overflow-visible">
      {years.map((yr, i) => {
        const yrStart = allDates.find(d => d.startsWith(yr));
        const yrEnd = [...allDates].reverse().find(d => d.startsWith(yr));
        if (!yrStart || !yrEnd) return null;
        const xs = x(yrStart);
        const xe = x(yrEnd);
        return (
          <g key={yr}>
            <rect x={xs} y={padT} width={xe - xs} height={innerH}
                  fill={i % 2 === 0 ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.04)'} />
            <text x={(xs + xe) / 2} y={H - 8} textAnchor="middle" fontSize="11" fill="rgba(255,255,255,0.4)">{yr}</text>
          </g>
        );
      })}

      {[minKg, (minKg + maxKg) / 2, maxKg].map((kg, i) => (
        <g key={`kg-${i}`}>
          <line x1={padL} y1={yKg(kg)} x2={W - padR} y2={yKg(kg)} stroke="rgba(255,255,255,0.05)" strokeDasharray="2,2" />
          <text x={padL - 8} y={yKg(kg) + 4} textAnchor="end" fontSize="10" fill="#a78bfa">{kg.toFixed(0)}</text>
        </g>
      ))}
      <text x={padL - 30} y={padT + innerH / 2} textAnchor="middle" fontSize="10" fill="#a78bfa"
            transform={`rotate(-90 ${padL - 30} ${padT + innerH / 2})`}>kg</text>

      {[10, 20, 30].map(bf => (
        <text key={`bf-${bf}`} x={W - padR + 8} y={yBF(bf) + 4} fontSize="10" fill="#fb923c">{bf}%</text>
      ))}
      <text x={W - padR + 28} y={padT + innerH / 2} textAnchor="middle" fontSize="10" fill="#fb923c"
            transform={`rotate(90 ${W - padR + 28} ${padT + innerH / 2})`}>BF%</text>

      {/* Daily weight dots */}
      {data.weights.map((p, i) => (
        <circle key={`w-${i}`} cx={x(p.day)} cy={yKg(p.kg)} r={1.5} fill="rgba(167,139,250,0.3)" />
      ))}

      {/* 7-day rolling weight line */}
      <path d={`M ${weightLine}`} stroke="#a78bfa" strokeWidth={2} fill="none" />

      {/* Body-fat entries — orange dots; tagged-phase entries get a small
          ring in the phase's first color. */}
      {bfEntries.map((c, i) => {
        const phaseColor = c.active_phases.length > 0
          ? colorForPhase(c.active_phases[0], data.phases)
          : null;
        return (
          <g key={`bf-${i}`}>
            <circle cx={x(c.date)} cy={yBF(c.body_fat_pct!)} r={4} fill="#fb923c" stroke="#fff" strokeWidth={1} />
            {phaseColor && (
              <circle cx={x(c.date)} cy={yBF(c.body_fat_pct!)} r={7} fill="none" stroke={phaseColor} strokeWidth={1.5} />
            )}
            <title>
              {c.date}: {c.body_fat_pct!.toFixed(1)}% BF, Lean: {c.lean_mass_kg ?? '—'} kg
              {c.active_phases.length > 0 ? ` (${c.active_phases.join(', ')})` : ''}
            </title>
          </g>
        );
      })}
      {bfEntries.length > 1 && (
        <path d={`M ${bfEntries.map(c => `${x(c.date)},${yBF(c.body_fat_pct!)}`).join(' L ')}`}
              stroke="rgba(251,146,60,0.4)" strokeWidth={1} fill="none" strokeDasharray="3,3" />
      )}
    </svg>
  );
}

function PhaseTable({ phases }: { phases: Phase[] }) {
  if (phases.length === 0) {
    return (
      <p className="text-xs text-white/40 italic">
        No tracking phases defined yet. Use <code>biohub log-phase start &lt;category&gt; &lt;name&gt;</code> to
        create one — e.g. a cut, bulk, training block, or supplement cycle.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-white/40 border-b border-white/10">
            <th className="text-left py-2 px-1">Phase</th>
            <th className="text-right py-2 px-1">Days</th>
            <th className="text-right py-2 px-1">kg start</th>
            <th className="text-right py-2 px-1">kg end</th>
            <th className="text-right py-2 px-1">Δ kg</th>
            <th className="text-right py-2 px-1">Δ/week</th>
            <th className="text-right py-2 px-1">kcal</th>
            <th className="text-right py-2 px-1">P g</th>
            <th className="text-right py-2 px-1">Lean Δ</th>
            <th className="text-right py-2 px-1">BF% Δ</th>
            <th className="text-right py-2 px-1">Rec %</th>
          </tr>
        </thead>
        <tbody>
          {phases.map((p, i) => (
            <tr key={i} className="border-b border-white/5 hover:bg-white/[0.02]">
              <td className="py-2 px-1 font-medium text-white/90 flex items-center gap-1.5">
                {p.color && (
                  <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
                )}
                {p.name}
              </td>
              <td className="text-right py-2 px-1 text-white/60">{p.days}</td>
              <td className="text-right py-2 px-1 text-white/60">{p.weight_start?.toFixed(1) ?? '—'}</td>
              <td className="text-right py-2 px-1 text-white/60">{p.weight_end?.toFixed(1) ?? '—'}</td>
              <td className={`text-right py-2 px-1 font-medium ${p.weight_delta && p.weight_delta < 0 ? 'text-emerald-400' : p.weight_delta && p.weight_delta > 0 ? 'text-amber-400' : 'text-white/60'}`}>
                {p.weight_delta !== null ? (p.weight_delta > 0 ? '+' : '') + p.weight_delta.toFixed(1) : '—'}
              </td>
              <td className="text-right py-2 px-1 text-white/60">
                {p.weight_delta_per_week !== null ? (p.weight_delta_per_week > 0 ? '+' : '') + p.weight_delta_per_week.toFixed(2) : '—'}
              </td>
              <td className="text-right py-2 px-1 text-white/60">{p.avg_kcal ?? '—'}</td>
              <td className="text-right py-2 px-1 text-white/60">{p.avg_protein ?? '—'}</td>
              <td className={`text-right py-2 px-1 ${p.lean_mass_change && p.lean_mass_change > 0 ? 'text-emerald-400' : p.lean_mass_change && p.lean_mass_change < 0 ? 'text-rose-400' : 'text-white/40'}`}>
                {p.lean_mass_change !== null ? (p.lean_mass_change > 0 ? '+' : '') + p.lean_mass_change.toFixed(1) : '—'}
              </td>
              <td className={`text-right py-2 px-1 ${p.bf_change && p.bf_change < 0 ? 'text-emerald-400' : p.bf_change && p.bf_change > 0 ? 'text-amber-400' : 'text-white/40'}`}>
                {p.bf_change !== null ? (p.bf_change > 0 ? '+' : '') + p.bf_change.toFixed(1) : '—'}
              </td>
              <td className="text-right py-2 px-1 text-white/60">{p.recovery?.toFixed(0) ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── ForwardSim ─────────────────────────────────────────────────────────────
// Generic textbook model: weight change rate ≈ (kcal - TDEE) / 7700 per day.
// `tdee` defaults to weight × 35 (rough multiplier for moderately active
// adults). User overrides via the input. Lean/fat split follows protein
// intake — same biological constants the VPS version used.

function ForwardSim({ data }: { data: ApiData }) {
  const currentWeight = data.insights.weight_current ?? 75;
  const currentBFRaw = data.insights.last_measurement?.body_fat_pct ?? 18;
  const defaultTDEE = Math.round(currentWeight * 35);

  const [kcal, setKcal] = useState(defaultTDEE - 500);
  const [protein, setProtein] = useState(Math.round(currentWeight * 1.8));
  const [tdee, setTdee] = useState(defaultTDEE);
  const [weeks, setWeeks] = useState(8);

  const KCAL_PER_KG = 7700;            // textbook value for body mass change
  const dailyDeficit = kcal - tdee;
  const predictedDailyRate = dailyDeficit / KCAL_PER_KG;
  const totalDays = weeks * 7;
  const predictedWeight = currentWeight + predictedDailyRate * totalDays;
  const totalLoss = predictedWeight - currentWeight;

  const currentLean = currentWeight * (1 - currentBFRaw / 100);
  const proteinPerKg = protein / currentWeight;
  // Higher protein protects lean mass during a deficit.
  // 1.6 g/kg → 60% of loss from fat; 2.5 g/kg → 85% from fat (linear interp).
  const fatLossRatio = Math.min(0.85, 0.6 + (proteinPerKg - 1.0) * 0.18);
  const leanLossRatio = 1 - fatLossRatio;
  const fatLoss = totalLoss * fatLossRatio;
  const leanLoss = totalLoss * leanLossRatio;
  const predictedFatKg = (currentWeight * currentBFRaw / 100) + fatLoss;
  const predictedLeanKg = currentLean + leanLoss;
  const predictedBF = (predictedFatKg / predictedWeight) * 100;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div>
          <label className="text-xs text-white/60">TDEE (maintenance kcal/day): <span className="font-bold text-white">{tdee}</span></label>
          <input type="range" min={1500} max={4500} step={50} value={tdee} onChange={e => setTdee(+e.target.value)}
                 className="w-full mt-1 accent-sky-400" />
        </div>
        <div>
          <label className="text-xs text-white/60">Target kcal/day: <span className="font-bold text-white">{kcal}</span></label>
          <input type="range" min={1200} max={5000} step={50} value={kcal} onChange={e => setKcal(+e.target.value)}
                 className="w-full mt-1 accent-amber-400" />
        </div>
        <div>
          <label className="text-xs text-white/60">Protein g/day: <span className="font-bold text-white">{protein}</span> ({(protein / currentWeight).toFixed(1)}g/kg)</label>
          <input type="range" min={50} max={350} step={5} value={protein} onChange={e => setProtein(+e.target.value)}
                 className="w-full mt-1 accent-emerald-400" />
        </div>
        <div>
          <label className="text-xs text-white/60">Duration: <span className="font-bold text-white">{weeks} weeks</span></label>
          <input type="range" min={1} max={26} step={1} value={weeks} onChange={e => setWeeks(+e.target.value)}
                 className="w-full mt-1 accent-indigo-400" />
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-4 bg-white/[0.03] rounded-lg">
        <div>
          <div className="text-xs text-white/50">Predicted weight</div>
          <div className="text-xl font-bold text-white">{predictedWeight.toFixed(1)} <span className="text-sm text-white/40">kg</span></div>
          <div className={`text-xs ${totalLoss < 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {totalLoss > 0 ? '+' : ''}{totalLoss.toFixed(1)} kg
          </div>
        </div>
        <div>
          <div className="text-xs text-white/50">Predicted BF%</div>
          <div className="text-xl font-bold text-white">{predictedBF.toFixed(1)}<span className="text-sm text-white/40">%</span></div>
          <div className={`text-xs ${predictedBF < currentBFRaw ? 'text-emerald-400' : 'text-rose-400'}`}>
            {(predictedBF - currentBFRaw) > 0 ? '+' : ''}{(predictedBF - currentBFRaw).toFixed(1)}pp
          </div>
        </div>
        <div>
          <div className="text-xs text-white/50">Lean mass</div>
          <div className="text-xl font-bold text-white">{predictedLeanKg.toFixed(1)} <span className="text-sm text-white/40">kg</span></div>
          <div className={`text-xs ${leanLoss > -0.5 ? 'text-emerald-400' : leanLoss > -1.5 ? 'text-amber-400' : 'text-rose-400'}`}>
            {leanLoss > 0 ? '+' : ''}{leanLoss.toFixed(2)} kg
          </div>
        </div>
        <div>
          <div className="text-xs text-white/50">Fat loss</div>
          <div className="text-xl font-bold text-white">{Math.abs(fatLoss).toFixed(1)} <span className="text-sm text-white/40">kg</span></div>
          <div className="text-xs text-white/40">({(fatLossRatio * 100).toFixed(0)}% of total)</div>
        </div>
      </div>

      <div className="text-xs text-white/40 italic">
        Textbook model: ΔWeight/day ≈ (intake − TDEE) / 7700 kcal/kg.
        Lean-vs-fat split scales with protein intake (1.6 g/kg → ~60% fat, 2.5 g/kg → ~85% fat).
        <strong className="text-amber-400/70 ml-1">Rough estimate only. Calibrate TDEE against your own logged data over a few weeks.</strong>
      </div>
    </div>
  );
}

// ─── 3D body simulator ──────────────────────────────────────────────────────

function skinfoldsFromEntry(entry: ApiData['insights']['last_measurement']):
  Skinfolds | undefined {
  if (!entry) return undefined;
  const sites: (keyof Skinfolds)[] = [
    'chest', 'abdominal', 'thigh', 'tricep',
    'subscapular', 'suprailiac', 'midaxillary',
  ];
  const sf: Partial<Skinfolds> = {};
  for (const s of sites) {
    const mm = (entry as unknown as Record<string, number | null>)[`${s}_mm`];
    if (mm == null) return undefined;
    sf[s] = mm;
  }
  return sf as Skinfolds;
}

function SexToggle({ value, onChange }: { value: Sex; onChange: (s: Sex) => void }) {
  const btn = (s: Sex, label: string) => (
    <button
      onClick={() => onChange(s)}
      className={
        'px-3 py-1 text-xs rounded transition ' +
        (value === s
          ? 'bg-white/15 text-white'
          : 'text-white/40 hover:text-white/70')
      }
    >
      {label}
    </button>
  );
  return (
    <div className="flex items-center gap-1 bg-white/5 rounded p-0.5">
      {btn('m', 'Male')}
      {btn('f', 'Female')}
    </div>
  );
}

function BodySimCard({ data }: { data: ApiData }) {
  const last = data.insights.last_measurement;
  const [sex, setSex] = useState<Sex>(() => {
    if (typeof window === 'undefined') return 'm';
    return (window.localStorage.getItem('biohub.bodysim.sex') as Sex) || 'm';
  });
  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('biohub.bodysim.sex', sex);
    }
  }, [sex]);

  if (!last) {
    return (
      <GlassCard>
        <CardHeader title="3D body composition" icon={<User className="w-4 h-4" />} />
        <div className="p-4 pt-2 text-sm text-white/60">
          Log a body-composition entry to see the 3D model.
        </div>
      </GlassCard>
    );
  }

  const weight = last.weight_kg ?? data.insights.weight_current ?? 75;
  const bf = last.body_fat_pct ?? 18;
  const skinfolds = skinfoldsFromEntry(last);
  const heightM = 1.75;  // TODO: read from user profile once we have one
  const captionMethod = last.method ?? 'manual';
  const captionDate = last.date;

  return (
    <GlassCard>
      <CardHeader
        title="3D body composition"
        icon={<User className="w-4 h-4" />}
        badge={<SexToggle value={sex} onChange={setSex} />}
      />
      <div className="p-4 pt-2 space-y-2">
        <BodyModel3D
          weightKg={weight}
          bfPct={bf}
          heightM={heightM}
          sex={sex}
          skinfolds={skinfolds}
          height={480}
        />
        <p className="text-xs text-white/40">
          Current — {weight.toFixed(1)} kg, {bf.toFixed(1)}% BF from {captionDate} ({captionMethod})
          {skinfolds
            ? ' · regional shape driven by 7-site caliper'
            : ' · uniform-distribution fallback (no caliper data)'}
        </p>
      </div>
    </GlassCard>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────

export function BodyCompositionTab() {
  const [data, setData] = useState<ApiData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/body-composition')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(String(e)); setLoading(false); });
  }, []);

  if (loading) return <div className="p-8 text-white/60"><Activity className="animate-pulse w-6 h-6" /></div>;
  if (error || !data) return <div className="p-8 text-rose-400"><AlertTriangle className="w-6 h-6" /> {error}</div>;

  const { insights } = data;
  const taggedCount = data.entries.filter(c => c.active_phases.length > 0).length;
  const hasEntries = data.entries.length > 0;

  if (!hasEntries) {
    return (
      <GlassCard>
        <div className="p-6 text-center text-white/60">
          <Trophy className="w-8 h-8 mx-auto mb-3 text-amber-400/60" />
          <p className="text-sm font-medium text-white/80">No body-composition data yet</p>
          <p className="text-xs text-white/40 mt-2 max-w-md mx-auto">
            Add a measurement via <code className="text-amber-400/80">biohub log-measurement</code>,
            or sync the Apple Health adapter — scale weight readings populate this tab automatically.
          </p>
        </div>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-4">
      {/* Insights header */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <GlassCard>
          <div className="p-3">
            <div className="text-xs text-white/50 mb-1 flex items-center gap-1"><Trophy className="w-3 h-3" /> Lean Mass Peak</div>
            <div className="text-xl font-bold text-emerald-400 flex items-center gap-1 flex-wrap">
              {insights.peak_lean?.lean_mass_kg?.toFixed(1) ?? '—'} kg
              <PhaseChips names={insights.peak_lean?.active_phases ?? []} phases={data.tracking_phases} />
            </div>
            <div className="text-xs text-white/40">
              {insights.peak_lean?.date} · {insights.peak_lean?.weight_kg?.toFixed(1)}kg @ {insights.peak_lean?.body_fat_pct?.toFixed(1)}%
            </div>
          </div>
        </GlassCard>
        <GlassCard>
          <div className="p-3">
            <div className="text-xs text-white/50 mb-1 flex items-center gap-1"><Target className="w-3 h-3" /> BF% Low</div>
            <div className="text-xl font-bold text-orange-400 flex items-center gap-1 flex-wrap">
              {insights.lowest_bf?.body_fat_pct?.toFixed(2) ?? '—'}%
              <PhaseChips names={insights.lowest_bf?.active_phases ?? []} phases={data.tracking_phases} />
            </div>
            <div className="text-xs text-white/40">{insights.lowest_bf?.date}</div>
          </div>
        </GlassCard>
        <GlassCard>
          <div className="p-3">
            <div className="text-xs text-white/50 mb-1 flex items-center gap-1"><Calendar className="w-3 h-3" /> Last measurement</div>
            <div className="text-xl font-bold text-white">{insights.last_measurement?.body_fat_pct?.toFixed(1) ?? '—'}%</div>
            <div className="text-xs text-white/40">
              {insights.last_measurement?.date} · Lean: {insights.last_measurement?.lean_mass_kg?.toFixed(1) ?? '—'} kg
            </div>
          </div>
        </GlassCard>
        <GlassCard>
          <div className="p-3">
            <div className="text-xs text-white/50 mb-1">Current weight</div>
            <div className="text-xl font-bold text-white">{insights.weight_current?.toFixed(1) ?? '—'} kg</div>
            <div className="text-xs text-white/40">
              All-time: {insights.weight_all_time_low?.toFixed(1) ?? '—'} – {insights.weight_all_time_high?.toFixed(1) ?? '—'} kg
            </div>
          </div>
        </GlassCard>
      </div>

      {/* Main chart */}
      <GlassCard>
        <CardHeader title="Weight + body-fat history" icon={<TrendingDown className="w-4 h-4" />} />
        <div className="p-4 pt-2">
          <MultiSeriesChart data={{
            weights: data.weights,
            entries: data.entries,
            phases: data.tracking_phases,
          }} />
          <div className="flex flex-wrap gap-6 mt-3 text-xs text-white/50">
            <div className="flex items-center gap-2"><span className="inline-block w-3 h-0.5 bg-purple-400"></span>Weight (7d rolling mean)</div>
            <div className="flex items-center gap-2"><span className="inline-block w-3 h-3 rounded-full bg-orange-400"></span>Caliper / DEXA BF%</div>
            {taggedCount > 0 && (
              <div className="flex items-center gap-2 text-white/40">
                <span className="inline-block w-3 h-3 rounded-full border-2 border-sky-400"></span>
                = entry tagged with a tracking phase ({taggedCount}/{data.entries.length})
              </div>
            )}
          </div>
        </div>
      </GlassCard>

      {/* Phase comparison */}
      <GlassCard>
        <CardHeader title="Tracking phases" icon={<TrendingUp className="w-4 h-4" />} />
        <div className="p-4 pt-2">
          <PhaseTable phases={data.phases} />
        </div>
      </GlassCard>

      {/* Entry detail */}
      <GlassCard>
        <CardHeader title={`Measurements (${data.entries.length})`} icon={<Target className="w-4 h-4" />} />
        <div className="p-4 pt-2 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-white/40 border-b border-white/10">
                <th className="text-left py-1.5 px-1">Date</th>
                <th className="text-left py-1.5 px-1">Method</th>
                <th className="text-right py-1.5 px-1">BF%</th>
                <th className="text-right py-1.5 px-1">Weight</th>
                <th className="text-right py-1.5 px-1">Lean kg</th>
                <th className="text-right py-1.5 px-1">Fat kg</th>
                <th className="text-right py-1.5 px-1">Σ Skinfolds</th>
              </tr>
            </thead>
            <tbody>
              {data.entries.map((c, i) => {
                const sites = [c.chest_mm, c.abdominal_mm, c.thigh_mm, c.tricep_mm,
                               c.subscapular_mm, c.suprailiac_mm, c.midaxillary_mm];
                const sumMM = sites.every(v => v !== null && v !== undefined)
                  ? sites.reduce((s, v) => s + (v ?? 0), 0)
                  : null;
                return (
                  <tr key={i} className="border-b border-white/5">
                    <td className="py-1.5 px-1 text-white/90">
                      <div className="flex items-center gap-1 flex-wrap">
                        {c.date}
                        <PhaseChips names={c.active_phases} phases={data.tracking_phases} />
                      </div>
                    </td>
                    <td className="py-1.5 px-1 text-white/50">{c.method ?? '—'}</td>
                    <td className="text-right py-1.5 px-1 text-orange-400 font-medium">
                      {c.body_fat_pct !== null ? `${c.body_fat_pct.toFixed(2)}%` : '—'}
                    </td>
                    <td className="text-right py-1.5 px-1 text-white/70">{c.weight_kg?.toFixed(1) ?? '—'}</td>
                    <td className="text-right py-1.5 px-1 text-emerald-400">{c.lean_mass_kg?.toFixed(1) ?? '—'}</td>
                    <td className="text-right py-1.5 px-1 text-white/60">{c.fat_mass_kg?.toFixed(1) ?? '—'}</td>
                    <td className="text-right py-1.5 px-1 text-white/40">{sumMM !== null ? `${sumMM.toFixed(1)} mm` : '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </GlassCard>

      {/* 3D body simulator */}
      <BodySimCard data={data} />

      {/* Forward simulator */}
      <GlassCard>
        <CardHeader title="Forward simulator (diet → body composition)" icon={<Calculator className="w-4 h-4" />} />
        <div className="p-4 pt-2">
          <ForwardSim data={data} />
        </div>
      </GlassCard>

      <p className="text-xs text-white/30 text-center pt-2">
        Last update: {new Date(data.computed_at).toLocaleString()}
      </p>
    </div>
  );
}
