# route-map

Local-only webapp that renders a guide's mapped **Route** / **POI** data on an
interactive topographic map, so a digitizer can *see* and QA the pipeline's
output. Conventions live in [`CLAUDE.md`](./CLAUDE.md); domain vocabulary in the
repo-root [`CONTEXT.md`](../CONTEXT.md).

## Requirements

- Node **24+** (`.nvmrc` pins 24; run `nvm use`)
- npm

## Getting started

```sh
npm install
npm run dev
```

`npm run dev` is a genuine one-command start: it opens the app on the
OpenTopoMap topographic basemap framed on the Wetterstein. The map credits
**© OpenStreetMap contributors** and OpenTopoMap (CC-BY-SA).

## Guide selection & live data

The app is a read-only consumer of the pipelines' working-tree output under the
repo-root `guides/<id>/data/` tree — there is **no copy step**, so it always
reflects the latest pipeline run. The guide is chosen by the `VITE_GUIDE_ID`
env var, defaulting to `wetterstein`:

```sh
VITE_GUIDE_ID=wetterstein npm run dev
```

The dev server mounts the two consumed stage dirs at stable URLs (see
`vite.config.ts`). `/guide-data/` maps onto `guides/<id>/data/`:

| URL | On-disk (repo root) |
|---|---|
| `/guide-data/parse-routes/03_structured/routes.json` | `guides/<id>/data/parse-routes/03_structured/routes.json` |
| `/guide-data/fetch-pois/04_final/pois.geojson` | `guides/<id>/data/fetch-pois/04_final/pois.geojson` |
| `/guide-data/fetch-pois/04_final/route_pois.jsonl` | `guides/<id>/data/fetch-pois/04_final/route_pois.jsonl` |

Only those two stage dirs are exposed. Nothing is fetched yet — the scaffold
wires the access so the `src/data` adapter (a later ticket) just fetches.

## The green-bar

Run all four green before pushing:

```sh
npm run check      # biome check .   (format + lint)
npm run typecheck  # tsc --noEmit
npm run test       # vitest run
npm run build      # vite build
```

## Testing

The webapp has **no automated UI/DOM tests** by design (see `CLAUDE.md` →
Testing). UI and map behavior are verified by eye in Chrome DevTools. Vitest is
wired for the future pure `src/data` adapter tests (node environment) only.
