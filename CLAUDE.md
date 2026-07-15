# av-guide — contribution & coding guidelines

Turn scanned *Alpenvereinsführer* guidebooks into structured, mapped route
data. This root file is the source of truth for **repo-wide** conventions;
agents and humans both follow it. Each module carries its own nested
`CLAUDE.md` for conventions local to it — read that too before working inside a
module. When a convention changes, update the file that owns it.

## Layout

A monorepo of independent modules plus shared, per-guide data:

```
data-pipeline/         # Python data pipelines (see data-pipeline/CLAUDE.md)
  parse-routes/        #   stage A: PDF (OCR text layer) -> structured routes.jsonl
  fetch-pois/          #   stage B: route place-names -> OpenStreetMap POIs + GeoJSON
route-map/             # TypeScript map webapp (Vite+React) — renders the pipeline's route/POI data (see route-map/CLAUDE.md)
guides/<id>/config.yml # one committed config per guide (facts + per-pipeline settings)
guides/<id>/data/<pipeline>/NN_stage/   # that guide's pipeline artifacts (gitignored)
CONTEXT.md             # ubiquitous language (Route, POI, Destination, Mention, …)
ruff.toml / mypy.ini   # shared Python tool config (root; used by data-pipeline)
.github/workflows/     # CI
```

`guides/` lives at the repo root because it is shared: the pipeline writes it,
and the map reads the pipeline's exported artifacts from it. Modules are
top-level sibling directories, each with its own nested `CLAUDE.md`.

## Domain language

Read `CONTEXT.md` before touching any module — it defines the shared vocabulary
(Route, POI, Destination, Mention, Gazetteer). Use those terms in code, comments,
and commits. Keep it current when the model changes.

## Contribution workflow

Applies to every module.

1. One **GitHub Issue** per ticket (the spec lives in the tracker).
2. Branch off `main` named `ticket-<n>-<slug>` (e.g. `ticket-14-hut-class-gap`).
3. **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, …).
4. Open a **PR that references its issue** (`Closes #<n>`), with a
   **Conventional-Commit title** — the squash merge (step 5) makes the PR title
   the commit message on `main`.
5. **Squash merge** into `main` for a linear history.
6. CI must be green to merge.
   (Transitional: the pipeline's `ruff check` and `mypy` are non-blocking until
   the baseline in #26 is cleared — don't add new violations; new code still
   runs them green.)

## Adding a module

Create a top-level sibling directory with its own toolchain, tests, `README.md`,
and a nested `CLAUDE.md` capturing its local conventions. Wire its checks into
`.github/workflows/ci.yml`. Anything that consumes pipeline output reads the
committed artifacts under `guides/<id>/…`; don't reach into another module's
source.

- **Adding a data pipeline stage/package** — see `data-pipeline/CLAUDE.md`.
