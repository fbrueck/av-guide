import type { Entry, GuideData, Place, Poi, Reference, Route } from "../domain";
import type {
	RawArtifacts,
	RawEntry,
	RawEntryPoiLink,
	RawPlacePoiLink,
	RawPoiFeature,
} from "./contracts";

// PURE raw -> domain join (route-map/CLAUDE.md rule 2 + Testing). No fetch, no
// DOM, no globals — just data in, domain out — so it is unit-tested in Vitest.
// "Trust the types, guard the seams": TypeScript describes the raw shapes; here
// we do cheap explicit guards where drift would otherwise cause a silent wrong
// render or an opaque crash, and handle misses HONESTLY — skip + console.warn
// so pipeline drift is visible. No schema library.
//
// The Entry model (#44, CONTEXT.md, ADR 0002): entries split into Places and
// Routes by `kind`; a Place resolves to <=1 POI (place_pois); a Route's
// coordinate is transitive via its Destination Place (destination_id -> Place ->
// POI) and it may name further target Places (place_ids); mentions are
// Entry-general (entry_pois, over any Entry's prose); References resolve
// id-to-id to Entries (dangling -> warn, honest drift).

// Build the openstreetmap.org deep link from the raw `osm` value. The value is
// "<type>/<id>" (way/370669072, node/…, relation/…); openstreetmap.org uses the
// same path, so this is a prefix. A malformed value is passed through as-is
// under the base URL rather than dropped — the POI is still worth showing.
export function osmUrlFor(osm: string): string {
	return `https://www.openstreetmap.org/${osm}`;
}

function toPoi(feature: RawPoiFeature): Poi | null {
	const props = feature.properties;
	if (!props || typeof props.poi_id !== "string") {
		console.warn("[data] skipping POI feature without poi_id", feature);
		return null;
	}
	const coords = feature.geometry?.coordinates;
	if (
		!Array.isArray(coords) ||
		typeof coords[0] !== "number" ||
		typeof coords[1] !== "number"
	) {
		console.warn(
			`[data] skipping POI ${props.poi_id}: missing point coordinates`,
		);
		return null;
	}
	return {
		id: props.poi_id,
		name: props.name,
		type: props.type,
		ele: typeof props.ele === "number" ? props.ele : null,
		osm: props.osm,
		osmUrl: osmUrlFor(props.osm),
		coordinates: [coords[0], coords[1]],
	};
}

// One Entry from a raw record, discriminated by `kind`. Place and Route share
// the prose + link fields (mentions/references), populated empty here and filled
// as the link artifacts are joined. An unknown kind is drift — skip + warn.
function toEntry(raw: RawEntry): Entry | null {
	if (typeof raw.id !== "string") {
		console.warn("[data] skipping entry without id", raw);
		return null;
	}
	const base = {
		id: raw.id,
		name: raw.name,
		summary: raw.summary,
		description: raw.description,
		mentions: [] as Poi[],
		references: [] as Reference[],
	};
	if (raw.kind === "place") {
		const place: Place = {
			...base,
			kind: "place",
			placeType: raw.place_type,
			elevation: raw.elevation,
			poi: null,
			routes: [],
		};
		return place;
	}
	if (raw.kind === "route") {
		const route: Route = {
			...base,
			kind: "route",
			peak: raw.peak,
			grade: raw.grade,
			time: raw.time,
			heightM: raw.height_m,
			firstAscent: raw.first_ascent,
			destination: null,
			places: [],
		};
		return route;
	}
	console.warn(`[data] skipping entry "${raw.id}" with unknown kind`, raw.kind);
	return null;
}

// Record that `entry` references `poi`, de-duplicated per (poi, entry). Used for
// both a Place's own coordinate and any Entry's Mentions, so the popup lists
// every distinct Entry behind a POI exactly once.
function indexEntryByPoi(
	entriesByPoiId: Map<string, Entry[]>,
	poiId: string,
	entry: Entry,
): void {
	const referencing = entriesByPoiId.get(poiId);
	if (referencing) {
		if (!referencing.includes(entry)) {
			referencing.push(entry);
		}
	} else {
		entriesByPoiId.set(poiId, [entry]);
	}
}

// Join the artifacts into the domain graph: build POIs + Entries, then resolve
// place_pois (Place -> POI), entry_pois (Entry Mentions -> POI), destination_id
// + place_ids (Route -> target Places, transitive coordinate) and references
// (Entry -> Entry). Misses are warned + skipped so pipeline drift stays visible.
export function joinGuideData(raw: RawArtifacts): GuideData {
	const pois: Poi[] = [];
	const poiById = new Map<string, Poi>();
	if (!Array.isArray(raw.pois?.features)) {
		console.warn("[data] pois.geojson has no feature array; no POIs loaded");
	} else {
		for (const feature of raw.pois.features) {
			const poi = toPoi(feature);
			if (poi) {
				pois.push(poi);
				poiById.set(poi.id, poi);
			}
		}
	}

	const entries: Entry[] = [];
	const entryById = new Map<string, Entry>();
	if (!Array.isArray(raw.entries)) {
		console.warn("[data] routes.json is not an array; no Entries loaded");
	} else {
		for (const rawEntry of raw.entries) {
			const entry = toEntry(rawEntry);
			if (entry) {
				entries.push(entry);
				entryById.set(entry.id, entry);
			}
		}
	}

	const entriesByPoiId = new Map<string, Entry[]>();

	// place_pois: a Place's single resolved POI — its coordinate.
	const placeLinks: RawPlacePoiLink[] = Array.isArray(raw.placeLinks)
		? raw.placeLinks
		: [];
	for (const link of placeLinks) {
		if (typeof link?.place_id !== "string" || typeof link.poi_id !== "string") {
			console.warn("[data] skipping malformed place_pois link", link);
			continue;
		}
		const entry = entryById.get(link.place_id);
		if (!entry) {
			console.warn(
				`[data] place link references unknown place_id "${link.place_id}"; skipping`,
			);
			continue;
		}
		if (entry.kind !== "place") {
			console.warn(
				`[data] place link place_id "${link.place_id}" is a ${entry.kind}, not a Place; skipping`,
			);
			continue;
		}
		const poi = poiById.get(link.poi_id);
		if (!poi) {
			console.warn(
				`[data] place link (place "${link.place_id}") references unknown poi_id "${link.poi_id}"; skipping`,
			);
			continue;
		}
		entry.poi = poi;
		indexEntryByPoi(entriesByPoiId, poi.id, entry);
	}

	// entry_pois: Entry-general Mentions -> POI.
	const entryLinks: RawEntryPoiLink[] = Array.isArray(raw.entryLinks)
		? raw.entryLinks
		: [];
	for (const link of entryLinks) {
		if (typeof link?.entry_id !== "string" || typeof link.poi_id !== "string") {
			console.warn("[data] skipping malformed entry_pois link", link);
			continue;
		}
		const entry = entryById.get(link.entry_id);
		if (!entry) {
			console.warn(
				`[data] mention link references unknown entry_id "${link.entry_id}"; skipping`,
			);
			continue;
		}
		const poi = poiById.get(link.poi_id);
		if (!poi) {
			console.warn(
				`[data] mention link (entry "${link.entry_id}") references unknown poi_id "${link.poi_id}"; skipping`,
			);
			continue;
		}
		entry.mentions.push(poi);
		indexEntryByPoi(entriesByPoiId, poi.id, entry);
	}

	// destination_id + place_ids + references need every Entry present, so
	// resolve them after the full entry index is built. A Route's coordinate stays
	// transitive: we link the target Place, never a direct route->POI edge.
	const routes: Route[] = [];
	const places: Place[] = [];
	for (const entry of entries) {
		if (entry.kind === "place") {
			places.push(entry);
		} else {
			routes.push(entry);
		}
	}

	const rawById = new Map<string, RawEntry>();
	if (Array.isArray(raw.entries)) {
		for (const rawEntry of raw.entries) {
			if (typeof rawEntry?.id === "string") {
				rawById.set(rawEntry.id, rawEntry);
			}
		}
	}

	// Resolve one target Place id to a Place, recording the route on that Place's
	// routes-leading-here list. Returns the Place, or null on a miss (warned).
	// `role` labels the warning so destination/place drift is told apart.
	function resolveTargetPlace(
		route: Route,
		placeId: string,
		role: "destination_id" | "place_id",
	): Place | null {
		const target = entryById.get(placeId);
		if (!target) {
			console.warn(
				`[data] route "${route.id}" ${role} "${placeId}" resolves to no Entry; skipping`,
			);
			return null;
		}
		if (target.kind !== "place") {
			console.warn(
				`[data] route "${route.id}" ${role} "${placeId}" is a ${target.kind}, not a Place; skipping`,
			);
			return null;
		}
		// The Place's routes-leading-here list (de-duplicated).
		if (!target.routes.includes(route)) {
			target.routes.push(route);
		}
		return target;
	}

	for (const route of routes) {
		const rawEntry = rawById.get(route.id);
		const destinationId =
			typeof rawEntry?.destination_id === "string"
				? rawEntry.destination_id
				: null;
		if (destinationId !== null) {
			route.destination = resolveTargetPlace(
				route,
				destinationId,
				"destination_id",
			);
		}
		const placeIds = Array.isArray(rawEntry?.place_ids)
			? rawEntry.place_ids
			: [];
		for (const placeId of placeIds) {
			const place = resolveTargetPlace(route, placeId, "place_id");
			if (place) {
				route.places.push(place);
			}
		}
	}

	// references: id-to-id to a target Entry. A null ref_id is anaphora ("wie
	// dort") — inherently unresolvable, kept with a null target, not warned. A
	// non-null ref_id with no matching Entry is dangling drift — warned.
	for (const entry of entries) {
		const rawEntry = rawById.get(entry.id);
		const rawRefs = Array.isArray(rawEntry?.references)
			? rawEntry.references
			: [];
		for (const rawRef of rawRefs) {
			const refId = rawRef?.ref_id ?? null;
			let target: Entry | null = null;
			if (refId !== null) {
				target = entryById.get(refId) ?? null;
				if (!target) {
					console.warn(
						`[data] entry "${entry.id}" reference "${refId}" resolves to no Entry (dangling)`,
					);
				}
			}
			entry.references.push({
				refId,
				surface: rawRef?.surface ?? "",
				target,
			});
		}
	}

	// A Route is unfiled only when it has no target Place at all — no Destination
	// and no places (an honest "not linked to anywhere" bucket).
	const unfiledRoutes = routes.filter(
		(route) => route.destination === null && route.places.length === 0,
	);

	return { entries, places, routes, unfiledRoutes, pois, entriesByPoiId };
}
