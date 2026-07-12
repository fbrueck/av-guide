import type { StyleSpecification } from "maplibre-gl";

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
