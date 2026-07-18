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
			{ id: "wetterstein", label: "Wetterstein (4. Auflage 1996)" },
			{ id: "karwendel", label: "Karwendel (16. Auflage 2011)" },
		];
		expect(parseGuidesManifest(raw)).toEqual([
			{ id: "wetterstein", label: "Wetterstein (4. Auflage 1996)" },
			{ id: "karwendel", label: "Karwendel (16. Auflage 2011)" },
		]);
	});

	it("keeps only id and label, dropping any extra fields", () => {
		const raw = [{ id: "wetterstein", label: "W", bbox: [1, 2, 3, 4] }];
		expect(parseGuidesManifest(raw)).toEqual([
			{ id: "wetterstein", label: "W" },
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
			{ id: "wetterstein", label: "W" },
			{ id: "karwendel" }, // missing label
			{ label: "orphan" }, // missing id
			{ id: "karwendel", label: "K" },
		];
		expect(parseGuidesManifest(raw)).toEqual([
			{ id: "wetterstein", label: "W" },
			{ id: "karwendel", label: "K" },
		]);
		expect(warn).toHaveBeenCalledTimes(2);
	});

	it("warn-and-skips entries whose id/label are the wrong type", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const raw = [
			{ id: 42, label: "numeric id" },
			{ id: "ok", label: 7 },
			{ id: "ok", label: "ok" },
		];
		expect(parseGuidesManifest(raw)).toEqual([{ id: "ok", label: "ok" }]);
		expect(warn).toHaveBeenCalledTimes(2);
	});

	it("warn-and-skips non-object entries (null, string, number)", () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		const raw = [null, "wetterstein", 3, { id: "ok", label: "ok" }];
		expect(parseGuidesManifest(raw)).toEqual([{ id: "ok", label: "ok" }]);
		expect(warn).toHaveBeenCalledTimes(3);
	});
});

describe("guidesManifestUrl", () => {
	it("builds the BASE_URL-prefixed manifest URL (bare in dev/vitest)", () => {
		expect(guidesManifestUrl()).toBe("/guide-data/guides.json");
	});
});
