"""Thin subprocess coverage for the argparse entrypoints: `--guide` is
required, an unknown guide fails clearly, and a happy path runs end to end
against a throwaway fixture guide dir under the repo's guides/."""

import os
import shutil

import pytest

from conftest import FIXTURES, run_cli
from pipeline.config import REPO_ROOT


def test_missing_guide_arg_errors():
    result = run_cli("match")
    assert result.returncode != 0
    assert "guide" in result.stderr.lower()


def test_unknown_guide_errors():
    result = run_cli("match", "--guide", "no-such-guide")
    assert result.returncode != 0
    assert "no guide config" in result.stderr


@pytest.fixture
def fixture_guide():
    """A throwaway guide dir under the real guides/ tree so `--guide` resolves
    it. Data is gitignored; the config.yml lives under a temp-named dir removed
    on teardown, so nothing is left tracked."""
    guide_id = f"_pytest_cli_{os.getpid()}"
    guide_dir = REPO_ROOT / "guides" / guide_id
    fetch_data = guide_dir / "data" / "fetch-pois"
    routes_dir = guide_dir / "data" / "parse-routes" / "03_structured"
    (fetch_data / "01_gazetteer").mkdir(parents=True, exist_ok=True)
    routes_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        REPO_ROOT / "guides" / "wetterstein" / "config.yml", guide_dir / "config.yml"
    )
    shutil.copyfile(
        FIXTURES / "overpass_raw.json",
        fetch_data / "01_gazetteer" / "overpass_raw.json",
    )
    shutil.copyfile(FIXTURES / "routes.jsonl", routes_dir / "routes.jsonl")
    try:
        yield guide_id, fetch_data
    finally:
        shutil.rmtree(guide_dir, ignore_errors=True)


def test_happy_path_gazetteer_then_match(fixture_guide):
    guide_id, fetch_data = fixture_guide

    gaz = run_cli("gazetteer", "--guide", guide_id)
    assert gaz.returncode == 0, gaz.stderr
    assert (fetch_data / "01_gazetteer" / "gazetteer.jsonl").exists()

    match = run_cli("match", "--guide", guide_id)
    assert match.returncode == 0, match.stderr
    assert (fetch_data / "04_final" / "pois.geojson").exists()
    assert (fetch_data / "03_matched" / "funnel.json").exists()

    # The validation gate reads the matcher's artifacts and prints both tables.
    audit = run_cli("audit", "--guide", guide_id)
    assert audit.returncode == 0, audit.stderr
    assert "## Place → POI anchors" in audit.stdout
    assert "## Entry mentions → POI" in audit.stdout
    assert "without a match" in audit.stderr


def test_audit_unknown_guide_errors():
    result = run_cli("audit", "--guide", "no-such-guide")
    assert result.returncode != 0
    assert "no guide config" in result.stderr
