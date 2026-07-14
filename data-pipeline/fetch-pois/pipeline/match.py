"""Stage 3: resolve Entries and their mentions against the gazetteer.

For each Entry the matcher resolves two kinds of thing to a POI (see CONTEXT.md,
ADR 0001):

  - **Place** (`kind: place`) — the Entry itself resolves to **at most one**
    POI, its coordinate. The Place's name matches, its best-effort `place_type`
    (a hint, not required) and verbatim `elevation` guard the match, and the
    result is a `{place_id, poi_id}` row in place_pois.jsonl (an unresolved
    Place is an honest absence, surfaced in the funnel, not a dropped record).
  - **Mention** (`kind: mention`) — a place-name stage 2 extracted from *any*
    Entry's prose (a Route description or a Place Übersicht). Each resolves to a
    `{entry_id, poi_id, surface}` row in entry_pois.jsonl.

A Route's `peak` string is **not** matched here: a Route's coordinate is
transitive via its Destination Place (route-map resolves destination_id -> Place
-> POI), so `peak` stays verbatim Route metadata. A Place and a Mention run the same
cascade (in code both are a `kind`-tagged `item` dict — the humble unit the
cascade takes):

  1. exact — gazetteer entries whose normalized name equals the item's
  2. fuzzy — RapidFuzz ratio >= FUZZY_CUTOFF on the normalized names

Both levels are guarded: a candidate must be taxonomy-compatible with the item's
type (see _NEAR_GROUPS; a Place's `place_type` hint is used exactly like a
mention type, and a null type disables the type guard) and, when both the book
and OSM state an elevation, agree within ELE_TOLERANCE meters. Exactly one
surviving candidate matches; provenance records the method (and score for
fuzzy). More than one candidate at equal footing — same cascade level, same
score — is never auto-resolved: the Place or Mention becomes an open case in
review.jsonl with decision: null. A human closes a case by editing `decision`
to either one of the case's candidate OSM refs (accept: the POI enters the
registry with `{"method": "review"}` provenance, ranked above exact) or the
string "skip" (routing it to unmatched.jsonl with `skipped_by: "review"`).
Decisions are validated against the case's own recorded candidates — any
other value is a typo and aborts the run — then re-applied on every rerun,
so review work survives matcher reruns and gazetteer/mention refreshes; an
accepted ref that has vanished from the gazetteer reopens the case with a
note instead.

No surviving candidate at either level lands in unmatched.jsonl — and, when
it still has shortlist candidates (unguarded fuzzy >=
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
provenance, review > exact > fuzzy > llm), place_pois.jsonl (`{place_id,
poi_id}`, one per resolved Place), entry_pois.jsonl (`{entry_id, poi_id,
surface}`, one per Entry mention/POI pair), pois.geojson (webapp export), and
matcher bookkeeping in 03_matched/: review.jsonl, unmatched.jsonl,
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


def entry_items(entry: dict, cfg: GuideConfig) -> tuple[list[dict], bool]:
    """The resolvable items an Entry contributes: the **Place** itself
    (`kind: place`, resolving to <=1 POI, typed by its best-effort `place_type`
    hint with elevation parsed from the verbatim `elevation` string) when the
    Entry is a Place, followed by every **Mention** (`kind: mention`) stage 2
    extracted from its prose if a part file exists. A Route's `peak` is not an
    item — its coordinate is transitive via its Destination Place. Returns
    (items, part file exists)."""
    items = []
    if entry["kind"] == "place":
        elevation = entry.get("elevation")
        items.append(
            {
                "surface": entry["name"],
                "name": entry["name"],
                "type": entry.get("place_type"),
                "elevation_m": stated_elevation(elevation) if elevation else None,
                "kind": "place",
            }
        )
    part = cfg.mention_parts / f"{entry['id']}.json"
    if part.exists():
        for m in json.loads(part.read_text(encoding="utf-8"))["mentions"]:
            items.append(
                {
                    "surface": m["surface"],
                    "name": m["name"],
                    "type": m["type"],
                    "elevation_m": m.get("elevation_m"),
                    "kind": "mention",
                }
            )
    return items, part.exists()


def passes_guards(item: dict, candidate: dict) -> bool:
    t = item["type"]
    type_ok = (
        t is None  # untyped item (a Place with no place_type hint) — no guard
        or t == candidate["type"]
        or "locality" in (t, candidate["type"])
        or any(t in g and candidate["type"] in g for g in _NEAR_GROUPS)
    )
    ele = item["elevation_m"]
    ele_ok = (
        ele is None
        or candidate["ele"] is None
        or abs(ele - candidate["ele"]) <= ELE_TOLERANCE
    )
    return type_ok and ele_ok


def build_index(
    gazetteer: list[dict],
) -> tuple[dict[str, list[dict]], list[str]]:
    """Group gazetteer entries by normalized name — the cascade's lookup index
    and its key list, shared by the matcher and the audit's method recompute."""
    index: dict[str, list[dict]] = {}
    for candidate in gazetteer:
        index.setdefault(norm_key(candidate["name"]), []).append(candidate)
    return index, list(index)


def resolve(
    item: dict, index: dict[str, list[dict]], keys: list[str]
) -> tuple[str, list]:
    """Run the cascade for one item. Returns (method, [(entry, score), ...])
    where method is 'exact'/'fuzzy' (single survivor), 'tie' (several at equal
    footing) or 'unmatched' (none)."""
    key = norm_key(item["name"])
    exact = [(e, 100.0) for e in index.get(key, []) if passes_guards(item, e)]
    if exact:
        return ("exact" if len(exact) == 1 else "tie"), exact

    hits = process.extract(
        key, keys, scorer=fuzz.ratio, score_cutoff=FUZZY_CUTOFF, limit=None
    )
    survivors = [
        (e, round(score, 1))
        for hit_key, score, _ in hits
        for e in index[hit_key]
        if passes_guards(item, e)
    ]
    if not survivors:
        return "unmatched", []
    best = max(score for _, score in survivors)
    top = [(e, score) for e, score in survivors if score == best]
    return ("fuzzy" if len(top) == 1 else "tie"), top


def shortlist(
    item: dict, index: dict[str, list[dict]], keys: list[str]
) -> list[tuple[dict, float]]:
    """Candidate shortlist for the LLM adjudicator: the top
    ADJUDICATION_SHORTLIST gazetteer entries by fuzzy ratio >=
    ADJUDICATION_CUTOFF, deliberately unguarded — the adjudicator sees each
    candidate's type and elevation and judges drift the cascade's guards
    can't (renamed huts, book-elevation typos, 1996 spellings)."""
    key = norm_key(item["name"])
    hits = process.extract(
        key, keys, scorer=fuzz.ratio, score_cutoff=ADJUDICATION_CUTOFF, limit=None
    )
    ranked = sorted(
        ((e, round(score, 1)) for hit_key, score, _ in hits for e in index[hit_key]),
        key=lambda es: (-es[1], es[0]["osm"]),
    )
    return ranked[:ADJUDICATION_SHORTLIST]


def case_id(eid: str, item: dict) -> str:
    """Filesystem-safe identity of an adjudication case — same fields as
    _case_key, so it is stable across reruns and refreshes and a verdict
    file survives them. The hash suffix disambiguates names that collide
    after slugging (e.g. 'Knorr Hütte' vs 'Knorr-Hütte')."""
    label = "place" if item["kind"] == "place" else item["type"]
    slug = re.sub(
        r"[^a-z0-9]+", "-", item["name"].casefold().translate(_TRANSLIT)
    ).strip("-")
    raw = f"{eid}\x1f{item['name']}\x1f{item['type']}\x1f{item['kind']}"
    return f"{eid}__{slug}__{label}__{hashlib.sha1(raw.encode()).hexdigest()[:8]}"


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
    item: dict,
    candidate: dict,
    method: str,
    score: float,
    reason: str | None = None,
) -> str:
    """Upsert the POI: aliases collect differing surface forms, provenance
    keeps the best method (review > exact > fuzzy > llm, then highest
    score). LLM provenance carries the adjudicator's reason."""
    pid = poi_id(candidate["osm"])
    poi = pois.setdefault(
        pid, {"poi_id": pid, **candidate, "aliases": [], "match": None}
    )
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
    for form in (strip_elevation(item["surface"]), item["name"]):
        if form != poi["name"] and form not in poi["aliases"]:
            poi["aliases"].append(form)
    return pid


def _add_place_link(place_links: dict, eid: str, pid: str) -> None:
    """Record a Place's single POI. A Place resolves to at most one POI, so
    the link is keyed by place_id (a rerun overwrites with the same value)."""
    place_links[eid] = {"place_id": eid, "poi_id": pid}


def _add_entry_link(entry_links: dict, eid: str, pid: str, item: dict) -> None:
    """Record an Entry mention -> POI link, deduplicated per (entry, POI);
    the first surface form seen wins."""
    entry_links.setdefault(
        (eid, pid),
        {"entry_id": eid, "poi_id": pid, "surface": item["surface"]},
    )


def _add_link(
    place_links: dict, entry_links: dict, eid: str, pid: str, item: dict
) -> None:
    """Route a resolved item to its link table: a Place to place_pois, an
    Entry mention to entry_pois."""
    if item["kind"] == "place":
        _add_place_link(place_links, eid, pid)
    else:
        _add_entry_link(entry_links, eid, pid, item)


def _case_key(eid: str, item: dict) -> tuple:
    """Identity of a review case, stable across reruns and refreshes."""
    return (eid, item["name"], item["type"], item["kind"])


def _unmatched_record(eid: str, item: dict, **extra) -> dict:
    return {
        "entry_id": eid,
        "mention": item["surface"],
        "name": item["name"],
        "type": item["type"],
        "kind": item["kind"],
        "elevation_m": item["elevation_m"],
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


def classify_method(
    item: dict,
    eid: str,
    index: dict[str, list[dict]],
    keys: list[str],
    decisions: dict[tuple, str],
    verdicts: dict[str, dict],
    cfg: GuideConfig,
) -> str:
    """The true resolution method for a single item, recomputed by replaying
    the matcher's per-item decision — the cascade (`resolve`), then a human
    review decision, then an LLM verdict — in the same precedence
    match_mentions applies (#7). Returns one of exact / fuzzy / review / llm /
    tie / skipped / unmatched.

    This is the per-match method the audit gate weights its sample by. It
    deliberately does *not* read pois.jsonl's `match` provenance: that records
    a POI's single best method across every item that reached it, so a POI
    resolved exactly by one Place and fuzzily by a mention would mislabel the
    mention. The method is recomputed from the item itself instead.

    It mirrors — rather than shares — match_mentions' branch logic: that
    function builds the funnel, review cases, the queue and the link tables in
    one interleaved pass, so a per-item projection is cleaner as its own read.
    test_audit's funnel-agreement test rebuilds the whole funnel from this
    function and asserts it byte-matches the matcher's, guarding the two
    against drift."""
    method, survivors = resolve(item, index, keys)
    if method in ("exact", "fuzzy"):
        return method
    key = _case_key(eid, item)
    decision = decisions.get(key)
    if method == "tie":
        refs = {e["osm"] for e, _ in survivors}
        if decision == "skip":
            return "skipped"
        return "review" if decision in refs else "tie"
    # Cascade found nothing: a documented out-of-scope class is a skip; a
    # leftover with shortlist candidates is an adjudication case where a human
    # decision wins over the LLM verdict; anything else stays unmatched.
    if out_of_scope_reason(item["name"], cfg.out_of_scope):
        return "skipped"
    candidates = shortlist(item, index, keys)
    if not candidates:
        return "unmatched"
    refs = {e["osm"] for e, _ in candidates}
    if decision == "skip":
        return "skipped"
    if decision in refs:
        return "review"
    verdict = verdicts.get(case_id(eid, item))
    if verdict and verdict["pick"] in refs:
        return "llm"
    return "unmatched"


def match_mentions(
    entries: list[dict],
    gazetteer: list[dict],
    cfg: GuideConfig,
    decisions: dict[tuple, str] | None = None,
    notes: dict[tuple, str] | None = None,
    verdicts: dict[str, dict] | None = None,
):
    """Returns (pois by id, place->poi links, entry->poi mention links, review
    cases, unmatched, adjudication queue, funnel by type, entries with a mention
    part file). `decisions`/`notes` come from load_decisions() and are applied to
    tie and adjudication cases alike; `verdicts` come from load_verdicts() and
    resolve adjudication cases that no decision overrides."""
    decisions = decisions or {}
    notes = notes or {}
    verdicts = verdicts or {}
    index, keys = build_index(gazetteer)

    pois: dict[str, dict] = {}
    place_links: dict[str, dict] = {}
    entry_links: dict[tuple[str, str], dict] = {}
    review: list[dict] = []
    unmatched: list[dict] = []
    queue: list[dict] = []
    funnel: dict[str, dict[str, int]] = {}
    with_parts = 0

    for entry in sorted(entries, key=lambda e: e["id"]):
        eid = entry["id"]
        items, has_part = entry_items(entry, cfg)
        with_parts += has_part
        for item in items:
            method, survivors = resolve(item, index, keys)
            bucket = funnel.setdefault(
                "place" if item["kind"] == "place" else item["type"],
                dict.fromkeys(_FUNNEL_COLS, 0),
            )
            bucket["mentions"] += 1
            if method in ("exact", "fuzzy"):
                bucket[method] += 1
                candidate, score = survivors[0]
                pid = register(pois, item, candidate, method, score)
                _add_link(place_links, entry_links, eid, pid, item)
            elif method == "tie":
                key = _case_key(eid, item)
                decision = decisions.get(key)
                by_ref = {e["osm"]: (e, score) for e, score in survivors}
                case = {
                    "mention": item["surface"],
                    "name": item["name"],
                    "type": item["type"],
                    "entry_id": eid,
                    "kind": item["kind"],
                    "candidates": _candidate_rows(survivors),
                    "decision": decision,
                    "source": "tie",
                }
                if decision == "skip":
                    # Human sent the item to unmatched; the case stays in
                    # review.jsonl as the persistent record of that decision.
                    bucket["skipped"] += 1
                    unmatched.append(_unmatched_record(eid, item, skipped_by="review"))
                elif decision in by_ref:
                    # Human accepted a candidate: it enters the registry with
                    # review provenance (ranked above exact).
                    bucket["review"] += 1
                    candidate, score = by_ref[decision]
                    pid = register(pois, item, candidate, "review", score)
                    _add_link(place_links, entry_links, eid, pid, item)
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
                skip_reason = out_of_scope_reason(item["name"], cfg.out_of_scope)
                if skip_reason:
                    bucket["skipped"] += 1
                    unmatched.append(
                        _unmatched_record(eid, item, skip_reason=skip_reason)
                    )
                    continue
                candidates = shortlist(item, index, keys)
                if not candidates:
                    # Nothing worth judging: plain unmatched, never adjudicated.
                    bucket["unmatched"] += 1
                    unmatched.append(_unmatched_record(eid, item))
                    continue
                # Cascade leftover with shortlist candidates: an adjudication
                # case (#6). A human decision (candidate ref or "skip") always
                # wins; otherwise the LLM verdict applies; without either the
                # case is queued for `plan adjudicate`.
                cid = case_id(eid, item)
                key = _case_key(eid, item)
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
                    "mention": item["surface"],
                    "name": item["name"],
                    "type": item["type"],
                    "entry_id": eid,
                    "kind": item["kind"],
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
                    unmatched.append(_unmatched_record(eid, item))
                    queue.append(
                        {
                            "case_id": cid,
                            "entry_id": eid,
                            "mention": item["surface"],
                            "name": item["name"],
                            "type": item["type"],
                            "kind": item["kind"],
                            "elevation_m": item["elevation_m"],
                            "candidates": case["candidates"],
                        }
                    )
                    if note:
                        review.append(case)
                    continue
                if decision == "skip":
                    bucket["skipped"] += 1
                    unmatched.append(_unmatched_record(eid, item, skipped_by="review"))
                elif decision in by_ref:
                    bucket["review"] += 1
                    candidate, score = by_ref[decision]
                    pid = register(pois, item, candidate, "review", score)
                    _add_link(place_links, entry_links, eid, pid, item)
                elif verdict["pick"] is None:
                    # LLM declared no-match: unmatched, reason preserved.
                    bucket["unmatched"] += 1
                    unmatched.append(
                        _unmatched_record(eid, item, llm_reason=verdict["reason"])
                    )
                elif verdict["pick"] in by_ref:
                    bucket["llm"] += 1
                    candidate, score = by_ref[verdict["pick"]]
                    pid = register(
                        pois, item, candidate, "llm", score, reason=verdict["reason"]
                    )
                    _add_link(place_links, entry_links, eid, pid, item)
                else:
                    # The pick is not one of the case's current candidates —
                    # hallucinated, or vanished with a gazetteer refresh.
                    bucket["unmatched"] += 1
                    case["note"] = (
                        f"verdict pick {verdict['pick']} is not among the current "
                        f"candidates — verdict ignored; delete "
                        f"{cfg.verdicts_dir / (cid + '.json')} to re-adjudicate"
                    )
                    unmatched.append(_unmatched_record(eid, item))
                review.append(case)
    return (
        pois,
        list(place_links.values()),
        list(entry_links.values()),
        review,
        unmatched,
        queue,
        funnel,
        with_parts,
    )


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
        key = (case["entry_id"], case["name"], case["type"], case["kind"])
        decision = case.get("decision")
        if decision is None:
            if case.get("note"):
                notes[key] = case["note"]
            continue
        refs = [c["osm"] for c in case["candidates"]]
        if decision != "skip" and decision not in refs:
            sys.exit(
                f"{cfg.review}: decision {decision!r} for {case['name']!r} "
                f"(entry {case['entry_id']}) is not one of the case's candidates "
                f'({", ".join(refs)}) and not "skip" — fix the typo and rerun.'
            )
        decisions[key] = decision
    return decisions, notes


def funnel_report(funnel: dict, n_entries: int, with_parts: int) -> dict:
    ordered = dict(sorted(funnel.items(), key=lambda kv: (-kv[1]["mentions"], kv[0])))
    totals = {col: sum(row[col] for row in funnel.values()) for col in _FUNNEL_COLS}
    return {
        "entries": {"total": n_entries, "with_mentions": with_parts},
        "types": ordered,
        "totals": totals,
    }


def to_geojson(pois: dict, place_links: list[dict], entry_links: list[dict]) -> dict:
    # n_entries: how many distinct Entries (Places via place_pois + Entries via
    # their mentions) reference each POI — the webapp's "used by N entries" count.
    entries_per_poi: dict[str, set[str]] = {}
    for link in place_links:
        entries_per_poi.setdefault(link["poi_id"], set()).add(link["place_id"])
    for link in entry_links:
        entries_per_poi.setdefault(link["poi_id"], set()).add(link["entry_id"])
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
                "n_entries": len(entries_per_poi.get(p["poi_id"], ())),
            },
        }
        for p in pois.values()
    ]
    return {"type": "FeatureCollection", "features": features}


def run_match(cfg: GuideConfig) -> dict:
    """Full stage 3: load entries/gazetteer/decisions/verdicts for the guide,
    run the cascade, and write every artifact. Returns the funnel report."""
    entries = load_jsonl(cfg.routes_jsonl)
    gazetteer = load_jsonl(cfg.gazetteer)
    decisions, notes = load_decisions(cfg)
    verdicts = load_verdicts(cfg)
    (
        pois,
        place_links,
        entry_links,
        review,
        unmatched,
        queue,
        funnel,
        with_parts,
    ) = match_mentions(entries, gazetteer, cfg, decisions, notes, verdicts)
    report = funnel_report(funnel, len(entries), with_parts)

    cfg.match_dir.mkdir(parents=True, exist_ok=True)
    cfg.final_dir.mkdir(parents=True, exist_ok=True)
    # Legacy artifacts the Entry model supersedes (peak-anchor era).
    (cfg.match_dir / "anchor_open.jsonl").unlink(missing_ok=True)
    (cfg.final_dir / "route_pois.jsonl").unlink(missing_ok=True)
    write_jsonl(cfg.review, review)
    write_jsonl(cfg.unmatched, unmatched)
    write_jsonl(cfg.adjudication_queue, queue)
    cfg.funnel.write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    write_jsonl(cfg.pois_jsonl, list(pois.values()))
    write_jsonl(cfg.place_pois_jsonl, place_links)
    write_jsonl(cfg.entry_pois_jsonl, entry_links)
    cfg.pois_geojson.write_text(
        json.dumps(to_geojson(pois, place_links, entry_links), ensure_ascii=False),
        encoding="utf-8",
    )

    totals = report["totals"]
    print(
        f"[match] entries: {len(entries)} ({with_parts} with extracted mentions) -> "
        f"items: {totals['mentions']}, exact: {totals['exact']}, "
        f"fuzzy: {totals['fuzzy']}, llm: {totals['llm']}, "
        f"review: {totals['review']}, "
        f"ties: {totals['tie']} open (-> {cfg.review}), "
        f"skipped: {totals['skipped']}, "
        f"unmatched: {totals['unmatched']} (-> {cfg.unmatched}, "
        f"{len(queue)} queued for adjudication); "
        f"{len(pois)} unique POIs, "
        f"{len(place_links)} place links, {len(entry_links)} mention links",
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
