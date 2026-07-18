# route-map serves multiple guides from one deployment

## Status

accepted — supersedes the "multi-guide publishing remains out of scope" line in
ADR-0003 (only `wetterstein` was published). Amends `route-map/CLAUDE.md`
rule 6 (the `/guide-data/` URL scheme gains a guide-id segment; `VITE_GUIDE_ID`
retired) and rule 5 (a single `?guide=` URL param is admitted). Adds **Guide**
to the root `CONTEXT.md` glossary.

Implementation follows in a separate PR; the rule-5/rule-6 amendments land
**with that code** (the rules describe live wiring, so they change when the
wiring does). This ADR records the decision cluster now.

## Context

route-map was built to render exactly **one** guide. The guide is chosen out of
band: in dev by `VITE_GUIDE_ID` (default `wetterstein`), which decides the
single `guides/<id>/data/` tree the `configureServer` middleware mounts at the
guide-blind `/guide-data/…` URLs; in the deployed build by whichever single
committed snapshot sits under `public/guide-data/…` (ADR-0003). The opening map
framing is a hardcoded `WETTERSTEIN_BOUNDS` constant, and "Guide" is an informal
word, not a domain term or a type.

A second guide — **Karwendel** — now has full pipeline data on disk
(`guides/karwendel/data/`), alongside `wetterstein`. The maintainer wants the
one deployed site to serve **both**, switchable in-app, so QA-ing and sharing
either massif is a single URL. "Serve Karwendel as well" is therefore not a
config swap but a small architectural change: the guide identity has to move
*into* the app's state, the data scheme, and the UI — which is what this ADR
records so a future reader is not surprised to find an id in the "stable" URL
scheme and a lone state atom in the URL that rule 5 otherwise forbids.

## Decision

Serve **all published guides from one deployment**, with an in-app switcher.
One build, both snapshots; the reader picks.

- **The `/guide-data/` URL scheme gains a guide-id path segment.** It becomes
  `/guide-data/<id>/…` → `guides/<id>/data/…`, i.e. the scheme stops dropping
  the guide prefix it always mirrored (rule 6). The `src/data` adapter builds
  its four artifact URLs from a `guideId`; the dev middleware maps
  `/guide-data/<id>/…` onto `guides/<id>/data/…` and no longer *selects* a guide
  by mounting (it serves every guide's tree); the deployed snapshot is laid out
  per guide under `public/guide-data/<id>/…`. A **path** segment — not a query
  param — because it must key the *static* snapshot on GitHub Pages, which
  ignores query strings.

- **A committed manifest `guides/guides.json`** lists the served guides as
  `[{ id, label }]` — nothing more. It lives at the root of the shared `guides/`
  tree (a sibling of each `guides/<id>/config.yml`, above the gitignored
  `guides/*/data/`), so it is a committed, reviewed statement of *which guides
  are published* and their human labels (copy, not derivable from an id). It is
  answered the same two ways as every artifact: the dev middleware serves it
  from `guides/guides.json`, and the build copies it into the snapshot. The
  manifest carries **no bbox**.

- **Opening framing is computed from the loaded POIs**, not stored. On load the
  adapter/map derives the guide's opening bounds from its `pois.geojson` extent
  (which is exactly what the retired `WETTERSTEIN_BOUNDS` numbers already were).
  Nobody maintains a per-guide framing number, and with lazy loading the POIs
  are already in hand when the map needs to frame.

- **Lazy, one guide at a time.** `loadGuideData(guideId)` is re-invoked on a
  switch, fetching and joining that guide's four artifacts and replacing the
  single `GuideData` in state; the existing first-load pending state is reused
  for switches. Only one guide's join is in memory. This keeps the load/join
  boundary (rule 2) almost verbatim — `loadGuideData` merely gains a param and
  is called more than once.

- **`selectedGuideId` is a new state atom; a switch clears selection + search,
  keeps terrain + sheet.** The selection stack and search text both reference
  the *old* guide's Entries, so they reset on switch (a stale Entry would point
  at nothing; a carried-over search would query the wrong guide's list). Terrain
  on/off and the mobile sheet mode are display preferences about *how* to
  render, guide-independent, so they persist. The selection stays `Entry[]`
  (rule 5, ADR-0004) — a guide is not selected *into* the stack; it is the
  context the stack lives in.

- **The chosen guide is reflected in a single `?guide=` URL query param** — read
  once on load, written with `history.replaceState` on switch, falling back to
  the default when absent or naming an unknown guide. This is a deliberate,
  narrow softening of rule 5's "no URL state": it is *one* param, no router, no
  history stack, and *only* the guide (selection/search/terrain stay ephemeral).
  It earns its exception because the deploy is a **shareable read-only snapshot**
  (ADR-0003) — "here is the Karwendel guide" is a link worth sending, and
  reloading lands back on the same massif. A query param (not a path) also keeps
  GitHub Pages happy without the SPA `404.html` redirect hack.

- **The default guide is the first manifest entry; `VITE_GUIDE_ID` is retired.**
  With every guide's tree served, the env var no longer selects anything by
  mounting. Rather than repurpose it as a subtly different "default selection,"
  it is dropped: the default (when no `?guide=`) is the manifest's first entry,
  so dev and deploy behave identically — the property rule 6 prizes. `npm run
  dev` still lands on a sensible guide in one command, now decided by manifest
  order.

- **"Guide" becomes a domain term and a type.** The root `CONTEXT.md` gains a
  **Guide** entry (a digitized Alpenvereinsführer volume — the container above
  Entry), and `src/domain/` gains a lightweight `Guide { id, label }` (the
  manifest shape) distinct from `GuideData` (the joined artifacts for *one*
  Guide). The switcher, manifest, and `loadGuideData(guideId)` speak `Guide`.

- **Karwendel ships live in the same change as the plumbing.** The existing
  Wetterstein snapshot is re-namespaced to `public/guide-data/wetterstein/…`,
  Karwendel's four artifacts are added under `public/guide-data/karwendel/…`,
  and `guides/guides.json` lists both — so merging and deploying actually shows
  Karwendel, publishing its current pipeline output.

## Considered options

- **Two separate deployments** (two builds, two URLs) — rejected: it fights the
  single project-site base (`/av-guide/`) and doesn't serve both "as well"
  (together); it serves one *or* the other per URL.
- **Keep it single-guide, just make the guide swappable** (dev via
  `VITE_GUIDE_ID`, deploy by swapping the baked snapshot) — rejected: it serves
  one *or* the other, never both at once, which is not "serve Karwendel as
  well."
- **Guide id as a URL query param for the data too** (`/guide-data/…?guide=id`)
  — rejected: GitHub Pages ignores query strings for static files, so the
  deployed snapshot cannot be laid out per guide this way. (The `?guide=` param
  is used only for the *app*'s selection state, where the static host never
  needs to understand it.)
- **A served, synthesized manifest** (dev middleware lists `guides/*/data/`
  dirs; build writes one) — rejected: the dev and build producers can drift, and
  it makes the published menu *implicit* (whatever dirs exist) rather than a
  deliberate committed choice. A hand-committed `guides.json` keeps "which
  guides are published" reviewed.
- **Store a per-guide framing bbox in the manifest** — rejected in favour of
  computing from the POI extent at load: it removes a hand-maintained number,
  and lazy loading means the POIs are already fetched when framing is needed.
  The `config.yml` `bbox` was also rejected as the framing source — it is the
  deliberately-wider *search* box, would frame looser than today, and lives in
  the pipeline's domain (reaching into it breaks the module boundary).
- **Eager-load every guide up front** into a `Map<id, GuideData>` for instant
  switches — rejected: pays startup cost and memory for guides that may never be
  opened, and grows as guides are adopted; a sub-second reload on a rare massif
  switch is not a hot path worth that.
- **Keep the guide purely in-memory** (no URL param, resets to default on every
  reload) — rejected: it keeps rule 5 pristine but loses the one place a
  shareable snapshot benefits from URL state — a linkable, reload-stable guide.

## Consequences

- **Rule 6 is amended** in the implementation PR: the `/guide-data/` scheme is
  documented as `/guide-data/<id>/…`, `VITE_GUIDE_ID` is removed as the guide
  selector (default becomes manifest order), and `guides/guides.json` is
  described as an app-owned, committed manifest served both ways. **Rule 5 is
  amended** to admit the single `?guide=` param as an explicit exception to "no
  URL state," scoped to the guide alone.
- The `src/data` boundary change is small and stays within rule 2:
  `loadGuideData` takes a `guideId` and is re-invokable; the raw→domain **join
  is unchanged** (it still operates on one guide's fetched artifacts). New
  **pure** logic — the manifest parse/guard and the POI→bounds extent
  computation (including degenerate empty / single-POI cases) — gets focused
  Vitest coverage, per the testing policy; the untouched join is not re-tested
  and `fetch` is not mocked.
- Adopting a further guide later is a deliberate, small act: run its pipeline,
  add one `{ id, label }` line to `guides.json`, and commit its
  `public/guide-data/<id>/…` snapshot — no code change.
- **Out of scope:** the ticket-124 sun/terrain spike (leftover, unmerged) hard­
  codes a Wetterstein sun center and imports `WETTERSTEIN_BOUNDS`. This change
  retires that constant and would make a single hardcoded sun center wrong for
  Karwendel — but productionizing the spike (a per-guide sun center, the import
  rename) is the spike's own concern, not this ticket's.
