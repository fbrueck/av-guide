"""Shared paths and constants for the mountain-POI pipeline."""
from __future__ import annotations

import os
from pathlib import Path

# Package root = parent of the `pipeline/` package.
ROOT = Path(__file__).resolve().parent.parent

# Data root is overridable so tests (and ad-hoc runs) can point the stages
# at a fixture directory. Same for the route index consumed from the
# digitization package.
DATA = Path(os.environ.get("AV_POI_DATA", ROOT / "data"))
ROUTES_JSONL = Path(
    os.environ.get(
        "AV_POI_ROUTES",
        ROOT.parent / "digitize-av-guide" / "data" / "03_structured" / "routes.jsonl",
    )
)

GAZETTEER_DIR = DATA / "01_gazetteer"
OVERPASS_RAW = GAZETTEER_DIR / "overpass_raw.json"  # cached raw response — reruns are offline
GAZETTEER = GAZETTEER_DIR / "gazetteer.jsonl"

MENTIONS_DIR = DATA / "02_mentions"   # LLM-extracted mentions
MENTION_PARTS = MENTIONS_DIR / "parts"  # one part file per route — the resumability unit
MATCH_DIR = DATA / "03_matched"       # matcher bookkeeping (open cases, reports)
FINAL_DIR = DATA / "04_final"         # webapp-facing artifacts

POIS_JSONL = FINAL_DIR / "pois.jsonl"
ROUTE_POIS_JSONL = FINAL_DIR / "route_pois.jsonl"
POIS_GEOJSON = FINAL_DIR / "pois.geojson"

ANCHOR_OPEN = MATCH_DIR / "anchor_open.jsonl"  # anchors the exact matcher could not resolve

OVERPASS_URL = os.environ.get("AV_POI_OVERPASS_URL", "https://overpass-api.de/api/interpreter")

# Wetterstein range plus its trailhead villages (Garmisch, Hammersbach,
# Ehrwald, Leutasch, Mittenwald): (south, west, north, east).
BBOX = (47.30, 10.85, 47.55, 11.35)

# Taxonomy type -> OSM tags that put an element in that type. Order matters:
# an element is classified by the first matching entry, so specific alpine
# types come before the `locality` catch-all.
TAG_MAP: dict[str, list[tuple[str, str]]] = {
    "peak": [("natural", "peak")],
    "pass": [("natural", "saddle"), ("mountain_pass", "yes")],
    "hut": [
        ("tourism", "alpine_hut"),
        ("tourism", "wilderness_hut"),
        ("amenity", "shelter"),
        ("place", "farm"),
    ],
    "glacier": [("natural", "glacier")],
    "valley": [("natural", "valley")],
    "ridge": [("natural", "ridge"), ("natural", "arete")],
    "station": [("aerialway", "station")],
    # town/suburb: Garmisch-Partenkirchen is place=town, Garmisch a suburb of
    # it — both were unmatched in the extraction demo (#11).
    "settlement": [
        ("place", "town"),
        ("place", "village"),
        ("place", "hamlet"),
        ("place", "suburb"),
    ],
    "bridge": [("man_made", "bridge"), ("natural", "gorge")],
    # Named paths/Steige (Stangensteig, Klammweg, …) and water features
    # (Blaue Gumpe, Partnach, …) — coverage gaps found during extraction (#11).
    "path": [("highway", "path"), ("highway", "track"), ("highway", "via_ferrata")],
    "water": [("natural", "water"), ("waterway", "river"), ("waterway", "stream")],
    "locality": [("place", "locality")],
}

# Linear features arrive from Overpass split into many same-named segments
# (a path or stream is dozens of ways). For these types the gazetteer keeps
# one representative entry per name — unlike e.g. peaks, where two elements
# with the same name are genuinely distinct places.
DEDUPED_TYPES = {"path", "water"}

# Mention classes deliberately outside the gazetteer's scope. A mention whose
# (elevation-stripped) name matches one of these patterns is recorded as
# status "skipped" with the given reason instead of polluting the unmatched
# funnel: mountain ranges/regions (Wettersteingebirge) have no useful point
# representation, so we never fetch them from Overpass (#11).
OUT_OF_SCOPE: list[tuple[str, str]] = [
    (r"gebirge$", "mountain range/region — deliberately not in the gazetteer (no point representation)"),
]
