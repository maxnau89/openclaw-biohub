"""Smoke tests for pipeline/paths.py — env var resolution and overrides."""
import importlib
import os
from pathlib import Path


def _reload_paths():
    import paths
    return importlib.reload(paths)


def test_defaults_when_unset(monkeypatch):
    for k in ("OPENCLAW_BIOHUB_HOME", "HEALTH_DB_PATH", "WHOOP_DB_PATH",
              "OPENCLAW_BIOHUB_SECRETS_DIR", "OPENCLAW_BIOHUB_PIPELINE_DIR",
              "OPENCLAW_BIOHUB_LOG_DIR"):
        monkeypatch.delenv(k, raising=False)
    paths = _reload_paths()

    assert paths.BIOHUB_HOME == Path("/opt/openclaw-biohub")
    assert paths.HEALTH_DB == Path("/opt/openclaw-biohub/data/health.db")
    assert paths.WHOOP_DB == Path("/opt/openclaw-biohub/data/whoop_raw.db")
    assert paths.WHOOP_CREDS_FILE.name == "whoop_credentials.json"
    assert paths.WHOOP_SYNC_SCRIPT.parts[-3:] == ("adapters", "whoop", "sync.py")


def test_home_overrides_everything(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", "/var/opt/oh")
    for k in ("HEALTH_DB_PATH", "WHOOP_DB_PATH",
              "OPENCLAW_BIOHUB_SECRETS_DIR", "OPENCLAW_BIOHUB_PIPELINE_DIR",
              "OPENCLAW_BIOHUB_LOG_DIR"):
        monkeypatch.delenv(k, raising=False)
    paths = _reload_paths()

    assert paths.BIOHUB_HOME == Path("/var/opt/oh")
    assert paths.HEALTH_DB == Path("/var/opt/oh/data/health.db")
    assert paths.WHOOP_DB == Path("/var/opt/oh/data/whoop_raw.db")
    assert paths.SECRETS_DIR == Path("/var/opt/oh/secrets")
    assert paths.PIPELINE_DIR == Path("/var/opt/oh/pipeline")


def test_individual_path_overrides_take_precedence(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", "/var/opt/oh")
    monkeypatch.setenv("HEALTH_DB_PATH", "/custom/h.db")
    monkeypatch.setenv("WHOOP_DB_PATH", "/custom/w.db")
    paths = _reload_paths()

    assert paths.HEALTH_DB == Path("/custom/h.db")
    assert paths.WHOOP_DB == Path("/custom/w.db")
    # Other paths still derive from BIOHUB_HOME
    assert paths.SECRETS_DIR == Path("/var/opt/oh/secrets")
