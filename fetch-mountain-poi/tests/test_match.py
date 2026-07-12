import json

from conftest import FIXTURES, run_stage


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def run_pipeline(data_dir):
    assert run_stage("gazetteer", data_dir).returncode == 0
    result = run_stage("match", data_dir, routes=FIXTURES / "routes.jsonl")
    assert result.returncode == 0, result.stderr
    return result


def test_anchor_matching(data_dir):
    result = run_pipeline(data_dir)

    pois = {p["name"]: p for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}
    links = load_jsonl(data_dir / "04_final" / "route_pois.jsonl")

    # Two routes anchor the Zugspitze -> one registry entry, two links.
    assert set(pois) == {"Zugspitze", "Knorrhütte", "Höllentorkopf", "Kreuzeckbahn Bergstation"}
    zug_links = [l for l in links if l["poi_id"] == pois["Zugspitze"]["poi_id"]]
    assert {l["route_id"] for l in zug_links} == {"r1", "r2"}
    # Surfaces stay verbatim; elevation-suffix variant produces no alias.
    assert {l["surface"] for l in zug_links} == {"Zugspitze", "Zugspitze, 2962 m"}
    assert pois["Zugspitze"]["aliases"] == []
    assert pois["Zugspitze"]["match"] == {"method": "exact"}

    # 'Knorr-Hütte' (book) matches 'Knorrhütte' (OSM) via normalization,
    # and the book spelling is kept as an alias.
    assert pois["Knorrhütte"]["aliases"] == ["Knorr-Hütte"]

    # 'Höllentorkopf, 2150 m' matches after elevation stripping.
    assert pois["Höllentorkopf"]["ele"] == 2150.0

    # 'Bergstation der Kreuzeckbahn' (book word order) matches the OSM station
    # 'Kreuzeckbahn Bergstation'; the book phrasing is kept as an alias.
    station = pois["Kreuzeckbahn Bergstation"]
    assert station["type"] == "station"
    assert station["aliases"] == ["Bergstation der Kreuzeckbahn"]

    assert all(l["is_anchor"] for l in links)
    # r7 has no anchor: 5 links total (r1, r2, r3, r4, r8).
    assert len(links) == 5


def test_open_cases_are_reported_not_dropped(data_dir):
    result = run_pipeline(data_dir)

    cases = {c["route_id"]: c for c in load_jsonl(data_dir / "03_matched" / "anchor_open.jsonl")}
    assert cases["r5"]["status"] == "tie"  # two 'Wasserfall' candidates
    assert len(cases["r5"]["candidates"]) == 2
    assert cases["r6"]["status"] == "unmatched"
    assert cases["r6"]["candidates"] == []

    # Ranges/regions are a documented out-of-scope class: skipped with a
    # reason, not counted as unmatched.
    assert cases["r9"]["status"] == "skipped"
    assert "range" in cases["r9"]["reason"]
    assert len(cases) == 3

    # Funnel summary reports the counts.
    assert "ties: 1" in result.stderr
    assert "skipped: 1" in result.stderr
    assert "unmatched: 1" in result.stderr


def test_geojson_export(data_dir):
    run_pipeline(data_dir)

    geojson = json.loads((data_dir / "04_final" / "pois.geojson").read_text(encoding="utf-8"))
    assert geojson["type"] == "FeatureCollection"
    features = {f["properties"]["name"]: f for f in geojson["features"]}
    assert set(features) == {"Zugspitze", "Knorrhütte", "Höllentorkopf", "Kreuzeckbahn Bergstation"}

    zug = features["Zugspitze"]
    assert zug["geometry"] == {"type": "Point", "coordinates": [10.9863, 47.4211]}
    assert zug["properties"]["type"] == "peak"
    assert zug["properties"]["n_routes"] == 2
