// Centralized path resolution for the openclaw-biohub dashboard.
// Mirrors pipeline/paths.py; keep them in sync.

import path from 'path';

export const BIOHUB_HOME =
  process.env.OPENCLAW_BIOHUB_HOME || '/opt/openclaw-biohub';

export const HEALTH_DB =
  process.env.HEALTH_DB_PATH || path.join(BIOHUB_HOME, 'data', 'health.db');

export const WHOOP_DB =
  process.env.WHOOP_DB_PATH || path.join(BIOHUB_HOME, 'data', 'whoop_raw.db');

export const OURA_DB =
  process.env.OURA_DB_PATH || path.join(BIOHUB_HOME, 'data', 'oura_raw.db');

export const APPLE_HEALTH_DB =
  process.env.APPLE_HEALTH_DB_PATH || path.join(BIOHUB_HOME, 'data', 'apple_health_raw.db');

export const FITBIT_DB =
  process.env.FITBIT_DB_PATH || path.join(BIOHUB_HOME, 'data', 'fitbit_raw.db');

export const GARMIN_DB =
  process.env.GARMIN_DB_PATH || path.join(BIOHUB_HOME, 'data', 'garmin_raw.db');

export const SECRETS_DIR =
  process.env.OPENCLAW_BIOHUB_SECRETS_DIR || path.join(BIOHUB_HOME, 'secrets');

export const WHOOP_CREDS_FILE = path.join(SECRETS_DIR, 'whoop_credentials.json');

export const PIPELINE_DIR =
  process.env.OPENCLAW_BIOHUB_PIPELINE_DIR || path.join(BIOHUB_HOME, 'pipeline');
