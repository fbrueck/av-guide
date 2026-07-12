---
description: Orchestrate the mountain-POI pipeline (gazetteer → mention extraction → matching) using subagents.
---

You are the orchestrator for resolving the digitized AV-guide routes to OSM
POIs. You run the deterministic stages yourself (via Bash) and delegate the
per-batch LLM work to subagents, fanned out in parallel. Everything is
resumable — the planner only ever returns routes that still need work, so you
can re-run this command safely after an interruption.

Run all commands from the `fetch-mountain-poi/` package with `uv run python`.
Work through the stages in order.

## Stage 1 — Gazetteer (deterministic, no subagents)

If `data/01_gazetteer/gazetteer.jsonl` does not exist, run:

```
uv run python -m pipeline.gazetteer
```

(The raw Overpass response is cached; pass `--refresh` only when the user asks
for fresh OSM data.)

## Stage 2 — Extract mentions (subagents: `mention-extractor`)

1. Get the work plan:
   ```
   uv run python -m pipeline.plan extract --batch 10
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
uv run python -m pipeline.match
```

## Finish

Report: gazetteer entries, routes extracted, mentions found, the match funnel
from the matcher's summary, and the paths to `data/04_final/`. Note anything
that failed and how to resume.

If the user passes an argument (e.g. "stage 2 only" or a batch limit), scope
the run accordingly instead of doing the whole thing.
