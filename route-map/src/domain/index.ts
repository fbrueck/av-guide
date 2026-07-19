// Domain types the rest of the app speaks — Entry (Place | Route), Poi,
// Destination, Mention, Reference (root CONTEXT.md). The src/data adapter is the
// one place that builds these from the raw artifacts; every component depends on
// these types, never on file layout (route-map/CLAUDE.md rule 2).

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

// A book-internal pointer from one Entry to another by entry id, found inline in
// prose ("Wie R 43", "(R 43, 243)") — CONTEXT.md: Reference. Resolved to the
// target Entry at join time; an unresolvable ref_id is surfaced honestly (a
// console.warn + a null target), never invented. `refId` is null for anaphora
// ("wie dort") — inherently unresolvable, so its null target is expected, not
// drift.
export interface Reference {
	/** Normalized canonical key (e.g. "R43"), or null for anaphora. */
	refId: string | null;
	/** The verbatim span as printed in the prose. */
	surface: string;
	/** The Entry this points to, or null when it cannot be resolved. */
	target: Entry | null;
}

// Fields common to every Entry (CONTEXT.md: Entry). Mentions and References are
// Entry-general — extracted from any Entry's prose (a Route's description or a
// Place's Übersicht), matched to a POI / another Entry respectively.
interface EntryBase {
	/** The book's own entry id (normalized Randziffer), e.g. "R43", "R376A". */
	id: string;
	name: string;
	/** The book's prose blurb (Übersicht for a Place), if any. */
	summary: string | null;
	description: string | null;
	/** Provenance of `description` (CONTEXT.md): "sliced" verbatim page text,
	 *  "stub" a body-less cross-ref's one-line heading, or "none". Lets the UI
	 *  flag non-verbatim descriptions instead of silently mixing them. */
	descriptionSource: "sliced" | "stub" | "none";
	/** Place-names in this Entry's prose matched to POIs (CONTEXT.md: Mention). */
	mentions: Poi[];
	/** Book-internal cross-references, resolved to Entries (CONTEXT.md: Reference). */
	references: Reference[];
}

// An Entry whose subject is a target feature — a summit, hut, pass, … that the
// guidebook describes in its own right and files Routes under (CONTEXT.md:
// Place). A Place resolves to at most one POI (its coordinate).
export interface Place extends EntryBase {
	kind: "place";
	/** Best-effort Gazetteer taxonomy hint (peak, hut, pass, …), or null. */
	placeType: string | null;
	/** Elevation exactly as the book prints it (e.g. "1652 m"), verbatim. */
	elevation: string | null;
	/** The single POI this Place resolves to, or null — an honest absence. */
	poi: Poi | null;
	/** Routes whose Destination (Ziel) is this Place — the routes that end here.
	 *  Waypoint links (a route's place_ids) are deliberately excluded: a route
	 *  passing through does not lead here. */
	routes: Route[];
}

// An Entry describing an itinerary — how to reach a target (CONTEXT.md: Route).
// A Route has NO geometry of its own: it is prose + verbatim-German metadata
// plus links. Its coordinate is transitive — its Destination Place's POI, never
// a direct route→POI link. Its full target set is `[destination, ...places]`.
export interface Route extends EntryBase {
	kind: "route";
	/** The `peak` string the book files the route under (verbatim, may be null). */
	peak: string | null;
	grade: string | null;
	time: string | null;
	heightM: string | null;
	firstAscent: string | null;
	/** The primary target Place — the structural parent the route is filed under
	 *  (destination_id resolved), or null when it has none. A Route's coordinate
	 *  is this Place's `poi` — transitive, never a direct link (CONTEXT.md:
	 *  Destination). */
	destination: Place | null;
	/** Additional target Places (place_ids resolved) — traverse waypoints,
	 *  disjoint from the Destination. */
	places: Place[];
}

// Every Entry is either a Place or a Route — that is its `kind` (CONTEXT.md).
export type Entry = Place | Route;

// A published Guide as the committed `guides/guides.json` manifest lists it
// (CONTEXT.md: Guide) — the digitized Alpenvereinsführer volume the whole model
// hangs under. This is the lightweight *identity + label* pair the switcher and
// the data loader speak, deliberately distinct from `GuideData` (the joined
// artifacts for ONE Guide, below): the manifest names which Guides are served
// and how they read; `GuideData` is what loading one of them yields.
export interface Guide {
	/** The short guide id keying its data URLs, e.g. "wetterstein". */
	id: string;
	/** Short massif name (e.g. "Wetterstein", "Karwendel") — titles the
	 *  overview boxes/rows, distinct from the fuller edition `label`. */
	name: string;
	/** Human copy shown in the switcher (an edition string), never a
	 *  mechanically-capitalized id. */
	label: string;
	/** The Guide's regional rectangle as `[south, west, north, east]`
	 *  (lat/lon degrees), hand-copied from the guide's config.yml bbox. Used
	 *  ONLY to draw the overview rectangle, never for load framing. */
	bbox: [number, number, number, number];
}

// The whole guide, loaded + joined once at startup by loadGuideData().
export interface GuideData {
	/** Every Entry (Places + Routes), in artifact order. */
	entries: Entry[];
	/** Every Place (mapped and unmapped) — the sidebar's primary, place-first
	 *  list derives its mapped rows from this by filtering on `poi`. */
	places: Place[];
	/** The Routes. */
	routes: Route[];
	/** Places that resolved to no POI (`poi === null`) — the "Orte ohne
	 *  Koordinate" bucket, always visible. Mirrors placelessRoutes. */
	uncoordinatedPlaces: Place[];
	/** Routes with no target Place at all — no Destination and no places — the
	 *  "Routen ohne Ort" bucket, always visible. */
	placelessRoutes: Route[];
	pois: Poi[];
	/** poi_id -> Entries that reference that POI (a Place via its coordinate, or
	 *  any Entry via a Mention). Powers the map popup's cross-links. */
	entriesByPoiId: Map<string, Entry[]>;
}
