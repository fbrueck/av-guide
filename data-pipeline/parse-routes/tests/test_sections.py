"""The section map is read from the toc-extractor's sections.json into a typed
SectionMap, validated, and rendered into the block the orchestrator injects into
the entry-extractor (ADR-0005). Tests feed a sections.json through the real read
path and assert on the parsed records / rendered block, never dict internals."""

from __future__ import annotations

import json

import pytest
from conftest import run_cli
from pipeline.config import load_guide
from pipeline.records import SectionMap
from pipeline.sections import (
    load_section_map,
    render_section_block,
    toc_page_stems,
)

# A minimal, well-formed map in the shape the toc-extractor writes.
KARWENDEL_SECTIONS = {
    "sections": [
        {"role": "front_matter", "title": "Zum Gebrauch des Führers", "book_page": 8},
        {"role": "valley_places", "title": "Täler und Talorte", "book_page": 20},
        {"role": "huts", "title": "Hütten und Zugangswege", "book_page": 42},
        {"role": "traverses", "title": "Übergänge und Höhenwege", "book_page": 87},
        {"role": "peaks", "title": "Gipfel und Gipfelrouten", "book_page": 125},
        {"role": "back_matter", "title": "Informationsteil", "book_page": 380},
    ]
}


def write_sections(cfg, data: dict) -> None:
    cfg.struct_dir.mkdir(parents=True, exist_ok=True)
    cfg.section_map.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# --- config -------------------------------------------------------------------


def test_toc_pages_load_from_config():
    # The Karwendel guide is onboarded to TOC-driven classification.
    assert load_guide("karwendel").toc_pages == (6,)
    # A guide without the fact loads with an empty tuple, not an error.
    assert load_guide("wetterstein").toc_pages == ()


def test_toc_page_stems_map_book_scan_number_to_stem():
    # toc_pages are 1-based; page stems are page_{N:04d}, so page 6 -> page_0006.
    cfg = load_guide("karwendel")
    assert toc_page_stems(cfg) == ["page_0006"]


# --- read + validate ----------------------------------------------------------


def test_load_section_map_parses_records(cfg):
    write_sections(cfg, KARWENDEL_SECTIONS)
    section_map = load_section_map(cfg)
    assert isinstance(section_map, SectionMap)
    assert [s.role for s in section_map.sections] == [
        "front_matter",
        "valley_places",
        "huts",
        "traverses",
        "peaks",
        "back_matter",
    ]
    traverses = next(s for s in section_map.sections if s.role == "traverses")
    assert traverses.title == "Übergänge und Höhenwege"
    assert traverses.book_page == 87


def test_load_section_map_missing_file_exits(cfg):
    with pytest.raises(SystemExit):
        load_section_map(cfg)


def test_validate_rejects_non_ascending_pages(cfg):
    bad = {"sections": [dict(s) for s in KARWENDEL_SECTIONS["sections"]]}
    bad["sections"][2]["book_page"] = 5  # huts before valley_places
    write_sections(cfg, bad)
    with pytest.raises(SystemExit):
        load_section_map(cfg)


def test_validate_rejects_unknown_role(cfg):
    bad = {"sections": [{"role": "gipfel", "title": "X", "book_page": 1}]}
    write_sections(cfg, bad)
    with pytest.raises(SystemExit):
        load_section_map(cfg)


def test_validate_requires_a_traverses_section(cfg):
    # The one role classification turns on must be present.
    no_trav = {
        "sections": [
            s for s in KARWENDEL_SECTIONS["sections"] if s["role"] != "traverses"
        ]
    }
    write_sections(cfg, no_trav)
    with pytest.raises(SystemExit):
        load_section_map(cfg)


# --- render -------------------------------------------------------------------


def test_render_block_marks_the_traverses_section_and_page_ranges(cfg):
    write_sections(cfg, KARWENDEL_SECTIONS)
    block = render_section_block(load_section_map(cfg))
    # The Übergänge section is called out as producing traverses...
    assert "Übergänge und Höhenwege" in block
    assert "traverse" in block.lower()
    # ...with a bounded range (up to the next section's start - 1)...
    assert "87–124" in block
    # ...and the last section is open-ended.
    assert "380+" in block
    # The straddle rule is spelled out for boundary pages.
    assert "straddle" in block.lower()


# --- CLI ----------------------------------------------------------------------


def test_sections_plan_cli_prints_toc_stems():
    result = run_cli("sections", "plan", "--guide", "karwendel")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "page_0006"
