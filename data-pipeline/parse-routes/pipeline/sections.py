"""Read the guidebook's section map and render it for the entry-extractor.

Deterministic, no LLM. The **toc-extractor** subagent reads the guide's
Inhaltsverzeichnis and writes `03_structured/sections.json` — the book's
top-level sections (`Täler und Talorte`, `Hütten und Zugangswege`, `Übergänge
und Höhenwege`, `Gipfel und Gipfelrouten`, …), each mapped to a canonical
`role` and the book page it opens on. This module parses that artifact into a
typed `SectionMap`, validates it, and renders the **section block** the
orchestrator injects into every entry-extractor so classification is anchored to
the book's own structure rather than guessed per page (ADR-0005).

The behavioural role is `traverses` — the "Übergänge und Höhenwege" section,
whose itineraries are Traverses (filed under no Place). In the other content
sections an itinerary is an ordinary Route filed under the preceding Place.

  python -m pipeline.sections plan   --guide <id>   # TOC page stems to read
  python -m pipeline.sections render --guide <id>   # the injectable block

`plan` prints the Inhaltsverzeichnis page stems (from `toc_pages`) for the
orchestrator to hand the toc-extractor; `render` prints the block once
`sections.json` exists.
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import GuideConfig, load_guide, page_name
from .records import Section, SectionMap, SectionRole

# What each role means for classification, phrased for the extractor prompt.
# Guide-agnostic: the guide's printed titles live in the data, the policy here.
_ROLE_POLICY: dict[SectionRole, str] = {
    "front_matter": "front matter — holds no Entries; skip.",
    "valley_places": (
        "valley places — Places (towns/localities) and any short Routes filed "
        "under them."
    ),
    "huts": "huts — Places (huts) and the Routes (Zugänge) filed under them.",
    "traverses": (
        "TRAVERSES — every itinerary here is kind=traverse: a range-wide tour "
        "filed under NO Place (no Destination). Not kind=route."
    ),
    "peaks": "peaks — Places (summits) and the Routes filed under them.",
    "back_matter": "back matter — holds no Entries; skip.",
}


def load_section_map(cfg: GuideConfig) -> SectionMap:
    """Read and validate `sections.json` into a SectionMap."""
    if not cfg.section_map.exists():
        sys.exit(f"No section map at {cfg.section_map} — run the toc-extractor first.")
    raw = json.loads(cfg.section_map.read_text(encoding="utf-8"))
    section_map = SectionMap.from_dict(raw)
    _validate(section_map)
    return section_map


def _validate(section_map: SectionMap) -> None:
    """Fail loudly on a malformed map: unknown role, non-ascending pages, or a
    missing traverse section (the one role the classification turns on)."""
    sections = section_map.sections
    if not sections:
        sys.exit("Section map is empty — the toc-extractor found no sections.")
    for s in sections:
        if s.role not in _ROLE_POLICY:
            sys.exit(f"Section map has unknown role {s.role!r} ({s.title!r}).")
    pages = [s.book_page for s in sections]
    if pages != sorted(pages):
        sys.exit(f"Section map pages are not ascending: {pages}.")
    if not any(s.role == "traverses" for s in sections):
        sys.exit("Section map has no 'traverses' section (Übergänge und Höhenwege).")


def _page_range(sections: list[Section], i: int) -> str:
    """The book-page span of section `i`: up to the next section's start, or open
    for the last."""
    start = sections[i].book_page
    if i + 1 < len(sections):
        return f"book pp. {start}–{sections[i + 1].book_page - 1}"
    return f"book pp. {start}+"


def render_section_block(section_map: SectionMap) -> str:
    """Render the section map as a plain block for the extractor prompt: one line
    per section with its page range and classification policy."""
    lines = [
        "Guidebook structure from the Inhaltsverzeichnis (ADR-0005). Classify each",
        "entry by the section its page falls in — the section title is reprinted",
        "in the running header at the top of every page:",
    ]
    for i, s in enumerate(section_map.sections):
        lines.append(
            f"- {s.title} ({_page_range(section_map.sections, i)}) — {_ROLE_POLICY[s.role]}"
        )
    lines.append(
        "On a page that straddles two sections (both running headers present), "
        "classify each entry by the heading it sits under."
    )
    return "\n".join(lines)


def toc_page_stems(cfg: GuideConfig) -> list[str]:
    """The Inhaltsverzeichnis page stems for the toc-extractor to read.

    `toc_pages` are 1-based book-scan page numbers; `page_name` is 0-based, so a
    configured page N maps to stem `page_name(N - 1)` (= `page_{N:04d}`)."""
    return [page_name(p - 1) for p in cfg.toc_pages]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Plan/render a guide's section map for the entry-extractor."
    )
    ap.add_argument(
        "action",
        choices=["plan", "render"],
        help="plan: print TOC page stems; render: print the section block",
    )
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    args = ap.parse_args()
    cfg = load_guide(args.guide)
    if args.action == "plan":
        stems = toc_page_stems(cfg)
        if not stems:
            sys.exit(f"no toc_pages configured for guide {cfg.id!r}.")
        print("\n".join(stems))
    else:
        print(render_section_block(load_section_map(cfg)))


if __name__ == "__main__":
    main()
