import json

from pipeline import plan


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
    # every Entry's prose is extracted, Places (r8) and Routes (r7) alike.
    r7 = batches[2]["entries"][0]
    assert set(r7) == {"entry_id", "kind", "name", "description"}
    assert r7["kind"] == "route"
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
