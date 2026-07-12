import json

from pipeline import plan


def run_plan(cfg, capsys, batch=3):
    plan._plan_extract(cfg, batch)
    out = capsys.readouterr()
    return [json.loads(line) for line in out.out.splitlines()], out.err


def mark_done(cfg, *route_ids):
    cfg.mention_parts.mkdir(parents=True, exist_ok=True)
    for rid in route_ids:
        (cfg.mention_parts / f"{rid}.json").write_text(
            json.dumps({"route_id": rid, "mentions": []}), encoding="utf-8"
        )


def test_batches_sorted_routes(cfg, capsys):
    batches, stderr = run_plan(cfg, capsys)

    # 9 fixture routes, batch size 3 -> 3 batches, sorted by route_id.
    assert [b["batch"] for b in batches] == [1, 2, 3]
    ids = [[r["route_id"] for r in b["routes"]] for b in batches]
    assert ids == [["r1", "r2", "r3"], ["r4", "r5", "r6"], ["r7", "r8", "r9"]]

    # Each route carries what the extractor subagent needs, nothing more.
    r7 = batches[2]["routes"][0]
    assert set(r7) == {"route_id", "peak", "description"}
    assert r7["peak"] is None  # routes without an anchor still get extracted

    assert "9 remaining in 3 batches" in stderr


def test_resume_skips_completed_and_keeps_batch_numbers(cfg, capsys):
    # Batch 1 fully done, batch 2 partially done (interrupted mid-batch).
    mark_done(cfg, "r1", "r2", "r3", "r4")

    batches, stderr = run_plan(cfg, capsys)

    # Batch 1 is gone; batch 2 reappears under its stable number with only
    # its missing routes; batch 3 is untouched.
    assert [b["batch"] for b in batches] == [2, 3]
    assert [r["route_id"] for r in batches[0]["routes"]] == ["r5", "r6"]
    assert [r["route_id"] for r in batches[1]["routes"]] == ["r7", "r8", "r9"]
    assert "4/9 routes extracted" in stderr

    # Batch composition is stable: rerunning yields the identical plan.
    assert run_plan(cfg, capsys) == (batches, stderr)


def test_nothing_to_do(cfg, capsys):
    mark_done(cfg, "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9")

    batches, stderr = run_plan(cfg, capsys)

    assert batches == []
    assert "nothing to do" in stderr
