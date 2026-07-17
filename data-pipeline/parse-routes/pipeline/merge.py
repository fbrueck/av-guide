"""Merge per-page Entry JSON into one file per Entry, plus a combined index.

The entry-extractor subagents write one part file per page
(`03_structured/parts/page_0051.json`) containing the **Entries** — Places and
Routes — that *start* on that page, in reading order. This step assembles them
into the final artifact: one JSON file per Entry under `03_structured/entries/`,
each self-contained, plus a combined `routes.jsonl` index and the `route-map`
contract `routes.json`.

The deterministic work that turns loose per-page entries into a linked dataset
lives here (no LLM):

- **Identity.** Key each Entry by the book's entry id, normalized to the
  canonical key (`R43`). When the OCR dropped a Randziffer (a reverse-video
  banner number, #86), recover it from the strictly-ascending sequence where the
  surviving neighbours pin it unambiguously (`inferred`); fall back to a
  deterministic synthetic id when it stays unrecoverable. Flagged `id_source:
  book | inferred | synthetic`. Places and Routes share one id namespace.
- **Destination and places.** A Route's *Destination* is its structural parent
  Place — the nearest preceding Place in the book's running sequence
  (`destination_id`, id-to-id from nesting; null when there is none, surfaced in
  the report rather than invented). Traverse Routes name *additional* target
  Places in prose; those resolve by name against a place-name index into
  `place_ids` (disjoint from the Destination; best-effort, unresolved surfaced).
- **References.** Inline cross-refs (`Wie R 43`) are parsed from each Entry's
  verbatim description into `{ref_id, surface}` (see references.py).
- **Validation.** Every reference `ref_id` is checked against the id set;
  dangling ids are reported, never dropped or invented.

The parts files are the source of truth, so this rebuilds the entries/ directory
from scratch on every run (deterministic, no stale files).

  python -m pipeline.merge --guide <id>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field, replace
from typing import Any

from .config import GuideConfig, load_guide
from .export import write_routes_json
from .ids import entry_id_number, infer_sequence_ids, normalize_entry_id, synthetic_id
from .records import DescriptionSource, Entry, PartEntry
from .references import parse_references
from .slicing import slice_description, unsliced_reason


@dataclass(frozen=True, slots=True)
class UnresolvedPlace:
    """A traverse place-name a Route's prose named that no Place resolves."""

    route: str
    name: str


@dataclass(frozen=True, slots=True)
class DanglingRef:
    """A Reference whose `ref_id` points at no Entry in the id set."""

    from_id: str
    ref_id: str


@dataclass(frozen=True, slots=True)
class UnslicedEntry:
    """An entry whose verbatim description could not be sliced, tagged with the
    reason bucket classifying why (#110). Identifies the entry (id, source page,
    name, kind) so the recovery passes can target it and every ticket can measure
    its effect; persisted one-per-line to the unsliced-report artifact."""

    id: str
    source_page: int | None
    name: str | None
    kind: str
    reason: str  # see slicing.unsliced_reason — the buckets partition the set

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_page": self.source_page,
            "name": self.name,
            "kind": self.kind,
            "reason": self.reason,
        }


@dataclass(slots=True)
class MergeReport:
    """What the assembly passes surface for the caller to warn about. Mutable
    on purpose: it is an accumulator built up across the passes (unlike the
    frozen domain records it reports on)."""

    synthetic: int = 0  # OCR-unrecoverable AND un-inferable (the spec's trigger)
    inferred: int = 0  # Randziffer OCR dropped, recovered from the sequence (#86)
    id_collisions: list[str] = field(default_factory=list)  # recoverable but taken
    unresolved_places: list[UnresolvedPlace] = field(default_factory=list)
    missing_destination: list[str] = field(default_factory=list)  # no parent Place
    dangling_refs: list[DanglingRef] = field(default_factory=list)
    # Entries whose description could not be sliced, each tagged with its reason
    # bucket (#110); persisted to the unsliced-report artifact.
    unsliced: list[UnslicedEntry] = field(default_factory=list)


def _norm_name(name: str) -> str:
    """Fold a place name to a match key: casefold + collapsed whitespace."""
    return " ".join(name.split()).casefold()


def _assign_ids(
    parts: list[tuple[int, list[PartEntry]]], report: MergeReport
) -> list[tuple[str, str]]:
    """Assign every entry's `(id, id_source)` in book order.

    Batched, not per-entry, because recovering a Randziffer the OCR dropped needs
    the whole ascending sequence in view (#86): the id is inferred from the gap
    the surviving neighbours leave. A recoverable, unique book number keys the
    Entry directly (`book`); a gap the sequence pins unambiguously is filled
    (`inferred`); failing both, a deterministic synthetic id stands. See
    `_pick_id` for the per-entry choice."""
    flat = [
        (page, seq, raw)
        for page, entries in parts
        for seq, raw in enumerate(entries, start=1)
    ]
    recovered = [normalize_entry_id(raw.entry_id_raw) for _, _, raw in flat]
    inferred = infer_sequence_ids([entry_id_number(c) for c in recovered])
    taken = {c for c in recovered if c}  # every real book id, to never re-key one

    used: set[str] = set()
    assignments: list[tuple[str, str]] = []
    for (page, seq, _), book, number in zip(flat, recovered, inferred):
        entry_id, id_source = _pick_id(
            book, number, synthetic_id(page, seq), used, taken, report
        )
        used.add(entry_id)
        assignments.append((entry_id, id_source))
    return assignments


def _pick_id(
    book: str | None,
    inferred_number: int | None,
    fallback: str,
    used: set[str],
    taken: set[str],
    report: MergeReport,
) -> tuple[str, str]:
    """Choose one entry's `(id, id_source)`: its own unique book number, else a
    sequence-inferred number, else `fallback` (the entry's deterministic
    synthetic id). Synthetic is counted apart for its two causes — a collision
    with an earlier Entry (surfaced, not overwritten) versus an OCR-unrecoverable,
    un-inferable number (the trigger). An inferred number is used only when it
    collides with no id at all — neither one already assigned nor any real book
    number elsewhere in the book."""
    if book and book not in used:
        return book, "book"
    if book:  # recoverable but already taken — never silently overwrite
        report.id_collisions.append(book)
        return fallback, "synthetic"
    if inferred_number is not None:
        candidate = f"R{inferred_number}"
        if candidate not in used and candidate not in taken:
            report.inferred += 1
            return candidate, "inferred"
    report.synthetic += 1
    return fallback, "synthetic"


def _build_entry(
    raw: PartEntry,
    entry_id: str,
    id_source: str,
    page: int,
    description: str | None,
    description_source: DescriptionSource,
) -> Entry:
    """One parsed per-page part entry -> an Entry, targets still unresolved. A
    Place carries place_type/elevation; a Route the climbing metadata — each
    leaves the other kind's verbatim fields None. `description` is the verbatim
    text merge sliced from the cleaned page between the entry's anchors;
    `description_source` records whether it was sliced, a stub one-liner, or
    absent (#114)."""
    is_place = raw.kind == "place"
    return Entry(
        id=entry_id,
        kind=raw.kind,
        id_source=id_source,
        source_page=page,
        name=raw.name,
        description=description,
        description_source=description_source,
        summary=raw.summary,
        references=parse_references(description),
        place_type=raw.place_type if is_place else None,
        elevation=raw.elevation if is_place else None,
        peak=None if is_place else raw.peak,
        grade=None if is_place else raw.grade,
        first_ascent=None if is_place else raw.first_ascent,
        time=None if is_place else raw.time,
        height_m=None if is_place else raw.height_m,
    )


def _resolve_description(
    raw: PartEntry,
    entry_id: str,
    page: int,
    text: str,
    next_text: str | None,
    report: MergeReport,
) -> tuple[str | None, DescriptionSource]:
    """Slice the entry's verbatim description and tag its provenance (#114).

    A successful slice is `sliced`. On failure the reason is classified and the
    entry recorded in the unsliced report (#110); a body-less `stub` (start ==
    end, no gap to cut) then keeps its one-line heading text — honest, verbatim,
    flagged `stub` — rather than dropping it; anything else stays `none`."""
    description = slice_description(text, next_text, raw.start_quote, raw.end_quote)
    if description is not None:
        return description, "sliced"

    reason = unsliced_reason(text, next_text, raw.start_quote, raw.end_quote)
    report.unsliced.append(
        UnslicedEntry(
            id=entry_id,
            source_page=page,
            name=raw.name,
            kind=raw.kind,
            reason=reason,
        )
    )
    if reason == "stub":
        # No span between the identical anchors — store the entry's one-line text
        # (its verbatim heading) so the stub is not left empty (#114).
        return raw.start_quote, "stub"
    return None, "none"


def _place_index(records: list[Entry]) -> dict[str, str]:
    """Map a normalized place name to its Entry id (first occurrence wins)."""
    index: dict[str, str] = {}
    for r in records:
        if r.kind == "place" and r.name:
            index.setdefault(_norm_name(r.name), r.id)
    return index


def _resolve_targets(
    route: Entry,
    current_place: str | None,
    place_names: list[str],
    index: dict[str, str],
    report: MergeReport,
) -> Entry:
    """Set a Route's Destination (nearest preceding Place, or None — surfaced,
    not invented) and its `place_ids` (traverse names resolved via the index,
    disjoint from the Destination)."""
    if current_place is None:
        report.missing_destination.append(route.id)
    place_ids: list[str] = []
    for name in place_names:
        rid = index.get(_norm_name(name))
        if rid is None:
            report.unresolved_places.append(UnresolvedPlace(route=route.id, name=name))
        elif rid != current_place and rid not in place_ids:
            place_ids.append(rid)
    return replace(route, destination_id=current_place, place_ids=place_ids)


def _report_dangling(records: list[Entry], report: MergeReport) -> None:
    """Validate every Reference `ref_id` against the id set; surface danglers."""
    id_set = {r.id for r in records}
    for r in records:
        for ref in r.references:
            if ref.ref_id is not None and ref.ref_id not in id_set:
                report.dangling_refs.append(
                    DanglingRef(from_id=r.id, ref_id=ref.ref_id)
                )


def assemble_entries(
    parts: list[tuple[int, list[PartEntry]]],
    page_texts: dict[int, str],
) -> tuple[list[Entry], MergeReport]:
    """Turn per-page entry lists (in book order) into linked Entry records.

    `parts` is `[(page, entries)]` already sorted in book (page) order; each
    entry is a `PartEntry` parsed from what an extractor wrote. `page_texts` maps
    a page number to its cleaned text, used to slice each entry's verbatim
    description between its anchors (the next page is read too, for entries that
    span a page break). Returns `(records, report)` where records are Entries in
    book order and report collects dangling refs / unresolved place names /
    destination gaps / inferred-, synthetic-id and collision counts / unsliced
    anchors for the caller to surface.
    """
    report = MergeReport()

    # Pass 1 — assign ids (one batch, so the gap-fill sees the whole ascending
    # sequence, #86), slice descriptions, build Entries (targets still
    # unresolved). Keep each Route's raw traverse place-names for the target pass.
    records: list[Entry] = []
    place_names: list[list[str]] = []
    assignments = iter(_assign_ids(parts, report))
    for page, entries in parts:
        text = page_texts.get(page, "")
        next_text = page_texts.get(page + 1)
        for raw in entries:
            entry_id, id_source = next(assignments)
            description, description_source = _resolve_description(
                raw, entry_id, page, text, next_text, report
            )
            records.append(
                _build_entry(
                    raw, entry_id, id_source, page, description, description_source
                )
            )
            place_names.append([] if raw.kind == "place" else raw.place_names)

    # Pass 2 — place-name index.
    index = _place_index(records)

    # Pass 3 — targets. A Place carries the running Destination forward; a Route
    # resolves its Destination and traverse place_ids against it.
    current_place: str | None = None
    for i, r in enumerate(records):
        if r.kind == "place":
            current_place = r.id
            continue
        records[i] = _resolve_targets(r, current_place, place_names[i], index, report)

    # Pass 4 — validate references against the id set (dangling surfaced).
    _report_dangling(records, report)

    return records, report


def _load_page_texts(
    cfg: GuideConfig, parts: list[tuple[int, list[PartEntry]]]
) -> dict[int, str]:
    """Read the cleaned text for every page that has entries, plus each one's
    next page (an entry can spill onto it). Missing pages map to ''."""
    wanted: set[int] = set()
    for page, _ in parts:
        wanted.add(page)
        wanted.add(page + 1)
    texts: dict[int, str] = {}
    for page in wanted:
        f = cfg.clean_pages / f"page_{page:04d}.txt"
        texts[page] = f.read_text(encoding="utf-8") if f.exists() else ""
    return texts


def merge(cfg: GuideConfig) -> None:
    if not cfg.struct_parts.exists():
        sys.exit("No parts dir — run the structure stage first.")

    # Rebuild entries/ from scratch so a re-merge never leaves stale files.
    if cfg.entries_dir.exists():
        shutil.rmtree(cfg.entries_dir)
    cfg.entries_dir.mkdir(parents=True, exist_ok=True)

    parts: list[tuple[int, list[PartEntry]]] = []
    bad = 0
    for part in sorted(cfg.struct_parts.glob("page_*.json")):
        page = int(part.stem.split("_")[1])
        try:
            data = json.loads(part.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            bad += 1
            print(f"  WARN: {part.name} is not valid JSON — skipped", file=sys.stderr)
            continue
        # Convert the wire dicts to typed records once, at the read boundary.
        entries = [PartEntry.from_dict(e) for e in data.get("entries", [])]
        parts.append((page, entries))

    # Load the cleaned page text merge slices descriptions from — each entry's
    # start page plus the next (for entries that spill across the page break).
    page_texts = _load_page_texts(cfg, parts)

    records, report = assemble_entries(parts, page_texts)

    # One self-contained JSON file per Entry, plus the combined index — both in
    # book order (page, then in-page sequence).
    ordered = [r.to_record() for r in records]
    for rec in ordered:
        (cfg.entries_dir / f"{rec['id']}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    with cfg.routes_jsonl.open("w", encoding="utf-8") as f:
        for rec in ordered:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Regenerate the route-map contract from the same records so it never drifts
    # from the index (#17).
    write_routes_json(cfg, records)

    # Persist the unsliced-entry report (#110): rebuilt from scratch each run, so
    # it never carries stale records; an empty file when nothing is unsliced.
    _write_unsliced_report(cfg, report.unsliced)

    _print_summary(cfg, records, report, bad)


def _write_unsliced_report(cfg: GuideConfig, unsliced: list[UnslicedEntry]) -> None:
    """Write one JSON record per unsliceable entry to the report artifact,
    truncating any prior run's file (empty when nothing is unsliced)."""
    with cfg.unsliced_report.open("w", encoding="utf-8") as f:
        for entry in unsliced:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")


def _print_summary(
    cfg: GuideConfig, records: list[Entry], report: MergeReport, bad: int
) -> None:
    n_place = sum(r.kind == "place" for r in records)
    n_route = sum(r.kind == "route" for r in records)
    n_collision = len(report.id_collisions)
    print(f"Wrote {len(records)} entry files -> {cfg.entries_dir}")
    print(
        f"  {n_place} places, {n_route} routes, "
        f"{report.inferred} inferred ids (Randziffer recovered from sequence), "
        f"{report.synthetic} synthetic ids (OCR-unrecoverable), "
        f"{n_collision} collision re-keyed"
    )
    print(f"Combined index -> {cfg.routes_jsonl}  ({bad} unreadable parts)")
    print(f"route-map contract -> {cfg.routes_json}")
    if report.id_collisions:
        print(
            f"  WARN: {n_collision} book-id collisions "
            f"(recoverable but duplicate; re-keyed synthetic): "
            f"{report.id_collisions}",
            file=sys.stderr,
        )
    if report.missing_destination:
        print(
            f"  WARN: {len(report.missing_destination)} routes with no "
            "Destination (no structural parent Place; surfaced, not invented)",
            file=sys.stderr,
        )
    if report.unresolved_places:
        print(
            f"  WARN: {len(report.unresolved_places)} unresolved traverse "
            "place names (surfaced, not invented)",
            file=sys.stderr,
        )
    if report.dangling_refs:
        print(
            f"  WARN: {len(report.dangling_refs)} dangling references "
            "(ref_id not in id set)",
            file=sys.stderr,
        )
    if report.unsliced:
        buckets: dict[str, int] = {}
        for u in report.unsliced:
            buckets[u.reason] = buckets.get(u.reason, 0) + 1
        by_reason = ", ".join(f"{r}={n}" for r, n in sorted(buckets.items()))
        print(
            f"  WARN: {len(report.unsliced)} entries with no sliceable "
            f"description ({by_reason}); see {cfg.unsliced_report}",
            file=sys.stderr,
        )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Merge per-page entry parts into routes.jsonl."
    )
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    args = ap.parse_args()
    merge(load_guide(args.guide))


if __name__ == "__main__":
    main()
