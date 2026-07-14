"""The audit gate (#7) is deterministic, offline logic, so it gets unit tests:
the cell/excerpt/elevation helpers, the seeded oversampling sample, the
per-match method recompute (proven against the matcher's own funnel), and the
rendered tables. Scenarios reuse the matcher's fixtures via the shared helpers
in test_match / test_adjudicate."""

from __future__ import annotations

import json

import pytest

from pipeline import audit
from pipeline.audit import Row
from pipeline.match import (
    build_index,
    classify_method,
    entry_items,
    load_decisions,
    load_verdicts,
)
from test_adjudicate import run_adj_pipeline, write_verdict
from test_match import (
    load_jsonl,
    mention,
    rerun_match,
    run_pipeline,
    write_cascade_parts,
    write_part,
)

FUNNEL_COLS = (
    "mentions",
    "exact",
    "fuzzy",
    "llm",
    "review",
    "tie",
    "skipped",
    "unmatched",
)


# --- pure helpers ----------------------------------------------------------


def test_cell_collapses_whitespace_and_escapes_pipes():
    assert audit._cell("a | b\nc") == "a \\| b c"
    assert audit._cell("  spaced   out ") == "spaced out"
    assert audit._cell("back\\slash") == "back\\\\slash"
    assert audit._cell("   ") == "—"  # empty after normalization


def test_elev_delta_is_signed_book_minus_osm():
    assert audit._elev_delta(2150.0, 2100.0) == "+50 m"
    assert audit._elev_delta(2100.0, 2150.0) == "-50 m"
    assert audit._elev_delta(2100.0, 2100.0) == "+0 m"
    # A silent side is the '—' the matcher's guard also skips.
    assert audit._elev_delta(None, 2100.0) == "—"
    assert audit._elev_delta(2100.0, None) == "—"


def test_excerpt_windows_around_the_mention():
    text = "lead " * 30 + "NEEDLE " + "tail " * 30
    out = audit._excerpt(text, "NEEDLE", 40)
    assert "NEEDLE" in out
    assert out.startswith("…") and out.endswith("…")
    assert len(out) <= 42  # width plus the two ellipses


def test_excerpt_falls_back_to_head_and_is_cell_safe():
    assert audit._excerpt("", None, 40) == "—"
    assert audit._excerpt("line one\nline | two", None, 100) == "line one line \\| two"
    long = "x" * 200
    assert audit._excerpt(long, "absent", 40) == "x" * 40 + "…"


# --- seeded oversampling ---------------------------------------------------


def _rows(prefix: str, method: str, n: int) -> list[Row]:
    return [
        Row(key=(f"{prefix}{i:03d}",), method=method, cells=(f"{prefix}{i}",))
        for i in range(n)
    ]


def test_sample_oversamples_fuzzy_llm_then_fills_with_exact():
    rows = _rows("e", "exact", 40) + _rows("f", "fuzzy", 5) + _rows("l", "llm", 3)
    picked = audit.sample(rows, size=30)

    methods = [r.method for r in picked]
    assert len(picked) == 30
    # Every fuzzy/llm match is carried; exact only fills the remainder.
    assert methods.count("fuzzy") == 5
    assert methods.count("llm") == 3
    assert methods.count("exact") == 22
    # Seeded: the identical sample on a rerun, displayed in stable key order.
    assert audit.sample(rows, size=30) == picked
    assert [r.key for r in picked] == sorted(r.key for r in picked)


def test_sample_drops_exact_entirely_when_fuzzy_llm_overflow():
    rows = _rows("e", "exact", 20) + _rows("f", "fuzzy", 35)
    picked = audit.sample(rows, size=30)
    assert len(picked) == 30
    assert all(r.method == "fuzzy" for r in picked)
    assert audit.sample(rows, size=30) == picked  # reproducible subset


def test_sample_returns_all_when_below_size():
    rows = _rows("e", "exact", 4) + _rows("f", "fuzzy", 2)
    picked = audit.sample(rows, size=30)
    assert len(picked) == 6
    assert [r.key for r in picked] == sorted(r.key for r in picked)


def test_sample_fills_with_review_ahead_of_exact():
    # "Falling back to exact only to fill": with fuzzy/llm exhausting nothing,
    # the fill prefers the adjudicated `review` matches over `exact` ones (#7).
    rows = _rows("e", "exact", 40) + _rows("r", "review", 20) + _rows("f", "fuzzy", 4)
    picked = audit.sample(rows, size=30)
    methods = [r.method for r in picked]
    assert methods.count("fuzzy") == 4  # all fuzzy oversampled
    assert methods.count("review") == 20  # every review before any exact
    assert methods.count("exact") == 6  # exact fills the remainder only


# --- per-match method recompute -------------------------------------------


def _match_context(cfg) -> audit.MatchContext:
    index, keys = build_index(load_jsonl(cfg.gazetteer))
    decisions, _notes = load_decisions(cfg)
    return audit.MatchContext(
        entries={e["id"]: e for e in load_jsonl(cfg.routes_jsonl)},
        pois={p["poi_id"]: p for p in load_jsonl(cfg.pois_jsonl)},
        index=index,
        keys=keys,
        decisions=decisions,
        verdicts=load_verdicts(cfg),
        cfg=cfg,
    )


def _rebuild_funnel_via_classify(cfg) -> dict[str, dict[str, int]]:
    """Recompute the funnel purely from classify_method — the same projection
    the audit's method column uses. Agreement with the matcher's own funnel
    proves the recompute matches match_mentions across every method."""
    ctx = _match_context(cfg)
    funnel: dict[str, dict[str, int]] = {}
    for entry in sorted(load_jsonl(cfg.routes_jsonl), key=lambda e: e["id"]):
        items, _ = entry_items(entry, cfg)
        for item in items:
            method = classify_method(
                item, entry["id"], ctx.index, ctx.keys, ctx.decisions, ctx.verdicts, cfg
            )
            t = "place" if item["kind"] == "place" else item["type"]
            bucket = funnel.setdefault(t, dict.fromkeys(FUNNEL_COLS, 0))
            bucket["mentions"] += 1
            bucket[method] += 1
    return funnel


def _assert_funnel_agrees(cfg):
    matcher = json.loads(cfg.funnel.read_text(encoding="utf-8"))["types"]
    assert _rebuild_funnel_via_classify(cfg) == matcher


def test_recomputed_method_matches_matcher_funnel(cfg):
    # Covers exact, fuzzy, tie, skipped (out-of-scope) and unmatched.
    write_cascade_parts(cfg)
    run_pipeline(cfg)
    _assert_funnel_agrees(cfg)


def test_recomputed_method_agrees_after_a_review_decision(cfg):
    from test_match import decide

    run_pipeline(cfg)
    decide(cfg, "node/1003")  # accept the r5 Wasserfall tie -> review
    rerun_match(cfg)
    _assert_funnel_agrees(cfg)


def test_method_is_per_link_not_pois_best_method(cfg):
    # r1's Übersicht names the hut by its OSM spelling (exact); r7's 1996
    # 'Meilerhaus' is LLM-adjudicated onto the *same* POI. pois.jsonl records
    # only the winning 'exact' provenance — the audit must still show the r7
    # link as 'llm', recomputed per match.
    write_part(cfg, "r1", mention("Meilerhütte", type="hut"))
    run_adj_pipeline(cfg)
    [case] = load_jsonl(cfg.adjudication_queue)
    write_verdict(cfg, case["case_id"], "node/8001")
    rerun_match(cfg)
    _assert_funnel_agrees(cfg)

    ctx = _match_context(cfg)
    rows = audit.build_mention_rows(load_jsonl(cfg.entry_pois_jsonl), ctx)
    by_surface = {r.cells[0]: r for r in rows}

    assert by_surface["Meilerhütte"].method == "exact"
    assert by_surface["Meilerhaus"].method == "llm"
    # The single deduped provenance both links share — what we must NOT trust
    # for the per-link method column: it says 'exact' for the llm link too.
    poi = next(p for p in ctx.pois.values() if p["osm"] == "node/8001")
    assert poi["match"]["method"] == "exact"


# --- artifact guards -------------------------------------------------------


def test_audit_before_match_exits_pointing_at_the_matcher(cfg):
    # The routes index exists (parse-routes ran) but the matcher has not, so
    # the 04_final artifacts are absent: the gate exits honestly, naming the
    # missing artifact and the matcher, rather than rendering an empty picture.
    with pytest.raises(SystemExit) as excinfo:
        audit.run_audit(cfg)
    msg = str(excinfo.value)
    assert "run the matcher first" in msg
    assert str(cfg.pois_jsonl) in msg


# --- rendered tables -------------------------------------------------------


def test_run_audit_renders_both_tables_with_five_columns(cfg, capsys):
    write_cascade_parts(cfg)
    run_pipeline(cfg)
    capsys.readouterr()  # drop the matcher summary

    out = audit.run_audit(cfg)
    captured = capsys.readouterr()

    # Returned text is exactly what went to stdout.
    assert captured.out.rstrip("\n") == out

    assert "## Place → POI matches" in out
    assert "## Entry mentions → POI" in out
    assert (
        "| Place (book elev.) | Übersicht excerpt | OSM name | Δ elev. | method |"
        in out
    )
    assert "| Mention | Prose context | OSM name | Δ elev. | method |" in out
    assert "| --- | --- | --- | --- | --- |" in out

    # A known exact Place match: 'Zugspitze, 2962 m' resolves to OSM Zugspitze.
    place_line = next(ln for ln in out.splitlines() if ln.startswith("| Zugspitze, "))
    cells = [c.strip() for c in place_line.strip("|").split("|")]
    assert cells[0] == "Zugspitze, 2962 m"
    assert cells[2] == "Zugspitze"
    assert cells[4] == "exact"

    # A known fuzzy mention: 'Predigtstain' (r7) -> OSM Predigtstein.
    mention_line = next(
        ln for ln in out.splitlines() if ln.startswith("| Predigtstain ")
    )
    mcells = [c.strip() for c in mention_line.strip("|").split("|")]
    assert mcells[2] == "Predigtstein"
    assert mcells[4] == "fuzzy"

    # Honest picture: what is not in the tables is surfaced on stderr.
    assert "without a match" in captured.err
    assert str(cfg.unmatched) in captured.err


def test_run_audit_is_byte_identical_on_rerun(cfg, capsys):
    write_cascade_parts(cfg)
    run_pipeline(cfg)
    capsys.readouterr()

    first = audit.run_audit(cfg)
    capsys.readouterr()
    second = audit.run_audit(cfg)
    capsys.readouterr()
    assert first == second


def test_empty_link_tables_render_headers_only(cfg, capsys):
    # A guide whose matcher produced no links still audits cleanly: header
    # rows, no data rows, and a summary that owns up to the misses.
    run_pipeline(cfg)  # no mention parts -> entry_pois is empty
    capsys.readouterr()

    out = audit.run_audit(cfg)
    captured = capsys.readouterr()
    mention_section = out.split("## Entry mentions → POI")[1]
    # header + separator only, no data row.
    assert mention_section.count("\n|") == 2
    assert "mention links: 0 matched" in captured.err
