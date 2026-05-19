'use client';

import { recoveryColor } from './colors';

interface Props {
  value: number | null | undefined; // 0..100
  size?: number;
  label?: string;
  sub?: string;
}

export function RecoveryDonut({ value, size = 180, label = 'Recovery', sub }: Props) {
  const v = value == null || isNaN(value) ? null : Math.max(0, Math.min(100, value));
  const pct = v == null ? 0 : v / 100;
  const color = recoveryColor(v);
  const stroke = 14;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const C = 2 * Math.PI * r;
  const dash = C * pct;
  const gap = C - dash;

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={stroke} />
        {v != null && (
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeDasharray={`${dash} ${gap}`}
            strokeDashoffset={C * 0.25}
            strokeLinecap="round"
            transform={`rotate(-90 ${cx} ${cy})`}
            style={{ transition: 'stroke-dasharray 600ms ease' }}
          />
        )}
        <text
          x={cx}
          y={cy - 2}
          textAnchor="middle"
          fontSize={size * 0.3}
          fontWeight={700}
          fill={color}
        >
          {v != null ? `${Math.round(v)}` : '—'}
        </text>
        <text
          x={cx}
          y={cy + size * 0.13}
          textAnchor="middle"
          fontSize={size * 0.085}
          fill="rgba(255,255,255,0.5)"
          letterSpacing={1}
        >
          %
        </text>
      </svg>
      <div className="text-[11px] uppercase tracking-wider text-white/40 mt-1">{label}</div>
      {sub && <div className="text-[10px] text-white/25 mt-0.5">{sub}</div>}
    </div>
  );
}
