# Configuration

All configuration is via environment variables. The canonical reference is
[`.env.example`](.env.example) at the repo root; this file explains each
variable in context.

## Filesystem layout

Everything roots at `$OPENCLAW_BIOHUB_HOME`. The expected on-disk layout
is:

```
$OPENCLAW_BIOHUB_HOME/
├── data/
│   ├── health.db          # blood, supplements, nutrition, daily WHOOP rollup
│   └── whoop_raw.db       # raw WHOOP API payloads
├── secrets/
│   └── whoop_credentials.json   # OAuth tokens (mode 0600)
├── pipeline/              # copy of the pipeline/ scripts at deploy time
└── logs/
    └── whoop_webhook.log
```

| Variable | Default | What it does |
|----------|---------|--------------|
| `OPENCLAW_BIOHUB_HOME` | `/opt/openclaw-biohub` | Base directory. Everything else derives from this. |
| `HEALTH_DB_PATH` | `$OPENCLAW_BIOHUB_HOME/data/health.db` | Override the health DB location. |
| `WHOOP_DB_PATH` | `$OPENCLAW_BIOHUB_HOME/data/whoop_raw.db` | Override the WHOOP raw DB location. |
| `OPENCLAW_BIOHUB_SECRETS_DIR` | `$OPENCLAW_BIOHUB_HOME/secrets` | Where `whoop_credentials.json` lives. |
| `OPENCLAW_BIOHUB_PIPELINE_DIR` | `$OPENCLAW_BIOHUB_HOME/pipeline` | Where the dashboard expects to find Python scripts to `execSync`. |
| `OPENCLAW_BIOHUB_LOG_DIR` | `$OPENCLAW_BIOHUB_HOME/logs` | Webhook log location. |

For local development you usually only need `OPENCLAW_BIOHUB_HOME`.

## Initial setup

```bash
# Pick a home and create the layout
export OPENCLAW_BIOHUB_HOME=/opt/openclaw-biohub
sudo install -d -o $USER -g $USER -m 0750 "$OPENCLAW_BIOHUB_HOME"
install -d -m 0700 "$OPENCLAW_BIOHUB_HOME/secrets"
install -d -m 0755 "$OPENCLAW_BIOHUB_HOME/data"
install -d -m 0755 "$OPENCLAW_BIOHUB_HOME/logs"

# Drop the pipeline scripts in place
cp -a pipeline "$OPENCLAW_BIOHUB_HOME/"

# Create the empty DBs from the schema
sqlite3 "$OPENCLAW_BIOHUB_HOME/data/health.db" < db/schema.sql
sqlite3 "$OPENCLAW_BIOHUB_HOME/data/whoop_raw.db" < db/schema.sql
# (schema.sql is idempotent — both DBs accept it; tables they don't have
# will simply be created, even though only their own block is populated.)
```

## WHOOP OAuth setup

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
```
