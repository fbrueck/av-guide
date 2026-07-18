import { afterEach, describe, expect, it, vi } from "vitest";
import { guidesManifestUrl, parseGuidesManifest } from "./manifest";

// The Guide manifest guard (route-map/CLAUDE.md rule 2 "guard the seams" +
// Testing): `guides.json` is hand-maintained maintainer metadata, so the guard
// keeps the well-formed Guides and warn-and-skips malformed entries rather than
// crashing. Pure raw->domain, so it is unit-tested with no fetch, no DOM.

afterEach(() => {
	vi.restoreAllMocks();
});

describe("parseGuidesManifest", () => {
	it("passes through a well-formed manifest as Guide[]", () => {
		const raw = [
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
		expect(parseGuidesManifest(raw)).toEqual([
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
		]);
	});

	it("returns id, name, label and bbox, dropping any extra fields", () => {
		const raw = [
			{
				id: "wetterstein",
				name: "W",
				label: "W ed.",
				bbox: [1, 2, 3, 4],
				x: 9,
			},
		];
		expect(parseGuidesManifest(raw)).toEqual([
			{ id: "wetterstein", name: "W", label: "W ed.", bbox: [1, 2, 3, 4] },
		]);
	});

	it("warn-and-returns [] when the manifest is not an array", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		expect(parseGuidesManifest({ id: "x", label: "y" })).toEqual([]);
		expect(warn).toHaveBeenCalledTimes(1);
	});

	it("warn-and-skips entries missing id or label, keeping the good ones", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const raw = [
			{ id: "wetterstein", name: "W", label: "W", bbox: [1, 2, 3, 4] },
			{ id: "karwendel", name: "K" }, // missing label
			{ label: "orphan" }, // missing id
			{ id: "karwendel", name: "K", label: "K", bbox: [1, 2, 3, 4] },
		];
		expect(parseGuidesManifest(raw)).toEqual([
			{ id: "wetterstein", name: "W", label: "W", bbox: [1, 2, 3, 4] },
			{ id: "karwendel", name: "K", label: "K", bbox: [1, 2, 3, 4] },
		]);
		expect(warn).toHaveBeenCalledTimes(2);
	});

	it("warn-and-skips entries whose id/label are the wrong type", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const raw = [
			{ id: 42, name: "N", label: "numeric id", bbox: [1, 2, 3, 4] },
			{ id: "ok", name: "N", label: 7, bbox: [1, 2, 3, 4] },
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		];
		expect(parseGuidesManifest(raw)).toEqual([
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		]);
		expect(warn).toHaveBeenCalledTimes(2);
	});

	it("warn-and-skips non-object entries (null, string, number)", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const raw = [
			null,
			"wetterstein",
			3,
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		];
		expect(parseGuidesManifest(raw)).toEqual([
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		]);
		expect(warn).toHaveBeenCalledTimes(3);
	});

	it("warn-and-skips an entry missing name, keeping a good sibling", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const raw = [
			{ id: "non ", label: "no name", bbox: [1, 2, 3, 4] },
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		];
		expect(parseGuidesManifest(raw)).toEqual([
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		]);
		expect(warn).toHaveBeenCalledTimes(1);
	});

	it("warn-and-skips an entry with a blank/whitespace name", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const raw = [
			{ id: "blank", name: "   ", label: "blank name", bbox: [1, 2, 3, 4] },
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		];
		expect(parseGuidesManifest(raw)).toEqual([
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		]);
		expect(warn).toHaveBeenCalledTimes(1);
	});

	it("warn-and-skips an entry missing bbox, keeping a good sibling", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const raw = [
			{ id: "nobbox", name: "N", label: "no bbox" },
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		];
		expect(parseGuidesManifest(raw)).toEqual([
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		]);
		expect(warn).toHaveBeenCalledTimes(1);
	});

	it("warn-and-skips an entry whose bbox is not length-4", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const raw = [
			{ id: "short", name: "N", label: "short bbox", bbox: [1, 2, 3] },
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		];
		expect(parseGuidesManifest(raw)).toEqual([
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		]);
		expect(warn).toHaveBeenCalledTimes(1);
	});

	it("warn-and-skips an entry whose bbox has a non-finite element", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const raw = [
			{ id: "nan", name: "N", label: "NaN elem", bbox: [1, 2, 3, Number.NaN] },
			{
				id: "inf",
				name: "N",
				label: "Infinity elem",
				bbox: [1, 2, 3, Number.POSITIVE_INFINITY],
			},
			{ id: "str", name: "N", label: "string elem", bbox: [1, 2, 3, "4"] },
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		];
		expect(parseGuidesManifest(raw)).toEqual([
			{ id: "ok", name: "N", label: "ok", bbox: [1, 2, 3, 4] },
		]);
		expect(warn).toHaveBeenCalledTimes(3);
	});
});

describe("guidesManifestUrl", () => {
	it("builds the BASE_URL-prefixed manifest URL (bare in dev/vitest)", () => {
		expect(guidesManifestUrl()).toBe("/guide-data/guides.json");
	});
});
