import {
	AttributionControl,
	Map as MapLibreMap,
	NavigationControl,
	ScaleControl,
} from "maplibre-gl";
import { BASEMAP_MAX_ZOOM, topoBasemapStyle } from "./basemap";
import { WETTERSTEIN_BOUNDS } from "./view";

// The single owner of the maplibre-gl Map instance (route-map/CLAUDE.md
// rule 4). It is created imperatively and hidden behind this small typed API;
// UI components never touch maplibre-gl directly. Later tickets grow this
// interface (highlightPois, fitTo, setTerrain, …) — for now it only manages
// its own lifecycle.
export interface RouteMap {
	destroy(): void;
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

	return {
		destroy() {
			map.remove();
		},
	};
}
