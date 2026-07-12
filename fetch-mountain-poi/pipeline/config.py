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

REVIEW = MATCH_DIR / "review.jsonl"        # open tie cases + recorded decisions/verdicts
UNMATCHED = MATCH_DIR / "unmatched.jsonl"  # mentions with no surviving candidate
FUNNEL = MATCH_DIR / "funnel.json"         # per-type cascade counts for `plan funnel`

# LLM adjudication of cascade leftovers (#6): unmatched mentions that still
# have shortlist candidates are queued for the match-adjudicator subagent.
ADJUDICATION_QUEUE = MATCH_DIR / "adjudication_queue.jsonl"  # open cases for `plan adjudicate`
VERDICTS_DIR = MATCH_DIR / "verdicts"  # one verdict file per case — the resumability unit

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

# Valley-floor inns and serviced houses the 1996 book calls Hütten/Häuser are
# often tagged amenity=restaurant / tourism=chalet / tourism=guest_house in
# OSM (Bockhütte, Kreuzalm, Kreuzjochhaus, Bayernhaus, … — #14). Adding those
# tags to TAG_MAP directly would ingest every town restaurant in
# Garmisch-Partenkirchen, so they are guarded instead: an element classified
# only via GUARDED_TAG_MAP is kept when it is
#   1. at least SETTLEMENT_EXCLUSION_KM from every settlement entry
#      (place=town/village/hamlet/suburb) fetched in the same run, and
#   2. gap-filling — its normalized name is not already in the gazetteer
#      (so a hut's restaurant sub-element never duplicates the hut, and
#      same-named entries can't turn existing exact matches into ties).
# TAG_MAP wins over GUARDED_TAG_MAP: a tourism=alpine_hut that also carries
# amenity=restaurant is a plain (unguarded) hut.
GUARDED_TAG_MAP: dict[str, list[tuple[str, str]]] = {
    "hut": [
        ("amenity", "restaurant"),
        ("tourism", "chalet"),
        ("tourism", "guest_house"),
    ],
}
SETTLEMENT_EXCLUSION_KM = 1.0

# Linear features arrive from Overpass split into many same-named segments
# (a path or stream is dozens of ways). For these types the gazetteer keeps
# one representative entry per name — unlike e.g. peaks, where two elements
# with the same name are genuinely distinct places.
DEDUPED_TYPES = {"path", "water"}

# Shortlist for the LLM adjudicator (#6): the top candidates by RapidFuzz
# ratio on the normalized names, without the cascade's type/elevation guards
# (the adjudicator sees each candidate's type and elevation and judges drift
# the deterministic guards can't). Mentions whose best candidate scores below
# the floor have nothing worth judging and stay plain unmatched.
ADJUDICATION_SHORTLIST = 10   # max candidates per case
ADJUDICATION_CUTOFF = 60.0    # minimum RapidFuzz ratio to enter the shortlist

# Mention classes deliberately outside the gazetteer's scope. A mention whose
# (elevation-stripped) name matches one of these patterns is recorded as
# status "skipped" with the given reason instead of polluting the unmatched
# funnel: mountain ranges/regions (Wettersteingebirge) have no useful point
# representation, so we never fetch them from Overpass (#11).
OUT_OF_SCOPE: list[tuple[str, str]] = [
    (r"gebirge$", "mountain range/region — deliberately not in the gazetteer (no point representation)"),
]
