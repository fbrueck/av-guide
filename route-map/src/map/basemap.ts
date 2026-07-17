import type {
	RasterDEMSourceSpecification,
	StyleSpecification,
} from "maplibre-gl";

// OpenTopoMap raster tiles. maxzoom 17 is the service's limit; the map clamps
// to it so we never request tiles that don't exist.
const OPENTOPO_MAX_ZOOM = 17;

// A single map credit: the linked source name plus the plain text that frames
// it. Structured (not an HTML string) so the React attribution component
// (src/components/MapAttribution.tsx) renders real anchors — this module is the
// single source of truth for the credits, and it no longer feeds a maplibre
// AttributionControl (the app owns attribution in the DOM, not the library).
export interface MapCredit {
	/** Text before the linked source name, e.g. "Kartendaten: © ". */
	readonly prefix: string;
	readonly name: string;
	readonly href: string;
	/** Text after the linked source name, e.g. " (CC-BY-SA)". */
	readonly suffix: string;
}

// Attribution required by the fetch-pois README: OpenStreetMap contributors +
// the OpenTopoMap (CC-BY-SA) rendering credit. The English "© OpenStreetMap
// contributors" wording is kept alongside the German original.
export const BASEMAP_CREDITS: readonly MapCredit[] = [
	{
		prefix: "Kartendaten: © ",
		name: "OpenStreetMap",
		href: "https://openstreetmap.org/copyright",
		suffix: "-Mitwirkende (© OpenStreetMap contributors), SRTM",
	},
	{
		prefix: "Kartendarstellung: © ",
		name: "OpenTopoMap",
		href: "https://opentopomap.org",
		suffix: " (CC-BY-SA)",
	},
];

const OPENTOPO_SOURCE_ID = "opentopomap";

export const topoBasemapStyle: StyleSpecification = {
	version: 8,
	sources: {
		[OPENTOPO_SOURCE_ID]: {
			type: "raster",
			tiles: [
				"https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
				"https://b.tile.opentopomap.org/{z}/{x}/{y}.png",
				"https://c.tile.opentopomap.org/{z}/{x}/{y}.png",
			],
			tileSize: 256,
			maxzoom: OPENTOPO_MAX_ZOOM,
		},
	},
	layers: [
		{
			id: OPENTOPO_SOURCE_ID,
			type: "raster",
			source: OPENTOPO_SOURCE_ID,
		},
	],
};

export const BASEMAP_MAX_ZOOM = OPENTOPO_MAX_ZOOM;

// 3D terrain (#23). Mapterhorn's free terrarium-encoded DEM tiles — the exact
// source MapLibre's own 3D-terrain example streams. The raster-dem source is
// added on demand by RouteMap.setTerrain and draped under the 2D basemap; the
// flat map is restored by clearing the terrain, so no separate 3D style exists.
export const TERRAIN_SOURCE_ID = "mapterhorn-terrain";

// The terrain credit, surfaced by the React attribution component only while
// terrain is enabled (the DEM tiles are not loaded otherwise, so crediting them
// on the flat map would be dishonest).
export const TERRAIN_CREDIT: MapCredit = {
	prefix: "Gelände: © ",
	name: "Mapterhorn",
	href: "https://mapterhorn.com/attribution",
	suffix: "",
};

// A modest vertical exaggeration reads as relief without caricaturing the Alps.
export const TERRAIN_EXAGGERATION = 1.4;

// Pitch the camera up on enable so the relief is visibly 3D; reset to flat off.
export const TERRAIN_PITCH = 60;

export const terrainSource: RasterDEMSourceSpecification = {
	type: "raster-dem",
	tiles: ["https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"],
	tileSize: 512,
	encoding: "terrarium",
};
