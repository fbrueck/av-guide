import type { FeatureCollection } from "geojson";
import {
	type ExpressionSpecification,
	type FilterSpecification,
	type GeoJSONSource,
	LngLatBounds,
	type LngLatLike,
	Map as MapLibreMap,
	Marker,
	NavigationControl,
	type PointLike,
	ScaleControl,
} from "maplibre-gl";
import type { Entry, Guide, Poi } from "../domain";
import {
	BASEMAP_MAX_ZOOM,
	basemapStyle2d,
	buildCombinedStyle,
	HILLSHADE_SOURCE_ID,
	OPENTOPO_SOURCE_ID,
	TERRAIN_EXAGGERATION,
	TERRAIN_PITCH,
	TERRAIN_SOURCE_ID,
	VERSATILES_SOURCE_ID,
} from "./basemap";
import { boundsForGuideBoxes } from "./overview";
import { poiColorExpression } from "./poiStyle";
import {
	type PoiVisibilityFeature,
	poiVisibilityFilter,
} from "./poiVisibility";
import {
	boundsForPois,
	type CameraFrame,
	DEFAULT_CENTER,
	DEFAULT_ZOOM,
	SINGLE_POINT_ZOOM,
} from "./view";

const POI_SOURCE_ID = "pois";
const POI_LAYER_ID = "poi-markers";

// The Guide overview layer (#141): each published Guide's manifest bbox drawn as
// a labelled rectangle so a reader can pick a Guide from the map itself. A
// dedicated source/layers, entirely separate from the POI layer — the boxes are
// overview chrome, never POIs and never a selection target (ADR-0004 untouched).
const GUIDE_BOX_SOURCE_ID = "guide-boxes";
const GUIDE_BOX_FILL_LAYER_ID = "guide-box-fill";
const GUIDE_BOX_LINE_LAYER_ID = "guide-box-line";

// A small palette cycled across the boxes so adjacent Guides read as distinct at
// a glance; the labels carry the actual identity.
const GUIDE_BOX_COLORS = [
	"#2563eb",
	"#dc2626",
	"#059669",
	"#d97706",
	"#7c3aed",
];

// A symbol layer that floats peak names above each summit — 3D only (the flat 2D
// OpenTopoMap raster carries its own baked labels). See
// docs/research/2026-07-17-peak-labels-on-3d-map.md (Approach A) for why this is
// screen-space rather than true metres-above-terrain.
const PEAK_LABEL_LAYER_ID = "peak-labels";

// A dedicated emphasis source/layer drawn ON TOP of the base poi-markers so a
// selected Entry's linked POI set stands out without redrawing the base
// (route-map/CLAUDE.md rule 3: rendering a Route = highlighting its POI set,
// never a polyline). Feature `role` drives a data-driven paint so the target
// coordinates (a Route's Destination + places' POIs, or a Place's own POI) are
// tell-apart-able from Mentions at a glance.
const HIGHLIGHT_SOURCE_ID = "entry-highlight";
const HIGHLIGHT_LAYER_ID = "entry-highlight-markers";

// Camera framing for the single-point case is SINGLE_POINT_ZOOM, owned by
// view.ts alongside boundsForPois so the opening frame and a selection fit cannot
// drift on how tight a lone point zooms (a zero-area bounds would over-zoom; the
// low zoom keeps surrounding terrain context in frame, #120).
// Fit padding + a ceiling so a tight multi-POI cluster does not slam to max zoom.
const FIT_PADDING = 64;
const FIT_MAX_ZOOM = 13;
// The opening frame (frameGuide) uses a snugger padding than a selection fit —
// it matches the padding the retired construction-time WETTERSTEIN_BOUNDS framing
// used, so the app opens on the POI extent visually identical to before (#131).
const OPENING_FIT_PADDING = 32;

// Mirrors the single `max-width: 768px` CSS breakpoint (route-map/CLAUDE.md
// rule 8): below it the route panel becomes a bottom sheet overlaying the map.
const MOBILE_BREAKPOINT = 768;

// Tap-tolerance for selecting a POI on touch/mobile. A Place marker's rendered
// disc is only ~16px across — well under the ≥44px mobile tap-target bar
// (route-map/CLAUDE.md rule 8). Rather than fatten the markers (which would
// bleed onto desktop and change the place-first look), we widen only the HIT
// TEST: on mobile a tap queries a padded box of this radius and selects the
// nearest tappable Place marker. Desktop keeps exact-hit — a mouse is precise,
// and a tolerance would "select" over empty map. The pad is the box radius, so
// 32px ≈ a 64px hit box.
const TAP_TOLERANCE_PX = 32;

// On mobile the bottom sheet overlays the lower part of the map with its
// collapsed peek height, so the camera must frame highlighted POIs in the area
// ABOVE it — otherwise a selection centers behind the sheet. Returns that peek
// height in pixels (the obscured bottom inset), reading the single source of
// truth CSS variable so it never drifts from the layout; 0 on desktop, where the
// panel docks beside the map and nothing overlays it.
function bottomSheetInsetPx(): number {
	if (window.innerWidth > MOBILE_BREAKPOINT) {
		return 0;
	}
	const raw = getComputedStyle(document.documentElement)
		.getPropertyValue("--sheet-peek-height")
		.trim();
	if (raw.endsWith("vh")) {
		return (Number.parseFloat(raw) / 100) * window.innerHeight;
	}
	if (raw.endsWith("px")) {
		return Number.parseFloat(raw);
	}
	return 0;
}

const EMPTY_FEATURE_COLLECTION: FeatureCollection = {
	type: "FeatureCollection",
	features: [],
};

// The single owner of the maplibre-gl Map instance (route-map/CLAUDE.md
// rule 4). It is created imperatively and hidden behind this small typed API;
// UI components never touch maplibre-gl directly.
export interface RouteMap {
	/** Render the guide's POIs as typed markers on the basemap. Place POIs (the
	 *  coordinate of a Place, `placePoiIds`) are the **primary** markers — drawn
	 *  larger with a dark ring — so the place-first model reads at a glance;
	 *  mention-only / gazetteer POIs recede. Also supply the poi_id ->
	 *  referencing-Entries index used to resolve a tapped Place-coordinate marker
	 *  back to its Place (ADR-0004: POIs are display-only, so this is the only
	 *  Entry lookup a POI tap does). All three arrive with the data (from the
	 *  loaded GuideData), so they are passed here rather than at construction.
	 *  Idempotent — calling again replaces the rendered set. */
	showPois(
		pois: Poi[],
		entriesByPoiId: Map<string, Entry[]>,
		placePoiIds: Set<string>,
	): void;
	/** Emphasize a selected Entry's linked POI set (#44) AND reveal that Entry's
	 *  Mentions on the base layer (#77) — one selection door drives both layers.
	 *  The highlight overlay styles the target coordinates (a Route's Destination
	 *  + places' POIs, or a Place's own POI) distinctly from the Mentions on top
	 *  of the base markers, then fits the camera to the set. Simultaneously the
	 *  base POI layer's filter switches to "Place POIs plus this Entry's Mentions"
	 *  so the mention-only POIs the default view hides become visible while the
	 *  Entry is selected. Passing `null` clears the highlight and returns the base
	 *  layer to the default (Place POIs only). Honest by design: an empty POI set
	 *  draws nothing, reveals nothing, and leaves the camera put — a Route has no
	 *  geometry, so nothing is invented (route-map/CLAUDE.md rule 3). Idempotent
	 *  and safe to call before the style loads. */
	highlightEntry(entry: Entry | null): void;
	/** Remove the current Guide's POIs (and their peak labels) — App calls this on
	 *  returning to the overview (#142), so the map is left clean beneath the
	 *  overview boxes (the two layers never overlap). Symmetric with
	 *  `clearGuideBoxes`; safe to call when no POIs are drawn or before the style
	 *  loads. Re-entering a Guide repaints them via `showPois`. */
	clearPois(): void;
	/** Flip the map between the flat 2D basemap and 3D terrain (#23). Both base
	 *  maps live in one combined style, so this is a visibility flip + setTerrain
	 *  + camera pitch — never a setStyle — which keeps the toggle a single smooth
	 *  motion with no full-style-reload flash (#121). On enable the OpenTopoMap
	 *  raster is hidden, the VersaTiles landcover + hillshade are shown, the
	 *  Mapterhorn terrain mesh is applied, and the camera pitches up; disable
	 *  reverses it and re-locks the angle — 2D fixes the tilt (maxPitch 0), while
	 *  rotation stays free in both modes (#120). Idempotent and safe to call
	 *  before the style loads. */
	setTerrain(enabled: boolean): void;
	/** Frame the map on a Guide's POI extent (#131) — the opening view, computed
	 *  from the loaded POIs (boundsForPois) rather than a hardcoded constant, so
	 *  the app opens fitted to whichever Guide it loads. App calls this once the
	 *  guide data resolves (the POIs aren't known at construction). Degenerate
	 *  sets are honest: no POIs → a default overview, a single POI → a sensible
	 *  centered zoom, never a zero-area frame (route-map/CLAUDE.md rule 3). Snaps
	 *  into place (no pan animation) and respects the mobile bottom-sheet inset,
	 *  like the selection framing (fitToPois). */
	frameGuide(pois: Poi[]): void;
	/** Draw the Guide overview boxes (#141): each Guide's manifest bbox as a
	 *  distinct, labelled rectangle, on a source/layers separate from the POI
	 *  layer. The boxes are display-only overview chrome — a click calls back
	 *  `onSelectGuide` (construction option), never a selection (ADR-0004). App
	 *  calls this while in the overview state. Idempotent (replaces the drawn set)
	 *  and safe to call before the style loads. */
	showGuideBoxes(guides: Guide[]): void;
	/** Remove the overview boxes — App calls this on entering a Guide, so the map
	 *  is left clean for that Guide's POIs. Safe to call when none are drawn. */
	clearGuideBoxes(): void;
	/** Hover-highlight one overview box by guide id (or `null` to clear), so the
	 *  sidebar Guide list and the map read as one picker (#141): hovering a row
	 *  emphasizes its box. The reverse — hovering a box emphasizing its row —
	 *  flows the other way via the `onHoverGuide` construction callback. */
	highlightGuideBox(guideId: string | null): void;
	/** Frame the camera to fit ALL Guide overview boxes (#141) — the overview
	 *  opening view, computed by boundsForGuideBoxes (pure). No boxes → a default
	 *  overview, never a zero-area frame. Snaps into place, respecting the mobile
	 *  bottom-sheet inset, like frameGuide. */
	frameOverview(guides: Guide[]): void;
	destroy(): void;
}

// The GeoJSON feature properties the overview box layers read. Flat + primitive
// (maplibre carries only JSON-serialisable props): `id` resolves a clicked/hovered
// box back to its Guide, `color` drives the per-box paint, `name` is unused by the
// layers (the DOM label markers show it) but kept for debuggability.
interface GuideBoxFeatureProps {
	id: string;
	name: string;
	color: string;
}

// The GeoJSON feature properties the POI layer reads. Kept flat and primitive
// because maplibre only carries JSON-serialisable feature properties. `type`
// drives the data-driven colour paint; `id`/`isPlace` (from PoiVisibilityFeature,
// the single source of truth for the base-layer shape) drive the visibility
// filter and the display-only tap → Place resolution (ADR-0004).
interface PoiFeatureProps extends PoiVisibilityFeature {
	type: string;
	// The peak-label symbol layer (3D) reads these for its text-field; flat and
	// primitive like the rest, because maplibre only carries JSON-serialisable
	// feature properties.
	name: string;
	ele: number | null;
}

function toFeatureCollection(
	pois: Poi[],
	placePoiIds: Set<string>,
): FeatureCollection {
	return {
		type: "FeatureCollection",
		features: pois.map((poi) => {
			const props: PoiFeatureProps = {
				id: poi.id,
				type: poi.type,
				isPlace: placePoiIds.has(poi.id),
				name: poi.name,
				ele: poi.ele,
			};
			return {
				type: "Feature",
				id: poi.id,
				geometry: { type: "Point", coordinates: poi.coordinates },
				properties: props,
			};
		}),
	};
}

// The Entry's POI set (route-map/CLAUDE.md rule 3): the target coordinates first
// (role "target" — a Route's Destination + places' POIs, or a Place's own POI),
// then its Mentions (role "mention"). The paint uses `role` to tell the targets
// apart from the places the prose merely passes through. Target coordinates are
// transitive via the Place — never a direct Entry->POI link.
type PoiRole = "target" | "mention";

interface HighlightSet {
	targets: Poi[];
	mentions: Poi[];
}

function highlightSetFor(entry: Entry): HighlightSet {
	if (entry.kind === "route") {
		// A Route's target coordinates: its Destination's POI plus each of its
		// additional target Places' POIs (transitive, skipping unresolved ones).
		const targets: Poi[] = [];
		for (const place of [entry.destination, ...entry.places]) {
			if (place?.poi) {
				targets.push(place.poi);
			}
		}
		return { targets, mentions: entry.mentions };
	}
	// A Place's own POI is its target coordinate; its Übersicht Mentions ride
	// along styled as mentions.
	return {
		targets: entry.poi ? [entry.poi] : [],
		mentions: entry.mentions,
	};
}

function toHighlightFeatureCollection(set: HighlightSet): FeatureCollection {
	const features: FeatureCollection["features"] = [];
	const push = (poi: Poi, role: PoiRole) => {
		features.push({
			type: "Feature",
			id: `${role}:${poi.id}`,
			geometry: { type: "Point", coordinates: poi.coordinates },
			properties: { role },
		});
	};
	for (const poi of set.targets) {
		push(poi, "target");
	}
	for (const poi of set.mentions) {
		push(poi, "mention");
	}
	return { type: "FeatureCollection", features };
}

// A Guide's manifest bbox (`[south, west, north, east]`, lat/lon) as a closed
// rectangle polygon in `[lng, lat]` — the order maplibre geometry uses. The one
// place the lat/lon-ordered bbox is turned into map geometry (boundsForGuideBoxes
// does the same conversion for the camera frame).
function toGuideBoxFeatureCollection(guides: Guide[]): FeatureCollection {
	return {
		type: "FeatureCollection",
		features: guides.map((guide, index) => {
			const [south, west, north, east] = guide.bbox;
			const props: GuideBoxFeatureProps = {
				id: guide.id,
				name: guide.name,
				// The modulo keeps the index in range; the ?? satisfies the
				// noUncheckedIndexedAccess strictness with an equivalent default.
				color: GUIDE_BOX_COLORS[index % GUIDE_BOX_COLORS.length] ?? "#2563eb",
			};
			return {
				type: "Feature",
				// String feature id so feature-state (the hover emphasis) keys on it.
				id: guide.id,
				geometry: {
					type: "Polygon",
					coordinates: [
						[
							[west, south],
							[east, south],
							[east, north],
							[west, north],
							[west, south],
						],
					],
				},
				properties: props,
			};
		}),
	};
}

// Options passed at construction (before the guide data loads). onSelectEntry is
// App's single selection entry point (a stable useCallback), so a tapped
// Place-coordinate marker selects its Place identically to a sidebar click — the
// map never owns selection, it just calls back (route-map/CLAUDE.md rule 4).
// onSelectGuide / onHoverGuide are the overview equivalents (#141): a box click
// picks that Guide (the same door the sidebar Guide list uses), and a box hover
// tells App which row to emphasize — the map owns neither the view nor the
// selection, it just calls back.
export interface CreateRouteMapOptions {
	onSelectEntry: (entry: Entry) => void;
	onSelectGuide: (guideId: string) => void;
	onHoverGuide: (guideId: string | null) => void;
}

export function createRouteMap(
	container: HTMLElement,
	{ onSelectEntry, onSelectGuide, onHoverGuide }: CreateRouteMapOptions,
): RouteMap {
	const map = new MapLibreMap({
		container,
		style: basemapStyle2d,
		// A broad default view for the map's first paint — the real opening frame
		// is set by frameGuide once the guide's POIs load (they aren't known at
		// construction, #131), which snaps the camera to the loaded Guide's extent.
		// This default just avoids a null-island flash in the meantime.
		center: DEFAULT_CENTER,
		zoom: DEFAULT_ZOOM,
		maxZoom: BASEMAP_MAX_ZOOM,
		// Start flat and tilt-locked: the map opens in 2D, where the angle is
		// fixed (#120). applyMode raises maxPitch when 3D is enabled and drops it
		// back to 0 on return. Rotation stays free in both modes.
		maxPitch: 0,
		// The app renders its own attribution as a React overlay
		// (src/components/MapAttribution.tsx) rather than a maplibre control, so
		// it can be collapsed-by-default declaratively — which the library's
		// AttributionControl does not support. Suppress the built-in one here.
		attributionControl: false,
	});

	map.addControl(new NavigationControl(), "top-right");
	map.addControl(new ScaleControl(), "bottom-left");

	// Swap the 2D-only bootstrap style for the combined style (both base maps + the
	// DEM) once its remote VersaTiles part is fetched. This is a one-time install at
	// startup — invisible, since both styles show OpenTopoMap in 2D — after which a
	// 2D↔3D toggle never touches setStyle (#121). The install wipes runtime-added
	// layers, so onCombinedReady re-applies POIs, highlight, and the view mode. Wait
	// for the new style's first `styledata` before gating on full readiness (right
	// after setStyle, isStyleLoaded() still reports the OLD style).
	buildCombinedStyle()
		.then((style) => {
			map.setStyle(style);
			map.once("styledata", () => whenStyleReady(onCombinedReady));
		})
		.catch((error: unknown) => {
			console.error("[route-map] combined style install failed", error);
		});

	// The poi_id -> referencing-Entries index, supplied with the POIs via showPois
	// (both come from the loaded GuideData). Used to resolve a tapped
	// Place-coordinate marker back to its Place (ADR-0004: POIs are display-only,
	// so this is the sole POI → Entry lookup). Empty until showPois runs; a tap
	// before data loads simply resolves nothing.
	let entriesByPoiId: Map<string, Entry[]> = new Map();
	// The set of poi_ids that are a Place's coordinate — the primary markers, and
	// the POIs whose click selects a Place directly. Supplied with the POIs.
	let placePoiIds: Set<string> = new Set();
	// showPois may run before the style has loaded (data fetch races map init);
	// buffer the latest set and flush it once the style is ready.
	let pendingPois: Poi[] | null = null;
	// highlightEntry has the same race (an entry can be pre-selected before load).
	// Buffer the latest requested selection; `null` means "clear". We track
	// whether a highlight request is pending separately from its value so a
	// buffered clear is distinguishable from "no request yet".
	let pendingHighlight: Entry | null = null;
	let hasPendingHighlight = false;
	// The currently-applied selection, read by the base POI layer's visibility
	// filter (#77): the default (null) shows only Place POIs; a selected Entry
	// also reveals that Entry's Mentions. Kept here (not only in pendingHighlight)
	// so renderPois can seed a freshly-created layer with the right filter when
	// the POIs load after a selection is already active.
	let selectedEntry: Entry | null = null;
	// setTerrain has the same race; buffer the latest desired state and apply it
	// once the combined style is installed.
	let terrainEnabled = false;
	// The map boots on the 2D-only style for an instant first paint, then the
	// combined style (both base maps + the DEM) is installed once its remote
	// VersaTiles part has been fetched (buildCombinedStyle). Until then a 2D↔3D
	// toggle is buffered in terrainEnabled and applied on install; after it, the
	// toggle is a pure visibility flip with no setStyle.
	let combinedInstalled = false;
	// The last POI set handed to showPois. Installing the combined style wipes all
	// runtime-added sources/layers, so the POIs (and the selection highlight, from
	// selectedEntry) must be re-rendered from here once it is in.
	let currentPois: Poi[] | null = null;
	// The POI click/hover handlers are map-level, filtered by layer id, so they
	// survive a style install and must be wired exactly once — re-wiring would
	// stack duplicate handlers.
	let interactionsWired = false;
	// The Guide overview boxes (#141). currentGuideBoxes is the last set handed to
	// showGuideBoxes, retained so the fill/line layers can be re-added after a base
	// style install wipes them (the label markers are DOM, so they survive it).
	// guideBoxMarkers holds the DOM label per guide id (for the hover emphasis + a
	// clean removal). hoveredBoxId is the box currently emphasized (from a row hover
	// or a box hover). guideBoxInteractionsWired mirrors interactionsWired.
	let currentGuideBoxes: Guide[] | null = null;
	const guideBoxMarkers = new Map<string, Marker>();
	let hoveredBoxId: string | null = null;
	let guideBoxInteractionsWired = false;

	// Run `task` once the style can accept sources/layers. maplibre's `load`
	// event is one-shot, so a `map.once("load", …)` registered AFTER load has
	// already fired never runs; and `isStyleLoaded()` can briefly report false in
	// the window just after load while a style-diff settles. A late caller like
	// showPois (which waits on async guide data) can land in exactly that window
	// — isStyleLoaded() false yet load already gone — and its POIs would stay
	// buffered forever (blank map on the deployed snapshot build, #64). So gate on
	// the events that keep firing as the style settles (`styledata`/`idle`),
	// re-checking readiness each time, instead of trusting one load event. Runs
	// synchronously when the style is already ready.
	function whenStyleReady(task: () => void): void {
		if (map.isStyleLoaded()) {
			task();
			return;
		}
		const attempt = () => {
			if (!map.isStyleLoaded()) {
				return;
			}
			map.off("styledata", attempt);
			map.off("idle", attempt);
			task();
		};
		map.on("styledata", attempt);
		map.on("idle", attempt);
	}

	// Flip which base map is shown, without a setStyle: 2D shows the OpenTopoMap
	// raster; 3D shows the VersaTiles landcover + hillshade + the floating peak
	// labels. A hidden layer streams no tiles, so 2D loads neither the VersaTiles
	// nor the DEM tiles (attribution stays honest). Leaves the POI + highlight
	// layers untouched — they show in both modes.
	function setBaseVisibility(enabled: boolean): void {
		const setVis = (id: string, visible: boolean) => {
			if (map.getLayer(id)) {
				map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
			}
		};
		for (const layer of map.getStyle().layers ?? []) {
			if (layer.id === OPENTOPO_SOURCE_ID) {
				setVis(layer.id, !enabled);
			} else if (layer.type === "background") {
				// VersaTiles' base land colour (rgb 249,244,238) is a source-less
				// background layer. It must show in 3D so the semi-transparent landcover
				// fills composite over an opaque pale base — otherwise bare/grassy terrain
				// (no landcover polygon) and the low-opacity fills render black. Hidden in
				// 2D, where the OpenTopoMap raster is the base.
				setVis(layer.id, enabled);
			} else if ("source" in layer && layer.source === VERSATILES_SOURCE_ID) {
				setVis(layer.id, enabled);
			}
		}
		setVis(HILLSHADE_SOURCE_ID, enabled);
		setVis(PEAK_LABEL_LAYER_ID, enabled);
	}

	// Apply the view mode: swap base visibility, attach/clear the terrain mesh
	// (its DEM source is resident in the combined style, so no addSource), and
	// pitch the camera. Firing all three together lets the tilt and the relief
	// animate as one motion instead of the old flat-then-pitch-then-pop stages.
	function applyMode(enabled: boolean): void {
		setBaseVisibility(enabled);
		if (enabled) {
			// Unlock tilt before pitching up — maxPitch is 0 while in 2D (#120).
			map.setMaxPitch(TERRAIN_PITCH);
			map.setTerrain({
				source: TERRAIN_SOURCE_ID,
				exaggeration: TERRAIN_EXAGGERATION,
			});
		} else {
			map.setTerrain(null);
		}
		map.easeTo({ pitch: enabled ? TERRAIN_PITCH : 0 });
		if (!enabled) {
			// Re-lock the flat 2D angle so the map can't be tilted (rotation stays
			// free) (#120). Deferred to the pitch-down's end so the smooth transition
			// (#121) survives — setMaxPitch would otherwise snap the camera flat. The
			// getTerrain guard drops a stale lock if 3D was re-enabled meanwhile; when
			// already flat (no pitch animation, e.g. reapply) it locks immediately.
			const lock = () => {
				if (!map.getTerrain()) {
					map.setMaxPitch(0);
				}
			};
			if (map.getPitch() === 0) {
				lock();
			} else {
				map.once("moveend", lock);
			}
		}
	}

	// Installing the combined style wipes all runtime-added sources/layers, so once
	// it is in we re-apply them from the retained state: POIs (+ peak labels) and
	// the selection highlight, then the current view mode. Nothing here reframes
	// the camera — a mode toggle keeps the view.
	function onCombinedReady(): void {
		combinedInstalled = true;
		if (currentPois) {
			renderPois(currentPois);
		}
		renderHighlight(selectedEntry, false);
		// Re-add the overview boxes' fill/line layers wiped by the install (their
		// DOM label markers survive it, so renderGuideBoxes leaves those alone).
		if (currentGuideBoxes) {
			renderGuideBoxes(currentGuideBoxes);
		}
		applyMode(terrainEnabled);
	}

	function renderPois(pois: Poi[]): void {
		const data = toFeatureCollection(pois, placePoiIds);
		const existing = map.getSource(POI_SOURCE_ID) as GeoJSONSource | undefined;
		if (existing) {
			existing.setData(data);
			return;
		}
		map.addSource(POI_SOURCE_ID, { type: "geojson", data });
		map.addLayer({
			id: POI_LAYER_ID,
			type: "circle",
			source: POI_SOURCE_ID,
			paint: {
				// Place POIs are the primary markers: larger, dark-ringed. Mention-
				// only / gazetteer POIs are smaller with a thin white ring so they
				// recede (route-map/CLAUDE.md rule 3, #44 place-first map).
				"circle-radius": [
					"case",
					["get", "isPlace"],
					8,
					/* other */ 5,
				] as unknown as ExpressionSpecification,
				"circle-color":
					poiColorExpression() as unknown as ExpressionSpecification,
				"circle-stroke-width": [
					"case",
					["get", "isPlace"],
					2.5,
					/* other */ 1,
				] as unknown as ExpressionSpecification,
				"circle-stroke-color": [
					"case",
					["get", "isPlace"],
					"#111827",
					/* other */ "#ffffff",
				] as unknown as ExpressionSpecification,
			},
		});
		// Seed the base layer's visibility filter from the current selection (#77):
		// the default hides mention-only POIs (Place POIs only), and if an Entry is
		// already selected when the POIs load, its Mentions show too. Same call the
		// highlight path uses, so there is one place the filter is built.
		applyPoiVisibility();
		// Wire interactions once (handlers are map-level and survive a style
		// install); the layer is re-created on each install but the handlers still
		// match it.
		if (!interactionsWired) {
			wireInteractions();
			interactionsWired = true;
		}
		// Float peak names above the summits (reads POI_SOURCE_ID). Present in both
		// modes but shown only in 3D — the 2D OpenTopoMap carries its own baked
		// labels — so its visibility tracks the current mode.
		addPeakLabels();
		if (map.getLayer(PEAK_LABEL_LAYER_ID)) {
			map.setLayoutProperty(
				PEAK_LABEL_LAYER_ID,
				"visibility",
				terrainEnabled ? "visible" : "none",
			);
		}
	}

	// A symbol layer for peak names, floating above each summit marker. Added once
	// the POIs exist and shown only in 3D (renderPois gates its visibility on the
	// mode; the VersaTiles style's own symbol layers were stripped at build time in
	// buildCombinedStyle, so this is the only label layer on the 3D surface). Reads
	// the existing `pois` GeoJSON source (POI_SOURCE_ID), filtered to peaks — no new
	// source/data. Screen-space "above the summit": the true metres-above-terrain
	// property (symbol-elevation) is not in maplibre 5.24 (style-spec #62 /
	// gl-js #7827, not shipped), so anchor the label's bottom edge on the summit and
	// lift it upward in pixels. Idempotent.
	function addPeakLabels(): void {
		if (!map.getSource(POI_SOURCE_ID) || map.getLayer(PEAK_LABEL_LAYER_ID)) {
			return;
		}
		map.addLayer({
			id: PEAK_LABEL_LAYER_ID,
			type: "symbol",
			source: POI_SOURCE_ID,
			filter: ["==", ["get", "type"], "peak"] as unknown as FilterSpecification,
			layout: {
				// Name, with elevation on a second (smaller) line when present.
				"text-field": [
					"case",
					["has", "ele"],
					[
						"format",
						["get", "name"],
						{},
						["concat", "\n", ["to-string", ["get", "ele"]], " m"],
						{ "font-scale": 0.8 },
					],
					["get", "name"],
				] as unknown as ExpressionSpecification,
				"text-anchor": "bottom",
				"text-offset": [0, -1.2],
				"text-size": 12,
				// Declutter ~100 labels: no overlap, highest peaks win placement.
				"text-allow-overlap": false,
				"text-optional": false,
				"symbol-sort-key": [
					"-",
					0,
					["coalesce", ["get", "ele"], 0],
				] as unknown as ExpressionSpecification,
			},
			paint: {
				"text-color": "#1a1a1a",
				"text-halo-color": "#ffffff",
				"text-halo-width": 1.4,
			},
		});
	}

	// Ease/fit the camera to the highlighted POI set. Single point eases to a
	// sensible zoom rather than a degenerate zero-area bounds; an empty set leaves
	// the camera where it is (nothing to frame). Both paths preserve the current
	// pitch and bearing so a tilted 3D view survives a selection (#120): easeTo
	// keeps unspecified camera props, and fitBounds is told the current values
	// explicitly (else it flattens to pitch-0 / north-up).
	function fitToPois(pois: Poi[]): void {
		const [first, ...rest] = pois;
		if (!first) {
			return;
		}
		// Frame within the map area NOT covered by the mobile bottom sheet.
		const bottomInset = bottomSheetInsetPx();
		if (rest.length === 0) {
			// A single point centers by offset: shift the target up by half the
			// obscured height so it lands in the middle of the visible area.
			map.easeTo({
				center: first.coordinates,
				zoom: SINGLE_POINT_ZOOM,
				offset: [0, -bottomInset / 2],
			});
			return;
		}
		const bounds = new LngLatBounds();
		for (const poi of pois) {
			bounds.extend(poi.coordinates);
		}
		// Extra bottom padding keeps the bounds above the sheet.
		map.fitBounds(bounds, {
			padding: {
				top: FIT_PADDING,
				right: FIT_PADDING,
				bottom: FIT_PADDING + bottomInset,
				left: FIT_PADDING,
			},
			maxZoom: FIT_MAX_ZOOM,
			// Keep the current tilt/rotation — fitBounds resets both to 0 otherwise.
			pitch: map.getPitch(),
			bearing: map.getBearing(),
		});
	}

	// Switch the base POI layer's filter to the current selection (#77). A no-op
	// until the layer exists — renderPois seeds the filter from `selectedEntry` on
	// creation, so a selection made before the POIs load is not lost.
	function applyPoiVisibility(): void {
		if (!map.getLayer(POI_LAYER_ID)) {
			return;
		}
		map.setFilter(
			POI_LAYER_ID,
			poiVisibilityFilter(selectedEntry) as unknown as FilterSpecification,
		);
	}

	// `refit` reframes the camera to the highlighted set; pass false when merely
	// rebuilding the layer after a base-map swap, so a 2D↔3D toggle keeps the view.
	function renderHighlight(entry: Entry | null, refit = true): void {
		// The selection drives both layers through this one door (route-map/CLAUDE.md
		// rule 4): the highlight overlay below, and the base layer's mention-reveal
		// filter. Update the reveal first so it swaps atomically with the highlight.
		selectedEntry = entry;
		applyPoiVisibility();
		const set = entry ? highlightSetFor(entry) : null;
		const data = set
			? toHighlightFeatureCollection(set)
			: EMPTY_FEATURE_COLLECTION;
		const existing = map.getSource(HIGHLIGHT_SOURCE_ID) as
			| GeoJSONSource
			| undefined;
		if (existing) {
			existing.setData(data);
		} else {
			map.addSource(HIGHLIGHT_SOURCE_ID, { type: "geojson", data });
			map.addLayer({
				id: HIGHLIGHT_LAYER_ID,
				type: "circle",
				source: HIGHLIGHT_SOURCE_ID,
				paint: {
					// The target coordinate is the biggest, dark-ringed marker;
					// Mentions are smaller with a blue ring. Size + ring together
					// make the target unmistakable against any type fill colour.
					"circle-radius": [
						"match",
						["get", "role"],
						"target",
						13,
						/* mention */ 8,
					] as unknown as ExpressionSpecification,
					"circle-color": "#ffffff",
					"circle-opacity": 0,
					"circle-stroke-width": [
						"match",
						["get", "role"],
						"target",
						5,
						/* mention */ 3,
					] as unknown as ExpressionSpecification,
					"circle-stroke-color": [
						"match",
						["get", "role"],
						"target",
						"#111827",
						/* mention */ "#2563eb",
					] as unknown as ExpressionSpecification,
				},
			});
		}
		// Only reframe when there is something to frame; a cleared or empty set
		// must not yank the camera (route-map/CLAUDE.md rule 3 — honest rendering).
		if (set && refit) {
			fitToPois([...set.targets, ...set.mentions]);
		}
	}

	function wireInteractions(): void {
		// POIs are display-only (ADR-0004): a POI is never a selection target and
		// there is no popup. The only tap behaviour is that a Place-coordinate
		// marker selects its Place — the same door a sidebar click uses, so the
		// highlight + fit + detail panel fire for free. A mention-only / gazetteer
		// marker has no Place of its own, so its tap is inert — navigation is
		// one-directional (Entry → its POIs), never POI → Entries.
		// Map-level (not layer-delegated) so the query geometry is ours to widen.
		// On mobile the tap queries a padded box (TAP_TOLERANCE_PX); on desktop it
		// stays an exact-point query, i.e. the rendered circle disc as before.
		map.on("click", (event) => {
			const { x, y } = event.point;
			const onMobile = window.innerWidth <= MOBILE_BREAKPOINT;
			const geometry: PointLike | [PointLike, PointLike] = onMobile
				? [
						[x - TAP_TOLERANCE_PX, y - TAP_TOLERANCE_PX],
						[x + TAP_TOLERANCE_PX, y + TAP_TOLERANCE_PX],
					]
				: event.point;
			const features = map.queryRenderedFeatures(geometry, {
				layers: [POI_LAYER_ID],
			});
			// The box can catch several markers. Pick the nearest TAPPABLE (Place)
			// one to the tap point; inert mention-only markers are skipped (ADR-0004)
			// so a tap near a mention still reaches a Place within reach.
			let bestId: string | null = null;
			let bestDist = Number.POSITIVE_INFINITY;
			for (const feature of features) {
				const props = feature.properties as PoiFeatureProps;
				if (!props.isPlace || feature.geometry.type !== "Point") {
					continue;
				}
				const point = map.project(feature.geometry.coordinates as LngLatLike);
				const dist = (point.x - x) ** 2 + (point.y - y) ** 2;
				if (dist < bestDist) {
					bestDist = dist;
					bestId = props.id;
				}
			}
			if (!bestId) {
				return;
			}
			const place = entriesByPoiId
				.get(bestId)
				?.find((entry) => entry.kind === "place");
			if (place) {
				onSelectEntry(place);
			}
		});
		map.on("mouseenter", POI_LAYER_ID, () => {
			map.getCanvas().style.cursor = "pointer";
		});
		map.on("mouseleave", POI_LAYER_ID, () => {
			map.getCanvas().style.cursor = "";
		});
	}

	// Apply a pure CameraFrame as the opening view, shared by frameGuide and
	// frameOverview so the POI-extent and box-extent framings cannot drift on
	// padding, zoom cap, or the mobile bottom-sheet inset. A center frame (empty
	// set) eases with no area; a bounds frame fits snugly above the sheet. Camera
	// moves are safe before the style loads, so no whenStyleReady gate.
	function applyOpeningFrame(frame: CameraFrame): void {
		const bottomInset = bottomSheetInsetPx();
		if (frame.kind === "center") {
			// Empty set: center at a sensible zoom (never a zero-area box). Shift up
			// by half the obscured height so it lands above the mobile sheet. duration
			// 0 — the opening frame appears at once, no pan from the default view.
			map.easeTo({
				center: frame.center,
				zoom: frame.zoom,
				offset: [0, -bottomInset / 2],
				duration: 0,
			});
			return;
		}
		// The extent: fit with a snug padding kept above the sheet, capped so a
		// tight cluster does not slam to max zoom. animate:false so the opening
		// view snaps in rather than flying from the default.
		map.fitBounds(frame.bounds, {
			padding: {
				top: OPENING_FIT_PADDING,
				right: OPENING_FIT_PADDING,
				bottom: OPENING_FIT_PADDING + bottomInset,
				left: OPENING_FIT_PADDING,
			},
			maxZoom: FIT_MAX_ZOOM,
			animate: false,
		});
	}

	// Draw (or update) the Guide overview boxes. The fill/line layers are style
	// layers (wiped by a base-style install, so re-addable from currentGuideBoxes);
	// the labels are DOM markers, which survive an install — hence created once and
	// left in place on a re-render. Idempotent.
	function renderGuideBoxes(guides: Guide[]): void {
		const data = toGuideBoxFeatureCollection(guides);
		const existing = map.getSource(GUIDE_BOX_SOURCE_ID) as
			| GeoJSONSource
			| undefined;
		if (existing) {
			existing.setData(data);
		} else {
			map.addSource(GUIDE_BOX_SOURCE_ID, { type: "geojson", data });
			map.addLayer({
				id: GUIDE_BOX_FILL_LAYER_ID,
				type: "fill",
				source: GUIDE_BOX_SOURCE_ID,
				paint: {
					"fill-color": ["get", "color"] as unknown as ExpressionSpecification,
					// The hovered box fills more strongly so a row/box hover reads as one
					// picker (#141); the rest stay a light wash so the map shows through.
					"fill-opacity": [
						"case",
						["boolean", ["feature-state", "hover"], false],
						0.35,
						/* other */ 0.12,
					] as unknown as ExpressionSpecification,
				},
			});
			map.addLayer({
				id: GUIDE_BOX_LINE_LAYER_ID,
				type: "line",
				source: GUIDE_BOX_SOURCE_ID,
				paint: {
					"line-color": ["get", "color"] as unknown as ExpressionSpecification,
					"line-width": [
						"case",
						["boolean", ["feature-state", "hover"], false],
						4,
						/* other */ 2,
					] as unknown as ExpressionSpecification,
				},
			});
			if (!guideBoxInteractionsWired) {
				wireGuideBoxInteractions();
				guideBoxInteractionsWired = true;
			}
		}
		// DOM label markers, one per box, at the bbox centre. They persist across a
		// base-style install, so create them only when absent.
		if (guideBoxMarkers.size === 0) {
			for (const guide of guides) {
				const [south, west, north, east] = guide.bbox;
				const element = document.createElement("div");
				element.className = "guide-box-label";
				element.textContent = guide.name;
				const marker = new Marker({ element })
					.setLngLat([(west + east) / 2, (south + north) / 2])
					.addTo(map);
				guideBoxMarkers.set(guide.id, marker);
			}
		}
	}

	// Remove the overview boxes entirely — the DOM label markers plus the fill/line
	// layers and their source. Left clean for the entered Guide's POIs. Safe when
	// nothing is drawn.
	// Tear down the POI marker layer + peak labels + their shared source (#142), so
	// returning to the overview leaves no stale markers under the boxes. The peak
	// labels read POI_SOURCE_ID, so they come off before the source. Safe when the
	// layers/source were never added.
	function removePois(): void {
		for (const id of [PEAK_LABEL_LAYER_ID, POI_LAYER_ID]) {
			if (map.getLayer(id)) {
				map.removeLayer(id);
			}
		}
		if (map.getSource(POI_SOURCE_ID)) {
			map.removeSource(POI_SOURCE_ID);
		}
	}

	function removeGuideBoxes(): void {
		for (const marker of guideBoxMarkers.values()) {
			marker.remove();
		}
		guideBoxMarkers.clear();
		for (const id of [GUIDE_BOX_LINE_LAYER_ID, GUIDE_BOX_FILL_LAYER_ID]) {
			if (map.getLayer(id)) {
				map.removeLayer(id);
			}
		}
		if (map.getSource(GUIDE_BOX_SOURCE_ID)) {
			map.removeSource(GUIDE_BOX_SOURCE_ID);
		}
		hoveredBoxId = null;
	}

	// Emphasize one box by guide id (or clear with null) via feature-state on the
	// fill/line paint and a class on the label marker. The single door for both a
	// row hover (App → highlightGuideBox) and a box hover (the mousemove handler),
	// so the list and the map stay in sync. A no-op on the boxes when the source is
	// gone; the marker class is still cleared.
	function applyGuideBoxHover(guideId: string | null): void {
		const hasSource = map.getSource(GUIDE_BOX_SOURCE_ID) !== undefined;
		if (hoveredBoxId && hoveredBoxId !== guideId) {
			if (hasSource) {
				map.setFeatureState(
					{ source: GUIDE_BOX_SOURCE_ID, id: hoveredBoxId },
					{ hover: false },
				);
			}
			guideBoxMarkers
				.get(hoveredBoxId)
				?.getElement()
				.classList.remove("guide-box-label--hovered");
		}
		if (guideId) {
			if (hasSource) {
				map.setFeatureState(
					{ source: GUIDE_BOX_SOURCE_ID, id: guideId },
					{ hover: true },
				);
			}
			guideBoxMarkers
				.get(guideId)
				?.getElement()
				.classList.add("guide-box-label--hovered");
		}
		hoveredBoxId = guideId;
	}

	// Wire the overview boxes' click + hover once (layer-scoped handlers survive a
	// style install and re-created layer, so re-wiring would stack duplicates). A
	// box click picks that Guide through the construction callback (the same door
	// the sidebar Guide list uses); hover drives the emphasis and tells App which
	// row to light up. Boxes are never a selection (ADR-0004).
	function wireGuideBoxInteractions(): void {
		map.on("click", GUIDE_BOX_FILL_LAYER_ID, (event) => {
			const feature = event.features?.[0];
			if (!feature) {
				return;
			}
			onSelectGuide((feature.properties as GuideBoxFeatureProps).id);
		});
		map.on("mousemove", GUIDE_BOX_FILL_LAYER_ID, (event) => {
			map.getCanvas().style.cursor = "pointer";
			const feature = event.features?.[0];
			if (!feature) {
				return;
			}
			const { id } = feature.properties as GuideBoxFeatureProps;
			if (id !== hoveredBoxId) {
				applyGuideBoxHover(id);
				onHoverGuide(id);
			}
		});
		map.on("mouseleave", GUIDE_BOX_FILL_LAYER_ID, () => {
			map.getCanvas().style.cursor = "";
			applyGuideBoxHover(null);
			onHoverGuide(null);
		});
	}

	return {
		showPois(
			pois: Poi[],
			index: Map<string, Entry[]>,
			placeIds: Set<string>,
		): void {
			entriesByPoiId = index;
			placePoiIds = placeIds;
			pendingPois = pois;
			// Retain the set so it can be re-rendered after a base-map swap (setStyle
			// wipes the runtime POI layer).
			currentPois = pois;
			whenStyleReady(() => {
				if (pendingPois) {
					renderPois(pendingPois);
					pendingPois = null;
				}
			});
		},
		clearPois(): void {
			// Drop any buffered/retained set so neither a late whenStyleReady flush
			// nor a base-style reinstall (onCombinedReady repaints currentPois)
			// repopulates the layer after this clear.
			pendingPois = null;
			currentPois = null;
			whenStyleReady(() => removePois());
		},
		highlightEntry(entry: Entry | null): void {
			pendingHighlight = entry;
			hasPendingHighlight = true;
			whenStyleReady(() => {
				if (hasPendingHighlight) {
					renderHighlight(pendingHighlight);
					pendingHighlight = null;
					hasPendingHighlight = false;
				}
			});
		},
		setTerrain(enabled: boolean): void {
			terrainEnabled = enabled;
			// Before the combined style is in, both base maps do not yet exist to
			// flip between; buffer the desired state — onCombinedReady applies the
			// latest terrainEnabled once it lands. After that, a toggle is a pure
			// visibility flip + terrain + pitch, with no setStyle.
			if (!combinedInstalled) {
				return;
			}
			whenStyleReady(() => applyMode(terrainEnabled));
		},
		frameGuide(pois: Poi[]): void {
			// The opening view is derived from the POI set (boundsForPois, pure),
			// then applied here with the mobile bottom-sheet inset — the map keeps
			// its maplibre-gl behind this module (route-map/CLAUDE.md rule 4).
			applyOpeningFrame(boundsForPois(pois));
		},
		showGuideBoxes(guides: Guide[]): void {
			// Retain the set so the fill/line layers can be re-added after a base
			// style install wipes them (renderGuideBoxes keeps the DOM markers).
			currentGuideBoxes = guides;
			whenStyleReady(() => {
				if (currentGuideBoxes) {
					renderGuideBoxes(currentGuideBoxes);
				}
			});
		},
		clearGuideBoxes(): void {
			currentGuideBoxes = null;
			whenStyleReady(() => removeGuideBoxes());
		},
		highlightGuideBox(guideId: string | null): void {
			applyGuideBoxHover(guideId);
		},
		frameOverview(guides: Guide[]): void {
			// The overview opening view fits every Guide's box (boundsForGuideBoxes,
			// pure), applied through the same door as frameGuide.
			applyOpeningFrame(boundsForGuideBoxes(guides));
		},
		destroy() {
			for (const marker of guideBoxMarkers.values()) {
				marker.remove();
			}
			map.remove();
		},
	};
}
