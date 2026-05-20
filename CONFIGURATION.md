# Configuration

All configuration is via environment variables. The canonical reference is
[`.env.example`](.env.example) at the repo root; this file explains each
variable in context. **For most adapters the recommended setup path is
`biohub connect <slug>`** — it walks you through credential capture
interactively. This document covers the env-var layer underneath the CLI
and the WHOOP systemd deployment, which is more involved than the others.

## Filesystem layout

Everything roots at `$OPENCLAW_BIOHUB_HOME`. The expected on-disk layout
(only the directories for adapters you've configured will be populated):

```
$OPENCLAW_BIOHUB_HOME/
├── data/
│   ├── health.db                # source-agnostic: blood, supplements, nutrition, daily_metrics
│   ├── whoop_raw.db             # raw WHOOP API payloads
│   ├── oura_raw.db              # raw Oura API payloads
│   ├── fitbit_raw.db            # raw Fitbit API payloads
│   ├── apple_health_raw.db      # raw Apple Health samples
│   └── garmin_raw.db            # raw Garmin Connect payloads (experimental)
├── secrets/
│   ├── whoop_credentials.json   # WHOOP OAuth tokens (single-file)
│   ├── oura.json                # Oura PAT
│   ├── fitbit.json              # Fitbit OAuth tokens + client_id/secret
│   ├── apple-health.json        # watch directory config
│   └── garmin/                  # garth token bundle (directory, multiple files)
├── pipeline/              # copy of the pipeline/ scripts at deploy time
└── logs/
    └── whoop_webhook.log
```

| Variable | Default | What it does |
|----------|---------|--------------|
| `OPENCLAW_BIOHUB_HOME` | `/opt/openclaw-biohub` | Base directory. Everything else derives from this. |
| `HEALTH_DB_PATH` | `$OPENCLAW_BIOHUB_HOME/data/health.db` | Override the health DB location. |
| `WHOOP_DB_PATH` | `$OPENCLAW_BIOHUB_HOME/data/whoop_raw.db` | Override the WHOOP raw DB location. |
| `OURA_DB_PATH` | `$OPENCLAW_BIOHUB_HOME/data/oura_raw.db` | Oura raw DB. |
| `FITBIT_DB_PATH` | `$OPENCLAW_BIOHUB_HOME/data/fitbit_raw.db` | Fitbit raw DB. |
| `APPLE_HEALTH_DB_PATH` | `$OPENCLAW_BIOHUB_HOME/data/apple_health_raw.db` | Apple Health raw DB. |
| `GARMIN_DB_PATH` | `$OPENCLAW_BIOHUB_HOME/data/garmin_raw.db` | Garmin raw DB. |
| `OPENCLAW_BIOHUB_SECRETS_DIR` | `$OPENCLAW_BIOHUB_HOME/secrets` | Where credentials live. |
| `OPENCLAW_BIOHUB_PIPELINE_DIR` | `$OPENCLAW_BIOHUB_HOME/pipeline` | Where the dashboard expects to find Python scripts to `execSync`. |
| `OPENCLAW_BIOHUB_LOG_DIR` | `$OPENCLAW_BIOHUB_HOME/logs` | Webhook log location. |
| `WHOOP_PORT` | `8893` | OAuth handler service port. |
| `WHOOP_WEBHOOK_PORT` | `8889` | Webhook receiver port. |
| `WHOOP_REFRESH_URL` | `http://127.0.0.1:8893/refresh` | OAuth handler refresh endpoint. |
| `FITBIT_CALLBACK_PORT` | `8894` | Localhost port for Fitbit OAuth callback. |

For local development you usually only need `OPENCLAW_BIOHUB_HOME`.

## Initial setup

```bash
# 1. Pick a home and create the layout
export OPENCLAW_BIOHUB_HOME=/opt/openclaw-biohub
sudo install -d -o $USER -g $USER -m 0750 "$OPENCLAW_BIOHUB_HOME"
install -d -m 0700 "$OPENCLAW_BIOHUB_HOME/secrets"
install -d -m 0755 "$OPENCLAW_BIOHUB_HOME/data"
install -d -m 0755 "$OPENCLAW_BIOHUB_HOME/logs"

# 2. Drop the pipeline scripts in place
cp -a pipeline "$OPENCLAW_BIOHUB_HOME/"

# 3. Create the empty health.db from the schema
sqlite3 "$OPENCLAW_BIOHUB_HOME/data/health.db" < db/schema.sql
# Adapter raw DBs (oura_raw.db, fitbit_raw.db, …) are created
# automatically on first sync from their respective adapter's schema.sql.

# 4. Install the biohub CLI
pip install -e .

# 5. Configure one or more adapters
biohub list-adapters
biohub connect oura      # easiest: just a Personal Access Token
biohub connect fitbit    # OAuth — opens browser
# biohub connect apple-health
# biohub connect garmin   # experimental
```

For each adapter, `biohub connect <slug>` prints the relevant
developer-portal URL, prompts for credentials, and runs a sanity sync
to confirm everything works. The WHOOP adapter has additional
systemd-handler setup — see the next section.

## Per-adapter notes

### Oura

One step: get a Personal Access Token from
<https://cloud.ouraring.com/personal-access-tokens>. No OAuth dance.

```
biohub connect oura
```

### Fitbit

Two steps:

1. Register a Personal app at <https://dev.fitbit.com/apps>:
   - Application Type: **Personal**
   - OAuth 2.0 Application Type: **Server**
   - Callback URL: `http://localhost:8894/fitbit/callback`
2. Run `biohub connect fitbit` — it'll prompt for the client ID +
   secret, then open the browser for the OAuth grant.

The CLI spins a one-shot localhost server on port 8894 to catch the
OAuth redirect (override via `FITBIT_CALLBACK_PORT`).

### Apple Health

No API; this adapter watches a directory for export files. Two
ingest modes:

1. **Health Auto Export iOS app** ($5 on the App Store) — writes
   per-metric JSON dumps to a folder. Point it at iCloud Drive /
   Dropbox / a self-hosted WebDAV mount that this host can read.
2. **Native Health.app export** — Settings → Health → Export All
   Health Data produces `export.zip`. AirDrop or copy to the same
   watch folder.

```
biohub connect apple-health
# prompts for the watch directory path
```

### Garmin (experimental)

⚠️ Uses the unofficial `garth` library; Garmin can break this at any
time without notice.

```
pip install garth
biohub connect garmin
# prompts for email + password; tokens cached to secrets/garmin/
```

## WHOOP setup (systemd-managed OAuth handler)

WHOOP is the only adapter that runs a long-running OAuth handler
service (because WHOOP rotates refresh tokens aggressively and the
service centralizes that). Other adapters use simpler in-process flows
driven by `biohub connect`.


1. **Create a WHOOP developer app.** Go to
   <https://developer.whoop.com>, sign in with your athlete account,
   create an app. Set the redirect URI to:

   ```
   https://YOUR_HOST/whoop/callback
   ```

   (You can use `http://localhost:8893/callback` for purely local dev.)

   Copy the client ID and client secret.

2. **Place them in a secrets file the systemd unit can read:**

   ```bash
   sudo install -d -m 0700 /etc/openclaw-biohub
   sudo install -m 0600 systemd/secrets.env.example /etc/openclaw-biohub/secrets.env
   sudoedit /etc/openclaw-biohub/secrets.env
   # Fill in WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET, WHOOP_REDIRECT_URI
   ```

3. **Install the systemd unit:**

   ```bash
   sudo install -m 0644 systemd/whoop-oauth-handler.service \
        /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now whoop-oauth-handler.service
   sudo systemctl status whoop-oauth-handler.service
   ```

4. **Run the OAuth flow once:**

   Visit `http://localhost:8893/login` (or however you've reverse-proxied
   it). After consent, the handler will write
   `$OPENCLAW_BIOHUB_HOME/secrets/whoop_credentials.json`. Subsequent
   syncs use that file and refresh the token automatically.

5. **Schedule the sync:**

   ```cron
   # Sync every 30 minutes (token refresh is automatic)
   */30 * * * * /usr/bin/python3 /opt/openclaw-biohub/pipeline/adapters/whoop/sync.py
   ```

   Or use a systemd timer.

## Dashboard (Next.js)

The dashboard uses the same `OPENCLAW_BIOHUB_HOME` to find the DBs.
Per-deployment overrides go in `dashboard/.env.local`:

```bash
OPENCLAW_BIOHUB_HOME=/opt/openclaw-biohub

# Optional: only if you want the "import supplement stack from Amazon"
# feature, which calls the Anthropic API.
# ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_BASE_URL=https://api.anthropic.com
```

Build and run:

```bash
cd dashboard
npm install
npm run build
npm start    # production
# or:
npm run dev  # development with HMR
```

For production, put the dashboard behind a reverse proxy with auth —
see [SECURITY.md](SECURITY.md).

## nginx examples

Two pieces need to be reachable from the WHOOP servers (the OAuth
callback and the optional webhook). Everything else stays on localhost.

```nginx
# WHOOP OAuth callback → python handler on :8893
location /whoop/callback {
    proxy_pass http://127.0.0.1:8893;
    proxy_set_header Host $host;
}

# WHOOP webhook receiver → python handler on :8889
location /whoop/webhook {
    proxy_pass http://127.0.0.1:8889;
    proxy_set_header Host $host;
}

# Dashboard, behind your auth method
location / {
    auth_basic "openclaw-biohub";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
}
```

## Validating your setup

```bash
# 1. Seed fixtures so you can see the dashboard without real data
OPENCLAW_BIOHUB_HOME=/tmp/oh python3 fixtures/seed.py

# 2. Run the analytics manually
OPENCLAW_BIOHUB_HOME=/tmp/oh python3 pipeline/whoop_pattern_engine.py
OPENCLAW_BIOHUB_HOME=/tmp/oh python3 pipeline/blood_marker_analytics.py
OPENCLAW_BIOHUB_HOME=/tmp/oh python3 pipeline/supplement_analytics.py

# 3. Run the test suite
pytest tests/ -v

# 4. Show adapter status
biohub list-adapters
```

## Migrating from v0.1 → v0.2

If you ran v0.1, the `whoop_daily` table needs to be renamed to
`daily_metrics` (with a new `source` column). Run once, before any
sync:

```bash
python3 db/migrate_v0.1_to_v0.2.py
# Looks at $OPENCLAW_BIOHUB_HOME/data/health.db by default.
```

The migration is idempotent — safe to run multiple times.
