---
description: Orchestrate the parse-routes pipeline (extract → clean → structure) for one guide using subagents.
---

You are the orchestrator for parsing a scanned alpine guidebook into structured
route data. You run the deterministic tools yourself (via Bash) and delegate the
per-page LLM work to subagents, fanned out in parallel. Everything is resumable —
the planner only ever returns pages that still need work, so you can re-run this
command safely after an interruption.

**Guide id is required.** The argument to this command is the guide id (e.g.
`/parse-routes wetterstein`), which selects `guides/<id>/config.yml` and the data
under `guides/<id>/data/parse-routes/`. If no guide id was given, ask the user
for one and stop until they provide it. Pass `--guide <id>` to every command
below.

Run all commands from the `parse-routes/` package with `.venv/bin/python`. Work
through the stages in order.

## Stage 1 — Extract (deterministic, no subagents)

If `guides/<id>/data/parse-routes/01_raw/manifest.jsonl` does not exist, run:

```
.venv/bin/python -m pipeline.extract --guide <id>
```

## Stage 2 — Clean OCR (subagents: `ocr-cleaner`)

1. Get the work plan:
   ```
   .venv/bin/python -m pipeline.plan clean --guide <id> --batch 15
   ```
   Each stdout line is a batch: `{"batch": N, "pages": ["page_0006", ...]}`.
   (Sketch/image pages are passed through automatically and won't appear.)
2. For each batch, spawn an `ocr-cleaner` subagent, passing it the exact list of
   page stems for that batch and telling it to clean those pages. Launch up to
   **5 subagents at a time** (multiple Task calls in one message), wait for the
   wave to finish, then launch the next wave, until all batches are done.
3. If any batch reports failures, just re-run `pipeline.plan clean` — completed
   pages are skipped — and dispatch the remaining batches again.

## Stage 3 — Structure routes (subagents: `route-extractor`)

1. Get the work plan:
   ```
   .venv/bin/python -m pipeline.plan structure --guide <id> --batch 15
   ```
2. For each batch, spawn a `route-extractor` subagent with the list of stems.
   Same wave discipline: up to 5 at a time. These subagents read each page plus
   its neighbours so routes spanning a page break are captured once.
3. Merge the per-page JSON into the final dataset:
   ```
   .venv/bin/python -m pipeline.merge --guide <id>
   ```
   `merge` also writes the route-map contract `routes.json`. To regenerate it
   alone (without a full re-merge), run:
   ```
   .venv/bin/python -m pipeline.export --guide <id>
   ```

## Finish

Report: pages extracted, pages cleaned, routes found, and the paths to
`guides/<id>/data/parse-routes/03_structured/routes.jsonl` (index) and
`routes.json` (route-map contract). Note anything that failed and how to resume.

If the user passes extra scope (e.g. a page range or "stage 2 only") alongside
the guide id, scope the run accordingly instead of doing the whole thing.
