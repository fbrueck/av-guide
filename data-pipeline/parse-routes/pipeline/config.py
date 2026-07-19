"""Per-guide configuration for the parse-routes pipeline.

A guide is described by one external YAML at `guides/<id>/config.yml` (repo
root): shared top-level facts (id, bbox) plus a `parse-routes:` subsection.
`load_guide(id)` reads it into an immutable `GuideConfig` that every pipeline
step takes as an argument — there is no module-level global config.

The fixed on-disk stage layout is NOT in the YAML: it lives here as path
helpers deriving from `cfg.data_root` (= `guides/<id>/data/parse-routes`).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# Repo root: guides/ lives here, and this file is
# <repo>/data-pipeline/parse-routes/pipeline/config.py.
REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class GuideFacts:
    """Bibliographic facts about the guidebook. Guide facts (not algorithm
    behaviour), so they come from config.yml. The orchestrator injects them into
    the LLM subagents so those prompts stay guide-agnostic — no guide is named in
    a prompt body (#147)."""

    title: str
    author: str
    edition: str
    year: int
    language: str


@dataclass(frozen=True)
class GuideConfig:
    """Everything the parse-routes steps need for one guide. Values come from
    the guide's config.yml; paths derive from data_root."""

    id: str
    bbox: tuple[float, float, float, float]  # shared top-level fact
    facts: GuideFacts  # shared top-level bibliographic facts (#147)
    data_root: Path
    pdf: Path  # source PDF, resolved under data_root
    min_text_chars: int
    # Scan page(s) holding the guidebook's Inhaltsverzeichnis, for the
    # toc-extractor to read into the section map (ADR-0005). Empty when a guide
    # is not (yet) onboarded to TOC-driven classification.
    toc_pages: tuple[int, ...]

    # --- path helpers (fixed layout, derived from data_root) ---
    @property
    def raw_dir(self) -> Path:  # deterministic pymupdf extraction
        return self.data_root / "01_raw"

    @property
    def clean_dir(self) -> Path:  # LLM-cleaned OCR text
        return self.data_root / "02_clean"

    @property
    def struct_dir(self) -> Path:  # parsed Entry records (Places + Routes)
        return self.data_root / "03_structured"

    @property
    def raw_pages(self) -> Path:
        return self.raw_dir / "pages"

    @property
    def clean_pages(self) -> Path:
        return self.clean_dir / "pages"

    @property
    def section_map(self) -> Path:  # guidebook structure from the TOC (ADR-0005)
        return self.struct_dir / "sections.json"

    @property
    def struct_parts(
        self,
    ) -> Path:  # one <stem>.json of Entries per page (resumability unit)
        return self.struct_dir / "parts"

    @property
    def entries_dir(self) -> Path:  # one JSON file per Entry (final artifact)
        return self.struct_dir / "entries"

    @property
    def routes_jsonl(self) -> Path:  # combined index of all entries
        return self.struct_dir / "routes.jsonl"

    @property
    def routes_json(self) -> Path:  # route-map data contract (plain JSON array)
        return self.struct_dir / "routes.json"

    @property
    def unsliced_report(self) -> Path:  # one record per unsliceable entry (#110)
        return self.struct_dir / "unsliced.jsonl"

    @property
    def repairs_dir(self) -> Path:  # one corrected-anchor file per entry (#113)
        return self.struct_dir / "repairs"

    @property
    def manifest(self) -> Path:  # one JSON record per page (metadata)
        return self.raw_dir / "manifest.jsonl"


def load_guide(guide_id: str) -> GuideConfig:
    """Read guides/<id>/config.yml into a GuideConfig for the parse-routes stages."""
    cfg_path = REPO_ROOT / "guides" / guide_id / "config.yml"
    if not cfg_path.exists():
        sys.exit(f"no guide config at {cfg_path} — check the --guide id.")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    section = raw.get("parse-routes", {}) or {}
    facts_raw = raw.get("facts", {}) or {}

    data_root = REPO_ROOT / "guides" / guide_id / "data" / "parse-routes"
    return GuideConfig(
        id=raw["id"],
        bbox=tuple(raw["bbox"]),
        facts=GuideFacts(
            title=facts_raw["title"],
            author=facts_raw["author"],
            edition=facts_raw["edition"],
            year=int(facts_raw["year"]),
            language=facts_raw["language"],
        ),
        data_root=data_root,
        pdf=data_root / section["pdf"],
        min_text_chars=int(section.get("min_text_chars", 200)),
        toc_pages=tuple(int(p) for p in section.get("toc_pages", []) or []),
    )


def page_name(index: int) -> str:
    """Zero-padded, 1-based page file stem, e.g. page_0001."""
    return f"page_{index + 1:04d}"
