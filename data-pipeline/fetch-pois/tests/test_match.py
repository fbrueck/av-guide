import json

import pytest

from pipeline import gazetteer, plan
from pipeline.match import run_match

# Extra gazetteer entries for the fuzzy scenarios, appended to the stage's
# output so the shared Overpass fixture stays untouched.
EXTRA_GAZETTEER = [
    {
        "name": "Predigtstein",
        "type": "peak",
        "lat": 47.46,
        "lon": 11.08,
        "ele": 1921.0,
        "osm": "node/9001",
    },
    {
        "name": "Partnachalm",
        "type": "hut",
        "lat": 47.47,
        "lon": 11.09,
        "ele": 1177.0,
        "osm": "node/9002",
    },
]


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def mention(surface, type="peak", name=None, elevation_m=None):
    return {
        "surface": surface,
        "name": name or surface,
        "type": type,
        "elevation_m": elevation_m,
    }


def write_part(cfg, entry_id, *mentions):
    cfg.mention_parts.mkdir(parents=True, exist_ok=True)
    (cfg.mention_parts / f"{entry_id}.json").write_text(
        json.dumps(
            {"entry_id": entry_id, "mentions": list(mentions)}, ensure_ascii=False
        ),
        encoding="utf-8",
    )


def run_pipeline(cfg, extra=()):
    """Build the gazetteer from the cached response, append the scenario's
    extra entries, then run the matcher. Returns the funnel report."""
    gazetteer.build_gazetteer(cfg, refresh=False)
    with cfg.gazetteer.open("a", encoding="utf-8") as f:
        for entry in (*EXTRA_GAZETTEER, *extra):
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return run_match(cfg)


def rerun_match(cfg):
    """Rerun the matcher only — the gazetteer (and any hand-edited
    review.jsonl) stays exactly as it is on disk."""
    return run_match(cfg)


def decide(cfg, decision, entry_id="r5"):
    """Hand-edit review.jsonl the way a reviewer does: fill in the decision
    on one case, leave everything else untouched."""
    cases = load_jsonl(cfg.review)
    next(c for c in cases if c["entry_id"] == entry_id)["decision"] = decision
    cfg.review.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases),
        encoding="utf-8",
    )


def write_cascade_parts(cfg):
    """Mention parts exercising every cascade path over both a Place's Übersicht
    (r1) and Route descriptions (r2, r7). The other entries contribute only
    their Place resolution."""
    # A Place's Übersicht naming its own summit -> the entry_pois mention link
    # is separate from the r1 place_pois link (both point at the same POI).
    write_part(
        cfg, "r1", mention("Zugspitze, 2962 m", name="Zugspitze", elevation_m=2962)
    )
    write_part(
        cfg,
        "r2",
        # Fuzzy 90.9 to 'Partnachalm' but peak never matches hut.
        mention("Partnachalb", type="peak"),
        # Fuzzy 91.7 to 'Predigtstein' but book says 1700, OSM 1921.
        mention("Predigtstain", type="peak", elevation_m=1700),
        # Two 'Wasserfall' peaks in the gazetteer -> tie.
        mention("Wasserfall", type="peak"),
    )
    write_part(
        cfg,
        "r7",
        mention("Hammersbach", type="settlement"),  # exact
        mention("Predigtstain", type="peak", elevation_m=1900),  # fuzzy, ele ok
        mention("Zugspitz", type="peak"),  # fuzzy, no ele stated
        mention("Partnachalb", type="hut"),  # fuzzy, type ok
    )


def test_place_resolution(cfg):
    run_pipeline(cfg)

    pois = {p["name"]: p for p in load_jsonl(cfg.pois_jsonl)}
    place_links = load_jsonl(cfg.place_pois_jsonl)

    # Each resolvable Place maps to exactly one POI; the four that resolve.
    assert set(pois) == {
        "Zugspitze",
        "Knorrhütte",
        "Höllentorkopf",
        "Kreuzeckbahn Bergstation",
    }
    assert pois["Zugspitze"]["match"] == {"method": "exact"}
    assert pois["Zugspitze"]["aliases"] == []

    # place_pois carries only {place_id, poi_id} — no surface, no anchor flag.
    by_place = {ln["place_id"]: ln for ln in place_links}
    assert set(by_place) == {"r1", "r3", "r4", "r8"}
    assert by_place["r1"] == {"place_id": "r1", "poi_id": pois["Zugspitze"]["poi_id"]}
    for link in place_links:
        assert set(link) == {"place_id", "poi_id"}

    # 'Knorr-Hütte' (book) matches 'Knorrhütte' (OSM) via normalization,
    # and the guarded place_type hint (hut) plus elevation let it through;
    # the book spelling is kept as an alias.
    assert pois["Knorrhütte"]["aliases"] == ["Knorr-Hütte"]

    # 'Höllentorkopf' resolves with the stated elevation agreeing with OSM.
    assert pois["Höllentorkopf"]["ele"] == 2150.0

    # 'Bergstation der Kreuzeckbahn' (book word order) matches the OSM station
    # 'Kreuzeckbahn Bergstation'; the book phrasing is kept as an alias.
    station = pois["Kreuzeckbahn Bergstation"]
    assert station["type"] == "station"
    assert station["aliases"] == ["Bergstation der Kreuzeckbahn"]

    # No mentions yet -> the entry_pois link table is empty. Routes never
    # resolve themselves; a Route's `peak` is not an item.
    assert load_jsonl(cfg.entry_pois_jsonl) == []


def test_places_ties_and_unmatched_are_reported_not_dropped(cfg):
    report = run_pipeline(cfg)

    # Two same-name 'Wasserfall' peaks survive for the r5 Place -> an open
    # review case with full candidate context and no auto-resolution.
    cases = load_jsonl(cfg.review)
    assert len(cases) == 1
    case = cases[0]
    assert case["mention"] == "Wasserfall"
    assert case["name"] == "Wasserfall"
    assert case["type"] == "peak"  # the Place's place_type hint
    assert case["entry_id"] == "r5"
    assert case["kind"] == "place"
    assert case["decision"] is None
    assert case["source"] == "tie"
    assert {c["osm"] for c in case["candidates"]} == {"node/1003", "node/1004"}
    for c in case["candidates"]:
        assert set(c) == {"osm", "name", "type", "ele", "lat", "lon", "score"}
        assert c["score"] == 100.0

    # Tied Places never enter the registry.
    assert "Wasserfall" not in {p["name"] for p in load_jsonl(cfg.pois_jsonl)}

    # r6's Place has no candidate -> unmatched, keyed by entry with its kind.
    # r9 ('Wettersteingebirge') is a documented out-of-scope class: recorded
    # alongside with a skip_reason and counted as skipped, not unmatched.
    unmatched = {c["entry_id"]: c for c in load_jsonl(cfg.unmatched)}
    assert unmatched["r6"] == {
        "entry_id": "r6",
        "mention": "Unbekanntspitze",
        "name": "Unbekanntspitze",
        "type": "peak",
        "kind": "place",
        "elevation_m": None,
    }
    assert "range" in unmatched["r9"]["skip_reason"]
    assert len(unmatched) == 2

    # Funnel report totals reflect the counts.
    assert report["totals"]["tie"] == 1
    assert report["totals"]["skipped"] == 1
    assert report["totals"]["unmatched"] == 1


def test_mention_cascade(cfg):
    write_cascade_parts(cfg)
    report = run_pipeline(cfg)
    assert report["entries"]["with_mentions"] == 3

    pois = {p["name"]: p for p in load_jsonl(cfg.pois_jsonl)}
    links = load_jsonl(cfg.entry_pois_jsonl)

    assert set(pois) == {
        "Zugspitze",
        "Knorrhütte",
        "Höllentorkopf",
        "Kreuzeckbahn Bergstation",
        "Hammersbach",
        "Predigtstein",
        "Partnachalm",
    }

    # Exact mention match carries exact provenance.
    assert pois["Hammersbach"]["match"] == {"method": "exact"}

    # Fuzzy matches record method and score; elevation within +-50 m passed.
    assert pois["Predigtstein"]["match"] == {"method": "fuzzy", "score": 91.7}
    assert pois["Predigtstein"]["aliases"] == ["Predigtstain"]
    # Type guard: 'Partnachalb' matched as hut (r7), never as peak (r2).
    assert pois["Partnachalm"]["match"] == {"method": "fuzzy", "score": 90.9}
    partnach_links = [
        ln for ln in links if ln["poi_id"] == pois["Partnachalm"]["poi_id"]
    ]
    assert [ln["entry_id"] for ln in partnach_links] == ["r7"]

    # Guard-blocked fuzzy candidates land in unmatched, not the registry.
    unmatched = {(u["entry_id"], u["name"]) for u in load_jsonl(cfg.unmatched)}
    assert ("r2", "Partnachalb") in unmatched  # type-incompatible
    assert ("r2", "Predigtstain") in unmatched  # elevation off by 221 m
    assert ("r6", "Unbekanntspitze") in unmatched  # r6 Place, no candidate

    # A mention-level tie (r2) joins the Place tie (r5) in review.jsonl.
    review = {(c["entry_id"], c["kind"]) for c in load_jsonl(cfg.review)}
    assert review == {("r5", "place"), ("r2", "mention")}

    # entry_pois links are mentions only: {entry_id, poi_id, surface}, keyed by
    # (entry, POI). r1's Übersicht mentions its own summit -> a mention link
    # distinct from the r1 place_pois link, both to the same POI.
    zug = pois["Zugspitze"]
    zug_links = {ln["entry_id"]: ln for ln in links if ln["poi_id"] == zug["poi_id"]}
    assert set(zug_links) == {"r1", "r7"}
    assert zug_links["r1"] == {
        "entry_id": "r1",
        "poi_id": zug["poi_id"],
        "surface": "Zugspitze, 2962 m",  # verbatim mention surface
    }
    assert "is_anchor" not in zug_links["r1"]
    # The fuzzy 'Zugspitz' mention (r7) adds an alias but the exact Place match
    # keeps the better provenance.
    assert zug["aliases"] == ["Zugspitz"]
    assert zug["match"] == {"method": "exact"}

    # The r1 Place still links its POI in place_pois too.
    assert {ln["place_id"] for ln in load_jsonl(cfg.place_pois_jsonl)} == {
        "r1",
        "r3",
        "r4",
        "r8",
    }

    geojson = json.loads(cfg.pois_geojson.read_text(encoding="utf-8"))
    n_entries = {
        f["properties"]["name"]: f["properties"]["n_entries"]
        for f in geojson["features"]
    }
    # Zugspitze is referenced by two distinct entries: the r1 Place and the r7
    # mention (r1's own mention collapses onto the r1 Place count).
    assert n_entries["Zugspitze"] == 2


def test_mentions_extracted_from_place_prose(cfg):
    # A Place's Übersicht (r3, Knorr-Hütte) names other places; those become
    # entry_pois mention links keyed by the Place's own entry id.
    write_part(cfg, "r3", mention("Hammersbach", type="settlement"))
    run_pipeline(cfg)

    links = load_jsonl(cfg.entry_pois_jsonl)
    pois = {p["name"]: p for p in load_jsonl(cfg.pois_jsonl)}
    ham = [ln for ln in links if ln["poi_id"] == pois["Hammersbach"]["poi_id"]]
    assert [ln["entry_id"] for ln in ham] == ["r3"]
    assert ham[0]["surface"] == "Hammersbach"


def test_funnel(cfg, capsys):
    write_cascade_parts(cfg)
    run_pipeline(cfg)

    funnel = json.loads(cfg.funnel.read_text(encoding="utf-8"))
    assert funnel["entries"] == {"total": 9, "with_mentions": 3}
    # Place resolution funnel: 4 exact (r1, r3, r4, r8), the r5 Wasserfall tie,
    # the r6 unmatched Place, and the r9 out-of-scope skip.
    assert funnel["types"]["place"] == {
        "mentions": 7,
        "exact": 4,
        "fuzzy": 0,
        "llm": 0,
        "review": 0,
        "tie": 1,
        "skipped": 1,
        "unmatched": 1,
    }
    assert funnel["types"]["peak"] == {
        "mentions": 6,
        "exact": 1,
        "fuzzy": 2,
        "llm": 0,
        "review": 0,
        "tie": 1,
        "skipped": 0,
        "unmatched": 2,
    }
    assert funnel["totals"] == {
        "mentions": 15,
        "exact": 6,
        "fuzzy": 3,
        "llm": 0,
        "review": 0,
        "tie": 2,
        "skipped": 1,
        "unmatched": 3,
    }

    # The planner renders it as a per-type table with a totals row.
    capsys.readouterr()  # drop the matcher's summary output
    plan._print_funnel(cfg)
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert lines[0].split() == [
        "type",
        "mentions",
        "exact",
        "fuzzy",
        "llm",
        "review",
        "tie",
        "skipped",
        "unmatched",
    ]
    rows = {line.split()[0]: line.split()[1:] for line in lines[1:]}
    assert rows["place"] == ["7", "4", "0", "0", "0", "1", "1", "1"]
    assert rows["settlement"] == ["1", "1", "0", "0", "0", "0", "0", "0"]
    assert rows["total"] == ["15", "6", "3", "0", "0", "2", "1", "3"]
    assert "3/9 entries have extracted mentions" in out.err


def test_accepted_decision_enters_registry_with_review_provenance(cfg):
    run_pipeline(cfg)
    # The r5 'Wasserfall' Place tie: accept the node/1003 candidate.
    decide(cfg, "node/1003")
    report = rerun_match(cfg)

    # The accepted candidate is in the registry with review provenance ...
    pois = {p["name"]: p for p in load_jsonl(cfg.pois_jsonl)}
    assert pois["Wasserfall"]["osm"] == "node/1003"
    assert pois["Wasserfall"]["match"] == {"method": "review"}

    # ... linked to the deciding Place in place_pois ...
    place_links = load_jsonl(cfg.place_pois_jsonl)
    link = next(
        ln for ln in place_links if ln["poi_id"] == pois["Wasserfall"]["poi_id"]
    )
    assert link == {"place_id": "r5", "poi_id": pois["Wasserfall"]["poi_id"]}

    # ... and exported to the GeoJSON.
    geojson = json.loads(cfg.pois_geojson.read_text(encoding="utf-8"))
    assert "Wasserfall" in {f["properties"]["name"] for f in geojson["features"]}

    # Funnel: the case moved from tie to the review column.
    funnel = json.loads(cfg.funnel.read_text(encoding="utf-8"))
    assert funnel["types"]["place"]["review"] == 1
    assert funnel["types"]["place"]["tie"] == 0
    assert report["totals"]["review"] == 1
    assert report["totals"]["tie"] == 0

    # The case stays in review.jsonl as the persistent decision record.
    case = next(c for c in load_jsonl(cfg.review) if c["entry_id"] == "r5")
    assert case["decision"] == "node/1003"


def test_review_provenance_outranks_exact(cfg):
    # 'Doppelspitze' twice in the gazetteer: r2's mention states 2000 m, so
    # the elevation guard resolves it exactly to node/9010; r7's mention
    # states nothing and ties.
    doppel = [
        {
            "name": "Doppelspitze",
            "type": "peak",
            "lat": 47.45,
            "lon": 11.05,
            "ele": 2000.0,
            "osm": "node/9010",
        },
        {
            "name": "Doppelspitze",
            "type": "peak",
            "lat": 47.48,
            "lon": 11.11,
            "ele": 2500.0,
            "osm": "node/9011",
        },
    ]
    write_part(cfg, "r2", mention("Doppelspitze", elevation_m=2000))
    write_part(cfg, "r7", mention("Doppelspitze"))
    run_pipeline(cfg, extra=doppel)

    pois = {p["name"]: p for p in load_jsonl(cfg.pois_jsonl)}
    assert pois["Doppelspitze"]["match"] == {"method": "exact"}

    # Accepting node/9010 for the r7 tie upgrades the provenance: a human
    # decision outranks the exact match from r2.
    decide(cfg, "node/9010", entry_id="r7")
    rerun_match(cfg)

    pois = {p["name"]: p for p in load_jsonl(cfg.pois_jsonl)}
    assert pois["Doppelspitze"]["osm"] == "node/9010"
    assert pois["Doppelspitze"]["match"] == {"method": "review"}


def test_skip_decision_routes_to_unmatched(cfg):
    run_pipeline(cfg)
    decide(cfg, "skip")
    rerun_match(cfg)

    # The Place lands in unmatched.jsonl, marked as a human skip ...
    unmatched = {c["entry_id"]: c for c in load_jsonl(cfg.unmatched)}
    assert unmatched["r5"] == {
        "entry_id": "r5",
        "mention": "Wasserfall",
        "name": "Wasserfall",
        "type": "peak",
        "kind": "place",
        "elevation_m": None,
        "skipped_by": "review",
    }

    # ... never in the registry, and the funnel counts it as skipped.
    assert "Wasserfall" not in {p["name"] for p in load_jsonl(cfg.pois_jsonl)}
    # skipped = r9's out-of-scope skip + this review skip.
    funnel = json.loads(cfg.funnel.read_text(encoding="utf-8"))
    assert funnel["types"]["place"]["skipped"] == 2
    assert funnel["types"]["place"]["tie"] == 0

    # The decision record persists in review.jsonl.
    case = next(c for c in load_jsonl(cfg.review) if c["entry_id"] == "r5")
    assert case["decision"] == "skip"


def test_review_decisions_survive_reruns(cfg):
    write_cascade_parts(cfg)  # adds a second, mention-level tie (r2)
    run_pipeline(cfg)

    open_before = next(c for c in load_jsonl(cfg.review) if c["entry_id"] == "r2")
    decide(cfg, "node/1003", entry_id="r5")

    # The decided case never reopens; the undecided one is re-emitted
    # unchanged — on the first rerun and on every one after.
    for _ in range(2):
        rerun_match(cfg)
        by_entry = {c["entry_id"]: c for c in load_jsonl(cfg.review)}
        assert by_entry["r5"]["decision"] == "node/1003"
        assert by_entry["r2"] == open_before
        funnel = json.loads(cfg.funnel.read_text(encoding="utf-8"))
        assert funnel["totals"]["review"] == 1
        assert funnel["totals"]["tie"] == 1


def test_invalid_decision_ref_fails_loudly(cfg):
    run_pipeline(cfg)
    decide(cfg, "node/99999")  # not one of the case's candidates: a typo

    with pytest.raises(SystemExit) as excinfo:
        rerun_match(cfg)
    msg = str(excinfo.value)
    for needle in ("node/99999", "Wasserfall", "r5", "node/1003", "node/1004"):
        assert needle in msg
    # Nothing was silently accepted: the case is still open on disk.
    case = next(c for c in load_jsonl(cfg.review) if c["entry_id"] == "r5")
    assert case["decision"] == "node/99999"


def test_vanished_accepted_candidate_reopens_case(cfg):
    # Three-way 'Wasserfall' tie; the reviewer accepts the extra candidate.
    extra = [
        {
            "name": "Wasserfall",
            "type": "peak",
            "lat": 47.50,
            "lon": 11.20,
            "ele": None,
            "osm": "node/9003",
        }
    ]
    run_pipeline(cfg, extra=extra)
    decide(cfg, "node/9003")

    # A gazetteer refetch drops node/9003; the decision points nowhere.
    kept = [e for e in load_jsonl(cfg.gazetteer) if e["osm"] != "node/9003"]
    cfg.gazetteer.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in kept),
        encoding="utf-8",
    )

    # No crash: the case is reopened with a note and counted as a tie again.
    rerun_match(cfg)
    case = next(c for c in load_jsonl(cfg.review) if c["entry_id"] == "r5")
    assert case["decision"] is None
    assert "node/9003" in case["note"]
    assert {c["osm"] for c in case["candidates"]} == {"node/1003", "node/1004"}
    funnel = json.loads(cfg.funnel.read_text(encoding="utf-8"))
    assert funnel["types"]["place"]["tie"] == 1
    assert funnel["types"]["place"]["review"] == 0

    # The note survives further reruns while the case stays undecided ...
    rerun_match(cfg)
    case = next(c for c in load_jsonl(cfg.review) if c["entry_id"] == "r5")
    assert "node/9003" in case["note"]

    # ... and a fresh decision on a surviving candidate closes it again.
    decide(cfg, "node/1004")
    rerun_match(cfg)
    pois = {p["name"]: p for p in load_jsonl(cfg.pois_jsonl)}
    assert pois["Wasserfall"]["osm"] == "node/1004"
    assert pois["Wasserfall"]["match"] == {"method": "review"}


def test_geojson_export(cfg):
    run_pipeline(cfg)

    geojson = json.loads(cfg.pois_geojson.read_text(encoding="utf-8"))
    assert geojson["type"] == "FeatureCollection"
    features = {f["properties"]["name"]: f for f in geojson["features"]}
    assert set(features) == {
        "Zugspitze",
        "Knorrhütte",
        "Höllentorkopf",
        "Kreuzeckbahn Bergstation",
    }

    zug = features["Zugspitze"]
    assert zug["geometry"] == {"type": "Point", "coordinates": [10.9863, 47.4211]}
    assert zug["properties"]["type"] == "peak"
    # One Place (r1) references the Zugspitze POI.
    assert zug["properties"]["n_entries"] == 1
