import type { Poi } from "../domain";

// The opening camera frame derived from a loaded Guide's POI set (#131). This
// replaces the retired, guide-specific WETTERSTEIN_BOUNDS constant: the app now
// frames whatever Guide it loads on that Guide's own POI extent, computed at
// load time (route-map ADR-0005 / #128).
//
// A discriminated union because the *honest* frame differs by POI count — a real
// extent needs bounds, but a single point (or none) has no area, so it collapses
// to a center + zoom rather than a degenerate zero-area box that would over-zoom
// (route-map/CLAUDE.md rule 3: render honestly, never invent geometry).
export type CameraFrame =
	| { kind: "center"; center: [number, number]; zoom: number }
	| { kind: "bounds"; bounds: [[number, number], [number, number]] };

// Fallback view for a Guide with no resolvable POIs (a degenerate, honest
// absence) and for the map's first paint before its data has loaded: a broad
// eastern-Alps overview at a modest zoom — a sensible somewhere, never
// null-island and never a zero-area frame.
export const DEFAULT_CENTER: [number, number] = [11.1, 47.45];
export const DEFAULT_ZOOM = 9;

// Zoom for the single-POI opening frame: a zero-area bounds would over-zoom, so
// center on the point at a sensible massif zoom — kept low enough that the
// surrounding terrain context stays in frame (#120). Shared with the selection
// framing in RouteMap so the single-point behaviour cannot drift between the two.
export const SINGLE_POINT_ZOOM = 12;

// Pure: derive the opening camera frame from a POI set (#131). Empty → the
// default overview; a single POI → centered at a sensible zoom; two or more →
// their lon/lat extent. No maplibre and no DOM — the reframe method on the map's
// imperative API applies this frame (and the mobile bottom-sheet inset) itself.
export function boundsForPois(pois: Poi[]): CameraFrame {
	const [first, ...rest] = pois;
	if (!first) {
		return { kind: "center", center: DEFAULT_CENTER, zoom: DEFAULT_ZOOM };
	}
	if (rest.length === 0) {
		return {
			kind: "center",
			center: first.coordinates,
			zoom: SINGLE_POINT_ZOOM,
		};
	}
	let minLng = first.coordinates[0];
	let minLat = first.coordinates[1];
	let maxLng = minLng;
	let maxLat = minLat;
	for (const poi of rest) {
		const [lng, lat] = poi.coordinates;
		minLng = Math.min(minLng, lng);
		minLat = Math.min(minLat, lat);
		maxLng = Math.max(maxLng, lng);
		maxLat = Math.max(maxLat, lat);
	}
	return {
		kind: "bounds",
		bounds: [
			[minLng, minLat],
			[maxLng, maxLat],
		],
	};
}
