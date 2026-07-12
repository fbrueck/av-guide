import type {
	RasterDEMSourceSpecification,
	StyleSpecification,
} from "maplibre-gl";

// OpenTopoMap raster tiles. maxzoom 17 is the service's limit; the map clamps
// to it so we never request tiles that don't exist.
const OPENTOPO_MAX_ZOOM = 17;

// Attribution required by the fetch-pois README: OpenStreetMap contributors +
// the OpenTopoMap (CC-BY-SA) rendering credit. The English "© OpenStreetMap
// contributors" wording is kept alongside the German original.
export const BASEMAP_ATTRIBUTION =
	'Kartendaten: © <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende ' +
	"(© OpenStreetMap contributors), SRTM | " +
	'Kartendarstellung: © <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)';

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
			attribution: BASEMAP_ATTRIBUTION,
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

// Attribution set ON the source so the existing AttributionControl surfaces the
// terrain credit automatically alongside the OSM/OpenTopoMap ones.
export const TERRAIN_ATTRIBUTION =
	'Gelände: © <a href="https://mapterhorn.com/attribution">Mapterhorn</a>';

// A modest vertical exaggeration reads as relief without caricaturing the Alps.
export const TERRAIN_EXAGGERATION = 1.4;

// Pitch the camera up on enable so the relief is visibly 3D; reset to flat off.
export const TERRAIN_PITCH = 60;

export const terrainSource: RasterDEMSourceSpecification = {
	type: "raster-dem",
	tiles: ["https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"],
	tileSize: 512,
	encoding: "terrarium",
	attribution: TERRAIN_ATTRIBUTION,
};
