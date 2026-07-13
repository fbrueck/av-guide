# fetch-pois

Resolves the places named in parsed AV-guide **Entries** (produced by the
`parse-routes` pipeline) to OpenStreetMap coordinates: a gazetteer-first
pipeline that fetches all named alpine features in the guide's bounding box via
Overpass, resolves each **Place** Entry to at most one POI (its coordinate),
extracts typed place mentions from every Entry's prose (Route descriptions and
Place Übersichten alike), matches them deterministically, and emits a
deduplicated POI registry plus a webapp-ready GeoJSON export. A Route's anchor
coordinate is not resolved here — it is transitive via the Route's Place
(`anchor_ids` -> Place -> POI, resolved downstream in `route-map`), so a Route's
`peak` string stays verbatim metadata.

The reference guide is the *Wetterstein* (Beulke, 1996), but the pipeline is
guide-agnostic: everything guide-specific lives in external config and data (see
**Guides** below). Spec and tickets: see the repo issue tracker (spec is issue
#1).

## Guides

A guide is one directory at the repo root:

```
guides/<id>/
  config.yml            # committed: guide facts + per-pipeline settings
  data/parse-routes/    # gitignored: upstream routes.jsonl this pipeline consumes
  data/fetch-pois/      # gitignored: this pipeline's artifacts
```

`config.yml` holds shared top-level facts (`id`, `bbox`) plus a `fetch-pois:`
subsection read by this pipeline — the taxonomy `tag_map` and `guarded_tag_map`
(nested lists of `[osm_key, osm_value]`), `deduped_types`,
`settlement_exclusion_km`, `out_of_scope` patterns, and an optional
`overpass_url` (defaults to the public endpoint):

```yaml
id: wetterstein
bbox: [47.30, 10.85, 47.55, 11.35]
fetch-pois:
  tag_map:
    peak: [[natural, peak]]
    hut:  [[tourism, alpine_hut], [amenity, shelter], ...]
    # ...
  guarded_tag_map:
    hut: [[amenity, restaurant], [tourism, chalet], [tourism, guest_house]]
  deduped_types: [path, water]
  settlement_exclusion_km: 1.0
  out_of_scope:
    - pattern: 'gebirge$'
      reason: 'mountain range/region — deliberately not in the gazetteer (no point representation)'
```

The **fixed on-disk stage layout is not in the YAML** — it lives in code
(`pipeline/config.py` path helpers, derived from `data_root =
guides/<id>/data/fetch-pois`). The upstream routes index is derived by
convention as `guides/<id>/data/parse-routes/03_structured/routes.jsonl`.

Every command takes a required `--guide <id>` argument; there is no default.
`pipeline/config.py` loads `guides/<id>/config.yml` into an immutable
`GuideConfig`, which each pure step function takes as an argument. (Matching
tuning that is algorithm behaviour rather than a guide fact — the fuzzy cutoff,
elevation tolerance, and adjudication shortlist size/floor — stays as module
constants in `pipeline/match.py`.)

## Stages

Data paths below are under `guides/<id>/data/fetch-pois/`.

| Stage | Command | Output |
|---|---|---|
| 1. Gazetteer | `uv run python -m pipeline.gazetteer --guide <id> [--refresh]` | `01_gazetteer/gazetteer.jsonl` (raw Overpass response cached alongside) |
| 2. Mention extraction (LLM) | `uv run python -m pipeline.plan extract --guide <id> [--batch 10]` plans; `mention-extractor` subagents execute | `02_mentions/parts/<entry_id>.json` (one part per Entry — the resumability unit) |
| 3. Matching | `uv run python -m pipeline.match --guide <id>` | `04_final/{pois.jsonl,place_pois.jsonl,entry_pois.jsonl,pois.geojson}`; `03_matched/{review.jsonl,unmatched.jsonl,adjudication_queue.jsonl,funnel.json}` (`uv run python -m pipeline.plan funnel --guide <id>` renders the funnel) |
| 4. Adjudication (LLM) | `uv run python -m pipeline.plan adjudicate --guide <id> [--batch 10]` plans; `match-adjudicator` subagents execute; rerun `pipeline.match` to consume | `03_matched/verdicts/<case_id>.json` (one verdict per case — the resumability unit) |

The whole pipeline is driven by the `/fetch-pois` slash command (see
`.claude/commands/fetch-pois.md`): it runs the deterministic stages and fans the
planner's batches out to `mention-extractor` and `match-adjudicator` subagents
until nothing remains. The planner batches the entry list sorted by entry id
(and the adjudication queue in matcher order), so batch numbers and membership
are stable across runs, and an interrupted run resumes without redoing
completed entries or re-adjudicating decided cases.

The gazetteer taxonomy (`tag_map` in the guide's `config.yml`) covers: peak,
pass, hut, glacier, valley, ridge, station, settlement, bridge, path (named
Steige/Wege like the Stangensteig), water (lakes and streams like Rießersee
and Partnach), and locality. Linear features (path, water) arrive from
Overpass as many same-named segments and are deduped to one representative
entry per name. Mountain ranges/regions (Wettersteingebirge) are deliberately
out of scope — no point representation — and the matcher records such mentions
in `unmatched.jsonl` with a `skip_reason` (`out_of_scope` in config) and counts
them as `skipped` in the funnel instead of unmatched.

Valley-floor inns the 1996 book calls Hütten/Häuser are often tagged
`amenity=restaurant` / `tourism=chalet` / `tourism=guest_house` in OSM
(Bockhütte, Kreuzalm, Kreuzjochhaus, Bayernhaus, …). Those tags are fetched
too but guarded (`guarded_tag_map` in config, #14): an element classified only
by a guarded tag becomes a `hut` entry when it is (1) at least
`settlement_exclusion_km` (1 km) from every settlement entry fetched in the
same run and (2) gap-filling — its normalized name is not already in the
gazetteer, so a hut's restaurant sub-element never duplicates the hut and
same-named admissions can't turn existing exact matches into ties. Known
limits: an inn sitting inside a hamlet is excluded along with the town
restaurants (e.g. Almwirtschaft Hintergraseck, right at the Hintergraseck
hamlet node), and a handful of remote-but-mundane names (holiday flats, resort
hotels) are admitted — harmless unless the book mentions an identical name,
in which case the tie/review machinery still applies.

The matcher resolves two kinds of *items* through one deterministic cascade:
each **Place** Entry (matched on its name, guarded by its best-effort
`place_type` hint and verbatim elevation) to at most one POI written as a
`{place_id, poi_id}` row in `place_pois.jsonl`; and every extracted **mention**
(from any Entry's prose) written as a `{entry_id, poi_id, surface}` row in
`entry_pois.jsonl`. The cascade is exact on normalized names, then RapidFuzz
>= 90 guarded by taxonomy-type compatibility and (where the book states one)
elevation agreement within +-50 m — a `place_type` of `null` simply disables
the type guard. Normalization also canonicalizes cable-car station naming drift
("Bergstation der Kreuzeckbahn" ↔ OSM "Kreuzeckbahn Bergstation"). Ties are
never auto-resolved — they become open cases in `review.jsonl`
(`decision: null`); no-candidate items land in `unmatched.jsonl`. A Place that
resolves to nothing is an honest absence surfaced in the funnel's `place` row,
never a dropped record. No route→POI anchor link is emitted: a Route's anchor
coordinate is transitive via its Place.

## LLM adjudication of cascade leftovers

Leftovers — mentions with no exact/fuzzy match that are not ties — go to an
LLM adjudicator when they still have anything worth judging: the matcher
writes each one to `03_matched/adjudication_queue.jsonl` with a shortlist of up
to 10 gazetteer candidates (`ADJUDICATION_SHORTLIST` in `match.py`), ranked by
fuzzy score down to a floor of 60 (`ADJUDICATION_CUTOFF`), deliberately
**unguarded** — the adjudicator sees each candidate's type and elevation and
judges drift the cascade's type/±50 m guards can't (renamed huts, 1996
spellings, book-elevation typos). Leftovers whose best candidate scores below
the floor stay plain unmatched and are never queued.

`uv run python -m pipeline.plan adjudicate --guide <id>` batches the queue for
`match-adjudicator` subagents, attaching each case's Entry context (the owning
Entry's name, kind, `peak` and full description). A subagent must either pick
exactly one
candidate ref or declare no-match — always with a readable reason — and
writes one verdict file per case to `03_matched/verdicts/<case_id>.json`.
Verdict files are the resumability unit: a case with a verdict never
reappears in the plan.

Rerunning the matcher consumes verdicts:

- **Pick**: the candidate enters the registry (and the GeoJSON) with
  `{"method": "llm", "score": ..., "reason": ...}` provenance. `llm` ranks
  *below* the deterministic cascade in best-method selection
  (`review > exact > fuzzy > llm`), and the funnel counts the mention in its
  own `llm` column, so adjudicated matches stay distinguishable from cascade
  matches.
- **No-match**: the mention stays in `unmatched.jsonl` with the reason
  preserved as `llm_reason`.
- Either way the verdict is recorded in `review.jsonl` with `source: "llm"`,
  its shortlist as `candidates`, and `decision: null` — see below for
  overriding it.
- A pick that names anything other than one of the case's current candidates
  (hallucinated, or vanished with a gazetteer refresh) is ignored with a
  `note` on the review case telling you to delete the verdict file to
  re-adjudicate; a verdict file without a `pick`/non-empty `reason` aborts
  the run.

## Review workflow

`03_matched/review.jsonl` holds two kinds of cases, told apart by `source`:
open ties (`"tie"`) awaiting a human decision, and LLM adjudication verdicts
(`"llm"`) recorded for audit and override. Cases are decided (or verdicts
overridden) by editing the file by hand. Each line carries the item (its
`name`, `entry_id` and `kind` — `place` or `mention`) and the `candidates`
(OSM ref, name, type, elevation, coordinates);
`llm` cases additionally carry the `verdict` (pick + reason) and `case_id`
(its verdict file). To decide a case — or overrule an LLM verdict — set its
`decision` field to either

- one of the case's candidate OSM refs (e.g. `"node/2061799676"`) — accept
  that candidate, or
- the string `"skip"` — the mention has no usable OSM representation.

Then rerun the matcher (`uv run python -m pipeline.match --guide <id>`).
Accepted candidates enter the POI registry (and the GeoJSON) with
`{"method": "review"}` provenance, which outranks `exact`, `fuzzy` and `llm`
in best-method selection — a human decision always wins, including over the
LLM verdict it overrides (the verdict stays on the case as the audit trail).
Skipped mentions are routed to `unmatched.jsonl` marked
`"skipped_by": "review"` to distinguish them from mentions the cascade itself
could not resolve. The funnel counts accepted decisions in its `review`
column and human skips under `skipped`; `tie` counts only still-open cases.

Decisions persist: decided cases stay in `review.jsonl` (that file is the
durable decision record) and are re-applied on every rerun, so a decided case
never reappears as open — even after the gazetteer or the extracted mentions
are refreshed. Undecided cases are re-emitted unchanged. Two guard rails:

- A `decision` that is neither `"skip"` nor one of the case's own recorded
  candidate refs is treated as a typo — the matcher aborts with a message
  naming the case and its valid refs, and writes nothing.
- If an accepted ref later disappears from a refetched gazetteer, the case is
  reopened (`decision: null` plus a `note` naming the vanished ref); a tie
  counts as open again and is yours to re-decide, while an `llm` case falls
  back to its recorded verdict (the note keeps the fallback auditable).

A decision applies for as long as the case stays a tie or an adjudication
case; if a gazetteer refresh makes the cascade resolve the mention
deterministically, the case (and its decision) drops out of `review.jsonl`.

## Configuration and data locations

There are **no environment variables** — the removed `AV_POI_DATA`,
`AV_POI_ROUTES` and `AV_POI_OVERPASS_URL` are gone. A guide is selected with the
required `--guide <id>` argument; its data root is
`guides/<id>/data/fetch-pois/`, its upstream routes index is
`guides/<id>/data/parse-routes/03_structured/routes.jsonl`, and the Overpass
endpoint comes from `fetch-pois.overpass_url` (defaulting to the public
endpoint). Tests build a `GuideConfig` pointing at a `tmp_path` and call the
step functions directly.

## Tests

```
uv run pytest
```

## Attribution

The gazetteer and all derived coordinates are © OpenStreetMap contributors,
licensed under the [ODbL](https://www.openstreetmap.org/copyright). Any public
display of this data (including the planned webapp) must credit
"© OpenStreetMap contributors".
