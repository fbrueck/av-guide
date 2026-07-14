# route-map — conventions

The local-only web app that renders a guide's mapped route data on an
interactive topographic map, so the digitizer can *see* and QA the pipeline's
output (#17). Repo-wide rules (contribution workflow, module layout, domain
language) live in the root `CLAUDE.md`; this file owns everything specific to
the webapp.

It is a **read-only consumer** of committed pipeline artifacts under
`guides/<id>/data/`. It never reaches into another module's source and never
writes guide data — it loads, joins, and renders.

```
route-map/
  src/
    data/        # the ONLY place that knows raw artifact shapes (adapter)
    domain/      # domain types the rest of the app speaks (Entry, Place, Route, Poi, …)
    map/         # all maplibre-gl wiring, imperative, behind one module
    components/  # React UI (sidebar, detail panel, popup, …)
    App.tsx
    main.tsx
  index.html
  vite.config.ts
  biome.json
  tsconfig.json
  package.json
```

## Toolchain (pinned)

- **Vite + React + TypeScript**, `maplibre-gl` for the map. No backend, no
  server-side code — Vite dev server only.
- **npm** (no pnpm/bun); commit `package-lock.json`. Node **24** (current LTS),
  pinned via `.nvmrc` and `package.json` `engines.node`.
- **TypeScript `strict: true`.** No `any` at module boundaries; the `src/data`
  adapter is where external, untyped JSON is turned into typed domain objects.
- **Biome** is the single format + lint tool (one `biome.json` at defaults) —
  the frontend counterpart to the pipeline's `ruff`. No ESLint, no Prettier.
- **Vitest** for tests, **node environment only** (see Testing).

## The green-bar

Run all four green before pushing, from `route-map/`:

```
npm run check      # biome check .   (format + lint)
npm run typecheck  # tsc --noEmit
npm run test       # vitest run
npm run build      # vite build
```

These are the agent's proof-of-done. A PR is green or it isn't finished; there
is no non-blocking transition period (this is greenfield — no debt baseline to
grandfather, unlike the pipeline's transitional `ruff`/`mypy`).

## Architecture rules

Load-bearing. Breaking one needs a deliberate, called-out reason.

1. **Local-only, no backend.** No server code, no API layer, no
   deployment/hosting. The Vite dev server serves everything; data is read from
   the local filesystem via the config in rule 6.

2. **A single data boundary.** `src/data/` is the *only* place that knows the
   raw on-disk artifact shapes and file formats (`contracts.ts`). It loads
   (`load.ts`), guards, and joins (`join.ts`) the artifacts into clean domain
   objects at startup, exposing one `loadGuideData(): Promise<GuideData>`
   (`index.ts`). **Every component depends on `src/domain/` types, never on file
   layout.** This is an anti-corruption layer: it mirrors "each pipeline owns
   its contract," and it means a change to any artifact's format is a one-file
   edit, not a hunt across the UI.

3. **A Route has no geometry** (see root `CONTEXT.md`). Rendering an Entry means
   **highlighting its linked POI set** — never drawing an invented path, no
   polylines. The target coordinates — a Route's **Destination** + `places`'
   POIs (transitive: `destination_id`/`place_ids` → Place → `poi`, never a direct
   route→POI link), or a Place's own **POI** — are styled distinctly from the
   **Mentions**. An Entry whose POI set is empty (a Place with no resolved POI, a
   Route with no target Place) is still selectable and rendered **honestly** —
   the detail panel notes what is unlinked, and Routes with no target at all live
   in a visible "Unfiled routes" bucket. Incomplete extraction must be *visible*,
   never papered over with fake geometry.

4. **Raw `maplibre-gl`, imperative, behind one map module.** No `react-map-gl`
   or other wrapper. `src/map/` owns the `Map` instance (created once in a
   ref/effect) and exposes a small typed imperative API (e.g. `highlightPois`,
   `fitTo`, `setTerrain`). React state drives the map through effects; markers,
   sources, and layers are managed imperatively inside `src/map/`. UI components
   never call `maplibre-gl` directly.

5. **Minimal state.** The app's state is: the selection (a small stack of
   Entries for drill-in/back through the place→route→reference graph), search
   text, terrain on/off. Plain React state (lifted to `App`, or one context) —
   **no router, no global-state library** (Redux/Zustand/etc.).

6. **Dev-time data access via Vite static-serve.** `vite.config.ts` serves the
   guide's `parse-routes/03_structured` and `fetch-pois/04_final` directories
   (under `guides/<id>/data/`) as static data, so the app always reflects the
   latest pipeline run with **no copy step**. The guide is selected by the
   `VITE_GUIDE_ID` env var, defaulting to the single existing guide
   (`wetterstein`), so `npm run dev` is a genuine one-command start. (This
   deliberately softens the pipeline's strict "no default `--guide`" rule — a
   personal QA tool should start with one command.)

   **URL scheme (stable — the `src/data` adapter fetches these):** `/guide-data/`
   maps onto `guides/<id>/data/`, mirroring the on-disk layout minus the guide
   prefix. Only the two consumed stage dirs are exposed:
   `/guide-data/parse-routes/03_structured/routes.json`,
   `/guide-data/fetch-pois/04_final/pois.geojson`,
   `/guide-data/fetch-pois/04_final/place_pois.jsonl`,
   `/guide-data/fetch-pois/04_final/entry_pois.jsonl`. Served by a small
   `configureServer` middleware in `vite.config.ts` (path-traversal guarded).

7. **Domain vocabulary in code and UI.** Use the root `CONTEXT.md` terms —
   Entry, Place, Route, POI, Destination, Mention, Reference, Gazetteer — in
   identifiers, comments, and user-facing copy. ("Anchor" is retired — ADR-0002.)

## Data contract

The webapp knows two per-pipeline layouts and joins them in the browser at
startup (the Entry model, #44; no precomputed bundle, no coordinates duplicated
into Entry records).

| Artifact | Owner / location | Shape |
|---|---|---|
| `routes.json` | `parse-routes` final stage (`03_structured/`) | array of **Entry** records: `id`, `kind` (`place`\|`route`), `name`, `place_type`, `elevation` (Places); `peak`, `grade`, `time`, `height_m`, `first_ascent`, `destination_id` (nullable), `place_ids` (Routes); `references` (`{ref_id, surface}`); `summary`, `description` |
| `pois.geojson` | `fetch-pois` `04_final/` | GeoJSON FeatureCollection of POIs (point geometry, `poi_id`/name/type/`ele`/`osm`/`aliases`/`n_entries`) |
| `place_pois.jsonl` | `fetch-pois` `04_final/` | link records `{place_id, poi_id}` — a Place's single resolved POI (its coordinate) |
| `entry_pois.jsonl` | `fetch-pois` `04_final/` | link records `{entry_id, poi_id, surface}` — Entry-general **Mentions** |

- **Entry metadata comes from `routes.json`, not browser-parsed JSONL.** The
  export step lives in and is tested by `parse-routes` (see
  `data-pipeline/CLAUDE.md`); the browser never parses `routes.jsonl`. The file
  keeps its name for contract stability though each record is now an Entry, not
  only a route. (If you find a ticket that says otherwise, it is stale — the
  parent #17 and its export/test decision win.)
- **A Route's coordinate is transitive.** There is no route→POI link: the join
  resolves `destination_id`/`place_ids` → target Place → the Place's `poi`. A
  Place that resolved to no POI is an honest absence, rendered as such.
- **Validation: trust the types, guard the seams.** No schema library
  (zod/valibot). TypeScript types in `contracts.ts` describe the raw shapes; the
  adapter does cheap explicit guards where it matters (is it an array; does a
  record have `route_id`/`poi_id`; is a link's `poi_id` resolvable) and handles
  misses honestly — skip the record and `console.warn`, so pipeline drift is
  *visible* rather than a silent wrong render or an opaque crash deep in a
  component.

## Testing

There are **no component/DOM tests, no jsdom, no React Testing Library.** Do
not add them: jsdom has no WebGL, so it cannot render the map that is this
app's core — it would only test glue over the already-tested join, at the cost
of a mocked-away map. If UI regressions ever justify automation, reach for
**Playwright** (real browser, real WebGL, can drive and screenshot the map),
never RTL.

**UI and map behavior are verified in the browser with Chrome DevTools.**
Against the acceptance criteria of the ticket being built, run `npm run dev`,
open the app in Chrome, and confirm with DevTools:

- the **Console** is clean — no errors and no adapter `console.warn` drift
  beyond what the current pipeline data honestly implies;
- the **Network** tab shows the artifacts and tiles loading (correct
  attribution present);
- the rendered map and DOM match the criteria — markers, highlighted POI set
  (target Places distinct from Mentions), detail panel, terrain toggle —
  inspected via the Elements panel and screenshots.

State plainly in the PR what was checked this way and the result; "verified by
eye" is not a pass unless it was actually done in DevTools.

The one automated-test exception is the `src/data` adapter: its load/join logic
is **pure, deterministic, and non-UI**, so it gets Vitest unit tests (node
environment) covering the raw→domain join — Place→POI resolution, a Route's
transitive coordinate (via its Destination + places), routes-leading-here,
Entry-general Mentions, References (resolved and dangling), unfiled routes, and
unresolvable links. This gives the deterministic join the same coverage the
pipeline mandates for deterministic logic. **Keep
Vitest confined to pure functions** — the moment a test needs a DOM, it does
not belong here.

Colocate tests with the code (`src/data/join.test.ts`). Everything else is
covered by strict types + the green-bar + the DevTools pass above.

## Adding to route-map

- **A new component/view:** add it under `src/components/`, speaking `domain`
  types only. If it needs the map, extend `src/map/`'s imperative API rather
  than touching `maplibre-gl` from the component.
- **A new artifact field or format change:** update `src/data/contracts.ts` and
  the join — nowhere else should need to change. If the change is to a
  pipeline's output, the owning pipeline changes its contract first.
- **A new domain concept:** add the term to the root `CONTEXT.md` before using
  it (that is a `/domain-modeling` action), then a type in `src/domain/`.
- **A new dependency:** justify it against the pinned toolchain. The bar is
  high — this is a small personal tool; prefer the platform and what `maplibre`
  already gives you.
