"""Validation gate: seeded audit tables for operator sign-off (#7).

The matcher's export is not final until the operator has eyeballed match
quality. This prints **two audit tables as GitHub-flavored Markdown to stdout**
so they can be pasted into an issue comment and signed off:

  - **Place -> POI matches** (place_pois.jsonl) — the coordinate pins. Columns:
    Place name + book elevation | Übersicht excerpt | matched OSM name |
    elevation Δ | method.
  - **Entry mentions -> POI** (entry_pois.jsonl) — the waypoints. Columns:
    mention surface form | entry-prose context excerpt | matched OSM name |
    elevation Δ | method.

Each table is a **seeded sample of SAMPLE_SIZE** matches, **oversampling
fuzzy/LLM matches** (where errors hide) and falling back to exact/review only to
fill the sample. The **method column is recomputed per match** by replaying the
matcher's cascade against the item (match.classify_method) — the true per-match
method, not pois.jsonl's deduped best-method (a POI reached by several items
records only its single best method). Places and mentions with no match are not
in the tables — they are surfaced honestly in the stderr summary, which points
at the funnel and unmatched artifact so nothing the operator signs off on is
silently dropped.

The tool is pure and offline (no network, no `gh`): stdout gets the Markdown,
stderr a one-line summary, mirroring `plan funnel`. Re-running it on unchanged
pipeline outputs prints byte-identical tables (seeded sample, sorted rows).

  python -m pipeline.audit --guide <id>
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import GuideConfig, load_guide
from .match import (
    build_index,
    classify_method,
    entry_items,
    load_decisions,
    load_jsonl,
    load_verdicts,
)

# Algorithm behaviour, not per-guide config (like match.py's cutoffs): a fixed
# sample size and seed make the gate reproducible — byte-identical on reruns.
SAMPLE_SIZE = 30
SEED = 0
# Sampling priority (lower = kept first). The two non-deterministic methods
# where errors hide — fuzzy and the LLM adjudicator — are oversampled ahead of
# everything; `review` (a human/LLM-adjudicated tie) is nearly as fallible so
# it outranks the deterministic `exact`, which fills the sample only when the
# rest cannot reach SAMPLE_SIZE ("falling back to exact only to fill", #7).
_FILL_PRIORITY = 2
_METHOD_PRIORITY = {"fuzzy": 0, "llm": 0, "review": 1}

# Excerpt widths (characters) for the prose columns.
UEBERSICHT_WIDTH = 90  # a Place's Übersicht, from the top
CONTEXT_WIDTH = 90  # a window of Route/Übersicht prose around the mention

_MISSING = "—"


@dataclass(frozen=True)
class Row:
    """One audit row: `key` gives a stable sort order, `method` drives
    oversampling, `cells` are the rendered Markdown cells."""

    key: tuple[str, ...]
    method: str
    cells: tuple[str, ...]


@dataclass(frozen=True)
class MatchContext:
    """Everything the row builders and the per-match method recompute read: the
    entries and POIs to join against, plus the matcher's own lookup index and
    decision/verdict state so `classify_method` can replay the cascade. Built
    once in `run_audit` and threaded through both builders as one value."""

    entries: dict[str, dict]
    pois: dict[str, dict]
    index: dict[str, list[dict]]
    keys: list[str]
    decisions: dict[tuple, str]
    verdicts: dict[str, dict]
    cfg: GuideConfig


def _norm_ws(text: str) -> str:
    """Collapse all whitespace (newlines included) to single spaces — a
    Markdown table cell is one line."""
    return " ".join(text.split())


def _esc(text: str) -> str:
    """Escape the characters that would break a Markdown table cell."""
    return text.replace("\\", "\\\\").replace("|", "\\|")


def _cell(text: str) -> str:
    return _esc(_norm_ws(text)) or _MISSING


def _fmt_m(ele: float) -> str:
    return f"{ele:g} m"


def _elev_delta(book: float | None, osm: float | None) -> str:
    """Signed book-minus-OSM elevation gap in meters, or `—` when either side
    is silent (the guard the matcher itself skips)."""
    if book is None or osm is None:
        return _MISSING
    return f"{book - osm:+.0f} m"


def _excerpt(text: str, needle: str | None, width: int) -> str:
    """A one-line, cell-safe excerpt of `text`, at most `width` chars: a window
    centered on `needle` when given and found (so a mention shows in context),
    otherwise the head of the text (a Place's Übersicht)."""
    text = _norm_ws(text)
    if not text:
        return _MISSING
    if needle:
        nl = _norm_ws(needle)
        idx = text.lower().find(nl.lower())
        if idx != -1:
            start = max(0, idx - (width - len(nl)) // 2)
            end = min(len(text), start + width)
            start = max(0, end - width)
            snippet = text[start:end]
            return _esc(
                ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")
            )
    return _esc(text[:width] + ("…" if len(text) > width else ""))


def _warn(message: str) -> None:
    print(f"[audit] warning: {message}", file=sys.stderr)


def _poi_cells(
    poi: dict | None, poi_id: str, book_ele: float | None
) -> tuple[str, str]:
    """The matched-OSM-name and elevation-Δ cells for a resolved POI. A link
    pointing at a POI absent from the registry is pipeline drift — surfaced
    (warn + visible marker), never a silent blank."""
    if poi is None:
        _warn(f"link references POI {poi_id!r} not in the registry")
        return f"(missing POI {poi_id})", _MISSING
    return _cell(poi["name"]), _elev_delta(book_ele, poi.get("ele"))


def _classify(item: dict, eid: str, ctx: MatchContext) -> str:
    return classify_method(
        item, eid, ctx.index, ctx.keys, ctx.decisions, ctx.verdicts, ctx.cfg
    )


def build_place_rows(links: list[dict], ctx: MatchContext) -> list[Row]:
    """One row per Place -> POI match (place_pois.jsonl)."""
    rows: list[Row] = []
    for link in links:
        eid = link["place_id"]
        entry = ctx.entries.get(eid)
        if entry is None:
            _warn(f"place link {eid!r} has no entry in the routes index")
            continue
        items, _ = entry_items(entry, ctx.cfg)
        item = next((i for i in items if i["kind"] == "place"), None)
        if item is None:
            _warn(f"entry {eid!r} is linked as a Place but is not kind=place")
            continue
        method = _classify(item, eid, ctx)
        book_ele = item["elevation_m"]
        name = entry.get("name") or item["name"]
        name_cell = _cell(
            f"{name}, {_fmt_m(book_ele)}" if book_ele is not None else name
        )
        osm_name, delta = _poi_cells(
            ctx.pois.get(link["poi_id"]), link["poi_id"], book_ele
        )
        rows.append(
            Row(
                key=(eid,),
                method=method,
                cells=(
                    name_cell,
                    _excerpt(entry.get("description", ""), None, UEBERSICHT_WIDTH),
                    osm_name,
                    delta,
                    method,
                ),
            )
        )
    return rows


def build_mention_rows(links: list[dict], ctx: MatchContext) -> list[Row]:
    """One row per Entry mention -> POI link (entry_pois.jsonl)."""
    rows: list[Row] = []
    for link in links:
        eid, surface = link["entry_id"], link["surface"]
        entry = ctx.entries.get(eid)
        if entry is None:
            _warn(f"mention link {eid!r} has no entry in the routes index")
            continue
        items, _ = entry_items(entry, ctx.cfg)
        item = next(
            (i for i in items if i["kind"] == "mention" and i["surface"] == surface),
            None,
        )
        if item is None:
            # The extracted mention this link came from is gone (a part file
            # changed after the match): show the row honestly, method unknown.
            _warn(f"entry {eid!r} no longer extracts the mention {surface!r}")
            method, book_ele = "?", None
        else:
            method = _classify(item, eid, ctx)
            book_ele = item["elevation_m"]
        osm_name, delta = _poi_cells(
            ctx.pois.get(link["poi_id"]), link["poi_id"], book_ele
        )
        rows.append(
            Row(
                key=(eid, surface, link["poi_id"]),
                method=method,
                cells=(
                    _cell(surface),
                    _excerpt(entry.get("description", ""), surface, CONTEXT_WIDTH),
                    osm_name,
                    delta,
                    method,
                ),
            )
        )
    return rows


def sample(rows: list[Row], size: int = SAMPLE_SIZE, seed: int = SEED) -> list[Row]:
    """A seeded sample of `size` rows, oversampling the fuzzy/LLM methods where
    errors hide (then review), and filling with exact only as needed. Within a
    priority tier the pick is uniform-random but deterministic: the random key
    is drawn once per row over a canonically sorted list, so an unchanged input
    yields the identical sample, displayed in stable order."""
    ordered = sorted(rows, key=lambda r: r.key)
    rng = random.Random(seed)
    decorated = [
        ((_METHOD_PRIORITY.get(r.method, _FILL_PRIORITY), rng.random()), r)
        for r in ordered
    ]
    decorated.sort(key=lambda d: d[0])
    return sorted((r for _, r in decorated[:size]), key=lambda r: r.key)


def render_table(headers: tuple[str, ...], rows: list[Row]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines += ["| " + " | ".join(r.cells) + " |" for r in rows]
    return "\n".join(lines)


PLACE_HEADERS = (
    "Place (book elev.)",
    "Übersicht excerpt",
    "OSM name",
    "Δ elev.",
    "method",
)
MENTION_HEADERS = ("Mention", "Prose context", "OSM name", "Δ elev.", "method")


def _require(path: Path, what: str) -> None:
    if not path.exists():
        sys.exit(f"missing {path} — {what}")


def _method_tally(rows: list[Row]) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.method] = counts.get(r.method, 0) + 1
    return ", ".join(f"{m}: {counts[m]}" for m in sorted(counts))


def run_audit(cfg: GuideConfig) -> str:
    """Build, sample, and render both audit tables. Prints the Markdown to
    stdout and a one-line summary (with the honest unmatched counts) to stderr,
    mirroring `plan funnel`. Returns the stdout text."""
    _require(cfg.routes_jsonl, "run the parse-routes pipeline first.")
    for path in (cfg.pois_jsonl, cfg.place_pois_jsonl, cfg.entry_pois_jsonl):
        _require(path, "run the matcher first.")

    index, keys = build_index(load_jsonl(cfg.gazetteer))
    decisions, _notes = load_decisions(cfg)
    ctx = MatchContext(
        entries={e["id"]: e for e in load_jsonl(cfg.routes_jsonl)},
        pois={p["poi_id"]: p for p in load_jsonl(cfg.pois_jsonl)},
        index=index,
        keys=keys,
        decisions=decisions,
        verdicts=load_verdicts(cfg),
        cfg=cfg,
    )
    place_rows = build_place_rows(load_jsonl(cfg.place_pois_jsonl), ctx)
    mention_rows = build_mention_rows(load_jsonl(cfg.entry_pois_jsonl), ctx)
    place_sample = sample(place_rows)
    mention_sample = sample(mention_rows)

    out = "\n".join(
        [
            f"## Place → POI matches ({len(place_sample)} of {len(place_rows)} matches)",
            "",
            render_table(PLACE_HEADERS, place_sample),
            "",
            f"## Entry mentions → POI ({len(mention_sample)} of {len(mention_rows)} matches)",
            "",
            render_table(MENTION_HEADERS, mention_sample),
        ]
    )
    print(out)

    # Honest picture: what is *not* in the tables. Places/mentions with no
    # match live in unmatched.jsonl (with the funnel counting them); surface
    # their counts and point at both artifacts so nothing is silently dropped.
    unmatched = load_jsonl(cfg.unmatched) if cfg.unmatched.exists() else []
    unmatched_places = sum(u["kind"] == "place" for u in unmatched)
    unmatched_mentions = sum(u["kind"] == "mention" for u in unmatched)
    print(
        f"[audit] place matches: {len(place_rows)} matched "
        f"(sample {len(place_sample)} — {_method_tally(place_sample)}), "
        f"{unmatched_places} without a match; "
        f"mention links: {len(mention_rows)} matched "
        f"(sample {len(mention_sample)} — {_method_tally(mention_sample)}), "
        f"{unmatched_mentions} without a match. "
        f"Unmatched/skipped detail in {cfg.unmatched}; "
        f"full funnel via `plan funnel --guide {cfg.id}`.",
        file=sys.stderr,
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Print seeded match-audit tables for operator sign-off."
    )
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    args = ap.parse_args()
    run_audit(load_guide(args.guide))


if __name__ == "__main__":
    main()
