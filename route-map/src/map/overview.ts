import type { Guide } from "../domain";
import { type CameraFrame, DEFAULT_CENTER, DEFAULT_ZOOM } from "./view";

// The opening camera frame for the Guide overview state (#141): the view that
// fits every published Guide's manifest `bbox` at once, so a reader lands seeing
// all of them. The sibling of boundsForPois (view.ts) for the overview: same
// pure, map-free, DOM-free contract, reusing its CameraFrame type and DEFAULT_*
// fallback, so the two opening-frame paths cannot drift.
//
// The manifest `bbox` is `[south, west, north, east]` (lat/lon degrees) — a Guide
// field, distinct from a POI's `[lng, lat]` coordinate — so this converts to the
// `[lng, lat]` extent maplibre bounds use, carefully, in one place.
//
// No boxes → the default overview (never a zero-area frame, route-map/CLAUDE.md
// rule 3). A single box or many → their combined lon/lat extent as bounds; a
// bbox is a real rectangle, so even one box has area and needs no center-fallback
// (unlike a single POI point).
export function boundsForGuideBoxes(guides: Guide[]): CameraFrame {
	const [first, ...rest] = guides;
	if (!first) {
		return { kind: "center", center: DEFAULT_CENTER, zoom: DEFAULT_ZOOM };
	}
	let [minLat, minLng, maxLat, maxLng] = first.bbox;
	for (const guide of rest) {
		const [south, west, north, east] = guide.bbox;
		minLat = Math.min(minLat, south);
		minLng = Math.min(minLng, west);
		maxLat = Math.max(maxLat, north);
		maxLng = Math.max(maxLng, east);
	}
	return {
		kind: "bounds",
		bounds: [
			[minLng, minLat],
			[maxLng, maxLat],
		],
	};
}
