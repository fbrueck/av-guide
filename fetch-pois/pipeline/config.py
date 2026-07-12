"""Per-guide configuration for the fetch-pois pipeline.

A guide is described by one external YAML at `guides/<id>/config.yml` (repo
root): shared top-level facts (id, bbox) plus a `fetch-pois:` subsection.
`load_guide(id)` reads it into an immutable `GuideConfig` that every pipeline
step takes as an argument — there is no module-level global config.

The fixed on-disk stage layout is NOT in the YAML: it lives here as path
helpers deriving from `cfg.data_root` (= `guides/<id>/data/fetch-pois`).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# Repo root: guides/ and each pipeline dir are direct children of it, and this
# file is <repo>/fetch-pois/pipeline/config.py.
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"


@dataclass(frozen=True)
class GuideConfig:
    """Everything the fetch-pois steps need for one guide. Values come from the
    guide's config.yml; paths derive from data_root."""

    id: str
    bbox: tuple[float, float, float, float]
    data_root: Path
    routes_jsonl: Path  # upstream parse-routes index this guide consumes
    tag_map: dict[str, list[tuple[str, str]]]
    guarded_tag_map: dict[str, list[tuple[str, str]]]
    deduped_types: frozenset[str]
    settlement_exclusion_km: float
    out_of_scope: tuple[tuple[str, str], ...]
    overpass_url: str

    # --- path helpers (fixed layout, derived from data_root) ---
    @property
    def gazetteer_dir(self) -> Path:
        return self.data_root / "01_gazetteer"

    @property
    def overpass_raw(self) -> Path:  # cached raw response — reruns are offline
        return self.gazetteer_dir / "overpass_raw.json"

    @property
    def gazetteer(self) -> Path:
        return self.gazetteer_dir / "gazetteer.jsonl"

    @property
    def mentions_dir(self) -> Path:  # LLM-extracted mentions
        return self.data_root / "02_mentions"

    @property
    def mention_parts(self) -> Path:  # one part file per route — resumability unit
        return self.mentions_dir / "parts"

    @property
    def match_dir(self) -> Path:  # matcher bookkeeping (open cases, reports)
        return self.data_root / "03_matched"

    @property
    def final_dir(self) -> Path:  # webapp-facing artifacts
        return self.data_root / "04_final"

    @property
    def pois_jsonl(self) -> Path:
        return self.final_dir / "pois.jsonl"

    @property
    def route_pois_jsonl(self) -> Path:
        return self.final_dir / "route_pois.jsonl"

    @property
    def pois_geojson(self) -> Path:
        return self.final_dir / "pois.geojson"

    @property
    def review(self) -> Path:  # open tie cases + recorded decisions/verdicts
        return self.match_dir / "review.jsonl"

    @property
    def unmatched(self) -> Path:  # mentions with no surviving candidate
        return self.match_dir / "unmatched.jsonl"

    @property
    def funnel(self) -> Path:  # per-type cascade counts for `plan funnel`
        return self.match_dir / "funnel.json"

    @property
    def adjudication_queue(self) -> Path:  # open cases for `plan adjudicate`
        return self.match_dir / "adjudication_queue.jsonl"

    @property
    def verdicts_dir(self) -> Path:  # one verdict file per case — resumability unit
        return self.match_dir / "verdicts"


def _pairs(raw) -> list[tuple[str, str]]:
    """YAML nested lists -> list of (key, value) tuples."""
    return [(str(k), str(v)) for k, v in raw]


def load_guide(guide_id: str) -> GuideConfig:
    """Read guides/<id>/config.yml into a GuideConfig for the fetch-pois stages."""
    cfg_path = REPO_ROOT / "guides" / guide_id / "config.yml"
    if not cfg_path.exists():
        sys.exit(f"no guide config at {cfg_path} — check the --guide id.")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    section = raw.get("fetch-pois", {}) or {}

    guide_dir = REPO_ROOT / "guides" / guide_id
    return GuideConfig(
        id=raw["id"],
        bbox=tuple(raw["bbox"]),
        data_root=guide_dir / "data" / "fetch-pois",
        # Upstream routes index by convention — no hardcoded cross-project hop.
        routes_jsonl=guide_dir
        / "data"
        / "parse-routes"
        / "03_structured"
        / "routes.jsonl",
        tag_map={
            t: _pairs(pairs) for t, pairs in (section.get("tag_map") or {}).items()
        },
        guarded_tag_map={
            t: _pairs(pairs)
            for t, pairs in (section.get("guarded_tag_map") or {}).items()
        },
        deduped_types=frozenset(section.get("deduped_types") or []),
        settlement_exclusion_km=float(section.get("settlement_exclusion_km", 1.0)),
        out_of_scope=tuple(
            (o["pattern"], o["reason"]) for o in (section.get("out_of_scope") or [])
        ),
        overpass_url=section.get("overpass_url") or DEFAULT_OVERPASS_URL,
    )
