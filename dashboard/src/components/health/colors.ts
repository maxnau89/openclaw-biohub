/**
 * Whoop-native color palette. Centralized so every chart uses the same.
 */

export const RECOVERY_COLORS = {
  green: '#22c55e',
  yellow: '#eab308',
  red: '#ef4444',
  unknown: '#525252',
};

export function recoveryColor(score: number | null | undefined): string {
  if (score == null) return RECOVERY_COLORS.unknown;
  if (score >= 67) return RECOVERY_COLORS.green;
  if (score >= 34) return RECOVERY_COLORS.yellow;
  return RECOVERY_COLORS.red;
}

/** Whoop HR-zones 0..5 — gray, blue, green, yellow, orange, red */
export const HR_ZONE_COLORS = [
  '#6b7280', // Z0  (gray) — Very Light
  '#3b82f6', // Z1  (blue) — Light
  '#22c55e', // Z2  (green) — Moderate
  '#eab308', // Z3  (yellow) — Vigorous
  '#f97316', // Z4  (orange) — Hard
  '#ef4444', // Z5  (red) — Max
];

export const HR_ZONE_LABELS = ['Z0', 'Z1', 'Z2', 'Z3', 'Z4', 'Z5'];

/** Whoop sleep stage palette */
export const SLEEP_COLORS = {
  awake: '#a3a3a3',
  light: '#14b8a6',
  deep: '#6366f1',
  rem: '#a855f7',
};

/** Whoop strain scale 0..21 → color */
export function strainColor(strain: number | null | undefined): string {
  if (strain == null || isNaN(strain)) return '#525252';
  if (strain < 6) return '#06b6d4'; // cyan — light
  if (strain < 10) return '#3b82f6'; // blue — moderate
  if (strain < 14) return '#22c55e'; // green — strenuous
  if (strain < 18) return '#f97316'; // orange — hard
  return '#ef4444'; // red — all out
}

export function strainLabel(strain: number | null | undefined): string {
  if (strain == null) return '—';
  if (strain < 6) return 'Light';
  if (strain < 10) return 'Moderate';
  if (strain < 14) return 'Strenuous';
  if (strain < 18) return 'Hard';
  return 'All Out';
}
