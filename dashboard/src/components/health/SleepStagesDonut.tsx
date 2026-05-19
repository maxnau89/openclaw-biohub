'use client';

import { SLEEP_COLORS } from './colors';

interface Stage {
  key: 'awake' | 'light' | 'deep' | 'rem';
  label: string;
  hours: number;
}

interface Props {
  awake: number; // hours
  light: number;
  deep: number;
  rem: number;
  size?: number;
}

export function SleepStagesDonut({ awake, light, deep, rem, size = 180 }: Props) {
  const stages: Stage[] = [
    { key: 'awake', label: 'Awake', hours: awake },
    { key: 'light', label: 'Light', hours: light },
    { key: 'deep', label: 'Deep', hours: deep },
    { key: 'rem', label: 'REM', hours: rem },
  ];
  const total = stages.reduce((s, x) => s + (x.hours || 0), 0);
  const stroke = 16;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const C = 2 * Math.PI * r;

  let offset = 0;
  const segments = stages.map(s => {
    const frac = total > 0 ? s.hours / total : 0;
    const dash = C * frac;
    const seg = {
      ...s,
      dash,
      offsetStart: offset,
      color: SLEEP_COLORS[s.key],
      pct: frac * 100,
    };
    offset += dash;
    return seg;
  });

  return (
    <div className="flex flex-col items-center gap-3 sm:flex-row sm:items-center sm:gap-6">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth={stroke} />
        {segments.map(s => (
          <circle
            key={s.key}
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={s.color}
            strokeWidth={stroke}
            strokeDasharray={`${s.dash} ${C - s.dash}`}
            strokeDashoffset={-s.offsetStart}
            transform={`rotate(-90 ${cx} ${cy})`}
          />
        ))}
        <text x={cx} y={cy - 4} textAnchor="middle" fontSize={size * 0.22} fontWeight={700} fill="rgba(255,255,255,0.92)">
          {total > 0 ? total.toFixed(1) : '—'}
        </text>
        <text x={cx} y={cy + size * 0.13} textAnchor="middle" fontSize={size * 0.08} fill="rgba(255,255,255,0.4)" letterSpacing={1}>
          HOURS
        </text>
      </svg>
      <div className="flex flex-col gap-1.5 text-xs min-w-[140px]">
        {segments.map(s => (
          <div key={s.key} className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: s.color }} />
            <span className="text-white/55 w-12">{s.label}</span>
            <span className="text-white/80 tabular-nums w-12">{s.hours.toFixed(1)}h</span>
            <span className="text-white/35 tabular-nums">{s.pct.toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
