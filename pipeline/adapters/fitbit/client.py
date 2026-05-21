"""Thin Fitbit Web API client.

Uses `_oauth_helpers.ensure_fresh_access_token` so individual sync
methods don't think about token state. Honours 429 rate-limit responses
with a single retry-after-wait (Fitbit returns Retry-After in seconds).

API base: https://api.fitbit.com
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

from .._oauth_helpers import ensure_fresh_access_token

API_BASE = "https://api.fitbit.com"

TOKEN_URL = f"{API_BASE}/oauth2/token"
AUTHORIZE_URL = "https://www.fitbit.com/oauth2/authorize"

# Default scopes — broad enough for everything we sync.
DEFAULT_SCOPES = [
    "activity", "heartrate", "sleep", "weight",
    "profile", "respiratory_rate", "oxygen_saturation", "temperature",
]


class FitbitRateLimitError(RuntimeError):
    """Raised when Fitbit returns 429 and Retry-After exceeds our budget."""


class FitbitClient:
    """Fitbit Web API wrapper.

    Construct with the path to the credentials file and the app's
    client_id / client_secret. Each call to `get(path)` will refresh
    the access token first if needed.
    """

    def __init__(
        self,
        creds_path: Path,
        client_id: str,
        client_secret: str,
        *,
        retry_on_429: bool = True,
        max_retry_wait: int = 60,
        timeout: int = 15,
    ) -> None:
        self.creds_path = creds_path
        self.client_id = client_id
        self.client_secret = client_secret
        self.retry_on_429 = retry_on_429
        self.max_retry_wait = max_retry_wait
        self.timeout = timeout

    def _access_token(self) -> str:
        return ensure_fresh_access_token(
            self.creds_path, TOKEN_URL, self.client_id, self.client_secret,
            use_basic_auth=True,
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET `path` (relative to api.fitbit.com). Returns the parsed JSON
        body, or raises. Handles one 429 retry if `retry_on_429`."""
        url = f"{API_BASE}{path}"
        for attempt in (0, 1):
            token = self._access_token()
            resp = requests.get(
                url, headers={"Authorization": f"Bearer {token}"},
                params=params, timeout=self.timeout,
            )
            if resp.status_code == 429 and attempt == 0 and self.retry_on_429:
                wait = int(resp.headers.get("Retry-After", "60"))
                if wait > self.max_retry_wait:
                    raise FitbitRateLimitError(
                        f"Rate-limited; Retry-After={wait}s exceeds budget {self.max_retry_wait}s"
                    )
                time.sleep(wait)
                continue
            if not resp.ok:
                raise RuntimeError(
                    f"Fitbit API {resp.status_code} {resp.reason}: {resp.text[:300]} "
                    f"(GET {path})"
                )
            return resp.json()
        # Should be unreachable
        raise RuntimeError(f"Fitbit GET {path} exhausted retries")
