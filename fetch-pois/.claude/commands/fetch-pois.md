---
description: Orchestrate the fetch-pois pipeline (gazetteer → mention extraction → matching → LLM adjudication) for one guide using subagents.
---

You are the orchestrator for resolving parsed guidebook routes to OSM POIs. You
run the deterministic stages yourself (via Bash) and delegate the per-batch LLM
work to subagents, fanned out in parallel. Everything is resumable — the planner
only ever returns routes that still need work, so you can re-run this command
safely after an interruption.

**Guide id is required.** The argument to this command is the guide id (e.g.
`/fetch-pois wetterstein`), which selects `guides/<id>/config.yml` and the data
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

## Stage 2 — Extract mentions (subagents: `mention-extractor`)

1. Get the work plan:
   ```
   uv run python -m pipeline.plan extract --guide <id> --batch 10
   ```
   Each stdout line is a batch: `{"batch": N, "routes": [{"route_id": ...,
   "peak": ..., "description": ...}, ...]}`. Batch numbers are stable across
   runs; already-extracted routes never reappear.
2. For each batch, spawn a `mention-extractor` subagent, passing it the batch's
   routes (route_id, peak, description) verbatim and telling it to extract
   mentions for those routes. Launch up to **5 subagents at a time** (multiple
   Task calls in one message), wait for the wave to finish, then launch the
   next wave, until all batches are done.
3. Re-run `pipeline.plan extract` — completed routes are skipped — and dispatch
   whatever remains, until the planner reports nothing to do.

## Stage 3 — Match (deterministic, no subagents)

```
uv run python -m pipeline.match --guide <id>
```

## Stage 4 — Adjudicate leftovers (subagents: `match-adjudicator`)

The matcher queues unresolved mentions that still have candidates in
`guides/<id>/data/fetch-pois/03_matched/adjudication_queue.jsonl`.

1. Get the work plan:
   ```
   uv run python -m pipeline.plan adjudicate --guide <id> --batch 10
   ```
   Each stdout line is a batch: `{"batch": N, "cases": [{"case_id": ...,
   "mention": ..., "candidates": [...], "route": {...}}, ...]}`. Cases with an
   existing verdict file never reappear.
2. For each batch, spawn a `match-adjudicator` subagent, passing it the
   batch's cases verbatim and telling it to write one verdict file per case.
   Launch up to **5 subagents at a time**, wave by wave, until all batches are
   done; re-run `pipeline.plan adjudicate` and dispatch whatever remains,
   until the planner reports nothing to do.
3. Consume the verdicts:
   ```
   uv run python -m pipeline.match --guide <id>
   ```
   Picks enter the registry with `llm` provenance; no-matches stay in
   `unmatched.jsonl` with the reason. Every verdict is recorded in
   `review.jsonl` (`source: "llm"`), where a human can override it later.

## Finish

Report: gazetteer entries, routes extracted, mentions found, the match funnel
from the final matcher summary (including the `llm` column and remaining open
ties), and the paths to `guides/<id>/data/fetch-pois/04_final/`. Note anything
that failed and how to resume.

If the user passes extra scope (e.g. "stage 2 only" or a batch limit) alongside
the guide id, scope the run accordingly instead of doing the whole thing.
