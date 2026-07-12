import type {
	RawArtifacts,
	RawPoiCollection,
	RawRoute,
	RawRoutePoiLink,
} from "./contracts";

// Fetch + parse the three raw artifacts from the dev server's stable
// `/guide-data/...` URLs (route-map/CLAUDE.md rule 6; scheme in vite.config.ts).
// This is the impure I/O half of the boundary; the pure raw->domain join lives
// in join.ts so it can be unit-tested. No guarding of record shapes here — that
// belongs to the join, which turns misses into visible warn-and-skip.

const ROUTES_URL = "/guide-data/parse-routes/03_structured/routes.json";
const POIS_URL = "/guide-data/fetch-pois/04_final/pois.geojson";
const ROUTE_POIS_URL = "/guide-data/fetch-pois/04_final/route_pois.jsonl";

async function fetchText(url: string): Promise<string> {
	const res = await fetch(url);
	if (!res.ok) {
		throw new Error(`Failed to load ${url}: ${res.status} ${res.statusText}`);
	}
	return res.text();
}

// Parse JSONL line-by-line: one JSON object per non-empty line. A single bad
// line is skipped with a warning rather than failing the whole load.
export function parseJsonl(text: string): RawRoutePoiLink[] {
	const links: RawRoutePoiLink[] = [];
	const lines = text.split("\n");
	for (let i = 0; i < lines.length; i++) {
		const line = lines[i]?.trim();
		if (!line) {
			continue;
		}
		try {
			links.push(JSON.parse(line) as RawRoutePoiLink);
		} catch {
			console.warn(`[data] skipping unparseable route_pois line ${i + 1}`);
		}
	}
	return links;
}

export async function loadRawArtifacts(): Promise<RawArtifacts> {
	const [routesText, poisText, linksText] = await Promise.all([
		fetchText(ROUTES_URL),
		fetchText(POIS_URL),
		fetchText(ROUTE_POIS_URL),
	]);
	return {
		routes: JSON.parse(routesText) as RawRoute[],
		pois: JSON.parse(poisText) as RawPoiCollection,
		links: parseJsonl(linksText),
	};
}
