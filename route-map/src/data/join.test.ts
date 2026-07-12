import { afterEach, describe, expect, it, vi } from "vitest";
import type {
	RawArtifacts,
	RawPoiFeature,
	RawRoute,
	RawRoutePoiLink,
} from "./contracts";
import { joinGuideData, osmUrlFor } from "./join";

// Pure join tests (route-map/CLAUDE.md Testing): the deterministic raw->domain
// logic is the one sanctioned automated-test point. No DOM, node env only.

function poiFeature(
	poi_id: string,
	overrides: Partial<RawPoiFeature["properties"]> = {},
	coordinates: [number, number] = [11.0, 47.4],
): RawPoiFeature {
	return {
		type: "Feature",
		geometry: { type: "Point", coordinates },
		properties: {
			poi_id,
			name: poi_id,
			type: "peak",
			ele: 2000,
			osm: `way/${poi_id}`,
			aliases: [],
			n_routes: 0,
			...overrides,
		},
	};
}

function route(route_id: string, overrides: Partial<RawRoute> = {}): RawRoute {
	return {
		route_id,
		name: `Route ${route_id}`,
		peak: null,
		grade: null,
		time: null,
		height_m: null,
		first_ascent: null,
		summary: null,
		description: null,
		...overrides,
	};
}

function link(
	route_id: string,
	poi_id: string,
	is_anchor: boolean,
): RawRoutePoiLink {
	return { route_id, poi_id, surface: poi_id, is_anchor };
}

function artifacts(
	features: RawPoiFeature[],
	routes: RawRoute[],
	links: RawRoutePoiLink[],
): RawArtifacts {
	return {
		routes,
		pois: { type: "FeatureCollection", features },
		links,
	};
}

afterEach(() => {
	vi.restoreAllMocks();
});

describe("osmUrlFor", () => {
	it("builds an openstreetmap.org link from the <type>/<id> value", () => {
		expect(osmUrlFor("way/370669072")).toBe(
			"https://www.openstreetmap.org/way/370669072",
		);
		expect(osmUrlFor("node/4547463685")).toBe(
			"https://www.openstreetmap.org/node/4547463685",
		);
		expect(osmUrlFor("relation/42")).toBe(
			"https://www.openstreetmap.org/relation/42",
		);
	});
});

describe("joinGuideData", () => {
	it("maps POI features to domain Pois with derived osmUrl", () => {
		const data = joinGuideData(
			artifacts(
				[
					poiFeature(
						"p1",
						{ name: "Zugspitze", type: "peak", ele: 2962, osm: "node/123" },
						[11.05, 47.42],
					),
				],
				[],
				[],
			),
		);
		expect(data.pois).toHaveLength(1);
		expect(data.pois[0]).toEqual({
			id: "p1",
			name: "Zugspitze",
			type: "peak",
			ele: 2962,
			osm: "node/123",
			osmUrl: "https://www.openstreetmap.org/node/123",
			coordinates: [11.05, 47.42],
		});
	});

	it("preserves a null elevation", () => {
		const data = joinGuideData(
			artifacts([poiFeature("p1", { ele: null })], [], []),
		);
		expect(data.pois[0]?.ele).toBeNull();
	});

	it("resolves an anchor link to the Route's anchor Poi", () => {
		const data = joinGuideData(
			artifacts(
				[poiFeature("peak1")],
				[route("r1", { peak: "Peak One" })],
				[link("r1", "peak1", true)],
			),
		);
		const r = data.routes.find((x) => x.id === "r1");
		expect(r?.anchor?.id).toBe("peak1");
		expect(r?.mentions).toHaveLength(0);
	});

	it("resolves mention links to the Route's mentions, not its anchor", () => {
		const data = joinGuideData(
			artifacts(
				[poiFeature("m1"), poiFeature("m2")],
				[route("r1")],
				[link("r1", "m1", false), link("r1", "m2", false)],
			),
		);
		const r = data.routes.find((x) => x.id === "r1");
		expect(r?.anchor).toBeNull();
		expect(r?.mentions.map((p) => p.id)).toEqual(["m1", "m2"]);
	});

	it("handles an anchor-only route set", () => {
		const data = joinGuideData(
			artifacts([poiFeature("a1")], [route("r1")], [link("r1", "a1", true)]),
		);
		const r = data.routes.find((x) => x.id === "r1");
		expect(r?.anchor?.id).toBe("a1");
		expect(r?.mentions).toEqual([]);
	});

	it("leaves a route with no links anchor-null and mentions-empty", () => {
		const data = joinGuideData(
			artifacts([poiFeature("p1")], [route("r1")], []),
		);
		const r = data.routes.find((x) => x.id === "r1");
		expect(r?.anchor).toBeNull();
		expect(r?.mentions).toEqual([]);
	});

	it("handles empty artifacts", () => {
		const data = joinGuideData(artifacts([], [], []));
		expect(data.routes).toEqual([]);
		expect(data.pois).toEqual([]);
		expect(data.routesByPoiId.size).toBe(0);
	});

	it("warns and skips a link whose poi_id is unresolvable", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const data = joinGuideData(
			artifacts([poiFeature("p1")], [route("r1")], [link("r1", "ghost", true)]),
		);
		const r = data.routes.find((x) => x.id === "r1");
		expect(r?.anchor).toBeNull();
		expect(warn).toHaveBeenCalledWith(
			expect.stringContaining('unknown poi_id "ghost"'),
		);
	});

	it("warns and skips a link whose route_id is unresolvable", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const data = joinGuideData(
			artifacts([poiFeature("p1")], [route("r1")], [link("ghost", "p1", true)]),
		);
		expect(data.routesByPoiId.size).toBe(0);
		expect(warn).toHaveBeenCalledWith(
			expect.stringContaining('unknown route_id "ghost"'),
		);
	});

	it("indexes routesByPoiId for both anchor and mention references", () => {
		const data = joinGuideData(
			artifacts(
				[poiFeature("shared")],
				[route("r1"), route("r2")],
				[link("r1", "shared", true), link("r2", "shared", false)],
			),
		);
		const referencing = data.routesByPoiId.get("shared");
		expect(referencing?.map((r) => r.id).sort()).toEqual(["r1", "r2"]);
	});

	it("does not double-list a route that references a POI twice", () => {
		const data = joinGuideData(
			artifacts(
				[poiFeature("p1")],
				[route("r1")],
				[link("r1", "p1", true), link("r1", "p1", false)],
			),
		);
		expect(data.routesByPoiId.get("p1")).toHaveLength(1);
	});

	it("warns and skips a POI feature with no coordinates", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const broken = poiFeature("p1");
		// biome-ignore lint/suspicious/noExplicitAny: forcing a malformed seam
		(broken.geometry as any).coordinates = null;
		const data = joinGuideData(artifacts([broken], [], []));
		expect(data.pois).toHaveLength(0);
		expect(warn).toHaveBeenCalled();
	});
});
