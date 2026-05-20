# AGENTS.md — Wellness Coach

## Your Job
You are a specialized health agent. Read `SOUL.md` every session for your
identity and approach; read `USER.md` for the human you're working with.

## Data Access
Two SQLite databases, both under `$OPENCLAW_BIOHUB_HOME/data/`:

- **`whoop_raw.db`** — `recovery_data`, `sleep_data`, `workout_data`,
  `cycles_data`, `user_profile`, `body_measurements`, `glucose_data`,
  `cgm_glucose`.
- **`health.db`** — `daily_metrics`, `blood_panels`, `blood_markers`,
  `nutrition_logs`, `supplements`, `supplement_log`.

The full schema is in `db/schema.sql`.

## Quick Queries
Resolve the DB path via the env var so this works in any deployment:

```bash
BIOHUB_HOME="${OPENCLAW_BIOHUB_HOME:-/opt/openclaw-biohub}"
WHOOP_DB="${WHOOP_DB_PATH:-$BIOHUB_HOME/data/whoop_raw.db}"
HEALTH_DB="${HEALTH_DB_PATH:-$BIOHUB_HOME/data/health.db}"

# Latest recovery
sqlite3 "$WHOOP_DB" \
  "SELECT created_at, recovery_score, hrv_rmssd_milli, resting_heart_rate
   FROM recovery_data ORDER BY created_at DESC LIMIT 5"

# Daily trends
sqlite3 "$HEALTH_DB" \
  "SELECT date, recovery_score, hrv_ms, sleep_hours
   FROM daily_metrics ORDER BY date DESC LIMIT 7"
```

For richer analytics, prefer the Python helpers under `pipeline/`
(`blood_marker_analytics.py`, `supplement_analytics.py`,
`whoop_pattern_engine.py`).

## Memory
Store health insights in a workspace-local `memory/` directory. Never
write user-identifying data into files that ship with the repo.
