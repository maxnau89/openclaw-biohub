"""BiometricAdapter — base interface for wearable-data adapters.

Each adapter ingests data from a specific provider (WHOOP, Oura, Fitbit,
Apple Health, Garmin, …) into its own raw SQLite database, then rolls
daily aggregates into the source-agnostic `daily_metrics` table in
`health.db`.

The dashboard, the agent persona, and the analytics tier read from
`daily_metrics` — they are source-agnostic. Adapters are the only code
that knows about a specific provider's API or file format.
"""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Put pipeline/ on sys.path so we can import paths.py when adapters
# are loaded standalone (e.g. from a cron-launched script).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paths import BIOHUB_HOME

Stability = Literal["stable", "beta", "experimental"]


@dataclass
class SyncResult:
    """Summary of a single sync run."""
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    error: str | None = None

    def __str__(self) -> str:
        parts: list[str] = []
        if self.rows_inserted:
            parts.append(f"{self.rows_inserted} inserted")
        if self.rows_updated:
            parts.append(f"{self.rows_updated} updated")
        if self.rows_skipped:
            parts.append(f"{self.rows_skipped} skipped")
        if self.error:
            parts.append(f"ERROR: {self.error}")
        return ", ".join(parts) or "no changes"


class BiometricAdapter(ABC):
    """Base class for biohub adapters.

    Subclasses declare their identity via class attributes and implement
    the four lifecycle methods (`setup_instructions`, `configure_interactive`,
    `sync`, `rollup_to_health_db`).
    """

    #: Machine slug, also used as the secrets filename and CLI subcommand
    #: target. e.g. "whoop", "oura", "fitbit", "apple-health", "garmin".
    slug: str = ""

    #: Human-readable name shown in CLI / dashboard.
    display_name: str = ""

    #: Filename of this adapter's raw SQLite DB, under
    #: `$OPENCLAW_BIOHUB_HOME/data/`. e.g. "whoop_raw.db".
    raw_db_name: str = ""

    #: Stability tier — surfaced to users so they can self-select risk.
    #: "experimental" adapters print a warning on connect/sync.
    stability: Stability = "experimental"

    #: Whether `configure_interactive()` runs an OAuth flow.
    requires_oauth: bool = False

    def __init__(self) -> None:
        for attr in ("slug", "display_name", "raw_db_name"):
            if not getattr(self, attr):
                raise TypeError(
                    f"{type(self).__name__} must set class attribute {attr!r}"
                )

    @property
    def raw_db_path(self) -> Path:
        """Filesystem path to this adapter's raw SQLite DB."""
        return BIOHUB_HOME / "data" / self.raw_db_name

    @property
    def secrets_path(self) -> Path:
        """Path to this adapter's credentials JSON file."""
        return BIOHUB_HOME / "secrets" / f"{self.slug}.json"

    @abstractmethod
    def setup_instructions(self) -> str:
        """Return markdown shown by `biohub connect <slug>` before any prompts.

        Should cover:
        - what this adapter pulls (in plain language),
        - where the user gets credentials (with a direct URL to the
          provider's developer portal),
        - device-specific caveats (e.g. rate limits, partnership-gated APIs).
        """

    @abstractmethod
    def configure_interactive(self) -> None:
        """Prompt the user for keys/codes, save to `secrets_path` (mode 0600).

        Called by `biohub connect <slug>` after `setup_instructions`.
        Must be idempotent: re-running overwrites stale credentials.
        """

    @abstractmethod
    def sync(self, since: str | None = None, limit: int | None = None) -> SyncResult:
        """Fetch new data from the provider, write rows into `raw_db_path`.

        - `since`: ISO date string. `None` means "all available history".
        - `limit`: max records per resource. Used by `--dry-run` style
          sanity checks during onboarding.
        """

    @abstractmethod
    def rollup_to_health_db(self) -> int:
        """Project rows from `raw_db_path` into the `daily_metrics` table
        in `health.db`.

        Implementations must `INSERT OR REPLACE` on the composite primary
        key `(source, date)`. Returns the number of rows upserted.
        """
