'use client';

import { strainColor, strainLabel } from './colors';

/**
 * StrainGauge — Whoop-style 0..21 strain arc.
 * Uses Whoop's exponential-feeling color ramp; the value is shown big in the middle.
 */

interface Props {
  value: number | null | undefined;
  size?: number;
  label?: string;
  sub?: string;
}

export function StrainGauge({ value, size = 180, label = 'Day Strain', sub }: Props) {
  const v = value == null || isNaN(value) ? null : Math.max(0, Math.min(21, value));
  const pct = v == null ? 0 : v / 21;
  const color = strainColor(v);
  const stroke = 14;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  // Arc spans 270° (from 135° to 45° clockwise, the bottom open)
  const startAngle = 135;
  const endAngle = 45 + 360; // 405
  const span = endAngle - startAngle; // 270
  const valueAngle = startAngle + span * pct;

  const polar = (deg: number) => {
    const rad = (deg * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  };
  const s = polar(startAngle);
  const e = polar(endAngle);
  const v1 = polar(valueAngle);

  const largeArcBg = span > 180 ? 1 : 0;
  const largeArcVal = span * pct > 180 ? 1 : 0;

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* Background track */}
        <path
          d={`M ${s.x} ${s.y} A ${r} ${r} 0 ${largeArcBg} 1 ${e.x} ${e.y}`}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        {/* Value arc */}
        {v != null && v > 0 && (
          <path
            d={`M ${s.x} ${s.y} A ${r} ${r} 0 ${largeArcVal} 1 ${v1.x} ${v1.y}`}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
          />
        )}
        {/* Value text */}
        <text
          x={cx}
          y={cy - 4}
          textAnchor="middle"
          fontSize={size * 0.28}
          fontWeight={700}
          fill={color}
        >
          {v != null ? v.toFixed(1) : '—'}
        </text>
        <text
          x={cx}
          y={cy + size * 0.13}
          textAnchor="middle"
          fontSize={size * 0.08}
          fill="rgba(255,255,255,0.5)"
          letterSpacing={1}
        >
          {strainLabel(v).toUpperCase()}
        </text>
      </svg>
      <div className="text-[11px] uppercase tracking-wider text-white/40 mt-1">{label}</div>
      {sub && <div className="text-[10px] text-white/25 mt-0.5">{sub}</div>}
    </div>
  );
}
