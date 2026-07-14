// The raw on-disk artifact shapes — the ONLY place in the app that names them
// (route-map/CLAUDE.md rule 2). These describe what the pipelines emit, before
// any guarding or joining. No `any`: unknown/optional fields are typed as such
// so the join must narrow them explicitly. Each pipeline owns its contract;
// a format change is a one-file edit here plus the join.

// A book-internal cross-reference as parse-routes emits it (CONTEXT.md:
// Reference): the canonical `ref_id` (null for anaphora) + the verbatim span.
export interface RawReference {
	ref_id: string | null;
	surface: string;
}

// --- parse-routes: 03_structured/routes.json (JSON array of Entries, #42) ---
// One record per Entry (Place or Route), discriminated by `kind`. Each kind
// leaves the other's fields null; the link fields default to [] (never null).
export interface RawEntry {
	id: string;
	kind: "place" | "route";
	name: string;
	// Place fields.
	place_type: string | null;
	elevation: string | null;
	// Route fields.
	peak: string | null;
	grade: string | null;
	time: string | null;
	height_m: string | null;
	first_ascent: string | null;
	// Link fields. `destination_id` is the Route's primary target Place (nullable
	// scalar, 0-or-1); `place_ids` are the additional target Places (traverse
	// waypoints), disjoint from the Destination. Both null/absent for a Place.
	destination_id: string | null;
	place_ids: string[];
	references: RawReference[];
	// Shared prose.
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
	/** How many distinct Entries reference this POI (place link + mentions). */
	n_entries: number;
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

// --- fetch-pois: 04_final/place_pois.jsonl (one JSON object per line) ---
// A Place's single resolved POI — its coordinate (CONTEXT.md: Place → POI).
export interface RawPlacePoiLink {
	place_id: string;
	poi_id: string;
}

// --- fetch-pois: 04_final/entry_pois.jsonl (one JSON object per line) ---
// An Entry-general Mention → POI link (mentions only; a Route's coordinate is
// transitive via its Destination Place, resolved here at join time).
export interface RawEntryPoiLink {
	entry_id: string;
	poi_id: string;
	surface: string;
}

// The artifacts as loaded (parsed) but not yet joined.
export interface RawArtifacts {
	entries: RawEntry[];
	pois: RawPoiCollection;
	placeLinks: RawPlacePoiLink[];
	entryLinks: RawEntryPoiLink[];
}
