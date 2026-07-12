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
decision: null. A human closes a case by editing `decision` to either one of
the case's candidate OSM refs (accept: the POI enters the registry with
`{"method": "review"}` provenance, ranked above exact) or the string "skip"
(the mention is routed to unmatched.jsonl with `skipped_by: "review"`).
Decisions are validated against the case's own recorded candidates — any
other value is a typo and aborts the run — then re-applied on every rerun,
so review work survives matcher reruns and gazetteer/mention refreshes; an
accepted ref that has vanished from the gazetteer reopens the case with a
note instead.

No surviving candidate at either level lands in unmatched.jsonl — and, when
the mention still has shortlist candidates (unguarded fuzzy >=
ADJUDICATION_CUTOFF, top ADJUDICATION_SHORTLIST), it is additionally queued
in adjudication_queue.jsonl for the LLM adjudicator (#6): `plan adjudicate`
batches the queue to match-adjudicator subagents, which write one verdict
file per case to 03_matched/verdicts/<case_id>.json — a pick (one of the
case's candidate refs) or an explicit no-match, always with a reason. On
rerun the matcher consumes verdicts: picks enter the registry with
`{"method": "llm", "score": ..., "reason": ...}` provenance (ranked below
the deterministic cascade), no-matches stay in unmatched.jsonl with the
reason preserved as `llm_reason`. Every verdict is also written to
review.jsonl with `source: "llm"` so it can be audited and overridden
through the same decision loop — a hand-written `decision` (candidate ref
or "skip") always wins over the LLM verdict. Verdict files are the
resumability unit: a case with a verdict is never re-adjudicated.

  python -m pipeline.match --guide <id>

Outputs: pois.jsonl (deduplicated registry with aliases and best-method
provenance, review > exact > fuzzy > llm), route_pois.jsonl (one link per
route/POI pair with anchor flag), pois.geojson (webapp export), and matcher
bookkeeping in 03_matched/: review.jsonl, unmatched.jsonl,
adjudication_queue.jsonl, funnel.json (rendered by
`python -m pipeline.plan funnel`).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys

from rapidfuzz import fuzz, process

from .config import GuideConfig, load_guide

FUZZY_CUTOFF = 90.0  # minimum RapidFuzz ratio for a fuzzy candidate
ELE_TOLERANCE = 50.0  # max |book - OSM| elevation difference in meters

# Shortlist tuning for the LLM adjudicator (#6): the top candidates by
# RapidFuzz ratio on the normalized names, without the cascade's
# type/elevation guards (the adjudicator sees each candidate's type and
# elevation and judges drift the deterministic guards can't). Mentions whose
# best candidate scores below the floor have nothing worth judging and stay
# plain unmatched. Algorithm tuning, not per-guide config.
ADJUDICATION_SHORTLIST = 10  # max candidates per case
ADJUDICATION_CUTOFF = 60.0  # minimum RapidFuzz ratio to enter the shortlist

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

# A human review decision always wins best-method selection; an LLM verdict
# ranks below the deterministic cascade.
_METHOD_RANK = {"review": 4, "exact": 3, "fuzzy": 2, "llm": 1}
_FUNNEL_COLS = (
    "mentions",
    "exact",
    "fuzzy",
    "llm",
    "review",
    "tie",
    "skipped",
    "unmatched",
)


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


def out_of_scope_reason(
    name: str, out_of_scope: tuple[tuple[str, str], ...]
) -> str | None:
    """Reason string if the name belongs to a class deliberately outside the
    gazetteer's scope (cfg.out_of_scope), else None."""
    stripped = strip_elevation(name)
    for pattern, reason in out_of_scope:
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


def route_mentions(route: dict, cfg: GuideConfig) -> tuple[list[dict], bool]:
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
    part = cfg.mention_parts / f"{route['route_id']}.json"
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
    ele_ok = (
        ele is None or entry["ele"] is None or abs(ele - entry["ele"]) <= ELE_TOLERANCE
    )
    return type_ok and ele_ok


def resolve(
    mention: dict, index: dict[str, list[dict]], keys: list[str]
) -> tuple[str, list]:
    """Run the cascade for one mention. Returns (method, [(entry, score), ...])
    where method is 'exact'/'fuzzy' (single survivor), 'tie' (several at equal
    footing) or 'unmatched' (none)."""
    key = norm_key(mention["name"])
    exact = [(e, 100.0) for e in index.get(key, []) if passes_guards(mention, e)]
    if exact:
        return ("exact" if len(exact) == 1 else "tie"), exact

    hits = process.extract(
        key, keys, scorer=fuzz.ratio, score_cutoff=FUZZY_CUTOFF, limit=None
    )
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


def shortlist(
    mention: dict, index: dict[str, list[dict]], keys: list[str]
) -> list[tuple[dict, float]]:
    """Candidate shortlist for the LLM adjudicator: the top
    ADJUDICATION_SHORTLIST gazetteer entries by fuzzy ratio >=
    ADJUDICATION_CUTOFF, deliberately unguarded — the adjudicator sees each
    candidate's type and elevation and judges drift the cascade's guards
    can't (renamed huts, book-elevation typos, 1996 spellings)."""
    key = norm_key(mention["name"])
    hits = process.extract(
        key, keys, scorer=fuzz.ratio, score_cutoff=ADJUDICATION_CUTOFF, limit=None
    )
    ranked = sorted(
        ((e, round(score, 1)) for hit_key, score, _ in hits for e in index[hit_key]),
        key=lambda es: (-es[1], es[0]["osm"]),
    )
    return ranked[:ADJUDICATION_SHORTLIST]


def case_id(rid: str, mention: dict) -> str:
    """Filesystem-safe identity of an adjudication case — same fields as
    _case_key, so it is stable across reruns and refreshes and a verdict
    file survives them. The hash suffix disambiguates names that collide
    after slugging (e.g. 'Knorr Hütte' vs 'Knorr-Hütte')."""
    kind = "anchor" if mention["is_anchor"] else mention["type"]
    slug = re.sub(
        r"[^a-z0-9]+", "-", mention["name"].casefold().translate(_TRANSLIT)
    ).strip("-")
    raw = f"{rid}\x1f{mention['name']}\x1f{mention['type']}\x1f{mention['is_anchor']}"
    return f"{rid}__{slug}__{kind}__{hashlib.sha1(raw.encode()).hexdigest()[:8]}"


def load_verdicts(cfg: GuideConfig) -> dict[str, dict]:
    """Adjudicator verdicts, one file per case in verdicts_dir (the
    resumability unit: a case with a verdict file is never re-adjudicated).
    Each verdict must carry a `pick` (a candidate OSM ref, or null for
    no-match) and a non-empty `reason` — anything else is a malformed
    subagent write and aborts the run."""
    verdicts: dict[str, dict] = {}
    if not cfg.verdicts_dir.exists():
        return verdicts
    for path in sorted(cfg.verdicts_dir.glob("*.json")):
        try:
            verdict = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            sys.exit(
                f"{path}: not valid JSON ({err}) — delete the file and re-adjudicate."
            )
        if verdict.get("case_id", path.stem) != path.stem:
            sys.exit(
                f"{path}: verdict case_id {verdict['case_id']!r} does not match the "
                f"file name {path.stem!r} — the subagent wrote to the wrong file; "
                "fix the name and rerun."
            )
        pick, reason = verdict.get("pick"), verdict.get("reason")
        if (
            "pick" not in verdict
            or not (pick is None or isinstance(pick, str))
            or not (isinstance(reason, str) and reason.strip())
        ):
            sys.exit(
                f"{path}: a verdict needs a `pick` (candidate OSM ref or null) and a "
                "non-empty `reason` — delete the file and re-adjudicate."
            )
        verdicts[path.stem] = {"pick": pick, "reason": reason}
    return verdicts


def register(
    pois: dict,
    mention: dict,
    entry: dict,
    method: str,
    score: float,
    reason: str | None = None,
) -> str:
    """Upsert the POI: aliases collect differing surface forms, provenance
    keeps the best method (review > exact > fuzzy > llm, then highest
    score). LLM provenance carries the adjudicator's reason."""
    pid = poi_id(entry["osm"])
    poi = pois.setdefault(pid, {"poi_id": pid, **entry, "aliases": [], "match": None})
    prov = {"method": method}
    if method == "fuzzy":
        prov["score"] = score
    elif method == "llm":
        prov["score"] = score
        prov["reason"] = reason
    cur = poi["match"]
    if cur is None or (_METHOD_RANK[method], score) > (
        _METHOD_RANK[cur["method"]],
        cur.get("score", 100.0),
    ):
        poi["match"] = prov
    for form in (strip_elevation(mention["surface"]), mention["name"]):
        if form != poi["name"] and form not in poi["aliases"]:
            poi["aliases"].append(form)
    return pid


def _add_link(links: dict, rid: str, pid: str, mention: dict) -> None:
    link = links.setdefault(
        (rid, pid),
        {
            "route_id": rid,
            "poi_id": pid,
            "surface": mention["surface"],
            "is_anchor": mention["is_anchor"],
        },
    )
    link["is_anchor"] = link["is_anchor"] or mention["is_anchor"]


def _case_key(rid: str, mention: dict) -> tuple:
    """Identity of a review case, stable across reruns and refreshes."""
    return (rid, mention["name"], mention["type"], mention["is_anchor"])


def _unmatched_record(rid: str, mention: dict, **extra) -> dict:
    return {
        "route_id": rid,
        "mention": mention["surface"],
        "name": mention["name"],
        "type": mention["type"],
        "is_anchor": mention["is_anchor"],
        "elevation_m": mention["elevation_m"],
        **extra,
    }


def _candidate_rows(survivors: list[tuple[dict, float]]) -> list[dict]:
    return [
        {
            "osm": e["osm"],
            "name": e["name"],
            "type": e["type"],
            "ele": e["ele"],
            "lat": e["lat"],
            "lon": e["lon"],
            "score": score,
        }
        for e, score in survivors
    ]


def match_mentions(
    routes: list[dict],
    gazetteer: list[dict],
    cfg: GuideConfig,
    decisions: dict[tuple, str] | None = None,
    notes: dict[tuple, str] | None = None,
    verdicts: dict[str, dict] | None = None,
):
    """Returns (pois by id, route<->poi links, review cases, unmatched,
    adjudication queue, funnel by type, routes with a mention part file).
    `decisions`/`notes` come from load_decisions() and are applied to tie
    and adjudication cases alike; `verdicts` come from load_verdicts() and
    resolve adjudication cases that no decision overrides."""
    decisions = decisions or {}
    notes = notes or {}
    verdicts = verdicts or {}
    index: dict[str, list[dict]] = {}
    for entry in gazetteer:
        index.setdefault(norm_key(entry["name"]), []).append(entry)
    keys = list(index)

    pois: dict[str, dict] = {}
    links: dict[tuple[str, str], dict] = {}
    review: list[dict] = []
    unmatched: list[dict] = []
    queue: list[dict] = []
    funnel: dict[str, dict[str, int]] = {}
    with_parts = 0

    for route in sorted(routes, key=lambda r: r["route_id"]):
        rid = route["route_id"]
        mentions, has_part = route_mentions(route, cfg)
        with_parts += has_part
        for mention in mentions:
            method, survivors = resolve(mention, index, keys)
            bucket = funnel.setdefault(
                "anchor" if mention["is_anchor"] else mention["type"],
                dict.fromkeys(_FUNNEL_COLS, 0),
            )
            bucket["mentions"] += 1
            if method in ("exact", "fuzzy"):
                bucket[method] += 1
                entry, score = survivors[0]
                pid = register(pois, mention, entry, method, score)
                _add_link(links, rid, pid, mention)
            elif method == "tie":
                key = _case_key(rid, mention)
                decision = decisions.get(key)
                by_ref = {e["osm"]: (e, score) for e, score in survivors}
                case = {
                    "mention": mention["surface"],
                    "name": mention["name"],
                    "type": mention["type"],
                    "route_id": rid,
                    "is_anchor": mention["is_anchor"],
                    "candidates": _candidate_rows(survivors),
                    "decision": decision,
                    "source": "tie",
                }
                if decision == "skip":
                    # Human sent the mention to unmatched; the case stays in
                    # review.jsonl as the persistent record of that decision.
                    bucket["skipped"] += 1
                    unmatched.append(
                        _unmatched_record(rid, mention, skipped_by="review")
                    )
                elif decision in by_ref:
                    # Human accepted a candidate: it enters the registry with
                    # review provenance (ranked above exact).
                    bucket["review"] += 1
                    entry, score = by_ref[decision]
                    pid = register(pois, mention, entry, "review", score)
                    _add_link(links, rid, pid, mention)
                else:
                    bucket["tie"] += 1
                    if decision is not None:
                        # Validated against the recorded candidates, so this is
                        # not a typo: the accepted ref vanished from a refetched
                        # gazetteer. Reopen instead of crashing.
                        case["decision"] = None
                        case["note"] = (
                            f"accepted candidate {decision} is no longer in the "
                            "gazetteer — case reopened"
                        )
                    elif key in notes:
                        case["note"] = notes[key]
                review.append(case)
            else:
                # Classes deliberately outside the gazetteer (#11,
                # cfg.out_of_scope) count as skipped, not unmatched.
                skip_reason = out_of_scope_reason(mention["name"], cfg.out_of_scope)
                if skip_reason:
                    bucket["skipped"] += 1
                    unmatched.append(
                        _unmatched_record(rid, mention, skip_reason=skip_reason)
                    )
                    continue
                candidates = shortlist(mention, index, keys)
                if not candidates:
                    # Nothing worth judging: plain unmatched, never adjudicated.
                    bucket["unmatched"] += 1
                    unmatched.append(_unmatched_record(rid, mention))
                    continue
                # Cascade leftover with shortlist candidates: an adjudication
                # case (#6). A human decision (candidate ref or "skip") always
                # wins; otherwise the LLM verdict applies; without either the
                # case is queued for `plan adjudicate`.
                cid = case_id(rid, mention)
                key = _case_key(rid, mention)
                decision = decisions.get(key)
                verdict = verdicts.get(cid)
                note = notes.get(key)
                by_ref = {e["osm"]: (e, score) for e, score in candidates}
                if (
                    decision is not None
                    and decision != "skip"
                    and decision not in by_ref
                ):
                    # Validated against the case's recorded candidates at load
                    # time, so this is not a typo: the accepted ref vanished
                    # from a refetched gazetteer/shortlist. The override is
                    # cleared — audibly — and the LLM verdict applies again.
                    note = (
                        f"accepted candidate {decision} is no longer a candidate "
                        "— override cleared"
                    )
                    decision = None
                case = {
                    "mention": mention["surface"],
                    "name": mention["name"],
                    "type": mention["type"],
                    "route_id": rid,
                    "is_anchor": mention["is_anchor"],
                    "case_id": cid,
                    "candidates": _candidate_rows(candidates),
                    "verdict": verdict,
                    "decision": decision,
                    "source": "llm",
                }
                if note:
                    case["note"] = note
                if decision is None and verdict is None:
                    # Not yet adjudicated: stays unmatched and is queued. The
                    # case enters review.jsonl once a verdict exists (or, edge
                    # case, to keep a note visible while re-adjudication runs).
                    bucket["unmatched"] += 1
                    unmatched.append(_unmatched_record(rid, mention))
                    queue.append(
                        {
                            "case_id": cid,
                            "route_id": rid,
                            "mention": mention["surface"],
                            "name": mention["name"],
                            "type": mention["type"],
                            "is_anchor": mention["is_anchor"],
                            "elevation_m": mention["elevation_m"],
                            "candidates": case["candidates"],
                        }
                    )
                    if note:
                        review.append(case)
                    continue
                if decision == "skip":
                    bucket["skipped"] += 1
                    unmatched.append(
                        _unmatched_record(rid, mention, skipped_by="review")
                    )
                elif decision in by_ref:
                    bucket["review"] += 1
                    entry, score = by_ref[decision]
                    pid = register(pois, mention, entry, "review", score)
                    _add_link(links, rid, pid, mention)
                elif verdict["pick"] is None:
                    # LLM declared no-match: unmatched, reason preserved.
                    bucket["unmatched"] += 1
                    unmatched.append(
                        _unmatched_record(rid, mention, llm_reason=verdict["reason"])
                    )
                elif verdict["pick"] in by_ref:
                    bucket["llm"] += 1
                    entry, score = by_ref[verdict["pick"]]
                    pid = register(
                        pois, mention, entry, "llm", score, reason=verdict["reason"]
                    )
                    _add_link(links, rid, pid, mention)
                else:
                    # The pick is not one of the case's current candidates —
                    # hallucinated, or vanished with a gazetteer refresh.
                    bucket["unmatched"] += 1
                    case["note"] = (
                        f"verdict pick {verdict['pick']} is not among the current "
                        f"candidates — verdict ignored; delete "
                        f"{cfg.verdicts_dir / (cid + '.json')} to re-adjudicate"
                    )
                    unmatched.append(_unmatched_record(rid, mention))
                review.append(case)
    return pois, list(links.values()), review, unmatched, queue, funnel, with_parts


def load_decisions(cfg: GuideConfig) -> tuple[dict[tuple, str], dict[tuple, str]]:
    """Review work must survive matcher reruns: decisions (and notes on still-
    open cases) in the existing review.jsonl are loaded so match_mentions can
    re-apply them — to tie cases and LLM adjudication cases alike, which is
    how a hand-written override outlives the LLM verdict. A non-null decision
    must be "skip" or one of the case's own recorded candidate refs — anything
    else is a typo and aborts the run."""
    decisions: dict[tuple, str] = {}
    notes: dict[tuple, str] = {}
    if not cfg.review.exists():
        return decisions, notes
    for case in load_jsonl(cfg.review):
        key = (case["route_id"], case["name"], case["type"], case["is_anchor"])
        decision = case.get("decision")
        if decision is None:
            if case.get("note"):
                notes[key] = case["note"]
            continue
        refs = [c["osm"] for c in case["candidates"]]
        if decision != "skip" and decision not in refs:
            sys.exit(
                f"{cfg.review}: decision {decision!r} for {case['name']!r} "
                f"(route {case['route_id']}) is not one of the case's candidates "
                f'({", ".join(refs)}) and not "skip" — fix the typo and rerun.'
            )
        decisions[key] = decision
    return decisions, notes


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


def run_match(cfg: GuideConfig) -> dict:
    """Full stage 3: load routes/gazetteer/decisions/verdicts for the guide,
    run the cascade, and write every artifact. Returns the funnel report."""
    routes = load_jsonl(cfg.routes_jsonl)
    gazetteer = load_jsonl(cfg.gazetteer)
    decisions, notes = load_decisions(cfg)
    verdicts = load_verdicts(cfg)
    pois, links, review, unmatched, queue, funnel, with_parts = match_mentions(
        routes, gazetteer, cfg, decisions, notes, verdicts
    )
    report = funnel_report(funnel, len(routes), with_parts)

    cfg.match_dir.mkdir(parents=True, exist_ok=True)
    cfg.final_dir.mkdir(parents=True, exist_ok=True)
    # review.jsonl + unmatched.jsonl supersede the old anchor-only artifact.
    (cfg.match_dir / "anchor_open.jsonl").unlink(missing_ok=True)
    write_jsonl(cfg.review, review)
    write_jsonl(cfg.unmatched, unmatched)
    write_jsonl(cfg.adjudication_queue, queue)
    cfg.funnel.write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    write_jsonl(cfg.pois_jsonl, list(pois.values()))
    write_jsonl(cfg.route_pois_jsonl, links)
    cfg.pois_geojson.write_text(
        json.dumps(to_geojson(pois, links), ensure_ascii=False), encoding="utf-8"
    )

    totals = report["totals"]
    print(
        f"[match] routes: {len(routes)} ({with_parts} with extracted mentions) -> "
        f"mentions: {totals['mentions']}, exact: {totals['exact']}, "
        f"fuzzy: {totals['fuzzy']}, llm: {totals['llm']}, "
        f"review: {totals['review']}, "
        f"ties: {totals['tie']} open (-> {cfg.review}), "
        f"skipped: {totals['skipped']}, "
        f"unmatched: {totals['unmatched']} (-> {cfg.unmatched}, "
        f"{len(queue)} queued for adjudication); "
        f"{len(pois)} unique POIs, {len(links)} links",
        file=sys.stderr,
    )
    return report


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Resolve mentions against the gazetteer.")
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    args = ap.parse_args()
    run_match(load_guide(args.guide))


if __name__ == "__main__":
    main()
