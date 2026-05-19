'use client';

import { SLEEP_COLORS } from './colors';

/**
 * SleepNeedBar — visualizes Sleep Got vs Sleep Need (stacked: baseline + debt + strain need).
 * For a single most-recent day, but designed to be horizontally stacked next to multiple.
 */

interface DayBars {
  date: string;
  got: number | null;
  baseline: number | null;
  debt: number | null;
  strainNeed: number | null;
}

interface Props {
  days: DayBars[]; // ascending order
  height?: number;
}

export function SleepNeedBar({ days, height = 160 }: Props) {
  const sorted = [...days].sort((a, b) => a.date.localeCompare(b.date));
  if (sorted.length === 0) {
    return <div className="text-white/20 text-xs py-6 text-center">No data</div>;
  }
  const totals = sorted.map(d => Math.max((d.baseline ?? 0) + (d.debt ?? 0) + (d.strainNeed ?? 0), d.got ?? 0));
  const yMax = Math.max(...totals, 8);

  return (
    <div>
      <div className="flex gap-3 mb-2 text-[10px] flex-wrap">
        <Legend color={SLEEP_COLORS.deep} label="Baseline need" />
        <Legend color={SLEEP_COLORS.rem} label="+ Debt" />
        <Legend color={SLEEP_COLORS.light} label="+ Strain need" />
        <Legend color="rgba(255,255,255,0.6)" label="Got (line)" />
      </div>
      <div className="relative">
        <div className="absolute left-0 top-0 bottom-0 w-7 flex flex-col justify-between text-[8px] text-white/15 pointer-events-none">
          <span>{yMax.toFixed(0)}h</span>
          <span>{(yMax / 2).toFixed(0)}h</span>
          <span>0h</span>
        </div>
        <div className="flex items-end gap-[1px] ml-8 relative" style={{ height }}>
          {sorted.map(d => {
            const baseline = d.baseline ?? 0;
            const debt = d.debt ?? 0;
            const strain = d.strainNeed ?? 0;
            const got = d.got;
            return (
              <div key={d.date} className="flex-1 h-full relative group">
                {/* Need stack (baseline+debt+strain) */}
                <div className="absolute inset-x-0 bottom-0 flex flex-col-reverse">
                  <div style={{ height: `${(baseline / yMax) * 100}%`, background: SLEEP_COLORS.deep, opacity: 0.6 }} />
                  <div style={{ height: `${(debt / yMax) * 100}%`, background: SLEEP_COLORS.rem, opacity: 0.6 }} />
                  <div style={{ height: `${(strain / yMax) * 100}%`, background: SLEEP_COLORS.light, opacity: 0.6 }} />
                </div>
                {/* "Got" marker as a horizontal line */}
                {got != null && (
                  <div
                    className="absolute left-0 right-0 h-[2px]"
                    style={{ bottom: `${(got / yMax) * 100}%`, background: 'rgba(255,255,255,0.85)' }}
                  />
                )}
                <div className="absolute -top-7 left-1/2 -translate-x-1/2 bg-black/90 border border-white/10 rounded px-1.5 py-0.5 text-[9px] whitespace-nowrap z-10 opacity-0 group-hover:opacity-100 pointer-events-none">
                  <div className="text-white/70 mb-0.5">{d.date}</div>
                  <div className="text-white/55">Got {got != null ? got.toFixed(1) : '—'}h / Need {(baseline + debt + strain).toFixed(1)}h</div>
                </div>
              </div>
            );
          })}
        </div>
        <div className="flex justify-between ml-8 mt-1 text-[8px] text-white/15">
          <span>{sorted[0].date}</span>
          <span>{sorted[sorted.length - 1].date}</span>
        </div>
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-white/45">
      <span className="w-2 h-2 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  );
}
