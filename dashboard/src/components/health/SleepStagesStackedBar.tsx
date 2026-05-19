'use client';

import { useState } from 'react';
import { SLEEP_COLORS } from './colors';

interface Day {
  date: string;
  awake: number | null;
  light: number | null;
  deep: number | null;
  rem: number | null;
}

interface Props {
  data: Day[]; // any order; we sort ascending
  height?: number;
}

export function SleepStagesStackedBar({ data, height = 160 }: Props) {
  const sorted = [...data].sort((a, b) => a.date.localeCompare(b.date));
  const [hover, setHover] = useState<number | null>(null);

  if (sorted.length === 0) {
    return <div className="text-white/20 text-xs py-6 text-center">No data</div>;
  }

  // Find max total to set y-scale
  const totals = sorted.map(d => (d.awake ?? 0) + (d.light ?? 0) + (d.deep ?? 0) + (d.rem ?? 0));
  const maxTotal = Math.max(...totals, 8);
  const yMax = Math.ceil(maxTotal);

  return (
    <div>
      <div className="flex gap-2 mb-2 text-[10px]">
        <Legend color={SLEEP_COLORS.awake} label="Awake" />
        <Legend color={SLEEP_COLORS.light} label="Light" />
        <Legend color={SLEEP_COLORS.deep} label="Deep" />
        <Legend color={SLEEP_COLORS.rem} label="REM" />
      </div>
      <div className="relative">
        <div className="absolute left-0 top-0 bottom-0 w-7 flex flex-col justify-between text-[8px] text-white/15 pointer-events-none">
          <span>{yMax}h</span>
          <span>{(yMax / 2).toFixed(0)}h</span>
          <span>0h</span>
        </div>
        <div className="flex items-end gap-[1px] ml-8" style={{ height }}>
          {sorted.map((d, i) => {
            const total = (d.awake ?? 0) + (d.light ?? 0) + (d.deep ?? 0) + (d.rem ?? 0);
            return (
              <div
                key={d.date}
                className="flex-1 h-full flex flex-col-reverse group relative"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              >
                {/* order bottom→top: deep, rem, light, awake (matches Whoop bias: deep visualized at bottom = "deep") */}
                <Seg height={((d.deep ?? 0) / yMax) * 100} color={SLEEP_COLORS.deep} />
                <Seg height={((d.rem ?? 0) / yMax) * 100} color={SLEEP_COLORS.rem} />
                <Seg height={((d.light ?? 0) / yMax) * 100} color={SLEEP_COLORS.light} />
                <Seg height={((d.awake ?? 0) / yMax) * 100} color={SLEEP_COLORS.awake} />

                {hover === i && (
                  <div className="absolute -top-1 left-1/2 -translate-x-1/2 -translate-y-full bg-black/90 border border-white/10 rounded px-2 py-1 text-[10px] whitespace-nowrap z-10">
                    <div className="text-white/60 mb-0.5">{d.date} · {total.toFixed(1)}h</div>
                    <div className="flex gap-2">
                      <span style={{ color: SLEEP_COLORS.deep }}>Deep {(d.deep ?? 0).toFixed(1)}</span>
                      <span style={{ color: SLEEP_COLORS.rem }}>REM {(d.rem ?? 0).toFixed(1)}</span>
                      <span style={{ color: SLEEP_COLORS.light }}>Light {(d.light ?? 0).toFixed(1)}</span>
                      <span style={{ color: SLEEP_COLORS.awake }}>Awake {(d.awake ?? 0).toFixed(1)}</span>
                    </div>
                  </div>
                )}
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

function Seg({ height, color }: { height: number; color: string }) {
  if (height <= 0) return null;
  return <div style={{ height: `${height}%`, background: color }} className="w-full" />;
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-white/45">
      <span className="w-2 h-2 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  );
}
