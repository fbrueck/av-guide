import { describe, expect, it } from "vitest";
import type { Guide } from "./domain";
import {
	deepLinkGuideId,
	guideParamSearch,
	readGuideParam,
} from "./guideParam";

// The `?guide=` param logic (ADR-0005, route-map/CLAUDE.md rule 5): pure
// string->string helpers, so the read/resolve/write contract is unit-tested with
// no DOM. App owns the impure `location.search` read and `history.replaceState`
// write — the behaviour (initial open, reload-stability, switch write) is
// verified in the browser with DevTools per the ticket.

const guides: Guide[] = [
	{
		id: "wetterstein",
		name: "Wetterstein",
		label: "Wetterstein (4. Auflage 1996)",
		bbox: [47.3, 10.85, 47.55, 11.35],
	},
	{
		id: "karwendel",
		name: "Karwendel",
		label: "Karwendel (16. Auflage 2011)",
		bbox: [47.27, 11.19, 47.6, 11.8],
	},
];

describe("readGuideParam", () => {
	it("reads the guide id from the search string", () => {
		expect(readGuideParam("?guide=karwendel")).toBe("karwendel");
	});

	it("reads it alongside other params", () => {
		expect(readGuideParam("?foo=bar&guide=karwendel&baz=1")).toBe("karwendel");
	});

	it("returns null when the param is absent", () => {
		expect(readGuideParam("?foo=bar")).toBeNull();
		expect(readGuideParam("")).toBeNull();
	});
});

describe("deepLinkGuideId", () => {
	it("deep-links into the requested Guide when the id names a manifest Guide", () => {
		expect(deepLinkGuideId("karwendel", guides)).toBe("karwendel");
	});

	it("stays on the overview (null) for an unknown id", () => {
		expect(deepLinkGuideId("bogus", guides)).toBeNull();
	});

	it("stays on the overview (null) when the param is absent", () => {
		expect(deepLinkGuideId(null, guides)).toBeNull();
	});

	it("stays on the overview (null) for an empty manifest", () => {
		expect(deepLinkGuideId("karwendel", [])).toBeNull();
		expect(deepLinkGuideId(null, [])).toBeNull();
	});
});

describe("guideParamSearch", () => {
	it("builds the search string reflecting the selected Guide", () => {
		expect(guideParamSearch("karwendel", "")).toBe("?guide=karwendel");
	});

	it("overwrites an existing guide param", () => {
		expect(guideParamSearch("karwendel", "?guide=wetterstein")).toBe(
			"?guide=karwendel",
		);
	});

	it("preserves other query params, setting only guide", () => {
		expect(guideParamSearch("karwendel", "?foo=bar")).toBe(
			"?foo=bar&guide=karwendel",
		);
	});
});
