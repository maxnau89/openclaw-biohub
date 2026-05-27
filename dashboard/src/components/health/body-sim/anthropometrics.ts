/**
 * Body composition math — typed port of the procedural POC's anthropometrics
 * module. Validated against:
 *
 *   - Hodgdon-Beckett US Navy BF% formula (male: waist−neck; female: waist+hip−neck)
 *   - FFMI (Kouri 1995)
 *   - NHANES anthropometric percentiles (rough fit, no fine-grained matching)
 *   - Forsberg / Helms / Aragon for the forward simulation parameters
 *
 * Units: kg, cm, %, kcal unless explicitly noted.
 */

// ─── Public types ────────────────────────────────────────────────────────────

export interface Skinfolds {
  chest: number;
  abdominal: number;
  thigh: number;
  tricep: number;
  subscapular: number;
  suprailiac: number;
  midaxillary: number;
}

export type Sex = 'm' | 'f';

export interface BodyInput {
  weightKg: number;
  bfPct: number;
  heightM: number;
  sex?: Sex;             // default 'm'
  skinfolds?: Skinfolds; // optional: enables regional-fat shape
}

export interface Girths {
  neck: number;
  chest: number;
  waist: number;
  hip: number;
  bicep: number;
  forearm: number;
  thigh: number;
  calf: number;
  wrist: number;
  ankle: number;
  /** Diagnostic: BF% recovered from predicted waist/neck via Navy. */
  _diagBF: number;
  _ffmi: number;
  _LBM: number;
  _FM: number;
}

export interface SimEndpoint {
  weightKg: number;
  bfPct: number;
  LBM: number;
  FM: number;
  ffmi: number;
}

export interface ForwardResult {
  start: SimEndpoint;
  end: SimEndpoint;
  deltaLBM: number;
  deltaFM: number;
  proteinPerKgLBM: number;
  dailyDeficit: number;
  weeks: number;
}

export interface PlanResult {
  weeksNeeded: number;
  dailyDeficit: number;
  targetIntake: number;
  deltaLBM: number;
  deltaFM: number;
  totalLossKg: number;
  proteinPerKgLBM: number;
  notes: string;
}

export interface SimulateForwardInput {
  weightKg: number;
  bfPct: number;
  heightM: number;
  dailyKcal: number;
  tdee: number;
  proteinG: number;
  weeks: number;
  /** Resistance training, hard intensity. Default true. */
  trainingHard?: boolean;
  /** 0 = novice, 1 = intermediate, 2 = advanced. Default 2. */
  lifterLevel?: 0 | 1 | 2;
}

export interface PlanToTargetInput {
  weightKg: number;
  bfPct: number;
  heightM: number;
  targetWeight: number;
  targetBF: number;
  tdee: number;
  proteinG: number;
}

// ─── Core formulas ───────────────────────────────────────────────────────────
//
// US Navy body-composition assessment uses the Hodgdon-Beckett density
// regression (waist−neck for men; waist+hip−neck for women, both with a
// height correction) and feeds it through the Siri equation to get BF%.
// The "86.010 × log10(...)" coefficients in many code snippets are the
// **inches** form. We use the cm-correct (Siri-on-Hodgdon-Beckett) form:
//
//   density = 1.0324 − 0.19077·log10(waist − neck) + 0.15456·log10(height)
//   BF% = 495 / density − 450
//
// for men, and the equivalent female form (using waist + hip − neck).

/** US Navy BF% for men, metric inputs in cm. */
export function navyBFMale(waistCm: number, neckCm: number, heightCm: number): number {
  const density = 1.0324
    - 0.19077 * Math.log10(waistCm - neckCm)
    + 0.15456 * Math.log10(heightCm);
  return 495 / density - 450;
}

/** US Navy BF% for women, metric inputs in cm. */
export function navyBFFemale(
  waistCm: number, hipCm: number, neckCm: number, heightCm: number,
): number {
  const density = 1.29579
    - 0.35004 * Math.log10(waistCm + hipCm - neckCm)
    + 0.22100 * Math.log10(heightCm);
  return 495 / density - 450;
}

/** Solve the male Navy formula for waist given target BF%. */
export function navyWaistMale(targetBF: number, neckCm: number, heightCm: number): number {
  // Invert: density = 495 / (BF + 450)
  const density = 495 / (targetBF + 450);
  // density = 1.0324 − 0.19077·log10(waist − neck) + 0.15456·log10(height)
  // ⇒ log10(waist − neck) = (1.0324 + 0.15456·log10(height) − density) / 0.19077
  const logTerm =
    (1.0324 + 0.15456 * Math.log10(heightCm) - density) / 0.19077;
  return Math.pow(10, logTerm) + neckCm;
}

/** Fat-Free Mass Index (Kouri 1995). */
export function ffmi(lbmKg: number, heightM: number): number {
  return lbmKg / (heightM * heightM);
}

/** Lean body mass from total weight + BF%. */
export function lbm(weightKg: number, bfPct: number): number {
  return weightKg * (1 - bfPct / 100);
}

/** Fat mass from total weight + BF%. */
export function fatMass(weightKg: number, bfPct: number): number {
  return weightKg * bfPct / 100;
}

// ─── Girth predictions ───────────────────────────────────────────────────────
//
// Heuristic — each girth = muscle_component(LBM) + fat_component(FM).
// Reference anchors are sex-specific:
//   - male:   advanced lifter, FFMI 25.5, 1.80 m, ~12 % BF, ~94 kg
//   - female: lean-trained,    FFMI 21.5, 1.65 m, ~22 % BF, ~65 kg
// These are anchor points, not targets. Any input scales relative to them.

interface AnchorTable {
  ffmi: number;
  heightM: number;
  baseGirth: Record<keyof Omit<Girths, '_diagBF' | '_ffmi' | '_LBM' | '_FM'>, number>;
  fatPerKg: Record<keyof Omit<Girths, '_diagBF' | '_ffmi' | '_LBM' | '_FM'>, number>;
  musclePow: Record<keyof Omit<Girths, '_diagBF' | '_ffmi' | '_LBM' | '_FM'>, number>;
}

const ANCHOR_MALE: AnchorTable = {
  ffmi: 25.5,
  heightM: 1.80,
  baseGirth: {
    neck: 38.0, chest: 105.0, waist: 76.0, hip: 96.0,
    bicep: 35.0, forearm: 30.0, thigh: 58.0, calf: 39.0,
    wrist: 17.5, ankle: 23.0,
  },
  // Where fat tends to land (kg fat × this = cm of girth contribution).
  fatPerKg: {
    neck: 0.12, chest: 0.45, waist: 0.85, hip: 0.55,
    bicep: 0.25, forearm: 0.08, thigh: 0.45, calf: 0.12,
    wrist: 0.02, ankle: 0.04,
  },
  // How strongly each girth scales with muscle (LBM via FFMI).
  musclePow: {
    neck: 0.6, chest: 1.0, waist: 0.3, hip: 0.4,
    bicep: 1.4, forearm: 1.1, thigh: 1.0, calf: 1.0,
    wrist: 0.1, ankle: 0.1,
  },
};

const ANCHOR_FEMALE: AnchorTable = {
  ffmi: 21.5,
  heightM: 1.65,
  baseGirth: {
    neck: 32.5, chest: 88.0, waist: 68.0, hip: 95.0,
    bicep: 28.0, forearm: 24.0, thigh: 56.0, calf: 35.0,
    wrist: 15.0, ankle: 21.0,
  },
  // Female fat distribution: more hip/thigh, less abdominal vs. male.
  fatPerKg: {
    neck: 0.10, chest: 0.40, waist: 0.65, hip: 0.85,
    bicep: 0.20, forearm: 0.08, thigh: 0.70, calf: 0.18,
    wrist: 0.02, ankle: 0.04,
  },
  musclePow: {
    neck: 0.5, chest: 0.9, waist: 0.3, hip: 0.45,
    bicep: 1.2, forearm: 1.0, thigh: 1.0, calf: 1.0,
    wrist: 0.1, ankle: 0.1,
  },
};

function anchorFor(sex: Sex): AnchorTable {
  return sex === 'f' ? ANCHOR_FEMALE : ANCHOR_MALE;
}

/** Returns predicted girths (cm) for the given body composition. */
export function predictGirths(input: BodyInput): Girths {
  const { weightKg, bfPct, heightM } = input;
  const sex: Sex = input.sex ?? 'm';
  const anchor = anchorFor(sex);

  const FM = fatMass(weightKg, bfPct);
  const LBM = lbm(weightKg, bfPct);
  const F = ffmi(LBM, heightM);
  const muscleRatio = F / anchor.ffmi;
  // Girths scale with height, but less than linearly (~h^0.7 from allometric scaling).
  const heightScale = Math.pow(heightM / anchor.heightM, 0.7);

  const out = {} as Girths;
  for (const k of Object.keys(anchor.baseGirth) as (keyof typeof anchor.baseGirth)[]) {
    const muscle = anchor.baseGirth[k] * Math.pow(muscleRatio, anchor.musclePow[k]);
    const fat = FM * anchor.fatPerKg[k];
    out[k] = (muscle + fat) * heightScale;
  }

  // Sanity: re-check waist via Navy and blend (Navy is the gold-standard for BF↔waist).
  const heightCm = heightM * 100;
  if (sex === 'm') {
    const navyWst = navyWaistMale(bfPct, out.neck, heightCm);
    out.waist = 0.7 * navyWst + 0.3 * out.waist;
    out._diagBF = navyBFMale(out.waist, out.neck, heightCm);
  } else {
    // Female Navy needs hip; we already predicted hip above, so re-derive
    // BF% from waist+hip+neck and report the diagnostic.
    out._diagBF = navyBFFemale(out.waist, out.hip, out.neck, heightCm);
  }
  out._ffmi = F;
  out._LBM = LBM;
  out._FM = FM;
  return out;
}

// ─── Forward simulation: diet/exercise → body comp ───────────────────────────
//
// Assumptions (well-supported in the literature):
//   - 1 kg fat ≈ 7700 kcal energy
//   - 1 kg muscle ≈ 5500 kcal (synthesis cost + extracellular water)
//   - Max LBM gain rate (kg/wk): novice ~0.4, intermediate ~0.2, advanced ~0.12
//   - In deficit + adequate protein (≥1.6 g/kg LBM): LBM loss is 5–25% of total weight loss

export function simulateForward(input: SimulateForwardInput): ForwardResult {
  const {
    weightKg, bfPct, heightM,
    dailyKcal, tdee, proteinG, weeks,
    trainingHard = true,
    lifterLevel = 2,
  } = input;

  const LBM0 = lbm(weightKg, bfPct);
  const FM0 = fatMass(weightKg, bfPct);
  const proteinPerKgLBM = proteinG / LBM0;
  const dailyDeficit = dailyKcal - tdee; // negative ⇒ cut
  const totalEnergyDelta = dailyDeficit * 7 * weeks; // kcal over the window

  const maxMuscleGainPerWeek = ([0.4, 0.2, 0.12] as const)[lifterLevel];

  let deltaLBM = 0;
  let deltaFM = 0;

  if (dailyDeficit < 0) {
    // CUT — most of the loss is fat, with some LBM bleed.
    let lbmLossFrac = 0.20; // baseline 20% of weight loss is LBM
    if (proteinPerKgLBM >= 2.0) lbmLossFrac -= 0.08;
    else if (proteinPerKgLBM >= 1.6) lbmLossFrac -= 0.04;
    if (trainingHard) lbmLossFrac -= 0.05;
    if (Math.abs(dailyDeficit) > 800) lbmLossFrac += 0.05;
    lbmLossFrac = Math.max(0.05, Math.min(0.30, lbmLossFrac));

    const totalWeightLossKg = -totalEnergyDelta / 7700;
    deltaLBM = -totalWeightLossKg * lbmLossFrac;
    deltaFM = -totalWeightLossKg * (1 - lbmLossFrac);

    // Trained lifter in moderate deficit with high protein can recomp slightly.
    if (trainingHard && proteinPerKgLBM >= 1.8 && Math.abs(dailyDeficit) < 400) {
      const recompGain = Math.min(maxMuscleGainPerWeek * weeks * 0.5, 1.0);
      deltaLBM += recompGain;
    }
  } else if (dailyDeficit > 0) {
    // BULK — surplus first feeds muscle synthesis, the rest spills to fat.
    const muscleCap = maxMuscleGainPerWeek * weeks;
    const muscleEnergyCost = 5500;
    const maxMuscleEnergyAbsorbable = muscleCap * muscleEnergyCost;

    if (totalEnergyDelta <= maxMuscleEnergyAbsorbable && proteinPerKgLBM >= 1.6) {
      // Small surplus, fully channeled to muscle.
      deltaLBM = totalEnergyDelta / muscleEnergyCost;
      deltaFM = 0;
    } else {
      const muscleEnergy = Math.max(0, Math.min(totalEnergyDelta, maxMuscleEnergyAbsorbable));
      const fatEnergy = totalEnergyDelta - muscleEnergy;
      deltaLBM = muscleEnergy / muscleEnergyCost;
      if (proteinPerKgLBM < 1.6) deltaLBM *= 0.5;
      deltaFM = fatEnergy / 7700;
    }
  } else {
    // Maintenance — small recomp possible if trained + high protein.
    if (trainingHard && proteinPerKgLBM >= 1.8) {
      const recomp = Math.min(maxMuscleGainPerWeek * weeks * 0.6, 1.5);
      deltaLBM = recomp;
      deltaFM = -recomp; // approximate body recomp 1:1
    }
  }

  const LBM1 = Math.max(40, LBM0 + deltaLBM);
  const FM1 = Math.max(2, FM0 + deltaFM);
  const weight1 = LBM1 + FM1;
  const bf1 = (FM1 / weight1) * 100;

  return {
    start: { weightKg, bfPct, LBM: LBM0, FM: FM0, ffmi: ffmi(LBM0, heightM) },
    end:   { weightKg: weight1, bfPct: bf1, LBM: LBM1, FM: FM1, ffmi: ffmi(LBM1, heightM) },
    deltaLBM, deltaFM,
    proteinPerKgLBM, dailyDeficit,
    weeks,
  };
}

// ─── Reverse planner: target → required diet plan ────────────────────────────

/** Given a goal body comp, suggest weekly deficit and duration. */
export function planToTarget(input: PlanToTargetInput): PlanResult {
  const {
    weightKg, bfPct, heightM: _heightM,
    targetWeight, targetBF,
    tdee, proteinG,
  } = input;
  const LBM0 = lbm(weightKg, bfPct);
  const LBMt = targetWeight * (1 - targetBF / 100);
  const FMt = targetWeight * targetBF / 100;
  const FM0 = fatMass(weightKg, bfPct);
  const deltaLBM = LBMt - LBM0;
  const deltaFM = FMt - FM0;
  const totalLossKg = weightKg - targetWeight;

  // Safe weekly loss = 0.5–1.0% of body weight; pick 0.75% as the midpoint.
  const weeklySafeLoss = weightKg * 0.0075;
  const weeksNeeded = Math.max(2, Math.round(totalLossKg / weeklySafeLoss));
  const dailyDeficit = -(totalLossKg * 7700) / (weeksNeeded * 7);

  return {
    weeksNeeded,
    dailyDeficit: Math.round(dailyDeficit),
    targetIntake: Math.round(tdee + dailyDeficit),
    deltaLBM, deltaFM, totalLossKg,
    proteinPerKgLBM: proteinG / LBM0,
    notes: dailyDeficit < -800
      ? 'Very aggressive deficit — LBM loss rises sharply at this rate.'
      : 'Realistic cut tempo.',
  };
}
