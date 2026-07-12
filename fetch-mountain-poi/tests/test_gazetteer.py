import json

from conftest import run_stage


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def test_gazetteer_from_cached_response(data_dir):
    result = run_stage("gazetteer", data_dir)
    assert result.returncode == 0, result.stderr
    assert "cached" in result.stderr  # no network touched

    entries = {e["osm"]: e for e in load_jsonl(data_dir / "01_gazetteer" / "gazetteer.jsonl")}

    zugspitze = entries["node/1001"]
    assert zugspitze == {
        "name": "Zugspitze", "type": "peak",
        "lat": 47.4211, "lon": 10.9863, "ele": 2962.0, "osm": "node/1001",
    }

    # Way gets its `center` as representative point; tag map classifies the hut.
    knorr = entries["way/2001"]
    assert (knorr["type"], knorr["lat"], knorr["lon"]) == ("hut", 47.418, 11.025)

    # Relation center, glacier type.
    ferner = entries["relation/3001"]
    assert (ferner["type"], ferner["lat"], ferner["lon"]) == ("glacier", 47.413, 10.98)

    assert entries["node/1006"]["type"] == "settlement"

    # The nameless peak (node/1005) is skipped.
    assert "node/1005" not in entries
    assert len(entries) == 7
