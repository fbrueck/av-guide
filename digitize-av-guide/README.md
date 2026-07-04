# AV-Guide digitalization pipeline

Turns the scanned *Alpenvereinsführer Wetterstein* (Beulke, 4. Auflage 1996) PDF
into clean, structured, machine-readable route data.

The PDF already carries an OCR text layer (from the 2021 Fujitsu ScandAll scan),
so there is **no OCR step** — stage 1 just reads it. The work is repairing the
OCR artifacts and giving the prose structure.

## Architecture: Claude Code is the orchestrator

The `/digitalize` slash command turns Claude Code into the pipeline orchestrator.
It runs the **deterministic tools** itself and delegates the per-page LLM work to
**subagents**, fanned out in parallel — all on your Claude Code subscription, no
API key and no per-token billing.

```
/digitalize  (Claude Code, orchestrator)
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
| `pipeline.extract` | Read text layer + page metadata → `data/01_raw/` | `pipeline/extract.py` |
| `pipeline.plan`    | List/batch pages needing work | `pipeline/plan.py` |
| `pipeline.merge`   | Combine per-page JSON → `routes.jsonl` | `pipeline/merge.py` |
| `ocr-cleaner`      | Subagent: repair OCR for a batch of pages | `.claude/agents/ocr-cleaner.md` |
| `route-extractor`  | Subagent: extract routes (handles routes that span a page break) | `.claude/agents/route-extractor.md` |
| `/digitalize`      | Orchestrator command | `.claude/commands/digitalize.md` |

## Setup

```bash
uv sync   # creates .venv and installs pinned deps from uv.lock
# Claude Code must be logged in (the subagents and orchestrator run on it).
```

## Run

In Claude Code, from the repo root:

```
/digitalize
```

That runs the whole pipeline. You can also drive the deterministic tools by hand:

```bash
.venv/bin/python -m pipeline.extract
.venv/bin/python -m pipeline.plan clean --batch 15
.venv/bin/python -m pipeline.plan structure --batch 15
.venv/bin/python -m pipeline.merge
```

## Output layout

```
data/
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

### Route record fields

Each route file (and `routes.jsonl` line) holds:

| Field | Source |
|-------|--------|
| `route_id`, `source_page` | assigned at merge — links the route to the book page |
| `name`, `peak`, `grade`, `first_ascent`, `time`, `height_m` | **copied verbatim** from the book |
| `description` | **copied verbatim** — the route's complete prose from the book (spans pages if the route does) |
| `summary` | **generated** by the agent — a one-sentence German abstract, no new facts |

The full per-page prose is also preserved in `data/02_clean/pages/`.
