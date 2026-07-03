import { useState, useEffect, useCallback } from 'react';

// When the dashboard is served under a sub-path (reverse-proxied at
// e.g. /biohub), Next's basePath prefixes pages + assets automatically, but
// NOT raw fetch() calls. `apiUrl` bridges that: it prepends the same base so
// API requests resolve under the sub-path. Baked at build time via
// NEXT_PUBLIC_BASE_PATH; empty string ⇒ root hosting (no change).
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || '';
export const apiUrl = (path: string) => `${BASE_PATH}${path}`;

export function useAutoRefresh<T>(url: string, intervalMs = 15000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(apiUrl(url));
      if (!res.ok) throw new Error(`${res.status}`);
      const json = await res.json();
      setData(json);
      setError(null);
      setLastUpdated(new Date());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);

  return { data, error, loading, lastUpdated, refresh };
}
