"""Tests for the biohub CLI."""
from __future__ import annotations

import io
import json
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


# ─── body_comp math ──────────────────────────────────────────────────────────


def test_compute_bf_jp7_male_known_values():
    """Hand-checked Jackson-Pollock 7-site + Siri sanity case (male)."""
    from biohub.body_comp import compute_bf_jp7
    sites = {
        "chest": 8, "abdominal": 12, "thigh": 14, "tricep": 7,
        "subscapular": 12, "suprailiac": 12, "midaxillary": 8,
    }
    bf = compute_bf_jp7(sites, sex="m", age=30)
    # Lean-ish male in that range should be 10–14 %
    assert 9.0 < bf < 16.0


def test_compute_bf_jp7_female_higher_than_male():
    """Same skinfolds → female %BF should exceed male %BF (Jackson-Pollock)."""
    from biohub.body_comp import compute_bf_jp7
    sites = {
        "chest": 12, "abdominal": 18, "thigh": 20, "tricep": 14,
        "subscapular": 16, "suprailiac": 18, "midaxillary": 12,
    }
    bf_m = compute_bf_jp7(sites, sex="m", age=35)
    bf_f = compute_bf_jp7(sites, sex="f", age=35)
    assert bf_f > bf_m


def test_compute_bf_jp7_missing_site_raises():
    from biohub.body_comp import compute_bf_jp7
    with pytest.raises(ValueError, match="missing site"):
        compute_bf_jp7({"chest": 8}, sex="m", age=30)


def test_derive_mass_splits_weight():
    from biohub.body_comp import derive_mass
    lean, fat = derive_mass(80.0, 20.0)
    assert fat == 16.0
    assert lean == 64.0
    assert round(lean + fat, 2) == 80.0


# ─── log-measurement ─────────────────────────────────────────────────────────


def test_log_measurement_dry_run_with_skinfolds(capsys):
    """Dry-run path: computes body fat from skinfolds, prints row, no DB write."""
    rc = cli_main([
        "log-measurement",
        "--date", "2026-05-19",
        "--method", "jackson-pollock-7",
        "--weight", "82.0",
        "--chest", "8", "--abdominal", "12", "--thigh", "14",
        "--tricep", "7", "--subscapular", "12", "--suprailiac", "12",
        "--midaxillary", "8",
        "--sex", "m", "--age", "30",
        "--non-interactive", "--dry-run",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["action"] == "dry-run"
    row = payload["row"]
    assert row["date"] == "2026-05-19"
    assert row["method"] == "jackson-pollock-7"
    assert row["weight_kg"] == 82.0
    assert row["body_fat_pct"] is not None
    assert 8 < row["body_fat_pct"] < 18
    assert row["chest_mm"] == 8
    assert row["midaxillary_mm"] == 8


def test_log_measurement_with_explicit_body_fat(capsys):
    """If body_fat_pct is supplied directly, no skinfolds / sex / age needed."""
    rc = cli_main([
        "log-measurement",
        "--date", "2026-05-19",
        "--method", "scale",
        "--weight", "80.0",
        "--body-fat-pct", "15.0",
        "--non-interactive", "--dry-run",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    row = json.loads(out)["row"]
    assert row["body_fat_pct"] == 15.0
    assert row["lean_mass_kg"] == 68.0  # 80 * (1 - 0.15)
    assert row["fat_mass_kg"] == 12.0


# ─── log-phase ───────────────────────────────────────────────────────────────


def test_log_phase_start_dry_run(capsys):
    rc = cli_main([
        "log-phase", "start", "diet", "Spring Cut",
        "--start", "2026-05-01", "--color", "#fbbf24",
        "--dry-run",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["action"] == "dry-run"
    assert payload["row"]["name"] == "Spring Cut"
    assert payload["row"]["category"] == "diet"
    assert payload["row"]["start_date"] == "2026-05-01"
    assert payload["row"]["color"] == "#fbbf24"
    assert payload["row"]["end_date"] is None


def test_log_phase_start_default_color_for_category(capsys):
    """Without --color, training picks emerald."""
    rc = cli_main([
        "log-phase", "start", "training", "Strength Block",
        "--dry-run",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    # default_color('training') == '#34d399'
    assert payload["row"]["color"] == "#34d399"


def test_log_phase_full_cycle_against_seed_db(openclaw_home, monkeypatch, capsys):
    """end-to-end: start → list → end → list against a seeded DB."""
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(openclaw_home))

    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import biohub.body_comp as bc
    importlib.reload(bc)
    import biohub.cli as cli
    importlib.reload(cli)

    # 1. start a phase
    rc = cli.main([
        "log-phase", "start", "supplement", "Test Creatine",
        "--start", "2026-05-10", "--color", "#a78bfa",
    ])
    assert rc == 0
    capsys.readouterr()  # drain

    # 2. list — should include the new phase
    rc = cli.main(["log-phase", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Test Creatine" in out
    assert "supplement" in out
    assert "(open)" in out

    # 3. end the phase
    rc = cli.main(["log-phase", "end", "Test Creatine", "--end", "2026-05-19"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "closed"
    assert payload["row"]["end_date"] == "2026-05-19"

    # 4. list --open-only — should no longer include the phase
    rc = cli.main(["log-phase", "list", "--open-only"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Test Creatine" not in out

    # 5. ending an already-closed phase returns 1 with no-match
    rc = cli.main(["log-phase", "end", "Test Creatine"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no open phase" in err


def test_log_measurement_persists_to_seed_db(openclaw_home, monkeypatch, capsys):
    monkeypatch.setenv("OPENCLAW_BIOHUB_HOME", str(openclaw_home))

    import importlib
    import paths as paths_mod
    importlib.reload(paths_mod)
    import biohub.body_comp as bc
    importlib.reload(bc)
    import biohub.cli as cli
    importlib.reload(cli)

    rc = cli.main([
        "log-measurement",
        "--date", "2026-05-19",
        "--method", "scale",
        "--weight", "81.5",
        "--body-fat-pct", "16.0",
        "--non-interactive",
    ])
    assert rc == 0
    capsys.readouterr()

    # Verify row landed in body_composition
    import sqlite3
    conn = sqlite3.connect(paths_mod.HEALTH_DB)
    try:
        row = conn.execute(
            "SELECT method, weight_kg, body_fat_pct, lean_mass_kg, fat_mass_kg "
            "FROM body_composition WHERE date = ?",
            ("2026-05-19",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "scale"
    assert row[1] == 81.5
    assert row[2] == 16.0
    assert row[3] == round(81.5 * 0.84, 2)
    assert row[4] == round(81.5 * 0.16, 2)
