# parse-routes

Turns a scanned *Alpenvereinsführer* guidebook PDF into clean, structured,
machine-readable **Entry** data — the book's **Places** (huts, summits, passes)
and the **Routes** filed under them, each keyed by the book's own **entry id**
(see `CONTEXT.md`, [ADR 0001](../../docs/adr/0001-entry-place-route-model.md)).
The reference guide is the *Wetterstein* (Beulke,
4. Auflage 1996), but the pipeline is guide-agnostic: everything guide-specific
lives in external config and data (see **Guides** below), so the same code
processes any guidebook.

The Wetterstein PDF already carries an OCR text layer (from the 2021 Fujitsu
ScandAll scan), so there is **no OCR step** — stage 1 just reads it. The work is
repairing the OCR artifacts and giving the prose structure.

## Guides

A guide is one directory at the repo root:

```
guides/<id>/
  config.yml            # committed: guide facts + per-pipeline settings
  data/parse-routes/    # gitignored: this pipeline's artifacts (+ the PDF)
  data/fetch-pois/      # gitignored: the downstream fetch-pois pipeline
```

`config.yml` holds shared top-level facts (`id`, `bbox`) plus a `parse-routes:`
subsection read by this pipeline:

```yaml
id: wetterstein
bbox: [47.30, 10.85, 47.55, 11.35]
parse-routes:
  pdf: Wetterstein_Beulke_4_Auflage_1996.pdf   # resolved under data/parse-routes/
  min_text_chars: 200                          # below this a page is an image/sketch
```

The **fixed on-disk stage layout is not in the YAML** — it lives in code
(`pipeline/config.py` path helpers, derived from `data_root =
guides/<id>/data/parse-routes`). The source PDF lives at
`guides/<id>/data/parse-routes/<pdf>` and is gitignored.

Every command takes a required `--guide <id>` argument; there is no default.
`pipeline/config.py` loads `guides/<id>/config.yml` into an immutable
`GuideConfig`, which each pure step function takes as an argument.

## Architecture: Claude Code is the orchestrator

The `/parse-routes` slash command turns Claude Code into the pipeline
orchestrator. It runs the **deterministic tools** itself and delegates the
per-page LLM work to **subagents**, fanned out in parallel — all on your Claude
Code subscription, no API key and no per-token billing.

```
/parse-routes wetterstein  (Claude Code, orchestrator)
   │
   ├─ Bash: pipeline.extract           deterministic — read OCR text layer
   ├─ Bash: pipeline.plan clean        deterministic — which pages need cleaning
   ├─ Task × N: ocr-cleaner            subagents — repair OCR per page
   ├─ Bash: pipeline.plan structure    deterministic — which pages need structuring
   ├─ Task × N: entry-extractor        subagents — classify + extract Entries (cross-page aware)
   └─ Bash: pipeline.merge             deterministic — key by entry id, link anchors, build routes.jsonl
```

Everything is **resumable**: the planner only ever returns pages that still need
work, so a re-run skips whatever is already done.

| Piece | What it is | Where |
|-------|-----------|-------|
| `pipeline.config` | `GuideConfig`, `load_guide`, path helpers | `pipeline/config.py` |
| `pipeline.extract` | Read text layer + page metadata → `01_raw/` | `pipeline/extract.py` |
| `pipeline.plan`    | List/batch pages needing work | `pipeline/plan.py` |
| `pipeline.ids`     | Canonical entry-id normalization (`R43`) + synthetic fallback | `pipeline/ids.py` |
| `pipeline.references` | Parse inline cross-refs (`Wie R 43`) → `{ref_id, surface}` | `pipeline/references.py` |
| `pipeline.merge`   | Key Entries by id, link anchors, validate → `routes.jsonl` | `pipeline/merge.py` |
| `pipeline.export`  | Project Entries onto the route-map contract → `routes.json` | `pipeline/export.py` |
| `ocr-cleaner`      | Subagent: repair OCR for a batch of pages | `.claude/agents/ocr-cleaner.md` |
| `entry-extractor`  | Subagent: classify + extract Entries (handles page-break spans) | `.claude/agents/entry-extractor.md` |
| `/parse-routes`    | Orchestrator command | `.claude/commands/parse-routes.md` |

## Setup

```bash
uv sync   # creates .venv and installs pinned deps from uv.lock
# Claude Code must be logged in (the subagents and orchestrator run on it).
```

## Run

In Claude Code, from the repo root:

```
/parse-routes wetterstein
```

That runs the whole pipeline for the `wetterstein` guide. You can also drive the
deterministic tools by hand (every command needs `--guide`):

```bash
.venv/bin/python -m pipeline.extract   --guide wetterstein
.venv/bin/python -m pipeline.plan clean     --guide wetterstein --batch 15
.venv/bin/python -m pipeline.plan structure --guide wetterstein --batch 15
.venv/bin/python -m pipeline.merge     --guide wetterstein
.venv/bin/python -m pipeline.export    --guide wetterstein
```

## Output layout

Under `guides/<id>/data/parse-routes/` (gitignored):

```
01_raw/
  manifest.jsonl        # per-page metadata (char_count, rotation, is_sketch, ...)
  pages/page_0001.txt   # raw OCR text, one file per page
02_clean/
  pages/page_0001.txt   # OCR-repaired text (written by ocr-cleaner subagents)
03_structured/
  parts/page_0051.json  # Entries starting on each page (written by entry-extractor)
  entries/R55.json      # FINAL: one self-contained file per Entry, keyed by entry id
  routes.jsonl          # combined index — one Entry record per line, in book order
  routes.json           # route-map data contract — a plain JSON array
```

`routes.jsonl` is the artifact the downstream **fetch-pois** pipeline consumes.
`routes.json` is the **route-map** webapp's contract: the same Entries as a plain
JSON array, projected to a stable field set (see below) so the browser loads
Entry metadata without parsing JSONL. It is written by `pipeline.export` and
also regenerated by `pipeline.merge`, so it never drifts from `routes.jsonl`.

(The filenames stay `routes.jsonl` / `routes.json` for contract stability, but
each line is now an **Entry** — a Place or a Route — not only a route.)

### Entry record fields

Every Entry (`routes.jsonl` line and `entries/<id>.json` file) carries the
shared identity/link fields; Places and Routes then add their own kind's fields.

| Field | Source |
|-------|--------|
| `id` | the book's **entry id**, normalized (`R43`, `R376A`), or a deterministic synthetic fallback |
| `id_source` | `book` \| `synthetic` — flags whether the Randziffer was recoverable from OCR |
| `kind` | `place` \| `route` — classified by the extractor |
| `source_page` | assigned at merge — links the Entry to the book page (internal, not in the contract) |
| `name`, `description` | **copied verbatim** from the book (`description` spans pages if the entry does) |
| `summary` | **generated** by the agent — a one-sentence German abstract, no new facts |
| `references` | `[{ref_id, surface}]` — inline cross-refs parsed from the description; unresolvable ones surfaced, not dropped |
| **Place:** `place_type`, `elevation` | best-effort category + verbatim elevation |
| **Route:** `peak`, `grade`, `first_ascent`, `time`, `height_m` | **copied verbatim** from the book |
| **Route:** `anchor_ids` | target Place ids — structural parent + traverse targets resolved by name (`[]` if orphan) |

The full per-page prose is also preserved in `02_clean/pages/`.

The `routes.json` contract is a projection of these onto a stable field set —
`id`, `kind`, `name`, `place_type`, `elevation`, `peak`, `grade`, `time`,
`height_m`, `first_ascent`, `anchor_ids`, `references`, `summary`, `description`
— dropping internal bookkeeping like `source_page` and `id_source`. Scalar
fields absent for a kind are `null`; the link fields (`anchor_ids`,
`references`) default to `[]`. That projection is the boundary the **route-map**
webapp (#44) and the **fetch-pois** pipeline (#43) depend on; keep it in step
with their contracts (`route-map/CLAUDE.md`) when any of them changes.

## Tests

```
uv run pytest
```
