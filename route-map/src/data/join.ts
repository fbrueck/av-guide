import type { GuideData, Poi, Route } from "../domain";
import type {
	RawArtifacts,
	RawPoiFeature,
	RawRoute,
	RawRoutePoiLink,
} from "./contracts";

// PURE raw -> domain join (route-map/CLAUDE.md rule 2 + Testing). No fetch, no
// DOM, no globals — just data in, domain out — so it is unit-tested in Vitest.
// "Trust the types, guard the seams": TypeScript describes the raw shapes; here
// we do cheap explicit guards where drift would otherwise cause a silent wrong
// render or an opaque crash, and handle misses HONESTLY — skip + console.warn
// so pipeline drift is visible. No schema library.

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

function toRoute(raw: RawRoute): Route | null {
	if (typeof raw.route_id !== "string") {
		console.warn("[data] skipping route without route_id", raw);
		return null;
	}
	return {
		id: raw.route_id,
		name: raw.name,
		peak: raw.peak,
		grade: raw.grade,
		time: raw.time,
		heightM: raw.height_m,
		firstAscent: raw.first_ascent,
		summary: raw.summary,
		description: raw.description,
		anchor: null,
		mentions: [],
	};
}

// Join the three artifacts into the domain graph: resolve every route_pois link
// to its Poi and attach it to the Route (anchor when is_anchor, else mention),
// and index Routes by referenced poi_id for the popup cross-links.
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

	const routes: Route[] = [];
	const routeById = new Map<string, Route>();
	if (!Array.isArray(raw.routes)) {
		console.warn("[data] routes.json is not an array; no Routes loaded");
	} else {
		for (const rawRoute of raw.routes) {
			const route = toRoute(rawRoute);
			if (route) {
				routes.push(route);
				routeById.set(route.id, route);
			}
		}
	}

	const routesByPoiId = new Map<string, Route[]>();
	const links: RawRoutePoiLink[] = Array.isArray(raw.links) ? raw.links : [];
	for (const link of links) {
		if (typeof link?.route_id !== "string" || typeof link.poi_id !== "string") {
			console.warn("[data] skipping malformed route_pois link", link);
			continue;
		}
		const route = routeById.get(link.route_id);
		if (!route) {
			console.warn(
				`[data] link references unknown route_id "${link.route_id}"; skipping`,
			);
			continue;
		}
		const poi = poiById.get(link.poi_id);
		if (!poi) {
			console.warn(
				`[data] link (route "${link.route_id}") references unknown poi_id "${link.poi_id}"; skipping`,
			);
			continue;
		}
		if (link.is_anchor) {
			route.anchor = poi;
		} else {
			route.mentions.push(poi);
		}
		const referencing = routesByPoiId.get(poi.id);
		if (referencing) {
			if (!referencing.includes(route)) {
				referencing.push(route);
			}
		} else {
			routesByPoiId.set(poi.id, [route]);
		}
	}

	return { routes, pois, routesByPoiId };
}
