'use client';

import { useState } from 'react';

/**
 * ColorBarChart — vertical bars with per-bar color (e.g. recovery, strain).
 * Drop-in replacement for the legacy ScaledBarChart but with hex colors instead of tailwind classes,
 * plus optional reference lines.
 */

interface Datum {
  date: string;
  value: number | null | undefined;
}

interface Props {
  data: Datum[]; // either order; we sort ascending
  /** Function returning a hex color for the value. */
  colorFn: (v: number) => string;
  unit?: string;
  height?: number;
  /** Optional reference lines (e.g. baseline) — value + label + color. */
  refs?: { value: number; label: string; color?: string }[];
  /** Force min/max. */
  yMin?: number;
  yMax?: number;
  decimals?: number;
}

export function ColorBarChart({
  data,
  colorFn,
  unit = '',
  height = 120,
  refs = [],
  yMin,
  yMax,
  decimals = 0,
}: Props) {
  const sorted = [...data].sort((a, b) => a.date.localeCompare(b.date));
  const [hover, setHover] = useState<number | null>(null);

  const values = sorted.map(d => d.value).filter((v): v is number => v != null && !isNaN(v as number));
  if (values.length === 0) {
    return <div className="text-white/20 text-xs py-6 text-center">No data</div>;
  }
  const allValues = [...values, ...refs.map(r => r.value)];
  const lo = yMin ?? Math.min(0, ...allValues);
  const hi = yMax ?? Math.max(...allValues);
  const padHi = hi + (hi - lo) * 0.05 || hi + 1;
  const padLo = lo;
  const range = padHi - padLo || 1;

  const fmt = (v: number) => (Number.isInteger(v) ? `${v}` : v.toFixed(decimals));

  return (
    <div>
      <div className="flex gap-1 relative" style={{ height }}>
        {/* Y axis */}
        <div className="absolute left-0 top-0 bottom-0 w-8 flex flex-col justify-between text-[8px] text-white/15 pointer-events-none z-10">
          <span>{fmt(padHi)}{unit}</span>
          <span>{fmt((padHi + padLo) / 2)}{unit}</span>
          <span>{fmt(padLo)}{unit}</span>
        </div>
        <div className="relative ml-9 flex-1 flex items-end gap-[1px] h-full">
          {/* Ref lines */}
          {refs.map((r, i) => {
            const y = (1 - (r.value - padLo) / range) * 100;
            return (
              <div key={i} className="absolute left-0 right-0 pointer-events-none" style={{ top: `${y}%` }}>
                <div className="h-px w-full" style={{ background: r.color || 'rgba(255,255,255,0.18)' }} />
                <div className="text-[8px] absolute right-0 -top-3" style={{ color: r.color || 'rgba(255,255,255,0.35)' }}>
                  {r.label}
                </div>
              </div>
            );
          })}
          {sorted.map((d, i) => {
            const v = d.value;
            const h = v != null ? Math.max(((v - padLo) / range) * 100, 1.5) : 0;
            const c = v != null ? colorFn(v as number) : 'rgba(255,255,255,0.08)';
            return (
              <div
                key={i}
                className="flex-1 h-full flex flex-col justify-end relative"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              >
                <div className="w-full rounded-sm transition-opacity hover:opacity-80" style={{ height: `${h}%`, background: c }} />
                {hover === i && v != null && (
                  <div className="absolute -top-7 left-1/2 -translate-x-1/2 bg-black/90 border border-white/10 rounded px-1.5 py-0.5 text-[9px] whitespace-nowrap z-20">
                    <span className="text-white/85">{typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(1)) : v}{unit}</span>
                    <span className="text-white/40"> · {d.date}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <div className="flex justify-between ml-9 mt-1 text-[8px] text-white/15">
        <span>{sorted[0]?.date}</span>
        <span>{sorted[sorted.length - 1]?.date}</span>
      </div>
    </div>
  );
}
