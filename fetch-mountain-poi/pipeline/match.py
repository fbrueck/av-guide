"""Stage 3: resolve anchors and extracted mentions against the gazetteer.

Every route contributes its `peak` field as an untyped anchor mention, and —
where stage 2 has produced a part file — the typed mentions extracted from
its description. Each mention runs through the deterministic cascade:

  1. exact — gazetteer entries whose normalized name equals the mention's
  2. fuzzy — RapidFuzz ratio >= FUZZY_CUTOFF on the normalized names

Both levels are guarded: a candidate must be taxonomy-compatible with the
mention's type (see _NEAR_GROUPS) and, when both the book and OSM state an
elevation, agree within ELE_TOLERANCE meters. Exactly one surviving candidate
matches; provenance records the method (and score for fuzzy). More than one
candidate at equal footing — same cascade level, same score — is never
auto-resolved: the mention becomes an open case in review.jsonl with
decision: null (non-null decisions already in the file are carried over on
rerun, so review work survives matcher reruns). No surviving candidate at
either level lands in unmatched.jsonl. Both files supersede the old
anchor_open.jsonl.

  python -m pipeline.match

Outputs: pois.jsonl (deduplicated registry with aliases and best-method
provenance, exact > fuzzy), route_pois.jsonl (one link per route/POI pair
with anchor flag), pois.geojson (webapp export), and matcher bookkeeping in
03_matched/: review.jsonl, unmatched.jsonl, funnel.json (rendered by
`python -m pipeline.plan funnel`).
"""
from __future__ import annotations

import json
import re
import sys

from rapidfuzz import fuzz, process

from . import config

FUZZY_CUTOFF = 90.0   # minimum RapidFuzz ratio for a fuzzy candidate
ELE_TOLERANCE = 50.0  # max |book - OSM| elevation difference in meters

# Trailing elevation as the book writes it: "Höllentorkopf, 2150 m".
_ELEV_SUFFIX = re.compile(r",?\s*\(?(\d{3,4})\s*m\)?\.?\s*$")
_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
# Cable-car station naming drift (#11): the book writes "Bergstation der
# Kreuzeckbahn"; OSM has "Kreuzeckbahn Bergstation", "Talstation Hausbergbahn",
# even "Bergstation Hausberg". Canonicalize both sides (word order, dropped
# article, "-bahn" suffix of the lift name) to "<lift> <berg|tal|mittel>station".
_STATION_PREFIX = re.compile(r"^(berg|tal|mittel)station\s+(?:de[rs]\s+)?(.+)$")
_STATION_SUFFIX = re.compile(r"^(.+?)\s+(berg|tal|mittel)station$")

# Taxonomy compatibility for the guards. Same type always matches, and
# `locality` is a catch-all on both sides (the extractor uses it for anything
# with a proper name; OSM's place=locality tags all sorts of features). The
# near-groups cover honest classification drift between book and OSM: a
# Joch/Scharte may be mapped as saddle or peak and named ridge/summit
# distinctions blur (peak/pass/ridge); Alms and Höfe drift between
# place=farm (-> hut) and place=hamlet (-> settlement). Everything else is
# incompatible — a `peak` mention never matches a `settlement`.
_NEAR_GROUPS = ({"peak", "pass", "ridge"}, {"hut", "settlement"})

_METHOD_RANK = {"exact": 2, "fuzzy": 1}
_FUNNEL_COLS = ("mentions", "exact", "fuzzy", "tie", "skipped", "unmatched")


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


def stated_elevation(surface: str) -> float | None:
    m = _ELEV_SUFFIX.search(surface)
    return float(m.group(1)) if m else None


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


def write_jsonl(path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def route_mentions(route: dict) -> tuple[list[dict], bool]:
    """The route's mentions — its anchor (untyped; elevation parsed from the
    surface) first, then the extracted mentions if stage 2 produced a part
    file. Returns (mentions, part file exists)."""
    mentions = []
    if route.get("peak"):
        mentions.append(
            {
                "surface": route["peak"],
                "name": strip_elevation(route["peak"]),
                "type": None,
                "elevation_m": stated_elevation(route["peak"]),
                "is_anchor": True,
            }
        )
    part = config.MENTION_PARTS / f"{route['route_id']}.json"
    if part.exists():
        for m in json.loads(part.read_text(encoding="utf-8"))["mentions"]:
            mentions.append(
                {
                    "surface": m["surface"],
                    "name": m["name"],
                    "type": m["type"],
                    "elevation_m": m.get("elevation_m"),
                    "is_anchor": False,
                }
            )
    return mentions, part.exists()


def passes_guards(mention: dict, entry: dict) -> bool:
    t = mention["type"]
    type_ok = (
        t is None  # anchors carry no type
        or t == entry["type"]
        or "locality" in (t, entry["type"])
        or any(t in g and entry["type"] in g for g in _NEAR_GROUPS)
    )
    ele = mention["elevation_m"]
    ele_ok = ele is None or entry["ele"] is None or abs(ele - entry["ele"]) <= ELE_TOLERANCE
    return type_ok and ele_ok


def resolve(mention: dict, index: dict[str, list[dict]], keys: list[str]) -> tuple[str, list]:
    """Run the cascade for one mention. Returns (method, [(entry, score), ...])
    where method is 'exact'/'fuzzy' (single survivor), 'tie' (several at equal
    footing) or 'unmatched' (none)."""
    key = norm_key(mention["name"])
    exact = [(e, 100.0) for e in index.get(key, []) if passes_guards(mention, e)]
    if exact:
        return ("exact" if len(exact) == 1 else "tie"), exact

    hits = process.extract(key, keys, scorer=fuzz.ratio, score_cutoff=FUZZY_CUTOFF, limit=None)
    survivors = [
        (e, round(score, 1))
        for hit_key, score, _ in hits
        for e in index[hit_key]
        if passes_guards(mention, e)
    ]
    if not survivors:
        return "unmatched", []
    best = max(score for _, score in survivors)
    top = [(e, score) for e, score in survivors if score == best]
    return ("fuzzy" if len(top) == 1 else "tie"), top


def register(pois: dict, mention: dict, entry: dict, method: str, score: float) -> str:
    """Upsert the POI: aliases collect differing surface forms, provenance
    keeps the best method (exact > fuzzy, then highest score)."""
    pid = poi_id(entry["osm"])
    poi = pois.setdefault(pid, {"poi_id": pid, **entry, "aliases": [], "match": None})
    prov = {"method": method} if method == "exact" else {"method": method, "score": score}
    cur = poi["match"]
    if cur is None or (_METHOD_RANK[method], score) > (_METHOD_RANK[cur["method"]], cur.get("score", 100.0)):
        poi["match"] = prov
    for form in (strip_elevation(mention["surface"]), mention["name"]):
        if form != poi["name"] and form not in poi["aliases"]:
            poi["aliases"].append(form)
    return pid


def match_mentions(routes: list[dict], gazetteer: list[dict]):
    """Returns (pois by id, route<->poi links, review cases, unmatched,
    funnel by type, routes with a mention part file)."""
    index: dict[str, list[dict]] = {}
    for entry in gazetteer:
        index.setdefault(norm_key(entry["name"]), []).append(entry)
    keys = list(index)

    pois: dict[str, dict] = {}
    links: dict[tuple[str, str], dict] = {}
    review: list[dict] = []
    unmatched: list[dict] = []
    funnel: dict[str, dict[str, int]] = {}
    with_parts = 0

    for route in sorted(routes, key=lambda r: r["route_id"]):
        rid = route["route_id"]
        mentions, has_part = route_mentions(route)
        with_parts += has_part
        for mention in mentions:
            method, survivors = resolve(mention, index, keys)
            # Classes deliberately outside the gazetteer (#11, config.OUT_OF_SCOPE)
            # count as skipped, not unmatched — but only when nothing matched.
            skip_reason = out_of_scope_reason(mention["name"]) if method == "unmatched" else None
            bucket = funnel.setdefault(
                "anchor" if mention["is_anchor"] else mention["type"],
                dict.fromkeys(_FUNNEL_COLS, 0),
            )
            bucket["mentions"] += 1
            bucket["skipped" if skip_reason else method] += 1
            if method in ("exact", "fuzzy"):
                entry, score = survivors[0]
                pid = register(pois, mention, entry, method, score)
                link = links.setdefault(
                    (rid, pid),
                    {"route_id": rid, "poi_id": pid, "surface": mention["surface"],
                     "is_anchor": mention["is_anchor"]},
                )
                link["is_anchor"] = link["is_anchor"] or mention["is_anchor"]
            elif method == "tie":
                review.append(
                    {
                        "mention": mention["surface"],
                        "name": mention["name"],
                        "type": mention["type"],
                        "route_id": rid,
                        "is_anchor": mention["is_anchor"],
                        "candidates": [
                            {"osm": e["osm"], "name": e["name"], "type": e["type"],
                             "ele": e["ele"], "lat": e["lat"], "lon": e["lon"], "score": score}
                            for e, score in survivors
                        ],
                        "decision": None,
                        "source": "tie",
                    }
                )
            else:
                case = {
                    "route_id": rid,
                    "mention": mention["surface"],
                    "name": mention["name"],
                    "type": mention["type"],
                    "is_anchor": mention["is_anchor"],
                    "elevation_m": mention["elevation_m"],
                }
                if skip_reason:
                    case["skip_reason"] = skip_reason
                unmatched.append(case)
    return pois, list(links.values()), review, unmatched, funnel, with_parts


def carry_decisions(review: list[dict]) -> None:
    """Rerunning the matcher must not lose review work: non-null decisions in
    the existing review.jsonl are carried over to matching open cases."""
    if not config.REVIEW.exists():
        return
    decided = {
        (case["route_id"], case["name"], case["type"], case["is_anchor"]): case["decision"]
        for case in load_jsonl(config.REVIEW)
        if case.get("decision") is not None
    }
    for case in review:
        key = (case["route_id"], case["name"], case["type"], case["is_anchor"])
        if key in decided:
            case["decision"] = decided[key]


def funnel_report(funnel: dict, n_routes: int, with_parts: int) -> dict:
    ordered = dict(sorted(funnel.items(), key=lambda kv: (-kv[1]["mentions"], kv[0])))
    totals = {col: sum(row[col] for row in funnel.values()) for col in _FUNNEL_COLS}
    return {
        "routes": {"total": n_routes, "with_mentions": with_parts},
        "types": ordered,
        "totals": totals,
    }


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
    pois, links, review, unmatched, funnel, with_parts = match_mentions(routes, gazetteer)
    carry_decisions(review)
    report = funnel_report(funnel, len(routes), with_parts)

    config.MATCH_DIR.mkdir(parents=True, exist_ok=True)
    config.FINAL_DIR.mkdir(parents=True, exist_ok=True)
    # review.jsonl + unmatched.jsonl supersede the old anchor-only artifact.
    (config.MATCH_DIR / "anchor_open.jsonl").unlink(missing_ok=True)
    write_jsonl(config.REVIEW, review)
    write_jsonl(config.UNMATCHED, unmatched)
    config.FUNNEL.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    write_jsonl(config.POIS_JSONL, list(pois.values()))
    write_jsonl(config.ROUTE_POIS_JSONL, links)
    config.POIS_GEOJSON.write_text(
        json.dumps(to_geojson(pois, links), ensure_ascii=False), encoding="utf-8"
    )

    totals = report["totals"]
    print(
        f"[match] routes: {len(routes)} ({with_parts} with extracted mentions) -> "
        f"mentions: {totals['mentions']}, exact: {totals['exact']}, "
        f"fuzzy: {totals['fuzzy']}, ties: {totals['tie']} (-> {config.REVIEW}), "
        f"skipped: {totals['skipped']}, "
        f"unmatched: {totals['unmatched']} (-> {config.UNMATCHED}); "
        f"{len(pois)} unique POIs, {len(links)} links",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
