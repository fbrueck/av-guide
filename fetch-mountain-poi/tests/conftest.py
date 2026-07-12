"""Tests exercise the data-directory seam: stages run as subprocesses the way
the orchestrator runs them, pointed at a fixture data root via AV_POI_DATA."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def run_stage(module: str, data_dir: Path, routes: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ | {"AV_POI_DATA": str(data_dir)}
    if routes is not None:
        env["AV_POI_ROUTES"] = str(routes)
    return subprocess.run(
        [sys.executable, "-m", f"pipeline.{module}"],
        cwd=PKG,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Fixture data root with the canned Overpass response pre-cached."""
    gaz_dir = tmp_path / "01_gazetteer"
    gaz_dir.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "overpass_raw.json", gaz_dir / "overpass_raw.json")
    return tmp_path
