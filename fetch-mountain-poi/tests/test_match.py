import json

from conftest import FIXTURES, run_stage

# Extra gazetteer entries for the fuzzy scenarios, appended to the stage's
# output so the shared Overpass fixture stays untouched.
EXTRA_GAZETTEER = [
    {"name": "Predigtstein", "type": "peak", "lat": 47.46, "lon": 11.08,
     "ele": 1921.0, "osm": "node/9001"},
    {"name": "Partnachalm", "type": "hut", "lat": 47.47, "lon": 11.09,
     "ele": 1177.0, "osm": "node/9002"},
]


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def mention(surface, type="peak", name=None, elevation_m=None):
    return {"surface": surface, "name": name or surface,
            "type": type, "elevation_m": elevation_m}


def write_part(data_dir, route_id, *mentions):
    parts = data_dir / "02_mentions" / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    (parts / f"{route_id}.json").write_text(
        json.dumps({"route_id": route_id, "mentions": list(mentions)}, ensure_ascii=False),
        encoding="utf-8",
    )


def run_pipeline(data_dir):
    assert run_stage("gazetteer", data_dir).returncode == 0
    with (data_dir / "01_gazetteer" / "gazetteer.jsonl").open("a", encoding="utf-8") as f:
        for entry in EXTRA_GAZETTEER:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    result = run_stage("match", data_dir, routes=FIXTURES / "routes.jsonl")
    assert result.returncode == 0, result.stderr
    return result


def write_cascade_parts(data_dir):
    """Mention parts exercising every cascade path (r1, r3, r7 of the fixture
    routes; the other routes contribute anchors only)."""
    # Same POI as r1's own anchor -> the (route, poi) link is deduplicated.
    write_part(data_dir, "r1",
               mention("Zugspitze, 2962 m", name="Zugspitze", elevation_m=2962))
    write_part(data_dir, "r3",
               # Fuzzy 90.9 to 'Partnachalm' but peak never matches hut.
               mention("Partnachalb", type="peak"),
               # Fuzzy 91.7 to 'Predigtstein' but book says 1700, OSM 1921.
               mention("Predigtstain", type="peak", elevation_m=1700),
               # Two 'Wasserfall' peaks in the gazetteer -> tie.
               mention("Wasserfall", type="peak"))
    write_part(data_dir, "r7",
               mention("Hammersbach", type="settlement"),          # exact
               mention("Predigtstain", type="peak", elevation_m=1900),  # fuzzy, ele ok
               mention("Zugspitz", type="peak"),                   # fuzzy, no ele stated
               mention("Partnachalb", type="hut"))                 # fuzzy, type ok


def test_anchor_matching(data_dir):
    run_pipeline(data_dir)

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

    # 'Höllentorkopf, 2150 m' matches after elevation stripping; the stated
    # elevation agrees with OSM, so the guard lets the exact match through.
    assert pois["Höllentorkopf"]["ele"] == 2150.0

    # 'Bergstation der Kreuzeckbahn' (book word order) matches the OSM station
    # 'Kreuzeckbahn Bergstation'; the book phrasing is kept as an alias.
    station = pois["Kreuzeckbahn Bergstation"]
    assert station["type"] == "station"
    assert station["aliases"] == ["Bergstation der Kreuzeckbahn"]

    assert all(l["is_anchor"] for l in links)
    # r7 has no anchor: 5 links total (r1, r2, r3, r4, r8).
    assert len(links) == 5


def test_ties_and_unmatched_are_reported_not_dropped(data_dir):
    result = run_pipeline(data_dir)

    # Two same-name 'Wasserfall' peaks survive for r5's anchor -> an open
    # review case with full candidate context and no auto-resolution.
    cases = load_jsonl(data_dir / "03_matched" / "review.jsonl")
    assert len(cases) == 1
    case = cases[0]
    assert case["mention"] == "Wasserfall"
    assert case["name"] == "Wasserfall"
    assert case["type"] is None  # anchors carry no taxonomy type
    assert case["route_id"] == "r5"
    assert case["is_anchor"] is True
    assert case["decision"] is None
    assert case["source"] == "tie"
    assert {c["osm"] for c in case["candidates"]} == {"node/1003", "node/1004"}
    for c in case["candidates"]:
        assert set(c) == {"osm", "name", "type", "ele", "lat", "lon", "score"}
        assert c["score"] == 100.0

    # Tied mentions never enter the registry.
    assert "Wasserfall" not in {p["name"] for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}

    # r6's anchor has no candidate -> unmatched, with the route reference.
    # r9 ('Wettersteingebirge') is a documented out-of-scope class: recorded
    # alongside with a skip_reason and counted as skipped, not unmatched.
    unmatched = {c["route_id"]: c for c in load_jsonl(data_dir / "03_matched" / "unmatched.jsonl")}
    assert unmatched["r6"] == {
        "route_id": "r6", "mention": "Unbekanntspitze", "name": "Unbekanntspitze",
        "type": None, "is_anchor": True, "elevation_m": None,
    }
    assert "range" in unmatched["r9"]["skip_reason"]
    assert len(unmatched) == 2

    # The old anchors-only artifact is superseded.
    assert not (data_dir / "03_matched" / "anchor_open.jsonl").exists()

    # Funnel summary reports the counts.
    assert "ties: 1" in result.stderr
    assert "skipped: 1" in result.stderr
    assert "unmatched: 1" in result.stderr


def test_mention_cascade(data_dir):
    write_cascade_parts(data_dir)
    result = run_pipeline(data_dir)
    assert "(3 with extracted mentions)" in result.stderr

    pois = {p["name"]: p for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}
    links = load_jsonl(data_dir / "04_final" / "route_pois.jsonl")

    assert set(pois) == {"Zugspitze", "Knorrhütte", "Höllentorkopf",
                         "Kreuzeckbahn Bergstation",
                         "Hammersbach", "Predigtstein", "Partnachalm"}

    # Exact mention match carries exact provenance.
    assert pois["Hammersbach"]["match"] == {"method": "exact"}

    # Fuzzy matches record method and score; elevation within +-50 m passed.
    assert pois["Predigtstein"]["match"] == {"method": "fuzzy", "score": 91.7}
    assert pois["Predigtstein"]["aliases"] == ["Predigtstain"]
    # Type guard: 'Partnachalb' matched as hut (r7), never as peak (r3).
    assert pois["Partnachalm"]["match"] == {"method": "fuzzy", "score": 90.9}
    partnach_links = [l for l in links if l["poi_id"] == pois["Partnachalm"]["poi_id"]]
    assert [l["route_id"] for l in partnach_links] == ["r7"]

    # Guard-blocked fuzzy candidates land in unmatched, not the registry.
    unmatched = {(u["route_id"], u["name"]) for u in
                 load_jsonl(data_dir / "03_matched" / "unmatched.jsonl")}
    assert ("r3", "Partnachalb") in unmatched     # type-incompatible
    assert ("r3", "Predigtstain") in unmatched    # elevation off by 221 m
    assert ("r6", "Unbekanntspitze") in unmatched

    # A mention-level tie joins the anchor tie in review.jsonl.
    review = {(c["route_id"], c["is_anchor"]) for c in
              load_jsonl(data_dir / "03_matched" / "review.jsonl")}
    assert review == {("r5", True), ("r3", False)}

    # Dedup across anchor + mention: r1 mentions its own anchor POI -> still
    # one link, anchor flag and anchor surface win.
    zug = pois["Zugspitze"]
    zug_links = {l["route_id"]: l for l in links if l["poi_id"] == zug["poi_id"]}
    assert set(zug_links) == {"r1", "r2", "r7"}
    assert zug_links["r1"] == {"route_id": "r1", "poi_id": zug["poi_id"],
                               "surface": "Zugspitze", "is_anchor": True}
    # The fuzzy 'Zugspitz' mention adds an alias but the exact anchor match
    # keeps the better provenance.
    assert zug_links["r7"]["is_anchor"] is False
    assert zug["aliases"] == ["Zugspitz"]
    assert zug["match"] == {"method": "exact"}

    geojson = json.loads((data_dir / "04_final" / "pois.geojson").read_text(encoding="utf-8"))
    n_routes = {f["properties"]["name"]: f["properties"]["n_routes"] for f in geojson["features"]}
    assert n_routes["Zugspitze"] == 3


def test_funnel(data_dir):
    write_cascade_parts(data_dir)
    run_pipeline(data_dir)

    funnel = json.loads((data_dir / "03_matched" / "funnel.json").read_text(encoding="utf-8"))
    assert funnel["routes"] == {"total": 9, "with_mentions": 3}
    # r8's station anchor matches exactly via canonicalization; r9's
    # 'Wettersteingebirge' is the documented out-of-scope skip.
    assert funnel["types"]["anchor"] == {"mentions": 8, "exact": 5, "fuzzy": 0,
                                         "tie": 1, "skipped": 1, "unmatched": 1}
    assert funnel["types"]["peak"] == {"mentions": 6, "exact": 1, "fuzzy": 2,
                                       "tie": 1, "skipped": 0, "unmatched": 2}
    assert funnel["totals"] == {"mentions": 16, "exact": 7, "fuzzy": 3,
                                "tie": 2, "skipped": 1, "unmatched": 3}

    # The planner renders it as a per-type table with a totals row.
    result = run_stage("plan", data_dir, routes=FIXTURES / "routes.jsonl", args=["funnel"])
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["type", "mentions", "exact", "fuzzy", "tie", "skipped", "unmatched"]
    rows = {line.split()[0]: line.split()[1:] for line in lines[1:]}
    assert rows["anchor"] == ["8", "5", "0", "1", "1", "1"]
    assert rows["settlement"] == ["1", "1", "0", "0", "0", "0"]
    assert rows["total"] == ["16", "7", "3", "2", "1", "3"]
    assert "3/9 routes have extracted mentions" in result.stderr


def test_review_decisions_survive_reruns(data_dir):
    result = run_pipeline(data_dir)

    review_path = data_dir / "03_matched" / "review.jsonl"
    case = load_jsonl(review_path)[0]
    case["decision"] = "node/1003"
    review_path.write_text(json.dumps(case, ensure_ascii=False) + "\n", encoding="utf-8")

    # Rerunning the matcher rewrites review.jsonl but keeps the decision.
    result = run_stage("match", data_dir, routes=FIXTURES / "routes.jsonl")
    assert result.returncode == 0, result.stderr
    assert load_jsonl(review_path)[0]["decision"] == "node/1003"


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
