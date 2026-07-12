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


def run_pipeline(data_dir, extra=()):
    assert run_stage("gazetteer", data_dir).returncode == 0
    with (data_dir / "01_gazetteer" / "gazetteer.jsonl").open("a", encoding="utf-8") as f:
        for entry in (*EXTRA_GAZETTEER, *extra):
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    result = run_stage("match", data_dir, routes=FIXTURES / "routes.jsonl")
    assert result.returncode == 0, result.stderr
    return result


def rerun_match(data_dir):
    """Rerun the matcher only — the gazetteer (and any hand-edited
    review.jsonl) stays exactly as it is on disk."""
    return run_stage("match", data_dir, routes=FIXTURES / "routes.jsonl")


def decide(data_dir, decision, route_id="r5"):
    """Hand-edit review.jsonl the way a reviewer does: fill in the decision
    on one case, leave everything else untouched."""
    path = data_dir / "03_matched" / "review.jsonl"
    cases = load_jsonl(path)
    next(c for c in cases if c["route_id"] == route_id)["decision"] = decision
    path.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases),
        encoding="utf-8",
    )


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
    assert funnel["types"]["anchor"] == {"mentions": 8, "exact": 5, "fuzzy": 0, "llm": 0,
                                         "review": 0, "tie": 1, "skipped": 1, "unmatched": 1}
    assert funnel["types"]["peak"] == {"mentions": 6, "exact": 1, "fuzzy": 2, "llm": 0,
                                       "review": 0, "tie": 1, "skipped": 0, "unmatched": 2}
    assert funnel["totals"] == {"mentions": 16, "exact": 7, "fuzzy": 3, "llm": 0, "review": 0,
                                "tie": 2, "skipped": 1, "unmatched": 3}

    # The planner renders it as a per-type table with a totals row.
    result = run_stage("plan", data_dir, routes=FIXTURES / "routes.jsonl", args=["funnel"])
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["type", "mentions", "exact", "fuzzy", "llm", "review",
                                "tie", "skipped", "unmatched"]
    rows = {line.split()[0]: line.split()[1:] for line in lines[1:]}
    assert rows["anchor"] == ["8", "5", "0", "0", "0", "1", "1", "1"]
    assert rows["settlement"] == ["1", "1", "0", "0", "0", "0", "0", "0"]
    assert rows["total"] == ["16", "7", "3", "0", "0", "2", "1", "3"]
    assert "3/9 routes have extracted mentions" in result.stderr


def test_accepted_decision_enters_registry_with_review_provenance(data_dir):
    run_pipeline(data_dir)
    # The r5 'Wasserfall' anchor tie: accept the node/1003 candidate.
    decide(data_dir, "node/1003")
    result = rerun_match(data_dir)
    assert result.returncode == 0, result.stderr

    # The accepted candidate is in the registry with review provenance ...
    pois = {p["name"]: p for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}
    assert pois["Wasserfall"]["osm"] == "node/1003"
    assert pois["Wasserfall"]["match"] == {"method": "review"}

    # ... linked to the deciding route with its anchor flag ...
    links = load_jsonl(data_dir / "04_final" / "route_pois.jsonl")
    link = next(l for l in links if l["poi_id"] == pois["Wasserfall"]["poi_id"])
    assert link == {"route_id": "r5", "poi_id": pois["Wasserfall"]["poi_id"],
                    "surface": "Wasserfall", "is_anchor": True}

    # ... and exported to the GeoJSON.
    geojson = json.loads((data_dir / "04_final" / "pois.geojson").read_text(encoding="utf-8"))
    assert "Wasserfall" in {f["properties"]["name"] for f in geojson["features"]}

    # Funnel: the case moved from tie to the review column.
    funnel = json.loads((data_dir / "03_matched" / "funnel.json").read_text(encoding="utf-8"))
    assert funnel["types"]["anchor"]["review"] == 1
    assert funnel["types"]["anchor"]["tie"] == 0
    assert "review: 1" in result.stderr
    assert "ties: 0 open" in result.stderr

    # The case stays in review.jsonl as the persistent decision record.
    case = next(c for c in load_jsonl(data_dir / "03_matched" / "review.jsonl")
                if c["route_id"] == "r5")
    assert case["decision"] == "node/1003"


def test_review_provenance_outranks_exact(data_dir):
    # 'Doppelspitze' twice in the gazetteer: r1's mention states 2000 m, so
    # the elevation guard resolves it exactly to node/9010; r3's mention
    # states nothing and ties.
    doppel = [
        {"name": "Doppelspitze", "type": "peak", "lat": 47.45, "lon": 11.05,
         "ele": 2000.0, "osm": "node/9010"},
        {"name": "Doppelspitze", "type": "peak", "lat": 47.48, "lon": 11.11,
         "ele": 2500.0, "osm": "node/9011"},
    ]
    write_part(data_dir, "r1", mention("Doppelspitze", elevation_m=2000))
    write_part(data_dir, "r3", mention("Doppelspitze"))
    run_pipeline(data_dir, extra=doppel)

    pois = {p["name"]: p for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}
    assert pois["Doppelspitze"]["match"] == {"method": "exact"}

    # Accepting node/9010 for the r3 tie upgrades the provenance: a human
    # decision outranks the exact match from r1.
    decide(data_dir, "node/9010", route_id="r3")
    assert rerun_match(data_dir).returncode == 0

    pois = {p["name"]: p for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}
    assert pois["Doppelspitze"]["osm"] == "node/9010"
    assert pois["Doppelspitze"]["match"] == {"method": "review"}


def test_skip_decision_routes_to_unmatched(data_dir):
    run_pipeline(data_dir)
    decide(data_dir, "skip")
    result = rerun_match(data_dir)
    assert result.returncode == 0, result.stderr

    # The mention lands in unmatched.jsonl, marked as a human skip ...
    unmatched = {c["route_id"]: c for c in load_jsonl(data_dir / "03_matched" / "unmatched.jsonl")}
    assert unmatched["r5"] == {
        "route_id": "r5", "mention": "Wasserfall", "name": "Wasserfall",
        "type": None, "is_anchor": True, "elevation_m": None, "skipped_by": "review",
    }

    # ... never in the registry, and the funnel counts it as skipped.
    assert "Wasserfall" not in {p["name"] for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}
    # skipped = r9's out-of-scope skip + this review skip.
    funnel = json.loads((data_dir / "03_matched" / "funnel.json").read_text(encoding="utf-8"))
    assert funnel["types"]["anchor"]["skipped"] == 2
    assert funnel["types"]["anchor"]["tie"] == 0

    # The decision record persists in review.jsonl.
    case = next(c for c in load_jsonl(data_dir / "03_matched" / "review.jsonl")
                if c["route_id"] == "r5")
    assert case["decision"] == "skip"


def test_review_decisions_survive_reruns(data_dir):
    write_cascade_parts(data_dir)  # adds a second, mention-level tie (r3)
    run_pipeline(data_dir)

    review_path = data_dir / "03_matched" / "review.jsonl"
    open_before = next(c for c in load_jsonl(review_path) if c["route_id"] == "r3")
    decide(data_dir, "node/1003", route_id="r5")

    # The decided case never reopens; the undecided one is re-emitted
    # unchanged — on the first rerun and on every one after.
    for _ in range(2):
        result = rerun_match(data_dir)
        assert result.returncode == 0, result.stderr
        by_route = {c["route_id"]: c for c in load_jsonl(review_path)}
        assert by_route["r5"]["decision"] == "node/1003"
        assert by_route["r3"] == open_before
        funnel = json.loads((data_dir / "03_matched" / "funnel.json").read_text(encoding="utf-8"))
        assert funnel["totals"]["review"] == 1
        assert funnel["totals"]["tie"] == 1


def test_invalid_decision_ref_fails_loudly(data_dir):
    run_pipeline(data_dir)
    decide(data_dir, "node/99999")  # not one of the case's candidates: a typo

    result = rerun_match(data_dir)
    assert result.returncode != 0
    for needle in ("node/99999", "Wasserfall", "r5", "node/1003", "node/1004"):
        assert needle in result.stderr
    # Nothing was silently accepted: the case is still open on disk.
    # (The failed run must not have rewritten any artifact.)
    case = next(c for c in load_jsonl(data_dir / "03_matched" / "review.jsonl")
                if c["route_id"] == "r5")
    assert case["decision"] == "node/99999"


def test_vanished_accepted_candidate_reopens_case(data_dir):
    # Three-way 'Wasserfall' tie; the reviewer accepts the extra candidate.
    extra = [{"name": "Wasserfall", "type": "peak", "lat": 47.50, "lon": 11.20,
              "ele": None, "osm": "node/9003"}]
    run_pipeline(data_dir, extra=extra)
    decide(data_dir, "node/9003")

    # A gazetteer refetch drops node/9003; the decision points nowhere.
    gaz_path = data_dir / "01_gazetteer" / "gazetteer.jsonl"
    kept = [e for e in load_jsonl(gaz_path) if e["osm"] != "node/9003"]
    gaz_path.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in kept),
        encoding="utf-8",
    )

    # No crash: the case is reopened with a note and counted as a tie again.
    result = rerun_match(data_dir)
    assert result.returncode == 0, result.stderr
    case = next(c for c in load_jsonl(data_dir / "03_matched" / "review.jsonl")
                if c["route_id"] == "r5")
    assert case["decision"] is None
    assert "node/9003" in case["note"]
    assert {c["osm"] for c in case["candidates"]} == {"node/1003", "node/1004"}
    funnel = json.loads((data_dir / "03_matched" / "funnel.json").read_text(encoding="utf-8"))
    assert funnel["types"]["anchor"]["tie"] == 1
    assert funnel["types"]["anchor"]["review"] == 0

    # The note survives further reruns while the case stays undecided ...
    assert rerun_match(data_dir).returncode == 0
    case = next(c for c in load_jsonl(data_dir / "03_matched" / "review.jsonl")
                if c["route_id"] == "r5")
    assert "node/9003" in case["note"]

    # ... and a fresh decision on a surviving candidate closes it again.
    decide(data_dir, "node/1004")
    assert rerun_match(data_dir).returncode == 0
    pois = {p["name"]: p for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}
    assert pois["Wasserfall"]["osm"] == "node/1004"
    assert pois["Wasserfall"]["match"] == {"method": "review"}


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
