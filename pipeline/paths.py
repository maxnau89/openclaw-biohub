"""Centralized path resolution for the openclaw-biohub Python pipeline.

All filesystem layout is rooted at $OPENCLAW_BIOHUB_HOME. Individual paths
can be overridden by their own env vars for non-standard deployments.

Defaults assume the systemd-style layout used in `systemd/whoop-oauth-handler.service`
(`/opt/openclaw-biohub/...`). For local development, point OPENCLAW_BIOHUB_HOME
at a writable directory.
"""
import os
from pathlib import Path

BIOHUB_HOME = Path(os.environ.get("OPENCLAW_BIOHUB_HOME", "/opt/openclaw-biohub"))

HEALTH_DB = Path(os.environ.get("HEALTH_DB_PATH", BIOHUB_HOME / "data" / "health.db"))
WHOOP_DB = Path(os.environ.get("WHOOP_DB_PATH", BIOHUB_HOME / "data" / "whoop_raw.db"))
OURA_DB = Path(os.environ.get("OURA_DB_PATH", BIOHUB_HOME / "data" / "oura_raw.db"))
APPLE_HEALTH_DB = Path(os.environ.get("APPLE_HEALTH_DB_PATH", BIOHUB_HOME / "data" / "apple_health_raw.db"))

SECRETS_DIR = Path(os.environ.get("OPENCLAW_BIOHUB_SECRETS_DIR", BIOHUB_HOME / "secrets"))
WHOOP_CREDS_FILE = SECRETS_DIR / "whoop_credentials.json"

PIPELINE_DIR = Path(os.environ.get("OPENCLAW_BIOHUB_PIPELINE_DIR", BIOHUB_HOME / "pipeline"))
WHOOP_SYNC_SCRIPT = PIPELINE_DIR / "adapters" / "whoop" / "sync.py"

LOG_DIR = Path(os.environ.get("OPENCLAW_BIOHUB_LOG_DIR", BIOHUB_HOME / "logs"))
WHOOP_WEBHOOK_LOG = LOG_DIR / "whoop_webhook.log"
