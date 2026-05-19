import { NextRequest, NextResponse } from 'next/server';
import { getLagHours, getDailyUnits } from '@/lib/supplement-lags';

export const dynamic = 'force-dynamic';

// Possible column names for each field across Amazon locales + export tools
const TITLE_COLS    = ['title', 'produktname', 'product name', 'name', 'item', 'items', 'artikelname',
                       'beschreibung', 'description', 'product', 'product title', 'item name',
                       'produkt', 'artikel', 'bestellte artikel'];
const DATE_COLS     = ['order date', 'bestelldatum', 'datum', 'date', 'ordered', 'order date (gmt)',
                       'purchase date', 'bestelldatum (gmt)', 'order placed', 'placed'];
const ASIN_COLS     = ['asin', 'asin/isbn', 'isbn', 'sku'];
const ORDER_COLS    = ['order id', 'bestellnummer', 'ordernumber', 'order number', 'order-id',
                       'order #', 'orderId', 'order_id'];

interface AmazonOrder {
  order_id: string;
  order_date: string;  // YYYY-MM-DD
  title: string;
  asin: string;
}

export interface AmazonImportSuggestion {
  suggested_name: string;
  active_ingredient: string | null;
  dose_mg: number | null;
  dose_unit: string;
  asin: string;
  confidence: number;
  unit_count: number;
  units_per_day: number;
  intake_periods: {
    intake_start: string;
    intake_end: string;
    duration_days: number;
    order_count: number;
    is_continuous: boolean;
    order_ids: string[];
  }[];
}

// ─── POST ─────────────────────────────────────────────────────────────────
export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();
    const type = formData.get('type') as string;

    if (type === 'csv') {
      const file = formData.get('file') as File | null;
      if (!file) return NextResponse.json({ error: 'No file' }, { status: 400 });

      const text = await file.text();
      const firstLine = text.split('\n')[0]?.slice(0, 200) || '';
      const { orders, headers } = parseCsv(text);

      if (!orders.length) {
        const headerInfo = headers.length
          ? `Detected columns: [${headers.join(' | ')}]`
          : `Could not detect headers. First line: "${firstLine}"`;
        return NextResponse.json({
          error: `No orders found. ${headerInfo}`,
          debug: { headers, first_line: firstLine },
        }, { status: 400 });
      }

      const suggestions = await identifySupplements(orders);
      return NextResponse.json({
        suggestions,
        total_orders: orders.length,
        sample_titles: orders.slice(0, 5).map(o => o.title),
      });
    }

    if (type === 'url') {
      const url = formData.get('url') as string;
      if (!url) return NextResponse.json({ error: 'No URL' }, { status: 400 });

      const title = await fetchAmazonTitle(url);
      if (!title) return NextResponse.json({ error: 'Could not fetch page title' }, { status: 400 });

      const asin = extractAsin(url);
      const orders: AmazonOrder[] = [{
        order_id: '',
        order_date: new Date().toISOString().slice(0, 10),
        title,
        asin: asin || '',
      }];

      const suggestions = await identifySupplements(orders);
      return NextResponse.json({ suggestions });
    }

    return NextResponse.json({ error: 'type must be "csv" or "url"' }, { status: 400 });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}

// ─── CSV parsing ──────────────────────────────────────────────────────────
function parseCsv(text: string): { orders: AmazonOrder[]; headers: string[] } {
  // Normalize line endings
  const lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length < 2) return { orders: [], headers: [] };

  // Detect delimiter: semicolon first (common in DE exports), then comma, then tab
  const firstLine = lines[0];
  const delim = firstLine.includes(';') ? ';' : firstLine.includes('\t') ? '\t' : ',';

  // Parse header row
  const rawHeaders = parseCsvLine(firstLine, delim);
  const headers = rawHeaders.map(h => h.replace(/^"|"$/g, '').trim());

  // Find columns by matching against known aliases (case-insensitive)
  const findCol = (aliases: string[]): number => {
    for (const alias of aliases) {
      const idx = headers.findIndex(h => h.toLowerCase() === alias.toLowerCase());
      if (idx >= 0) return idx;
    }
    // Partial match fallback
    for (const alias of aliases) {
      const idx = headers.findIndex(h => h.toLowerCase().includes(alias.toLowerCase()));
      if (idx >= 0) return idx;
    }
    return -1;
  };

  const titleIdx = findCol(TITLE_COLS);
  const dateIdx  = findCol(DATE_COLS);
  const asinIdx  = findCol(ASIN_COLS);
  const orderIdx = findCol(ORDER_COLS);

  // If no title column found, try using the longest text column heuristically
  // (some browser-plugin exports may use non-standard headers)
  let effectiveTitleIdx = titleIdx;
  if (effectiveTitleIdx < 0 && headers.length > 0) {
    // Find column with longest average value across first 5 data rows
    const sample = lines.slice(1, 6).map(l => parseCsvLine(l, delim).map(c => c.replace(/^"|"$/g, '').trim()));
    let maxAvgLen = 0;
    for (let col = 0; col < headers.length; col++) {
      const avg = sample.reduce((s, row) => s + (row[col]?.length || 0), 0) / sample.length;
      if (avg > maxAvgLen) { maxAvgLen = avg; effectiveTitleIdx = col; }
    }
  }

  if (effectiveTitleIdx < 0) return { orders: [], headers };

  const orders: AmazonOrder[] = [];

  for (let i = 1; i < lines.length; i++) {
    const cols = parseCsvLine(lines[i], delim).map(c => c.replace(/^"|"$/g, '').trim());
    const title = cols[effectiveTitleIdx] || '';
    if (!title || title.length < 3) continue;

    const rawDate = dateIdx >= 0 ? (cols[dateIdx] || '') : '';
    const order_date = normalizeDate(rawDate) || new Date().toISOString().slice(0, 10);

    orders.push({
      order_id: orderIdx >= 0 ? (cols[orderIdx] || '') : '',
      order_date,
      title,
      asin: asinIdx >= 0 ? (cols[asinIdx] || '') : '',
    });
  }

  return { orders, headers };
}

function parseCsvLine(line: string, delim: string): string[] {
  const result: string[] = [];
  let current = '';
  let inQuotes = false;

  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      inQuotes = !inQuotes;
    } else if (ch === delim && !inQuotes) {
      result.push(current);
      current = '';
    } else {
      current += ch;
    }
  }
  result.push(current);
  return result;
}

function normalizeDate(raw: string): string | null {
  if (!raw) return null;
  // Try formats: DD.MM.YYYY, MM/DD/YYYY, YYYY-MM-DD, "Month DD, YYYY"
  const isoMatch = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (isoMatch) return `${isoMatch[1]}-${isoMatch[2]}-${isoMatch[3]}`;

  const deMatch = raw.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})/);
  if (deMatch) return `${deMatch[3]}-${deMatch[2].padStart(2,'0')}-${deMatch[1].padStart(2,'0')}`;

  const usMatch = raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (usMatch) return `${usMatch[3]}-${usMatch[1].padStart(2,'0')}-${usMatch[2].padStart(2,'0')}`;

  try {
    const d = new Date(raw);
    if (!isNaN(d.getTime())) return d.toISOString().slice(0, 10);
  } catch { /* */ }

  return null;
}

// ─── Extract ASIN from Amazon URL ────────────────────────────────────────
function extractAsin(url: string): string | null {
  const m = url.match(/\/dp\/([A-Z0-9]{10})/i) || url.match(/\/gp\/product\/([A-Z0-9]{10})/i);
  return m ? m[1] : null;
}

// ─── Fetch Amazon product title ───────────────────────────────────────────
async function fetchAmazonTitle(url: string): Promise<string | null> {
  try {
    const res = await fetch(url, {
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; bot)' },
      signal: AbortSignal.timeout(10000),
    });
    const html = await res.text();
    const titleMatch = html.match(/<title>([^<]+)<\/title>/i);
    return titleMatch ? titleMatch[1].replace(' : Amazon.de.*', '').replace(/ - Amazon\..*$/, '').trim() : null;
  } catch {
    return null;
  }
}

// ─── LLM: identify supplements in order list ─────────────────────────────
async function identifySupplements(orders: AmazonOrder[]): Promise<AmazonImportSuggestion[]> {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) throw new Error('ANTHROPIC_API_KEY not set on server');

  const baseUrl = (process.env.ANTHROPIC_BASE_URL || 'https://api.anthropic.com').replace(/\/$/, '');

  // Deduplicate by ASIN (keep all dates)
  const byAsin = new Map<string, AmazonOrder[]>();
  for (const o of orders) {
    const key = o.asin || o.title.slice(0, 40);
    if (!byAsin.has(key)) byAsin.set(key, []);
    byAsin.get(key)!.push(o);
  }

  // Only send unique products to Claude (max 50 to keep prompt manageable)
  const uniqueProducts = Array.from(byAsin.entries()).slice(0, 50).map(([, orders]) => ({
    title: orders[0].title,
    asin: orders[0].asin,
  }));

  const prompt = `Analyze these Amazon order titles and identify supplements, vitamins, minerals, herbs, or other health products.

Products:
${uniqueProducts.map((p, i) => `${i + 1}. ${p.title}`).join('\n')}

For each product, respond with JSON. Only include products that are clearly health supplements. Return an array:
[
  {
    "index": 1,
    "is_supplement": true,
    "suggested_name": "Magnesium Bisglycinat",
    "active_ingredient": "Magnesium",
    "dose_mg": 400,
    "dose_unit": "mg",
    "unit_count": 120,
    "unit_type": "capsule",
    "confidence": 0.95
  }
]

Rules:
- unit_count: extract from title (e.g. "120 Kapseln" → 120, "500g" → 500, "365 Tabletten" → 365)
- unit_type: "capsule", "tablet", "softgel", "scoop", "ml", "g"
- dose_mg: the dose per unit (e.g. "400mg Magnesium" → 400)
- confidence: 0-1 (1=clear supplement, 0=not a supplement)
- Skip food items, household products, books, etc.
- Respond with ONLY the JSON array, no explanation.`;

  const res = await fetch(`${baseUrl}/v1/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 4096,
      messages: [{ role: 'user', content: prompt }],
    }),
    signal: AbortSignal.timeout(30000),
  });

  if (!res.ok) {
    const errBody = await res.text().catch(() => '');
    throw new Error(`Claude API ${res.status}: ${errBody.slice(0, 200)}`);
  }

  const data = await res.json();
  const text = data.content?.[0]?.text || '';
  const jsonMatch = text.match(/\[[\s\S]*\]/);
  if (!jsonMatch) throw new Error(`Claude returned no JSON array. Response: "${text.slice(0, 200)}"`);

  const parsed: Array<{
    index: number; is_supplement: boolean; suggested_name: string;
    active_ingredient: string; dose_mg: number; dose_unit: string;
    unit_count: number; unit_type: string; confidence: number;
  }> = JSON.parse(jsonMatch[0]);

  const suggestions: AmazonImportSuggestion[] = [];

  for (const item of parsed) {
    if (!item.is_supplement || item.confidence < 0.5) continue;

    const product = uniqueProducts[item.index - 1];
    if (!product) continue;

    const asinKey = product.asin || product.title.slice(0, 40);
    const productOrders = byAsin.get(asinKey) || [];

    const unitsPerDay = getDailyUnits(item.suggested_name || item.active_ingredient || '');
    const lagHours = getLagHours(item.suggested_name || item.active_ingredient || '');

    const unitCount = item.unit_count || 60;
    const durationDays = Math.round(unitCount / unitsPerDay);

    const periods = buildIntakePeriods(productOrders, durationDays);

    suggestions.push({
      suggested_name: item.suggested_name,
      active_ingredient: item.active_ingredient || null,
      dose_mg: item.dose_mg || null,
      dose_unit: item.dose_unit || 'mg',
      asin: product.asin,
      confidence: item.confidence,
      unit_count: unitCount,
      units_per_day: unitsPerDay,
      intake_periods: periods,
    });

    // Attach lag hours for frontend (not in type but safe to add)
    (suggestions[suggestions.length - 1] as AmazonImportSuggestion & { lag_hours: number }).lag_hours = lagHours;
  }

  return suggestions;
}

// ─── Build intake periods from ordered list of purchase dates ────────────
function buildIntakePeriods(
  orders: AmazonOrder[],
  durationDays: number,
): AmazonImportSuggestion['intake_periods'] {
  if (!orders.length) return [];

  const sorted = [...orders].sort((a, b) => a.order_date.localeCompare(b.order_date));
  const GAP_THRESHOLD = 14; // days gap before splitting into separate periods

  const periods: AmazonImportSuggestion['intake_periods'] = [];
  let currentStart = sorted[0].order_date;
  let currentEnd = addDays(sorted[0].order_date, durationDays);
  let orderCount = 1;
  const orderIds = [sorted[0].order_id];
  let isContinuous = false;

  for (let i = 1; i < sorted.length; i++) {
    const nextOrder = sorted[i];
    const gapDays = daysBetween(currentEnd, nextOrder.order_date);

    if (gapDays <= GAP_THRESHOLD) {
      // Extend the current period
      const newEnd = addDays(nextOrder.order_date, durationDays);
      if (newEnd > currentEnd) currentEnd = newEnd;
      orderCount++;
      orderIds.push(nextOrder.order_id);
      isContinuous = true;
    } else {
      // Close current period, start new one
      periods.push({
        intake_start: currentStart,
        intake_end: currentEnd,
        duration_days: daysBetween(currentStart, currentEnd),
        order_count: orderCount,
        is_continuous: isContinuous,
        order_ids: [...orderIds],
      });
      currentStart = nextOrder.order_date;
      currentEnd = addDays(nextOrder.order_date, durationDays);
      orderCount = 1;
      orderIds.splice(0, orderIds.length, nextOrder.order_id);
      isContinuous = false;
    }
  }

  // Push final period
  periods.push({
    intake_start: currentStart,
    intake_end: currentEnd,
    duration_days: daysBetween(currentStart, currentEnd),
    order_count: orderCount,
    is_continuous: isContinuous,
    order_ids: [...orderIds],
  });

  return periods;
}

function addDays(date: string, days: number): string {
  const d = new Date(date);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function daysBetween(a: string, b: string): number {
  const msPerDay = 86400000;
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / msPerDay);
}

