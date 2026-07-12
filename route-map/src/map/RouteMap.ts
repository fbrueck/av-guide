import type { FeatureCollection } from "geojson";
import {
	AttributionControl,
	type ExpressionSpecification,
	type GeoJSONSource,
	Map as MapLibreMap,
	NavigationControl,
	Popup,
	ScaleControl,
} from "maplibre-gl";
import type { Poi } from "../domain";
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

// The single owner of the maplibre-gl Map instance (route-map/CLAUDE.md
// rule 4). It is created imperatively and hidden behind this small typed API;
// UI components never touch maplibre-gl directly. Later tickets grow this
// interface (highlightPois, fitTo, setTerrain, …).
export interface RouteMap {
	/** Render the guide's POIs as typed markers on the basemap. Idempotent —
	 *  calling again replaces the rendered set. */
	showPois(pois: Poi[]): void;
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
// (#21 AC). Isolated so #25 can extend it with the Routes referencing this POI
// (see routesByPoiId) and make them clickable via an onSelectRoute callback —
// the seam is here: this function is the only place popup HTML is built.
function poiPopupHtml(props: PoiFeatureProps): string {
	const name = escapeHtml(props.name || "(unnamed POI)");
	const type = escapeHtml(props.type || "—");
	const ele = props.ele != null ? `${Math.round(props.ele)} m` : "keine Angabe";
	const osmUrl = escapeHtml(props.osmUrl);
	return `
		<div class="poi-popup">
			<strong class="poi-popup__name">${name}</strong>
			<dl class="poi-popup__meta">
				<div><dt>Typ</dt><dd>${type}</dd></div>
				<div><dt>Höhe</dt><dd>${ele}</dd></div>
			</dl>
			<a class="poi-popup__osm" href="${osmUrl}" target="_blank" rel="noopener noreferrer">
				Auf OpenStreetMap prüfen ↗
			</a>
		</div>
	`;
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

export function createRouteMap(container: HTMLElement): RouteMap {
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
	// showPois may run before the style has loaded (data fetch races map init);
	// buffer the latest set and flush it once the style is ready.
	let pendingPois: Poi[] | null = null;
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
			popup = new Popup({ offset: 10, closeButton: true })
				.setLngLat([lon, lat])
				.setHTML(poiPopupHtml(props))
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
		showPois(pois: Poi[]): void {
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
