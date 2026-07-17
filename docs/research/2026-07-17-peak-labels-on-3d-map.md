# Peak names on the 3D map, floating above the summit

**Date:** 2026-07-17
**Question:** How can we show **peak names on the 3D map**, rendered **above the
peak** (the label floating above the summit)? Deliver concrete, drop-in MapLibre
GL JS approaches with tradeoffs and a recommendation.
**Module:** `route-map` (MapLibre GL JS `maplibre-gl` ^5.24.0, TypeScript + React,
imperative map behind `src/map/`, no backend, static GitHub Pages snapshot; high
dependency bar — prefer what maplibre already gives you: `route-map/CLAUDE.md`
rule 4 and "Adding to route-map").

## TL;DR / recommendation

Use a **native `symbol` layer** built from the peaks we already have (the `pois`
source, filtered to `type === "peak"`), added **after** `customizeBasemap()`
strips symbols and re-added in the existing `reapplyAfterStyle()` flow. Place the
text **above the marker in screen space** with `text-anchor: "bottom"` +
`text-offset: [0, -1.2]`, a white `text-halo` for legibility, and declutter ~100
labels with `text-allow-overlap: false` + `symbol-sort-key` (rank by elevation so
the highest peaks win collisions). Optionally filter to prominent peaks by `ele`.

Why this and not the alternatives:

- **A true "floating billboard N metres above the summit" is not possible in
  5.24.** No MapLibre style property elevates a symbol a fixed height above the
  terrain surface today. The proposal is **open** (style-spec #62), its spec PR
  (#1508) is **open**, and the GL-JS implementation PR (#7827) is a **draft** as
  of June 2026 — nothing shipped in 5.x (or in the current 6.0.0-x pre-releases).
  See [Approach B](#approach-b--true-3d-elevation-symbol-elevation--not-available-in-524).
- **Native symbols already sit ON the terrain surface** when terrain is on (their
  anchor is placed at terrain height), so a screen-space upward `text-offset`
  reads convincingly as "the name hovering just above the summit" without any 3D
  elevation property. This is the pragmatic, dependency-free path and it matches
  the codebase's "prefer what maplibre gives you" bar.
- **HTML `Marker`s** ([Approach C](#approach-c--html-markers-maplibreglmarker))
  are the only option that gives real **terrain occlusion** (a label behind a
  mountain fades via `maplibregl-marker-covered`), but ~100 DOM nodes are heavier,
  they do **not** auto-declutter/collide, and they still float via a *pixel*
  offset — not a true metric height. Reach for them only if occlusion fidelity
  matters more than perf and collision.

**One caveat to call out for either symbol approach:** MapLibre does **not**
depth-occlude symbol/text against terrain — labels for peaks hidden behind a
nearer ridge will still draw on top ("show through"). This is a known, still-open
limitation (issue #1030, open since 2022). Filtering to prominent peaks and the
south-west camera framing mitigate it; it is not fully solvable with symbols today.

## Version facts (what needs which maplibre-gl, and what 5.24 has)

| Capability | Property / API | Introduced | In 5.24? |
|---|---|---|---|
| Point symbol placed at its geometry, on terrain surface | `symbol-placement: "point"` (default) | js `0.10.0` | ✅ yes |
| Text label content | `text-field` | js `0.10.0` | ✅ yes |
| Screen-space vertical offset | `text-offset`, `text-anchor` | js `0.10.0` | ✅ yes |
| Variable/radial offset placement | `text-variable-anchor`, `text-radial-offset` | js `0.54.0` | ✅ yes |
| Collision control | `text-allow-overlap`, `text-optional` | js `0.10.0` | ✅ yes |
| Collision priority | `symbol-sort-key` | js `0.53.0` | ✅ yes |
| Draw order | `symbol-z-order` | js `0.49.0` | ✅ yes |
| Marker occlusion behind terrain | `opacity`/`opacityWhenCovered`, `maplibregl-marker-covered` | (v3 terrain era) | ✅ yes |
| Read terrain height at a point | `Map.queryTerrainElevation()` | v3 (2023) | ✅ yes |
| **True 3D elevation of a symbol (metres above terrain)** | `symbol-elevation` / `symbol-elevation-reference` | **not merged** | ❌ **no** |
| **`symbol-z-elevate`** (Mapbox-style) | — | **never adopted by MapLibre** | ❌ **no** |

SDK-support versions above are quoted from the MapLibre style-spec reference
(`v8.json`, see per-property citations below); the map layout is stable back to
`0.54.0`, so everything except true 3D elevation is comfortably present in 5.24.

## What each investigated point actually resolves to

### 1. Symbol layers on 3D terrain (the native baseline)

A `symbol` layer defaults to `symbol-placement: "point"` — "The label is placed
at the point where the geometry is located"
([style-spec: layers → symbol-placement](https://maplibre.org/maplibre-style-spec/layers/)).
When terrain is enabled, MapLibre places that point **at the terrain surface
height**: the whole premise of the (not-yet-merged) elevation proposal is that
`symbol-elevation` would display icons/text "at the given height, **overriding
the map's terrain height**"
([style-spec PR #1508 description](https://github.com/maplibre/maplibre-style-spec/pull/1508)),
i.e. the current, un-overridden behaviour is that symbols render **at** terrain
height. So today a peak label's anchor already lands on the summit surface with
no extra work — we only need to push the text upward in screen space to get the
"above the peak" look.

### 2. `symbol-z-elevate` — does not exist in MapLibre

There is **no `symbol-z-elevate` property in the MapLibre style spec.** A grep of
the authoritative reference
([`src/reference/v8.json` on `main`](https://github.com/maplibre/maplibre-style-spec/blob/main/src/reference/v8.json),
fetched 2026-07-17) finds no `elevate`, no `symbol-z-elevate`, and no
`symbol-elevation*` keys at all; the symbol layout properties present are
`symbol-placement`, `symbol-spacing`, `symbol-avoid-edges`, `symbol-sort-key`,
and `symbol-z-order`. `symbol-z-elevate` is a **Mapbox GL JS** property (Mapbox's
3D "elevate symbols above the terrain/other symbols" feature) that MapLibre has
**not** adopted — I could not find it in any MapLibre primary source, which is
itself the finding. Do not reach for it; it will silently do nothing (or fail
validation) in maplibre-gl. The nearest MapLibre thing to "order symbols for
occlusion" is `symbol-z-order` / `symbol-sort-key`, which sort within the layer
but do **not** elevate anything in 3D
([style-spec: symbol-z-order](https://maplibre.org/maplibre-style-spec/layers/)).

### 3. Floating a label a fixed height ABOVE the summit (true 3D vertical offset)

**Not possible in 5.24.** There is no `symbol-elevation`,
`symbol-elevation-reference`, or any metres-above-terrain offset property in the
shipped spec (grep of `v8.json`, above). Status of the effort, from primary
sources:

- **Design proposal — OPEN.** [maplibre-style-spec #62 "Add elevation to symbol
  layer"](https://github.com/maplibre/maplibre-style-spec/issues/62): "the general
  idea is that a symbol layer should be allowed to be presented above the ground …
  both when terrain is enabled and when extrusions are displayed." Candidate names
  discussed: `symbol-elevation`, `symbol-height`, `symbol-elevation-offset`,
  `symbol-height-offset`. Still open, no final property.
- **Spec PR — OPEN.** [maplibre-style-spec #1508](https://github.com/maplibre/maplibre-style-spec/pull/1508)
  proposes `symbol-elevation` (an **offset from terrain**, like fill-extrusion,
  restricted to `symbol-placement: point`). Not merged.
- **GL-JS implementation — DRAFT.** [maplibre-gl-js #7827](https://github.com/maplibre/maplibre-gl-js/pull/7827)
  implements the elevation offset (shader projects the symbol with an elevation
  offset — a genuine 3D vertical position), but it is a **draft** depending on
  #1508, as of June 2026.
- **Feature request open, "need more info".** [maplibre-gl-js #4879 "Could I set
  height for symbol?"](https://github.com/maplibre/maplibre-gl-js/issues/4879)
  (Oct 2024): "MapLibre GL JS does not natively support setting symbol heights in
  3D space." Still open.
- **CHANGELOG confirms nothing shipped:** no `symbol-elevation` / `symbol-z-elevate`
  entry anywhere in
  [CHANGELOG.md](https://github.com/maplibre/maplibre-gl-js/blob/main/CHANGELOG.md)
  (top of file is `6.0.0-22`, fetched 2026-07-17). So it is absent from 5.24 and
  from the current 6.0.0-x pre-releases alike.

**Bottom line:** a true billboard hovering a fixed number of metres over the
summit (that reprojects correctly as you pitch/zoom) is a future feature. Today,
"above the peak" must be faked in screen space (Approach A) or with a pixel-offset
DOM marker (Approach C).

### 4. Screen-space "above the peak" via `text-offset` / `text-anchor`

This is the workable native path. Relevant properties (all `layout`, quoted from
the style spec):

- `text-anchor` (default `"center"`) — "Part of the text placed closest to the
  anchor." Set to `"bottom"` so the label grows **upward** from its anchor point.
- `text-offset` (default `[0, 0]`, units ems) — "Offset distance of text from its
  anchor. Positive values indicate right and down, while negative values indicate
  left and up." Use a **negative Y** (e.g. `[0, -1.2]`) to lift the text above the
  summit point.
- `text-variable-anchor` / `text-radial-offset` (js `0.54.0`) — let the engine try
  alternative placements to avoid collisions; optional for peaks.
- `text-allow-overlap` (default `false`) — "Text visibility despite collisions
  with other previously drawn symbols." Keep **false** so ~100 labels declutter.
- `text-optional` (default `false`) — only relevant if the layer also has an icon.
- `symbol-sort-key` (js `0.53.0`) — "Features with lower sort keys are drawn and
  placed first … features with a lower sort key will have priority during
  placement" when overlap is off. Rank peaks so the **highest/most prominent win**
  collisions (sort key = negative elevation).

(All property docs above: [style-spec layers page](https://maplibre.org/maplibre-style-spec/layers/),
backed by [`v8.json`](https://github.com/maplibre/maplibre-style-spec/blob/main/src/reference/v8.json).)

Collision behaviour for ~100 labels: with `text-allow-overlap: false`, MapLibre's
global collision detection drops labels that would overlap, keeping the map
readable; `symbol-sort-key` decides *which* survive. This is exactly what we want
(Wetterstein ~107 peaks, Karwendel ~14) — we do not need to pre-thin, though an
`ele` filter helps (point 7).

### 5. HTML `Marker` approach (`maplibregl.Marker` with custom DOM)

Confirmed against the Marker source and API:

- **Auto-clamps to terrain.** A Marker listens for the `terrain` event and, when
  `map.terrain` is set, projects its lng/lat through the terrain-aware transform,
  so it sits on the terrain surface automatically
  ([`src/ui/marker.ts` `_update`](https://github.com/maplibre/maplibre-gl-js/blob/main/src/ui/marker.ts):
  `map.on('terrain', this._update)` and the `if (this._map.terrain)` branch).
- **Terrain occlusion — this is the Marker-only advantage.** "CSS class
  `maplibregl-marker-covered` is toggled on the marker element when the marker is
  hidden behind 3D terrain or on the back of a globe" (marker.ts lines ~192-194),
  driven by `transform.isLocationOccluded()` + `terrain.depthAtPoint()`. Opacity
  options: `opacity` (default `1`) — "Marker's opacity when it's in clear view
  (not behind 3d terrain)" — and `opacityWhenCovered` (default `0.2`) — "Marker's
  opacity when it's behind 3d terrain"
  ([MarkerOptions](https://maplibre.org/maplibre-gl-js/docs/API/type-aliases/MarkerOptions/)).
- **Relevant `MarkerOptions`** (defaults from the same page): `offset` (PointLike,
  pixels; "Negatives indicate left and up" — this is how a DOM label floats above
  the point), `anchor` (default `'center'`), `pitchAlignment` (default `'auto'`;
  `'viewport'` keeps the label facing the camera — the right choice for a floating
  name), `rotationAlignment` (default `'auto'`), `className`, `subpixelPositioning`.
- **`Map.queryTerrainElevation(lngLatLike)`** — "Gets the elevation at a given
  location, in meters above sea level. Returns null if terrain is not enabled. If
  terrain is enabled with some exaggeration value, the value returned here will be
  reflective of (multiplied by) that exaggeration value."
  ([`src/ui/map.ts`](https://github.com/maplibre/maplibre-gl-js/blob/main/src/ui/map.ts),
  `queryTerrainElevation`). Note: we already have each peak's `ele` from the
  pipeline, so we don't need this for labels — it's only useful if you wanted to
  drive a *real* metric offset yourself (which markers can't do natively anyway;
  the offset is pixels).
- Related known rough edge for large custom markers on terrain:
  [maplibre-gl-js #1783](https://github.com/maplibre/maplibre-gl-js/issues/1783)
  (a wide custom element can read as "in clear view" until its center is clearly
  behind a mountain).

DOM markers vs a symbol layer for ~100 peaks: symbols are GPU-drawn in one layer,
collide/declutter for free, and cost ~nothing extra per feature; ~100 DOM markers
are 100 elements the browser lays out and repositions every frame with no
built-in collision. For a static snapshot with a tilted, panning camera, the
symbol layer is the lighter, better-decluttered choice.

### 6. Occlusion for symbol layers (labels showing through mountains)

**Symbol/text is not depth-occluded against terrain in MapLibre.** A peak label
whose summit is behind a nearer ridge will still draw on top. Primary source:
[maplibre-gl-js #1030 "Line labels 'show through' the terrain"](https://github.com/maplibre/maplibre-gl-js/issues/1030)
— open since Feb 2022, labels render fully even when the geometry is obscured;
"Show labels only not obstructed by the terrain" is the *requested* (not current)
behaviour. This is the one place DOM markers (point 5) are strictly better, since
they get the `maplibregl-marker-covered` fade. Mitigations for the symbol path:
filter to prominent peaks (fewer background labels to poke through), keep the
`60°`/south-west framing, and accept that a far-side peak name may occasionally
appear over a foreground slope.

### 7. Label legibility on 3D terrain

- **Halo.** `text-halo-color` + `text-halo-width` (both js `0.10.0`) — a white or
  light halo (width ~1.2-2) keeps dark peak text readable over the VersaTiles
  landcover and hillshade. Standard practice; the maplibre
  [3D terrain example](https://maplibre.org/maplibre-gl-js/docs/examples/3d-terrain/)
  renders a labelled vector style over terrain (labels kept, not stripped) —
  evidence that labelled symbols on a terrain mesh are a supported, normal setup.
- **Thin the set by prominence.** Filter the symbol layer by `ele`, e.g. only
  peaks above a metre threshold, or by zoom (show more as you zoom in). We have
  `ele` per peak in the domain data, so this is a pure style filter.
- **Declutter via collision.** `text-allow-overlap: false` + `symbol-sort-key`
  (point 4) does the automatic decluttering; no manual layout needed.

## The three approaches, side by side

| | A. Symbol layer + screen-space offset (**recommended**) | B. Symbol layer + true 3D elevation | C. HTML `Marker`s |
|---|---|---|---|
| Available in 5.24? | ✅ fully | ❌ not shipped (#62/#1508 open, #7827 draft) | ✅ fully |
| "Floating above summit" fidelity | Good — text sits on summit + lifted in screen px | Ideal — true metric hover, reprojects with camera | OK — pixel offset above the clamped point |
| Sits on terrain surface | ✅ automatic | ✅ (offset from it) | ✅ automatic |
| Terrain occlusion (hidden behind ridge) | ❌ shows through (#1030) | ❌ (same engine limitation) | ✅ `opacityWhenCovered` / `maplibregl-marker-covered` |
| Declutter/collision for ~100 | ✅ built-in | ✅ built-in | ❌ none (manual) |
| Perf at ~100 peaks | ✅ one GPU layer | ✅ one GPU layer | ⚠️ ~100 DOM nodes repositioned per frame |
| Dependency-bar fit (rule 4) | ✅ pure maplibre style | ✅ once it ships | ✅ maplibre, but heavier + more glue |

## Drop-in sketch for the recommended approach (Approach A)

Fits the imperative `src/map/` pattern. Two edits:

**(1) Carry `name` + `ele` on the peak features.** The existing
`toFeatureCollection` in `RouteMap.ts` only emits `{ id, type, isPlace }`. The
symbol layer needs the label text, so extend `PoiFeatureProps` and the mapper:

```ts
// RouteMap.ts — PoiFeatureProps gains the label fields (maplibre only carries
// JSON-serialisable feature properties, so keep them flat/primitive).
interface PoiFeatureProps extends PoiVisibilityFeature {
	type: string;
	name: string;
	ele: number | null; // metres; may be null (see domain Poi)
}

// ...inside toFeatureCollection's props:
const props: PoiFeatureProps = {
	id: poi.id,
	type: poi.type,
	isPlace: placePoiIds.has(poi.id),
	name: poi.name,
	ele: poi.ele,
};
```

**(2) A `PEAK_LABEL_LAYER_ID` symbol layer, added AFTER `customizeBasemap`
stripped symbols, and re-added by `reapplyAfterStyle`.** It reads the *existing*
`pois` source (no new source), filtered to peaks:

```ts
const PEAK_LABEL_LAYER_ID = "peak-labels";

// A symbol layer for peak names, floating above each summit marker. Added only in
// 3D and only AFTER customizeBasemap() has stripped the basemap's own symbol
// layers, so it survives that pass. Reads the existing `pois` GeoJSON source
// (POI_SOURCE_ID), filtered to peaks, so no new source/data is needed.
function addPeakLabels(): void {
	if (!map.getSource(POI_SOURCE_ID) || map.getLayer(PEAK_LABEL_LAYER_ID)) {
		return; // needs the pois source; idempotent
	}
	map.addLayer({
		id: PEAK_LABEL_LAYER_ID,
		type: "symbol",
		source: POI_SOURCE_ID,
		// Only peaks. Optionally also gate on prominence, e.g. add
		// ["any", ["!", ["has", "ele"]], [">=", ["get", "ele"], 2000]].
		filter: ["==", ["get", "type"], "peak"],
		layout: {
			// Name, with elevation on a second line when present.
			"text-field": [
				"case",
				["has", "ele"],
				["format",
					["get", "name"], {},
					["concat", "\n", ["to-string", ["get", "ele"]], " m"],
						{ "font-scale": 0.8 },
				],
				["get", "name"],
			],
			// Float the text ABOVE the summit point: anchor at the label's bottom
			// edge and lift it upward (negative Y = up). This is screen-space —
			// the true metres-above-terrain property (symbol-elevation) is not in
			// 5.24 (style-spec #62 / gl-js #7827, not shipped).
			"text-anchor": "bottom",
			"text-offset": [0, -1.2],
			"text-size": 12,
			// Declutter ~100 labels: no overlap, highest peaks win placement.
			"text-allow-overlap": false,
			"text-optional": false,
			"symbol-sort-key": ["-", 0, ["coalesce", ["get", "ele"], 0]],
		},
		paint: {
			"text-color": "#1a1a1a",
			"text-halo-color": "#ffffff",
			"text-halo-width": 1.4,
		},
	});
}
```

**(3) Wire it into the existing lifecycle.** `customizeBasemap` runs on 3D style
(re)load and strips symbols; add the peak labels right after it, and re-add them
in `reapplyAfterStyle` (which already rebuilds everything a `setStyle` swap wiped,
in the right order — base customizations → terrain → POIs → highlight):

```ts
function reapplyAfterStyle(): void {
	if (appliedMode === "3d") {
		customizeBasemap(map);
	}
	applyTerrain(terrainEnabled);
	if (currentPois) {
		renderPois(currentPois);
	}
	if (appliedMode === "3d") {
		addPeakLabels(); // AFTER renderPois (needs POI_SOURCE_ID) and AFTER the strip
	}
	renderHighlight(selectedEntry, false);
}
```

Because `renderPois` re-creates the `pois` source on every base-map swap and
`customizeBasemap` strips all symbols each time the 3D style loads, `addPeakLabels`
must run **after both** — exactly where `reapplyAfterStyle` places it. In 2D the
OpenTopoMap raster keeps its own baked labels, so peak labels are added in 3D only
(mirroring how `customizeBasemap`/hillshade are 3D-only). Guard for null `ele`
with `has`/`coalesce` as shown (the domain `Poi.ele` may be null).

Note: this uses the basemap's font glyphs. VersaTiles "colorful" defines a
`glyphs` URL in its style JSON, which survives `setStyle`, so `text-field` has
fonts to render with; if a specific `text-font` is ever needed, set one that the
glyph endpoint provides.

## What I verified vs. what I could not

- **Verified against primary sources (quoted/grepped above):** the symbol layout
  properties and their SDK-support versions
  ([style-spec layers](https://maplibre.org/maplibre-style-spec/layers/) +
  [`v8.json`](https://github.com/maplibre/maplibre-style-spec/blob/main/src/reference/v8.json));
  the **absence** of `symbol-z-elevate` / `symbol-elevation*` from the spec (grep
  of `v8.json` on `main`, 2026-07-17) and from the
  [CHANGELOG](https://github.com/maplibre/maplibre-gl-js/blob/main/CHANGELOG.md);
  the open/draft status of the elevation feature
  ([#62](https://github.com/maplibre/maplibre-style-spec/issues/62),
  [#1508](https://github.com/maplibre/maplibre-style-spec/pull/1508),
  [#7827](https://github.com/maplibre/maplibre-gl-js/pull/7827),
  [#4879](https://github.com/maplibre/maplibre-gl-js/issues/4879)); Marker terrain
  clamping, occlusion, and options
  ([marker.ts](https://github.com/maplibre/maplibre-gl-js/blob/main/src/ui/marker.ts),
  [MarkerOptions](https://maplibre.org/maplibre-gl-js/docs/API/type-aliases/MarkerOptions/));
  `queryTerrainElevation` semantics
  ([map.ts](https://github.com/maplibre/maplibre-gl-js/blob/main/src/ui/map.ts));
  and the still-open label-occlusion limitation
  ([#1030](https://github.com/maplibre/maplibre-gl-js/issues/1030)).
- **Inferred, not stated verbatim:** that point symbols render *at terrain height*
  by default — I read this from PR #1508's description that `symbol-elevation`
  would "override the map's terrain height", plus the identical terrain-projection
  path Markers use; there is no single doc sentence that says "symbols are clamped
  to terrain," so treat it as strongly-supported inference rather than a quoted
  spec line.
- **`symbol-z-elevate` as a Mapbox property:** stated from its absence in MapLibre
  primary sources; I did not cite Mapbox's (non-MapLibre) docs, so the "it's a
  Mapbox feature" framing is context, not a MapLibre-sourced claim.
- **Not verified in-browser:** I did not run the sketch against the live app
  (research-only task). The glyph/font availability note and the exact
  `text-offset` value should be confirmed in the DevTools pass when implemented
  (`route-map/CLAUDE.md` Testing).
