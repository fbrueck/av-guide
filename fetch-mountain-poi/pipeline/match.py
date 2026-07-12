"""Resolve route anchors (the `peak` field) against the gazetteer.

Exact matching on normalized names only — the fuzzy cascade, tie review and
LLM adjudication are later stages. Anchors the exact matcher cannot resolve
(no candidate, or several same-name candidates) are written to anchor_open.jsonl
and counted in the funnel; nothing is silently dropped.

  python -m pipeline.match

Outputs: pois.jsonl (deduplicated registry), route_pois.jsonl (route<->POI
links with anchor flag), pois.geojson (webapp export).
"""
from __future__ import annotations

import json
import re
import sys

from . import config

# Trailing elevation as the book writes it: "Höllentorkopf, 2150 m".
_ELEV_SUFFIX = re.compile(r",?\s*\(?\d{3,4}\s*m\)?\.?\s*$")
_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
# Cable-car station naming drift (#11): the book writes "Bergstation der
# Kreuzeckbahn"; OSM has "Kreuzeckbahn Bergstation", "Talstation Hausbergbahn",
# even "Bergstation Hausberg". Canonicalize both sides (word order, dropped
# article, "-bahn" suffix of the lift name) to "<lift> <berg|tal|mittel>station".
_STATION_PREFIX = re.compile(r"^(berg|tal|mittel)station\s+(?:de[rs]\s+)?(.+)$")
_STATION_SUFFIX = re.compile(r"^(.+?)\s+(berg|tal|mittel)station$")


def strip_elevation(surface: str) -> str:
    return _ELEV_SUFFIX.sub("", surface).strip(" ,")


def _canon_station(s: str) -> str:
    """Canonical form for station names (s already casefolded); non-station
    names pass through unchanged."""
    if m := _STATION_PREFIX.match(s):
        position, lift = m.group(1), m.group(2)
    elif m := _STATION_SUFFIX.match(s):
        lift, position = m.group(1), m.group(2)
    else:
        return s
    return f"{re.sub(r'bahn$', '', lift)} {position}station"


def norm_key(name: str) -> str:
    """Matching key: casefolded, transliterated, all non-alphanumerics removed
    (so 'Knorr-Hütte' and 'Knorrhütte' collide)."""
    s = _canon_station(strip_elevation(name).casefold()).translate(_TRANSLIT)
    return re.sub(r"[^a-z0-9]", "", s)


def out_of_scope_reason(name: str) -> str | None:
    """Reason string if the name belongs to a class deliberately outside the
    gazetteer's scope (config.OUT_OF_SCOPE), else None."""
    stripped = strip_elevation(name)
    for pattern, reason in config.OUT_OF_SCOPE:
        if re.search(pattern, stripped, re.IGNORECASE):
            return reason
    return None


def poi_id(osm_ref: str) -> str:
    return "osm-" + osm_ref.replace("/", "-")


def load_jsonl(path) -> list[dict]:
    if not path.exists():
        sys.exit(f"missing {path} — run the earlier stage first.")
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def match_anchors(routes: list[dict], gazetteer: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    """Returns (pois by id, route->poi links, open cases)."""
    index: dict[str, list[dict]] = {}
    for entry in gazetteer:
        index.setdefault(norm_key(entry["name"]), []).append(entry)

    pois: dict[str, dict] = {}
    links: list[dict] = []
    open_cases: list[dict] = []

    for route in routes:
        surface = route.get("peak")
        if not surface:
            continue
        candidates = index.get(norm_key(surface), [])
        if len(candidates) == 1:
            entry = candidates[0]
            pid = poi_id(entry["osm"])
            poi = pois.setdefault(
                pid,
                {"poi_id": pid, **entry, "aliases": [], "match": {"method": "exact"}},
            )
            alias = strip_elevation(surface)
            if alias != poi["name"] and alias not in poi["aliases"]:
                poi["aliases"].append(alias)
            links.append(
                {"route_id": route["route_id"], "poi_id": pid, "surface": surface, "is_anchor": True}
            )
        else:
            reason = None if candidates else out_of_scope_reason(surface)
            case = {
                "route_id": route["route_id"],
                "surface": surface,
                "status": "tie" if candidates else ("skipped" if reason else "unmatched"),
                "candidates": [
                    {"osm": c["osm"], "name": c["name"], "type": c["type"], "ele": c["ele"]}
                    for c in candidates
                ],
            }
            if reason:
                case["reason"] = reason
            open_cases.append(case)
    return pois, links, open_cases


def to_geojson(pois: dict, links: list[dict]) -> dict:
    n_routes: dict[str, int] = {}
    for link in links:
        n_routes[link["poi_id"]] = n_routes.get(link["poi_id"], 0) + 1
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
            "properties": {
                "poi_id": p["poi_id"],
                "name": p["name"],
                "type": p["type"],
                "ele": p["ele"],
                "osm": p["osm"],
                "aliases": p["aliases"],
                "n_routes": n_routes.get(p["poi_id"], 0),
            },
        }
        for p in pois.values()
    ]
    return {"type": "FeatureCollection", "features": features}


def main() -> None:
    routes = load_jsonl(config.ROUTES_JSONL)
    gazetteer = load_jsonl(config.GAZETTEER)
    pois, links, open_cases = match_anchors(routes, gazetteer)

    config.MATCH_DIR.mkdir(parents=True, exist_ok=True)
    config.FINAL_DIR.mkdir(parents=True, exist_ok=True)
    with config.ANCHOR_OPEN.open("w", encoding="utf-8") as f:
        for case in open_cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
    with config.POIS_JSONL.open("w", encoding="utf-8") as f:
        for poi in pois.values():
            f.write(json.dumps(poi, ensure_ascii=False) + "\n")
    with config.ROUTE_POIS_JSONL.open("w", encoding="utf-8") as f:
        for link in links:
            f.write(json.dumps(link, ensure_ascii=False) + "\n")
    config.POIS_GEOJSON.write_text(
        json.dumps(to_geojson(pois, links), ensure_ascii=False), encoding="utf-8"
    )

    with_anchor = sum(1 for r in routes if r.get("peak"))
    ties = sum(1 for c in open_cases if c["status"] == "tie")
    skipped = sum(1 for c in open_cases if c["status"] == "skipped")
    print(
        f"[match] routes: {len(routes)}, with anchor: {with_anchor} -> "
        f"matched: {len(links)} ({len(pois)} unique POIs), "
        f"ties: {ties}, skipped: {skipped}, "
        f"unmatched: {len(open_cases) - ties - skipped} "
        f"(open cases -> {config.ANCHOR_OPEN})",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
