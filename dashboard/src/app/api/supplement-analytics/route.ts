import { NextResponse } from 'next/server';
import { execSync } from 'child_process';
import path from 'path';
import { PIPELINE_DIR } from '@/lib/paths';

export const dynamic = 'force-dynamic';

const SCRIPT = path.join(PIPELINE_DIR, 'supplement_analytics.py');

let cache: { data: unknown; ts: number } | null = null;

export async function GET() {
  try {
    const now = Date.now();
    if (cache && now - cache.ts < 60_000) return NextResponse.json(cache.data);

    const output = execSync(`python3 "${SCRIPT}" 2>/dev/null`, {
      timeout: 30000,
      encoding: 'utf-8',
    });

    const data = JSON.parse(output);
    cache = { data, ts: now };
    return NextResponse.json(data);
  } catch (e: unknown) {
    return NextResponse.json({ supplements: [], error: String(e) });
  }
}
