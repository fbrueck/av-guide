import type { FeatureCollection } from "geojson";
import {
	AttributionControl,
	type ExpressionSpecification,
	type FilterSpecification,
	type GeoJSONSource,
	LngLatBounds,
	Map as MapLibreMap,
	NavigationControl,
	ScaleControl,
} from "maplibre-gl";
import type { Entry, Poi } from "../domain";
import {
	BASEMAP_MAX_ZOOM,
	TERRAIN_EXAGGERATION,
	TERRAIN_PITCH,
	TERRAIN_SOURCE_ID,
	terrainSource,
	topoBasemapStyle,
} from "./basemap";
import { poiColorExpression } from "./poiStyle";
import {
	type PoiVisibilityFeature,
	poiVisibilityFilter,
} from "./poiVisibility";
import { WETTERSTEIN_BOUNDS } from "./view";

const POI_SOURCE_ID = "pois";
const POI_LAYER_ID = "poi-markers";

// A dedicated emphasis source/layer drawn ON TOP of the base poi-markers so a
// selected Entry's linked POI set stands out without redrawing the base
// (route-map/CLAUDE.md rule 3: rendering a Route = highlighting its POI set,
// never a polyline). Feature `role` drives a data-driven paint so the target
// coordinates (a Route's Destination + places' POIs, or a Place's own POI) are
// tell-apart-able from Mentions at a glance.
const HIGHLIGHT_SOURCE_ID = "entry-highlight";
const HIGHLIGHT_LAYER_ID = "entry-highlight-markers";

// Camera framing for the single-point case (most Entries — a Route with just its
// Destination, or a Place with just its own POI). A degenerate zero-area bounds would
// over-zoom, so we ease to the point at a sensible massif zoom.
const SINGLE_POINT_ZOOM = 14;
// Fit padding + a ceiling so a tight multi-POI cluster does not slam to max zoom.
const FIT_PADDING = 64;
const FIT_MAX_ZOOM = 15;

// Mirrors the single `max-width: 768px` CSS breakpoint (route-map/CLAUDE.md
// rule 8) so the maplibre controls constructed here agree with the responsive
// layout. Not a second breakpoint — the CSS query stays the sole one; this only
// lets the imperative map read the same threshold at construction.
const MOBILE_BREAKPOINT = 768;

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
	/** Flip the map between the flat 2D basemap and 3D terrain (#23). On enable
	 *  the Mapterhorn raster-dem source is draped under the basemap and the
	 *  camera pitches up; on disable the terrain is cleared and the camera
	 *  returns to flat. Idempotent and safe to call before the style loads. */
	setTerrain(enabled: boolean): void;
	destroy(): void;
}

// The GeoJSON feature properties the POI layer reads. Kept flat and primitive
// because maplibre only carries JSON-serialisable feature properties. `type`
// drives the data-driven colour paint; `id`/`isPlace` (from PoiVisibilityFeature,
// the single source of truth for the base-layer shape) drive the visibility
// filter and the display-only tap → Place resolution (ADR-0004).
interface PoiFeatureProps extends PoiVisibilityFeature {
	type: string;
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

// Options passed at construction (before the guide data loads). onSelectEntry is
// App's single selection entry point (a stable useCallback), so a tapped
// Place-coordinate marker selects its Place identically to a sidebar click — the
// map never owns selection, it just calls back (route-map/CLAUDE.md rule 4).
export interface CreateRouteMapOptions {
	onSelectEntry: (entry: Entry) => void;
}

export function createRouteMap(
	container: HTMLElement,
	{ onSelectEntry }: CreateRouteMapOptions,
): RouteMap {
	const map = new MapLibreMap({
		container,
		style: topoBasemapStyle,
		bounds: WETTERSTEIN_BOUNDS,
		fitBoundsOptions: { padding: 32 },
		maxZoom: BASEMAP_MAX_ZOOM,
		// Add the attribution control explicitly (below) so we control its compact
		// mode per viewport rather than take the map default.
		attributionControl: false,
	});

	// Attribution compactness is fixed at construction (maplibre reads it once),
	// so we pick it from the viewport width here — approach (a) of #103. On mobile
	// (≤768px) the control renders MapLibre's compact `ⓘ` toggle so the credits do
	// not steal map space or hide behind the bottom sheet; the OSM + OpenTopoMap
	// (CC-BY-SA) + Mapterhorn credits stay reachable one tap behind the `ⓘ`. Above
	// the breakpoint `compact: false` keeps the full, always-visible attribution
	// desktop has always had — license compliance holds in both modes.
	const compactAttribution = window.innerWidth <= MOBILE_BREAKPOINT;
	map.addControl(
		new AttributionControl({ compact: compactAttribution }),
		"bottom-right",
	);
	map.addControl(new NavigationControl(), "top-right");
	map.addControl(new ScaleControl(), "bottom-left");

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
	// on load. Track the applied state so re-adding the source stays idempotent.
	let terrainEnabled = false;

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

	function applyTerrain(enabled: boolean): void {
		if (enabled) {
			if (!map.getSource(TERRAIN_SOURCE_ID)) {
				map.addSource(TERRAIN_SOURCE_ID, terrainSource);
			}
			map.setTerrain({
				source: TERRAIN_SOURCE_ID,
				exaggeration: TERRAIN_EXAGGERATION,
			});
			map.easeTo({ pitch: TERRAIN_PITCH });
		} else {
			map.setTerrain(null);
			map.easeTo({ pitch: 0 });
		}
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
		wireInteractions();
	}

	// Ease/fit the camera to the highlighted POI set. Single point eases to a
	// sensible zoom rather than a degenerate zero-area bounds; an empty set leaves
	// the camera where it is (nothing to frame).
	function fitToPois(pois: Poi[]): void {
		const [first, ...rest] = pois;
		if (!first) {
			return;
		}
		if (rest.length === 0) {
			map.easeTo({ center: first.coordinates, zoom: SINGLE_POINT_ZOOM });
			return;
		}
		const bounds = new LngLatBounds();
		for (const poi of pois) {
			bounds.extend(poi.coordinates);
		}
		map.fitBounds(bounds, { padding: FIT_PADDING, maxZoom: FIT_MAX_ZOOM });
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

	function renderHighlight(entry: Entry | null): void {
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
		if (set) {
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
		map.on("click", POI_LAYER_ID, (event) => {
			const feature = event.features?.[0];
			if (!feature) {
				return;
			}
			const props = feature.properties as PoiFeatureProps;
			if (!props.isPlace) {
				return;
			}
			const place = entriesByPoiId
				.get(props.id)
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

	return {
		showPois(
			pois: Poi[],
			index: Map<string, Entry[]>,
			placeIds: Set<string>,
		): void {
			entriesByPoiId = index;
			placePoiIds = placeIds;
			pendingPois = pois;
			whenStyleReady(() => {
				if (pendingPois) {
					renderPois(pendingPois);
					pendingPois = null;
				}
			});
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
			whenStyleReady(() => {
				applyTerrain(terrainEnabled);
			});
		},
		destroy() {
			map.remove();
		},
	};
}
