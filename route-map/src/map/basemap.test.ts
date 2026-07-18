import { describe, expect, it } from "vitest";
import {
	BASEMAP_CREDITS,
	BASEMAP_CREDITS_SKITOURENGURU,
	is2dBaseVisible,
	mapCreditsFor,
	TERRAIN_CREDIT,
} from "./basemap";

// The two pure seams #135 adds: which credits the attribution overlay shows for
// the active view, and which of the two 2D raster bases is visible. Both are
// pure look-up tables (the RouteMap and MapAttribution consume them), so they
// get the same unit coverage the join and poiVisibility do — the map wiring
// itself stays a DevTools check (route-map/CLAUDE.md Testing).

describe("mapCreditsFor", () => {
	it("credits OpenTopoMap when the flat OpenTopoMap base is active in 2D", () => {
		expect(mapCreditsFor("opentopomap", false)).toBe(BASEMAP_CREDITS);
	});

	it("credits Skitourenguru when its base is active in 2D", () => {
		const credits = mapCreditsFor("skitourenguru", false);
		expect(credits).toBe(BASEMAP_CREDITS_SKITOURENGURU);
		expect(credits.some((c) => c.name === "Skitourenguru")).toBe(true);
	});

	it("credits the 3D base + terrain regardless of the selected 2D base", () => {
		// In 3D both 2D rasters are hidden, so neither 2D credit shows; the
		// Mapterhorn terrain credit is added because its DEM tiles are now loaded.
		for (const base2d of ["opentopomap", "skitourenguru"] as const) {
			const credits = mapCreditsFor(base2d, true);
			expect(credits).toContain(TERRAIN_CREDIT);
			expect(credits.some((c) => c.name === "VersaTiles")).toBe(true);
			expect(credits.some((c) => c.name === "OpenTopoMap")).toBe(false);
			expect(credits.some((c) => c.name === "Skitourenguru")).toBe(false);
		}
	});
});

describe("is2dBaseVisible", () => {
	it("shows exactly the selected 2D base in 2D and hides the other", () => {
		expect(is2dBaseVisible("opentopomap", "opentopomap", false)).toBe(true);
		expect(is2dBaseVisible("skitourenguru", "opentopomap", false)).toBe(false);
		expect(is2dBaseVisible("skitourenguru", "skitourenguru", false)).toBe(true);
		expect(is2dBaseVisible("opentopomap", "skitourenguru", false)).toBe(false);
	});

	it("hides every 2D base in 3D (the VersaTiles landcover is the base there)", () => {
		expect(is2dBaseVisible("opentopomap", "opentopomap", true)).toBe(false);
		expect(is2dBaseVisible("skitourenguru", "skitourenguru", true)).toBe(false);
	});
});
