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

The matcher resolves route anchors (the `peak` field) and every extracted
mention through a deterministic cascade: exact on normalized names, then
RapidFuzz >= 90 guarded by taxonomy-type compatibility and (where the book
states one) elevation agreement within +-50 m. Normalization also
canonicalizes cable-car station naming drift ("Bergstation der Kreuzeckbahn" ↔
OSM "Kreuzeckbahn Bergstation"). Ties are never auto-resolved — they become
open cases in `review.jsonl` (`decision: null`; filled-in decisions survive
reruns); no-candidate mentions land in `unmatched.jsonl`. LLM adjudication of
the leftovers is a later ticket.

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
