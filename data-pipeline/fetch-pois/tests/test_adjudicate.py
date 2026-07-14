import json

import pytest

from pipeline import plan
from test_match import load_jsonl, mention, rerun_match, run_pipeline, write_part

# A renamed hut, the adjudicator's home turf: the 1996 book says
# 'Meilerhaus', today's OSM 'Meilerhütte' — fuzzy 72.7, far below the
# cascade's 90 cutoff but above the shortlist floor. 'Meilerkopf' is a
# lower-scoring decoy so shortlists carry more than one candidate.
ADJ_GAZETTEER = [
    {
        "name": "Meilerhütte",
        "type": "hut",
        "lat": 47.44,
        "lon": 11.15,
        "ele": 2366.0,
        "osm": "node/8001",
    },
    {
        "name": "Meilerkopf",
        "type": "peak",
        "lat": 47.45,
        "lon": 11.16,
        "ele": 2120.0,
        "osm": "node/8002",
    },
]


def write_adj_part(cfg):
    write_part(cfg, "r7", mention("Meilerhaus", type="hut"))


def run_adj_pipeline(cfg):
    write_adj_part(cfg)
    return run_pipeline(cfg, extra=ADJ_GAZETTEER)


def queued_cases(cfg):
    return load_jsonl(cfg.adjudication_queue)


def write_verdict(
    cfg, case_id, pick, reason="1996 'Meilerhaus' is today's Meilerhütte."
):
    cfg.verdicts_dir.mkdir(parents=True, exist_ok=True)
    (cfg.verdicts_dir / f"{case_id}.json").write_text(
        json.dumps(
            {"case_id": case_id, "pick": pick, "reason": reason}, ensure_ascii=False
        ),
        encoding="utf-8",
    )


def review_case(cfg, entry_id="r7"):
    return next(c for c in load_jsonl(cfg.review) if c["entry_id"] == entry_id)


def override(cfg, decision, entry_id="r7"):
    """Hand-edit review.jsonl the way a reviewer overrides an LLM verdict:
    fill in the decision, leave the recorded verdict untouched."""
    cases = load_jsonl(cfg.review)
    next(c for c in cases if c["entry_id"] == entry_id)["decision"] = decision
    cfg.review.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases),
        encoding="utf-8",
    )


def test_leftovers_are_queued_with_shortlists(cfg):
    run_adj_pipeline(cfg)

    # The leftover has candidates below the fuzzy cutoff -> one open
    # adjudication case with an unguarded, score-ranked shortlist.
    cases = queued_cases(cfg)
    assert len(cases) == 1
    case = cases[0]
    assert case["mention"] == "Meilerhaus"
    assert case["name"] == "Meilerhaus"
    assert case["type"] == "hut"
    assert case["entry_id"] == "r7"
    assert case["kind"] == "mention"
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
    unmatched = {u["name"] for u in load_jsonl(cfg.unmatched)}
    assert "Meilerhaus" in unmatched
    assert all(c["entry_id"] != "r7" for c in load_jsonl(cfg.review))
    funnel = json.loads(cfg.funnel.read_text(encoding="utf-8"))
    assert funnel["types"]["hut"] == {
        "mentions": 1,
        "exact": 0,
        "fuzzy": 0,
        "llm": 0,
        "review": 0,
        "tie": 0,
        "skipped": 0,
        "unmatched": 1,
    }

    # Leftovers without any shortlist candidate (r6's 'Unbekanntspitze' Place)
    # are plain unmatched — nothing worth judging, never queued.
    assert all(c["entry_id"] != "r6" for c in cases)


def test_plan_adjudicate_batches_with_entry_context_and_resumes(cfg, capsys):
    run_adj_pipeline(cfg)
    [case] = queued_cases(cfg)

    capsys.readouterr()  # drop the matcher output
    plan._plan_adjudicate(cfg, 10)
    out = capsys.readouterr()
    batches = [json.loads(line) for line in out.out.splitlines()]
    assert [b["batch"] for b in batches] == [1]
    [planned] = batches[0]["cases"]
    # The queue record verbatim, plus the entry context the subagent needs —
    # including the route's resolved Destination (its parent Place + that Place's
    # POI) as a geographic prior. r7 is filed under r4 'Höllentorkopf', which
    # resolves exactly to the OSM peak at 2150 m.
    assert planned == {
        **case,
        "entry": {
            "name": "Übergang zum Höllentorkopf",
            "kind": "route",
            "peak": None,
            "destination": {
                "name": "Höllentorkopf",
                "poi": {
                    "name": "Höllentorkopf",
                    "type": "peak",
                    "ele": 2150.0,
                    "lat": 47.44,
                    "lon": 11.05,
                },
            },
            "description": "...",
        },
    }
    assert "1 remaining in 1 batches" in out.err

    # A verdict file marks the case done: it never reappears.
    write_verdict(cfg, case["case_id"], "node/8001")
    capsys.readouterr()
    plan._plan_adjudicate(cfg, 10)
    out = capsys.readouterr()
    assert out.out == ""
    assert "nothing to do" in out.err


def test_pick_enters_registry_with_llm_provenance(cfg, capsys):
    run_adj_pipeline(cfg)
    [case] = queued_cases(cfg)
    write_verdict(cfg, case["case_id"], "node/8001")

    rerun_match(cfg)
    stderr = capsys.readouterr().err

    # The pick is in the registry, LLM-tagged with score and reason ...
    pois = {p["name"]: p for p in load_jsonl(cfg.pois_jsonl)}
    assert pois["Meilerhütte"]["osm"] == "node/8001"
    assert pois["Meilerhütte"]["match"] == {
        "method": "llm",
        "score": 72.7,
        "reason": "1996 'Meilerhaus' is today's Meilerhütte.",
    }
    assert pois["Meilerhütte"]["aliases"] == ["Meilerhaus"]

    # ... linked to the entry (mention link) and exported to the GeoJSON ...
    links = load_jsonl(cfg.entry_pois_jsonl)
    link = next(ln for ln in links if ln["poi_id"] == pois["Meilerhütte"]["poi_id"])
    assert link == {
        "entry_id": "r7",
        "poi_id": pois["Meilerhütte"]["poi_id"],
        "surface": "Meilerhaus",
    }
    geojson = json.loads(cfg.pois_geojson.read_text(encoding="utf-8"))
    assert "Meilerhütte" in {f["properties"]["name"] for f in geojson["features"]}

    # ... counted under the funnel's llm column, no longer unmatched/queued.
    funnel = json.loads(cfg.funnel.read_text(encoding="utf-8"))
    assert funnel["types"]["hut"]["llm"] == 1
    assert funnel["types"]["hut"]["unmatched"] == 0
    assert "llm: 1" in stderr
    assert queued_cases(cfg) == []
    assert all(u["entry_id"] != "r7" for u in load_jsonl(cfg.unmatched))

    # The verdict is on the audit record: a review case with the shortlist,
    # the verdict, and an open decision a human may still override.
    case = review_case(cfg)
    assert case["source"] == "llm"
    assert case["verdict"] == {
        "pick": "node/8001",
        "reason": "1996 'Meilerhaus' is today's Meilerhütte.",
    }
    assert case["decision"] is None
    assert [c["osm"] for c in case["candidates"]] == ["node/8001", "node/8002"]

    # Resumable: further reruns consume the same verdict, ask nothing again.
    rerun_match(cfg)
    assert queued_cases(cfg) == []
    assert review_case(cfg) == case


def test_no_match_lands_in_unmatched_with_reason(cfg):
    run_adj_pipeline(cfg)
    [case] = queued_cases(cfg)
    write_verdict(
        cfg,
        case["case_id"],
        None,
        reason="No candidate is this place: both are 3+ km from the route.",
    )

    rerun_match(cfg)

    # Unmatched, with the adjudicator's reason preserved; never registered.
    unmatched = next(u for u in load_jsonl(cfg.unmatched) if u["entry_id"] == "r7")
    assert unmatched == {
        "entry_id": "r7",
        "mention": "Meilerhaus",
        "name": "Meilerhaus",
        "type": "hut",
        "kind": "mention",
        "elevation_m": None,
        "llm_reason": "No candidate is this place: both are 3+ km from the route.",
    }
    assert "Meilerhütte" not in {p["name"] for p in load_jsonl(cfg.pois_jsonl)}

    # The verdict is auditable in review.jsonl and the case is settled: not
    # queued again, funnel still counts the mention as unmatched.
    case = review_case(cfg)
    assert case["verdict"]["pick"] is None
    assert case["decision"] is None
    assert queued_cases(cfg) == []
    funnel = json.loads(cfg.funnel.read_text(encoding="utf-8"))
    assert funnel["types"]["hut"] == {
        "mentions": 1,
        "exact": 0,
        "fuzzy": 0,
        "llm": 0,
        "review": 0,
        "tie": 0,
        "skipped": 0,
        "unmatched": 1,
    }


def test_override_beats_verdict_and_persists(cfg):
    # The LLM declared no-match; the human disagrees and accepts node/8001.
    run_adj_pipeline(cfg)
    [case] = queued_cases(cfg)
    write_verdict(cfg, case["case_id"], None, reason="Not confident.")
    rerun_match(cfg)
    override(cfg, "node/8001")

    rerun_match(cfg)

    # The override wins: registry with review provenance, not llm.
    pois = {p["name"]: p for p in load_jsonl(cfg.pois_jsonl)}
    assert pois["Meilerhütte"]["osm"] == "node/8001"
    assert pois["Meilerhütte"]["match"] == {"method": "review"}
    funnel = json.loads(cfg.funnel.read_text(encoding="utf-8"))
    assert funnel["types"]["hut"]["review"] == 1
    assert funnel["types"]["hut"]["llm"] == 0

    # The case keeps both the verdict (audit trail) and the decision, and the
    # override persists across further reruns.
    for _ in range(2):
        case = review_case(cfg)
        assert case["decision"] == "node/8001"
        assert case["verdict"] == {"pick": None, "reason": "Not confident."}
        rerun_match(cfg)


def test_override_skip_beats_pick(cfg):
    # The LLM picked a candidate; the human overrides with "skip".
    run_adj_pipeline(cfg)
    [case] = queued_cases(cfg)
    write_verdict(cfg, case["case_id"], "node/8001")
    rerun_match(cfg)
    override(cfg, "skip")
    rerun_match(cfg)

    # The pick is out of the registry; the mention is a human skip.
    assert "Meilerhütte" not in {p["name"] for p in load_jsonl(cfg.pois_jsonl)}
    unmatched = next(u for u in load_jsonl(cfg.unmatched) if u["entry_id"] == "r7")
    assert unmatched["skipped_by"] == "review"
    funnel = json.loads(cfg.funnel.read_text(encoding="utf-8"))
    assert funnel["types"]["hut"]["skipped"] == 1
    assert funnel["types"]["hut"]["llm"] == 0


def test_invalid_override_fails_loudly(cfg):
    # The same typo guard as tie decisions: an override that names neither
    # "skip" nor one of the case's candidates aborts the run.
    run_adj_pipeline(cfg)
    [case] = queued_cases(cfg)
    write_verdict(cfg, case["case_id"], "node/8001")
    rerun_match(cfg)
    override(cfg, "node/99999")

    with pytest.raises(SystemExit) as excinfo:
        rerun_match(cfg)
    msg = str(excinfo.value)
    for needle in ("node/99999", "Meilerhaus", "r7", "node/8001", "node/8002"):
        assert needle in msg


def test_llm_provenance_ranks_below_cascade(cfg):
    # r1's Übersicht mentions the Meilerhütte by its OSM name (exact); r7's
    # 'Meilerhaus' is LLM-picked onto the same POI. The deterministic match
    # keeps the provenance; the verdict stays auditable in review.jsonl.
    write_part(cfg, "r1", mention("Meilerhütte", type="hut"))
    run_adj_pipeline(cfg)
    [case] = queued_cases(cfg)
    write_verdict(cfg, case["case_id"], "node/8001")
    rerun_match(cfg)

    pois = {p["name"]: p for p in load_jsonl(cfg.pois_jsonl)}
    assert pois["Meilerhütte"]["match"] == {"method": "exact"}
    assert pois["Meilerhütte"]["aliases"] == ["Meilerhaus"]
    links = load_jsonl(cfg.entry_pois_jsonl)
    assert {
        ln["entry_id"] for ln in links if ln["poi_id"] == pois["Meilerhütte"]["poi_id"]
    } == {"r1", "r7"}
    assert review_case(cfg)["verdict"]["pick"] == "node/8001"


def test_hallucinated_pick_is_ignored_with_note(cfg):
    # A pick that is not one of the case's candidates never enters the
    # registry: the mention stays unmatched and the case carries a note
    # saying how to re-adjudicate.
    run_adj_pipeline(cfg)
    [case] = queued_cases(cfg)
    write_verdict(cfg, case["case_id"], "node/424242")
    rerun_match(cfg)

    assert "Meilerhütte" not in {p["name"] for p in load_jsonl(cfg.pois_jsonl)}
    assert any(u["entry_id"] == "r7" for u in load_jsonl(cfg.unmatched))
    case = review_case(cfg)
    assert "node/424242" in case["note"]
    assert "re-adjudicate" in case["note"]


def test_malformed_verdict_fails_loudly(cfg):
    run_adj_pipeline(cfg)
    [case] = queued_cases(cfg)
    cfg.verdicts_dir.mkdir(parents=True, exist_ok=True)
    # A verdict without a reason is a malformed subagent write.
    (cfg.verdicts_dir / f"{case['case_id']}.json").write_text(
        json.dumps({"case_id": case["case_id"], "pick": "node/8001"}), encoding="utf-8"
    )

    with pytest.raises(SystemExit) as excinfo:
        rerun_match(cfg)
    msg = str(excinfo.value)
    assert case["case_id"] in msg
    assert "reason" in msg


def test_verdict_case_id_mismatch_fails_loudly(cfg):
    # A correct verdict written to the wrong file name is caught, not left as
    # a silent orphan while the case stays queued.
    run_adj_pipeline(cfg)
    [case] = queued_cases(cfg)
    cfg.verdicts_dir.mkdir(parents=True, exist_ok=True)
    (cfg.verdicts_dir / "wrong-name.json").write_text(
        json.dumps({"case_id": case["case_id"], "pick": "node/8001", "reason": "x."}),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        rerun_match(cfg)
    msg = str(excinfo.value)
    assert "wrong-name" in msg and case["case_id"] in msg
