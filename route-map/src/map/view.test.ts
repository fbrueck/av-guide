import { describe, expect, it } from "vitest";
import type { Poi } from "../domain";
import {
	boundsForPois,
	DEFAULT_CENTER,
	DEFAULT_ZOOM,
	SINGLE_POINT_ZOOM,
} from "./view";

// Pure opening-frame math (#131, route-map/CLAUDE.md Testing): boundsForPois
// turns a Guide's POI set into the opening camera frame with no map instance and
// no DOM, so it gets Vitest coverage of its contract for each POI count — the
// same treatment as the pure POI colour table and visibility rule. Contract only:
// which frame is returned per case; the map module owns applying it.

function poi(id: string, coordinates: [number, number]): Poi {
	return {
		id,
		name: id,
		type: "peak",
		ele: 2000,
		osm: `way/${id}`,
		osmUrl: `https://www.openstreetmap.org/way/${id}`,
		coordinates,
	};
}

describe("boundsForPois", () => {
	it("falls back to the default overview when there are no POIs", () => {
		// A Guide with no resolvable POIs must still open somewhere sensible —
		// never a zero-area frame (route-map/CLAUDE.md rule 3, honest absence).
		expect(boundsForPois([])).toEqual({
			kind: "center",
			center: DEFAULT_CENTER,
			zoom: DEFAULT_ZOOM,
		});
	});

	it("centers a single POI at a sensible zoom rather than a zero-area box", () => {
		const only = poi("A", [11.1, 47.4]);
		expect(boundsForPois([only])).toEqual({
			kind: "center",
			center: [11.1, 47.4],
			zoom: SINGLE_POINT_ZOOM,
		});
	});

	it("returns the lon/lat extent of a multi-POI set", () => {
		const pois = [
			poi("A", [11.0, 47.5]),
			poi("B", [11.3, 47.4]),
			poi("C", [10.9, 47.55]),
		];
		expect(boundsForPois(pois)).toEqual({
			kind: "bounds",
			bounds: [
				[10.9, 47.4],
				[11.3, 47.55],
			],
		});
	});
});
