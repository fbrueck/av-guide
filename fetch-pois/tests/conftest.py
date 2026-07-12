"""Tests exercise the pure step functions directly: a `cfg` fixture builds a
GuideConfig (the real `wetterstein` guide's values) whose data_root points at a
fresh tmp dir and whose routes index points at the fixture, so steps read and
write under tmp_path with no env vars and no subprocess. A couple of thin tests
shell out via `--guide` to cover the argparse entrypoints (see test_cli.py)."""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline.config import load_guide

PKG = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def cfg(tmp_path: Path):
    """The wetterstein GuideConfig with data_root redirected to a fresh tmp dir
    and the routes index to the test fixture. The canned Overpass response is
    pre-cached so the gazetteer step runs offline."""
    base = load_guide("wetterstein")
    c = dataclasses.replace(
        base, data_root=tmp_path, routes_jsonl=FIXTURES / "routes.jsonl"
    )
    c.gazetteer_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / "overpass_raw.json", c.overpass_raw)
    return c


def run_cli(module: str, *args: str) -> subprocess.CompletedProcess:
    """Run a pipeline entrypoint as a subprocess the way the orchestrator does."""
    return subprocess.run(
        [sys.executable, "-m", f"pipeline.{module}", *args],
        cwd=PKG,
        capture_output=True,
        text=True,
    )
