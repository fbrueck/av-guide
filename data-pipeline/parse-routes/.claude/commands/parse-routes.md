---
description: Orchestrate the parse-routes pipeline (extract → clean → structure) for one guide using subagents.
---

You are the orchestrator for parsing a scanned alpine guidebook into structured
Entry data (Places and Routes). You run the deterministic tools yourself (via
Bash) and delegate the
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

1. Get the guide's facts block once — you pass it verbatim to **every**
   `ocr-cleaner` so the prompt stays guide-agnostic (the guidebook's
   title/author/edition/year/language come from config, never the prompt body):
   ```
   .venv/bin/python -m pipeline.facts --guide <id>
   ```
2. Get the work plan:
   ```
   .venv/bin/python -m pipeline.plan clean --guide <id> --batch 15
   ```
   Each stdout line is a batch: `{"batch": N, "pages": ["page_0006", ...]}`.
   (Sketch/image pages are passed through automatically and won't appear.)
3. For each batch, spawn an `ocr-cleaner` subagent, passing it (a) the Guide
   facts block from step 1 and (b) the exact list of page stems for that batch,
   and telling it to clean those pages. Launch up to **10 subagents at a time**
   (multiple Task calls in one message), wait for the wave to finish, then launch
   the next wave, until all batches are done.
4. If any batch reports failures, just re-run `pipeline.plan clean` — completed
   pages are skipped — and dispatch the remaining batches again.

## Stage 3 — Structure entries (subagents: `toc-extractor`, `entry-extractor`)

1. **Section map (once per guide).** The entry-extractor classifies each entry by
   the book section it falls in, so build the section map from the guide's
   Inhaltsverzeichnis first. If
   `guides/<id>/data/parse-routes/03_structured/sections.json` does not exist:
   ```
   .venv/bin/python -m pipeline.sections plan --guide <id>
   ```
   prints the Inhaltsverzeichnis page stems. Spawn **one** `toc-extractor`
   subagent, passing it the Guide facts block and those stems; it writes
   `sections.json`. (If the guide has no `toc_pages` configured, `plan` errors —
   classification then falls back to heading shape only; skip this step.)
   Then render the block you will inject into every extractor:
   ```
   .venv/bin/python -m pipeline.sections render --guide <id>
   ```
2. Get the work plan:
   ```
   .venv/bin/python -m pipeline.plan structure --guide <id> --batch 15
   ```
3. For each batch, spawn an `entry-extractor` subagent, passing it (a) the same
   Guide facts block you fetched once in Stage 2, (b) the **Section map block**
   from step 1 (so the extractor prompt stays guide-agnostic), and (c) the list
   of stems.
   Same wave discipline: up to 10 at a time. These subagents read each batch
   page plus its neighbours **once** so entries spanning a page break are
   captured once; each entry is classified as a Place, a Route, or a Traverse
   (by its section) and carries the book's entry id.
4. Merge the per-page JSON into the final dataset:
   ```
   .venv/bin/python -m pipeline.merge --guide <id>
   ```
   `merge` keys entries by their book entry id, links each Route to its
   Destination (`destination_id`) and any additional target Places (`place_ids`),
   parses inline cross-references, validates the id graph (reporting any dangling
   refs / missing destinations / unresolved places), and also writes the
   route-map contract `routes.json`. To regenerate the contract alone (without a
   full re-merge), run:
   ```
   .venv/bin/python -m pipeline.export --guide <id>
   ```

## Stage 4 — Repair unsliceable anchors (subagents: `anchor-repairer`)

Optional recovery pass (#113). `merge` writes an **unsliced report**
(`03_structured/unsliced.jsonl`) listing every entry whose verbatim description
could not be sliced, each tagged with a reason bucket. The `end_mismatch`,
`start_not_found`, and `start_ambiguous` buckets are a fidelity problem — the
text is on the page but the emitted anchor is not a char-exact copy. This pass
asks subagents for corrected anchors and re-slices deterministically (the
exact-by-construction guarantee holds — no fuzzy matching). The `empty_anchor`
bucket is fixed by re-extracting the page (Stage 3), and `stub` entries have no
gap to cut — neither is repaired here.

1. Get the repair plan (only the repairable buckets appear):
   ```
   .venv/bin/python -m pipeline.repair plan --guide <id> --batch 15
   ```
   Each stdout line is a batch: `{"batch": N, "tasks": [ {entry_id, stem, name,
   reason, start_quote, end_quote}, … ]}`.
2. For each batch, spawn an `anchor-repairer` subagent with that batch's task
   list. Same wave discipline as Stage 3: up to 10 at a time. Each subagent reads
   the cleaned page, copies corrected char-exact anchors, and writes one
   `03_structured/repairs/<entry_id>.json` per entry it could fix.
3. Apply the corrected anchors back into the page part files, then re-merge:
   ```
   .venv/bin/python -m pipeline.repair apply --guide <id>
   .venv/bin/python -m pipeline.merge --guide <id>
   ```
   Re-running is idempotent — `plan` only lists entries still unsliced, so
   already-sliceable entries are never touched. Repeat 1–3 if the unsliced count
   is still dropping; entries the subagents could not place honestly stay in the
   report.

## Finish

Report: pages extracted, pages cleaned, entries found (places vs routes), any
synthetic ids / dangling references / missing destinations / unresolved places
surfaced by merge, and
the paths to `guides/<id>/data/parse-routes/03_structured/routes.jsonl` (index)
and `routes.json` (route-map contract). Note anything that failed and how to
resume.

If the user passes extra scope (e.g. a page range or "stage 2 only") alongside
the guide id, scope the run accordingly instead of doing the whole thing.
