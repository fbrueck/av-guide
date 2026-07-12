# av-guide — contribution & coding guidelines

Turn scanned *Alpenvereinsführer* guidebooks into structured, mapped route
data. This file is the source of truth for how we build here; agents and humans
both follow it. Keep it current when a convention changes. Nested `CLAUDE.md`
files may be added later for genuinely local rules — this root file wins for
everything shared.

## Layout

A `uv`-managed monorepo of independent pipeline packages plus per-guide data:

```
parse-routes/          # stage A: PDF (OCR text layer) -> structured routes.jsonl
fetch-pois/            # stage B: route place-names -> OpenStreetMap POIs + GeoJSON
guides/<id>/config.yml # one committed config per guide (facts + per-pipeline settings)
guides/<id>/data/<pipeline>/NN_stage/   # that guide's pipeline artifacts
CONTEXT.md             # ubiquitous language (Route, POI, Anchor, Mention, …)
ruff.toml / mypy.ini   # shared tool config (root)
```

Read `CONTEXT.md` for domain terms before touching pipeline code.

## Architecture rules

These are the load-bearing conventions. Breaking one needs a deliberate,
called-out reason.

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
- **Formatting & linting: ruff. Types: mypy.** Both use the shared root config
  (`ruff.toml`, `mypy.ini`) at defaults. Run all three green before pushing —
  from the package directory:
  ```
  uv run ruff format . && uv run ruff check . \
    && uv run mypy --config-file ../mypy.ini pipeline \
    && uv run pytest
  ```
- **Type hints throughout**, with `from __future__ import annotations` at the
  top of every module (matches existing code).
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

## Contribution workflow

1. One **GitHub Issue** per ticket (the spec lives in the tracker).
2. Branch off `main` named `ticket-<n>-<slug>` (e.g. `ticket-14-hut-class-gap`).
3. **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `docs:`, …).
4. Open a **PR that references its issue** (`Closes #<n>`).
5. **Squash merge** into `main` for a linear history.
6. CI (ruff + mypy + pytest on both packages) must be green to merge.
   (Transitional: `ruff check` and `mypy` are non-blocking until the baseline
   in #26 is cleared — don't add new violations; new code still runs them green.)

## Adding to the repo

- **A new guide:** drop `guides/<id>/config.yml` (copy an existing one, adjust
  `id`, `bbox`, and per-pipeline settings) and run the pipelines with
  `--guide <id>`. No code change — that's the point of config injection.
- **A new pipeline package:** mirror the existing layout — top-level dir with
  its own `pyproject.toml` (`[tool.uv] package = false`, `pytest` +
  `ruff`/`mypy` dev deps), a `pipeline/` package (with `config.py` exposing a
  `GuideConfig`/`load_guide`), a `tests/` suite, `.claude/{commands,agents}`
  for the orchestrated LLM work, and a `README.md`. Add it to the CI matrix in
  `.github/workflows/ci.yml`.
