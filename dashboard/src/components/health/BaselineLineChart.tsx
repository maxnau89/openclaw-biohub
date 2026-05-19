'use client';

/**
 * BaselineLineChart — line trend with a baseline band (mean ± stddev over the window).
 * Pure SVG, no deps.
 *
 * Data is expected in *display* order (chronological ascending or descending) — we sort
 * internally to be safe. Days with null values are skipped (no point) but still take
 * a horizontal slot.
 */

import { useMemo, useState } from 'react';

interface Point {
  date: string;
  value: number | null | undefined;
}

interface Props {
  data: Point[];
  label: string;
  unit: string;
  color: string;
  /** Optional formatter for tooltip / Y-axis ticks. */
  format?: (v: number) => string;
  /** If true, lower values are better (e.g. RHR) — visual cue only. */
  lowerIsBetter?: boolean;
  /** Override min/max scale; defaults to auto-fit with ~5% padding. */
  yMin?: number;
  yMax?: number;
  /** Render height in px. */
  height?: number;
  /** Show baseline band. Defaults true. */
  showBaseline?: boolean;
  /** Number of decimals for tooltip. */
  decimals?: number;
}

export function BaselineLineChart({
  data,
  label,
  unit,
  color,
  format,
  yMin,
  yMax,
  height = 140,
  showBaseline = true,
  decimals = 1,
}: Props) {
  // Sort ascending by date for left-to-right rendering
  const sorted = useMemo(() => {
    return [...data].sort((a, b) => a.date.localeCompare(b.date));
  }, [data]);

  const values = sorted.map(d => d.value).filter((v): v is number => v != null && !isNaN(v as number));
  const [hover, setHover] = useState<{ idx: number; x: number; y: number } | null>(null);

  if (values.length === 0) {
    return <div className="text-white/20 text-xs py-6 text-center">No data</div>;
  }

  // Baseline (mean ± stddev)
  const mean = values.reduce((s, v) => s + v, 0) / values.length;
  const variance = values.reduce((s, v) => s + (v - mean) ** 2, 0) / values.length;
  const std = Math.sqrt(variance);
  const baselineLow = mean - std;
  const baselineHigh = mean + std;

  // Scale
  const minV = yMin ?? Math.min(...values, baselineLow);
  const maxV = yMax ?? Math.max(...values, baselineHigh);
  const padding = (maxV - minV) * 0.08 || 1;
  const lo = minV - padding;
  const hi = maxV + padding;
  const range = hi - lo || 1;

  // Layout
  const W = 800;
  const H = height;
  const PAD_L = 36;
  const PAD_R = 8;
  const PAD_T = 6;
  const PAD_B = 18;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;

  const n = sorted.length;
  const xOf = (i: number) => PAD_L + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const yOf = (v: number) => PAD_T + (1 - (v - lo) / range) * plotH;

  // Build path skipping nulls
  let pathD = '';
  let pen = false;
  for (let i = 0; i < n; i++) {
    const v = sorted[i].value;
    if (v == null || isNaN(v as number)) {
      pen = false;
      continue;
    }
    const x = xOf(i);
    const y = yOf(v as number);
    pathD += pen ? ` L ${x.toFixed(1)} ${y.toFixed(1)}` : ` M ${x.toFixed(1)} ${y.toFixed(1)}`;
    pen = true;
  }

  const baselineY = yOf(mean);
  const bandTop = yOf(baselineHigh);
  const bandBot = yOf(baselineLow);

  // Y ticks (3 of them)
  const yTicks = [hi, (hi + lo) / 2, lo];

  const fmt = (v: number) => (format ? format(v) : Number.isInteger(v) ? `${v}` : v.toFixed(decimals));

  const hoverPoint = hover ? sorted[hover.idx] : null;

  return (
    <div className="w-full">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" preserveAspectRatio="none" style={{ height }}>
        {/* Y grid */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line x1={PAD_L} x2={W - PAD_R} y1={yOf(t)} y2={yOf(t)} stroke="rgba(255,255,255,0.05)" strokeWidth={1} />
            <text x={PAD_L - 4} y={yOf(t) + 3} fontSize={9} fill="rgba(255,255,255,0.25)" textAnchor="end">
              {fmt(t)}
            </text>
          </g>
        ))}

        {/* Baseline band */}
        {showBaseline && (
          <>
            <rect
              x={PAD_L}
              y={Math.min(bandTop, bandBot)}
              width={plotW}
              height={Math.abs(bandBot - bandTop)}
              fill={color}
              opacity={0.08}
            />
            <line
              x1={PAD_L}
              x2={W - PAD_R}
              y1={baselineY}
              y2={baselineY}
              stroke={color}
              strokeOpacity={0.4}
              strokeDasharray="3 3"
              strokeWidth={1}
            />
          </>
        )}

        {/* Line */}
        <path d={pathD} fill="none" stroke={color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />

        {/* Points */}
        {sorted.map((d, i) =>
          d.value != null ? (
            <circle key={i} cx={xOf(i)} cy={yOf(d.value)} r={1.6} fill={color} />
          ) : null
        )}

        {/* Hover overlay */}
        <rect
          x={PAD_L}
          y={PAD_T}
          width={plotW}
          height={plotH}
          fill="transparent"
          onMouseLeave={() => setHover(null)}
          onMouseMove={e => {
            const rect = (e.currentTarget as SVGRectElement).getBoundingClientRect();
            const relX = ((e.clientX - rect.left) / rect.width) * plotW;
            const idx = Math.max(0, Math.min(n - 1, Math.round((relX / plotW) * (n - 1))));
            setHover({ idx, x: xOf(idx), y: sorted[idx].value != null ? yOf(sorted[idx].value as number) : H / 2 });
          }}
        />

        {/* Hover marker */}
        {hover && hoverPoint && hoverPoint.value != null && (
          <>
            <line x1={hover.x} x2={hover.x} y1={PAD_T} y2={H - PAD_B} stroke="rgba(255,255,255,0.15)" strokeWidth={1} />
            <circle cx={hover.x} cy={hover.y} r={3.5} fill={color} stroke="#0b0b0b" strokeWidth={1.5} />
          </>
        )}

        {/* X-axis: first/last */}
        <text x={PAD_L} y={H - 4} fontSize={9} fill="rgba(255,255,255,0.2)">
          {sorted[0]?.date}
        </text>
        <text x={W - PAD_R} y={H - 4} fontSize={9} fill="rgba(255,255,255,0.2)" textAnchor="end">
          {sorted[n - 1]?.date}
        </text>
      </svg>

      {/* Footer: latest value + baseline */}
      <div className="flex items-center justify-between mt-2 text-[10px]">
        <div className="flex items-center gap-3">
          <div>
            <span className="text-white/30">{label}: </span>
            <span style={{ color }} className="font-semibold">
              {sorted[n - 1]?.value != null ? fmt(sorted[n - 1].value as number) : '—'}
              {unit}
            </span>
          </div>
          {showBaseline && (
            <div className="text-white/25">
              baseline {fmt(mean)}±{fmt(std)}
              {unit}
            </div>
          )}
        </div>
        {hover && hoverPoint && hoverPoint.value != null && (
          <div className="text-white/50">
            {hoverPoint.date}: <span style={{ color }} className="font-semibold">{fmt(hoverPoint.value as number)}{unit}</span>
          </div>
        )}
      </div>
    </div>
  );
}
