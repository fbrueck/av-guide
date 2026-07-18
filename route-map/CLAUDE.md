# route-map — conventions

The web app that renders a guide's mapped route data on an interactive
topographic map, so the digitizer can *see* and QA the pipeline's output (#17).
It runs in two modes over one static frontend: a **local-live** QA tool (Vite
dev server, live pipeline artifacts) and a **deployed read-only snapshot**
published to GitHub Pages (ADR-0003) — see rules 1 and 6. The one frontend is
**responsive**: the desktop two-column shell above `768px`, a map-primary
**bottom-sheet** layout below it for smartphones (rule 8). Only the deployed
snapshot is held to the mobile-quality bar; local-live QA stays desktop. Repo-wide
rules (contribution workflow, module layout, domain language) live in the root
`CLAUDE.md`; this file owns everything specific to the webapp.

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

1. **No backend; two delivery modes.** No server code and no API layer, ever.
   The app runs in two modes over the *same* static frontend (ADR-0003):
   **local-live** — the Vite dev server serves everything and reads the live
   pipeline artifacts from the local filesystem (rule 6); and
   **deployed-snapshot** — a static, read-only build published to GitHub Pages
   (project site under `/av-guide/`), fed by a committed data snapshot baked
   into the build (rule 6). Deployment is limited to that static snapshot — it
   adds no runtime server, and publishing is a deliberate act (update the
   snapshot, merge to `main`), never a side effect of a local pipeline run.

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

5. **Minimal state.** The app's state is: the `selectedGuideId` (which published
   Guide is loaded), the selection (a small stack of Entries for drill-in/back
   through the place→route→reference graph), search text, terrain on/off, and —
   on mobile — whether the bottom sheet is expanded (a selection made from the
   map auto-expands it, so it must be real state, not pure CSS). The selection
   stays `Entry[]`: a POI is **never** selected (rule 9), so the stack is not
   widened; a Guide is **not** pushed onto it either (ADR-0004/0005) — the Guide
   is the *context* the stack lives in. **On a Guide switch** (`selectedGuideId`
   changes via the switcher, #133/ADR-0005): the app lazily re-loads that Guide's
   data — one Guide's join in memory at a time, reusing the first-load pending
   state for a brief honest loading state — and reframes the map onto the new
   Guide's POI extent; the **selection** and **search text** are **cleared**
   (both reference the old Guide's Entries), while **terrain** and the **mobile
   sheet mode** **persist** (guide-independent display choices). Plain React
   state (lifted to `App`, or one context) — **no router, no global-state
   library** (Redux/Zustand/etc.). The **selected Guide — and only the Guide — is
   reflected in a `?guide=<id>` query param** (#134/ADR-0005): **read once on
   load** from `location.search` (a valid id opens that Guide; absent/unknown
   falls back honestly to the manifest default), and **written with
   `history.replaceState` on switch** (no new history entry, no router; done with
   the platform `location`/`history` API, not a routing library — see
   `src/guideParam.ts`). Selection, search, terrain, and sheet mode stay
   **ephemeral** — never in the URL. A query param (not a path) is deliberate so
   GitHub Pages serves the single `index.html` and the client reads
   `location.search`, with no `404.html` SPA redirect hack.

6. **Data access: dev-live vs deployed-snapshot.** Two sources answer the same
   id-namespaced `/guide-data/<id>/` URL scheme by design (ADR-0003); the
   `src/data` adapter's contract is identical in both. The Guide id is threaded
   through the whole data path — `loadGuideData(guideId)` builds its four
   artifact URLs from the id via a pure, unit-tested URL-construction helper in
   `src/data/load.ts` (#130). It is a path **segment**, not a query param,
   because it must key the static snapshot on GitHub Pages (which ignores query
   strings).
   - **Dev (live):** `vite.config.ts`'s `configureServer` middleware serves
     **every** Guide's `parse-routes/03_structured` and `fetch-pois/04_final`
     directories (under the gitignored `guides/<id>/data/`) as static data,
     mapping `/guide-data/<id>/…` onto `guides/<id>/data/…`, so the app always
     reflects the latest pipeline run with **no copy step** and no Guide
     selection at mount (the id in the URL selects). `npm run dev` is a genuine
     one-command start.
   - **Build/deploy (snapshot):** a committed copy of the four consumed
     artifacts lives under Vite's static `public/guide-data/<id>/` directory
     (mirroring the id-namespaced `/guide-data/<id>/` scheme) and is copied into
     `dist/` verbatim, so the deployed site renders from a
     **deliberately-updated snapshot**, kept separate from the live gitignored
     tree so local pipeline reruns never dirty what is published. ADR-0003 owns
     the full rationale and the gitignore mechanics.
   - **Base path is conditional:** `base` is `'/'` in dev and `'/av-guide/'` in
     build; the adapter prefixes its data URLs with `import.meta.env.BASE_URL`
     so the same fetches resolve under the project-site base when deployed and
     stay bare in dev.

   **URL scheme (stable — the `src/data` adapter fetches these):**
   `/guide-data/<id>/` maps onto `guides/<id>/data/`, mirroring the on-disk
   layout. Only the two consumed stage dirs are exposed:
   `/guide-data/<id>/parse-routes/03_structured/routes.json`,
   `/guide-data/<id>/fetch-pois/04_final/pois.geojson`,
   `/guide-data/<id>/fetch-pois/04_final/place_pois.jsonl`,
   `/guide-data/<id>/fetch-pois/04_final/entry_pois.jsonl`. Served by a small
   `configureServer` middleware in `vite.config.ts` (path-traversal guarded on
   both the id segment and the stage-relative path; stage-dir allowlist
   retained).

   **The Guide manifest** — `/guide-data/guides.json`, an id-less sibling of the
   per-Guide trees (ADR-0005, #132) — is the committed, hand-maintained list of
   published Guides as `[{ id, name, label, bbox }]` (`name` = short massif name
   titling the overview; `bbox` = `[south, west, north, east]` regional rectangle
   hand-copied from the guide's `config.yml`, used ONLY to draw the overview
   rectangle, never for load framing; app/maintainer metadata, NOT pipeline
   output). It is answered the same two ways: the dev middleware
   serves it from `guides/guides.json` (the root of the shared guides tree,
   beside each `guides/<id>/config.yml`); the build copies it into the snapshot at
   `public/guide-data/guides.json`. The `src/data` adapter loads + guards it
   (`manifest.ts`, warn-and-skip malformed entries) into `Guide[]`. There is no
   `VITE_GUIDE_ID`: `App` picks the **first manifest entry** as the default Guide
   (a `?guide=` switcher lands later), so dev and deploy open on the same Guide
   and `npm run dev` stays one-command.

7. **Domain vocabulary in code and UI.** Use the root `CONTEXT.md` terms —
   Entry, Place, Route, POI, Destination, Mention, Reference, Gazetteer — in
   identifiers, comments, and user-facing copy. ("Anchor" is retired — ADR-0002.)

8. **Responsive: one frontend, two layouts, one breakpoint.** A single
   `max-width: 768px` media query is the only line. **Above it:** the desktop
   two-column shell (map + docked 340px panel), unchanged. **Below it:**
   **map-primary + bottom sheet** — the map fills the screen and the panel
   becomes a sheet that **taps between peek ↔ full** (CSS transition; **no drag
   physics, no sheet library** — the dependency bar in "Adding to route-map"
   holds). Support down to **360px** wide, portrait-primary; landscape must not
   break, but gets no dedicated design, and there is no separate tablet layout.
   On mobile the on-map controls are de-conflicted with the sheet: the legend
   collapses to a button, attribution uses MapLibre's **compact** `ⓘ` (license
   compliance is non-negotiable — OSM + OpenTopoMap CC-BY-SA + Mapterhorn), the
   zoom buttons are hidden (pinch covers them), and scale + attribution sit above
   the sheet's peek. Terrain (rule 4) stays available and default-off on mobile.

9. **POIs are display-only (ADR-0004).** A POI is rendered but is **never a
   selection target** — there is no POI popup and no POI detail view. Tapping a
   Place-coordinate marker selects that Place (an Entry); a mention-only marker
   is inert. This is why the selection stack stays `Entry[]` (rule 5) and
   navigation is one-directional (Entry → its POIs, no POI → Entries reverse
   lookup). Do not re-add a POI popup or a selectable POI without revisiting
   ADR-0004.

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

For **mobile** work (rule 8), verify in **DevTools device mode at 360px and
768px**: the layout flips at the breakpoint, the bottom sheet taps peek ↔ full,
the on-map controls don't overlap and don't hide the attribution, and tap
targets are ≥44px. DevTools device mode is the agent's proof-of-done here; real
finger-gesture feel (pinch/pitch, sheet tap under a thumb) is a manual real-phone
check the digitizer does against the deployed snapshot — not an agent gate.

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
