"""Tests for the Health Auto Export CSV parser and the push receiver's
token auth + payload landing.

The receiver reuses the Apple Health adapter's sync() for parsing, so these
tests focus on: (1) the new CSV parser, (2) token generation/persistence,
(3) end-to-end HTTP auth + file landing against a live localhost server.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

from adapters.apple_health import receiver as rcv  # noqa: E402
from adapters.apple_health.sync import parse_health_export_csv  # noqa: E402

_CSV = (
    "Date,Heart Rate [count/min],Step Count [count]\n"
    "2026-07-01 08:00:00,62,1200\n"
    "2026-07-01 09:00:00,71,3400\n"
)


def test_csv_parser_extracts_metrics_and_units(tmp_path):
    fp = tmp_path / "hae.csv"
    fp.write_text(_CSV)
    metrics, sleeps, workouts = parse_health_export_csv(fp)
    assert sleeps == [] and workouts == []
    names = {m["metric_name"] for m in metrics}
    # normalize_metric_name maps "Heart Rate"→heart_rate, "Step Count"→step_count
    assert "heart_rate" in names
    hr = next(m for m in metrics if m["metric_name"] == "heart_rate")
    assert hr["unit"] == "count/min"
    assert hr["value"] == 62.0
    assert len(metrics) == 4        # 2 metrics × 2 rows


def test_csv_parser_skips_blank_and_nonnumeric(tmp_path):
    fp = tmp_path / "hae.csv"
    fp.write_text("Date,VO2 Max [ml/kg/min]\n2026-07-01,\n2026-07-02,n/a\n2026-07-03,48.2\n")
    metrics, _, _ = parse_health_export_csv(fp)
    assert len(metrics) == 1
    assert metrics[0]["value"] == 48.2


def _make_adapter(tmp_path):
    """An AppleHealthAdapter whose secrets + raw DB live under tmp_path."""
    from adapters.apple_health.sync import AppleHealthAdapter
    a = AppleHealthAdapter()
    watch = tmp_path / "watch"
    watch.mkdir()
    secrets_path = tmp_path / "apple-health.json"
    secrets_path.write_text(json.dumps({"watch_dir": str(watch)}))
    # Redirect the adapter's paths at tmp_path.
    type(a).secrets_path = property(lambda self: secrets_path)
    type(a).raw_db_path = property(lambda self: tmp_path / "apple_health_raw.db")
    return a, watch


def test_ensure_receiver_token_persists(tmp_path):
    a, _ = _make_adapter(tmp_path)
    t1 = rcv.ensure_receiver_token(a)
    t2 = rcv.ensure_receiver_token(a)
    assert t1 and t1 == t2                      # stable across calls
    saved = json.loads((tmp_path / "apple-health.json").read_text())
    assert saved["receiver_token"] == t1


def test_ensure_token_requires_configured_adapter(tmp_path):
    from adapters.apple_health.sync import AppleHealthAdapter
    a = AppleHealthAdapter()
    empty = tmp_path / "empty.json"
    type(a).secrets_path = property(lambda self: empty)
    with pytest.raises(SystemExit):
        rcv.ensure_receiver_token(a)


@pytest.fixture
def live_server(tmp_path):
    a, watch = _make_adapter(tmp_path)
    token = rcv.ensure_receiver_token(a)
    handler = rcv._make_handler(a, token, watch)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield f"http://127.0.0.1:{port}", token, watch
    server.shutdown()


def test_health_probe_needs_no_auth(live_server):
    base, _, _ = live_server
    with urllib.request.urlopen(f"{base}/health", timeout=5) as r:
        assert r.status == 200
        assert json.loads(r.read())["status"] == "ok"


def test_post_without_token_is_401(live_server):
    base, _, _ = live_server
    req = urllib.request.Request(f"{base}/", data=b'{"data":{}}',
                                 headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=5)
    assert ei.value.code == 401


def test_post_with_token_lands_file_and_ingests(live_server):
    base, token, watch = live_server
    payload = json.dumps({"data": {"metrics": [
        {"name": "heart_rate", "units": "count/min",
         "data": [{"date": "2026-07-01 08:00:00", "qty": 60}]}
    ]}}).encode()
    req = urllib.request.Request(
        f"{base}/", data=payload, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.loads(r.read())
    assert r.status == 200
    assert body["status"] == "ingested"
    # A file was written into the watch dir.
    assert any(p.suffix == ".json" for p in watch.iterdir())
