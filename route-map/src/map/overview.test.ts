import { describe, expect, it } from "vitest";
import type { Guide } from "../domain";
import { boundsForGuideBoxes } from "./overview";
import { DEFAULT_CENTER, DEFAULT_ZOOM } from "./view";

// Pure overview-frame math (#141, route-map/CLAUDE.md Testing): boundsForGuideBoxes
// turns the published Guides' manifest bboxes into the overview camera frame with
// no map instance and no DOM — the same treatment as boundsForPois. Contract only:
// which frame is returned per box count, and that the `[south, west, north, east]`
// lat/lon bbox is converted correctly to the `[lng, lat]` extent maplibre uses.

function guide(id: string, bbox: [number, number, number, number]): Guide {
	return {
		id,
		name: id,
		label: `${id} edition`,
		bbox,
	};
}

describe("boundsForGuideBoxes", () => {
	it("falls back to the default overview when there are no boxes", () => {
		// No published Guides must still open somewhere sensible — never a zero-area
		// frame (route-map/CLAUDE.md rule 3, honest absence).
		expect(boundsForGuideBoxes([])).toEqual({
			kind: "center",
			center: DEFAULT_CENTER,
			zoom: DEFAULT_ZOOM,
		});
	});

	it("frames a single box as its own lon/lat extent", () => {
		// [south, west, north, east] -> [[west, south], [east, north]].
		const only = guide("wetterstein", [47.3, 10.85, 47.55, 11.35]);
		expect(boundsForGuideBoxes([only])).toEqual({
			kind: "bounds",
			bounds: [
				[10.85, 47.3],
				[11.35, 47.55],
			],
		});
	});

	it("returns the combined extent of several boxes", () => {
		const guides = [
			guide("wetterstein", [47.3, 10.85, 47.55, 11.35]),
			guide("karwendel", [47.27, 11.19, 47.6, 11.8]),
		];
		expect(boundsForGuideBoxes(guides)).toEqual({
			kind: "bounds",
			bounds: [
				[10.85, 47.27],
				[11.8, 47.6],
			],
		});
	});
});
