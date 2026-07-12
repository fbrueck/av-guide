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
| 3. Matching | `uv run python -m pipeline.match` | `data/04_final/{pois.jsonl,route_pois.jsonl,pois.geojson}`, open cases in `data/03_matched/anchor_open.jsonl` |

The whole pipeline is driven by the `/fetch-poi` slash command (see
`.claude/commands/fetch-poi.md`): it runs the deterministic stages and fans the
planner's batches out to `mention-extractor` subagents until nothing remains.
The planner batches the route list sorted by route_id, so batch numbers and
membership are stable across runs, and an interrupted run resumes without
redoing completed routes.

Currently the matcher resolves route anchors (the `peak` field) by exact
matching on normalized names. Fuzzy matching, tie review, and LLM adjudication
are later tickets.

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
