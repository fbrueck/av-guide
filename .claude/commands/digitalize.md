---
description: Orchestrate the AV-guide digitalization pipeline (extract → clean → structure) using subagents.
---

You are the orchestrator for digitalizing the scanned Wetterstein alpine guide.
You run the deterministic tools yourself (via Bash) and delegate the per-page
LLM work to subagents, fanned out in parallel. Everything is resumable — the
planner only ever returns pages that still need work, so you can re-run this
command safely after an interruption.

Use `.venv/bin/python` for all commands. Work through the stages in order.

## Stage 1 — Extract (deterministic, no subagents)

If `data/01_raw/manifest.jsonl` does not exist, run:

```
.venv/bin/python -m pipeline.extract
```

## Stage 2 — Clean OCR (subagents: `ocr-cleaner`)

1. Get the work plan:
   ```
   .venv/bin/python -m pipeline.plan clean --batch 15
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
   .venv/bin/python -m pipeline.plan structure --batch 15
   ```
2. For each batch, spawn a `route-extractor` subagent with the list of stems.
   Same wave discipline: up to 5 at a time. These subagents read each page plus
   its neighbours so routes spanning a page break are captured once.
3. Merge the per-page JSON into the final dataset:
   ```
   .venv/bin/python -m pipeline.merge
   ```

## Finish

Report: pages extracted, pages cleaned, routes found, and the path to
`data/03_structured/routes.jsonl`. Note anything that failed and how to resume.

If the user passes an argument (e.g. a page range or "stage 2 only"), scope the
run accordingly instead of doing the whole thing.
