import json

from pipeline import plan


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )


def run_plan(cfg, capsys, batch=3):
    plan._plan_extract(cfg, batch)
    out = capsys.readouterr()
    return [json.loads(line) for line in out.out.splitlines()], out.err


def mark_done(cfg, *entry_ids):
    cfg.mention_parts.mkdir(parents=True, exist_ok=True)
    for eid in entry_ids:
        (cfg.mention_parts / f"{eid}.json").write_text(
            json.dumps({"entry_id": eid, "mentions": []}), encoding="utf-8"
        )


def test_batches_sorted_entries(cfg, capsys):
    batches, stderr = run_plan(cfg, capsys)

    # 9 fixture entries, batch size 3 -> 3 batches, sorted by entry id.
    assert [b["batch"] for b in batches] == [1, 2, 3]
    ids = [[e["entry_id"] for e in b["entries"]] for b in batches]
    assert ids == [["r1", "r2", "r3"], ["r4", "r5", "r6"], ["r7", "r8", "r9"]]

    # Each entry carries what the extractor subagent needs, nothing more —
    # every Entry's prose is extracted, Places (r8) and Routes (r7) alike. The
    # bulk `description` never travels through the plan (#90): the descriptor
    # carries a `source` path to the entry's on-disk file, which the extractor
    # Reads itself.
    r7 = batches[2]["entries"][0]
    assert set(r7) == {"entry_id", "kind", "name", "source"}
    assert "description" not in r7
    assert r7["kind"] == "route"
    assert r7["source"] == str(cfg.parse_routes_entries_dir / "r7.json")
    r8 = batches[2]["entries"][1]
    assert r8["kind"] == "place"

    assert "9 remaining in 3 batches" in stderr


def test_resume_skips_completed_and_keeps_batch_numbers(cfg, capsys):
    # Batch 1 fully done, batch 2 partially done (interrupted mid-batch).
    mark_done(cfg, "r1", "r2", "r3", "r4")

    batches, stderr = run_plan(cfg, capsys)

    # Batch 1 is gone; batch 2 reappears under its stable number with only
    # its missing entries; batch 3 is untouched.
    assert [b["batch"] for b in batches] == [2, 3]
    assert [e["entry_id"] for e in batches[0]["entries"]] == ["r5", "r6"]
    assert [e["entry_id"] for e in batches[1]["entries"]] == ["r7", "r8", "r9"]
    assert "4/9 entries extracted" in stderr

    # Batch composition is stable: rerunning yields the identical plan.
    assert run_plan(cfg, capsys) == (batches, stderr)


def test_nothing_to_do(cfg, capsys):
    mark_done(cfg, "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9")

    batches, stderr = run_plan(cfg, capsys)

    assert batches == []
    assert "nothing to do" in stderr


# --- plan adjudicate: destination-enriched entry context ----------------------


def adjudicate(cfg, capsys):
    plan._plan_adjudicate(cfg, 10)
    out = capsys.readouterr()
    cases = [c for line in out.out.splitlines() for c in json.loads(line)["cases"]]
    return {c["case_id"]: c for c in cases}


def test_adjudicate_case_carries_resolved_destination(cfg, capsys):
    # The fixture files r2 under its parent Place r1 (Zugspitze), which resolves
    # to a POI in place_pois -> pois; the route's case must carry that
    # Destination (name + a compact POI projection) as a geographic prior.
    write_jsonl(
        cfg.pois_jsonl,
        [
            {
                "poi_id": "osm-node-1",
                "name": "Zugspitze",
                "type": "peak",
                "ele": 2962.0,
                "lat": 47.42,
                "lon": 10.98,
                "osm": "node/1",
            }
        ],
    )
    write_jsonl(cfg.place_pois_jsonl, [{"place_id": "r1", "poi_id": "osm-node-1"}])
    write_jsonl(
        cfg.adjudication_queue,
        [{"case_id": "c-route", "entry_id": "r2", "mention": "x", "candidates": []}],
    )

    cases = adjudicate(cfg, capsys)

    assert cases["c-route"]["entry"]["destination"] == {
        "name": "Zugspitze",
        "poi": {
            "name": "Zugspitze",
            "type": "peak",
            "ele": 2962.0,
            "lat": 47.42,
            "lon": 10.98,
        },
    }


def test_adjudicate_destination_with_no_poi_is_null(cfg, capsys):
    # r7 is filed under r4 (Höllentorkopf), but no place_pois link resolves it:
    # the Destination is still named, its POI honestly null.
    write_jsonl(
        cfg.adjudication_queue,
        [{"case_id": "c-nopoi", "entry_id": "r7", "mention": "x", "candidates": []}],
    )

    cases = adjudicate(cfg, capsys)

    assert cases["c-nopoi"]["entry"]["destination"] == {
        "name": "Höllentorkopf",
        "poi": None,
    }


def test_adjudicate_place_owned_case_has_null_destination(cfg, capsys):
    # A case owned by a Place (r1) has no Destination — only Routes do.
    write_jsonl(
        cfg.adjudication_queue,
        [{"case_id": "c-place", "entry_id": "r1", "mention": "x", "candidates": []}],
    )

    cases = adjudicate(cfg, capsys)

    assert cases["c-place"]["entry"]["kind"] == "place"
    assert cases["c-place"]["entry"]["destination"] is None
