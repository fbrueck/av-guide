# parse-routes

Turns a scanned *Alpenvereinsführer* guidebook PDF into clean, structured,
machine-readable route data. The reference guide is the *Wetterstein* (Beulke,
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
   ├─ Task × N: route-extractor        subagents — extract routes (cross-page aware)
   └─ Bash: pipeline.merge             deterministic — build routes.jsonl
```

Everything is **resumable**: the planner only ever returns pages that still need
work, so a re-run skips whatever is already done.

| Piece | What it is | Where |
|-------|-----------|-------|
| `pipeline.config` | `GuideConfig`, `load_guide`, path helpers | `pipeline/config.py` |
| `pipeline.extract` | Read text layer + page metadata → `01_raw/` | `pipeline/extract.py` |
| `pipeline.plan`    | List/batch pages needing work | `pipeline/plan.py` |
| `pipeline.merge`   | Combine per-page JSON → `routes.jsonl` | `pipeline/merge.py` |
| `ocr-cleaner`      | Subagent: repair OCR for a batch of pages | `.claude/agents/ocr-cleaner.md` |
| `route-extractor`  | Subagent: extract routes (handles page-break spans) | `.claude/agents/route-extractor.md` |
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
  parts/page_0051.json  # routes starting on each page (written by route-extractor)
  routes/p0051_01.json  # FINAL: one self-contained file per route
  routes.jsonl          # combined index — one route record per line
```

`routes.jsonl` is the artifact the downstream **fetch-pois** pipeline consumes.

### Route record fields

Each route file (and `routes.jsonl` line) holds:

| Field | Source |
|-------|--------|
| `route_id`, `source_page` | assigned at merge — links the route to the book page |
| `name`, `peak`, `grade`, `first_ascent`, `time`, `height_m` | **copied verbatim** from the book |
| `description` | **copied verbatim** — the route's complete prose (spans pages if the route does) |
| `summary` | **generated** by the agent — a one-sentence German abstract, no new facts |

The full per-page prose is also preserved in `02_clean/pages/`.

## Tests

```
uv run pytest
```
