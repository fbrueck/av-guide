# route-map gains a deployed, read-only static snapshot on GitHub Pages

## Status

accepted — reverses `route-map/CLAUDE.md` rule 1 ("Local-only … no
deployment/hosting"). Rules 1 and 6 are amended to describe the local-live vs
deployed-snapshot duality this decision introduces.

## Context

route-map was built as a **local-only** QA tool (#17): to see a Guide's mapped
Route/POI data, someone must clone the repo, run the data pipeline to produce
the artifacts, install the frontend toolchain, and start the Vite dev server.
`route-map/CLAUDE.md` rule 1 encoded this as a hard architecture rule — no
backend, **no deployment/hosting** — and rule 6 wired the dev server to serve
the live, gitignored `guides/<id>/data/` tree directly, so the app always
reflects the latest pipeline run with no copy step.

That local-only posture makes it impossible to simply *show* the result to
someone (#46). The maintainer wants to share the Wetterstein map as a link that
anyone can open in a browser, with no login and no local setup. Honouring that
means route-map must gain a hosted mode — a deliberate reversal of the
load-bearing rule 1, which this ADR records so a future reader is not surprised
to find the "no deployment" tool deploying.

## Decision

Promote route-map from "local QA tool" to **"local QA tool *and* published
read-only view."** Publish it as a static site on **GitHub Pages** (project
site, served under `/av-guide/`), fed by a **committed data snapshot** baked
into the build rather than the dev server's live-data middleware.

- **Two data sources answer `/guide-data/` by design.** In `dev`, the existing
  `configureServer` middleware keeps serving the **live**, gitignored
  `guides/<id>/data/` tree (rule 6 unchanged — the local QA workflow is
  byte-for-byte intact). In `build`/production, a **committed snapshot** of the
  four consumed artifacts under Vite's static `public/` directory is copied into
  `dist/` verbatim (no build plugin, no copy step) and served statically. The
  snapshot mirrors the stable `/guide-data/` URL scheme:
  `parse-routes/03_structured/routes.json`,
  `fetch-pois/04_final/pois.geojson`,
  `fetch-pois/04_final/place_pois.jsonl`,
  `fetch-pois/04_final/entry_pois.jsonl`.
- **The snapshot is a separate, deliberately-updated copy** — not the live
  gitignored pipeline tree. `.gitignore` is amended to un-ignore exactly those
  four snapshot files while `guides/*/data/` stays ignored. Publishing is
  therefore an explicit gesture: the maintainer updates the snapshot and merges
  to `main`; noisy local pipeline reruns never dirty what is published.
- **Conditional base path.** Vite `base` is `'/'` in `dev` and `'/av-guide/'`
  in `build`. Conditional (not unconditional) so the dev middleware, which
  matches the `/guide-data/` prefix, is not broken by a base prefix. The
  `src/data` adapter prepends `import.meta.env.BASE_URL` to its data URLs, so
  they resolve to `/av-guide/guide-data/…` in the build and stay `/guide-data/…`
  in dev; the URL scheme and the adapter's raw→domain contract are otherwise
  unchanged.
- **Deploy is automated and build-only.** A standalone GitHub Actions workflow
  (kept apart from the PR-checks `ci.yml`) triggers on **push to `main`** and
  **`workflow_dispatch`**, runs `npm ci` → `npm run build`, and deploys `dist/`
  via `actions/upload-pages-artifact` + `actions/deploy-pages`. It does not
  re-run the green-bar (`check`/`typecheck`/`test`), trusting PR-time `ci.yml`;
  a non-building app still fails the deploy, so a broken app can never be
  published. **Zero secrets** — the basemap (OpenTopoMap raster) and terrain
  (Mapterhorn DEM) tiles are public and keyless.
- **The deployed page renders the real product**, not a degraded demo: typed
  POI markers, a Route's **Destination** styled distinctly from its **Mentions**
  (ADR-0002 — "Anchor" is retired), Route selection highlighting its linked POI
  set, detail panel, search, 3D terrain toggle. Incomplete data stays honest
  (rule 3): a Route with an empty or Destination-only POI set is still
  selectable and its unlinked state noted; unfiled routes remain visible.

## Considered options

- **Regenerate the pipeline in CI** (run `parse-routes` + `fetch-pois` on each
  deploy to produce fresh artifacts) — rejected: it would put the Python
  toolchain and external OpenStreetMap calls on the deploy critical path, making
  a public deploy slow, non-reproducible, and dependent on third-party service
  availability. A committed snapshot makes the deploy reproducible and pure.
- **Track the live artifacts in place under `guides/`** (un-ignore the live
  `guides/<id>/data/` tree and serve it directly in the build) — rejected: it
  couples "what is published" to every local pipeline run, so a noisy or
  half-finished rerun would silently change the public site. A separate,
  deliberately-updated snapshot under `public/` keeps publishing an explicit
  act.
- **Stay local-only / do not deploy** (the status quo rule 1) — rejected: it
  fails the core goal of #46, sharing the map as a link, and there is no lighter
  way to let someone see the real rendered product without cloning and running
  the whole pipeline.

## Consequences

- Rule 1 is no longer an absolute "no deployment/hosting"; it now describes a
  local-live mode **and** a hosted read-only snapshot mode. Rule 6 documents the
  dev-live vs deployed-snapshot data-source duality. Both are updated in this
  change so the reversal is discoverable at the point of the rule it changes.
- The only behavioural code change is the conditional `base` and prefixing the
  adapter's data URLs with `BASE_URL`; the raw→domain contract, the join, and
  every component are untouched. It is verified end-to-end via
  `npm run build && npm run preview` in the browser (per `route-map/CLAUDE.md`
  Testing), not a new Vitest seam — that would fight the rule keeping Vitest
  confined to the pure `src/data` join logic.
- **Maintainer-owned one-time prerequisite:** GitHub Pages must be enabled with
  **Settings → Pages → Build and deployment → Source: "GitHub Actions."** The
  workflow cannot publish until this is set.
- Producing the Guide data (running the pipeline) and multi-guide publishing
  remain out of scope; only the single `wetterstein` Guide is published, and an
  uncommitted snapshot would deploy an honestly-empty page until the snapshot
  lands.
