import { NextResponse } from 'next/server';
import { getWhoopData } from '@/lib/whoop';

export const dynamic = 'force-dynamic';

let cache: { data: ReturnType<typeof getWhoopData>; ts: number } | null = null;

export async function GET() {
  try {
    const now = Date.now();
    if (cache && now - cache.ts < 120000) {
      return NextResponse.json(cache.data);
    }
    const data = getWhoopData();
    cache = { data, ts: now };
    return NextResponse.json(data);
  } catch (e: unknown) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
