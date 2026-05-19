'use client';

/**
 * WorkoutHeatmap — 7×24 weekday × hour grid. Cells colored by workout count.
 */
interface Workout {
  start_time?: string | null;
  created_at: string;
}

interface Props {
  workouts: Workout[];
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function WorkoutHeatmap({ workouts }: Props) {
  const grid = Array.from({ length: 7 }, () => Array(24).fill(0));
  workouts.forEach(w => {
    const iso = w.start_time || w.created_at;
    if (!iso) return;
    const d = new Date(iso);
    if (isNaN(d.getTime())) return;
    // JS getDay: Sun=0..Sat=6. We want Mon=0..Sun=6
    const wd = (d.getDay() + 6) % 7;
    const hr = d.getHours();
    grid[wd][hr]++;
  });

  const max = Math.max(...grid.flat(), 1);

  return (
    <div>
      <div className="flex gap-[2px] text-[8px] text-white/15">
        <div className="w-8" />
        {Array.from({ length: 24 }, (_, h) => (
          <div key={h} className="flex-1 text-center">{h % 6 === 0 ? h : ''}</div>
        ))}
      </div>
      {grid.map((row, wd) => (
        <div key={wd} className="flex gap-[2px] mt-[2px]">
          <div className="w-8 text-[9px] text-white/30 leading-[14px]">{WEEKDAYS[wd]}</div>
          {row.map((count, h) => {
            const intensity = count / max;
            const bg = count === 0 ? 'rgba(255,255,255,0.04)' : `rgba(245, 158, 11, ${0.18 + intensity * 0.72})`;
            return (
              <div
                key={h}
                className="flex-1 h-3.5 rounded-sm"
                style={{ background: bg }}
                title={`${WEEKDAYS[wd]} ${h}:00 · ${count} workout${count !== 1 ? 's' : ''}`}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}
