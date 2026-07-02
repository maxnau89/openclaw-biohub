import { NextResponse } from 'next/server';
import { execSync } from 'child_process';
import path from 'path';
import { PIPELINE_DIR } from '@/lib/paths';

export const dynamic = 'force-dynamic';

const SCRIPT = path.join(PIPELINE_DIR, 'physiological_age.py');

let cache: { data: unknown; ts: number } | null = null;
const IS_DEV = process.env.NODE_ENV !== 'production';

export async function GET() {
  try {
    const now = Date.now();
    if (!IS_DEV && cache && now - cache.ts < 300_000) return NextResponse.json(cache.data);

    const output = execSync(`python3 "${SCRIPT}" 2>/dev/null`, {
      timeout: 30000,
      encoding: 'utf-8',
    });

    const data = JSON.parse(output);
    cache = { data, ts: now };
    return NextResponse.json(data);
  } catch (e: unknown) {
    return NextResponse.json({ physiological_age: null, contributions: [], error: String(e) });
  }
}
