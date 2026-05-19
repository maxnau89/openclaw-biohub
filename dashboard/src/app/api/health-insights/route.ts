import { NextRequest, NextResponse } from 'next/server';
import { execSync } from 'child_process';
import { PIPELINE_DIR, WHOOP_DB } from '@/lib/paths';

export const dynamic = 'force-dynamic';

let cache: { data: unknown; ts: number } | null = null;
const CACHE_MS = 300_000; // 5 minutes

export async function GET(req: NextRequest) {
  try {
    const days = req.nextUrl.searchParams.get('days') || '90';

    const now = Date.now();
    const cacheKey = `insights_${days}`;
    if (cache && cache.ts > now - CACHE_MS) {
      return NextResponse.json(cache.data);
    }

    const output = execSync(
      `python3 -c "
import json, sys, os, warnings
warnings.filterwarnings('ignore')
sys.stdout = open(os.devnull, 'w')  # suppress prints
sys.path.insert(0, '${PIPELINE_DIR}')
from whoop_pattern_engine import WhoopPatternEngine
engine = WhoopPatternEngine('${WHOOP_DB}')
result = engine.generate_actionable_insights(days=${parseInt(days)})
sys.stdout = sys.__stdout__
print(json.dumps(result, default=str))
" 2>/dev/null`,
      { timeout: 30000, encoding: 'utf-8' }
    );

    const data = JSON.parse(output);
    cache = { data, ts: now };
    return NextResponse.json(data);
  } catch (e: unknown) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
