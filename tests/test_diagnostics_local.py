"""Real local preflight checks; no generated audio or aircraft data."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture(scope="module")
def local_probe(tmp_path_factory):
    root = tmp_path_factory.mktemp("preflight")
    target = root / "new" / "jobs"
    source = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ, PYTHONPATH=str(source))
    completed = subprocess.run(
        [sys.executable, "-m", "dopplergeist.cli", "doctor", "--json", "--jobs", str(target)],
        env=env, capture_output=True, text=True, timeout=75, check=False,
    )
    return completed, json.loads(completed.stdout), target


def test_preflight_reports_real_environment(local_probe):
    _, report, _ = local_probe
    names = {check["name"] for check in report["checks"]}
    assert {"python", "platform", "ffmpeg", "ffprobe", "web_assets", "job_storage"} <= names
    assert report["schema_version"] == 1
    assert all(c["status"] in {"ok", "warning", "error"} for c in report["checks"])


def test_preflight_exit_matches_errors(local_probe):
    completed, report, _ = local_probe
    errors = any(c["status"] == "error" for c in report["checks"])
    assert completed.returncode == (1 if errors else 0), completed.stderr
    assert (report["status"] == "error") == errors


def test_preflight_does_not_create_job_storage(local_probe):
    _, report, target = local_probe
    assert not target.parent.exists()
    assets = next(c for c in report["checks"] if c["name"] == "web_assets")
    assert assets["status"] == "ok"
