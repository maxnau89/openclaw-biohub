'use client';

import { RECOVERY_COLORS } from './colors';

interface Props {
  scores: (number | null | undefined)[];
}

/**
 * Horizontal stacked bar showing % of days in green/yellow/red recovery zones,
 * plus count labels. Cleaner than a pie for narrow cards.
 */
export function RecoveryDistribution({ scores }: Props) {
  const valid = scores.filter((s): s is number => s != null && !isNaN(s as number));
  const total = valid.length;
  if (total === 0) {
    return <div className="text-white/20 text-xs py-6 text-center">No data</div>;
  }
  const green = valid.filter(s => s >= 67).length;
  const yellow = valid.filter(s => s >= 34 && s < 67).length;
  const red = valid.filter(s => s < 34).length;
  const pct = (n: number) => (n / total) * 100;

  return (
    <div className="space-y-3">
      <div className="flex h-6 rounded overflow-hidden">
        <div style={{ width: `${pct(green)}%`, background: RECOVERY_COLORS.green }} title={`Green: ${green} days`} />
        <div style={{ width: `${pct(yellow)}%`, background: RECOVERY_COLORS.yellow }} title={`Yellow: ${yellow} days`} />
        <div style={{ width: `${pct(red)}%`, background: RECOVERY_COLORS.red }} title={`Red: ${red} days`} />
      </div>
      <div className="grid grid-cols-3 gap-3 text-xs">
        <Stat color={RECOVERY_COLORS.green} label="Green" count={green} total={total} sub="≥ 67%" />
        <Stat color={RECOVERY_COLORS.yellow} label="Yellow" count={yellow} total={total} sub="34–66%" />
        <Stat color={RECOVERY_COLORS.red} label="Red" count={red} total={total} sub="< 34%" />
      </div>
    </div>
  );
}

function Stat({ color, label, count, total, sub }: { color: string; label: string; count: number; total: number; sub: string }) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <div className="flex items-center gap-2">
      <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: color }} />
      <div className="min-w-0">
        <div className="text-white/70 font-medium">{label}</div>
        <div className="text-white/40 text-[10px]">{count} d · {pct.toFixed(0)}% · {sub}</div>
      </div>
    </div>
  );
}
