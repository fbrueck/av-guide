# data-pipeline — conventions

The Python data pipelines that turn a scanned guidebook into mapped route data.
Repo-wide rules (contribution workflow, module layout, domain language) live in
the root `CLAUDE.md`; this file owns everything specific to the pipelines.

```
data-pipeline/
  parse-routes/   # stage A: PDF (OCR text layer) -> structured Entries (Places + Routes), keyed by book entry id
  fetch-pois/     # stage B: Entry place-names -> OpenStreetMap POIs + GeoJSON
```

`parse-routes` follows the **Entry model** (`CONTEXT.md`, ADR 0001/0002): each
extracted item is classified `kind: place | route`, keyed by the book's own
**entry id** (normalized `R43`, deterministic synthetic fallback flagged
`id_source`), with Routes linked to their primary target Place via
`destination_id` and any further target Places via `place_ids`, and inline
cross-refs captured as `references`. The `routes.jsonl` / `routes.json`
filenames are kept for contract stability even though each record is now an
Entry, not only a route.

Both are independent `uv` packages. They read and write per-guide data under
`guides/<id>/data/<pipeline>/` at the **repo root** (one level above
`data-pipeline/`) — `config.py` derives that root from its own file location.

## Architecture rules

Load-bearing. Breaking one needs a deliberate, called-out reason.

1. **Deterministic Python, LLM in subagents.** Deterministic logic (parsing,
   planning, matching, merging) lives in the `pipeline` package and runs as
   plain `uv run python -m pipeline.<step>` commands. Fuzzy / natural-language
   work is delegated to Claude Code subagents driven by a slash command (see
   each package's `.claude/commands` + `.claude/agents`). **Never bury an LLM
   call inside the Python** — the deterministic core stays offline and testable.

2. **Everything is resumable.** A stage must be safe to re-run. Planners return
   only the work that is still outstanding; outputs are keyed per unit (e.g.
   one part/verdict file per route/case) so a re-run skips what's done. An
   interrupted run resumes without redoing completed work.

3. **Numbered data-stage layout.** Pipeline artifacts live under
   `guides/<id>/data/<pipeline>/NN_stage/` (`01_gazetteer`, `02_mentions`, …).
   Each stage reads the previous stage's artifact; nothing writes outside its
   guide's data root.

4. **Config injection, no module globals.** Everything guide-specific lives in
   the external `guides/<id>/config.yml`, loaded once via `load_guide(id)` into
   an immutable `GuideConfig` dataclass that every step takes as an argument —
   there is no module-level mutable config. The fixed on-disk stage layout is
   *not* in the YAML; it's derived in code from `cfg.data_root`. Distinguish
   **guide facts** (bbox, tag map, PDF name → YAML) from **algorithm behaviour**
   (fuzzy cutoff, elevation tolerance → named constants in code). Every CLI
   entry point takes a required `--guide <id>`; there is no default.

## Coding conventions

- **Python 3.13, managed with `uv`.** Run things with `uv run` from inside the
  package. Add deps via `uv add` (runtime) / `uv add --dev` (tooling); commit
  the updated `uv.lock`.
- **Formatting & linting: ruff. Types: mypy.** Both use the shared config at the
  repo root (`ruff.toml`, `mypy.ini`) at defaults — ruff finds `ruff.toml` by
  walking up; mypy needs the path passed. Run all four green before pushing,
  from the package directory (`data-pipeline/<pkg>/`):
  ```
  uv run ruff format . && uv run ruff check . \
    && uv run mypy --config-file ../../mypy.ini pipeline \
    && uv run pytest
  ```
- **Type hints throughout**, with `from __future__ import annotations` at the
  top of every module.
- **Module docstrings are required.** Every pipeline module opens with a
  docstring explaining its stage: what it reads, what it writes, and the key
  rules of its algorithm. This is our strongest existing practice — keep it up.
- Referencing the driving issue in a comment for a non-obvious decision (e.g.
  `# guarded hut widening (#14)`) is encouraged where it aids a future reader.

## Testing

New or changed **deterministic Python must ship with pytest tests** (see each
package's `tests/`). LLM-subagent prompt work is exempt — we don't fake LLM
outputs in unit tests. Tests import `pipeline` directly (`pythonpath = ["."]`)
and point stages at fixture data via the injected `GuideConfig`.

## Adding to the pipeline

- **A new guide:** drop `guides/<id>/config.yml` (copy an existing one, adjust
  `id`, `bbox`, and per-pipeline settings) and run the pipelines with
  `--guide <id>`. No code change — that's the point of config injection.
- **A new pipeline package:** add it under `data-pipeline/`, mirroring the
  existing layout — its own `pyproject.toml` (`[tool.uv] package = false`,
  `pytest` + `ruff`/`mypy` dev deps), a `pipeline/` package (with `config.py`
  exposing a `GuideConfig`/`load_guide`), a `tests/` suite, `.claude/{commands,
  agents}` for the orchestrated LLM work, and a `README.md`. Add it to the CI
  matrix in `.github/workflows/ci.yml`.
