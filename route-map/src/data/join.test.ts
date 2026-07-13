import { afterEach, describe, expect, it, vi } from "vitest";
import type { Place, Route } from "../domain";
import type {
	RawArtifacts,
	RawEntry,
	RawEntryPoiLink,
	RawPlacePoiLink,
	RawPoiFeature,
	RawReference,
} from "./contracts";
import { joinGuideData, osmUrlFor } from "./join";

// Pure join tests (route-map/CLAUDE.md Testing): the deterministic raw->domain
// logic is the one sanctioned automated-test point. No DOM, node env only. The
// Entry model (#44): Places resolve to <=1 POI, a Route's anchor coordinate is
// transitive via its Anchor Place, mentions are Entry-general, References
// resolve to Entries (dangling ones warned, not crashed).

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
			n_entries: 0,
			...overrides,
		},
	};
}

function place(id: string, overrides: Partial<RawEntry> = {}): RawEntry {
	return {
		id,
		kind: "place",
		name: `Place ${id}`,
		place_type: "peak",
		elevation: null,
		peak: null,
		grade: null,
		time: null,
		height_m: null,
		first_ascent: null,
		anchor_ids: [],
		references: [],
		summary: null,
		description: null,
		...overrides,
	};
}

function route(id: string, overrides: Partial<RawEntry> = {}): RawEntry {
	return {
		id,
		kind: "route",
		name: `Route ${id}`,
		place_type: null,
		elevation: null,
		peak: null,
		grade: null,
		time: null,
		height_m: null,
		first_ascent: null,
		anchor_ids: [],
		references: [],
		summary: null,
		description: null,
		...overrides,
	};
}

function ref(
	ref_id: string | null,
	surface = ref_id ?? "wie dort",
): RawReference {
	return { ref_id, surface };
}

function placeLink(place_id: string, poi_id: string): RawPlacePoiLink {
	return { place_id, poi_id };
}

function entryLink(
	entry_id: string,
	poi_id: string,
	surface = poi_id,
): RawEntryPoiLink {
	return { entry_id, poi_id, surface };
}

function artifacts(
	features: RawPoiFeature[],
	entries: RawEntry[],
	placeLinks: RawPlacePoiLink[] = [],
	entryLinks: RawEntryPoiLink[] = [],
): RawArtifacts {
	return {
		entries,
		pois: { type: "FeatureCollection", features },
		placeLinks,
		entryLinks,
	};
}

function placeById(data: ReturnType<typeof joinGuideData>, id: string): Place {
	const p = data.places.find((x) => x.id === id);
	if (!p) {
		throw new Error(`no place ${id}`);
	}
	return p;
}

function routeById(data: ReturnType<typeof joinGuideData>, id: string): Route {
	const r = data.routes.find((x) => x.id === id);
	if (!r) {
		throw new Error(`no route ${id}`);
	}
	return r;
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
	});
});

describe("joinGuideData — POIs", () => {
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
			artifacts([poiFeature("p1", { ele: null })], []),
		);
		expect(data.pois[0]?.ele).toBeNull();
	});

	it("warns and skips a POI feature with no coordinates", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const broken = poiFeature("p1");
		// biome-ignore lint/suspicious/noExplicitAny: forcing a malformed seam
		(broken.geometry as any).coordinates = null;
		const data = joinGuideData(artifacts([broken], []));
		expect(data.pois).toHaveLength(0);
		expect(warn).toHaveBeenCalled();
	});
});

describe("joinGuideData — Places and their POI", () => {
	it("splits entries into places and routes by kind", () => {
		const data = joinGuideData(
			artifacts([], [place("R1"), route("R2"), place("R3")]),
		);
		expect(data.places.map((p) => p.id)).toEqual(["R1", "R3"]);
		expect(data.routes.map((r) => r.id)).toEqual(["R2"]);
		expect(data.entries).toHaveLength(3);
	});

	it("resolves a Place to its single POI via a place_pois link", () => {
		const data = joinGuideData(
			artifacts(
				[poiFeature("poi1", {}, [11.1, 47.5])],
				[place("R1", { place_type: "hut", elevation: "1652 m" })],
				[placeLink("R1", "poi1")],
			),
		);
		const p = placeById(data, "R1");
		expect(p.poi?.id).toBe("poi1");
		expect(p.poi?.coordinates).toEqual([11.1, 47.5]);
		expect(p.placeType).toBe("hut");
		expect(p.elevation).toBe("1652 m");
	});

	it("renders a Place with no place_pois link honestly (poi null)", () => {
		const data = joinGuideData(artifacts([], [place("R1")]));
		expect(placeById(data, "R1").poi).toBeNull();
	});

	it("warns and skips a place link whose poi_id is unresolvable", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const data = joinGuideData(
			artifacts([], [place("R1")], [placeLink("R1", "ghost")]),
		);
		expect(placeById(data, "R1").poi).toBeNull();
		expect(warn).toHaveBeenCalledWith(
			expect.stringContaining('unknown poi_id "ghost"'),
		);
	});

	it("warns when a place link's place_id is not a Place", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		joinGuideData(
			artifacts([poiFeature("poi1")], [route("R1")], [placeLink("R1", "poi1")]),
		);
		expect(warn).toHaveBeenCalledWith(expect.stringContaining("R1"));
	});
});

describe("joinGuideData — Anchors (transitive coordinate) and unfiled routes", () => {
	it("resolves a Route's anchors to Places, coordinate transitive via place.poi", () => {
		const data = joinGuideData(
			artifacts(
				[poiFeature("poi1", {}, [10.9, 47.3])],
				[place("R1"), route("R2", { anchor_ids: ["R1"] })],
				[placeLink("R1", "poi1")],
			),
		);
		const r = routeById(data, "R2");
		expect(r.anchors.map((a) => a.id)).toEqual(["R1"]);
		// The anchor coordinate is never a direct route->POI link; it is reached
		// transitively through the Anchor Place's POI.
		expect(r.anchors[0]?.poi?.coordinates).toEqual([10.9, 47.3]);
	});

	it("adds a route to its Anchor Place's routes-leading-here list", () => {
		const data = joinGuideData(
			artifacts(
				[],
				[
					place("R1"),
					route("R2", { anchor_ids: ["R1"] }),
					route("R3", { anchor_ids: ["R1"] }),
				],
			),
		);
		expect(
			placeById(data, "R1")
				.routes.map((r) => r.id)
				.sort(),
		).toEqual(["R2", "R3"]);
	});

	it("puts an anchor-less Route in the unfiled-routes bucket", () => {
		const data = joinGuideData(
			artifacts(
				[],
				[place("R1"), route("R2"), route("R3", { anchor_ids: ["R1"] })],
			),
		);
		expect(data.unfiledRoutes.map((r) => r.id)).toEqual(["R2"]);
	});

	it("keeps an anchored Route's Anchor Place resolvable even with no POI", () => {
		const data = joinGuideData(
			artifacts([], [place("R1"), route("R2", { anchor_ids: ["R1"] })]),
		);
		const r = routeById(data, "R2");
		expect(r.anchors[0]?.id).toBe("R1");
		expect(r.anchors[0]?.poi).toBeNull();
		expect(data.unfiledRoutes).toHaveLength(0);
	});

	it("warns and skips an anchor_id that resolves to no Entry", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const data = joinGuideData(
			artifacts([], [route("R2", { anchor_ids: ["ghost"] })]),
		);
		const r = routeById(data, "R2");
		expect(r.anchors).toHaveLength(0);
		// no anchors resolved -> unfiled
		expect(data.unfiledRoutes.map((x) => x.id)).toEqual(["R2"]);
		expect(warn).toHaveBeenCalledWith(
			expect.stringContaining('anchor_id "ghost"'),
		);
	});

	it("warns and skips an anchor_id that resolves to a Route, not a Place", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const data = joinGuideData(
			artifacts([], [route("R1"), route("R2", { anchor_ids: ["R1"] })]),
		);
		expect(routeById(data, "R2").anchors).toHaveLength(0);
		expect(warn).toHaveBeenCalledWith(expect.stringContaining("R1"));
	});
});

describe("joinGuideData — Mentions (Entry-general)", () => {
	it("attaches entry_pois mentions to a Route", () => {
		const data = joinGuideData(
			artifacts(
				[poiFeature("m1"), poiFeature("m2")],
				[route("R1")],
				[],
				[entryLink("R1", "m1"), entryLink("R1", "m2")],
			),
		);
		expect(routeById(data, "R1").mentions.map((p) => p.id)).toEqual([
			"m1",
			"m2",
		]);
	});

	it("attaches mentions to a Place too (Übersicht prose)", () => {
		const data = joinGuideData(
			artifacts([poiFeature("m1")], [place("R1")], [], [entryLink("R1", "m1")]),
		);
		expect(placeById(data, "R1").mentions.map((p) => p.id)).toEqual(["m1"]);
	});

	it("warns and skips a mention link whose poi_id is unresolvable", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const data = joinGuideData(
			artifacts([], [route("R1")], [], [entryLink("R1", "ghost")]),
		);
		expect(routeById(data, "R1").mentions).toHaveLength(0);
		expect(warn).toHaveBeenCalledWith(
			expect.stringContaining('unknown poi_id "ghost"'),
		);
	});

	it("warns and skips a mention link whose entry_id is unknown", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		joinGuideData(
			artifacts(
				[poiFeature("m1")],
				[route("R1")],
				[],
				[entryLink("ghost", "m1")],
			),
		);
		expect(warn).toHaveBeenCalledWith(
			expect.stringContaining('unknown entry_id "ghost"'),
		);
	});
});

describe("joinGuideData — References", () => {
	it("resolves a reference to its target Entry", () => {
		const data = joinGuideData(
			artifacts(
				[],
				[place("R1"), route("R2", { references: [ref("R1", "R 1")] })],
			),
		);
		const r = routeById(data, "R2");
		expect(r.references).toHaveLength(1);
		expect(r.references[0]?.surface).toBe("R 1");
		expect(r.references[0]?.target?.id).toBe("R1");
	});

	it("warns and keeps a dangling reference (unknown ref_id), target null", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const data = joinGuideData(
			artifacts([], [route("R2", { references: [ref("R999", "R 999")] })]),
		);
		const r = routeById(data, "R2");
		expect(r.references).toHaveLength(1);
		expect(r.references[0]?.target).toBeNull();
		expect(warn).toHaveBeenCalledWith(expect.stringContaining("R999"));
	});

	it("keeps an anaphora reference (null ref_id) as an unresolved target without warning", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const data = joinGuideData(
			artifacts([], [route("R2", { references: [ref(null, "wie dort")] })]),
		);
		const r = routeById(data, "R2");
		expect(r.references[0]?.target).toBeNull();
		expect(r.references[0]?.surface).toBe("wie dort");
		expect(warn).not.toHaveBeenCalled();
	});
});

describe("joinGuideData — entriesByPoiId index", () => {
	it("indexes both a Place's own POI and mentioning Entries", () => {
		const data = joinGuideData(
			artifacts(
				[poiFeature("shared")],
				[place("R1"), route("R2")],
				[placeLink("R1", "shared")],
				[entryLink("R2", "shared")],
			),
		);
		const referencing = data.entriesByPoiId.get("shared");
		expect(referencing?.map((e) => e.id).sort()).toEqual(["R1", "R2"]);
	});

	it("does not double-list an entry that references a POI twice", () => {
		const data = joinGuideData(
			artifacts(
				[poiFeature("m1")],
				[place("R1")],
				[placeLink("R1", "m1")],
				[entryLink("R1", "m1")],
			),
		);
		expect(data.entriesByPoiId.get("m1")).toHaveLength(1);
	});
});

describe("joinGuideData — degenerate inputs", () => {
	it("handles empty artifacts", () => {
		const data = joinGuideData(artifacts([], []));
		expect(data.entries).toEqual([]);
		expect(data.places).toEqual([]);
		expect(data.routes).toEqual([]);
		expect(data.pois).toEqual([]);
		expect(data.unfiledRoutes).toEqual([]);
		expect(data.entriesByPoiId.size).toBe(0);
	});
});
