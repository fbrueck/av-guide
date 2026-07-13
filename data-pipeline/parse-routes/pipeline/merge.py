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
- **Anchors.** A Route's *primary* anchor is its structural parent Place — the
  nearest preceding Place in the book's running sequence (id-to-id from nesting).
  Traverse Routes name *additional* target Places in prose; those are resolved
  by name against a place-name index (best-effort; unresolved surfaced).
- **References.** Inline cross-refs (`Wie R 43`) are parsed from each Entry's
  verbatim description into `{ref_id, surface}` (see references.py).
- **Validation.** Every reference `ref_id` and every `anchor_id` is checked
  against the id set; dangling ids are reported, never dropped or invented.

The parts files are the source of truth, so this rebuilds the entries/ directory
from scratch on every run (deterministic, no stale files).

  python -m pipeline.merge --guide <id>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys

from .config import GuideConfig, load_guide
from .export import write_routes_json
from .ids import normalize_entry_id, synthetic_id
from .references import parse_references

# Route-only and Place-only verbatim fields carried through from extraction.
_ROUTE_FIELDS = ("peak", "grade", "first_ascent", "time", "height_m")
_PLACE_FIELDS = ("place_type", "elevation")


def _norm_name(name: str) -> str:
    """Fold a place name to a match key: casefold + collapsed whitespace."""
    return " ".join(name.split()).casefold()


def assemble_entries(
    parts: list[tuple[int, list[dict]]],
) -> tuple[list[dict], dict]:
    """Turn per-page entry lists (in book order) into linked Entry records.

    `parts` is `[(page, entries)]` already sorted in book (page) order; each
    entry is the raw dict an extractor wrote. Returns `(records, report)` where
    records are in book order and report collects dangling refs / unresolved
    anchor names / synthetic-id and collision counts for the caller to surface.
    """
    report: dict = {
        "synthetic": 0,  # book number unrecoverable from OCR (the spec's trigger)
        "id_collisions": [],  # book number recoverable but already taken
        "unresolved_anchors": [],
        "dangling_refs": [],
    }

    # Pass 1 — assign ids. A recoverable, unique book number keys the Entry
    # directly (`id_source: book`). Otherwise the id is generated
    # (`id_source: synthetic`) for one of two distinct reasons, counted apart:
    # the number was unrecoverable from OCR (the spec's trigger), or it was
    # recoverable but collided with an earlier Entry (an OCR/book anomaly we
    # surface rather than silently overwrite).
    records: list[dict] = []
    used_ids: set[str] = set()
    for page, entries in parts:
        for seq, entry in enumerate(entries, start=1):
            book_id = normalize_entry_id(entry.get("entry_id_raw"))
            if book_id and book_id not in used_ids:
                entry_id, id_source = book_id, "book"
            else:
                if book_id in used_ids:
                    report["id_collisions"].append(book_id)
                else:
                    report["synthetic"] += 1  # only the OCR-unrecoverable case
                entry_id, id_source = synthetic_id(page, seq), "synthetic"
            used_ids.add(entry_id)

            kind = entry.get("kind", "route")
            rec: dict = {
                "id": entry_id,
                "id_source": id_source,
                "kind": kind,
                "source_page": page,
                "_seq": seq,  # book-order tiebreak; stripped before writing
                "name": entry.get("name"),
                "description": entry.get("description"),
                "summary": entry.get("summary"),
                "references": parse_references(entry.get("description")),
            }
            if kind == "place":
                for f in _PLACE_FIELDS:
                    rec[f] = entry.get(f)
            else:
                for f in _ROUTE_FIELDS:
                    rec[f] = entry.get(f)
                rec["_anchor_names"] = entry.get("anchor_names") or []
            records.append(rec)

    id_set = {r["id"] for r in records}

    # Pass 2 — place-name index (first occurrence wins on duplicate names).
    place_index: dict[str, str] = {}
    for r in records:
        if r["kind"] == "place" and r.get("name"):
            place_index.setdefault(_norm_name(r["name"]), r["id"])

    # Pass 3 — anchors. Primary = nearest preceding Place (structural nesting);
    # additional = traverse target names resolved via the place-name index.
    current_place: str | None = None
    for r in records:
        if r["kind"] == "place":
            current_place = r["id"]
            continue
        anchor_ids: list[str] = []
        if current_place is not None:
            anchor_ids.append(current_place)
        for name in r.pop("_anchor_names"):
            rid = place_index.get(_norm_name(name))
            if rid is None:
                report["unresolved_anchors"].append({"route": r["id"], "name": name})
            elif rid not in anchor_ids:
                anchor_ids.append(rid)
        r["anchor_ids"] = anchor_ids

    # Pass 4 — validate references against the id set (dangling surfaced).
    for r in records:
        for ref in r["references"]:
            rid = ref["ref_id"]
            if rid is not None and rid not in id_set:
                report["dangling_refs"].append({"from": r["id"], "ref_id": rid})

    return records, report


def _clean_record(rec: dict) -> dict:
    """Strip internal bookkeeping keys before persisting a record."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def merge(cfg: GuideConfig) -> None:
    if not cfg.struct_parts.exists():
        sys.exit("No parts dir — run the structure stage first.")

    # Rebuild entries/ from scratch so a re-merge never leaves stale files.
    if cfg.entries_dir.exists():
        shutil.rmtree(cfg.entries_dir)
    cfg.entries_dir.mkdir(parents=True, exist_ok=True)

    parts: list[tuple[int, list[dict]]] = []
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

    for rec in records:
        clean = _clean_record(rec)
        (cfg.entries_dir / f"{clean['id']}.json").write_text(
            json.dumps(clean, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # Index and route-map contract in book order (page, then in-page sequence).
    ordered = [_clean_record(r) for r in records]
    with cfg.routes_jsonl.open("w", encoding="utf-8") as f:
        for rec in ordered:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Regenerate the route-map contract from the same list so it never drifts
    # from the index (#17).
    write_routes_json(cfg, ordered)

    _print_summary(cfg, records, report, bad)


def _print_summary(
    cfg: GuideConfig, records: list[dict], report: dict, bad: int
) -> None:
    n_place = sum(r["kind"] == "place" for r in records)
    n_route = sum(r["kind"] == "route" for r in records)
    n_collision = len(report["id_collisions"])
    print(f"Wrote {len(records)} entry files -> {cfg.entries_dir}")
    print(
        f"  {n_place} places, {n_route} routes, "
        f"{report['synthetic']} synthetic ids (OCR-unrecoverable), "
        f"{n_collision} collision re-keyed"
    )
    print(f"Combined index -> {cfg.routes_jsonl}  ({bad} unreadable parts)")
    print(f"route-map contract -> {cfg.routes_json}")
    if report["id_collisions"]:
        print(
            f"  WARN: {n_collision} book-id collisions "
            f"(recoverable but duplicate; re-keyed synthetic): "
            f"{report['id_collisions']}",
            file=sys.stderr,
        )
    if report["unresolved_anchors"]:
        print(
            f"  WARN: {len(report['unresolved_anchors'])} unresolved traverse "
            "anchor names (surfaced, not invented)",
            file=sys.stderr,
        )
    if report["dangling_refs"]:
        print(
            f"  WARN: {len(report['dangling_refs'])} dangling references "
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
