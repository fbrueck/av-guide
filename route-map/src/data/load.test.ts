import { describe, expect, it } from "vitest";
import { guideDataUrls } from "./load";

// The pure URL-construction helper (route-map/CLAUDE.md rule 6): it builds the
// four id-namespaced artifact URLs for a Guide id, without any I/O — so it is
// unit-testable without mocking `fetch`. BASE_URL is `/` under vitest.
describe("guideDataUrls", () => {
	it("builds the four id-namespaced artifact paths for a guide id", () => {
		expect(guideDataUrls("wetterstein")).toEqual({
			entries: "/guide-data/wetterstein/parse-routes/03_structured/routes.json",
			pois: "/guide-data/wetterstein/fetch-pois/04_final/pois.geojson",
			placeLinks:
				"/guide-data/wetterstein/fetch-pois/04_final/place_pois.jsonl",
			entryLinks:
				"/guide-data/wetterstein/fetch-pois/04_final/entry_pois.jsonl",
		});
	});

	it("namespaces by the given id — a different id yields a different prefix", () => {
		const urls = guideDataUrls("karwendel");
		expect(urls.entries).toBe(
			"/guide-data/karwendel/parse-routes/03_structured/routes.json",
		);
		expect(urls.pois).toBe(
			"/guide-data/karwendel/fetch-pois/04_final/pois.geojson",
		);
	});
});
