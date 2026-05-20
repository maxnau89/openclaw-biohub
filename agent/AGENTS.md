# AGENTS.md — Wellness Coach

## Your Job
You are a specialized health agent. Read `SOUL.md` every session for your
identity and approach; read `USER.md` for the human you're working with.

## Data Access

SQLite databases under `$OPENCLAW_BIOHUB_HOME/data/`. The user may have
one, several, or all of these depending on which adapters they have
configured (run `biohub list-adapters` to see):

- **`health.db`** — source-agnostic. Prefer this for daily summaries.
  - `daily_metrics` — one row per `(source, date)`. Columns:
    `recovery_score`, `hrv_ms`, `resting_hr`, `spo2`, `skin_temp_c`,
    `sleep_performance`, `sleep_hours`, `sleep_efficiency`,
    `rem_hours`, `deep_sleep_hours`, `light_sleep_hours`,
    `day_strain`, `calories_burned`, `steps`, `active_minutes`.
  - `blood_panels`, `blood_markers`, `nutrition_logs`, `supplements`,
    `supplement_log`.
- **`whoop_raw.db`** — WHOOP API payloads.
- **`oura_raw.db`** — Oura Ring API payloads.
- **`fitbit_raw.db`** — Fitbit Web API payloads.
- **`apple_health_raw.db`** — Apple Health samples.
- **`garmin_raw.db`** — Garmin Connect (experimental).

The `health.db` schema is in `db/schema.sql`. Each adapter's raw-DB
schema lives at `pipeline/adapters/<slug>/schema.sql`.

## Quick Queries

Resolve paths via env vars so this works in any deployment:

```bash
BIOHUB_HOME="${OPENCLAW_BIOHUB_HOME:-/opt/openclaw-biohub}"
HEALTH_DB="${HEALTH_DB_PATH:-$BIOHUB_HOME/data/health.db}"

# Latest 7 days of daily metrics across all configured sources
sqlite3 "$HEALTH_DB" \
  "SELECT date, source, recovery_score, hrv_ms, sleep_hours
   FROM daily_metrics ORDER BY date DESC LIMIT 7"

# Filter to a specific source (whoop, oura, fitbit, apple-health, garmin)
sqlite3 "$HEALTH_DB" \
  "SELECT date, recovery_score, hrv_ms, sleep_hours
   FROM daily_metrics WHERE source = 'oura'
   ORDER BY date DESC LIMIT 7"

# Latest blood panel
sqlite3 "$HEALTH_DB" \
  "SELECT m.marker_name, m.value, m.unit, m.status
   FROM blood_markers m JOIN blood_panels p ON m.panel_id = p.id
   WHERE p.panel_date = (SELECT MAX(panel_date) FROM blood_panels)
   ORDER BY m.marker_name"
```

For richer analytics, prefer the Python helpers under `pipeline/`
(`blood_marker_analytics.py`, `supplement_analytics.py`,
`whoop_pattern_engine.py`).

## Memory
Store health insights in a workspace-local `memory/` directory. Never
write user-identifying data into files that ship with the repo.
