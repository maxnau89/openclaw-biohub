"""Tests for pipeline/adapters/_oauth_helpers.py.

HTTP is mocked via a tiny session double — no `requests-mock` dependency.
"""
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from adapters._oauth_helpers import (
    build_authorize_url,
    ensure_fresh_access_token,
    exchange_code_for_tokens,
    is_expired,
    load_credentials,
    refresh_access_token,
    save_credentials,
)


# ─── Credentials I/O ─────────────────────────────────────────────────────────


def test_save_and_load_credentials_roundtrip(tmp_path):
    p = tmp_path / "creds.json"
    save_credentials(p, {"access_token": "abc", "refresh_token": "rrr", "expires_in": 3600})
    loaded = load_credentials(p)
    assert loaded["access_token"] == "abc"
    assert loaded["refresh_token"] == "rrr"
    assert loaded["expires_in"] == 3600
    assert "obtained_at" in loaded
    # File should be mode 0600 on Unix; check best-effort
    mode = p.stat().st_mode & 0o777
    assert mode in (0o600, 0o644)  # 0o644 on filesystems that ignore chmod


def test_save_credentials_merge_preserves_refresh_token(tmp_path):
    """Token-refresh responses often omit the refresh_token; merging must
    keep the existing one rather than dropping it."""
    p = tmp_path / "creds.json"
    save_credentials(p, {"access_token": "v1", "refresh_token": "RT", "expires_in": 3600})
    # Simulate a refresh response that omits refresh_token
    save_credentials(p, {"access_token": "v2", "expires_in": 3600})
    loaded = load_credentials(p)
    assert loaded["access_token"] == "v2"
    assert loaded["refresh_token"] == "RT"


def test_load_credentials_missing_file_returns_empty(tmp_path):
    assert load_credentials(tmp_path / "missing.json") == {}


def test_load_credentials_malformed_returns_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json")
    assert load_credentials(p) == {}


# ─── Expiry check ────────────────────────────────────────────────────────────


def test_is_expired_no_creds():
    assert is_expired({}) is True


def test_is_expired_no_expiry_info():
    assert is_expired({"access_token": "abc"}) is True


def test_is_expired_within_threshold():
    creds = {"access_token": "abc", "obtained_at": int(time.time()) - 3500, "expires_in": 3600}
    # ~100s remaining, below default 300s threshold
    assert is_expired(creds) is True


def test_is_expired_fresh_token():
    creds = {"access_token": "abc", "obtained_at": int(time.time()), "expires_in": 3600}
    assert is_expired(creds) is False


def test_is_expired_custom_threshold():
    creds = {"access_token": "abc", "obtained_at": int(time.time()) - 2500, "expires_in": 3600}
    # 1100s remaining
    assert is_expired(creds, threshold_seconds=60) is False
    assert is_expired(creds, threshold_seconds=2000) is True


# ─── Authorize URL ───────────────────────────────────────────────────────────


def test_build_authorize_url_basic():
    url = build_authorize_url(
        "https://example.com/auth",
        client_id="cid",
        redirect_uri="http://localhost/cb",
        scopes="read:a read:b",
    )
    assert url.startswith("https://example.com/auth?")
    assert "client_id=cid" in url
    assert "response_type=code" in url
    assert "scope=read%3Aa+read%3Ab" in url


def test_build_authorize_url_scopes_as_list():
    url = build_authorize_url(
        "https://example.com/auth", "cid", "http://localhost/cb",
        scopes=["sleep", "heart"],
    )
    assert "scope=sleep+heart" in url


def test_build_authorize_url_with_state_and_extra():
    url = build_authorize_url(
        "https://example.com/auth", "cid", "http://localhost/cb",
        scopes="x", state="nonce", extra={"prompt": "consent"},
    )
    assert "state=nonce" in url
    assert "prompt=consent" in url


# ─── Token endpoint helpers (HTTP mocked) ────────────────────────────────────


@pytest.fixture
def mock_post(monkeypatch):
    """Patch requests.post in _oauth_helpers; capture call args + return
    a configurable JSON response."""
    captured: list[dict] = []

    def make_response(payload: dict, status: int = 200):
        resp = MagicMock()
        resp.ok = 200 <= status < 300
        resp.status_code = status
        resp.reason = "OK" if resp.ok else "Bad Request"
        resp.text = json.dumps(payload)
        resp.json.return_value = payload
        return resp

    state: dict = {"response_payload": {"access_token": "new", "expires_in": 3600}, "status": 200}

    def fake_post(url, data=None, headers=None, auth=None, timeout=None):
        captured.append({"url": url, "data": data, "headers": headers, "auth": auth})
        return make_response(state["response_payload"], state["status"])

    monkeypatch.setattr("adapters._oauth_helpers.requests.post", fake_post)
    return {"captured": captured, "state": state}


def test_exchange_code_for_tokens_form_credentials(mock_post):
    result = exchange_code_for_tokens(
        "https://example.com/token", "cid", "csecret", "the_code", "http://localhost/cb",
    )
    call = mock_post["captured"][0]
    assert call["data"]["grant_type"] == "authorization_code"
    assert call["data"]["code"] == "the_code"
    assert call["data"]["client_id"] == "cid"
    assert call["data"]["client_secret"] == "csecret"
    assert call["auth"] is None
    assert result["access_token"] == "new"


def test_exchange_code_for_tokens_basic_auth(mock_post):
    """Fitbit and some others require client credentials via HTTP Basic auth."""
    exchange_code_for_tokens(
        "https://example.com/token", "cid", "csecret", "code", "http://localhost/cb",
        use_basic_auth=True,
    )
    call = mock_post["captured"][0]
    assert call["data"]["grant_type"] == "authorization_code"
    assert "client_id" not in call["data"]   # not in form when using basic auth
    assert "client_secret" not in call["data"]
    assert call["auth"] == ("cid", "csecret")


def test_refresh_access_token_form_creds(mock_post):
    refresh_access_token(
        "https://example.com/token", "cid", "csecret", "rt_value",
    )
    call = mock_post["captured"][0]
    assert call["data"]["grant_type"] == "refresh_token"
    assert call["data"]["refresh_token"] == "rt_value"
    assert call["data"]["client_id"] == "cid"


def test_refresh_access_token_propagates_errors(mock_post):
    mock_post["state"]["status"] = 401
    mock_post["state"]["response_payload"] = {"error": "invalid_grant"}
    with pytest.raises(RuntimeError, match="401"):
        refresh_access_token("https://example.com/token", "c", "s", "rt")


# ─── Top-level convenience: ensure_fresh_access_token ───────────────────────


def test_ensure_fresh_returns_cached_token_when_valid(tmp_path, mock_post):
    p = tmp_path / "creds.json"
    save_credentials(p, {"access_token": "still-fresh", "refresh_token": "rt", "expires_in": 3600})
    token = ensure_fresh_access_token(p, "https://example.com/token", "cid", "csecret")
    assert token == "still-fresh"
    assert mock_post["captured"] == []   # no HTTP call


def test_ensure_fresh_refreshes_when_expired(tmp_path, mock_post):
    p = tmp_path / "creds.json"
    save_credentials(p, {"access_token": "stale", "refresh_token": "RT-1", "expires_in": 60})
    # Make sure it's stale: rewrite obtained_at far in the past
    cur = json.loads(p.read_text())
    cur["obtained_at"] = int(time.time()) - 1000
    p.write_text(json.dumps(cur))

    mock_post["state"]["response_payload"] = {
        "access_token": "fresh", "refresh_token": "RT-2", "expires_in": 3600,
    }
    token = ensure_fresh_access_token(p, "https://example.com/token", "cid", "csecret")
    assert token == "fresh"
    # Saved creds keep the new refresh_token
    saved = load_credentials(p)
    assert saved["refresh_token"] == "RT-2"


def test_ensure_fresh_raises_without_refresh_token(tmp_path, mock_post):
    p = tmp_path / "creds.json"
    # No refresh_token in creds, and expired
    save_credentials(p, {"access_token": "stale", "expires_in": 60})
    with pytest.raises(RuntimeError, match="No refresh_token"):
        ensure_fresh_access_token(p, "https://example.com/token", "cid", "csecret")
