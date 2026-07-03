'use client';

import { Suspense, useState, useRef, useCallback, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useAutoRefresh, apiUrl } from '@/lib/fetcher';
import { TabBar } from '@/components/layout/TabBar';
import { GlassCard, CardHeader } from '@/components/cards/GlassCard';
import { useSearchParams } from 'next/navigation';
import { Heart, Moon, Dumbbell, Activity, Droplets, TrendingUp, User, ExternalLink, Upload, Brain, AlertTriangle, Zap, ChevronDown, ChevronUp, CheckCircle, RefreshCw, Pill, Plus, Trash2, FileUp, Link2, Calendar, Flame, Wind } from 'lucide-react';
import type { WhoopData, Supplement, SupplementLog, SupplementsData, SupplementCorrelation } from '@/lib/whoop';
import { BaselineLineChart } from '@/components/health/BaselineLineChart';
import { StrainGauge } from '@/components/health/StrainGauge';
import { RecoveryDonut } from '@/components/health/RecoveryDonut';
import { SleepStagesDonut } from '@/components/health/SleepStagesDonut';
import { SleepStagesStackedBar } from '@/components/health/SleepStagesStackedBar';
import { HRZoneStackedBar } from '@/components/health/HRZoneStackedBar';
import { ColorBarChart } from '@/components/health/ColorBarChart';
import { RecoveryDistribution } from '@/components/health/RecoveryDistribution';
import { MonthlyDelta } from '@/components/health/MonthlyDelta';
import { WorkoutHeatmap } from '@/components/health/WorkoutHeatmap';
import { SleepNeedBar } from '@/components/health/SleepNeedBar';
import { BodyCompositionTab } from '@/components/health/BodyCompTab';
import { SleepConsistencyHeatmap } from '@/components/health/SleepConsistencyHeatmap';
import { recoveryColor, strainColor, HR_ZONE_COLORS, HR_ZONE_LABELS } from '@/components/health/colors';

const tabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'strain', label: 'Strain' },
  { id: 'trends', label: 'Trends' },
  { id: 'sleep', label: 'Sleep' },
  { id: 'workouts', label: 'Workouts' },
  { id: 'body-comp', label: 'Body Comp' },
  { id: 'bio-age', label: 'Bio Age' },
  { id: 'glucose', label: 'Glucose' },
  { id: 'blood', label: 'Blood Work' },
  { id: 'supplements', label: 'Supplements' },
];

const timeRanges = [
  { id: '7', label: '7d' },
  { id: '14', label: '14d' },
  { id: '30', label: '30d' },
  { id: '90', label: '90d' },
  { id: 'all', label: 'All' },
];

function rc(score: number | null): string {
  if (score == null) return 'text-white/30';
  if (score >= 67) return 'text-emerald-400';
  if (score >= 34) return 'text-amber-400';
  return 'text-red-400';
}
function rbg(score: number | null): string {
  if (score == null) return 'bg-white/[0.04]';
  if (score >= 67) return 'bg-emerald-500/10 border-emerald-500/20';
  if (score >= 34) return 'bg-amber-500/10 border-amber-500/20';
  return 'bg-red-500/10 border-red-500/20';
}
function rbar(score: number): string {
  if (score >= 67) return 'bg-emerald-500';
  if (score >= 34) return 'bg-amber-500';
  return 'bg-red-500';
}
// HRV: higher = better (baseline ~58ms)
function hrvBar(v: number): string {
  if (v >= 70) return 'bg-emerald-500';
  if (v >= 45) return 'bg-amber-500';
  return 'bg-red-500';
}
// RHR: lower = better (baseline ~68bpm)
function rhrBar(v: number): string {
  if (v <= 60) return 'bg-emerald-500';
  if (v <= 70) return 'bg-amber-500';
  return 'bg-red-500';
}
// Sleep hours: ≥7h good, ≥6h ok (baseline ~6.7h)
function sleepBar(v: number): string {
  if (v >= 7) return 'bg-emerald-500';
  if (v >= 6) return 'bg-amber-500';
  return 'bg-red-500';
}
function msH(ms: number | null): string {
  if (ms == null) return '—';
  return `${(ms / 3600000).toFixed(1)}h`;
}
function fd(iso: string): string {
  try { return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: '2-digit' }); } catch { return iso; }
}
function markerStatus(s: string): string {
  if (s === 'normal') return 'text-emerald-400';
  if (s === 'high') return 'text-red-400';
  if (s === 'low') return 'text-amber-400';
  return 'text-white/30';
}

function TimeRangeSelector({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex items-center gap-1 bg-white/[0.03] rounded-lg p-0.5 border border-white/[0.06]">
      {timeRanges.map(r => (
        <button key={r.id} onClick={() => onChange(r.id)}
          className={`px-2.5 py-1 rounded-md text-[10px] font-medium transition-all ${
            value === r.id ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' : 'text-white/30 hover:text-white/50 border border-transparent'
          }`}>{r.label}</button>
      ))}
    </div>
  );
}

function ScaledBarChart({ data, color, colorFn, valueKey, label, unit, days }: {
  data: Record<string, unknown>[];
  color: string;
  colorFn?: (v: number) => string;
  valueKey: string;
  label: string;
  unit: string;
  days: number;
}) {
  const sliced = days === 0 ? [...data].reverse() : [...data.slice(0, days)].reverse();
  const values = sliced.map(d => (d[valueKey] as number) ?? 0).filter(v => v > 0);
  if (values.length === 0) return <div className="text-white/20 text-xs">No data</div>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const scaleMin = Math.floor(min - range * 0.1);
  const scaleMax = Math.ceil(max + range * 0.1);
  const scaleRange = scaleMax - scaleMin || 1;

  return (
    <div>
      <div className="flex items-end gap-[1px] h-28 relative">
        {/* Y-axis labels */}
        <div className="absolute left-0 top-0 bottom-0 w-8 flex flex-col justify-between text-[8px] text-white/15 pointer-events-none z-10">
          <span>{scaleMax}{unit}</span>
          <span>{Math.round((scaleMax + scaleMin) / 2)}{unit}</span>
          <span>{scaleMin}{unit}</span>
        </div>
        <div className="flex items-end gap-[1px] h-full flex-1 ml-9">
          {sliced.map((d, i) => {
            const v = (d[valueKey] as number) ?? 0;
            const pct = v > 0 ? ((v - scaleMin) / scaleRange) * 100 : 0;
            return (
              <div key={String(d.date || i)} className="flex-1 h-full flex flex-col justify-end group relative">
                <div className={`w-full rounded-sm ${colorFn ? colorFn(v) : color} transition-all hover:opacity-80`} style={{ height: `${Math.max(pct, 2)}%` }} />
                <div className="absolute -top-7 left-1/2 -translate-x-1/2 bg-black/90 text-white/80 text-[9px] px-1.5 py-0.5 rounded opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-20">
                  {typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(1)) : v}{unit} · {String(d.date)}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {/* X-axis: first and last date */}
      <div className="flex justify-between ml-9 mt-1 text-[8px] text-white/15">
        <span>{String(sliced[0]?.date || '')}</span>
        <span>{String(sliced[sliced.length - 1]?.date || '')}</span>
      </div>
    </div>
  );
}

interface Insight {
  correlations?: Array<{ metric1: string; metric2: string; correlation: number; strength: string; interpretation: string }>;
  anomalies?: Array<{ date: string; metric: string; interpretation: string; severity?: string; type?: string }>;
  predictions?: Array<{ model: string; type: string; description: string; recommendation: string; r_squared?: number; correlation?: number }>;
  recommendations?: Array<{ type: string; priority: string; title: string; action: string; detail: string }>;
  data_summary?: { days_analyzed: number; date_range?: { from: string; to: string } };
  error?: string;
}

function InsightsPanel({ days }: { days: number }) {
  const { data, loading } = useAutoRefresh<Insight>(`/api/health-insights?days=${days}`, 300000);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ recs: true });

  if (loading && !data) return <GlassCard className="animate-pulse"><div className="h-20 flex items-center justify-center text-white/20 text-xs">Analyzing patterns...</div></GlassCard>;
  if (!data || data.error) return null;

  const recs = data.recommendations || [];
  const correlations = Array.isArray(data.correlations) ? data.correlations.slice(0, 5) : [];
  const anomalies = Array.isArray(data.anomalies) ? data.anomalies.slice(0, 5) : [];

  const priorityIcon = (p: string) => {
    if (p === 'high') return <AlertTriangle size={12} className="text-red-400" />;
    if (p === 'medium') return <Zap size={12} className="text-amber-400" />;
    return <TrendingUp size={12} className="text-emerald-400" />;
  };

  return (
    <div className="space-y-3">
      {recs.length > 0 && (
        <GlassCard>
          <button className="w-full" onClick={() => setExpanded(e => ({ ...e, recs: !e.recs }))}>
            <CardHeader icon={<Brain size={16} className="text-purple-400" />} title="AI Insights & Recommendations" badge={
              <span className="flex items-center gap-1 text-[10px] text-white/20">
                {data.data_summary?.days_analyzed || '?'} days analyzed
                {expanded.recs ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </span>
            } />
          </button>
          {expanded.recs && (
            <div className="mt-3 space-y-2">
              {recs.map((r, i) => (
                <div key={i} className={`flex items-start gap-2.5 p-2.5 rounded-lg border ${
                  r.priority === 'high' ? 'bg-red-500/5 border-red-500/15' :
                  r.priority === 'medium' ? 'bg-amber-500/5 border-amber-500/15' :
                  'bg-emerald-500/5 border-emerald-500/15'
                }`}>
                  {priorityIcon(r.priority)}
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-white/70">{r.title}</div>
                    <div className="text-[11px] text-white/50 mt-0.5">{r.action}</div>
                    <div className="text-[10px] text-white/25 mt-0.5">{r.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      )}

      {correlations.length > 0 && (
        <GlassCard>
          <button className="w-full" onClick={() => setExpanded(e => ({ ...e, corr: !e.corr }))}>
            <CardHeader icon={<TrendingUp size={16} className="text-cyan-400" />} title="Key Correlations" badge={
              <span className="flex items-center gap-1 text-[10px] text-white/20">
                {correlations.length} found
                {expanded.corr ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </span>
            } />
          </button>
          {expanded.corr && (
            <div className="mt-3 space-y-1.5">
              {correlations.map((c, i) => (
                <div key={i} className="flex items-center justify-between px-2.5 py-1.5 rounded bg-white/[0.02]">
                  <span className="text-[11px] text-white/50 flex-1">{c.interpretation}</span>
                  <span className={`text-[10px] font-mono ml-2 ${Math.abs(c.correlation) > 0.6 ? 'text-cyan-400' : 'text-white/30'}`}>
                    r={c.correlation > 0 ? '+' : ''}{c.correlation}
                  </span>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      )}

      {anomalies.length > 0 && (
        <GlassCard>
          <button className="w-full" onClick={() => setExpanded(e => ({ ...e, anom: !e.anom }))}>
            <CardHeader icon={<AlertTriangle size={16} className="text-amber-400" />} title="Recent Anomalies" badge={
              <span className="flex items-center gap-1 text-[10px] text-white/20">
                {anomalies.length} detected
                {expanded.anom ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </span>
            } />
          </button>
          {expanded.anom && (
            <div className="mt-3 space-y-1.5">
              {anomalies.map((a, i) => (
                <div key={i} className="flex items-center gap-2 px-2.5 py-1.5 rounded bg-white/[0.02]">
                  <span className="text-[10px] text-white/25 w-16 shrink-0">{a.date}</span>
                  <span className="text-[10px] text-amber-400/60 w-20 shrink-0">{a.metric}</span>
                  <span className="text-[11px] text-white/40 flex-1">{a.interpretation}</span>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      )}
    </div>
  );
}

function BloodPanelUpload({ onUploaded, panelCount }: { onUploaded: () => void; panelCount: number }) {
  const [uploading, setUploading] = useState(false);
  const [wiping, setWiping] = useState(false);
  const [result, setResult] = useState<{ markers_extracted?: number; error?: string; message?: string } | null>(null);
  const [panelDate, setPanelDate] = useState(new Date().toISOString().slice(0, 10));
  const [labName, setLabName] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const handleWipe = useCallback(async () => {
    if (!confirm('Delete all blood panels and markers? You can re-upload the PDFs after.')) return;
    setWiping(true);
    setResult(null);
    try {
      const res = await fetch(apiUrl('/api/blood-panel'), { method: 'DELETE' });
      const data = await res.json();
      setResult({ message: data.message || `Wiped ${data.deleted} panels` });
      onUploaded();
    } catch (e) {
      setResult({ error: String(e) });
    } finally {
      setWiping(false);
    }
  }, [onUploaded]);

  const handleUpload = useCallback(async () => {
    const files = fileRef.current?.files;
    if (!files || files.length === 0) return;
    setUploading(true);
    setResult(null);
    try {
      let totalMarkers = 0;
      let successCount = 0;
      const errors: string[] = [];
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const form = new FormData();
        form.append('file', file);
        // Only pass manual date if single file; multi-file uses auto-detect from filename
        if (files.length === 1) {
          form.append('panel_date', panelDate);
        }
        if (labName) form.append('lab_name', labName);
        const res = await fetch(apiUrl('/api/blood-panel'), { method: 'POST', body: form });
        const data = await res.json();
        if (data.error) {
          errors.push(`${file.name}: ${data.error}`);
        } else {
          totalMarkers += data.markers_extracted || 0;
          successCount++;
        }
      }
      if (errors.length > 0 && successCount === 0) {
        setResult({ error: errors.join('; ') });
      } else {
        setResult({ markers_extracted: totalMarkers, message: successCount > 1 ? `✅ ${successCount} panels uploaded, ${totalMarkers} markers extracted` : undefined });
        onUploaded();
      }
    } catch (e) {
      setResult({ error: String(e) });
    } finally {
      setUploading(false);
    }
  }, [panelDate, labName, onUploaded]);

  return (
    <GlassCard>
      <CardHeader icon={<Upload size={16} className="text-indigo-400" />} title="Upload Blood Panel PDFs" />
      <div className="mt-3 space-y-3">
        <div className="flex gap-3">
          <div className="flex-1">
            <label className="text-[10px] text-white/25 uppercase tracking-wider">Date (auto-detected for multi-upload)</label>
            <input type="date" value={panelDate} onChange={e => setPanelDate(e.target.value)}
              className="w-full mt-1 px-2.5 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-xs text-white/70 focus:border-indigo-500/30 focus:outline-none" />
          </div>
          <div className="flex-1">
            <label className="text-[10px] text-white/25 uppercase tracking-wider">Lab (optional)</label>
            <input type="text" value={labName} onChange={e => setLabName(e.target.value)} placeholder="e.g. Synlab, LabCorp"
              className="w-full mt-1 px-2.5 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-xs text-white/70 placeholder:text-white/15 focus:border-indigo-500/30 focus:outline-none" />
          </div>
        </div>
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
          <input ref={fileRef} type="file" accept=".pdf" multiple className="flex-1 min-w-0 text-xs text-white/40 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-indigo-500/20 file:text-indigo-400 file:text-xs file:font-medium file:cursor-pointer hover:file:bg-indigo-500/30" />
          <button onClick={handleUpload} disabled={uploading}
            className="px-4 py-1.5 rounded-lg bg-indigo-500/20 border border-indigo-500/30 text-indigo-400 text-xs font-medium hover:bg-indigo-500/30 disabled:opacity-40 transition-all whitespace-nowrap shrink-0">
            {uploading ? 'Parsing...' : 'Upload & Parse All'}
          </button>
        </div>
        {result && (
          <div className={`text-xs p-2.5 rounded-lg ${result.error ? 'bg-red-500/10 text-red-400' : 'bg-emerald-500/10 text-emerald-400'}`}>
            {result.error ? `Error: ${result.error}` : result.message ? (result.message.startsWith('✅') ? result.message : `🗑️ ${result.message}`) : `✅ Extracted ${result.markers_extracted} markers`}
          </div>
        )}
        {panelCount > 0 && (
          <div className="flex items-center justify-between pt-2 border-t border-white/[0.06]">
            <span className="text-[10px] text-white/20">{panelCount} panels in database</span>
            <button onClick={handleWipe} disabled={wiping}
              className="text-[10px] text-red-400/50 hover:text-red-400 transition-colors disabled:opacity-40">
              {wiping ? 'Wiping...' : 'Reset all panels'}
            </button>
          </div>
        )}
      </div>
    </GlassCard>
  );
}

interface BloodAnalytics {
  panels_count: number;
  markers_count: number;
  time_series: Record<string, {
    category: string;
    points: Array<{ date: string; value: number | null; unit: string | null; ref_low: number | null; ref_high: number | null; status: string; lab: string | null }>;
    trend: { direction: string; change_pct: number; first: number; last: number } | null;
    unit: string | null;
    ref_low: number | null;
    ref_high: number | null;
    current_status: string | null;
  }>;
  correlations: Array<{ marker: string; whoop_metric: string; correlation: number; strength: string; direction: string; data_points: number; interpretation: string }>;
  categories: Record<string, string[]>;
  flagged: Array<{ marker: string; status: string; value: number | null; unit: string | null; ref_low: number | null; ref_high: number | null; trend: { direction: string; change_pct: number } | null; category: string }>;
  panel_dates: string[];
}

// ─────────────────────────────────────────────────────────────────────────────
// SupplementsTab
// ─────────────────────────────────────────────────────────────────────────────

type SupplementsView = 'log' | 'correlations' | 'supplements' | 'import';
type ImportMode = 'csv' | 'url';

interface BioAgeContribution {
  key: string;
  name: string;
  group: string;
  value: number;
  delta_years: number;
  source: string;
}
interface BioAgeData {
  chronological_age: number | null;
  physiological_age: number | null;
  delta_years: number;
  pace_of_aging: number;
  contributions: BioAgeContribution[];
  markers_scored: number;
  markers_total: number;
  data_completeness: number;
  missing_markers: string[];
  needs_date_of_birth: boolean;
  note?: string;
  error?: string;
}

interface GlucoseOverview {
  readings: number;
  mean_mgdl?: number;
  sd_mgdl?: number;
  cv_pct?: number | null;
  gmi_pct?: number;
  time_in_range_pct?: number | null;
  hypo_pct?: number | null;
  hyper_pct?: number | null;
  target_low?: number;
  target_high?: number;
}
interface GlucoseDaily { date: string; night_glucose_avg: number | null; day_glucose_avg: number | null; readings: number; }
interface GlucoseData {
  overview: GlucoseOverview;
  daily: GlucoseDaily[];
  recovery_correlation?: { r: number | null; n: number; interpretation?: string };
  error?: string;
}

const GLUCOSE_RANGES = [
  { id: 90, label: '90d' },
  { id: 365, label: '1y' },
  { id: 730, label: '2y' },
];

function GlucoseRangeSelector({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex items-center gap-1 bg-white/[0.03] rounded-lg p-0.5 border border-white/[0.06]">
      {GLUCOSE_RANGES.map(r => (
        <button key={r.id} onClick={() => onChange(r.id)}
          className={`px-2.5 py-1 rounded-md text-[10px] font-medium transition-all ${
            value === r.id ? 'bg-sky-500/20 text-sky-400 border border-sky-500/30' : 'text-white/30 hover:text-white/50 border border-transparent'
          }`}>{r.label}</button>
      ))}
    </div>
  );
}

function GlucoseTab() {
  const [days, setDays] = useState<number>(90);
  const { data, loading } = useAutoRefresh<GlucoseData>(`/api/glucose?days=${days}`, 300000);

  if (loading && !data) {
    return <GlassCard className="animate-pulse"><div className="h-24 flex items-center justify-center text-white/20 text-xs">Loading glucose…</div></GlassCard>;
  }
  const empty = !data || data.error || !data.overview || data.overview.readings === 0;
  if (empty) {
    return (
      <div className="space-y-3">
        <div className="flex justify-end"><GlucoseRangeSelector value={days} onChange={setDays} /></div>
        <GlassCard><p className="text-sm text-white/40">
          No glucose readings in the last {days} days.
          {days < 730 ? ' Try a wider range above,' : ''} or connect the FreeStyle Libre adapter
          (<code className="text-white/60">biohub connect libre</code>) and drop a LibreView CSV export into the watch folder.
        </p></GlassCard>
      </div>
    );
  }

  const o = data.overview;
  const series = data.daily.filter(d => d.day_glucose_avg !== null || d.night_glucose_avg !== null);
  const maxG = Math.max(...series.flatMap(d => [d.day_glucose_avg ?? 0, d.night_glucose_avg ?? 0]), o.target_high ?? 180);
  const corr = data.recovery_correlation;

  const stat = (label: string, value: string, sub?: string, color = 'text-white/90') => (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-white/30">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      {sub && <div className="text-xs text-white/40">{sub}</div>}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-end"><GlucoseRangeSelector value={days} onChange={setDays} /></div>
      <GlassCard>
        <div className="flex flex-wrap gap-x-8 gap-y-3">
          {stat('Mean glucose', `${o.mean_mgdl} mg/dL`, `SD ${o.sd_mgdl} · CV ${o.cv_pct}%`)}
          {stat('GMI (est. HbA1c)', `${o.gmi_pct}%`, o.gmi_pct && o.gmi_pct < 5.7 ? 'normal range' : 'elevated', (o.gmi_pct ?? 0) < 5.7 ? 'text-emerald-400' : 'text-amber-400')}
          {stat('Time in range', `${o.time_in_range_pct}%`, `${o.target_low}–${o.target_high} mg/dL`, (o.time_in_range_pct ?? 0) >= 70 ? 'text-emerald-400' : 'text-amber-400')}
          {stat('Low / high', `${o.hypo_pct}% / ${o.hyper_pct}%`, 'time below / above range')}
          {stat('Readings', `${o.readings.toLocaleString()}`, `last ${days} days`)}
        </div>
        {corr?.r !== null && corr?.r !== undefined && (
          <p className="mt-3 text-xs text-white/40">
            Overnight glucose ↔ next-day recovery: r = <span className="text-white/70">{corr.r}</span> ({corr.n} days). {corr.interpretation}
          </p>
        )}
      </GlassCard>

      <GlassCard>
        <CardHeader icon={<Droplets size={16} className="text-sky-400" />} title="Daily glucose" badge={<span className="text-[10px] text-white/30">overnight (23:00–07:00) vs daytime mean</span>} />
        <div className="mt-3 flex items-end gap-[2px] h-40 overflow-x-auto">
          {series.map(d => (
            <div key={d.date} className="flex flex-col justify-end items-center gap-[1px] min-w-[3px] flex-1 h-full" title={`${d.date}\nnight ${d.night_glucose_avg ?? '—'} / day ${d.day_glucose_avg ?? '—'} mg/dL`}>
              {d.day_glucose_avg !== null && (
                <div className="w-full bg-sky-500/40" style={{ height: `${(d.day_glucose_avg / maxG) * 100}%` }} />
              )}
              {d.night_glucose_avg !== null && (
                <div className="w-full bg-indigo-400/60" style={{ height: `${(d.night_glucose_avg / maxG) * 40}%` }} />
              )}
            </div>
          ))}
        </div>
        <div className="mt-2 flex gap-4 text-[11px] text-white/40">
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-2 bg-sky-500/40" /> daytime mean</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-2 bg-indigo-400/60" /> overnight mean</span>
        </div>
      </GlassCard>
    </div>
  );
}

function BioAgeTab() {
  const { data, loading } = useAutoRefresh<BioAgeData>('/api/physiological-age', 300000);

  if (loading && !data) {
    return <GlassCard className="animate-pulse"><div className="h-24 flex items-center justify-center text-white/20 text-xs">Computing biological age…</div></GlassCard>;
  }
  if (!data || data.error || data.contributions.length === 0) {
    return <GlassCard><p className="text-sm text-white/40">No biological-age data yet — needs WHOOP recovery/sleep history and (for the absolute age) a date of birth in the profile.</p></GlassCard>;
  }

  const delta = data.delta_years;
  const younger = delta < 0;
  const deltaColor = younger ? 'text-emerald-400' : delta > 0 ? 'text-amber-400' : 'text-white/60';
  const maxAbs = Math.max(...data.contributions.map(c => Math.abs(c.delta_years)), 0.1);

  return (
    <div className="space-y-4">
      <GlassCard>
        <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-white/30">Biological age</div>
            <div className="text-3xl font-bold text-white/90">
              {data.physiological_age !== null ? `${data.physiological_age.toFixed(1)} yr` : '—'}
            </div>
            {data.chronological_age !== null && (
              <div className="text-xs text-white/40">chronological {data.chronological_age.toFixed(1)} yr</div>
            )}
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-white/30">Delta</div>
            <div className={`text-3xl font-bold ${deltaColor}`}>
              {delta > 0 ? '+' : ''}{delta.toFixed(1)} yr
            </div>
            <div className="text-xs text-white/40">{younger ? 'younger than your age' : delta > 0 ? 'older than your age' : 'on par'}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-white/30">Pace of aging*</div>
            <div className="text-3xl font-bold text-white/70">{data.pace_of_aging > 0 ? '+' : ''}{data.pace_of_aging.toFixed(2)}×</div>
            <div className="text-xs text-white/40">{data.markers_scored}/{data.markers_total} markers</div>
          </div>
        </div>
        {data.needs_date_of_birth && (
          <p className="mt-3 text-xs text-amber-400/80">Set a date of birth in the profile to get the absolute biological age — the per-marker breakdown below works without it.</p>
        )}
      </GlassCard>

      <GlassCard>
        <CardHeader icon={<Activity size={16} className="text-emerald-400" />} title="Marker contributions" badge={<span className="text-[10px] text-white/30">negative = younger</span>} />
        <div className="space-y-2 mt-3">
          {data.contributions.map(c => {
            const neg = c.delta_years < 0;
            const pct = (Math.abs(c.delta_years) / maxAbs) * 100;
            return (
              <div key={c.key} className="flex items-center gap-3 text-xs">
                <div className="w-40 shrink-0 text-white/70 truncate" title={c.source}>{c.name}</div>
                <div className="w-16 shrink-0 text-right text-white/40 tabular-nums">{c.value}</div>
                <div className="flex-1 relative h-4 bg-white/[0.04] rounded overflow-hidden">
                  <div
                    className={`absolute top-0 bottom-0 ${neg ? 'right-1/2 bg-emerald-500/50' : 'left-1/2 bg-amber-500/50'}`}
                    style={{ width: `${pct / 2}%` }}
                  />
                  <div className="absolute left-1/2 top-0 bottom-0 w-px bg-white/20" />
                </div>
                <div className={`w-14 shrink-0 text-right tabular-nums ${neg ? 'text-emerald-400' : c.delta_years > 0 ? 'text-amber-400' : 'text-white/40'}`}>
                  {c.delta_years > 0 ? '+' : ''}{c.delta_years.toFixed(2)}
                </div>
              </div>
            );
          })}
        </div>
        {data.missing_markers.length > 0 && (
          <p className="mt-3 text-[11px] text-white/30">Not scored (no data): {data.missing_markers.join(', ')}</p>
        )}
        <p className="mt-2 text-[11px] text-white/25">*{data.note}</p>
      </GlassCard>
    </div>
  );
}

function SupplementsTab() {
  const [view, setView] = useState<SupplementsView>('log');
  const [importMode, setImportMode] = useState<ImportMode>('csv');
  const [supplements, setSupplements] = useState<Supplement[]>([]);
  const [recentLogs, setRecentLogs] = useState<(SupplementLog & { supplement_name: string })[]>([]);
  const [correlations, setCorrelations] = useState<SupplementCorrelation[]>([]);
  const [loadingCorr, setLoadingCorr] = useState(false);

  // Quick-log form state
  const [logName, setLogName] = useState('');
  const [logDate, setLogDate] = useState(new Date().toISOString().slice(0, 10));
  const [logDose, setLogDose] = useState('');
  const [logUnit, setLogUnit] = useState('mg');
  const [logSubmitting, setLogSubmitting] = useState(false);
  const [logMsg, setLogMsg] = useState('');
  const [suggestion, setSuggestion] = useState<{ dose_mg: number | null; dose_unit: string; active_ingredient: string | null; default_lag_hours: number } | null>(null);
  const [suggestionLoading, setSuggestionLoading] = useState(false);

  // Import state
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importUrl, setImportUrl] = useState('');
  const [importLoading, setImportLoading] = useState(false);
  const [importResults, setImportResults] = useState<any[] | null>(null);
  const [importSelected, setImportSelected] = useState<Set<number>>(new Set());
  const [importConfirming, setImportConfirming] = useState(false);
  const [importMsg, setImportMsg] = useState('');

  // Per-period editable units_per_day (index in importResults)
  const [editedUnitsPerDay, setEditedUnitsPerDay] = useState<Map<number, number>>(new Map());

  const fetchSupplements = async () => {
    try {
      const res = await fetch(apiUrl('/api/supplements'));
      const data: SupplementsData = await res.json();
      setSupplements(data.supplements || []);
      setRecentLogs(data.recent_logs || []);
    } catch { /* */ }
  };

  const fetchCorrelations = async () => {
    setLoadingCorr(true);
    try {
      const res = await fetch(apiUrl('/api/supplement-analytics'));
      const data = await res.json();
      setCorrelations(data.supplements || []);
    } catch { /* */ } finally {
      setLoadingCorr(false);
    }
  };

  // Initial load
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchSupplements(); }, []);

  const handleViewChange = (v: SupplementsView) => {
    setView(v);
    if (v === 'correlations' && correlations.length === 0) fetchCorrelations();
  };

  // ── Quick-log: when name changes, fetch suggestion for unknown supplements ──
  const handleLogNameChange = async (name: string) => {
    setLogName(name);
    setSuggestion(null);
    const existing = supplements.find(s => s.name.toLowerCase() === name.toLowerCase());
    if (existing) {
      if (existing.dose_mg) setLogDose(String(existing.dose_mg));
      setLogUnit(existing.dose_unit || 'mg');
      return;
    }
    if (name.length < 3) return;
    setSuggestionLoading(true);
    try {
      const res = await fetch(apiUrl('/api/supplements'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'suggest', name }),
      });
      const s = await res.json();
      setSuggestion(s);
      if (s.dose_mg) setLogDose(String(s.dose_mg));
      if (s.dose_unit) setLogUnit(s.dose_unit);
    } catch { /* */ } finally {
      setSuggestionLoading(false);
    }
  };

  const handleLogSubmit = async () => {
    if (!logName.trim()) return;
    setLogSubmitting(true);
    setLogMsg('');
    try {
      // Find or create supplement
      let supId: number;
      const existing = supplements.find(s => s.name.toLowerCase() === logName.toLowerCase());
      if (existing) {
        supId = existing.id;
      } else {
        const createRes = await fetch(apiUrl('/api/supplements'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: 'add_supplement',
            name: logName.trim(),
            active_ingredient: suggestion?.active_ingredient || null,
            dose_mg: logDose ? parseFloat(logDose) : null,
            dose_unit: logUnit,
            default_lag_hours: suggestion?.default_lag_hours || 24,
          }),
        });
        const cr = await createRes.json();
        supId = cr.id;
      }

      // Log intake
      await fetch(apiUrl('/api/supplements'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'log_intake',
          supplement_id: supId,
          taken_at: logDate,
          dose_mg: logDose ? parseFloat(logDose) : null,
          dose_unit: logUnit,
        }),
      });

      setLogMsg(`✓ Logged ${logName} for ${logDate}`);
      setLogName('');
      setLogDose('');
      setSuggestion(null);
      fetchSupplements();
    } catch (e) {
      setLogMsg(`Error: ${e}`);
    } finally {
      setLogSubmitting(false);
    }
  };

  const handleDeleteSupplement = async (id: number) => {
    if (!confirm('Delete this supplement and all its logs?')) return;
    await fetch(apiUrl(`/api/supplements?id=${id}`), { method: 'DELETE' });
    fetchSupplements();
  };

  // ── Amazon Import ──────────────────────────────────────────────────────────
  const handleImportSubmit = async () => {
    setImportLoading(true);
    setImportResults(null);
    setImportMsg('');
    try {
      const fd = new FormData();
      if (importMode === 'csv') {
        if (!importFile) { setImportMsg('Please select a CSV file'); setImportLoading(false); return; }
        fd.append('type', 'csv');
        fd.append('file', importFile);
      } else {
        if (!importUrl) { setImportMsg('Please enter an Amazon URL'); setImportLoading(false); return; }
        fd.append('type', 'url');
        fd.append('url', importUrl);
      }

      const res = await fetch(apiUrl('/api/supplements/import-amazon'), { method: 'POST', body: fd });
      const data = await res.json();

      if (!res.ok || data.error) {
        setImportMsg(`Error: ${data.error || res.statusText}`);
        return;
      }

      const suggestions = data.suggestions || [];
      setImportResults(suggestions);
      setImportSelected(new Set(suggestions.map((_: any, i: number) => i)));
      setEditedUnitsPerDay(new Map(suggestions.map((s: any, i: number) => [i, s.units_per_day])));

      if (suggestions.length === 0) {
        const sample = data.sample_titles?.length
          ? ` Sample titles: ${data.sample_titles.join(', ')}`
          : '';
        setImportMsg(importMode === 'csv'
          ? `Parsed ${data.total_orders || 0} orders, 0 identified as supplements.${sample}`
          : 'No supplement identified. Try adding manually.');
      }
    } catch (e) {
      setImportMsg(String(e));
    } finally {
      setImportLoading(false);
    }
  };

  const handleImportConfirm = async () => {
    if (!importResults) return;
    setImportConfirming(true);
    setImportMsg('');
    let added = 0;

    try {
      for (let i = 0; i < importResults.length; i++) {
        if (!importSelected.has(i)) continue;
        const s = importResults[i];
        const unitsPerDay = editedUnitsPerDay.get(i) || s.units_per_day || 1;

        // Create supplement
        const createRes = await fetch(apiUrl('/api/supplements'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: 'add_supplement',
            name: s.suggested_name,
            active_ingredient: s.active_ingredient,
            dose_mg: s.dose_mg,
            dose_unit: s.dose_unit,
            amazon_asin: s.asin,
            default_lag_hours: (s as any).lag_hours,
          }),
        });
        const cr = await createRes.json();
        const supId = cr.id;

        // Log each period
        for (const period of s.intake_periods || []) {
          const durationDays = Math.round(s.unit_count / unitsPerDay);
          const intakeEnd = addDaysToDate(period.intake_start, durationDays);
          await fetch(apiUrl('/api/supplements'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              action: 'log_period',
              supplement_id: supId,
              intake_start: period.intake_start,
              intake_end: intakeEnd,
              duration_days: durationDays,
              dose_mg: s.dose_mg,
              dose_unit: s.dose_unit,
              source: 'amazon_csv',
              amazon_order_id: period.order_ids?.[0] || null,
            }),
          });
        }
        added++;
      }

      setImportMsg(`✓ Added ${added} supplement(s) with intake history`);
      setImportResults(null);
      fetchSupplements();
    } catch (e) {
      setImportMsg(String(e));
    } finally {
      setImportConfirming(false);
    }
  };

  function addDaysToDate(date: string, days: number): string {
    const d = new Date(date);
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  }

  const subNavBtnClass = (active: boolean) =>
    `px-3 py-1.5 rounded-lg text-xs font-medium transition-all whitespace-nowrap ${
      active
        ? 'bg-violet-500/20 text-violet-400 border border-violet-500/30'
        : 'bg-white/[0.03] text-white/30 border border-white/[0.06] hover:text-white/50'
    }`;

  return (
    <div className="space-y-4">
      {/* Sub-navigation */}
      <div className="flex flex-wrap items-center gap-2">
        {([
          { id: 'log' as const, label: 'Quick Log' },
          { id: 'correlations' as const, label: 'Correlations' },
          { id: 'supplements' as const, label: 'My Supplements' },
          { id: 'import' as const, label: 'Import' },
        ] as const).map(v => (
          <button key={v.id} onClick={() => handleViewChange(v.id)} className={subNavBtnClass(view === v.id)}>
            {v.label}
          </button>
        ))}
      </div>

      {/* ─── QUICK LOG ───────────────────────────────────────────────────────── */}
      {view === 'log' && (
        <div className="space-y-4">
          <GlassCard>
            <CardHeader icon={<Pill size={16} className="text-violet-400" />} title="Log Supplement Intake" />
            <div className="mt-3 space-y-3">
              {/* Supplement name with datalist autocomplete */}
              <div>
                <label className="text-[10px] text-white/30 mb-1 block">Supplement</label>
                <div className="relative">
                  <input
                    type="text"
                    list="supp-list"
                    value={logName}
                    onChange={e => handleLogNameChange(e.target.value)}
                    placeholder="e.g. Magnesium, Vitamin D3, Ashwagandha..."
                    className="w-full bg-white/[0.05] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white/80 placeholder-white/20 focus:outline-none focus:border-violet-500/40"
                  />
                  <datalist id="supp-list">
                    {supplements.map(s => <option key={s.id} value={s.name} />)}
                  </datalist>
                  {suggestionLoading && (
                    <div className="absolute right-3 top-2.5 text-[10px] text-white/25 animate-pulse">looking up...</div>
                  )}
                </div>
                {suggestion && !suggestionLoading && (
                  <div className="mt-1 px-2 py-1.5 rounded-lg bg-violet-500/5 border border-violet-500/15 text-[10px] text-violet-300/70">
                    Suggested: {suggestion.dose_mg}{suggestion.dose_unit}
                    {suggestion.active_ingredient && ` · ${suggestion.active_ingredient}`}
                    {suggestion.default_lag_hours && ` · lag ${suggestion.default_lag_hours}h`}
                  </div>
                )}
              </div>

              {/* Date + Dose row */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                <div>
                  <label className="text-[10px] text-white/30 mb-1 block">Date</label>
                  <input
                    type="date"
                    value={logDate}
                    onChange={e => setLogDate(e.target.value)}
                    className="w-full bg-white/[0.05] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white/80 focus:outline-none focus:border-violet-500/40"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-white/30 mb-1 block">Dose</label>
                  <input
                    type="number"
                    value={logDose}
                    onChange={e => setLogDose(e.target.value)}
                    placeholder="400"
                    className="w-full bg-white/[0.05] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white/80 placeholder-white/20 focus:outline-none focus:border-violet-500/40"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-white/30 mb-1 block">Unit</label>
                  <select
                    value={logUnit}
                    onChange={e => setLogUnit(e.target.value)}
                    className="w-full bg-white/[0.05] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white/80 focus:outline-none focus:border-violet-500/40"
                  >
                    {['mg', 'mcg', 'IU', 'g', 'ml', 'caps'].map(u => <option key={u} value={u}>{u}</option>)}
                  </select>
                </div>
              </div>

              <button
                onClick={handleLogSubmit}
                disabled={logSubmitting || !logName.trim()}
                className="w-full py-2 rounded-lg text-sm font-medium bg-violet-500/20 text-violet-400 border border-violet-500/30 hover:bg-violet-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
              >
                {logSubmitting ? 'Logging...' : 'Log Intake'}
              </button>

              {logMsg && (
                <div className={`text-xs px-3 py-2 rounded-lg ${logMsg.startsWith('✓') ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>
                  {logMsg}
                </div>
              )}
            </div>
          </GlassCard>

          {/* Recent logs */}
          {recentLogs.length > 0 && (
            <GlassCard>
              <CardHeader icon={<Calendar size={16} className="text-white/30" />} title="Recent Logs" badge={
                <span className="text-[10px] text-white/20">{recentLogs.length} entries</span>
              } />
              <div className="mt-2 space-y-1">
                {recentLogs.slice(0, 10).map(log => (
                  <div key={log.id} className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-white/[0.02] transition-colors">
                    <div className="min-w-0">
                      <span className="text-xs text-white/70 font-medium">{log.supplement_name}</span>
                      {log.dose_mg && <span className="text-[10px] text-white/30 ml-2">{log.dose_mg}{log.dose_unit}</span>}
                    </div>
                    <span className="text-[10px] text-white/25 shrink-0 ml-2">{log.taken_at}</span>
                  </div>
                ))}
              </div>
            </GlassCard>
          )}
        </div>
      )}

      {/* ─── CORRELATIONS ──────────────────────────────────────────────────── */}
      {view === 'correlations' && (
        <div className="space-y-4">
          {loadingCorr ? (
            <GlassCard><p className="text-xs text-white/30 animate-pulse">Computing correlations...</p></GlassCard>
          ) : correlations.length === 0 ? (
            <GlassCard>
              <CardHeader icon={<TrendingUp size={16} className="text-violet-400" />} title="Supplement ↔ Recovery Correlations" />
              <p className="text-xs text-white/30 mt-2">
                No correlations available yet. Log at least 5 days of supplement intake to see how it correlates with your recovery score and HRV.
              </p>
              <div className="mt-3 p-3 rounded-lg bg-white/[0.03] border border-white/[0.06]">
                <p className="text-[10px] text-white/25">Tip: Import your Amazon order history to retroactively populate months of supplement intake data.</p>
              </div>
            </GlassCard>
          ) : (
            <GlassCard>
              <CardHeader icon={<TrendingUp size={16} className="text-violet-400" />} title="Supplement ↔ Recovery" badge={
                <span className="text-[10px] text-white/20">{correlations.length} supplements · {correlations.some(c => c.adjusted) ? 'adjusted for sleep & strain' : 'bivariate'}</span>
              } />
              <div className="mt-3 space-y-2">
                {correlations.map((c, i) => {
                  const r   = c.correlation_recovery;
                  const rColor = Math.abs(r) > 0.6
                    ? (r > 0 ? 'text-emerald-400' : 'text-red-400')
                    : Math.abs(r) > 0.35 ? 'text-amber-400' : 'text-white/40';
                  const ciStraddles = c.ci_low != null && c.ci_high != null && c.ci_low < 0 && c.ci_high > 0;
                  return (
                    <div key={i} className="px-3 py-2.5 rounded-lg bg-white/[0.02] hover:bg-white/[0.04] transition-colors">
                      <div className="flex items-start gap-3">
                        <div className={`mt-0.5 w-1.5 h-8 rounded-full shrink-0 ${
                          c.strength === 'strong'   ? (c.direction === 'positive' ? 'bg-emerald-500' : 'bg-red-500') :
                          c.strength === 'moderate' ? 'bg-amber-500' : 'bg-white/20'
                        }`} />
                        <div className="flex-1 min-w-0">
                          {/* Row 1: name + badges */}
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-xs font-medium text-white/70">{c.name}</span>
                            <span className="text-[9px] text-white/20">lag {c.lag_hours}h</span>
                            {c.significant
                              ? <span className="text-[9px] px-1 py-0.5 rounded border border-emerald-500/20 text-emerald-400/70">p&lt;0.05</span>
                              : <span className="text-[9px] text-white/15">not significant</span>
                            }
                            {c.adjusted && <span className="text-[9px] text-violet-400/40">adj.</span>}
                          </div>
                          {/* Row 2: delta */}
                          <div className={`text-[11px] font-semibold mt-0.5 ${c.recovery_delta >= 0 ? 'text-emerald-400/80' : 'text-red-400/80'}`}>
                            {c.recovery_delta >= 0 ? '+' : ''}{c.recovery_delta} pts recovery
                            <span className="text-[10px] font-normal text-white/25 ml-1">({c.avg_recovery_with} vs {c.avg_recovery_without})</span>
                          </div>
                          {/* Row 3: r + CI + days */}
                          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                            <span className={`text-[10px] font-mono ${rColor}`}>r={r > 0 ? '+' : ''}{r}</span>
                            {c.ci_low != null && c.ci_high != null && (
                              <span className={`text-[9px] ${ciStraddles ? 'text-amber-400/50' : 'text-white/20'}`}>
                                CI [{c.ci_low > 0 ? '+' : ''}{c.ci_low}, {c.ci_high > 0 ? '+' : ''}{c.ci_high}]{ciStraddles ? ' ⚠' : ''}
                              </span>
                            )}
                            <span className={`text-[9px] ${c.data_points < 20 ? 'text-amber-400/60' : 'text-white/15'}`}>
                              {c.data_points} days{c.data_points < 20 ? ' ⚠' : ''}
                            </span>
                            {c.correlation_hrv != null && (
                              <span className="text-[9px] text-white/20">HRV r={c.correlation_hrv > 0 ? '+' : ''}{c.correlation_hrv}</span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </GlassCard>
          )}
        </div>
      )}

      {/* ─── MY SUPPLEMENTS ────────────────────────────────────────────────── */}
      {view === 'supplements' && (
        <div className="space-y-4">
          {supplements.length === 0 ? (
            <GlassCard>
              <CardHeader icon={<Pill size={16} className="text-violet-400" />} title="My Supplements" />
              <p className="text-xs text-white/30 mt-2">No supplements added yet. Use Quick Log to add your first supplement, or import from Amazon.</p>
            </GlassCard>
          ) : (
            <GlassCard>
              <CardHeader icon={<Pill size={16} className="text-violet-400" />} title="My Supplements" badge={
                <span className="text-[10px] text-white/20">{supplements.length} tracked</span>
              } />
              <div className="mt-2 divide-y divide-white/[0.04]">
                {supplements.map(s => (
                  <div key={s.id} className="flex items-center justify-between py-2.5 px-1 group">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-white/70">{s.name}</span>
                        {s.dose_mg && (
                          <span className="text-[10px] text-white/30">{s.dose_mg}{s.dose_unit}</span>
                        )}
                        {s.active_ingredient && s.active_ingredient !== s.name && (
                          <span className="text-[10px] text-violet-400/50 px-1.5 py-0.5 rounded-full border border-violet-500/15 bg-violet-500/5">{s.active_ingredient}</span>
                        )}
                      </div>
                      <div className="text-[10px] text-white/20 mt-0.5">
                        {s.total_logs ? `${s.total_logs} log${s.total_logs !== 1 ? 's' : ''}` : 'no logs'}
                        {s.last_taken_at && ` · last: ${s.last_taken_at}`}
                        {s.default_lag_hours ? ` · lag ${s.default_lag_hours}h` : ''}
                      </div>
                    </div>
                    <button
                      onClick={() => handleDeleteSupplement(s.id)}
                      className="opacity-0 group-hover:opacity-100 p-1.5 rounded text-white/20 hover:text-red-400 hover:bg-red-500/10 transition-all"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
              </div>
            </GlassCard>
          )}
        </div>
      )}

      {/* ─── IMPORT ────────────────────────────────────────────────────────── */}
      {view === 'import' && (
        <div className="space-y-4">
          <GlassCard>
            <CardHeader icon={<FileUp size={16} className="text-violet-400" />} title="Import from Amazon" badge={
              <span className="text-[10px] text-white/20">requires ANTHROPIC_API_KEY</span>
            } />

            {/* Toggle CSV / URL */}
            <div className="flex gap-2 mt-3">
              {(['csv', 'url'] as const).map(m => (
                <button key={m} onClick={() => setImportMode(m)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                    importMode === m ? 'bg-violet-500/20 text-violet-400 border border-violet-500/30' : 'bg-white/[0.03] text-white/25 border border-white/[0.06] hover:text-white/50'
                  }`}>
                  {m === 'csv' ? 'CSV Upload' : 'URL Paste'}
                </button>
              ))}
            </div>

            {importMode === 'csv' ? (
              <div className="mt-3">
                <p className="text-[10px] text-white/25 mb-2">Export your Amazon order history: Account → Orders → Download order reports (CSV)</p>
                <label className="flex flex-col items-center gap-2 py-6 rounded-lg border border-dashed border-white/[0.10] bg-white/[0.02] cursor-pointer hover:bg-white/[0.04] transition-colors">
                  <Upload size={20} className="text-white/20" />
                  <span className="text-xs text-white/30">{importFile ? importFile.name : 'Click to select CSV file'}</span>
                  <input type="file" accept=".csv" className="hidden" onChange={e => setImportFile(e.target.files?.[0] || null)} />
                </label>
              </div>
            ) : (
              <div className="mt-3">
                <p className="text-[10px] text-white/25 mb-2">Paste an Amazon product URL to identify a supplement</p>
                <div className="flex gap-2">
                  <input
                    type="url"
                    value={importUrl}
                    onChange={e => setImportUrl(e.target.value)}
                    placeholder="https://www.amazon.de/dp/..."
                    className="flex-1 bg-white/[0.05] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white/80 placeholder-white/20 focus:outline-none focus:border-violet-500/40"
                  />
                  <Link2 size={16} className="self-center text-white/20 shrink-0" />
                </div>
              </div>
            )}

            <button
              onClick={handleImportSubmit}
              disabled={importLoading || (importMode === 'csv' ? !importFile : !importUrl)}
              className="mt-3 w-full py-2 rounded-lg text-sm font-medium bg-violet-500/20 text-violet-400 border border-violet-500/30 hover:bg-violet-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {importLoading ? 'Analyzing...' : 'Analyze'}
            </button>

            {importMsg && !importResults && (
              <div className={`mt-2 text-xs px-3 py-2 rounded-lg ${importMsg.startsWith('✓') ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-amber-500/10 text-amber-400/70 border border-amber-500/20'}`}>
                {importMsg}
              </div>
            )}
          </GlassCard>

          {/* Import results review */}
          {importResults && importResults.length > 0 && (
            <GlassCard>
              <CardHeader icon={<CheckCircle size={16} className="text-emerald-400" />} title="Review Import" badge={
                <span className="text-[10px] text-white/20">{importSelected.size} of {importResults.length} selected</span>
              } />

              <div className="mt-3 space-y-3">
                {importResults.map((s: any, i: number) => (
                  <div key={i} className={`rounded-lg border p-3 transition-all ${importSelected.has(i) ? 'border-violet-500/20 bg-violet-500/5' : 'border-white/[0.06] bg-white/[0.02] opacity-50'}`}>
                    <div className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        checked={importSelected.has(i)}
                        onChange={e => {
                          const next = new Set(importSelected);
                          e.target.checked ? next.add(i) : next.delete(i);
                          setImportSelected(next);
                        }}
                        className="mt-0.5 shrink-0 accent-violet-500"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium text-white/80">{s.suggested_name}</span>
                          {s.active_ingredient && s.active_ingredient !== s.suggested_name && (
                            <span className="text-[10px] text-violet-400/60 px-1.5 py-0.5 rounded-full border border-violet-500/15 bg-violet-500/5">{s.active_ingredient}</span>
                          )}
                          <span className={`text-[9px] px-1.5 py-0.5 rounded-full border ${s.confidence > 0.8 ? 'text-emerald-400/60 border-emerald-500/15' : 'text-amber-400/60 border-amber-500/15'}`}>
                            {Math.round(s.confidence * 100)}% match
                          </span>
                        </div>

                        <div className="flex items-center gap-3 mt-1 flex-wrap">
                          {s.dose_mg && (
                            <span className="text-[10px] text-white/30">{s.dose_mg}{s.dose_unit}</span>
                          )}
                          <span className="text-[10px] text-white/25">{s.unit_count} {s.unit_count === 1 ? 'unit' : 'units'} per package</span>
                          <div className="flex items-center gap-1">
                            <span className="text-[10px] text-white/25">units/day:</span>
                            <input
                              type="number"
                              min="0.25"
                              step="0.25"
                              value={editedUnitsPerDay.get(i) ?? s.units_per_day}
                              onChange={e => setEditedUnitsPerDay(m => { const n = new Map(m); n.set(i, parseFloat(e.target.value)); return n; })}
                              className="w-12 bg-white/[0.05] border border-white/[0.08] rounded px-1 py-0.5 text-xs text-white/60 focus:outline-none focus:border-violet-500/30"
                            />
                          </div>
                          <span className="text-[10px] text-white/20">
                            ≈ {(v => isFinite(v) ? v : '?')(Math.round(s.unit_count / (editedUnitsPerDay.get(i) || s.units_per_day || 1)))} days/package
                          </span>
                        </div>

                        {/* Intake periods */}
                        {s.intake_periods?.length > 0 && (
                          <div className="mt-2 space-y-1">
                            {s.intake_periods.map((p: any, pi: number) => (
                              <div key={pi} className="flex items-center gap-2 px-2 py-1 rounded bg-white/[0.03] border border-white/[0.05]">
                                <Calendar size={10} className="text-white/20 shrink-0" />
                                <span className="text-[10px] text-white/50">{p.intake_start} → {
                                  addDaysStr(p.intake_start, Math.round(s.unit_count / (editedUnitsPerDay.get(i) || s.units_per_day || 1)))
                                }</span>
                                <span className="text-[9px] text-white/20">
                                  {(v => isFinite(v) ? v : '?')(Math.round(s.unit_count / (editedUnitsPerDay.get(i) || s.units_per_day || 1)))} days
                                </span>
                                {p.is_continuous && (
                                  <span className="text-[9px] px-1 py-0.5 rounded border border-emerald-500/15 text-emerald-400/50">continuous</span>
                                )}
                                {p.order_count > 1 && (
                                  <span className="text-[9px] text-white/20">{p.order_count} orders</span>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              <button
                onClick={handleImportConfirm}
                disabled={importConfirming || importSelected.size === 0}
                className="mt-4 w-full py-2 rounded-lg text-sm font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
              >
                {importConfirming ? 'Importing...' : `Import ${importSelected.size} supplement${importSelected.size !== 1 ? 's' : ''}`}
              </button>

              {importMsg && (
                <div className={`mt-2 text-xs px-3 py-2 rounded-lg ${importMsg.startsWith('✓') ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>
                  {importMsg}
                </div>
              )}
            </GlassCard>
          )}
        </div>
      )}
    </div>
  );
}

function addDaysStr(date: string, days: number): string {
  if (!isFinite(days) || isNaN(days)) return '?';
  const d = new Date(date);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function BloodWorkTab({ bloodPanels, onRefresh }: { bloodPanels: WhoopData['bloodPanels']; onRefresh: () => void }) {
  const [view, setView] = useState<'timeline' | 'correlations' | 'panels'>('timeline');
  const [selectedCat, setSelectedCat] = useState<string | null>(null);
  const { data: analytics } = useAutoRefresh<BloodAnalytics>('/api/blood-analytics', 300000);

  const hasPanels = bloodPanels.length > 0;
  const categories = analytics?.categories || {};
  const ts = analytics?.time_series || {};
  const allCats = Object.keys(categories).sort();
  const filteredMarkers = selectedCat ? (categories[selectedCat] || []) : Object.keys(ts).sort();

  return (
    <div className="space-y-4">
      <BloodPanelUpload onUploaded={onRefresh} panelCount={bloodPanels.length} />

      {hasPanels && (
        <>
          {/* Sub-navigation */}
          <div className="flex flex-wrap items-center gap-2">
            {[
              { id: 'timeline' as const, label: 'Time Series' },
              { id: 'correlations' as const, label: 'Correlations' },
              { id: 'panels' as const, label: 'Panel History' },
            ].map(v => (
              <button key={v.id} onClick={() => setView(v.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all whitespace-nowrap ${
                  view === v.id ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' : 'bg-white/[0.03] text-white/30 border border-white/[0.06] hover:text-white/50'
                }`}>{v.label}</button>
            ))}
          </div>

          {/* ─── TIME SERIES VIEW ─── */}
          {view === 'timeline' && analytics && (
            <div className="space-y-4">
              {/* Flagged markers */}
              {analytics.flagged.length > 0 && (
                <GlassCard>
                  <CardHeader icon={<AlertTriangle size={16} className="text-amber-400" />} title="Markers Needing Attention" badge={
                    <span className="text-[10px] text-white/20">latest panel values only</span>
                  } />
                  <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {analytics.flagged.map((f: { marker: string; status: string; value: number | null; unit: string | null; ref_low: number | null; ref_high: number | null; trend: { direction: string; change_pct: number } | null; category: string; panel_date?: string }) => (
                      <div key={f.marker} className={`flex items-center justify-between p-2.5 rounded-lg border ${
                        f.status === 'high' ? 'bg-red-500/5 border-red-500/15' : 'bg-amber-500/5 border-amber-500/15'
                      }`}>
                        <div className="min-w-0">
                          <div className="text-xs font-medium text-white/70 truncate">{f.marker}</div>
                          <div className="text-[10px] text-white/30">{f.category}{f.panel_date ? ` · ${fd(f.panel_date)}` : ''}</div>
                        </div>
                        <div className="text-right shrink-0 ml-2">
                          <div className={`text-sm font-semibold ${f.status === 'high' ? 'text-red-400' : 'text-amber-400'}`}>
                            {f.value} <span className="text-[10px] text-white/25">{f.unit}</span>
                          </div>
                          <div className="text-[9px] text-white/20">
                            ref: {f.ref_low ?? '?'} – {f.ref_high ?? '?'}
                            {f.trend && <span className="ml-1">({f.trend.direction === 'up' ? '↑' : '↓'}{Math.abs(f.trend.change_pct)}%)</span>}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </GlassCard>
              )}

              {/* Category filter */}
              <div className="flex flex-wrap gap-1.5">
                <button onClick={() => setSelectedCat(null)}
                  className={`px-2 py-1 rounded text-[10px] font-medium transition-all ${
                    !selectedCat ? 'bg-white/10 text-white/70' : 'bg-white/[0.03] text-white/25 hover:text-white/40'
                  }`}>All ({Object.keys(ts).length})</button>
                {allCats.map(cat => (
                  <button key={cat} onClick={() => setSelectedCat(selectedCat === cat ? null : cat)}
                    className={`px-2 py-1 rounded text-[10px] font-medium transition-all ${
                      selectedCat === cat ? 'bg-white/10 text-white/70' : 'bg-white/[0.03] text-white/25 hover:text-white/40'
                    }`}>{cat} ({categories[cat]?.length || 0})</button>
                ))}
              </div>

              {/* Marker time series cards — global date axis for consistent x-positions */}
              {(() => {
                // Global date axis: all panel dates sorted ascending
                const allDates = analytics.panel_dates;
                const nDates = allDates.length;
                const chartW = Math.max(120, nDates * 50);
                const shortDate = (iso: string) => { try { const d = new Date(iso); return d.toLocaleDateString('en-GB', { month: 'short', year: '2-digit' }); } catch { return iso; } };
                // X position for a given global date index
                const xForIdx = (i: number) => nDates <= 1 ? chartW / 2 : (i / (nDates - 1)) * (chartW - 20) + 10;

                return (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {filteredMarkers.map(name => {
                      const m = ts[name];
                      if (!m || !m.points.length) return null;
                      const pts = m.points;
                      const values = pts.map(p => p.value).filter((v): v is number => v !== null);
                      if (!values.length) return null;
                      const dataMin = Math.min(...values);
                      const dataMax = Math.max(...values);
                      // Include reference range in y-axis scale
                      const yMin = Math.min(dataMin, m.ref_low ?? dataMin) * 0.92;
                      const yMax = Math.max(dataMax, m.ref_high ?? dataMax) * 1.08;
                      const yRange = yMax - yMin || 1;
                      // viewBox height = 108: top 12px reserved for value labels, then 58px chart area, bottom 24px for date labels
                      const toY = (v: number) => 80 - ((v - yMin) / yRange) * 58;
                      const fmtVal = (v: number) => Number.isInteger(v) ? v.toString() : v >= 100 ? Math.round(v).toString() : v.toFixed(1);

                      const lineColor = m.current_status === 'high' ? '#f87171' : m.current_status === 'low' ? '#fbbf24' : '#818cf8';

                      // Map each global date slot to this marker's actual data (or null)
                      const fullPts = allDates.map(date => {
                        const pt = pts.find(p => p.date === date);
                        return pt ?? { date, value: null as number | null, unit: null, ref_low: null, ref_high: null, status: 'missing' as string, lab: null };
                      });

                      // Build SVG path d — connect all measured points, skip null slots without breaking
                      let pathD = '';
                      let started = false;
                      fullPts.forEach((p, i) => {
                        if (p.value !== null) {
                          const x = xForIdx(i);
                          const y = toY(p.value);
                          pathD += started ? ` L${x} ${y}` : `M${x} ${y}`;
                          started = true;
                        }
                        // null slot: skip silently — next non-null will connect with L
                      });

                      // Most-recent measured point for header display
                      const lastMeasured = [...pts].reverse().find(p => p.value !== null);

                      return (
                        <GlassCard key={name} className="!p-3">
                          <div className="flex items-center justify-between mb-2">
                            <div className="min-w-0">
                              <div className="text-xs font-medium text-white/70 truncate">{name}</div>
                              <div className="text-[9px] text-white/20">{m.category}</div>
                            </div>
                            <div className="text-right shrink-0 ml-2">
                              <div className={`text-sm font-bold ${markerStatus(m.current_status || 'unknown')}`}>
                                {lastMeasured?.value ?? '—'} <span className="text-[9px] text-white/25 font-normal">{m.unit || ''}</span>
                              </div>
                              {m.trend && (
                                <div className="text-[9px] text-white/30">
                                  {m.trend.direction === 'up' ? '↑' : m.trend.direction === 'down' ? '↓' : '→'} {Math.abs(m.trend.change_pct)}%
                                </div>
                              )}
                            </div>
                          </div>
                          {/* Chart with y-axis reference range */}
                          <div className="flex gap-1">
                            {/* Y-axis labels */}
                            <div className="flex flex-col justify-between h-24 text-[8px] text-white/50 w-8 shrink-0 text-right pr-1 pb-4">
                              <span className="text-white/50">{m.ref_high ?? Math.round(yMax)}</span>
                              <span className="text-white/50">{m.ref_low ?? Math.round(yMin)}</span>
                            </div>
                            {/* SVG chart */}
                            <div className="relative flex-1 h-24">
                              <svg viewBox={`0 0 ${chartW} 108`} className="w-full h-full" preserveAspectRatio="xMidYMid meet">
                                {/* Reference range band */}
                                {m.ref_low != null && m.ref_high != null && (
                                  <rect x="0" y={toY(m.ref_high)} width={chartW} height={Math.max(1, toY(m.ref_low) - toY(m.ref_high))}
                                    fill="rgba(52,211,153,0.06)" stroke="rgba(52,211,153,0.15)" strokeWidth="0.5" strokeDasharray="4 2" />
                                )}
                                {/* One-sided ref lines */}
                                {m.ref_high != null && m.ref_low == null && (
                                  <line x1="0" y1={toY(m.ref_high)} x2={chartW} y2={toY(m.ref_high)}
                                    stroke="rgba(52,211,153,0.25)" strokeWidth="0.5" strokeDasharray="4 2" />
                                )}
                                {m.ref_low != null && m.ref_high == null && (
                                  <line x1="0" y1={toY(m.ref_low)} x2={chartW} y2={toY(m.ref_low)}
                                    stroke="rgba(52,211,153,0.25)" strokeWidth="0.5" strokeDasharray="4 2" />
                                )}
                                {/* Line — path with lifted pen for missing slots */}
                                {pathD && (
                                  <path d={pathD} fill="none" stroke={lineColor} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                )}
                                {/* Dots + date labels — only for global date slots */}
                                {fullPts.map((p, i) => {
                                  const x = xForIdx(i);
                                  if (p.value === null) {
                                    // Ghost tick: slot exists but no measurement
                                    return (
                                      <line key={i} x1={x} y1="96" x2={x} y2="100"
                                        stroke="rgba(255,255,255,0.10)" strokeWidth="1" />
                                    );
                                  }
                                  const dotColor = p.status === 'high' ? '#f87171' : p.status === 'low' ? '#fbbf24' : p.status === 'normal' ? '#34d399' : '#6366f1';
                                  const cy = toY(p.value);
                                  return (
                                    <g key={i}>
                                      {/* Value label above dot */}
                                      <text x={x} y={Math.max(cy - 7, 9)} textAnchor="middle" fontSize="7" fontWeight="600"
                                        fill={dotColor}>{fmtVal(p.value)}</text>
                                      <circle cx={x} cy={cy} r="4"
                                        fill={dotColor} stroke="rgba(0,0,0,0.4)" strokeWidth="1" />
                                      {/* Date label at bottom */}
                                      <text x={x} y="108" textAnchor="middle" fontSize="7.5" fill="rgba(255,255,255,0.55)">{shortDate(p.date)}</text>
                                      <title>{p.date}: {p.value} {m.unit || ''} ({p.status})</title>
                                    </g>
                                  );
                                })}
                              </svg>
                            </div>
                          </div>
                        </GlassCard>
                      );
                    })}
                  </div>
                );
              })()}
            </div>
          )}

          {/* ─── CORRELATIONS VIEW ─── */}
          {view === 'correlations' && analytics && (
            <div className="space-y-4">
              {analytics.correlations.length === 0 ? (
                <GlassCard>
                  <CardHeader icon={<TrendingUp size={16} className="text-cyan-400" />} title="Blood ↔ Whoop Correlations" />
                  <p className="text-xs text-white/30 mt-2">
                    Need at least 2 blood panels to calculate correlations. Upload more panels over time to see how your blood markers influence HRV, recovery, and sleep.
                  </p>
                </GlassCard>
              ) : (
                <GlassCard>
                  <CardHeader icon={<TrendingUp size={16} className="text-cyan-400" />} title="Blood Markers ↔ Whoop Performance" badge={
                    <span className="text-[10px] text-white/20">{analytics.correlations.length} found · {analytics.correlations.some((c: any) => c.adjusted) ? 'adjusted for sleep & strain' : 'bivariate'}</span>
                  } />
                  <div className="mt-3 space-y-2">
                    {analytics.correlations.map((c: any, i: number) => {
                      const r        = c.correlation;
                      const rColor   = Math.abs(r) > 0.6 ? (r > 0 ? 'text-emerald-400' : 'text-red-400') : Math.abs(r) > 0.35 ? 'text-amber-400' : 'text-white/40';
                      const ciStrad  = c.ci_low != null && c.ci_high != null && c.ci_low < 0 && c.ci_high > 0;
                      return (
                        <div key={i} className="px-3 py-2.5 rounded-lg bg-white/[0.02] hover:bg-white/[0.04] transition-colors">
                          <div className="flex items-start gap-3">
                            <div className={`mt-0.5 w-1.5 h-8 rounded-full shrink-0 ${
                              c.strength === 'strong'   ? (c.direction === 'positive' ? 'bg-emerald-500' : 'bg-red-500') :
                              c.strength === 'moderate' ? 'bg-amber-500' : 'bg-white/20'
                            }`} />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-xs font-medium text-white/70">{c.marker}</span>
                                <span className="text-[10px] text-white/20">→</span>
                                <span className="text-xs text-cyan-400/60">{c.whoop_label || c.whoop_metric}</span>
                                {c.significant
                                  ? <span className="text-[9px] px-1 py-0.5 rounded border border-emerald-500/20 text-emerald-400/70">p&lt;0.05</span>
                                  : <span className="text-[9px] text-white/15">not significant</span>
                                }
                                {c.adjusted && <span className="text-[9px] text-violet-400/40">adj.</span>}
                              </div>
                              <div className="text-[10px] text-white/25 mt-0.5">{c.interpretation}</div>
                              <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                                <span className={`text-[10px] font-mono ${rColor}`}>r={r > 0 ? '+' : ''}{r}</span>
                                {c.ci_low != null && c.ci_high != null && (
                                  <span className={`text-[9px] ${ciStrad ? 'text-amber-400/50' : 'text-white/20'}`}>
                                    CI [{c.ci_low > 0 ? '+' : ''}{c.ci_low}, {c.ci_high > 0 ? '+' : ''}{c.ci_high}]{ciStrad ? ' ⚠' : ''}
                                  </span>
                                )}
                                <span className={`text-[9px] ${c.data_points < 5 ? 'text-amber-400/60' : 'text-white/15'}`}>
                                  {c.data_points} panels{c.data_points < 5 ? ' ⚠' : ''}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </GlassCard>
              )}
            </div>
          )}

          {/* ─── PANEL HISTORY VIEW ─── */}
          {view === 'panels' && (
            <div className="space-y-4">
              {bloodPanels.map(panel => (
                <GlassCard key={panel.id}>
                  <CardHeader icon={<Droplets size={16} className="text-red-400" />} title={`Panel — ${panel.panel_date}`} badge={
                    <span className="text-[10px] text-white/25">{panel.lab_name || 'Unknown lab'} · {panel.markers.length} markers</span>
                  } />
                  {panel.markers.length > 0 && (
                    <div className="overflow-x-auto mt-3">
                      <table className="w-full text-xs">
                        <thead><tr className="text-white/25 text-left">
                          <th className="pb-2 font-medium">Marker</th>
                          <th className="pb-2 font-medium">Value</th>
                          <th className="pb-2 font-medium">Unit</th>
                          <th className="pb-2 font-medium">Reference</th>
                          <th className="pb-2 font-medium">Status</th>
                        </tr></thead>
                        <tbody className="divide-y divide-white/[0.04]">
                          {panel.markers.map(m => (
                            <tr key={m.id} className="hover:bg-white/[0.02]">
                              <td className="py-1.5 text-white/60">{m.marker_name}</td>
                              <td className={`py-1.5 font-semibold ${markerStatus(m.status)}`}>{m.value ?? '—'}</td>
                              <td className="py-1.5 text-white/30">{m.unit || ''}</td>
                              <td className="py-1.5 text-white/25">{m.ref_low != null && m.ref_high != null ? `${m.ref_low} – ${m.ref_high}` : '—'}</td>
                              <td className="py-1.5">
                                <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                                  m.status === 'normal' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' :
                                  m.status === 'high' ? 'bg-red-500/10 border-red-500/20 text-red-400' :
                                  m.status === 'low' ? 'bg-amber-500/10 border-amber-500/20 text-amber-400' :
                                  'bg-white/[0.04] border-white/[0.06] text-white/30'
                                }`}>{m.status}</span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </GlassCard>
              ))}
            </div>
          )}
        </>
      )}

      {!hasPanels && (
        <GlassCard>
          <CardHeader icon={<Droplets size={16} className="text-red-400" />} title="Blood Work" />
          <p className="text-sm text-white/40 mt-2">
            No blood panels uploaded yet. Upload a lab report PDF above — markers will be extracted automatically.
          </p>
          <div className="mt-4 p-3 rounded-lg bg-white/[0.03] border border-white/[0.06]">
            <p className="text-[11px] text-white/30">Supported: LabCorp, Quest, Synlab, LADR, Bioscientia, MVZ, and generic EU/DE formats.</p>
            <p className="text-[11px] text-white/20 mt-1">Upload multiple panels over time to see trends and correlations with your Whoop metrics.</p>
          </div>
        </GlassCard>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//  HEALTH TAB COMPONENTS — extracted for clarity. All custom-SVG charts.
// ═══════════════════════════════════════════════════════════════════

type DailyT = WhoopData['daily'][number];

function asPoint(d: DailyT, key: keyof DailyT) {
  return { date: d.date, value: (d[key] as number | null | undefined) ?? null };
}

function monthAverages(daily: DailyT[]) {
  // Current calendar month + previous calendar month.
  const byMonth = new Map<string, DailyT[]>();
  for (const d of daily) {
    const k = d.date.slice(0, 7); // YYYY-MM
    if (!byMonth.has(k)) byMonth.set(k, []);
    byMonth.get(k)!.push(d);
  }
  const keys = [...byMonth.keys()].sort().reverse();
  const cur = keys[0] ? byMonth.get(keys[0])! : [];
  const prev = keys[1] ? byMonth.get(keys[1])! : [];
  const avg = (rows: DailyT[], key: keyof DailyT): number | null => {
    const vs = rows.map(r => r[key]).filter((v): v is number => typeof v === 'number');
    if (!vs.length) return null;
    return vs.reduce((s, v) => s + v, 0) / vs.length;
  };
  return {
    curLabel: keys[0] ?? '—',
    prevLabel: keys[1] ?? '—',
    cur: {
      recovery: avg(cur, 'recovery_score'),
      strain: avg(cur, 'day_strain'),
      sleep: avg(cur, 'sleep_hours'),
      hrv: avg(cur, 'hrv_ms'),
      rhr: avg(cur, 'resting_hr'),
    },
    prev: {
      recovery: avg(prev, 'recovery_score'),
      strain: avg(prev, 'day_strain'),
      sleep: avg(prev, 'sleep_hours'),
      hrv: avg(prev, 'hrv_ms'),
      rhr: avg(prev, 'resting_hr'),
    },
  };
}

function OverviewTab({ data, range, days, rangeData, latest, latestDaily }: {
  data: WhoopData;
  range: string;
  days: number;
  rangeData: DailyT[];
  latest: WhoopData['recovery'][number] | undefined;
  latestDaily: DailyT | undefined;
}) {
  const todayRecovery = latest?.recovery_score ?? latestDaily?.recovery_score ?? null;
  const todayStrain = latestDaily?.day_strain ?? data.cycles[0]?.strain ?? null;
  const months = monthAverages(data.daily);

  // 30d window for distribution
  const last30 = data.daily.slice(0, 30);

  return (
    <div className="space-y-4">
      {/* Top: 2 prominent gauges + 4 stat cards */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <GlassCard className="flex items-center justify-center py-6">
          <RecoveryDonut value={todayRecovery} sub={latestDaily?.date ?? ''} />
        </GlassCard>
        <GlassCard className="flex items-center justify-center py-6">
          <StrainGauge value={todayStrain} sub={latestDaily?.date ?? ''} />
        </GlassCard>
        <GlassCard className="py-4">
          <CardHeader icon={<Heart size={16} className="text-rose-400" />} title="Today" />
          <div className="grid grid-cols-2 gap-3 mt-2">
            <Stat label="HRV" value={(latest?.hrv_rmssd_milli ?? latestDaily?.hrv_ms)?.toFixed(1) ?? '—'} unit="ms" color="text-cyan-400" />
            <Stat label="Resting HR" value={`${latest?.resting_heart_rate ?? latestDaily?.resting_hr ?? '—'}`} unit="bpm" color="text-rose-400" />
            <Stat label="SpO₂" value={(latest?.spo2_percentage ?? latestDaily?.spo2)?.toFixed(1) ?? '—'} unit="%" color="text-blue-400" />
            <Stat label="Skin Temp" value={(latest?.skin_temp_celsius ?? latestDaily?.skin_temp_c)?.toFixed(1) ?? '—'} unit="°C" color="text-orange-400" />
            <Stat label="Sleep" value={latestDaily?.sleep_hours?.toFixed(1) ?? '—'} unit="h" color="text-indigo-400" />
            <Stat label="Resp Rate" value={latestDaily?.respiratory_rate?.toFixed(1) ?? '—'} unit="rpm" color="text-teal-400" />
          </div>
        </GlassCard>
      </div>

      {/* 90d stat row (kept from old design for parity) */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        {[
          { label: 'Recovery', value: data.stats.avgRecovery != null ? `${data.stats.avgRecovery}%` : '—', color: rc(data.stats.avgRecovery), sub: 'avg' },
          { label: 'HRV', value: data.stats.avgHRV != null ? `${data.stats.avgHRV}ms` : '—', color: 'text-cyan-400', sub: 'avg' },
          { label: 'Resting HR', value: data.stats.avgRestingHR != null ? `${data.stats.avgRestingHR}bpm` : '—', color: 'text-rose-400', sub: 'avg' },
          { label: 'Day Strain', value: data.stats.avgDayStrain != null ? `${data.stats.avgDayStrain}` : '—', color: 'text-cyan-300', sub: 'avg' },
          { label: 'Sleep Perf', value: data.stats.avgSleepPerformance != null ? `${data.stats.avgSleepPerformance}%` : '—', color: 'text-indigo-400', sub: 'avg' },
          { label: 'Workouts', value: `${data.stats.totalWorkouts}`, color: 'text-amber-400', sub: '180d' },
        ].map(s => (
          <GlassCard key={s.label} className="text-center py-3">
            <div className={`text-xl font-bold ${s.color}`}>{s.value}</div>
            <div className="text-[10px] text-white/30 mt-0.5">{s.label}</div>
            <div className="text-[9px] text-white/15">{s.sub}</div>
          </GlassCard>
        ))}
      </div>

      {/* Recovery 30d chart with color-coded bars */}
      <GlassCard>
        <CardHeader icon={<Activity size={16} className="text-emerald-400" />} title={`Recovery (${range === 'all' ? 'all time' : range + ' days'})`} />
        <ColorBarChart
          data={rangeData.map(d => ({ date: d.date, value: d.recovery_score }))}
          colorFn={(v) => recoveryColor(v)}
          unit="%"
          yMin={0}
          yMax={100}
          refs={[
            { value: 67, label: 'Green', color: 'rgba(34,197,94,0.4)' },
            { value: 34, label: 'Yellow', color: 'rgba(234,179,8,0.35)' },
          ]}
        />
      </GlassCard>

      {/* Recovery distribution */}
      <GlassCard>
        <CardHeader icon={<TrendingUp size={16} className="text-emerald-400" />} title="Recovery Distribution" badge={<span className="text-[10px] text-white/20">{last30.filter(d => d.recovery_score != null).length} days</span>} />
        <div className="mt-2">
          <RecoveryDistribution scores={last30.map(d => d.recovery_score)} />
        </div>
      </GlassCard>

      {/* Monthly performance */}
      <GlassCard>
        <CardHeader icon={<Calendar size={16} className="text-violet-400" />} title="Monthly Performance" badge={<span className="text-[10px] text-white/20">{months.curLabel} vs {months.prevLabel}</span>} />
        <div className="mt-2">
          <MonthlyDelta metrics={[
            { label: 'Recovery', current: months.cur.recovery, previous: months.prev.recovery, unit: '%', decimals: 0, color: '#22c55e' },
            { label: 'Day Strain', current: months.cur.strain, previous: months.prev.strain, unit: '', decimals: 1, color: '#06b6d4' },
            { label: 'Sleep', current: months.cur.sleep, previous: months.prev.sleep, unit: 'h', decimals: 2, color: '#6366f1' },
            { label: 'HRV', current: months.cur.hrv, previous: months.prev.hrv, unit: 'ms', decimals: 1, color: '#22d3ee' },
            { label: 'Resting HR', current: months.cur.rhr, previous: months.prev.rhr, unit: 'bpm', decimals: 0, lowerIsBetter: true, color: '#f43f5e' },
          ]} />
        </div>
      </GlassCard>

      {/* AI Insights */}
      <InsightsPanel days={days || 90} />
    </div>
  );
}

function Stat({ label, value, unit, color }: { label: string; value: string; unit: string; color: string }) {
  return (
    <div>
      <div className="text-[10px] text-white/25 uppercase tracking-wider">{label}</div>
      <div className={`text-lg font-semibold ${color}`}>{value} <span className="text-xs text-white/25">{unit}</span></div>
    </div>
  );
}

function StrainTab({ data, days, rangeData }: { data: WhoopData; days: number; rangeData: DailyT[] }) {
  // Cumulative time in zones (last 30d via workouts)
  const startDate = (() => {
    if (days === 0 || !data.workouts.length) return null;
    const d = new Date();
    d.setDate(d.getDate() - days);
    return d.toISOString();
  })();
  const workoutsInRange = startDate
    ? data.workouts.filter(w => (w.start_time ?? w.created_at) >= startDate)
    : data.workouts;
  const cumZones = [0, 0, 0, 0, 0, 0];
  workoutsInRange.forEach(w => {
    cumZones[0] += w.zone_zero_milli ?? 0;
    cumZones[1] += w.zone_one_milli ?? 0;
    cumZones[2] += w.zone_two_milli ?? 0;
    cumZones[3] += w.zone_three_milli ?? 0;
    cumZones[4] += w.zone_four_milli ?? 0;
    cumZones[5] += w.zone_five_milli ?? 0;
  });
  const totalZoneMs = cumZones.reduce((s, x) => s + x, 0);
  const hasZoneData = totalZoneMs > 0;

  const latestStrain = rangeData[0]?.day_strain ?? data.cycles[0]?.strain ?? null;

  return (
    <div className="space-y-4">
      {/* Big strain gauge + recent workouts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <GlassCard className="flex items-center justify-center py-6">
          <StrainGauge value={latestStrain} label="Today's Strain" sub={rangeData[0]?.date ?? ''} size={200} />
        </GlassCard>
        <GlassCard className="lg:col-span-2">
          <CardHeader icon={<Flame size={16} className="text-orange-400" />} title="Day Strain Trend" />
          <ColorBarChart
            data={rangeData.map(d => ({ date: d.date, value: d.day_strain }))}
            colorFn={(v) => strainColor(v)}
            unit=""
            yMin={0}
            yMax={21}
            decimals={1}
            refs={[
              { value: 14, label: 'Strenuous', color: 'rgba(34,197,94,0.35)' },
              { value: 10, label: 'Moderate', color: 'rgba(59,130,246,0.35)' },
            ]}
          />
        </GlassCard>
      </div>

      {/* Activity strain per workout */}
      <GlassCard>
        <CardHeader icon={<Dumbbell size={16} className="text-amber-400" />} title="Activity Strain" badge={<span className="text-[10px] text-white/20">last {workoutsInRange.length} workouts</span>} />
        <div className="mt-3 space-y-1.5 max-h-64 overflow-y-auto pr-1">
          {workoutsInRange.slice(0, 30).map(w => {
            const strain = w.strain ?? 0;
            const pct = Math.min((strain / 21) * 100, 100);
            return (
              <div key={w.id} className="flex items-center gap-2 text-[11px]">
                <div className="w-20 text-white/40 shrink-0 truncate">{fd(w.start_time ?? w.created_at)}</div>
                <div className="w-24 text-white/70 truncate shrink-0">{w.sport_name}</div>
                <div className="flex-1 h-2.5 bg-white/[0.04] rounded overflow-hidden">
                  <div style={{ width: `${pct}%`, background: strainColor(strain) }} className="h-full" />
                </div>
                <div className="w-10 text-right tabular-nums" style={{ color: strainColor(strain) }}>{strain.toFixed(1)}</div>
              </div>
            );
          })}
          {workoutsInRange.length === 0 && <div className="text-white/20 text-xs py-4 text-center">No workouts in range</div>}
        </div>
      </GlassCard>

      {/* HR-Zones cumulative */}
      <GlassCard>
        <CardHeader icon={<Heart size={16} className="text-rose-400" />} title="Time in Heart-Rate Zones" badge={<span className="text-[10px] text-white/20">{workoutsInRange.length} workouts</span>} />
        {hasZoneData ? (
          <div className="mt-3">
            <HRZoneStackedBar zones={cumZones} variant="horizontal" width={undefined as unknown as number} height={18} legend />
            <div className="grid grid-cols-2 md:grid-cols-6 gap-2 mt-3">
              {cumZones.map((ms, i) => {
                const min = Math.round(ms / 60000);
                return (
                  <div key={i} className="rounded bg-white/[0.03] border border-white/[0.04] p-2">
                    <div className="flex items-center gap-1.5 text-[10px]">
                      <span className="w-2 h-2 rounded-sm" style={{ background: HR_ZONE_COLORS[i] }} />
                      <span className="text-white/45">{HR_ZONE_LABELS[i]}</span>
                    </div>
                    <div className="text-sm font-semibold mt-1" style={{ color: HR_ZONE_COLORS[i] }}>
                      {min >= 60 ? `${Math.floor(min / 60)}h ${min % 60}m` : `${min}m`}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="mt-3 text-[11px] text-white/30 italic">
            HR-zone data is not yet populated by the Whoop sync. Once present (post-workout), zones will visualize here.
          </div>
        )}
      </GlassCard>
    </div>
  );
}

function TrendsTab({ rangeData, days }: { rangeData: DailyT[]; days: number }) {
  // grid of baseline line charts (the Whoop Health Monitor look)
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <GlassCard>
          <CardHeader icon={<TrendingUp size={16} className="text-cyan-400" />} title="HRV" badge={<span className="text-[10px] text-white/20">{rangeData.filter(d => d.hrv_ms != null).length} d</span>} />
          <BaselineLineChart data={rangeData.map(d => ({ date: d.date, value: d.hrv_ms }))} label="HRV" unit="ms" color="#22d3ee" decimals={1} />
        </GlassCard>
        <GlassCard>
          <CardHeader icon={<Heart size={16} className="text-rose-400" />} title="Resting Heart Rate" badge={<span className="text-[10px] text-white/20">{rangeData.filter(d => d.resting_hr != null).length} d</span>} />
          <BaselineLineChart data={rangeData.map(d => ({ date: d.date, value: d.resting_hr }))} label="RHR" unit="bpm" color="#f43f5e" decimals={0} lowerIsBetter />
        </GlassCard>
        <GlassCard>
          <CardHeader icon={<Wind size={16} className="text-teal-400" />} title="Respiratory Rate" badge={<span className="text-[10px] text-white/20">{rangeData.filter(d => d.respiratory_rate != null).length} d</span>} />
          <BaselineLineChart data={rangeData.map(d => ({ date: d.date, value: d.respiratory_rate }))} label="Resp Rate" unit="rpm" color="#2dd4bf" decimals={1} />
        </GlassCard>
        <GlassCard>
          <CardHeader icon={<Activity size={16} className="text-orange-400" />} title="Skin Temperature" badge={<span className="text-[10px] text-white/20">{rangeData.filter(d => d.skin_temp_c != null).length} d</span>} />
          <BaselineLineChart data={rangeData.map(d => ({ date: d.date, value: d.skin_temp_c }))} label="Skin Temp" unit="°C" color="#fb923c" decimals={2} />
        </GlassCard>
        <GlassCard>
          <CardHeader icon={<Droplets size={16} className="text-blue-400" />} title="Blood Oxygen" badge={<span className="text-[10px] text-white/20">{rangeData.filter(d => d.spo2 != null).length} d</span>} />
          <BaselineLineChart data={rangeData.map(d => ({ date: d.date, value: d.spo2 }))} label="SpO₂" unit="%" color="#60a5fa" decimals={1} />
        </GlassCard>
        <GlassCard>
          <CardHeader icon={<Moon size={16} className="text-indigo-400" />} title="Sleep Duration" badge={<span className="text-[10px] text-white/20">{rangeData.filter(d => d.sleep_hours != null).length} d</span>} />
          <BaselineLineChart data={rangeData.map(d => ({ date: d.date, value: d.sleep_hours }))} label="Sleep" unit="h" color="#818cf8" decimals={2} />
        </GlassCard>
      </div>

      {/* Daily log table (kept) */}
      <GlassCard>
        <CardHeader icon={<Activity size={16} />} title="Daily Log" badge={<span className="text-[10px] text-white/20">{rangeData.length} days</span>} />
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-xs">
            <thead><tr className="text-white/25 text-left">
              <th className="pb-2 font-medium">Date</th>
              <th className="pb-2 font-medium">Recovery</th>
              <th className="pb-2 font-medium">Strain</th>
              <th className="pb-2 font-medium">HRV</th>
              <th className="pb-2 font-medium">RHR</th>
              <th className="pb-2 font-medium">SpO₂</th>
              <th className="pb-2 font-medium">Sleep</th>
              <th className="pb-2 font-medium">Perf</th>
              <th className="pb-2 font-medium">Eff</th>
            </tr></thead>
            <tbody className="divide-y divide-white/[0.04]">
              {rangeData.map(d => (
                <tr key={d.date} className="hover:bg-white/[0.02]">
                  <td className="py-1.5 text-white/50">{d.date}</td>
                  <td className={`py-1.5 font-semibold ${rc(d.recovery_score)}`}>{d.recovery_score ?? '—'}%</td>
                  <td className="py-1.5 tabular-nums" style={{ color: d.day_strain != null ? strainColor(d.day_strain) : 'rgba(255,255,255,0.3)' }}>{d.day_strain?.toFixed(1) ?? '—'}</td>
                  <td className="py-1.5 text-cyan-400/70">{d.hrv_ms?.toFixed(0) ?? '—'}</td>
                  <td className="py-1.5 text-rose-400/70">{d.resting_hr ?? '—'}</td>
                  <td className="py-1.5 text-blue-400/70">{d.spo2?.toFixed(1) ?? '—'}%</td>
                  <td className="py-1.5 text-indigo-400/70">{d.sleep_hours?.toFixed(1) ?? '—'}h</td>
                  <td className="py-1.5 text-white/40">{d.sleep_performance ?? '—'}%</td>
                  <td className="py-1.5 text-white/40">{d.sleep_efficiency?.toFixed(0) ?? '—'}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </div>
  );
}

function SleepTab({ data, rangeData, days }: { data: WhoopData; rangeData: DailyT[]; days: number }) {
  const latest = data.daily.find(d => d.sleep_hours != null);
  const stagesDays = rangeData.filter(d => d.sleep_hours != null);

  // Average stages last 30d (for the donut if no latest)
  const last30 = data.daily.slice(0, 30).filter(d => d.sleep_hours != null);
  const avg = (key: keyof DailyT): number => {
    const vs = last30.map(d => d[key]).filter((v): v is number => typeof v === 'number');
    return vs.length ? vs.reduce((s, v) => s + v, 0) / vs.length : 0;
  };

  // Use latest day for the donut if all stages present, else avg
  const donutData = latest && latest.deep_sleep_hours != null && latest.rem_hours != null && latest.light_sleep_hours != null
    ? { awake: latest.awake_hours ?? 0, light: latest.light_sleep_hours ?? 0, deep: latest.deep_sleep_hours ?? 0, rem: latest.rem_hours ?? 0, date: latest.date }
    : { awake: avg('awake_hours'), light: avg('light_sleep_hours'), deep: avg('deep_sleep_hours'), rem: avg('rem_hours'), date: '30d avg' };

  return (
    <div className="space-y-4">
      {/* Stages donut + key stats */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <GlassCard className="py-6">
          <CardHeader icon={<Moon size={16} className="text-indigo-400" />} title={`Sleep Stages · ${donutData.date}`} />
          <div className="mt-3">
            <SleepStagesDonut awake={donutData.awake} light={donutData.light} deep={donutData.deep} rem={donutData.rem} />
          </div>
        </GlassCard>
        <GlassCard className="lg:col-span-2">
          <CardHeader icon={<Activity size={16} className="text-violet-400" />} title="Sleep Performance" />
          <ColorBarChart
            data={rangeData.map(d => ({ date: d.date, value: d.sleep_performance }))}
            colorFn={(v) => v >= 90 ? '#22c55e' : v >= 70 ? '#eab308' : '#ef4444'}
            unit="%"
            yMin={0}
            yMax={100}
            refs={[{ value: 85, label: '85% target', color: 'rgba(99,102,241,0.4)' }]}
          />
        </GlassCard>
      </div>

      {/* Sleep need vs got */}
      <GlassCard>
        <CardHeader icon={<Moon size={16} className="text-indigo-400" />} title="Sleep Need vs Got" badge={<span className="text-[10px] text-white/20">stacked need · line = got</span>} />
        <div className="mt-2">
          <SleepNeedBar days={stagesDays.map(d => ({
            date: d.date,
            got: d.sleep_hours,
            baseline: d.sleep_baseline_hours ?? null,
            debt: d.sleep_debt_hours ?? null,
            strainNeed: d.sleep_strain_need_hours ?? null,
          }))} />
        </div>
      </GlassCard>

      {/* Stage composition over time */}
      <GlassCard>
        <CardHeader icon={<TrendingUp size={16} className="text-violet-400" />} title="Sleep Composition" badge={<span className="text-[10px] text-white/20">{stagesDays.length} nights</span>} />
        <div className="mt-2">
          <SleepStagesStackedBar data={stagesDays.map(d => ({
            date: d.date,
            awake: d.awake_hours ?? null,
            light: d.light_sleep_hours,
            deep: d.deep_sleep_hours,
            rem: d.rem_hours,
          }))} />
        </div>
      </GlassCard>

      {/* Consistency heatmap */}
      <GlassCard>
        <CardHeader icon={<Calendar size={16} className="text-indigo-400" />} title="Bedtime / Waketime Consistency" badge={<span className="text-[10px] text-white/20">{stagesDays.filter(d => d.bedtime && d.waketime).length} nights</span>} />
        <div className="mt-2">
          <SleepConsistencyHeatmap days={stagesDays.map(d => ({ date: d.date, bedtime: d.bedtime ?? null, waketime: d.waketime ?? null }))} />
        </div>
      </GlassCard>

      {/* Respiratory rate baseline trend */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <GlassCard>
          <CardHeader icon={<Wind size={16} className="text-teal-400" />} title="Respiratory Rate" />
          <BaselineLineChart data={rangeData.map(d => ({ date: d.date, value: d.respiratory_rate }))} label="Resp" unit="rpm" color="#2dd4bf" decimals={1} />
        </GlassCard>
        <GlassCard>
          <CardHeader icon={<Activity size={16} className="text-emerald-400" />} title="Sleep Efficiency" />
          <BaselineLineChart data={rangeData.map(d => ({ date: d.date, value: d.sleep_efficiency }))} label="Efficiency" unit="%" color="#34d399" decimals={1} />
        </GlassCard>
      </div>

      {/* Detail table */}
      <GlassCard>
        <CardHeader icon={<Moon size={16} className="text-indigo-400" />} title="Sleep Detail" />
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-xs">
            <thead><tr className="text-white/25 text-left">
              <th className="pb-2 font-medium">Date</th>
              <th className="pb-2 font-medium">Total</th>
              <th className="pb-2 font-medium">Perf</th>
              <th className="pb-2 font-medium">Eff</th>
              <th className="pb-2 font-medium">REM</th>
              <th className="pb-2 font-medium">Deep</th>
              <th className="pb-2 font-medium">Light</th>
              <th className="pb-2 font-medium">Awake</th>
              <th className="pb-2 font-medium">Resp</th>
              <th className="pb-2 font-medium">Cycles</th>
              <th className="pb-2 font-medium">Disturb</th>
            </tr></thead>
            <tbody className="divide-y divide-white/[0.04]">
              {stagesDays.slice(0, 30).map(d => (
                <tr key={d.date} className="hover:bg-white/[0.02]">
                  <td className="py-1.5 text-white/50">{d.date}</td>
                  <td className={`py-1.5 font-semibold ${(d.sleep_hours ?? 0) >= 7 ? 'text-indigo-400' : (d.sleep_hours ?? 0) >= 6 ? 'text-amber-400' : 'text-red-400'}`}>{d.sleep_hours?.toFixed(1)}h</td>
                  <td className="py-1.5 text-white/50">{d.sleep_performance ?? '—'}%</td>
                  <td className="py-1.5 text-white/40">{d.sleep_efficiency?.toFixed(0) ?? '—'}%</td>
                  <td className="py-1.5 text-purple-400/70">{d.rem_hours?.toFixed(1) ?? '—'}h</td>
                  <td className="py-1.5 text-blue-400/70">{d.deep_sleep_hours?.toFixed(1) ?? '—'}h</td>
                  <td className="py-1.5 text-teal-400/70">{d.light_sleep_hours?.toFixed(1) ?? '—'}h</td>
                  <td className="py-1.5 text-white/30">{d.awake_hours?.toFixed(1) ?? '—'}h</td>
                  <td className="py-1.5 text-teal-300/70">{d.respiratory_rate?.toFixed(1) ?? '—'}</td>
                  <td className="py-1.5 text-white/40">{d.sleep_cycle_count ?? '—'}</td>
                  <td className="py-1.5 text-white/30">{d.disturbance_count ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </div>
  );
}

function WorkoutsTab({ data }: { data: WhoopData }) {
  const sorted = [...data.workouts].sort((a, b) => (b.start_time ?? b.created_at).localeCompare(a.start_time ?? a.created_at));
  const top = sorted.slice(0, 30);

  // Strain per workout, sorted
  const strainSorted = [...sorted].filter(w => w.strain != null).sort((a, b) => (b.strain ?? 0) - (a.strain ?? 0)).slice(0, 15);

  // Totals
  const totalKcal = sorted.reduce((s, w) => s + (w.kilojoule ?? 0) * 0.239, 0);
  const totalMin = sorted.reduce((s, w) => {
    if (w.start_time && w.end_time) {
      return s + (new Date(w.end_time).getTime() - new Date(w.start_time).getTime()) / 60000;
    }
    return s;
  }, 0);
  const avgStrain = sorted.length ? sorted.reduce((s, w) => s + (w.strain ?? 0), 0) / sorted.length : 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <GlassCard className="text-center py-3"><div className="text-xl font-bold text-amber-400">{sorted.length}</div><div className="text-[10px] text-white/30 mt-0.5">Workouts</div></GlassCard>
        <GlassCard className="text-center py-3"><div className="text-xl font-bold" style={{ color: strainColor(avgStrain) }}>{avgStrain.toFixed(1)}</div><div className="text-[10px] text-white/30 mt-0.5">Avg Strain</div></GlassCard>
        <GlassCard className="text-center py-3"><div className="text-xl font-bold text-orange-400">{Math.round(totalKcal).toLocaleString()}</div><div className="text-[10px] text-white/30 mt-0.5">Calories burned</div></GlassCard>
        <GlassCard className="text-center py-3"><div className="text-xl font-bold text-rose-400">{Math.round(totalMin / 60)}h</div><div className="text-[10px] text-white/30 mt-0.5">Time training</div></GlassCard>
      </div>

      {/* Heatmap */}
      <GlassCard>
        <CardHeader icon={<Calendar size={16} className="text-amber-400" />} title="Workout Frequency" badge={<span className="text-[10px] text-white/20">weekday × hour</span>} />
        <div className="mt-3">
          <WorkoutHeatmap workouts={sorted} />
        </div>
      </GlassCard>

      {/* Top strain */}
      <GlassCard>
        <CardHeader icon={<Flame size={16} className="text-orange-400" />} title="Highest-Strain Workouts" />
        <div className="mt-3 space-y-1.5">
          {strainSorted.map(w => {
            const strain = w.strain ?? 0;
            const pct = Math.min((strain / 21) * 100, 100);
            return (
              <div key={w.id} className="flex items-center gap-2 text-[11px]">
                <div className="w-20 text-white/40 shrink-0 truncate">{fd(w.start_time ?? w.created_at)}</div>
                <div className="w-24 text-white/70 truncate shrink-0">{w.sport_name}</div>
                <div className="flex-1 h-2.5 bg-white/[0.04] rounded overflow-hidden">
                  <div style={{ width: `${pct}%`, background: strainColor(strain) }} className="h-full" />
                </div>
                <div className="w-10 text-right tabular-nums" style={{ color: strainColor(strain) }}>{strain.toFixed(1)}</div>
              </div>
            );
          })}
        </div>
      </GlassCard>

      {/* Detail table */}
      <GlassCard>
        <CardHeader icon={<Dumbbell size={16} className="text-amber-400" />} title="Workout History" />
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-xs">
            <thead><tr className="text-white/25 text-left">
              <th className="pb-2 font-medium">Date</th>
              <th className="pb-2 font-medium">Activity</th>
              <th className="pb-2 font-medium">Strain</th>
              <th className="pb-2 font-medium">Avg HR</th>
              <th className="pb-2 font-medium">Max HR</th>
              <th className="pb-2 font-medium">Calories</th>
              <th className="pb-2 font-medium">Zones</th>
            </tr></thead>
            <tbody className="divide-y divide-white/[0.04]">
              {top.map(w => {
                const zones = [w.zone_zero_milli, w.zone_one_milli, w.zone_two_milli, w.zone_three_milli, w.zone_four_milli, w.zone_five_milli];
                const hasZones = zones.some(z => (z ?? 0) > 0);
                return (
                  <tr key={w.id} className="hover:bg-white/[0.02]">
                    <td className="py-1.5 text-white/50">{fd(w.start_time ?? w.created_at)}</td>
                    <td className="py-1.5 text-white/70 font-medium">{w.sport_name}</td>
                    <td className="py-1.5 tabular-nums" style={{ color: w.strain != null ? strainColor(w.strain) : 'rgba(255,255,255,0.3)' }}>{w.strain?.toFixed(1) ?? '—'}</td>
                    <td className="py-1.5 text-rose-400/70">{w.average_heart_rate ?? '—'}</td>
                    <td className="py-1.5 text-red-400">{w.max_heart_rate ?? '—'}</td>
                    <td className="py-1.5 text-white/40">{w.kilojoule ? Math.round(w.kilojoule * 0.239) : '—'} kcal</td>
                    <td className="py-1.5">{hasZones ? <HRZoneStackedBar zones={zones} width={120} height={6} /> : <span className="text-white/15">—</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </div>
  );
}

function HealthContent() {
  const searchParams = useSearchParams();
  const activeTab = searchParams.get('tab') || 'overview';
  const [range, setRange] = useState('30');
  const { data, loading, refresh } = useAutoRefresh<WhoopData>('/api/whoop', 30000);
  const { data: tokenStatus } = useAutoRefresh<{ has_access_token: boolean; has_refresh_token: boolean; token_remaining_seconds: number }>('/api/whoop/status', 60000);
  const days = range === 'all' ? 0 : parseInt(range);
  const isConnected = !!(tokenStatus?.has_access_token && (tokenStatus.token_remaining_seconds > 0 || tokenStatus.has_refresh_token));

  if (loading && !data) return <div className="text-white/30 text-sm animate-pulse">Loading Whoop data...</div>;

  if (!data || (!data.recovery.length && !data.daily.length && !data.profile)) {
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <h1 className="text-xl font-bold mb-2 text-white/90">Health & Wellness</h1>
        <GlassCard><p className="text-sm text-white/40">No Whoop data available.</p></GlassCard>
      </motion.div>
    );
  }

  const latest = data.recovery[0];
  const latestDaily = data.daily[0];
  const last30 = data.daily.slice(0, 30);
  const rangeData = days === 0 ? data.daily : data.daily.slice(0, days);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-2 gap-2">
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-white/90">Health & Wellness</h1>
          <p className="text-xs text-white/30 truncate">
            {data.profile?.first_name || 'User'}
            {data.stats.totalDays > 0 && ` · ${data.stats.totalDays} days tracked`}
            {data.stats.dateRange && ` · ${fd(data.stats.dateRange.from)} — ${fd(data.stats.dateRange.to)}`}
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {data.profile && (
            <div className="hidden sm:flex items-center gap-3 text-[10px] text-white/25">
              <span>{data.profile.height_meter}m</span>
              <span>{data.profile.weight_kilogram}kg</span>
              <span>Max HR: {data.profile.max_heart_rate}</span>
            </div>
          )}
          <a
            href="/whoop/login"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border transition-all text-xs ${
              isConnected
                ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400/70 hover:bg-emerald-500/15 hover:text-emerald-400'
                : 'bg-white/[0.06] border-white/[0.08] text-white/50 hover:bg-white/[0.10] hover:border-white/[0.15] hover:text-white/80'
            }`}
          >
            {isConnected ? <CheckCircle size={12} /> : <ExternalLink size={12} />}
            <span>{isConnected ? `Connected${tokenStatus?.has_refresh_token ? ' · auto-refresh' : ''}` : 'Connect Whoop'}</span>
          </a>
        </div>
      </div>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-4 gap-2">
        <TabBar tabs={tabs} defaultTab="overview" />
        {(activeTab === 'overview' || activeTab === 'trends' || activeTab === 'sleep' || activeTab === 'strain' || activeTab === 'workouts') && (
          <TimeRangeSelector value={range} onChange={setRange} />
        )}
      </div>

      {/* ───────── OVERVIEW ───────── */}
      {activeTab === 'overview' && (
        <OverviewTab data={data} range={range} days={days} rangeData={rangeData} latest={latest} latestDaily={latestDaily} />
      )}

      {/* ───────── STRAIN ───────── */}
      {activeTab === 'strain' && (
        <StrainTab data={data} days={days} rangeData={rangeData} />
      )}

      {/* ───────── TRENDS ───────── */}
      {activeTab === 'trends' && (
        <TrendsTab rangeData={rangeData} days={days} />
      )}

      {/* ───────── SLEEP ───────── */}
      {activeTab === 'sleep' && (
        <SleepTab data={data} rangeData={rangeData} days={days} />
      )}

      {/* ───────── WORKOUTS ───────── */}
      {activeTab === 'workouts' && (
        <WorkoutsTab data={data} />
      )}

      {/* ───────── BODY COMPOSITION ───────── */}
      {activeTab === 'body-comp' && (
        <BodyCompositionTab />
      )}

      {/* ───────── BLOOD WORK ───────── */}
      {activeTab === 'bio-age' && (
        <BioAgeTab />
      )}

      {activeTab === 'glucose' && (
        <GlucoseTab />
      )}

      {activeTab === 'blood' && (
        <BloodWorkTab bloodPanels={data.bloodPanels} onRefresh={() => refresh()} />
      )}

      {/* ───────── SUPPLEMENTS ───────── */}
      {activeTab === 'supplements' && (
        <SupplementsTab />
      )}
    </motion.div>
  );
}

export default function HealthPage() {
  return <Suspense fallback={<div className="text-white/30 text-sm">Loading...</div>}><HealthContent /></Suspense>;
}
