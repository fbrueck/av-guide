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
import { WETTERSTEIN_BOUNDS } from "./view";

const POI_SOURCE_ID = "pois";
const POI_LAYER_ID = "poi-markers";

// A dedicated emphasis source/layer drawn ON TOP of the base poi-markers so a
// selected Entry's linked POI set stands out without redrawing the base
// (route-map/CLAUDE.md rule 3: rendering a Route = highlighting its POI set,
// never a polyline). Feature `role` drives a data-driven paint so the target
// coordinate (a Route's Anchor POIs, or a Place's own POI) is tell-apart-able
// from Mentions at a glance.
const HIGHLIGHT_SOURCE_ID = "entry-highlight";
const HIGHLIGHT_LAYER_ID = "entry-highlight-markers";

// Camera framing for the single-point case (most Entries — an Anchor-only Route
// or a Place with just its own POI). A degenerate zero-area bounds would
// over-zoom, so we ease to the point at a sensible massif zoom.
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
// UI components never touch maplibre-gl directly.
export interface RouteMap {
	/** Render the guide's POIs as typed markers on the basemap. Place POIs (the
	 *  coordinate of a Place, `placePoiIds`) are the **primary** markers — drawn
	 *  larger with a dark ring — so the place-first model reads at a glance;
	 *  mention-only / gazetteer POIs recede. Also supply the poi_id ->
	 *  referencing-Entries index the popup cross-links read. All three arrive with
	 *  the data (from the loaded GuideData), so they are passed here rather than at
	 *  construction. Idempotent — calling again replaces the rendered set. */
	showPois(
		pois: Poi[],
		entriesByPoiId: Map<string, Entry[]>,
		placePoiIds: Set<string>,
	): void;
	/** Emphasize a selected Entry's linked POI set (#44): the target coordinate
	 *  (a Route's Anchor POIs, or a Place's own POI) styled distinctly from the
	 *  Mentions on top of the base markers, then fit the camera to the set.
	 *  Passing `null` clears the highlight. Honest by design: an empty POI set
	 *  draws nothing and leaves the camera put — a Route has no geometry, so
	 *  nothing is invented (route-map/CLAUDE.md rule 3). Idempotent and safe to
	 *  call before the style loads. */
	highlightEntry(entry: Entry | null): void;
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
	/** Whether this POI is a Place's resolved coordinate — a primary marker. */
	isPlace: boolean;
}

function escapeHtml(value: string): string {
	return value
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

// Popup body = POI identity + a link to verify the match on openstreetmap.org
// (#21 AC) + the Entries referencing this POI as clickable cross-links (#44).
// Built as a real DOM element (returned to setDOMContent, not setHTML) so each
// Entry can carry a live click handler that calls back into React via
// onSelectEntry — a string popup could not carry safe handlers. This is the one
// place popup content is built.
function buildPoiPopupElement(
	props: PoiFeatureProps,
	entries: Entry[],
	onSelectEntry: (entry: Entry) => void,
	onNavigate: () => void,
): HTMLElement {
	const root = document.createElement("div");
	root.className = "poi-popup";

	const name = props.name || "(unnamed POI)";
	const type = props.type || "—";
	const ele = props.ele != null ? `${Math.round(props.ele)} m` : "keine Angabe";

	// Identity block + OSM verify link is static, so an escaped HTML string stays
	// the readable option here; the interactive Entry list below is real DOM.
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

	root.appendChild(buildEntryCrossLinks(entries, onSelectEntry, onNavigate));
	return root;
}

// The cross-link section: the Entries that reference this POI — a Place whose
// coordinate it is, or any Entry that Mentions it (via entriesByPoiId). Each is
// a button whose click selects the Entry through the SAME handler a sidebar
// click uses, so the highlight + fit + detail panel all fire for free. A POI no
// Entry names (possible for gazetteer POIs) shows an honest empty line.
function buildEntryCrossLinks(
	entries: Entry[],
	onSelectEntry: (entry: Entry) => void,
	onNavigate: () => void,
): HTMLElement {
	const section = document.createElement("div");
	section.className = "poi-popup__entries";

	if (entries.length === 0) {
		const empty = document.createElement("p");
		empty.className = "poi-popup__entries-empty";
		empty.textContent = "Kein Eintrag nennt diesen POI.";
		section.appendChild(empty);
		return section;
	}

	const title = document.createElement("p");
	title.className = "poi-popup__entries-title";
	title.textContent = `Einträge zu diesem POI (${entries.length})`;
	section.appendChild(title);

	const list = document.createElement("ul");
	list.className = "poi-popup__entries-list";
	for (const entry of entries) {
		const item = document.createElement("li");
		const button = document.createElement("button");
		button.type = "button";
		button.className = "poi-popup__entry";

		const entryName = document.createElement("span");
		entryName.className = "poi-popup__entry-name";
		// textContent escapes for free — no manual escaping needed on DOM nodes.
		entryName.textContent = entry.name;
		button.appendChild(entryName);

		const meta = document.createElement("span");
		meta.className = "poi-popup__entry-meta";
		const kind = document.createElement("span");
		kind.textContent = entry.kind === "place" ? "Ort" : "Route";
		const detail = document.createElement("span");
		detail.className = "poi-popup__entry-grade";
		detail.textContent =
			entry.kind === "place"
				? (entry.placeType ?? "—")
				: (entry.grade ?? entry.peak ?? "—");
		meta.append(kind, detail);
		button.appendChild(meta);

		button.addEventListener("click", () => {
			onSelectEntry(entry);
			onNavigate();
		});
		item.appendChild(button);
		list.appendChild(item);
	}
	section.appendChild(list);
	return section;
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
				name: poi.name,
				type: poi.type,
				ele: poi.ele,
				osmUrl: poi.osmUrl,
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

// The Entry's POI set (route-map/CLAUDE.md rule 3): the target coordinate first
// (role "anchor" — a Route's Anchor Places' POIs, or a Place's own POI), then
// its Mentions (role "mention"). The paint uses `role` to tell the target apart
// from the places the prose passes through. Anchor coordinates are transitive
// via the Place — never a direct Entry->POI link.
type PoiRole = "anchor" | "mention";

interface HighlightSet {
	anchors: Poi[];
	mentions: Poi[];
}

function highlightSetFor(entry: Entry): HighlightSet {
	if (entry.kind === "route") {
		const anchors: Poi[] = [];
		for (const anchor of entry.anchors) {
			if (anchor.poi) {
				anchors.push(anchor.poi);
			}
		}
		return { anchors, mentions: entry.mentions };
	}
	// A Place's own POI is its target coordinate; its Übersicht Mentions ride
	// along styled as mentions.
	return {
		anchors: entry.poi ? [entry.poi] : [],
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
	for (const poi of set.anchors) {
		push(poi, "anchor");
	}
	for (const poi of set.mentions) {
		push(poi, "mention");
	}
	return { type: "FeatureCollection", features };
}

// Options passed at construction (before the guide data loads). onSelectEntry is
// App's single selection entry point (a stable useCallback), so an Entry clicked
// in a POI popup selects it identically to a sidebar click — the map never owns
// selection, it just calls back (route-map/CLAUDE.md rule 4).
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
		// Add the attribution control explicitly (compact: false) so the OSM +
		// OpenTopoMap credits are always visible, not hidden behind a toggle.
		attributionControl: false,
	});

	map.addControl(new AttributionControl({ compact: false }), "bottom-right");
	map.addControl(new NavigationControl(), "top-right");
	map.addControl(new ScaleControl(), "bottom-left");

	let popup: Popup | null = null;
	// The poi_id -> referencing-Entries index the popup reads, supplied with the
	// POIs via showPois (both come from the loaded GuideData). Empty until then;
	// a click before data loads simply finds no cross-links.
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

	function renderHighlight(entry: Entry | null): void {
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
		if (set) {
			fitToPois([...set.anchors, ...set.mentions]);
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
			const referencingEntries = entriesByPoiId.get(props.id) ?? [];
			// Place POIs are the primary markers: clicking one selects that Place
			// directly (its detail panel carries the OSM-verify link + routes
			// leading here), per the spec's "selecting a Place selects it". A
			// mention-only / gazetteer POI has no Place of its own, so it opens the
			// cross-link popup instead — the Entries that name it.
			if (props.isPlace) {
				const place = referencingEntries.find((e) => e.kind === "place");
				if (place) {
					onSelectEntry(place);
					return;
				}
			}
			popup = new Popup({ offset: 10, closeButton: true })
				.setLngLat([lon, lat])
				.setDOMContent(
					buildPoiPopupElement(props, referencingEntries, onSelectEntry, () =>
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
		showPois(
			pois: Poi[],
			index: Map<string, Entry[]>,
			placeIds: Set<string>,
		): void {
			entriesByPoiId = index;
			placePoiIds = placeIds;
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
		highlightEntry(entry: Entry | null): void {
			if (map.isStyleLoaded()) {
				renderHighlight(entry);
			} else {
				pendingHighlight = entry;
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
