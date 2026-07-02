import { NextResponse } from 'next/server';
import { execSync } from 'child_process';
import path from 'path';
import { PIPELINE_DIR } from '@/lib/paths';

export const dynamic = 'force-dynamic';

const SCRIPT = path.join(PIPELINE_DIR, 'glucose_analytics.py');

// Cache keyed by the days window — otherwise a days=90 result would be
// served for a days=365 request and vice-versa.
const cache = new Map<number, { data: unknown; ts: number }>();
const IS_DEV = process.env.NODE_ENV !== 'production';

export async function GET(request: Request) {
  try {
    const days = Number(new URL(request.url).searchParams.get('days')) || 90;
    const now = Date.now();
    const hit = cache.get(days);
    if (!IS_DEV && hit && now - hit.ts < 300_000) return NextResponse.json(hit.data);

    const output = execSync(`python3 "${SCRIPT}" --days ${days} 2>/dev/null`, {
      timeout: 30000,
      encoding: 'utf-8',
    });

    const data = JSON.parse(output);
    cache.set(days, { data, ts: now });
    return NextResponse.json(data);
  } catch (e: unknown) {
    return NextResponse.json({ overview: { readings: 0 }, daily: [], error: String(e) });
  }
}
