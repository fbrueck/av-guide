import type {
	RawArtifacts,
	RawEntry,
	RawEntryPoiLink,
	RawPlacePoiLink,
	RawPoiCollection,
} from "./contracts";

// Fetch + parse the raw artifacts from the dev server's stable `/guide-data/...`
// URLs (route-map/CLAUDE.md rule 6; scheme in vite.config.ts). This is the
// impure I/O half of the boundary; the pure raw->domain join lives in join.ts so
// it can be unit-tested. No guarding of record shapes here — that belongs to the
// join, which turns misses into visible warn-and-skip.
//
// The Entry model (#44): the browser loads the Entry array (routes.json), the
// POI GeoJSON, and the two link tables — place_pois.jsonl (Place -> POI) and
// entry_pois.jsonl (Entry Mentions -> POI). The old route_pois.jsonl is gone.

// The four artifact URLs for a given Guide id.
export interface GuideDataUrls {
	entries: string;
	pois: string;
	placeLinks: string;
	entryLinks: string;
}

// Pure URL-construction helper: builds the four id-namespaced artifact URLs for
// a Guide id (route-map/CLAUDE.md rule 6). It is pure so it is unit-testable
// without mocking `fetch`.
//
// The stable `/guide-data/<id>/…` scheme is prefixed with Vite's BASE_URL
// (always trailing-slashed): it is `/` in dev — so URLs stay
// `/guide-data/<id>/…` for the configureServer middleware — and `/av-guide/` in
// the GitHub Pages build, so they resolve to `/av-guide/guide-data/<id>/…`
// against the deployed base path. The `<id>` segment keys the static snapshot
// on GitHub Pages, which ignores query strings — so it is a path segment, not a
// query param.
export function guideDataUrls(guideId: string): GuideDataUrls {
	const base = `${import.meta.env.BASE_URL}guide-data/${guideId}`;
	return {
		entries: `${base}/parse-routes/03_structured/routes.json`,
		pois: `${base}/fetch-pois/04_final/pois.geojson`,
		placeLinks: `${base}/fetch-pois/04_final/place_pois.jsonl`,
		entryLinks: `${base}/fetch-pois/04_final/entry_pois.jsonl`,
	};
}

async function fetchText(url: string): Promise<string> {
	const res = await fetch(url);
	if (!res.ok) {
		throw new Error(`Failed to load ${url}: ${res.status} ${res.statusText}`);
	}
	return res.text();
}

// Parse JSONL line-by-line: one JSON object per non-empty line. A single bad
// line is skipped with a warning rather than failing the whole load.
export function parseJsonl<T>(text: string, label: string): T[] {
	const records: T[] = [];
	const lines = text.split("\n");
	for (let i = 0; i < lines.length; i++) {
		const line = lines[i]?.trim();
		if (!line) {
			continue;
		}
		try {
			records.push(JSON.parse(line) as T);
		} catch {
			console.warn(`[data] skipping unparseable ${label} line ${i + 1}`);
		}
	}
	return records;
}

export async function loadRawArtifacts(guideId: string): Promise<RawArtifacts> {
	const urls = guideDataUrls(guideId);
	const [entriesText, poisText, placeLinksText, entryLinksText] =
		await Promise.all([
			fetchText(urls.entries),
			fetchText(urls.pois),
			fetchText(urls.placeLinks),
			fetchText(urls.entryLinks),
		]);
	return {
		entries: JSON.parse(entriesText) as RawEntry[],
		pois: JSON.parse(poisText) as RawPoiCollection,
		placeLinks: parseJsonl<RawPlacePoiLink>(placeLinksText, "place_pois"),
		entryLinks: parseJsonl<RawEntryPoiLink>(entryLinksText, "entry_pois"),
	};
}
