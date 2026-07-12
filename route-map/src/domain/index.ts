// Domain types the rest of the app speaks — Route, Poi, Anchor, Mention
// (root CONTEXT.md). The src/data adapter is the one place that builds these
// from the raw artifacts; every component depends on these types, never on
// file layout (route-map/CLAUDE.md rule 2).

// A named alpine feature resolved to a single OpenStreetMap coordinate — always
// a point, even for linear features like paths (CONTEXT.md: POI).
export interface Poi {
	/** Stable identity from `poi_id`, e.g. "osm-way-370669072". */
	id: string;
	name: string;
	/** Feature class: peak, hut, pass, path, … (raw `type` string, unbounded). */
	type: string;
	/** Elevation in metres, or null when OSM has none. */
	ele: number | null;
	/** Raw OSM reference, e.g. "way/370669072". */
	osm: string;
	/** Deep link to the feature on openstreetmap.org. */
	osmUrl: string;
	/** [lon, lat] — GeoJSON Point order. */
	coordinates: [number, number];
}

// A single numbered guidebook itinerary. A Route has NO geometry of its own
// (CONTEXT.md): it is prose + verbatim-German metadata plus links to POIs.
// Rendering a Route means highlighting its linked POI set.
export interface Route {
	id: string;
	name: string;
	/** The `peak` field the guidebook files the route under (may be null). */
	peak: string | null;
	grade: string | null;
	time: string | null;
	heightM: string | null;
	firstAscent: string | null;
	summary: string | null;
	description: string | null;
	/** The POI matched from `peak` (link with is_anchor:true), if resolvable. */
	anchor: Poi | null;
	/** POIs matched from the description prose (links with is_anchor:false). */
	mentions: Poi[];
}

// The whole guide, loaded + joined once at startup by loadGuideData().
export interface GuideData {
	routes: Route[];
	pois: Poi[];
	/** poi_id -> Routes that reference that POI (anchor or mention). Powers the
	 *  popup's "which routes reference this POI" cross-links in a later ticket. */
	routesByPoiId: Map<string, Route[]>;
}
