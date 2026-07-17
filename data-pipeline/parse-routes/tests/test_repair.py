"""Tests for the deterministic halves of the anchor-repair pass (#113): planning
from the unsliced report and applying corrected anchors back to the part files.
The LLM `anchor-repairer` subagent itself is exempt (data-pipeline/CLAUDE.md)."""

import json

from pipeline.repair import (
    REPAIRABLE,
    AnchorRepair,
    apply_repairs,
    plan_repair,
)


def write_unsliced(cfg, records):
    cfg.struct_dir.mkdir(parents=True, exist_ok=True)
    with cfg.unsliced_report.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_part(cfg, page, entries):
    cfg.struct_parts.mkdir(parents=True, exist_ok=True)
    (cfg.struct_parts / f"page_{page:04d}.json").write_text(
        json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8"
    )


def read_part(cfg, page):
    data = json.loads(
        (cfg.struct_parts / f"page_{page:04d}.json").read_text(encoding="utf-8")
    )
    return data["entries"]


def write_repair(cfg, entry_id, **fields):
    cfg.repairs_dir.mkdir(parents=True, exist_ok=True)
    (cfg.repairs_dir / f"{entry_id}.json").write_text(
        json.dumps({"entry_id": entry_id, **fields}, ensure_ascii=False),
        encoding="utf-8",
    )


# --- plan_repair -------------------------------------------------------------


def test_plan_repair_keeps_only_repairable_buckets(cfg):
    # empty_anchor (→ re-extraction, #112) and stub (→ provenance, #114) are NOT
    # repairable; the three fidelity buckets are.
    write_unsliced(
        cfg,
        [
            {
                "id": "R1",
                "source_page": 15,
                "name": "A",
                "kind": "place",
                "reason": "end_mismatch",
            },
            {
                "id": "R2",
                "source_page": 15,
                "name": "B",
                "kind": "route",
                "reason": "start_not_found",
            },
            {
                "id": "R3",
                "source_page": 15,
                "name": "C",
                "kind": "route",
                "reason": "start_ambiguous",
            },
            {
                "id": "R4",
                "source_page": 15,
                "name": "D",
                "kind": "place",
                "reason": "empty_anchor",
            },
            {
                "id": "R5",
                "source_page": 15,
                "name": "E",
                "kind": "route",
                "reason": "stub",
            },
        ],
    )
    write_part(
        cfg,
        15,
        [
            {
                "kind": "place",
                "name": "A",
                "start_quote": "A start",
                "end_quote": "A broken",
            },
            {
                "kind": "route",
                "name": "B",
                "start_quote": "B broken",
                "end_quote": "B end",
            },
            {"kind": "route", "name": "C", "start_quote": "C", "end_quote": "C end"},
            {"kind": "place", "name": "D"},
            {"kind": "route", "name": "E", "start_quote": "E", "end_quote": "E"},
        ],
    )

    tasks = plan_repair(cfg)

    assert {t.entry_id for t in tasks} == {"R1", "R2", "R3"}
    assert all(t.reason in REPAIRABLE for t in tasks)
    # The current (broken) anchors are read from the part file for the subagent.
    a = next(t for t in tasks if t.entry_id == "R1")
    assert a.start_quote == "A start" and a.end_quote == "A broken"
    assert a.stem == "page_0015"


def test_plan_repair_empty_when_no_report(cfg):
    assert plan_repair(cfg) == []


# --- apply_repairs -----------------------------------------------------------


def test_apply_repairs_writes_corrected_anchors_back(cfg):
    write_part(
        cfg,
        15,
        [
            {
                "kind": "place",
                "name": "Falzturntal",
                "start_quote": "Falzturntal, 1090 m",
                "end_quote": "broken tail",
            },
            {"kind": "route", "name": "Andere", "start_quote": "x", "end_quote": "y"},
        ],
    )
    write_repair(
        cfg,
        "R1",
        source_page=15,
        name="Falzturntal",
        start_quote="Falzturntal, 1090 m",
        end_quote="hinab ins Tal.",
    )

    result = apply_repairs(cfg)

    assert result.applied == ["R1"]
    assert result.skipped == []
    entries = read_part(cfg, 15)
    fixed = next(e for e in entries if e["name"] == "Falzturntal")
    assert fixed["end_quote"] == "hinab ins Tal."
    # An untouched entry keeps its anchors.
    assert next(e for e in entries if e["name"] == "Andere")["end_quote"] == "y"


def test_apply_repairs_skips_ambiguous_name_never_guesses(cfg):
    # Two entries share a name on the page → the repair can't be placed
    # unambiguously, so it is skipped and surfaced, never guessed onto the first.
    write_part(
        cfg,
        15,
        [
            {"kind": "route", "name": "Dup", "start_quote": "a", "end_quote": "b"},
            {"kind": "route", "name": "Dup", "start_quote": "c", "end_quote": "d"},
        ],
    )
    write_repair(
        cfg, "R1", source_page=15, name="Dup", start_quote="new", end_quote="new end"
    )

    result = apply_repairs(cfg)

    assert result.applied == []
    assert result.skipped == ["R1"]
    # Neither part entry was mutated.
    assert [e["end_quote"] for e in read_part(cfg, 15)] == ["b", "d"]


def test_apply_repairs_skips_when_part_file_missing(cfg):
    write_repair(
        cfg, "R1", source_page=99, name="Ghost", start_quote="x", end_quote="y"
    )
    result = apply_repairs(cfg)
    assert result.applied == []
    assert result.skipped == ["R1"]


def test_anchor_repair_from_dict_defaults():
    r = AnchorRepair.from_dict({"entry_id": "R1", "source_page": "15", "name": "A"})
    assert r.source_page == 15
    assert r.start_quote is None
