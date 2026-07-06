#!/usr/bin/env python3
"""
WHOOP OAuth2 Handler
- /login → redirects to WHOOP authorization page (with offline scope)
- /callback → exchanges auth code for tokens, saves credentials
- /refresh → uses refresh_token to get a new access_token automatically
"""
import json
import os
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests as req_lib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from paths import WHOOP_CREDS_FILE

CLIENT_ID = os.environ.get("WHOOP_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("WHOOP_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("WHOOP_REDIRECT_URI", "")
PORT = int(os.environ.get("WHOOP_PORT", "8893"))

CREDS_FILE = WHOOP_CREDS_FILE
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"

SCOPES = "offline read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement"


def load_creds() -> dict:
    if CREDS_FILE.exists():
        try:
            return json.loads(CREDS_FILE.read_text())
        except Exception:
            pass
    return {}


def save_creds(data: dict):
    CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = load_creds()
    existing.update(data)
    existing["obtained_at"] = int(time.time())
    CREDS_FILE.write_text(json.dumps(existing, indent=2))
    print(f"Credentials saved to {CREDS_FILE}")


def post_form(url: str, params: dict) -> dict:
    print(f"POST {url} params={list(params.keys())}")
    resp = req_lib.post(url, data=params, timeout=15)
    print(f"Response: {resp.status_code} — {resp.text[:300]}")
    if not resp.ok:
        raise Exception(f"{resp.status_code} {resp.reason}: {resp.text}")
    return resp.json()


def do_refresh() -> dict | None:
    """Use refresh_token to get a new access_token. Returns new creds or None."""
    creds = load_creds()
    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        print("No refresh_token available — manual re-auth required")
        return None
    try:
        result = post_form(TOKEN_URL, {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            # WHOOP only returns a NEW (rotated) refresh_token when the refresh
            # request carries scope=offline. Without it the old token is consumed
            # but not replaced, so the next refresh 400s — forcing a manual
            # re-auth every few days. With it, the refresh chain never breaks.
            "scope": "offline",
        })
        print(f"Token refreshed: expires_in={result.get('expires_in')}s")
        save_creds(result)
        return result
    except Exception as e:
        print(f"Token refresh failed: {e}")
        return None


class WhoopHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(fmt % args)

    def send_html(self, code: int, body: str):
        encoded = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_json(self, code: int, data: dict):
        encoded = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = dict(urllib.parse.parse_qsl(parsed.query))

        if path == "/login":
            auth_params = {
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "scope": SCOPES,
                "response_type": "code",
                "state": "openclaw",
            }
            url = AUTH_URL + "?" + urllib.parse.urlencode(auth_params)
            self.send_response(302)
            self.send_header("Location", url)
            self.end_headers()

        elif path == "/callback":
            code = params.get("code")
            error = params.get("error")
            if error or not code:
                self.send_html(400, f"<h2>OAuth Error: {error or 'no code'}</h2>")
                return
            try:
                result = post_form(TOKEN_URL, {
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "redirect_uri": REDIRECT_URI,
                })
                print(f"Token response: {json.dumps({k: v for k, v in result.items() if k != 'access_token'})}")
                save_creds(result)
                has_refresh = "refresh_token" in result
                self.send_html(200, f"""
                    <html><body style="font-family:sans-serif;padding:2rem">
                    <h2>✅ WHOOP Connected</h2>
                    <p>Access token received (expires in {result.get('expires_in', '?')}s)</p>
                    <p>{'✅ Refresh token saved — auto-refresh enabled' if has_refresh else '⚠️ No refresh token received'}</p>
                    <p>You can close this tab.</p>
                    </body></html>
                """)
            except Exception as e:
                msg = str(e)
                print(f"Token exchange failed: {msg}")
                self.send_html(500, f"<html><body style='font-family:sans-serif;padding:2rem'><h2>❌ Token exchange failed</h2><pre>{msg}</pre></body></html>")

        elif path == "/refresh":
            result = do_refresh()
            if result:
                self.send_json(200, {"ok": True, "expires_in": result.get("expires_in")})
            else:
                self.send_json(400, {"ok": False, "error": "no refresh_token or refresh failed"})

        elif path == "/status":
            creds = load_creds()
            obtained = creds.get("obtained_at", 0)
            expires_in = creds.get("expires_in", 3600)
            remaining = max(0, int(obtained + expires_in - time.time()))
            has_refresh = bool(creds.get("refresh_token"))
            self.send_json(200, {
                "has_access_token": bool(creds.get("access_token")),
                "has_refresh_token": has_refresh,
                "token_remaining_seconds": remaining,
                "obtained_at": obtained,
            })

        elif path == "/health":
            # Simple health endpoint for monitoring/curl checks.
            # Considers the service healthy if creds file exists and has a refresh_token
            # (access tokens auto-rotate via /refresh, no need to fail just on expiry).
            creds = load_creds()
            healthy = bool(creds.get("refresh_token"))
            self.send_json(200 if healthy else 503, {
                "status": "ok" if healthy else "degraded",
                "has_refresh_token": healthy,
            })

        elif path == "/":
            # Root probe — also returns ok so generic uptime checks pass.
            self.send_json(200, {"status": "ok", "service": "whoop-oauth-handler"})

        else:
            self.send_html(404, "<h2>Not found</h2>")


if __name__ == "__main__":
    print(f"Whoop OAuth handler listening on port {PORT}")
    server = HTTPServer(("127.0.0.1", PORT), WhoopHandler)
    server.serve_forever()
