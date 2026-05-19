'use client';

/**
 * SleepConsistencyHeatmap — shows bedtime + waketime as horizontal bars per day.
 * Each row = day. X-axis = hour-of-day (0..24, plus we wrap so 20:00 prev night → 10:00 next morning).
 */

interface Day {
  date: string;
  bedtime: string | null;
  waketime: string | null;
}

interface Props {
  days: Day[];
  height?: number;
}

/** Convert ISO to fractional hour of day; if before 12:00 we add 24 so a bedtime of 23:00 and waketime 07:00 render as 23 → 31. */
function toShiftedHour(iso: string | null, isWake: boolean): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  const h = d.getHours() + d.getMinutes() / 60;
  // Shift: anchor at noon. Anything before noon = + 24 (so we display 18→30 range typical bedtimes)
  return h < 12 ? h + 24 : h;
}

export function SleepConsistencyHeatmap({ days, height = 200 }: Props) {
  const sorted = [...days].sort((a, b) => a.date.localeCompare(b.date));
  if (sorted.length === 0) {
    return <div className="text-white/20 text-xs py-6 text-center">No data</div>;
  }

  // Range: 18:00 (h=18) to 12:00 next day (h=36), so 18 hours window
  const X_MIN = 18;
  const X_MAX = 36;
  const xRange = X_MAX - X_MIN;
  const W = 800;
  const H = height;
  const PAD_L = 50;
  const PAD_R = 8;
  const PAD_T = 18;
  const PAD_B = 16;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const n = sorted.length;
  const rowH = plotH / Math.max(n, 1);

  const xOf = (h: number) => PAD_L + ((h - X_MIN) / xRange) * plotW;
  const fmtHour = (h: number) => {
    const real = h >= 24 ? h - 24 : h;
    return `${Math.floor(real)}:00`;
  };

  // X tick marks every 3h
  const ticks: number[] = [];
  for (let h = X_MIN; h <= X_MAX; h += 3) ticks.push(h);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" style={{ height }}>
      {/* X-axis ticks */}
      {ticks.map(t => (
        <g key={t}>
          <line x1={xOf(t)} x2={xOf(t)} y1={PAD_T} y2={H - PAD_B} stroke="rgba(255,255,255,0.04)" />
          <text x={xOf(t)} y={PAD_T - 4} fontSize={9} fill="rgba(255,255,255,0.25)" textAnchor="middle">
            {fmtHour(t)}
          </text>
        </g>
      ))}

      {sorted.map((d, i) => {
        const bed = toShiftedHour(d.bedtime, false);
        const wake = toShiftedHour(d.waketime, true);
        const y = PAD_T + i * rowH + rowH * 0.2;
        const h = rowH * 0.6;
        if (bed == null || wake == null) return null;
        // Clip into range
        const x1 = Math.max(xOf(bed), PAD_L);
        const x2 = Math.min(xOf(wake), PAD_L + plotW);
        if (x2 <= x1) return null;
        // Color by duration: shorter sleeps red-er
        const durHours = wake - bed;
        const color = durHours >= 7 ? '#6366f1' : durHours >= 6 ? '#a855f7' : '#ef4444';
        return (
          <g key={d.date}>
            {/* Y label every ~5th row */}
            {(i % Math.max(1, Math.floor(n / 6)) === 0 || i === n - 1) && (
              <text x={PAD_L - 4} y={y + h / 2 + 3} fontSize={8} fill="rgba(255,255,255,0.3)" textAnchor="end">
                {d.date.slice(5)}
              </text>
            )}
            <rect x={x1} y={y} width={x2 - x1} height={h} rx={1.5} fill={color} opacity={0.7} />
          </g>
        );
      })}
    </svg>
  );
}
