import { describe, expect, it } from 'vitest';
import {
  navyBFMale, navyBFFemale, navyWaistMale,
  ffmi, lbm, fatMass,
  predictGirths, simulateForward, planToTarget,
} from './anthropometrics';

// ─── Core formulas ───────────────────────────────────────────────────────────

describe('navyBFMale', () => {
  it('produces a plausible BF% for a lean male (waist 80, neck 38, height 180)', () => {
    // Hodgdon-Beckett + Siri gives ~12 % for this profile.
    const bf = navyBFMale(80, 38, 180);
    expect(bf).toBeGreaterThan(10);
    expect(bf).toBeLessThan(14);
  });

  it('produces a plausible BF% for a softer male (waist 95, neck 40, height 180)', () => {
    const bf = navyBFMale(95, 40, 180);
    expect(bf).toBeGreaterThan(20);
    expect(bf).toBeLessThan(28);
  });

  it('rises monotonically with waist', () => {
    expect(navyBFMale(85, 38, 180)).toBeGreaterThan(navyBFMale(80, 38, 180));
    expect(navyBFMale(90, 38, 180)).toBeGreaterThan(navyBFMale(85, 38, 180));
  });
});

describe('navyBFFemale', () => {
  it('produces a plausible BF% for an average lean female', () => {
    // 1.65 m, neck 32 cm, waist 70 cm, hip 95 cm → roughly ~22-25 % BF
    const bf = navyBFFemale(70, 95, 32, 165);
    expect(bf).toBeGreaterThan(18);
    expect(bf).toBeLessThan(28);
  });

  it('rises with waist and hip together', () => {
    const lean = navyBFFemale(65, 90, 32, 165);
    const soft = navyBFFemale(75, 100, 32, 165);
    expect(soft).toBeGreaterThan(lean);
  });
});

describe('navyWaistMale', () => {
  it('is the inverse of navyBFMale', () => {
    for (const targetBF of [8, 12, 18, 25, 32]) {
      const waist = navyWaistMale(targetBF, 38, 180);
      const recovered = navyBFMale(waist, 38, 180);
      expect(Math.abs(recovered - targetBF)).toBeLessThan(0.1);
    }
  });
});

describe('ffmi / lbm / fatMass', () => {
  it('ffmi is LBM divided by height squared', () => {
    expect(ffmi(80, 1.80)).toBeCloseTo(24.69, 2);
  });

  it('lbm + fatMass = total weight', () => {
    const w = 82, bf = 18;
    expect(lbm(w, bf) + fatMass(w, bf)).toBeCloseTo(w);
  });

  it('lbm at 0 % BF is the full weight', () => {
    expect(lbm(80, 0)).toBe(80);
    expect(fatMass(80, 0)).toBe(0);
  });
});

// ─── predictGirths ───────────────────────────────────────────────────────────

describe('predictGirths (male)', () => {
  it('reproduces sensible girths near the reference anchor', () => {
    // Anchor athlete: 94 kg, 12 % BF, 1.80 m → predicted girths should be
    // close to the baseGirth table.
    const g = predictGirths({ weightKg: 94, bfPct: 12, heightM: 1.80, sex: 'm' });
    expect(g.waist).toBeGreaterThan(78);  // a lean 94 kg male is ~80-85 cm
    expect(g.waist).toBeLessThan(90);
    expect(g.bicep).toBeGreaterThan(36);
    expect(g.bicep).toBeLessThan(44);
    expect(g._ffmi).toBeGreaterThan(24);
    expect(g._ffmi).toBeLessThan(27);
  });

  it('fatter body → larger waist', () => {
    const lean = predictGirths({ weightKg: 80, bfPct: 10, heightM: 1.80, sex: 'm' });
    const soft = predictGirths({ weightKg: 80, bfPct: 25, heightM: 1.80, sex: 'm' });
    expect(soft.waist).toBeGreaterThan(lean.waist);
  });

  it('diagBF round-trips within ~1.5 % for typical inputs (male)', () => {
    // The heuristic waist is blended 70/30 with Navy's solved waist, so the
    // round-trip carries 30 % of the heuristic's drift. 1.5 % is the floor.
    for (const bf of [8, 12, 18, 25]) {
      const g = predictGirths({ weightKg: 80, bfPct: bf, heightM: 1.80, sex: 'm' });
      expect(Math.abs(g._diagBF - bf)).toBeLessThan(1.5);
    }
  });
});

describe('predictGirths (female)', () => {
  it('female ref athlete has female anchor girths', () => {
    const g = predictGirths({ weightKg: 65, bfPct: 22, heightM: 1.65, sex: 'f' });
    // Female silhouette has wider hip-to-waist ratio than male.
    expect(g.hip).toBeGreaterThan(g.waist);
    expect(g.bicep).toBeLessThan(35);    // smaller arms than male anchor
    expect(g.thigh).toBeGreaterThan(50); // larger thigh share of LBM
  });

  it('female body has wider hip than male body at same weight + BF%', () => {
    const m = predictGirths({ weightKg: 70, bfPct: 22, heightM: 1.70, sex: 'm' });
    const f = predictGirths({ weightKg: 70, bfPct: 22, heightM: 1.70, sex: 'f' });
    expect(f.hip).toBeGreaterThan(m.hip);
  });
});

// ─── simulateForward ─────────────────────────────────────────────────────────

describe('simulateForward — cut', () => {
  it('8 weeks at -500 kcal/day on a trained lifter loses 3-5 kg total', () => {
    const r = simulateForward({
      weightKg: 85, bfPct: 18, heightM: 1.80,
      dailyKcal: 2300, tdee: 2800, proteinG: 180, weeks: 8,
    });
    const totalLoss = r.start.weightKg - r.end.weightKg;
    expect(totalLoss).toBeGreaterThan(3);
    expect(totalLoss).toBeLessThan(5);
    expect(r.end.bfPct).toBeLessThan(r.start.bfPct);
  });

  it('high protein protects more LBM than low protein at same deficit', () => {
    const lowProtein = simulateForward({
      weightKg: 85, bfPct: 18, heightM: 1.80,
      dailyKcal: 2300, tdee: 2800, proteinG: 80, weeks: 8,
    });
    const highProtein = simulateForward({
      weightKg: 85, bfPct: 18, heightM: 1.80,
      dailyKcal: 2300, tdee: 2800, proteinG: 180, weeks: 8,
    });
    expect(highProtein.deltaLBM).toBeGreaterThan(lowProtein.deltaLBM);
  });
});

describe('simulateForward — bulk', () => {
  it('moderate surplus + high protein on advanced lifter produces some LBM', () => {
    const r = simulateForward({
      weightKg: 80, bfPct: 12, heightM: 1.80,
      dailyKcal: 3200, tdee: 2900, proteinG: 160, weeks: 12,
      lifterLevel: 2,
    });
    expect(r.deltaLBM).toBeGreaterThan(0);
  });

  it('huge surplus mostly spills to fat (muscle cap hits)', () => {
    const r = simulateForward({
      weightKg: 80, bfPct: 12, heightM: 1.80,
      dailyKcal: 4500, tdee: 2900, proteinG: 160, weeks: 12,
      lifterLevel: 2,
    });
    expect(r.deltaFM).toBeGreaterThan(r.deltaLBM);
  });
});

describe('simulateForward — maintenance recomp', () => {
  it('trained lifter at maintenance with high protein recomps slowly', () => {
    const r = simulateForward({
      weightKg: 80, bfPct: 18, heightM: 1.80,
      dailyKcal: 2800, tdee: 2800, proteinG: 160, weeks: 12,
    });
    expect(r.deltaLBM).toBeGreaterThan(0);
    expect(r.deltaFM).toBeLessThan(0);
    expect(Math.abs(r.end.weightKg - r.start.weightKg)).toBeLessThan(0.5);
  });
});

// ─── planToTarget ────────────────────────────────────────────────────────────

describe('planToTarget', () => {
  it('80 kg @ 18 % → 75 kg @ 12 % produces a sane plan', () => {
    const r = planToTarget({
      weightKg: 80, bfPct: 18, heightM: 1.80,
      targetWeight: 75, targetBF: 12,
      tdee: 2800, proteinG: 160,
    });
    expect(r.totalLossKg).toBe(5);
    expect(r.weeksNeeded).toBeGreaterThan(4);
    expect(r.weeksNeeded).toBeLessThan(12);
    expect(r.dailyDeficit).toBeLessThan(0);
    expect(r.targetIntake).toBeLessThan(2800);
  });

  it('flags an aggressive deficit when goal is too ambitious', () => {
    const r = planToTarget({
      weightKg: 80, bfPct: 22, heightM: 1.80,
      targetWeight: 65, targetBF: 8,    // -15 kg, very aggressive
      tdee: 2800, proteinG: 160,
    });
    // Either weeks bumps up or deficit warning fires; with safe weekly loss
    // calc, weeks should stretch so deficit stays bearable.
    expect(r.dailyDeficit).toBeLessThanOrEqual(-400);
  });
});
