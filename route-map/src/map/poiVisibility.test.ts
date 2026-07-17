import { describe, expect, it } from "vitest";
import type { Entry, Place, Poi, Route } from "../domain";
import { isPoiVisible, revealedMentionPoiIds } from "./poiVisibility";

// Pure visibility-rule tests (#77, route-map/CLAUDE.md Testing): the rule that
// decides which base-layer POIs show is pure and non-UI, so it gets the same
// Vitest coverage as the pure POI colour table — no map instance, node env.
// Contract only: which POIs pass for a given selection. No assertions on the
// maplibre filter expression internals.

function poi(id: string): Poi {
	return {
		id,
		name: id,
		type: "peak",
		ele: 2000,
		osm: `way/${id}`,
		osmUrl: `https://www.openstreetmap.org/way/${id}`,
		coordinates: [11.0, 47.4],
	};
}

function place(id: string, mentions: Poi[]): Place {
	return {
		kind: "place",
		id,
		name: `Place ${id}`,
		summary: null,
		description: null,
		descriptionSource: "none",
		mentions,
		references: [],
		placeType: "peak",
		elevation: null,
		poi: null,
		routes: [],
	};
}

function route(id: string, mentions: Poi[]): Route {
	return {
		kind: "route",
		id,
		name: `Route ${id}`,
		summary: null,
		description: null,
		descriptionSource: "none",
		mentions,
		references: [],
		peak: null,
		grade: null,
		time: null,
		heightM: null,
		firstAscent: null,
		destination: null,
		places: [],
	};
}

// A representative base-layer POI set: two Place coordinates (always visible)
// and three mention-only POIs (visible only when the selected Entry mentions
// them). `isPlace` is the base layer's feature prop, computed from the loaded
// Places' resolved coordinates — the rule takes it as given.
const PLACE_A = { id: "place-a", isPlace: true };
const PLACE_B = { id: "place-b", isPlace: true };
const MENTION_X = { id: "mention-x", isPlace: false };
const MENTION_Y = { id: "mention-y", isPlace: false };
const MENTION_Z = { id: "mention-z", isPlace: false };
const ALL = [PLACE_A, PLACE_B, MENTION_X, MENTION_Y, MENTION_Z];

function visibleIds(entry: Entry | null): string[] {
	return ALL.filter((p) => isPoiVisible(p, entry)).map((p) => p.id);
}

describe("revealedMentionPoiIds", () => {
	it("is empty with no selection", () => {
		expect(revealedMentionPoiIds(null)).toEqual(new Set());
	});

	it("is empty for an Entry with no Mentions", () => {
		expect(revealedMentionPoiIds(route("R1", []))).toEqual(new Set());
	});

	it("is exactly the selected Entry's Mention poi_ids", () => {
		const entry = route("R1", [poi("mention-x"), poi("mention-z")]);
		expect(revealedMentionPoiIds(entry)).toEqual(
			new Set(["mention-x", "mention-z"]),
		);
	});
});

describe("isPoiVisible", () => {
	it("shows only Place POIs when nothing is selected", () => {
		expect(visibleIds(null)).toEqual(["place-a", "place-b"]);
	});

	it("shows Place POIs plus exactly the selected Route's Mentions", () => {
		const entry = route("R1", [poi("mention-x"), poi("mention-z")]);
		expect(visibleIds(entry)).toEqual([
			"place-a",
			"place-b",
			"mention-x",
			"mention-z",
		]);
	});

	it("applies the same rule to a selected Place's Mentions", () => {
		const entry = place("P1", [poi("mention-y")]);
		expect(visibleIds(entry)).toEqual(["place-a", "place-b", "mention-y"]);
	});

	it("reveals nothing extra for an Entry with no Mentions (same as no selection)", () => {
		expect(visibleIds(route("R1", []))).toEqual(visibleIds(null));
	});

	it("keeps a Place POI visible even when it is also a Mention that is not revealed", () => {
		// A POI that is both a Place coordinate and mentioned elsewhere must never
		// be hidden: `isPlace` wins regardless of the current selection (#77 story 10).
		const other = route("R1", [poi("mention-x")]);
		expect(isPoiVisible(PLACE_A, other)).toBe(true);
	});
});
