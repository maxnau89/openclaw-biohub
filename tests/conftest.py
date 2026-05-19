"""Shared pytest fixtures.

Provides a seeded `openclaw_home` directory containing fresh `health.db`
and `whoop_raw.db` populated by `fixtures/seed.py`. The directory is
created once per session and torn down at the end.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_SCRIPT = REPO_ROOT / "fixtures" / "seed.py"

# Put pipeline on sys.path at collection time so test modules can import
# `paths`, `whoop_pattern_engine`, etc. directly.
_PIPELINE_DIR = str(REPO_ROOT / "pipeline")
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)


@pytest.fixture(scope="session")
def openclaw_home():
    home = Path(tempfile.mkdtemp(prefix="openclaw-biohub-test-"))
    env = {**os.environ, "OPENCLAW_BIOHUB_HOME": str(home)}
    result = subprocess.run(
        [sys.executable, str(SEED_SCRIPT)],
        env=env, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        shutil.rmtree(home, ignore_errors=True)
        raise RuntimeError(
            f"seed.py failed (exit {result.returncode}):\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    yield home
    shutil.rmtree(home, ignore_errors=True)


