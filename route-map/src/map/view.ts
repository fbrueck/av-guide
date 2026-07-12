import type { LngLatBoundsLike } from "maplibre-gl";

// Wetterstein framing — the POI bounding box exported by fetch-pois
// (lon 10.9219–11.2930, lat 47.3682–47.5460). The app opens fitted to this so
// the digitizer lands on the massif with no manual panning.
export const WETTERSTEIN_BOUNDS: LngLatBoundsLike = [
	[10.9219, 47.3682],
	[11.293, 47.546],
];
