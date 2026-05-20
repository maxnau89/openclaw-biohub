"""Thin Oura API v2 HTTP client.

Pagination: Oura uses a `next_token` cursor. The client transparently
follows it and yields rows until exhausted.

Date filtering: most endpoints accept `start_date` / `end_date`
(inclusive ISO YYYY-MM-DD). For incremental sync, pass `start_date` =
last synced day.

Rate limits: Oura's official limit at the time of writing is 5000
requests / 5 minutes. We don't bother with rate limiting in the
client — typical syncs are dozens of requests, not thousands.
"""
from __future__ import annotations

from typing import Any, Iterator

import requests

BASE_URL = "https://api.ouraring.com/v2"


class OuraClient:
    def __init__(self, access_token: str, timeout: int = 15) -> None:
        if not access_token:
            raise ValueError("Oura access_token is required")
        self.token = access_token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """Yield each `data[]` row from an Oura usercollection endpoint, following
        `next_token` cursors until exhausted."""
        params = dict(params or {})
        url = f"{BASE_URL}/usercollection/{path.lstrip('/')}"
        while True:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            for row in payload.get("data", []):
                yield row
            next_token = payload.get("next_token")
            if not next_token:
                return
            params = {"next_token": next_token}

    def get_one(self, path: str) -> dict[str, Any]:
        """Convenience for singular endpoints (e.g. /personal_info)."""
        url = f"{BASE_URL}/usercollection/{path.lstrip('/')}"
        resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()
