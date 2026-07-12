# fetch-mountain-poi

Resolves the places named in the digitized AV-guide routes (`digitize-av-guide`)
to OpenStreetMap coordinates: a gazetteer-first pipeline that fetches all named
alpine features in the Wetterstein bbox via Overpass, extracts typed place
mentions from route descriptions, matches them deterministically, and emits a
deduplicated POI registry plus a webapp-ready GeoJSON export.

Spec and tickets: see the repo issue tracker (spec is issue #1).

## Stages

| Stage | Command | Output |
|---|---|---|
| 1. Gazetteer | `uv run python -m pipeline.gazetteer [--refresh]` | `data/01_gazetteer/gazetteer.jsonl` (raw Overpass response cached alongside) |
| 2. Mention extraction (LLM) | `uv run python -m pipeline.plan extract [--batch 10]` plans; `mention-extractor` subagents execute | `data/02_mentions/parts/<route_id>.json` (one part per route — the resumability unit) |
| 3. Matching | `uv run python -m pipeline.match` | `data/04_final/{pois.jsonl,route_pois.jsonl,pois.geojson}`; `data/03_matched/{review.jsonl,unmatched.jsonl,funnel.json}` (`uv run python -m pipeline.plan funnel` renders the funnel) |

The whole pipeline is driven by the `/fetch-poi` slash command (see
`.claude/commands/fetch-poi.md`): it runs the deterministic stages and fans the
planner's batches out to `mention-extractor` subagents until nothing remains.
The planner batches the route list sorted by route_id, so batch numbers and
membership are stable across runs, and an interrupted run resumes without
redoing completed routes.

The gazetteer taxonomy (`TAG_MAP` in `pipeline/config.py`) covers: peak, pass,
hut, glacier, valley, ridge, station, settlement, bridge, path (named
Steige/Wege like the Stangensteig), water (lakes and streams like Rießersee
and Partnach), and locality. Linear features (path, water) arrive from
Overpass as many same-named segments and are deduped to one representative
entry per name. Mountain ranges/regions (Wettersteingebirge) are deliberately
out of scope — no point representation — and the matcher records such mentions
in `unmatched.jsonl` with a `skip_reason` (`OUT_OF_SCOPE` in config) and counts
them as `skipped` in the funnel instead of unmatched.

Valley-floor inns the 1996 book calls Hütten/Häuser are often tagged
`amenity=restaurant` / `tourism=chalet` / `tourism=guest_house` in OSM
(Bockhütte, Kreuzalm, Kreuzjochhaus, Bayernhaus, …). Those tags are fetched
too but guarded (`GUARDED_TAG_MAP` in config, #14): an element classified only
by a guarded tag becomes a `hut` entry when it is (1) at least
`SETTLEMENT_EXCLUSION_KM` (1 km) from every settlement entry fetched in the
same run and (2) gap-filling — its normalized name is not already in the
gazetteer, so a hut's restaurant sub-element never duplicates the hut and
same-named admissions can't turn existing exact matches into ties. Known
limits: an inn sitting inside a hamlet is excluded along with the town
restaurants (e.g. Almwirtschaft Hintergraseck, right at the Hintergraseck
hamlet node), and a handful of remote-but-mundane names (holiday flats, resort
hotels) are admitted — harmless unless the book mentions an identical name,
in which case the tie/review machinery still applies.

The matcher resolves route anchors (the `peak` field) and every extracted
mention through a deterministic cascade: exact on normalized names, then
RapidFuzz >= 90 guarded by taxonomy-type compatibility and (where the book
states one) elevation agreement within +-50 m. Normalization also
canonicalizes cable-car station naming drift ("Bergstation der Kreuzeckbahn" ↔
OSM "Kreuzeckbahn Bergstation"). Ties are never auto-resolved — they become
open cases in `review.jsonl` (`decision: null`); no-candidate mentions land in
`unmatched.jsonl`. LLM adjudication of the leftovers is a later ticket.

## Review workflow

Open tie cases in `data/03_matched/review.jsonl` are decided by editing the
file by hand. Each line carries the mention, its route, and the surviving
`candidates` (OSM ref, name, type, elevation, coordinates). To decide a case,
set its `decision` field to either

- one of the case's candidate OSM refs (e.g. `"node/2061799676"`) — accept
  that candidate, or
- the string `"skip"` — the mention has no usable OSM representation.

Then rerun the matcher (`uv run python -m pipeline.match`). Accepted
candidates enter the POI registry (and the GeoJSON) with
`{"method": "review"}` provenance, which outranks `exact` and `fuzzy` in
best-method selection — a human decision always wins. Skipped mentions are
routed to `unmatched.jsonl` marked `"skipped_by": "review"` to distinguish
them from mentions the cascade itself could not resolve. The funnel counts
accepted decisions in its `review` column and human skips under `skipped`;
`tie` counts only still-open cases.

Decisions persist: decided cases stay in `review.jsonl` (that file is the
durable decision record) and are re-applied on every rerun, so a decided case
never reappears as open — even after the gazetteer or the extracted mentions
are refreshed. Undecided cases are re-emitted unchanged. Two guard rails:

- A `decision` that is neither `"skip"` nor one of the case's own recorded
  candidate refs is treated as a typo — the matcher aborts with a message
  naming the case and its valid refs, and writes nothing.
- If an accepted ref later disappears from a refetched gazetteer, the case is
  reopened (`decision: null` plus a `note` naming the vanished ref) and
  counted as an open tie again; decide it afresh.

A decision applies for as long as the case remains a tie; if a gazetteer
refresh makes the cascade resolve the mention deterministically, the case
(and its decision) drops out of `review.jsonl`.

The data root defaults to `./data` and can be overridden with `AV_POI_DATA`;
the route index defaults to the digitization package's `routes.jsonl` and can
be overridden with `AV_POI_ROUTES`. Tests use these to run the stages against
fixture directories.

## Tests

```
uv run pytest
```

## Attribution

The gazetteer and all derived coordinates are © OpenStreetMap contributors,
licensed under the [ODbL](https://www.openstreetmap.org/copyright). Any public
display of this data (including the planned webapp) must credit
"© OpenStreetMap contributors".
