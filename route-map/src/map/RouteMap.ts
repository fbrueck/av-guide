import type { FeatureCollection } from "geojson";
import {
	AttributionControl,
	type ExpressionSpecification,
	type GeoJSONSource,
	LngLatBounds,
	Map as MapLibreMap,
	NavigationControl,
	Popup,
	ScaleControl,
} from "maplibre-gl";
import type { Poi, Route } from "../domain";
import {
	BASEMAP_MAX_ZOOM,
	TERRAIN_EXAGGERATION,
	TERRAIN_PITCH,
	TERRAIN_SOURCE_ID,
	terrainSource,
	topoBasemapStyle,
} from "./basemap";
import { poiColorExpression } from "./poiStyle";
import { WETTERSTEIN_BOUNDS } from "./view";

const POI_SOURCE_ID = "pois";
const POI_LAYER_ID = "poi-markers";

// A dedicated emphasis source/layer drawn ON TOP of the base poi-markers so a
// selected Route's linked POI set stands out without redrawing the base
// (route-map/CLAUDE.md rule 3: rendering a Route = highlighting its POI set,
// never a polyline). Feature `role` drives a data-driven paint so the Anchor is
// tell-apart-able from Mentions at a glance.
const HIGHLIGHT_SOURCE_ID = "route-highlight";
const HIGHLIGHT_LAYER_ID = "route-highlight-markers";

// Camera framing for the single-point case (Anchor-only Routes — most of them,
// since mention extraction covers ~20 of 738 Routes). A degenerate zero-area
// bounds would over-zoom, so we ease to the point at a sensible massif zoom.
const SINGLE_POINT_ZOOM = 14;
// Fit padding + a ceiling so a tight multi-POI cluster does not slam to max zoom.
const FIT_PADDING = 64;
const FIT_MAX_ZOOM = 15;

const EMPTY_FEATURE_COLLECTION: FeatureCollection = {
	type: "FeatureCollection",
	features: [],
};

// The single owner of the maplibre-gl Map instance (route-map/CLAUDE.md
// rule 4). It is created imperatively and hidden behind this small typed API;
// UI components never touch maplibre-gl directly. Later tickets grow this
// interface (highlightPois, fitTo, setTerrain, …).
export interface RouteMap {
	/** Render the guide's POIs as typed markers on the basemap, and supply the
	 *  poi_id -> referencing-Routes index the popup cross-links read (#25). The
	 *  index arrives with the data (both come from the loaded GuideData), so it is
	 *  passed here rather than at construction. Idempotent — calling again
	 *  replaces the rendered set and the index. */
	showPois(pois: Poi[], routesByPoiId: Map<string, Route[]>): void;
	/** Emphasize a selected Route's linked POI set (#24): highlight the Anchor
	 *  distinctly from the Mentions on top of the base markers, then fit the
	 *  camera to the set. Passing `null` clears the highlight. Honest by design:
	 *  an empty POI set draws nothing and leaves the camera put — a Route has no
	 *  geometry, so nothing is invented (route-map/CLAUDE.md rule 3). Idempotent
	 *  and safe to call before the style loads. */
	highlightRoute(route: Route | null): void;
	/** Flip the map between the flat 2D basemap and 3D terrain (#23). On enable
	 *  the Mapterhorn raster-dem source is draped under the basemap and the
	 *  camera pitches up; on disable the terrain is cleared and the camera
	 *  returns to flat. Idempotent and safe to call before the style loads. */
	setTerrain(enabled: boolean): void;
	destroy(): void;
}

// The GeoJSON feature properties the POI layer + popup read. Kept flat and
// primitive because maplibre only carries JSON-serialisable feature properties.
interface PoiFeatureProps {
	id: string;
	name: string;
	type: string;
	ele: number | null;
	osmUrl: string;
}

function escapeHtml(value: string): string {
	return value
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

// Popup body = POI identity + a link to verify the match on openstreetmap.org
// (#21 AC) + the Routes referencing this POI as clickable cross-links (#25 AC).
// Built as a real DOM element (returned to setDOMContent, not setHTML) so each
// Route entry can carry a live click handler that calls back into React via
// onSelectRoute — a string popup could not carry safe handlers. This is the one
// place popup content is built.
function buildPoiPopupElement(
	props: PoiFeatureProps,
	routes: Route[],
	onSelectRoute: (route: Route) => void,
	onNavigate: () => void,
): HTMLElement {
	const root = document.createElement("div");
	root.className = "poi-popup";

	const name = props.name || "(unnamed POI)";
	const type = props.type || "—";
	const ele = props.ele != null ? `${Math.round(props.ele)} m` : "keine Angabe";

	// Identity block + OSM verify link is static, so an escaped HTML string stays
	// the readable option here; the interactive Route list below is real DOM.
	root.innerHTML = `
		<strong class="poi-popup__name">${escapeHtml(name)}</strong>
		<dl class="poi-popup__meta">
			<div><dt>Typ</dt><dd>${escapeHtml(type)}</dd></div>
			<div><dt>Höhe</dt><dd>${escapeHtml(ele)}</dd></div>
		</dl>
		<a class="poi-popup__osm" href="${escapeHtml(props.osmUrl)}" target="_blank" rel="noopener noreferrer">
			Auf OpenStreetMap prüfen ↗
		</a>
	`;

	root.appendChild(buildRouteCrossLinks(routes, onSelectRoute, onNavigate));
	return root;
}

// The #25 cross-link section: the Routes that reference this POI (Anchor or
// Mention, via routesByPoiId). Each is a button whose click selects the Route
// through the SAME handler a sidebar click uses, so the #24 highlight + fit +
// RouteDetail all fire for free. A POI no Route names (possible for gazetteer
// POIs) shows an honest empty line, never a blank section.
function buildRouteCrossLinks(
	routes: Route[],
	onSelectRoute: (route: Route) => void,
	onNavigate: () => void,
): HTMLElement {
	const section = document.createElement("div");
	section.className = "poi-popup__routes";

	if (routes.length === 0) {
		const empty = document.createElement("p");
		empty.className = "poi-popup__routes-empty";
		empty.textContent = "Keine Routen nennen diesen POI.";
		section.appendChild(empty);
		return section;
	}

	const title = document.createElement("p");
	title.className = "poi-popup__routes-title";
	title.textContent = `Routen, die diesen POI nennen (${routes.length})`;
	section.appendChild(title);

	const list = document.createElement("ul");
	list.className = "poi-popup__routes-list";
	for (const route of routes) {
		const item = document.createElement("li");
		const button = document.createElement("button");
		button.type = "button";
		button.className = "poi-popup__route";

		const routeName = document.createElement("span");
		routeName.className = "poi-popup__route-name";
		// textContent escapes for free — no manual escaping needed on DOM nodes.
		routeName.textContent = route.name;
		button.appendChild(routeName);

		const meta = document.createElement("span");
		meta.className = "poi-popup__route-meta";
		const peak = document.createElement("span");
		peak.textContent = route.peak ?? "—";
		const grade = document.createElement("span");
		grade.className = "poi-popup__route-grade";
		grade.textContent = route.grade ?? "—";
		meta.append(peak, grade);
		button.appendChild(meta);

		button.addEventListener("click", () => {
			onSelectRoute(route);
			onNavigate();
		});
		item.appendChild(button);
		list.appendChild(item);
	}
	section.appendChild(list);
	return section;
}

function toFeatureCollection(pois: Poi[]): FeatureCollection {
	return {
		type: "FeatureCollection",
		features: pois.map((poi) => {
			const props: PoiFeatureProps = {
				id: poi.id,
				name: poi.name,
				type: poi.type,
				ele: poi.ele,
				osmUrl: poi.osmUrl,
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

// The Route's POI set (route-map/CLAUDE.md rule 3): the Anchor first (if
// resolved), then its Mentions. Each feature carries a `role` so the paint can
// tell the target summit from the places the prose passes through.
type PoiRole = "anchor" | "mention";

function toHighlightFeatureCollection(route: Route): FeatureCollection {
	const features: FeatureCollection["features"] = [];
	const push = (poi: Poi, role: PoiRole) => {
		features.push({
			type: "Feature",
			id: `${role}:${poi.id}`,
			geometry: { type: "Point", coordinates: poi.coordinates },
			properties: { role },
		});
	};
	if (route.anchor) {
		push(route.anchor, "anchor");
	}
	for (const mention of route.mentions) {
		push(mention, "mention");
	}
	return { type: "FeatureCollection", features };
}

// Options passed at construction (before the guide data loads). onSelectRoute is
// App's single selection entry point (a stable useCallback), so a Route clicked
// in a POI popup selects it identically to a sidebar click — the map never owns
// selection, it just calls back (route-map/CLAUDE.md rule 4).
export interface CreateRouteMapOptions {
	onSelectRoute: (route: Route) => void;
}

export function createRouteMap(
	container: HTMLElement,
	{ onSelectRoute }: CreateRouteMapOptions,
): RouteMap {
	const map = new MapLibreMap({
		container,
		style: topoBasemapStyle,
		bounds: WETTERSTEIN_BOUNDS,
		fitBoundsOptions: { padding: 32 },
		maxZoom: BASEMAP_MAX_ZOOM,
		// Add the attribution control explicitly (compact: false) so the OSM +
		// OpenTopoMap credits are always visible, not hidden behind a toggle.
		attributionControl: false,
	});

	map.addControl(new AttributionControl({ compact: false }), "bottom-right");
	map.addControl(new NavigationControl(), "top-right");
	map.addControl(new ScaleControl(), "bottom-left");

	let popup: Popup | null = null;
	// The poi_id -> referencing-Routes index the popup reads, supplied with the
	// POIs via showPois (both come from the loaded GuideData). Empty until then;
	// a click before data loads simply finds no cross-links.
	let routesByPoiId: Map<string, Route[]> = new Map();
	// showPois may run before the style has loaded (data fetch races map init);
	// buffer the latest set and flush it once the style is ready.
	let pendingPois: Poi[] | null = null;
	// highlightRoute has the same race (a route can be pre-selected before load).
	// Buffer the latest requested selection; `null` means "clear". We track
	// whether a highlight request is pending separately from its value so a
	// buffered clear is distinguishable from "no request yet".
	let pendingHighlight: Route | null = null;
	let hasPendingHighlight = false;
	// setTerrain has the same race; buffer the latest desired state and apply it
	// on load. Track the applied state so re-adding the source stays idempotent.
	let terrainEnabled = false;

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
		const data = toFeatureCollection(pois);
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
				"circle-radius": 6,
				"circle-color":
					poiColorExpression() as unknown as ExpressionSpecification,
				"circle-stroke-width": 1.5,
				"circle-stroke-color": "#ffffff",
			},
		});
		wireInteractions();
	}

	// Ease/fit the camera to the highlighted POI set. Single point (Anchor-only
	// Routes) eases to a sensible zoom rather than a degenerate zero-area bounds;
	// an empty set leaves the camera where it is (nothing to frame).
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

	function renderHighlight(route: Route | null): void {
		const data = route
			? toHighlightFeatureCollection(route)
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
					// Anchor is the biggest, dark-ringed marker (the target summit);
					// Mentions are smaller with a white ring. Size + ring together
					// make the Anchor unmistakable against any type fill colour.
					"circle-radius": [
						"match",
						["get", "role"],
						"anchor",
						13,
						/* mention */ 8,
					] as unknown as ExpressionSpecification,
					"circle-color": "#ffffff",
					"circle-opacity": 0,
					"circle-stroke-width": [
						"match",
						["get", "role"],
						"anchor",
						5,
						/* mention */ 3,
					] as unknown as ExpressionSpecification,
					"circle-stroke-color": [
						"match",
						["get", "role"],
						"anchor",
						"#111827",
						/* mention */ "#2563eb",
					] as unknown as ExpressionSpecification,
				},
			});
		}
		// Only reframe when there is something to frame; a cleared or empty set
		// must not yank the camera (route-map/CLAUDE.md rule 3 — honest rendering).
		if (route) {
			const set = route.anchor
				? [route.anchor, ...route.mentions]
				: route.mentions;
			fitToPois(set);
		}
	}

	function wireInteractions(): void {
		map.on("click", POI_LAYER_ID, (event) => {
			const feature = event.features?.[0];
			if (!feature) {
				return;
			}
			const props = feature.properties as PoiFeatureProps;
			const geometry = feature.geometry;
			if (geometry.type !== "Point") {
				return;
			}
			const [lon, lat] = geometry.coordinates as [number, number];
			popup?.remove();
			const referencingRoutes = routesByPoiId.get(props.id) ?? [];
			popup = new Popup({ offset: 10, closeButton: true })
				.setLngLat([lon, lat])
				.setDOMContent(
					buildPoiPopupElement(props, referencingRoutes, onSelectRoute, () =>
						popup?.remove(),
					),
				)
				.addTo(map);
		});
		map.on("mouseenter", POI_LAYER_ID, () => {
			map.getCanvas().style.cursor = "pointer";
		});
		map.on("mouseleave", POI_LAYER_ID, () => {
			map.getCanvas().style.cursor = "";
		});
	}

	return {
		showPois(pois: Poi[], index: Map<string, Route[]>): void {
			routesByPoiId = index;
			if (map.isStyleLoaded()) {
				renderPois(pois);
			} else {
				pendingPois = pois;
				map.once("load", () => {
					if (pendingPois) {
						renderPois(pendingPois);
						pendingPois = null;
					}
				});
			}
		},
		highlightRoute(route: Route | null): void {
			if (map.isStyleLoaded()) {
				renderHighlight(route);
			} else {
				pendingHighlight = route;
				hasPendingHighlight = true;
				map.once("load", () => {
					if (hasPendingHighlight) {
						renderHighlight(pendingHighlight);
						pendingHighlight = null;
						hasPendingHighlight = false;
					}
				});
			}
		},
		setTerrain(enabled: boolean): void {
			terrainEnabled = enabled;
			if (map.isStyleLoaded()) {
				applyTerrain(enabled);
			} else {
				map.once("load", () => {
					applyTerrain(terrainEnabled);
				});
			}
		},
		destroy() {
			popup?.remove();
			map.remove();
		},
	};
}
