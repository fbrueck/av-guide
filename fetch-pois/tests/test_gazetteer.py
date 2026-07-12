import json

from pipeline import gazetteer


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def test_gazetteer_from_cached_response(cfg, capsys):
    gazetteer.build_gazetteer(cfg, refresh=False)
    assert "using cached response" in capsys.readouterr().err  # no network touched

    entries = {e["osm"]: e for e in load_jsonl(cfg.gazetteer)}

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

    # Named paths and water features (#11 classes).
    assert entries["way/2004"]["type"] == "water"          # Blaue Gumpe (lake)
    assert entries["way/2006"]["type"] == "station"        # Kreuzeckbahn Bergstation

    # Linear features are deduped to one entry per name: the two Stangensteig
    # path segments collapse (lowest way id wins) …
    stangensteig = [e for e in entries.values() if e["name"] == "Stangensteig"]
    assert [e["osm"] for e in stangensteig] == ["way/2002"]
    assert stangensteig[0]["type"] == "path"
    # … and the Partnach river relation is preferred over its member way.
    partnach = [e for e in entries.values() if e["name"] == "Partnach"]
    assert [e["osm"] for e in partnach] == ["relation/3002"]
    assert partnach[0]["type"] == "water"

    # Guarded lodging/restaurant widening (#14): the valley inn far from any
    # settlement is admitted as a hut …
    bock = entries["way/2007"]
    assert (bock["name"], bock["type"], bock["ele"]) == ("Bockhütte", "hut", 1052.0)
    # … the restaurant ~0.2 km from the Hammersbach settlement node is not …
    assert "node/1007" not in entries
    # … and neither is the far-from-town restaurant whose normalized name is
    # already covered ('Knorr-Hütte' vs the alpine_hut 'Knorrhütte') — guarded
    # tags fill gaps, they never duplicate a covered feature into a tie.
    assert "node/1008" not in entries

    # The nameless peak (node/1005) is skipped.
    assert "node/1005" not in entries
    assert len(entries) == 12
