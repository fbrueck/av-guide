import json

from conftest import FIXTURES, run_stage

ROUTES = FIXTURES / "routes.jsonl"


def run_plan(data_dir, batch=3):
    result = run_stage("plan", data_dir, routes=ROUTES, args=["extract", "--batch", str(batch)])
    assert result.returncode == 0, result.stderr
    return [json.loads(line) for line in result.stdout.splitlines()], result.stderr


def mark_done(data_dir, *route_ids):
    parts = data_dir / "02_mentions" / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    for rid in route_ids:
        (parts / f"{rid}.json").write_text(
            json.dumps({"route_id": rid, "mentions": []}), encoding="utf-8"
        )


def test_batches_sorted_routes(data_dir):
    batches, stderr = run_plan(data_dir)

    # 9 fixture routes, batch size 3 -> 3 batches, sorted by route_id.
    assert [b["batch"] for b in batches] == [1, 2, 3]
    ids = [[r["route_id"] for r in b["routes"]] for b in batches]
    assert ids == [["r1", "r2", "r3"], ["r4", "r5", "r6"], ["r7", "r8", "r9"]]

    # Each route carries what the extractor subagent needs, nothing more.
    r7 = batches[2]["routes"][0]
    assert set(r7) == {"route_id", "peak", "description"}
    assert r7["peak"] is None  # routes without an anchor still get extracted

    assert "9 remaining in 3 batches" in stderr


def test_resume_skips_completed_and_keeps_batch_numbers(data_dir):
    # Batch 1 fully done, batch 2 partially done (interrupted mid-batch).
    mark_done(data_dir, "r1", "r2", "r3", "r4")

    batches, stderr = run_plan(data_dir)

    # Batch 1 is gone; batch 2 reappears under its stable number with only
    # its missing routes; batch 3 is untouched.
    assert [b["batch"] for b in batches] == [2, 3]
    assert [r["route_id"] for r in batches[0]["routes"]] == ["r5", "r6"]
    assert [r["route_id"] for r in batches[1]["routes"]] == ["r7", "r8", "r9"]
    assert "4/9 routes extracted" in stderr

    # Batch composition is stable: rerunning yields the identical plan.
    assert run_plan(data_dir) == (batches, stderr)


def test_nothing_to_do(data_dir):
    mark_done(data_dir, "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9")

    batches, stderr = run_plan(data_dir)

    assert batches == []
    assert "nothing to do" in stderr
