"""Stage 1: build the OSM gazetteer for the configured bbox.

One Overpass query fetches every named element matching the taxonomy tag map
inside the guide's bbox, plus the guarded lodging/restaurant tags
(guarded_tag_map, #14) that are only admitted outside settlement radius and
where the name fills a gap. The raw response is cached to disk so reruns are
offline and reproducible; pass --refresh to refetch.

  python -m pipeline.gazetteer --guide <id> [--refresh]

Output: gazetteer.jsonl — one entry per named element with taxonomy type,
representative coordinates (node position or way/relation center), elevation
where OSM has one, and the OSM reference.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.parse
import urllib.request

from .config import GuideConfig, load_guide
from .match import norm_key

_ELE_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def build_query(cfg: GuideConfig) -> str:
    s, w, n, e = cfg.bbox
    lines = []
    for pairs in (*cfg.tag_map.values(), *cfg.guarded_tag_map.values()):
        for key, value in pairs:
            lines.append(f'  nwr["{key}"="{value}"]["name"]({s},{w},{n},{e});')
    body = "\n".join(dict.fromkeys(lines))  # dedupe repeated tag pairs across types
    return f"[out:json][timeout:180];\n(\n{body}\n);\nout center tags;\n"


def fetch(cfg: GuideConfig, refresh: bool) -> dict:
    if cfg.overpass_raw.exists() and not refresh:
        print(f"[gazetteer] using cached response {cfg.overpass_raw}", file=sys.stderr)
        return json.loads(cfg.overpass_raw.read_text(encoding="utf-8"))

    print(f"[gazetteer] querying {cfg.overpass_url}", file=sys.stderr)
    req = urllib.request.Request(
        cfg.overpass_url,
        data=urllib.parse.urlencode({"data": build_query(cfg)}).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            # Overpass rejects generic library user agents (HTTP 406) and asks
            # clients to identify themselves.
            "User-Agent": "av-guide-poi-pipeline/0.1 (github.com/fbrueck/av-guide)",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode("utf-8")
    cfg.gazetteer_dir.mkdir(parents=True, exist_ok=True)
    cfg.overpass_raw.write_text(raw, encoding="utf-8")
    print(f"[gazetteer] cached raw response to {cfg.overpass_raw}", file=sys.stderr)
    return json.loads(raw)


def classify(tags: dict, tag_map: dict[str, list[tuple[str, str]]]) -> str | None:
    for poi_type, pairs in tag_map.items():
        if any(tags.get(key) == value for key, value in pairs):
            return poi_type
    return None


def parse_ele(tags: dict) -> float | None:
    m = _ELE_RE.search(tags.get("ele", ""))
    return float(m.group().replace(",", ".")) if m else None


# For deduped linear types, prefer the element that represents the whole
# feature: a relation over its member ways, a way over a node; then lowest id
# so the pick is deterministic.
_OSM_RANK = {"relation": 0, "way": 1, "node": 2}


def dedupe_linear(entries: list[dict], cfg: GuideConfig) -> list[dict]:
    """Collapse same-named entries of the guide's deduped_types (paths/streams
    arrive as many segments) to one representative each; other types pass
    through."""
    best: dict[tuple[str, str], dict] = {}
    for entry in entries:
        if entry["type"] not in cfg.deduped_types:
            continue
        key = (entry["type"], entry["name"])
        kind, osm_id = entry["osm"].split("/")
        rank = (_OSM_RANK[kind], int(osm_id))
        if key not in best or rank < best[key][0]:
            best[key] = (rank, entry)
    kept = {id(entry) for _, entry in best.values()}
    return [
        e for e in entries if e["type"] not in cfg.deduped_types or id(e) in kept
    ]


def dist_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular approximation — plenty accurate at bbox scale."""
    dlat = (lat2 - lat1) * 111.32
    dlon = (lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


def admit_guarded(candidates: list[dict], entries: list[dict], cfg: GuideConfig) -> list[dict]:
    """Precision guard for guarded_tag_map candidates (#14): admit only
    elements at least settlement_exclusion_km from every settlement entry and
    whose normalized name fills a gap in the (unguarded) gazetteer — so town
    restaurants and duplicates of already-covered features stay out."""
    settlements = [e for e in entries if e["type"] == "settlement"]
    covered = {norm_key(e["name"]) for e in entries}
    return [
        c
        for c in candidates
        if norm_key(c["name"]) not in covered
        and all(
            dist_km(c["lat"], c["lon"], s["lat"], s["lon"])
            >= cfg.settlement_exclusion_km
            for s in settlements
        )
    ]


def parse(raw: dict, cfg: GuideConfig) -> list[dict]:
    entries = []
    guarded = []
    for el in raw.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        center = el.get("center", el)
        lat, lon = center.get("lat"), center.get("lon")
        if not name or lat is None or lon is None:
            continue
        # TAG_MAP wins: a double-tagged element (alpine_hut + restaurant) is a
        # plain hut; only elements covered solely by GUARDED_TAG_MAP are guarded.
        poi_type = classify(tags, cfg.tag_map)
        guarded_type = None if poi_type else classify(tags, cfg.guarded_tag_map)
        if poi_type is None and guarded_type is None:
            continue
        (entries if poi_type else guarded).append(
            {
                "name": name,
                "type": poi_type or guarded_type,
                "lat": lat,
                "lon": lon,
                "ele": parse_ele(tags),
                "osm": f"{el['type']}/{el['id']}",
            }
        )
    entries.extend(admit_guarded(guarded, entries, cfg))
    return dedupe_linear(entries, cfg)


def build_gazetteer(cfg: GuideConfig, refresh: bool) -> list[dict]:
    """Fetch (or reuse the cached response), parse, and write gazetteer.jsonl."""
    entries = parse(fetch(cfg, refresh), cfg)
    cfg.gazetteer_dir.mkdir(parents=True, exist_ok=True)
    with cfg.gazetteer.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    by_type: dict[str, int] = {}
    for entry in entries:
        by_type[entry["type"]] = by_type.get(entry["type"], 0) + 1
    summary = ", ".join(f"{t}: {n}" for t, n in sorted(by_type.items()))
    print(f"[gazetteer] {len(entries)} entries ({summary}) -> {cfg.gazetteer}", file=sys.stderr)
    return entries


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the OSM gazetteer for a guide's bbox.")
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    ap.add_argument("--refresh", action="store_true", help="Refetch even if a cached response exists.")
    args = ap.parse_args()

    build_gazetteer(load_guide(args.guide), args.refresh)


if __name__ == "__main__":
    main()
