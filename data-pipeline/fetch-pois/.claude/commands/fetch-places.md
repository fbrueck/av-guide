---
description: Resolve a guide's Place entries to OSM POIs (gazetteer → match → LLM adjudication of Place leftovers). The primary, no-bulk-extraction branch of fetch-pois.
---

You are the orchestrator for resolving a guide's **Place** entries (`kind:
place`, structured straight from `routes.jsonl`) to OSM POIs. This is the
primary fetch-pois branch: it produces the coordinate pins (`place_pois.jsonl`)
without the expensive stage-2 mention extraction — Places carry their own name,
`place_type`, and elevation, so no prose is read here. Text **Mentions** are a
separate, later branch (`/fetch-mentions`); see the fetch-pois README.

You run the deterministic stages yourself (via Bash) and delegate only the
per-batch LLM adjudication to subagents, fanned out in parallel. Everything is
resumable — the planner only ever returns cases that still need work, so you can
re-run this command safely after an interruption.

**Guide id is required.** The argument to this command is the guide id (e.g.
`/fetch-places wetterstein`), which selects `guides/<id>/config.yml` and the data
under `guides/<id>/data/fetch-pois/` (the upstream routes index comes from
`guides/<id>/data/parse-routes/03_structured/routes.jsonl`). If no guide id was
given, ask the user for one and stop until they provide it. Pass `--guide <id>`
to every command below.

Run all commands from the `fetch-pois/` package with `uv run python`. Work
through the stages in order.

## Stage 1 — Gazetteer (deterministic, no subagents)

If `guides/<id>/data/fetch-pois/01_gazetteer/gazetteer.jsonl` does not exist, run:

```
uv run python -m pipeline.gazetteer --guide <id>
```

(The raw Overpass response is cached; pass `--refresh` only when the user asks
for fresh OSM data.)

## Stage 2 — Match (deterministic, no subagents)

```
uv run python -m pipeline.match --guide <id>
```

The matcher resolves every item it finds. On a Places-only run no mentions have
been extracted, so it produces the Place → POI links (`place_pois.jsonl`) and
queues any unresolved Places for adjudication.

## Stage 3 — Adjudicate Place leftovers (subagents: `match-adjudicator`)

The matcher queues unresolved Places that still have candidates in
`guides/<id>/data/fetch-pois/03_matched/adjudication_queue.jsonl`.

1. Get the work plan, **restricted to Places**:
   ```
   uv run python -m pipeline.plan adjudicate --guide <id> --kind place --batch 10
   ```
   Each stdout line is a batch: `{"batch": N, "cases": [{"case_id": ...,
   "entry_id": ..., "mention": ..., "candidates": [...], "entry": {...}}, ...]}`.
   `--kind place` keeps this branch from fanning subagents out over Mention
   cases. Cases with an existing verdict file never reappear.
2. For each batch, spawn a `match-adjudicator` subagent, passing it the batch's
   cases verbatim and telling it to write one verdict file per case. Launch up
   to **10 subagents at a time** (multiple Task calls in one message), wave by
   wave, until all batches are done; re-run `pipeline.plan adjudicate --kind
   place` and dispatch whatever remains, until the planner reports nothing to do.
3. Consume the verdicts:
   ```
   uv run python -m pipeline.match --guide <id>
   ```
   Picks enter the registry with `llm` provenance; no-matches stay in
   `unmatched.jsonl` with the reason. Every verdict is recorded in
   `review.jsonl` (`source: "llm"`), where a human can override it later.

## Stage 4 — Validation gate (deterministic, no subagents)

Once matching (and any adjudication) is settled, print the Place audit table for
the operator to sign off on:

```
uv run python -m pipeline.audit --guide <id> --kind place
```

One seeded Markdown table goes to stdout — Place → POI matches, a sample of 30
oversampling the fuzzy/LLM matches, with the match method recomputed per row.
Surface the table to the operator (it is meant to be pasted into an issue
comment for sign-off) along with the stderr summary's miss counts. The export is
not final until the operator signs off.

## Finish

Report: gazetteer entries, the Place rows of the match funnel from the final
matcher summary (the `place` row, its `llm` column and any remaining open ties),
and the paths to `guides/<id>/data/fetch-pois/04_final/` (`pois.jsonl`,
`place_pois.jsonl`, `pois.geojson`). Note that Mentions are the separate
`/fetch-mentions` branch, and flag anything that failed and how to resume.

If the user passes extra scope (e.g. "stage 2 only" or a batch limit) alongside
the guide id, scope the run accordingly instead of doing the whole thing.
