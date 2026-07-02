"""Adapter registry — single source of truth for which adapters exist.

Adapters are eagerly imported here so the CLI knows about all of them
without needing the user to declare them anywhere. Adding a new adapter
means: (1) write `pipeline/adapters/<slug>/sync.py` with a class that
subclasses `BiometricAdapter`, (2) add the import + class to this file.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Type

# Put pipeline/ on sys.path so the `adapters.*` imports below resolve.
_PIPELINE_DIR = Path(__file__).resolve().parent.parent / "pipeline"
if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

from adapters.apple_health.sync import AppleHealthAdapter
from adapters.base import BiometricAdapter
from adapters.fitbit.sync import FitbitAdapter
from adapters.garmin.sync import GarminAdapter
from adapters.libre.sync import LibreAdapter
from adapters.oura.sync import OuraAdapter
from adapters.whoop.sync import WhoopAdapter

# Order here determines display order in `biohub list-adapters`.
# Stable adapters first, experimental at the bottom.
_ADAPTER_CLASSES: list[Type[BiometricAdapter]] = [
    WhoopAdapter,
    OuraAdapter,
    FitbitAdapter,
    AppleHealthAdapter,
    GarminAdapter,
    LibreAdapter,
]

ADAPTERS: dict[str, Type[BiometricAdapter]] = {
    cls.slug: cls for cls in _ADAPTER_CLASSES
}


def get_adapter(slug: str) -> BiometricAdapter:
    """Return an instantiated adapter for `slug`. Raises KeyError if unknown."""
    if slug not in ADAPTERS:
        available = ", ".join(ADAPTERS)
        raise KeyError(f"Unknown adapter '{slug}'. Available: {available}")
    return ADAPTERS[slug]()


def all_adapters() -> list[BiometricAdapter]:
    """Return one instance per registered adapter, in display order."""
    return [cls() for cls in _ADAPTER_CLASSES]
