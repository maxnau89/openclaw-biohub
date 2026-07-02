#!/usr/bin/env python3
"""Live push receiver for the "Health Auto Export" iOS app.

Apple exposes no server-side HealthKit API, so the standard way to get a
live feed is the Health Auto Export app's REST automation, which POSTs a
JSON (or CSV) payload on a schedule. This is a thin, token-authenticated
HTTP front-end for that: it validates the bearer token, writes the raw
payload into the Apple Health adapter's watch directory, and runs the
adapter's normal ingest — so the parsing/rollup logic is exactly the same
as the file-drop path, not a second copy.

Security posture (public-repo-safe defaults):
  • Binds to 127.0.0.1 by default. Set HEALTHKIT_HOST=0.0.0.0 only if you
    deliberately want it reachable on your LAN (the app runs on the same
    network). Never expose it to the public internet.
  • Requires a bearer token. Generated on `configure`, stored 0600 in
    secrets/apple-health.json under "receiver_token". Requests without a
    matching `Authorization: Bearer <token>` get 401.
  • GET /health is an unauthenticated liveness probe (no data).

Run:
    python3 -m adapters.apple_health.receiver          # from pipeline/
    HEALTHKIT_PORT=8894 HEALTHKIT_HOST=0.0.0.0 python3 -m adapters.apple_health.receiver
Point Health Auto Export at  http://<host>:8894/  with header
    Authorization: Bearer <receiver_token>
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Allow both `python3 -m adapters.apple_health.receiver` and direct execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from adapters.apple_health.sync import AppleHealthAdapter  # noqa: E402

DEFAULT_PORT = 8894
MAX_BODY_BYTES = 64 * 1024 * 1024   # 64 MB — HAE payloads are large but bounded


def _load_secrets(adapter: AppleHealthAdapter) -> dict:
    if adapter.secrets_path.exists():
        return json.loads(adapter.secrets_path.read_text())
    return {}


def ensure_receiver_token(adapter: AppleHealthAdapter) -> str:
    """Return the configured receiver token, generating + persisting one
    (0600) on first use. Requires the adapter to already be connected
    (watch_dir set)."""
    cfg = _load_secrets(adapter)
    if not cfg.get("watch_dir"):
        raise SystemExit(
            "Apple Health adapter not configured. Run `biohub connect apple-health` first."
        )
    if not cfg.get("receiver_token"):
        cfg["receiver_token"] = secrets.token_urlsafe(24)
        adapter.secrets_path.write_text(json.dumps(cfg))
        adapter.secrets_path.chmod(0o600)
    return cfg["receiver_token"]


def _make_handler(adapter: AppleHealthAdapter, token: str, watch_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        # Silence default noisy logging; print concise lines instead.
        def log_message(self, fmt, *args):  # noqa: N802
            return

        def _send(self, code: int, body: dict) -> None:
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self) -> bool:
            hdr = self.headers.get("Authorization", "")
            if not hdr.startswith("Bearer "):
                return False
            return secrets.compare_digest(hdr[7:].strip(), token)

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") in ("/health", "/ping", ""):
                self._send(200, {"status": "ok", "service": "biohub-healthkit-receiver"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if not self._authorized():
                self._send(401, {"error": "missing or invalid bearer token"})
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0 or length > MAX_BODY_BYTES:
                self._send(413, {"error": f"body must be 1..{MAX_BODY_BYTES} bytes"})
                return
            body = self.rfile.read(length)

            # Extension from content-type: HAE pushes JSON by default; CSV
            # export is also accepted and lands as a .csv for the adapter.
            ctype = (self.headers.get("Content-Type", "") or "").lower()
            ext = ".csv" if ("csv" in ctype or self.path.lower().endswith(".csv")) else ".json"
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            fp = watch_dir / f"hae-push-{stamp}{ext}"
            try:
                fp.write_bytes(body)
            except OSError as e:
                self._send(500, {"error": f"could not write payload: {e}"})
                return

            # Ingest immediately so the push is truly "live". Reuse the
            # adapter's own sync() so parsing/rollup is identical to the
            # file-drop path (it scans the watch dir, picks up this file).
            try:
                result = adapter.sync()
                adapter.rollup_to_health_db()
            except Exception as e:  # noqa: BLE001 — report, keep serving
                self._send(202, {"status": "stored", "file": fp.name,
                                 "ingest_error": str(e)})
                return
            self._send(200, {"status": "ingested", "file": fp.name,
                             "rows_inserted": result.rows_inserted,
                             "error": result.error})

    return Handler


def main() -> int:
    adapter = AppleHealthAdapter()
    token = ensure_receiver_token(adapter)
    watch_dir = adapter._watch_dir()
    watch_dir.mkdir(parents=True, exist_ok=True)

    host = os.environ.get("HEALTHKIT_HOST", "127.0.0.1")
    port = int(os.environ.get("HEALTHKIT_PORT", str(DEFAULT_PORT)))
    server = ThreadingHTTPServer((host, port), _make_handler(adapter, token, watch_dir))

    lan_note = "" if host == "127.0.0.1" else "  ⚠ reachable on your LAN"
    print(f"biohub HealthKit receiver on http://{host}:{port}/{lan_note}")
    print(f"  watch dir : {watch_dir}")
    print(f"  auth      : Authorization: Bearer {token}")
    print("  Point Health Auto Export's REST automation at the URL above.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
