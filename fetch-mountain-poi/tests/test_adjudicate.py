import json

from conftest import FIXTURES, run_stage
from test_match import load_jsonl, mention, rerun_match, run_pipeline, write_part

# A renamed hut, the adjudicator's home turf: the 1996 book says
# 'Meilerhaus', today's OSM 'Meilerhütte' — fuzzy 72.7, far below the
# cascade's 90 cutoff but above the shortlist floor. 'Meilerkopf' is a
# lower-scoring decoy so shortlists carry more than one candidate.
ADJ_GAZETTEER = [
    {"name": "Meilerhütte", "type": "hut", "lat": 47.44, "lon": 11.15,
     "ele": 2366.0, "osm": "node/8001"},
    {"name": "Meilerkopf", "type": "peak", "lat": 47.45, "lon": 11.16,
     "ele": 2120.0, "osm": "node/8002"},
]


def write_adj_part(data_dir):
    write_part(data_dir, "r7", mention("Meilerhaus", type="hut"))


def run_adj_pipeline(data_dir):
    write_adj_part(data_dir)
    return run_pipeline(data_dir, extra=ADJ_GAZETTEER)


def queued_cases(data_dir):
    return load_jsonl(data_dir / "03_matched" / "adjudication_queue.jsonl")


def write_verdict(data_dir, case_id, pick, reason="1996 'Meilerhaus' is today's Meilerhütte."):
    verdicts = data_dir / "03_matched" / "verdicts"
    verdicts.mkdir(parents=True, exist_ok=True)
    (verdicts / f"{case_id}.json").write_text(
        json.dumps({"case_id": case_id, "pick": pick, "reason": reason}, ensure_ascii=False),
        encoding="utf-8",
    )


def review_case(data_dir, route_id="r7"):
    return next(c for c in load_jsonl(data_dir / "03_matched" / "review.jsonl")
                if c["route_id"] == route_id)


def override(data_dir, decision, route_id="r7"):
    """Hand-edit review.jsonl the way a reviewer overrides an LLM verdict:
    fill in the decision, leave the recorded verdict untouched."""
    path = data_dir / "03_matched" / "review.jsonl"
    cases = load_jsonl(path)
    next(c for c in cases if c["route_id"] == route_id)["decision"] = decision
    path.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases),
        encoding="utf-8",
    )


def test_leftovers_are_queued_with_shortlists(data_dir):
    run_adj_pipeline(data_dir)

    # The leftover has candidates below the fuzzy cutoff -> one open
    # adjudication case with an unguarded, score-ranked shortlist.
    cases = queued_cases(data_dir)
    assert len(cases) == 1
    case = cases[0]
    assert case["mention"] == "Meilerhaus"
    assert case["name"] == "Meilerhaus"
    assert case["type"] == "hut"
    assert case["route_id"] == "r7"
    assert case["is_anchor"] is False
    assert case["case_id"].startswith("r7__meilerhaus__hut__")
    # Shortlist ranked by score; the type-incompatible decoy is included —
    # judging drift is the adjudicator's job, not the guards'.
    assert [c["osm"] for c in case["candidates"]] == ["node/8001", "node/8002"]
    scores = [c["score"] for c in case["candidates"]]
    assert scores == sorted(scores, reverse=True)
    for c in case["candidates"]:
        assert set(c) == {"osm", "name", "type", "ele", "lat", "lon", "score"}

    # Until adjudicated the mention stays unmatched and is not yet a review
    # case; the funnel counts it as unmatched, nothing under llm.
    unmatched = {u["name"] for u in load_jsonl(data_dir / "03_matched" / "unmatched.jsonl")}
    assert "Meilerhaus" in unmatched
    assert all(c["route_id"] != "r7" for c in load_jsonl(data_dir / "03_matched" / "review.jsonl"))
    funnel = json.loads((data_dir / "03_matched" / "funnel.json").read_text(encoding="utf-8"))
    assert funnel["types"]["hut"] == {"mentions": 1, "exact": 0, "fuzzy": 0, "llm": 0,
                                      "review": 0, "tie": 0, "skipped": 0, "unmatched": 1}

    # Leftovers without any shortlist candidate (r6's 'Unbekanntspitze') are
    # plain unmatched — nothing worth judging, never queued.
    assert all(c["route_id"] != "r6" for c in cases)


def test_plan_adjudicate_batches_with_route_context_and_resumes(data_dir):
    run_adj_pipeline(data_dir)
    [case] = queued_cases(data_dir)

    result = run_stage("plan", data_dir, routes=FIXTURES / "routes.jsonl",
                       args=["adjudicate", "--batch", "10"])
    assert result.returncode == 0, result.stderr
    batches = [json.loads(line) for line in result.stdout.splitlines()]
    assert [b["batch"] for b in batches] == [1]
    [planned] = batches[0]["cases"]
    # The queue record verbatim, plus the route context the subagent needs.
    assert planned == {**case, "route": {"peak": None, "description": "..."}}
    assert "1 remaining in 1 batches" in result.stderr

    # A verdict file marks the case done: it never reappears.
    write_verdict(data_dir, case["case_id"], "node/8001")
    result = run_stage("plan", data_dir, routes=FIXTURES / "routes.jsonl", args=["adjudicate"])
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert "nothing to do" in result.stderr


def test_pick_enters_registry_with_llm_provenance(data_dir):
    run_adj_pipeline(data_dir)
    [case] = queued_cases(data_dir)
    write_verdict(data_dir, case["case_id"], "node/8001")

    result = rerun_match(data_dir)
    assert result.returncode == 0, result.stderr

    # The pick is in the registry, LLM-tagged with score and reason ...
    pois = {p["name"]: p for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}
    assert pois["Meilerhütte"]["osm"] == "node/8001"
    assert pois["Meilerhütte"]["match"] == {
        "method": "llm", "score": 72.7,
        "reason": "1996 'Meilerhaus' is today's Meilerhütte.",
    }
    assert pois["Meilerhütte"]["aliases"] == ["Meilerhaus"]

    # ... linked to the route and exported to the GeoJSON ...
    links = load_jsonl(data_dir / "04_final" / "route_pois.jsonl")
    link = next(l for l in links if l["poi_id"] == pois["Meilerhütte"]["poi_id"])
    assert link == {"route_id": "r7", "poi_id": pois["Meilerhütte"]["poi_id"],
                    "surface": "Meilerhaus", "is_anchor": False}
    geojson = json.loads((data_dir / "04_final" / "pois.geojson").read_text(encoding="utf-8"))
    assert "Meilerhütte" in {f["properties"]["name"] for f in geojson["features"]}

    # ... counted under the funnel's llm column, no longer unmatched/queued.
    funnel = json.loads((data_dir / "03_matched" / "funnel.json").read_text(encoding="utf-8"))
    assert funnel["types"]["hut"]["llm"] == 1
    assert funnel["types"]["hut"]["unmatched"] == 0
    assert "llm: 1" in result.stderr
    assert queued_cases(data_dir) == []
    assert all(u["route_id"] != "r7" for u in load_jsonl(data_dir / "03_matched" / "unmatched.jsonl"))

    # The verdict is on the audit record: a review case with the shortlist,
    # the verdict, and an open decision a human may still override.
    case = review_case(data_dir)
    assert case["source"] == "llm"
    assert case["verdict"] == {"pick": "node/8001",
                               "reason": "1996 'Meilerhaus' is today's Meilerhütte."}
    assert case["decision"] is None
    assert [c["osm"] for c in case["candidates"]] == ["node/8001", "node/8002"]

    # Resumable: further reruns consume the same verdict, ask nothing again.
    assert rerun_match(data_dir).returncode == 0
    assert queued_cases(data_dir) == []
    assert review_case(data_dir) == case


def test_no_match_lands_in_unmatched_with_reason(data_dir):
    run_adj_pipeline(data_dir)
    [case] = queued_cases(data_dir)
    write_verdict(data_dir, case["case_id"], None,
                  reason="No candidate is this place: both are 3+ km from the route.")

    result = rerun_match(data_dir)
    assert result.returncode == 0, result.stderr

    # Unmatched, with the adjudicator's reason preserved; never registered.
    unmatched = next(u for u in load_jsonl(data_dir / "03_matched" / "unmatched.jsonl")
                     if u["route_id"] == "r7")
    assert unmatched == {
        "route_id": "r7", "mention": "Meilerhaus", "name": "Meilerhaus",
        "type": "hut", "is_anchor": False, "elevation_m": None,
        "llm_reason": "No candidate is this place: both are 3+ km from the route.",
    }
    assert "Meilerhütte" not in {p["name"] for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}

    # The verdict is auditable in review.jsonl and the case is settled: not
    # queued again, funnel still counts the mention as unmatched.
    case = review_case(data_dir)
    assert case["verdict"]["pick"] is None
    assert case["decision"] is None
    assert queued_cases(data_dir) == []
    funnel = json.loads((data_dir / "03_matched" / "funnel.json").read_text(encoding="utf-8"))
    assert funnel["types"]["hut"] == {"mentions": 1, "exact": 0, "fuzzy": 0, "llm": 0,
                                      "review": 0, "tie": 0, "skipped": 0, "unmatched": 1}


def test_override_beats_verdict_and_persists(data_dir):
    # The LLM declared no-match; the human disagrees and accepts node/8001.
    run_adj_pipeline(data_dir)
    [case] = queued_cases(data_dir)
    write_verdict(data_dir, case["case_id"], None, reason="Not confident.")
    assert rerun_match(data_dir).returncode == 0
    override(data_dir, "node/8001")

    result = rerun_match(data_dir)
    assert result.returncode == 0, result.stderr

    # The override wins: registry with review provenance, not llm.
    pois = {p["name"]: p for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}
    assert pois["Meilerhütte"]["osm"] == "node/8001"
    assert pois["Meilerhütte"]["match"] == {"method": "review"}
    funnel = json.loads((data_dir / "03_matched" / "funnel.json").read_text(encoding="utf-8"))
    assert funnel["types"]["hut"]["review"] == 1
    assert funnel["types"]["hut"]["llm"] == 0

    # The case keeps both the verdict (audit trail) and the decision, and the
    # override persists across further reruns.
    for _ in range(2):
        case = review_case(data_dir)
        assert case["decision"] == "node/8001"
        assert case["verdict"] == {"pick": None, "reason": "Not confident."}
        assert rerun_match(data_dir).returncode == 0


def test_override_skip_beats_pick(data_dir):
    # The LLM picked a candidate; the human overrides with "skip".
    run_adj_pipeline(data_dir)
    [case] = queued_cases(data_dir)
    write_verdict(data_dir, case["case_id"], "node/8001")
    assert rerun_match(data_dir).returncode == 0
    override(data_dir, "skip")
    assert rerun_match(data_dir).returncode == 0

    # The pick is out of the registry; the mention is a human skip.
    assert "Meilerhütte" not in {p["name"] for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}
    unmatched = next(u for u in load_jsonl(data_dir / "03_matched" / "unmatched.jsonl")
                     if u["route_id"] == "r7")
    assert unmatched["skipped_by"] == "review"
    funnel = json.loads((data_dir / "03_matched" / "funnel.json").read_text(encoding="utf-8"))
    assert funnel["types"]["hut"]["skipped"] == 1
    assert funnel["types"]["hut"]["llm"] == 0


def test_invalid_override_fails_loudly(data_dir):
    # The same typo guard as tie decisions: an override that names neither
    # "skip" nor one of the case's candidates aborts the run.
    run_adj_pipeline(data_dir)
    [case] = queued_cases(data_dir)
    write_verdict(data_dir, case["case_id"], "node/8001")
    assert rerun_match(data_dir).returncode == 0
    override(data_dir, "node/99999")

    result = rerun_match(data_dir)
    assert result.returncode != 0
    for needle in ("node/99999", "Meilerhaus", "r7", "node/8001", "node/8002"):
        assert needle in result.stderr


def test_llm_provenance_ranks_below_cascade(data_dir):
    # r1 mentions the Meilerhütte by its OSM name (exact); r7's 'Meilerhaus'
    # is LLM-picked onto the same POI. The deterministic match keeps the
    # provenance; the verdict stays auditable in review.jsonl.
    write_part(data_dir, "r1", mention("Meilerhütte", type="hut"))
    run_adj_pipeline(data_dir)
    [case] = queued_cases(data_dir)
    write_verdict(data_dir, case["case_id"], "node/8001")
    assert rerun_match(data_dir).returncode == 0

    pois = {p["name"]: p for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}
    assert pois["Meilerhütte"]["match"] == {"method": "exact"}
    assert pois["Meilerhütte"]["aliases"] == ["Meilerhaus"]
    links = load_jsonl(data_dir / "04_final" / "route_pois.jsonl")
    assert {l["route_id"] for l in links if l["poi_id"] == pois["Meilerhütte"]["poi_id"]} == {"r1", "r7"}
    assert review_case(data_dir)["verdict"]["pick"] == "node/8001"


def test_hallucinated_pick_is_ignored_with_note(data_dir):
    # A pick that is not one of the case's candidates never enters the
    # registry: the mention stays unmatched and the case carries a note
    # saying how to re-adjudicate.
    run_adj_pipeline(data_dir)
    [case] = queued_cases(data_dir)
    write_verdict(data_dir, case["case_id"], "node/424242")
    result = rerun_match(data_dir)
    assert result.returncode == 0, result.stderr

    assert "Meilerhütte" not in {p["name"] for p in load_jsonl(data_dir / "04_final" / "pois.jsonl")}
    assert any(u["route_id"] == "r7" for u in load_jsonl(data_dir / "03_matched" / "unmatched.jsonl"))
    case = review_case(data_dir)
    assert "node/424242" in case["note"]
    assert "re-adjudicate" in case["note"]


def test_malformed_verdict_fails_loudly(data_dir):
    run_adj_pipeline(data_dir)
    [case] = queued_cases(data_dir)
    verdicts = data_dir / "03_matched" / "verdicts"
    verdicts.mkdir(parents=True, exist_ok=True)
    # A verdict without a reason is a malformed subagent write.
    (verdicts / f"{case['case_id']}.json").write_text(
        json.dumps({"case_id": case["case_id"], "pick": "node/8001"}), encoding="utf-8"
    )

    result = rerun_match(data_dir)
    assert result.returncode != 0
    assert case["case_id"] in result.stderr
    assert "reason" in result.stderr


def test_verdict_case_id_mismatch_fails_loudly(data_dir):
    # A correct verdict written to the wrong file name is caught, not left as
    # a silent orphan while the case stays queued.
    run_adj_pipeline(data_dir)
    [case] = queued_cases(data_dir)
    verdicts = data_dir / "03_matched" / "verdicts"
    verdicts.mkdir(parents=True, exist_ok=True)
    (verdicts / "wrong-name.json").write_text(
        json.dumps({"case_id": case["case_id"], "pick": "node/8001", "reason": "x."}),
        encoding="utf-8",
    )

    result = rerun_match(data_dir)
    assert result.returncode != 0
    assert "wrong-name" in result.stderr and case["case_id"] in result.stderr
