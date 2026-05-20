"""Shared OAuth 2.0 primitives for adapters that need them.

The functions here are deliberately stateless — caller supplies the
credentials path, the provider's endpoints, and the client_id /
client_secret. That keeps each adapter's OAuth bits short while
letting it customize scopes, response handling, and storage layout.

Currently used by:
- pipeline/adapters/whoop/oauth_handler.py  (refactor pending — it
  still has its own copy)
- pipeline/adapters/fitbit/sync.py          (planned, v0.2 Step 5)

The standard OAuth 2.0 flow these helpers compose:
  1. build_authorize_url(...) — point the user's browser here
  2. user authorizes; provider redirects with ?code=...
  3. exchange_code_for_tokens(...) — code → access_token + refresh_token
  4. is_expired(creds, ...) → True  →  refresh_access_token(...)
"""
from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path
from typing import Any

import requests


# ─── Credential file I/O ─────────────────────────────────────────────────────


def load_credentials(path: Path) -> dict[str, Any]:
    """Read credentials JSON. Returns empty dict if file missing or malformed."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_credentials(path: Path, data: dict[str, Any], *, merge: bool = True) -> None:
    """Persist credentials. By default merges with existing values so a
    refresh response (which often omits the refresh_token) doesn't wipe
    earlier fields. Always stamps `obtained_at` (unix seconds).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_credentials(path) if merge else {}
    existing.update(data)
    existing["obtained_at"] = int(time.time())
    path.write_text(json.dumps(existing, indent=2))
    try:
        path.chmod(0o600)
    except OSError:
        # Some filesystems (e.g. mounted volumes) won't honour chmod;
        # secrets are still local-only so this is best-effort.
        pass


# ─── Token expiry ────────────────────────────────────────────────────────────


def is_expired(creds: dict[str, Any], *, threshold_seconds: int = 300) -> bool:
    """True if the token is missing, has no expiry info, or expires within
    `threshold_seconds`. The default threshold covers stale-token + clock
    drift; raise it for long-running batch jobs."""
    if not creds.get("access_token"):
        return True
    obtained = creds.get("obtained_at")
    expires_in = creds.get("expires_in")
    if obtained is None or expires_in is None:
        return True
    remaining = (obtained + expires_in) - time.time()
    return remaining < threshold_seconds


# ─── Authorize-URL construction ──────────────────────────────────────────────


def build_authorize_url(
    auth_url: str,
    client_id: str,
    redirect_uri: str,
    scopes: str | list[str],
    *,
    state: str | None = None,
    extra: dict[str, str] | None = None,
) -> str:
    """Construct an OAuth 2.0 authorize-endpoint URL. `scopes` can be a
    space-separated string (WHOOP style) or a list (we'll join)."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes if isinstance(scopes, str) else " ".join(scopes),
    }
    if state:
        params["state"] = state
    if extra:
        params.update(extra)
    return f"{auth_url}?{urllib.parse.urlencode(params)}"


# ─── Token endpoint helpers ──────────────────────────────────────────────────


def _post_form(
    token_url: str,
    params: dict[str, str],
    *,
    basic_auth: tuple[str, str] | None = None,
    timeout: int = 15,
) -> dict[str, Any]:
    """Form-encoded POST to a token endpoint. `basic_auth` is used by
    providers that require client credentials via HTTP Basic auth instead
    of form parameters (Fitbit). The body parses as JSON."""
    headers = {"Accept": "application/json"}
    resp = requests.post(
        token_url, data=params, headers=headers,
        auth=basic_auth, timeout=timeout,
    )
    if not resp.ok:
        raise RuntimeError(
            f"OAuth token request failed: {resp.status_code} {resp.reason} — {resp.text[:300]}"
        )
    return resp.json()


def exchange_code_for_tokens(
    token_url: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    *,
    use_basic_auth: bool = False,
) -> dict[str, Any]:
    """Exchange an authorization code for access + refresh tokens.

    Some providers (Fitbit) require client credentials via HTTP Basic
    auth instead of form params — set `use_basic_auth=True` for those.
    """
    params: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if use_basic_auth:
        return _post_form(token_url, params, basic_auth=(client_id, client_secret))
    params["client_id"] = client_id
    params["client_secret"] = client_secret
    return _post_form(token_url, params)


def refresh_access_token(
    token_url: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    *,
    use_basic_auth: bool = False,
) -> dict[str, Any]:
    """Use a refresh_token to get a new access_token. Returns the
    provider's raw JSON response.

    Most providers rotate the refresh_token on each refresh — the
    response carries a new one that the caller must persist.
    """
    params: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if use_basic_auth:
        return _post_form(token_url, params, basic_auth=(client_id, client_secret))
    params["client_id"] = client_id
    params["client_secret"] = client_secret
    return _post_form(token_url, params)


# ─── Convenience wrapper: get-or-refresh ─────────────────────────────────────


def ensure_fresh_access_token(
    creds_path: Path,
    token_url: str,
    client_id: str,
    client_secret: str,
    *,
    use_basic_auth: bool = False,
    threshold_seconds: int = 300,
) -> str:
    """Read credentials, refresh if near-expiry, return a valid access_token.

    Raises if credentials are missing or refresh fails.
    """
    creds = load_credentials(creds_path)
    if not is_expired(creds, threshold_seconds=threshold_seconds):
        return creds["access_token"]

    refresh = creds.get("refresh_token")
    if not refresh:
        raise RuntimeError(
            f"No refresh_token in {creds_path}; run `biohub connect <slug>` "
            "to complete OAuth setup."
        )
    fresh = refresh_access_token(
        token_url, client_id, client_secret, refresh,
        use_basic_auth=use_basic_auth,
    )
    save_credentials(creds_path, fresh)
    return fresh["access_token"]
