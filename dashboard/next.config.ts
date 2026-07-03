import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
  // Serve under a sub-path when reverse-proxied (e.g. /biohub). Set
  // NEXT_PUBLIC_BASE_PATH at build time; empty ⇒ root hosting. apiUrl()
  // in lib/fetcher mirrors this for raw fetch() calls.
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || '',
  serverExternalPackages: ['better-sqlite3'],
};

export default nextConfig;
