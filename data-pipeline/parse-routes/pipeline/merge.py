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
  canonical key (`R43`); fall back to a deterministic synthetic id when the
  Randziffer is unrecoverable, flagged `id_source: book | synthetic`. Places and
  Routes share one id namespace.
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
from .ids import normalize_entry_id, synthetic_id
from .records import Entry
from .references import parse_references


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


@dataclass
class MergeReport:
    """What the assembly passes surface for the caller to warn about. Mutable
    on purpose: it is an accumulator built up across the passes (unlike the
    frozen domain records it reports on)."""

    synthetic: int = 0  # book number unrecoverable from OCR (the spec's trigger)
    id_collisions: list[str] = field(default_factory=list)  # recoverable but taken
    unresolved_places: list[UnresolvedPlace] = field(default_factory=list)
    missing_destination: list[str] = field(default_factory=list)  # no parent Place
    dangling_refs: list[DanglingRef] = field(default_factory=list)


def _norm_name(name: str) -> str:
    """Fold a place name to a match key: casefold + collapsed whitespace."""
    return " ".join(name.split()).casefold()


def _assign_id(
    raw: dict[str, Any], page: int, seq: int, used_ids: set[str], report: MergeReport
) -> tuple[str, str]:
    """A recoverable, unique book number keys the Entry directly
    (`id_source: book`). Otherwise a deterministic synthetic id is assigned for
    one of two reasons, counted apart: the number was unrecoverable from OCR
    (the spec's trigger), or it collided with an earlier Entry (surfaced, not
    silently overwritten)."""
    book_id = normalize_entry_id(raw.get("entry_id_raw"))
    if book_id and book_id not in used_ids:
        return book_id, "book"
    if book_id in used_ids and book_id is not None:
        report.id_collisions.append(book_id)
    else:
        report.synthetic += 1  # only the OCR-unrecoverable case
    return synthetic_id(page, seq), "synthetic"


def _build_entry(
    raw: dict[str, Any], entry_id: str, id_source: str, page: int
) -> Entry:
    """One raw per-page entry dict -> an Entry, targets still unresolved. A
    Place carries place_type/elevation; a Route the climbing metadata — each
    leaves the other kind's verbatim fields None."""
    kind = raw.get("kind", "route")
    is_place = kind == "place"
    return Entry(
        id=entry_id,
        kind=kind,
        id_source=id_source,
        source_page=page,
        name=raw.get("name"),
        description=raw.get("description"),
        summary=raw.get("summary"),
        references=parse_references(raw.get("description")),
        place_type=raw.get("place_type") if is_place else None,
        elevation=raw.get("elevation") if is_place else None,
        peak=None if is_place else raw.get("peak"),
        grade=None if is_place else raw.get("grade"),
        first_ascent=None if is_place else raw.get("first_ascent"),
        time=None if is_place else raw.get("time"),
        height_m=None if is_place else raw.get("height_m"),
    )


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
    parts: list[tuple[int, list[dict[str, Any]]]],
) -> tuple[list[Entry], MergeReport]:
    """Turn per-page entry lists (in book order) into linked Entry records.

    `parts` is `[(page, entries)]` already sorted in book (page) order; each
    entry is the raw wire dict an extractor wrote. Returns `(records, report)`
    where records are Entries in book order and report collects dangling refs /
    unresolved place names / destination gaps / synthetic-id and collision
    counts for the caller to surface.
    """
    report = MergeReport()

    # Pass 1 — assign ids and build Entries (targets still unresolved). Keep each
    # Route's raw traverse place-names alongside for the target pass.
    records: list[Entry] = []
    place_names: list[list[str]] = []
    used_ids: set[str] = set()
    for page, entries in parts:
        for seq, raw in enumerate(entries, start=1):
            entry_id, id_source = _assign_id(raw, page, seq, used_ids, report)
            used_ids.add(entry_id)
            records.append(_build_entry(raw, entry_id, id_source, page))
            place_names.append(
                [] if raw.get("kind") == "place" else raw.get("place_names") or []
            )

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


def merge(cfg: GuideConfig) -> None:
    if not cfg.struct_parts.exists():
        sys.exit("No parts dir — run the structure stage first.")

    # Rebuild entries/ from scratch so a re-merge never leaves stale files.
    if cfg.entries_dir.exists():
        shutil.rmtree(cfg.entries_dir)
    cfg.entries_dir.mkdir(parents=True, exist_ok=True)

    parts: list[tuple[int, list[dict[str, Any]]]] = []
    bad = 0
    for part in sorted(cfg.struct_parts.glob("page_*.json")):
        page = int(part.stem.split("_")[1])
        try:
            data = json.loads(part.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            bad += 1
            print(f"  WARN: {part.name} is not valid JSON — skipped", file=sys.stderr)
            continue
        parts.append((page, data.get("entries", [])))

    records, report = assemble_entries(parts)

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

    _print_summary(cfg, records, report, bad)


def _print_summary(
    cfg: GuideConfig, records: list[Entry], report: MergeReport, bad: int
) -> None:
    n_place = sum(r.kind == "place" for r in records)
    n_route = sum(r.kind == "route" for r in records)
    n_collision = len(report.id_collisions)
    print(f"Wrote {len(records)} entry files -> {cfg.entries_dir}")
    print(
        f"  {n_place} places, {n_route} routes, "
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


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Merge per-page entry parts into routes.jsonl."
    )
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    args = ap.parse_args()
    merge(load_guide(args.guide))


if __name__ == "__main__":
    main()
