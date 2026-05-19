#!/usr/bin/env python3
"""
WHOOP Webhook Handler (v2)
Receives real-time push notifications from WHOOP when new data is available.
Validates HMAC-SHA256 signature, then triggers whoop_sync.py asynchronously.

Nginx proxies: /whoop/webhook → http://127.0.0.1:8889
"""
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from paths import WHOOP_SYNC_SCRIPT, WHOOP_WEBHOOK_LOG

PORT = int(os.environ.get("WHOOP_WEBHOOK_PORT", "8889"))
CLIENT_SECRET = os.environ.get("WHOOP_CLIENT_SECRET", "")
SYNC_SCRIPT = WHOOP_SYNC_SCRIPT
LOG_FILE = WHOOP_WEBHOOK_LOG

# ─── Pending events queue (for when token is expired at event time) ──────────
_pending_lock = threading.Lock()
_pending_events: list[dict] = []
_last_sync_at: float = 0
_sync_cooldown: float = 60  # min seconds between triggered syncs


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def validate_signature(raw_body: bytes, timestamp_header: str, signature_header: str) -> bool:
    """HMAC-SHA256: base64(HMAC(timestamp + raw_body, client_secret))"""
    if not CLIENT_SECRET:
        log("WARNING: WHOOP_CLIENT_SECRET not set — skipping signature validation")
        return True
    if not timestamp_header or not signature_header:
        return False
    payload = timestamp_header.encode() + raw_body
    expected = base64.b64encode(
        hmac.new(CLIENT_SECRET.encode(), payload, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature_header)


def run_sync(reason: str):
    """Run whoop_sync.py in background, with cooldown to prevent hammering."""
    global _last_sync_at
    now = time.time()
    if now - _last_sync_at < _sync_cooldown:
        log(f"Sync cooldown active ({int(_sync_cooldown - (now - _last_sync_at))}s remaining) — skipping for: {reason}")
        return
    _last_sync_at = now
    log(f"Triggering sync: {reason}")

    def _run():
        try:
            result = subprocess.run(
                ["python3", str(SYNC_SCRIPT)],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                log(f"Sync OK: {result.stdout.strip().splitlines()[-1] if result.stdout.strip() else 'done'}")
            else:
                last_line = (result.stdout + result.stderr).strip().splitlines()[-1] if (result.stdout + result.stderr).strip() else "no output"
                log(f"Sync failed (rc={result.returncode}): {last_line}")
        except subprocess.TimeoutExpired:
            log("Sync timed out after 120s")
        except Exception as e:
            log(f"Sync error: {e}")

    threading.Thread(target=_run, daemon=True).start()


class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default access log (we use our own)

    def send_status(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path.rstrip("/") not in ("", "/"):
            self.send_status(404, {"error": "not found"})
            return

        # Read raw body
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)

        # Validate signature
        sig = self.headers.get("X-WHOOP-Signature", "")
        ts = self.headers.get("X-WHOOP-Signature-Timestamp", "")
        if not validate_signature(raw_body, ts, sig):
            log(f"Invalid signature — rejecting webhook (ts={ts})")
            self.send_status(401, {"error": "invalid signature"})
            return

        # Parse event
        try:
            event = json.loads(raw_body)
        except Exception:
            self.send_status(400, {"error": "invalid json"})
            return

        event_type = event.get("type", "unknown")
        event_id = event.get("id", "?")
        user_id = event.get("user_id", "?")

        log(f"Webhook received: type={event_type} id={event_id} user={user_id}")

        # Return 200 immediately (async processing)
        self.send_status(200, {"ok": True, "received": event_type})

        # Skip delete events (no new data to sync)
        if event_type.endswith(".deleted"):
            log(f"Skipping delete event: {event_type}")
            return

        # Trigger sync in background
        run_sync(f"webhook:{event_type}")

    def do_GET(self):
        if self.path == "/health":
            self.send_status(200, {
                "status": "ok",
                "last_sync": _last_sync_at,
                "pending": len(_pending_events),
            })
        else:
            self.send_status(404, {"error": "not found"})


if __name__ == "__main__":
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log(f"WHOOP webhook handler listening on port {PORT}")
    if not CLIENT_SECRET:
        log("WARNING: WHOOP_CLIENT_SECRET not set — signature validation disabled")
    server = HTTPServer(("127.0.0.1", PORT), WebhookHandler)
    server.serve_forever()
