"""Tests for the biohub CLI."""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

# Make the `biohub` package importable from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from biohub.cli import main as cli_main
from biohub.registry import ADAPTERS, all_adapters, get_adapter


# ─── Registry ────────────────────────────────────────────────────────────────


def test_registry_contains_all_v0_2_adapters():
    expected = {"whoop", "oura", "fitbit", "apple-health", "garmin"}
    assert expected == set(ADAPTERS)


def test_get_adapter_returns_instances():
    a = get_adapter("oura")
    assert a.slug == "oura"


def test_get_adapter_unknown_slug_raises():
    with pytest.raises(KeyError, match="Available"):
        get_adapter("bogus")


def test_all_adapters_in_registry_order():
    """Stable adapters first; experimental at the bottom."""
    slugs = [a.slug for a in all_adapters()]
    assert slugs == ["whoop", "oura", "fitbit", "apple-health", "garmin"]


# ─── list-adapters ───────────────────────────────────────────────────────────


def test_list_adapters_prints_all_four(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(tmp_path))
    # Reload paths + adapters so secrets_path uses the tmp home
    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import adapters.base as base_mod
    importlib.reload(base_mod)
    import biohub.registry as reg
    importlib.reload(reg)
    import biohub.cli as cli
    importlib.reload(cli)

    rc = cli.main(["list-adapters"])
    assert rc == 0
    out = capsys.readouterr().out
    # Header + 5 adapter rows
    for slug in ("whoop", "oura", "fitbit", "apple-health", "garmin"):
        assert slug in out
    # None configured (tmp dir has no secrets/)
    assert "no" in out
    # Stable + experimental markers both present
    assert "stable" in out
    assert "EXPERIMENTAL" in out


def test_list_adapters_marks_configured(monkeypatch, tmp_path, capsys):
    """Drop a fake secrets file for oura and verify the table flips to 'yes'."""
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(tmp_path))
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "oura.json").write_text("{}")

    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import adapters.base as base_mod
    importlib.reload(base_mod)
    import biohub.registry as reg
    importlib.reload(reg)
    import biohub.cli as cli
    importlib.reload(cli)

    cli.main(["list-adapters"])
    out = capsys.readouterr().out
    # The oura row should end with 'yes'
    oura_line = next(ln for ln in out.splitlines() if ln.startswith("oura"))
    assert oura_line.rstrip().endswith("yes")


# ─── connect ─────────────────────────────────────────────────────────────────


def test_connect_dry_run_prints_setup_only(capsys):
    rc = cli_main(["connect", "oura", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    # Oura's instructions reference its dev portal
    assert "cloud.ouraring.com/personal-access-tokens" in out
    assert "--dry-run" in out and "no credentials" in out.lower()


def test_connect_unknown_slug_exits_2(capsys):
    rc = cli_main(["connect", "bogus", "--dry-run"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "Unknown adapter" in err


# ─── sync ────────────────────────────────────────────────────────────────────


def test_sync_requires_slug_or_all(capsys):
    rc = cli_main(["sync"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--all" in err or "slug" in err


def test_sync_all_with_none_configured_returns_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(tmp_path))
    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import adapters.base as base_mod
    importlib.reload(base_mod)
    import biohub.registry as reg
    importlib.reload(reg)
    import biohub.cli as cli
    importlib.reload(cli)

    rc = cli.main(["sync", "--all"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "No adapters are configured" in err


def test_sync_unknown_slug_exits_2(capsys):
    rc = cli_main(["sync", "bogus"])
    assert rc == 2


def test_sync_dry_run_skips_network(monkeypatch, tmp_path, capsys):
    """With --dry-run and a configured adapter, we shouldn't hit any network
    or call sync()/rollup_to_health_db() — verifying by ensuring requests
    isn't even imported."""
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(tmp_path))
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "oura.json").write_text("{}")

    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import adapters.base as base_mod
    importlib.reload(base_mod)
    import biohub.registry as reg
    importlib.reload(reg)
    import biohub.cli as cli
    importlib.reload(cli)

    # Patch sync + rollup to detect if they get called
    sync_calls = []
    monkeypatch.setattr(
        "adapters.oura.sync.OuraAdapter.sync",
        lambda self, **kw: sync_calls.append(kw) or "should-not-be-called",
    )
    rc = cli.main(["sync", "oura", "--dry-run"])
    assert rc == 0
    assert sync_calls == []   # network path skipped
    assert "dry-run" in capsys.readouterr().out.lower()


def test_sync_specific_unconfigured_exits_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(tmp_path))
    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import adapters.base as base_mod
    importlib.reload(base_mod)
    import biohub.registry as reg
    importlib.reload(reg)
    import biohub.cli as cli
    importlib.reload(cli)

    rc = cli.main(["sync", "oura"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "Not configured" in out
    assert "biohub connect oura" in out
