'use client';

interface Metric {
  label: string;
  current: number | null;
  previous: number | null;
  unit?: string;
  decimals?: number;
  /** lower is better (e.g. RHR). */
  lowerIsBetter?: boolean;
  color?: string;
}

interface Props {
  title?: string;
  metrics: Metric[];
}

export function MonthlyDelta({ metrics }: Props) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {metrics.map(m => {
        const has = m.current != null && m.previous != null;
        const delta = has ? (m.current as number) - (m.previous as number) : null;
        const deltaPct = has && m.previous !== 0 ? (delta! / (m.previous as number)) * 100 : null;
        const positive = delta != null && delta > 0;
        const better = delta == null ? null : m.lowerIsBetter ? delta < 0 : delta > 0;
        const arrowColor = better == null ? 'text-white/30' : better ? 'text-emerald-400' : 'text-rose-400';
        const fmt = (v: number) => (m.decimals != null ? v.toFixed(m.decimals) : Number.isInteger(v) ? `${v}` : v.toFixed(1));

        return (
          <div key={m.label} className="rounded-lg bg-white/[0.03] border border-white/[0.05] p-3">
            <div className="text-[10px] text-white/40 uppercase tracking-wider">{m.label}</div>
            <div className="flex items-baseline gap-2 mt-1">
              <div className="text-xl font-semibold" style={{ color: m.color ?? 'rgba(255,255,255,0.85)' }}>
                {m.current != null ? fmt(m.current) : '—'}
                {m.unit && <span className="text-sm text-white/30 font-normal">{m.unit}</span>}
              </div>
            </div>
            {has && delta != null && (
              <div className={`text-[10px] mt-1 ${arrowColor}`}>
                {positive ? '▲' : '▼'} {fmt(Math.abs(delta))}
                {m.unit ?? ''}
                {deltaPct != null && Math.abs(deltaPct) < 999 && (
                  <span className="text-white/30 ml-1">({deltaPct >= 0 ? '+' : ''}{deltaPct.toFixed(1)}%)</span>
                )}
                <span className="text-white/30 ml-1">vs prev</span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
