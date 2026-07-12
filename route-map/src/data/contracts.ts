// The raw on-disk artifact shapes — the ONLY place in the app that names them
// (route-map/CLAUDE.md rule 2). These describe what the pipelines emit, before
// any guarding or joining. No `any`: unknown/optional fields are typed as such
// so the join must narrow them explicitly. Each pipeline owns its contract;
// a format change is a one-file edit here plus the join.

// --- parse-routes: 03_structured/routes.json (JSON array) ---
export interface RawRoute {
	route_id: string;
	name: string;
	peak: string | null;
	grade: string | null;
	time: string | null;
	height_m: string | null;
	first_ascent: string | null;
	summary: string | null;
	description: string | null;
}

// --- fetch-pois: 04_final/pois.geojson (GeoJSON FeatureCollection) ---
export interface RawPoiProperties {
	poi_id: string;
	name: string;
	type: string;
	ele: number | null;
	osm: string;
	aliases: string[];
	n_routes: number;
}

export interface RawPoiFeature {
	type: "Feature";
	geometry: {
		type: "Point";
		coordinates: [number, number];
	};
	properties: RawPoiProperties;
}

export interface RawPoiCollection {
	type: "FeatureCollection";
	features: RawPoiFeature[];
}

// --- fetch-pois: 04_final/route_pois.jsonl (one JSON object per line) ---
export interface RawRoutePoiLink {
	route_id: string;
	poi_id: string;
	surface: string;
	is_anchor: boolean;
}

// The three artifacts as loaded (parsed) but not yet joined.
export interface RawArtifacts {
	routes: RawRoute[];
	pois: RawPoiCollection;
	links: RawRoutePoiLink[];
}
