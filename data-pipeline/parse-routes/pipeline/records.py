"""Typed domain records shared across the parse-routes stages.

A `dict` is the JSONL/JSON wire format only (see data-pipeline/CLAUDE.md); read
functions parse it into the records named here for their CONTEXT.md concept, and
write functions serialize them back. No bare record `dict` crosses a boundary in
between.

  - `Entry` — a single numbered book item (Place or Route), the pipeline's unit
    of identity (`CONTEXT.md`). Places and Routes share one dataclass; a field
    that belongs to the other kind stays None.
  - `PartEntry` — one entry as the extractor wrote it to a part file, before
    merge assigns identity and resolves targets. Merge parses each part entry
    into this record at the read boundary, then builds the final `Entry`.
  - `PageMeta` — one per-page metadata record produced by the extractor and read
    back by the planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .references import Reference

# Every Entry/PartEntry is one of these two kinds (CONTEXT.md).
Kind = Literal["place", "route"]

# Provenance of an Entry's `description` (#114), so verbatim and non-verbatim
# text are never silently mixed: `sliced` = cut verbatim from the page between
# the anchors; `stub` = a body-less □ cross-ref's one-line heading (no gap to
# slice); `none` = no description recovered.
DescriptionSource = Literal["sliced", "stub", "none"]

# Route-only and Place-only verbatim fields carried through from extraction.
_ROUTE_FIELDS = ("peak", "grade", "first_ascent", "time", "height_m")
_PLACE_FIELDS = ("place_type", "elevation")


@dataclass(frozen=True, slots=True)
class Entry:
    """A book Entry keyed by its canonical entry id (`R43`). `kind` is
    `place` or `route`; Route-only metadata (peak/grade/…) and Place-only
    metadata (place_type/elevation) stay None on the other kind. `destination_id`
    and `place_ids` are a Route's resolved targets (empty/None on a Place)."""

    id: str
    kind: Kind
    name: str | None = None
    description: str | None = None
    # Where `description` came from — never silently mix verbatim and non-verbatim
    # text (#114). `none` matches a null description, `stub` a body-less one-liner.
    description_source: DescriptionSource = "none"
    summary: str | None = None
    references: list[Reference] = field(default_factory=list)
    # Internal bookkeeping — not part of the route-map contract.
    id_source: str = "book"  # "book" | "inferred" | "synthetic"
    source_page: int | None = None
    # Place-only verbatim metadata.
    place_type: str | None = None
    elevation: str | None = None
    # Route-only verbatim metadata.
    peak: str | None = None
    grade: str | None = None
    first_ascent: str | None = None
    time: str | None = None
    height_m: str | None = None
    # Route targets (resolved at merge).
    destination_id: str | None = None
    place_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Entry:
        """Parse a wire record (a merge-record or contract dict) into an Entry.
        Absent fields fall back to the dataclass defaults."""
        return cls(
            id=raw["id"],
            kind=raw.get("kind", "route"),
            name=raw.get("name"),
            description=raw.get("description"),
            description_source=raw.get("description_source", "none"),
            summary=raw.get("summary"),
            references=[Reference.from_dict(r) for r in raw.get("references") or []],
            id_source=raw.get("id_source", "book"),
            source_page=raw.get("source_page"),
            place_type=raw.get("place_type"),
            elevation=raw.get("elevation"),
            peak=raw.get("peak"),
            grade=raw.get("grade"),
            first_ascent=raw.get("first_ascent"),
            time=raw.get("time"),
            height_m=raw.get("height_m"),
            destination_id=raw.get("destination_id"),
            place_ids=list(raw.get("place_ids") or []),
        )

    def to_record(self) -> dict[str, Any]:
        """Serialize to the merged-index/entry-file wire shape: shared fields,
        then the kind's own verbatim metadata (a Route also carries its resolved
        targets). Internal bookkeeping is kept; `merge` strips it per file."""
        rec: dict[str, Any] = {
            "id": self.id,
            "id_source": self.id_source,
            "kind": self.kind,
            "source_page": self.source_page,
            "name": self.name,
            "description": self.description,
            "description_source": self.description_source,
            "summary": self.summary,
            "references": [r.to_dict() for r in self.references],
        }
        if self.kind == "place":
            for f in _PLACE_FIELDS:
                rec[f] = getattr(self, f)
        else:
            for f in _ROUTE_FIELDS:
                rec[f] = getattr(self, f)
            rec["destination_id"] = self.destination_id
            rec["place_ids"] = list(self.place_ids)
        return rec


@dataclass(frozen=True, slots=True)
class PartEntry:
    """One entry as an entry-extractor subagent wrote it to a part file
    (`03_structured/parts/page_NNNN.json`), before merge assigns identity and
    resolves targets. A `dict` is the wire format only; merge parses each part
    entry into this record at its read boundary (`from_dict`), then builds the
    final `Entry`. Place-only fields (place_type/elevation) and Route-only fields
    (peak/…/place_names) stay at their defaults on the other kind.

    The extractor emits only `start_quote`/`end_quote` boundary anchors, not the
    verbatim text; merge slices the `Entry.description` between them from the
    cleaned page (see slicing.py, #80)."""

    kind: Kind = "route"
    entry_id_raw: str | None = None
    name: str | None = None
    summary: str | None = None
    # Boundary anchors: the entry's first and last words, for merge to slice its
    # verbatim description out of the cleaned page text.
    start_quote: str | None = None
    end_quote: str | None = None
    # Place-only verbatim metadata.
    place_type: str | None = None
    elevation: str | None = None
    # Route-only verbatim metadata.
    peak: str | None = None
    grade: str | None = None
    first_ascent: str | None = None
    time: str | None = None
    height_m: str | None = None
    # Traverse target place-names for merge to resolve (route-only).
    place_names: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PartEntry:
        """Parse a part-file entry dict into a record. Absent fields fall back to
        the dataclass defaults, matching the extractor's omit/`null` contract."""
        return cls(
            kind=raw.get("kind", "route"),
            entry_id_raw=raw.get("entry_id_raw"),
            name=raw.get("name"),
            summary=raw.get("summary"),
            start_quote=raw.get("start_quote"),
            end_quote=raw.get("end_quote"),
            place_type=raw.get("place_type"),
            elevation=raw.get("elevation"),
            peak=raw.get("peak"),
            grade=raw.get("grade"),
            first_ascent=raw.get("first_ascent"),
            time=raw.get("time"),
            height_m=raw.get("height_m"),
            place_names=list(raw.get("place_names") or []),
        )


@dataclass(frozen=True, slots=True)
class PageMeta:
    """Per-page metadata from the deterministic extractor (manifest.jsonl):
    page number, file stem, stripped char count, rotation, image count, the
    largest embedded image's dims (or None), and whether the page is a
    text-poor sketch/diagram scan."""

    page: int
    stem: str
    char_count: int
    rotation: int
    n_images: int
    largest_image: tuple[int, int] | None
    is_sketch: bool

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PageMeta:
        img = raw.get("largest_image")
        return cls(
            page=raw["page"],
            stem=raw["stem"],
            char_count=raw["char_count"],
            rotation=raw["rotation"],
            n_images=raw["n_images"],
            largest_image=(int(img[0]), int(img[1])) if img else None,
            is_sketch=raw["is_sketch"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "stem": self.stem,
            "char_count": self.char_count,
            "rotation": self.rotation,
            "n_images": self.n_images,
            "largest_image": list(self.largest_image) if self.largest_image else None,
            "is_sketch": self.is_sketch,
        }
