'use client';

import { HR_ZONE_COLORS, HR_ZONE_LABELS } from './colors';

interface Props {
  /** Time in milliseconds in each zone (z0..z5). Null entries treated as 0. */
  zones: (number | null | undefined)[];
  /** Variant: 'horizontal' (single bar, e.g. for a workout row) or 'vertical' (column). */
  variant?: 'horizontal' | 'vertical';
  width?: number;
  height?: number;
  /** Show legend below. */
  legend?: boolean;
}

export function HRZoneStackedBar({ zones, variant = 'horizontal', width = 160, height = 10, legend = false }: Props) {
  const ms = zones.map(z => z ?? 0);
  const total = ms.reduce((s, x) => s + x, 0);
  if (total <= 0) {
    return <div className="text-[10px] text-white/20">no zones</div>;
  }
  const fmtMin = (m: number) => {
    const min = Math.round(m / 60000);
    if (min < 60) return `${min}m`;
    return `${Math.floor(min / 60)}h${min % 60 ? ` ${min % 60}m` : ''}`;
  };

  if (variant === 'horizontal') {
    return (
      <div>
        <div className="flex rounded overflow-hidden" style={{ width, height }}>
          {ms.map((m, i) => {
            const w = (m / total) * 100;
            if (w <= 0) return null;
            return <div key={i} title={`${HR_ZONE_LABELS[i]} · ${fmtMin(m)}`} style={{ width: `${w}%`, background: HR_ZONE_COLORS[i] }} />;
          })}
        </div>
        {legend && (
          <div className="flex flex-wrap gap-2 mt-1.5 text-[9px]">
            {ms.map((m, i) =>
              m > 0 ? (
                <span key={i} className="flex items-center gap-1 text-white/45">
                  <span className="w-1.5 h-1.5 rounded-sm" style={{ background: HR_ZONE_COLORS[i] }} />
                  {HR_ZONE_LABELS[i]} {fmtMin(m)}
                </span>
              ) : null
            )}
          </div>
        )}
      </div>
    );
  }

  // vertical: stacked column
  return (
    <div className="flex flex-col-reverse rounded overflow-hidden" style={{ width: height, height: width }}>
      {ms.map((m, i) => {
        const h = (m / total) * 100;
        if (h <= 0) return null;
        return <div key={i} title={`${HR_ZONE_LABELS[i]} · ${fmtMin(m)}`} style={{ height: `${h}%`, background: HR_ZONE_COLORS[i] }} />;
      })}
    </div>
  );
}
