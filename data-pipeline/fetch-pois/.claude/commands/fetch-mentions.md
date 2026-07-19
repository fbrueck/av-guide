---
description: Resolve a guide's prose Mentions to OSM POIs (extract → match → LLM adjudication of Mention leftovers). The bonus fetch-pois branch, run after /fetch-places.
---

You are the orchestrator for resolving a guide's text **Mentions** (place-names
stage 2 extracts from *any* Entry's prose — a Route description or a Place
Übersicht) to OSM POIs. This is the bonus fetch-pois branch: Mentions are lower
value than Place entries and cost a full LLM extraction pass over all prose, so
they run separately and later.

**Run `/fetch-places <id>` first.** Mentions build on the Places branch: the
matcher shares one gazetteer, and the Mention adjudicator uses each Route's
resolved Destination POI (from `place_pois.jsonl`) as a geographic prior. If the
Places branch has not run for this guide, run it first (or expect a weaker
adjudication context and no Place coordinates).

You run the deterministic stages yourself (via Bash) and delegate the per-batch
LLM work — mention extraction and adjudication — to subagents, fanned out in
parallel. Everything is resumable — the planner only ever returns work that
still needs doing, so you can re-run this command safely after an interruption.

**Guide id is required.** The argument to this command is the guide id (e.g.
`/fetch-mentions wetterstein`), which selects `guides/<id>/config.yml` and the
data under `guides/<id>/data/fetch-pois/` (the upstream routes index comes from
`guides/<id>/data/parse-routes/03_structured/routes.jsonl`). If no guide id was
given, ask the user for one and stop until they provide it. Pass `--guide <id>`
to every command below.

Run all commands from the `fetch-pois/` package with `uv run python`. Work
through the stages in order.

## Stage 1 — Gazetteer (deterministic, no subagents)

If `guides/<id>/data/fetch-pois/01_gazetteer/gazetteer.jsonl` does not exist (it
should, from `/fetch-places`), run:

```
uv run python -m pipeline.gazetteer --guide <id>
```

## Stage 2 — Extract mentions (subagents: `mention-extractor`)

Mention extraction runs over **every Entry's** prose — a Route's description
*and* a Place's Übersicht.

1. Get the work plan:
   ```
   uv run python -m pipeline.plan extract --guide <id> --batch 10
   ```
   Each stdout line is a batch: `{"batch": N, "entries": [{"entry_id": ...,
   "kind": ..., "name": ..., "source": ...}, ...]}`. Each descriptor is
   lightweight: `source` is a path to the entry's prose on disk, **not** the
   prose itself, so the bulk text never enters your context. Batch numbers are
   stable across runs; already-extracted entries never reappear.
2. For each batch, spawn a `mention-extractor` subagent, passing it the batch's
   descriptors (entry_id, kind, name, source) verbatim and telling it to Read
   each entry's prose from its `source` file and extract mentions. Do **not**
   read the source files yourself. Launch up to **10 subagents at a time**
   (multiple Task calls in one message), wait for the wave to finish, then
   launch the next wave, until all batches are done.
3. Re-run `pipeline.plan extract` — completed entries are skipped — and
   dispatch whatever remains, until the planner reports nothing to do.

## Stage 3 — Match (deterministic, no subagents)

```
uv run python -m pipeline.match --guide <id>
```

The matcher resolves every item in one idempotent pass: it refreshes the Place →
POI links (unchanged since `/fetch-places`, so this is a cheap deterministic
re-run) and adds the Mention → POI links (`entry_pois.jsonl`), queuing
unresolved Mentions that still have candidates for adjudication.

## Stage 4 — Adjudicate Mention leftovers (subagents: `match-adjudicator`)

1. Get the work plan, **restricted to Mentions**:
   ```
   uv run python -m pipeline.plan adjudicate --guide <id> --kind mention --batch 10
   ```
   `--kind mention` keeps this branch off the Place cases (already settled by
   `/fetch-places`). Cases with an existing verdict file never reappear.
2. For each batch, spawn a `match-adjudicator` subagent, passing it the batch's
   cases verbatim and telling it to write one verdict file per case. Launch up
   to **10 subagents at a time**, wave by wave, until all batches are done;
   re-run `pipeline.plan adjudicate --kind mention` and dispatch whatever
   remains, until the planner reports nothing to do.
3. Consume the verdicts:
   ```
   uv run python -m pipeline.match --guide <id>
   ```
   Picks enter the registry with `llm` provenance; no-matches stay in
   `unmatched.jsonl` with the reason. Every verdict is recorded in
   `review.jsonl` (`source: "llm"`), where a human can override it later.

## Stage 5 — Validation gate (deterministic, no subagents)

```
uv run python -m pipeline.audit --guide <id> --kind mention
```

One seeded Markdown table goes to stdout — Entry mentions → POI, a sample of 30
oversampling the fuzzy/LLM matches, with the match method recomputed per row.
Surface the table to the operator (meant to be pasted into an issue comment for
sign-off) along with the stderr summary's miss counts. The export is not final
until the operator signs off.

## Finish

Report: entries extracted, mentions found, the Mention rows of the match funnel
from the final matcher summary (the `llm` column and any remaining open ties),
and the paths to `guides/<id>/data/fetch-pois/04_final/` (`pois.jsonl`,
`entry_pois.jsonl`, `pois.geojson`). Note anything that failed and how to resume.

If the user passes extra scope (e.g. "stage 2 only" or a batch limit) alongside
the guide id, scope the run accordingly instead of doing the whole thing.
