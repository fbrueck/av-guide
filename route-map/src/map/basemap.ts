import type {
	Map as MapLibreMap,
	RasterDEMSourceSpecification,
	StyleSpecification,
} from "maplibre-gl";

// The app renders two base maps depending on the view mode (RouteMap.setTerrain):
//
//   2D (flat)    — OpenTopoMap: a topographic raster whose baked hillshade reads
//                  well on a flat map.
//   3D (terrain) — VersaTiles "colorful": a keyless landcover VECTOR basemap with
//                  NO baked shading. Draped over the tilted terrain mesh it lets
//                  MapLibre's own hillshade (computed from the Mapterhorn DEM by
//                  customizeBasemap) be the only relief, so the light agrees with
//                  the geometry. OpenTopoMap's baked shading would double up on the
//                  3D surface, which is why the flat basemap is swapped out in 3D.

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

// Credits for the 2D base map (OpenTopoMap): OpenStreetMap data + the OpenTopoMap
// (CC-BY-SA) rendering credit. The English "© OpenStreetMap contributors" wording
// is kept alongside the German original.
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

// Credits for the 3D base map (VersaTiles "colorful"): OpenStreetMap data +
// VersaTiles rendering. Shown in place of BASEMAP_CREDITS while terrain is on,
// because in 3D the OpenTopoMap tiles are not loaded (see MapAttribution).
export const BASEMAP_CREDITS_3D: readonly MapCredit[] = [
	{
		prefix: "Kartendaten: © ",
		name: "OpenStreetMap",
		href: "https://openstreetmap.org/copyright",
		suffix: "-Mitwirkende (© OpenStreetMap contributors)",
	},
	{
		prefix: "Kartendarstellung: © ",
		name: "VersaTiles",
		href: "https://versatiles.org",
		suffix: "",
	},
];

const OPENTOPO_SOURCE_ID = "opentopomap";

// 2D flat base map — the default.
export const basemapStyle2d: StyleSpecification = {
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

// 3D landcover base map — a keyless VersaTiles vector style, loaded by URL.
// customizeBasemap post-processes it (strip labels, recolour forest, add the
// calculated hillshade) once it has loaded.
export const basemapStyle3d =
	"https://tiles.versatiles.org/assets/styles/colorful/style.json";

// Camera zoom cap. OpenTopoMap (source maxzoom 17) and the VersaTiles vector
// tiles both overzoom past this, so 18 is safe for either base map.
export const BASEMAP_MAX_ZOOM = 18;

// 3D terrain (#23). Mapterhorn's free terrarium-encoded DEM tiles — the exact
// source MapLibre's own 3D-terrain example streams. The raster-dem source is
// added on demand by RouteMap.setTerrain and draped under the base map.
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

// Separate raster-dem source id for the hillshade layer, kept independent of the
// terrain mesh source (TERRAIN_SOURCE_ID) — MapLibre recommends distinct sources
// for terrain and hillshade for render quality.
const HILLSHADE_SOURCE_ID = "mapterhorn-hillshade";

// Post-process the freshly-loaded VersaTiles (3D) style: drop its labels, give
// forest a legible green, and drape MapLibre's calculated hillshade. Idempotent,
// so it is safe to run each time the 3D style (re)loads.
export function customizeBasemap(map: MapLibreMap): void {
	// 1. Strip every label (symbol) layer — labels render awkwardly on the tilted
	//    3D surface.
	for (const layer of map.getStyle().layers ?? []) {
		if (layer.type === "symbol") {
			map.removeLayer(layer.id);
		}
	}

	// 2. Forest: a legible green at reduced opacity so the hillshade relief still
	//    reads through the tree cover. VersaTiles renders forest at only 0.1
	//    opacity by default, so the opacity must be raised for the colour to show.
	if (map.getLayer("land-forest")) {
		map.setPaintProperty("land-forest", "fill-color", "#43a047");
		map.setPaintProperty("land-forest", "fill-opacity", 0.6);
	}

	// 3. Client-side hillshade computed on the GPU from the Mapterhorn DEM. Light
	//    locked to the compass (anchor "map") from the south-west (225°) so it does
	//    not swing with the camera, draped over the landcover fills.
	if (!map.getSource(HILLSHADE_SOURCE_ID)) {
		map.addSource(HILLSHADE_SOURCE_ID, {
			type: "raster-dem",
			tiles: ["https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"],
			tileSize: 512,
			encoding: "terrarium",
		});
	}
	if (!map.getLayer(HILLSHADE_SOURCE_ID)) {
		map.addLayer({
			id: HILLSHADE_SOURCE_ID,
			type: "hillshade",
			source: HILLSHADE_SOURCE_ID,
			paint: {
				"hillshade-illumination-anchor": "map",
				"hillshade-illumination-direction": 225,
				"hillshade-exaggeration": 0.5,
			},
		});
	}
}
