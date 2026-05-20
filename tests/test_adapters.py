"""Tests for the BiometricAdapter ABC and the WHOOP reference adapter."""
import sqlite3

import pytest

from adapters.base import BiometricAdapter, SyncResult
from adapters.whoop.sync import WhoopAdapter


def test_abstract_adapter_cannot_instantiate():
    with pytest.raises(TypeError):
        BiometricAdapter()  # type: ignore[abstract]


def test_subclass_missing_class_attrs_raises():
    class Bad(BiometricAdapter):
        def setup_instructions(self) -> str: return ""
        def configure_interactive(self) -> None: pass
        def sync(self, since=None, limit=None) -> SyncResult: return SyncResult()
        def rollup_to_health_db(self) -> int: return 0
    with pytest.raises(TypeError, match="slug"):
        Bad()


def test_whoop_adapter_identity():
    a = WhoopAdapter()
    assert a.slug == "whoop"
    assert a.display_name == "WHOOP"
    assert a.raw_db_name == "whoop_raw.db"
    assert a.stability == "stable"
    assert a.requires_oauth is True


def test_whoop_adapter_paths_derive_from_home(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(tmp_path))
    # paths.py reads env at import time, so the existing module's BIOHUB_HOME
    # is /opt/openclaw-biohub. Force reload to pick up the env override.
    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import adapters.base as base_mod
    importlib.reload(base_mod)
    # reload whoop.sync so its imports refer to the reloaded modules
    import adapters.whoop.sync as whoop_sync_mod
    importlib.reload(whoop_sync_mod)

    a = whoop_sync_mod.WhoopAdapter()
    assert a.raw_db_path == tmp_path / "data" / "whoop_raw.db"
    assert a.secrets_path == tmp_path / "secrets" / "whoop.json"


def test_whoop_setup_instructions_mentions_dev_portal():
    txt = WhoopAdapter().setup_instructions()
    assert "developer.whoop.com" in txt
    assert "client_id" in txt
    assert "redirect" in txt.lower()


def test_whoop_rollup_writes_daily_metrics_with_source(openclaw_home):
    """After seed.py runs, daily_metrics should be populated with source='whoop'."""
    health_db = openclaw_home / "data" / "health.db"
    with sqlite3.connect(health_db) as conn:
        rows = conn.execute(
            "SELECT source, date, recovery_score FROM daily_metrics LIMIT 5"
        ).fetchall()
    assert rows, "no rows in daily_metrics"
    for source, date, recovery in rows:
        assert source == "whoop"
        assert date  # non-empty
        assert recovery is not None


def test_sync_result_str_summary():
    assert str(SyncResult(rows_inserted=10, rows_updated=2)) == "10 inserted, 2 updated"
    assert str(SyncResult()) == "no changes"
    assert "ERROR" in str(SyncResult(error="boom"))
