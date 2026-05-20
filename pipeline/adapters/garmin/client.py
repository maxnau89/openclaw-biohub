"""Thin wrapper around the `garth` library.

`garth` is imported lazily so users who don't use Garmin don't need it
installed. The wrapper exists so tests can monkeypatch a single
`GarminClient.connectapi` method without monkeypatching `garth`
internals across versions.

EXPERIMENTAL: Garmin Connect Web is not a public API. This whole layer
breaks if Garmin changes their internal endpoints. Treat sync failures
as expected during major Garmin UI/site updates.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _require_garth():
    try:
        import garth  # type: ignore[import-not-found]
        return garth
    except ImportError as e:
        raise ImportError(
            "The Garmin adapter requires the `garth` package. "
            "Install with: pip install garth"
        ) from e


class GarminClient:
    """Thin facade. All Garmin Connect endpoints flow through `connectapi()`."""

    def __init__(self, tokens_dir: Path) -> None:
        self.tokens_dir = tokens_dir

    def resume(self) -> None:
        """Reload Garmin Connect tokens from disk (no network)."""
        garth = _require_garth()
        garth.resume(str(self.tokens_dir))

    def login(self, email: str, password: str) -> None:
        """Authenticate with Garmin Connect; persists tokens to tokens_dir."""
        garth = _require_garth()
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        garth.login(email, password)
        garth.save(str(self.tokens_dir))

    def connectapi(self, path: str, **params) -> Any:
        """Generic GET against Garmin Connect's internal JSON API.

        Examples:
            client.connectapi(f"/wellness-service/wellness/dailySleepData/{user}", date=d)
        """
        garth = _require_garth()
        return garth.client.connectapi(path, params=params)
