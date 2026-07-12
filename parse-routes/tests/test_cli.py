"""Thin subprocess coverage for the argparse entrypoints: `--guide` is
required, an unknown guide fails clearly, and a happy path (merge) runs
against a throwaway fixture guide dir under the repo's guides/."""
import json
import os
import shutil

import pytest

from conftest import run_cli
from pipeline.config import REPO_ROOT


def test_missing_guide_arg_errors():
    result = run_cli("merge")
    assert result.returncode != 0
    assert "guide" in result.stderr.lower()


def test_unknown_guide_errors():
    result = run_cli("merge", "--guide", "no-such-guide")
    assert result.returncode != 0
    assert "no guide config" in result.stderr


@pytest.fixture
def fixture_guide():
    """A throwaway guide dir under the real guides/ tree so `--guide` resolves
    it. Data is gitignored; the config.yml lives under a temp-named dir removed
    on teardown."""
    guide_id = f"_pytest_cli_{os.getpid()}"
    guide_dir = REPO_ROOT / "guides" / guide_id
    parts = guide_dir / "data" / "parse-routes" / "03_structured" / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO_ROOT / "guides" / "wetterstein" / "config.yml", guide_dir / "config.yml")
    (parts / "page_0051.json").write_text(
        json.dumps({"routes": [{"name": "R", "description": "R", "summary": None}]}),
        encoding="utf-8",
    )
    try:
        yield guide_id, guide_dir / "data" / "parse-routes" / "03_structured"
    finally:
        shutil.rmtree(guide_dir, ignore_errors=True)


def test_happy_path_merge(fixture_guide):
    guide_id, struct = fixture_guide

    result = run_cli("merge", "--guide", guide_id)
    assert result.returncode == 0, result.stderr
    routes = [json.loads(l) for l in (struct / "routes.jsonl").read_text().splitlines()]
    assert [r["route_id"] for r in routes] == ["p0051_01"]
