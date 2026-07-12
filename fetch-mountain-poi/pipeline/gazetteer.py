"""Stage 1: build the OSM gazetteer for the configured bbox.

One Overpass query fetches every named element matching the taxonomy tag map
inside BBOX. The raw response is cached to disk so reruns are offline and
reproducible; pass --refresh to refetch.

  python -m pipeline.gazetteer [--refresh]

Output: gazetteer.jsonl — one entry per named element with taxonomy type,
representative coordinates (node position or way/relation center), elevation
where OSM has one, and the OSM reference.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request

from . import config

_ELE_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def build_query() -> str:
    s, w, n, e = config.BBOX
    lines = []
    for pairs in config.TAG_MAP.values():
        for key, value in pairs:
            lines.append(f'  nwr["{key}"="{value}"]["name"]({s},{w},{n},{e});')
    body = "\n".join(dict.fromkeys(lines))  # dedupe repeated tag pairs across types
    return f"[out:json][timeout:180];\n(\n{body}\n);\nout center tags;\n"


def fetch(refresh: bool) -> dict:
    if config.OVERPASS_RAW.exists() and not refresh:
        print(f"[gazetteer] using cached response {config.OVERPASS_RAW}", file=sys.stderr)
        return json.loads(config.OVERPASS_RAW.read_text(encoding="utf-8"))

    print(f"[gazetteer] querying {config.OVERPASS_URL}", file=sys.stderr)
    req = urllib.request.Request(
        config.OVERPASS_URL,
        data=urllib.parse.urlencode({"data": build_query()}).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            # Overpass rejects generic library user agents (HTTP 406) and asks
            # clients to identify themselves.
            "User-Agent": "av-guide-poi-pipeline/0.1 (github.com/fbrueck/av-guide)",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode("utf-8")
    config.GAZETTEER_DIR.mkdir(parents=True, exist_ok=True)
    config.OVERPASS_RAW.write_text(raw, encoding="utf-8")
    print(f"[gazetteer] cached raw response to {config.OVERPASS_RAW}", file=sys.stderr)
    return json.loads(raw)


def classify(tags: dict) -> str | None:
    for poi_type, pairs in config.TAG_MAP.items():
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


def dedupe_linear(entries: list[dict]) -> list[dict]:
    """Collapse same-named entries of DEDUPED_TYPES (paths/streams arrive as
    many segments) to one representative each; other types pass through."""
    best: dict[tuple[str, str], dict] = {}
    for entry in entries:
        if entry["type"] not in config.DEDUPED_TYPES:
            continue
        key = (entry["type"], entry["name"])
        kind, osm_id = entry["osm"].split("/")
        rank = (_OSM_RANK[kind], int(osm_id))
        if key not in best or rank < best[key][0]:
            best[key] = (rank, entry)
    kept = {id(entry) for _, entry in best.values()}
    return [
        e for e in entries if e["type"] not in config.DEDUPED_TYPES or id(e) in kept
    ]


def parse(raw: dict) -> list[dict]:
    entries = []
    for el in raw.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        poi_type = classify(tags)
        center = el.get("center", el)
        lat, lon = center.get("lat"), center.get("lon")
        if not name or poi_type is None or lat is None or lon is None:
            continue
        entries.append(
            {
                "name": name,
                "type": poi_type,
                "lat": lat,
                "lon": lon,
                "ele": parse_ele(tags),
                "osm": f"{el['type']}/{el['id']}",
            }
        )
    return dedupe_linear(entries)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the OSM gazetteer for the configured bbox.")
    ap.add_argument("--refresh", action="store_true", help="Refetch even if a cached response exists.")
    args = ap.parse_args()

    entries = parse(fetch(args.refresh))
    config.GAZETTEER_DIR.mkdir(parents=True, exist_ok=True)
    with config.GAZETTEER.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    by_type: dict[str, int] = {}
    for entry in entries:
        by_type[entry["type"]] = by_type.get(entry["type"], 0) + 1
    summary = ", ".join(f"{t}: {n}" for t, n in sorted(by_type.items()))
    print(f"[gazetteer] {len(entries)} entries ({summary}) -> {config.GAZETTEER}", file=sys.stderr)


if __name__ == "__main__":
    main()
