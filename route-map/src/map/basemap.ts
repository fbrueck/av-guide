import type {
	LayerSpecification,
	RasterDEMSourceSpecification,
	RasterSourceSpecification,
	StyleSpecification,
} from "maplibre-gl";

// The app renders two base maps depending on the view mode (RouteMap.setTerrain).
// Both live in ONE combined style (buildCombinedStyle) so toggling between them
// never calls map.setStyle — it flips layer visibility and setTerrain, avoiding
// the full-style-reload flash (#121):
//
//   2D (flat)    — OpenTopoMap: a topographic raster whose baked hillshade reads
//                  well on a flat map. The default; the only base visible in 2D.
//   3D (terrain) — VersaTiles "colorful": a keyless landcover VECTOR basemap with
//                  NO baked shading. Draped over the tilted terrain mesh it lets
//                  MapLibre's own hillshade (computed from the Mapterhorn DEM) be
//                  the only relief, so the light agrees with the geometry.
//                  OpenTopoMap's baked shading would double up on the 3D surface,
//                  which is why the flat basemap is hidden in 3D.
//
// The VersaTiles layers + the hillshade start hidden, so while in 2D their tiles
// (and the DEM tiles) are NOT loaded — a hidden layer streams nothing. That keeps
// attribution honest (MapAttribution credits VersaTiles/Mapterhorn only in 3D,
// route-map/CLAUDE.md rule 3) and 2D cheap.

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
// because in 2D the VersaTiles tiles are not loaded (see MapAttribution).
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

// OpenTopoMap doubles as the source id and the layer id of the 2D raster base.
// RouteMap toggles this layer's visibility on the 2D↔3D flip.
export const OPENTOPO_SOURCE_ID = "opentopomap";

const opentopoSource: RasterSourceSpecification = {
	type: "raster",
	tiles: [
		"https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
		"https://b.tile.opentopomap.org/{z}/{x}/{y}.png",
		"https://c.tile.opentopomap.org/{z}/{x}/{y}.png",
	],
	tileSize: 256,
	maxzoom: OPENTOPO_MAX_ZOOM,
};

// 2D flat base map — the style the Map is constructed with, for an instant first
// paint. buildCombinedStyle swaps in the full combined style once it has fetched
// the VersaTiles style (an invisible swap: both show OpenTopoMap in 2D).
export const basemapStyle2d: StyleSpecification = {
	version: 8,
	sources: {
		[OPENTOPO_SOURCE_ID]: opentopoSource,
	},
	layers: [
		{
			id: OPENTOPO_SOURCE_ID,
			type: "raster",
			source: OPENTOPO_SOURCE_ID,
		},
	],
};

// The keyless VersaTiles "colorful" vector style, loaded by URL and merged into
// the combined style by buildCombinedStyle.
const VERSATILES_STYLE_URL =
	"https://tiles.versatiles.org/assets/styles/colorful/style.json";

// The single vector source id inside the VersaTiles style. RouteMap flips the
// visibility of every layer bound to it on the 2D↔3D toggle.
export const VERSATILES_SOURCE_ID = "versatiles-shortbread";

// Camera zoom cap. OpenTopoMap (source maxzoom 17) and the VersaTiles vector
// tiles both overzoom past this, so 18 is safe for either base map.
export const BASEMAP_MAX_ZOOM = 18;

// 3D terrain (#23). Mapterhorn's free terrarium-encoded DEM tiles — the exact
// source MapLibre's own 3D-terrain example streams. The raster-dem source lives
// in the combined style and is referenced by map.setTerrain when 3D is enabled.
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

const terrainSource: RasterDEMSourceSpecification = {
	type: "raster-dem",
	tiles: ["https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"],
	tileSize: 512,
	encoding: "terrarium",
};

// Separate raster-dem source (and layer) id for the hillshade, kept independent
// of the terrain mesh source (TERRAIN_SOURCE_ID) — MapLibre recommends distinct
// sources for terrain and hillshade for render quality. Doubles as the layer id
// RouteMap toggles.
export const HILLSHADE_SOURCE_ID = "mapterhorn-hillshade";

const hillshadeSource: RasterDEMSourceSpecification = {
	type: "raster-dem",
	tiles: ["https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"],
	tileSize: 512,
	encoding: "terrarium",
};

// Fetch the VersaTiles style and assemble the ONE combined style the map runs on:
// OpenTopoMap raster (2D base, visible), the customized VersaTiles layers (3D
// base, hidden), a hillshade layer (3D, hidden), and the two DEM sources resident
// so terrain can flip on with no source add. Because the VersaTiles/hillshade
// layers start hidden, their tiles are not fetched until 3D is enabled.
//
// The VersaTiles layers are customized here at build time (what customizeBasemap
// used to do imperatively on the live map): its label (symbol) layers are dropped
// — they render awkwardly on the tilted 3D surface — and forest gets a legible
// green at reduced opacity so the hillshade relief still reads through the cover
// (VersaTiles renders forest at only 0.1 opacity, so it must be raised).
export async function buildCombinedStyle(): Promise<StyleSpecification> {
	const response = await fetch(VERSATILES_STYLE_URL);
	if (!response.ok) {
		throw new Error(
			`VersaTiles style fetch failed: ${response.status} ${response.statusText}`,
		);
	}
	const versatiles = (await response.json()) as StyleSpecification;

	const versatilesLayers: LayerSpecification[] = [];
	for (const layer of versatiles.layers) {
		if (layer.type === "symbol") {
			continue;
		}
		const hidden = {
			...layer,
			layout: { ...layer.layout, visibility: "none" },
		} as LayerSpecification;
		if (hidden.id === "land-forest" && hidden.type === "fill") {
			hidden.paint = {
				...hidden.paint,
				"fill-color": "#43a047",
				"fill-opacity": 0.6,
			};
		}
		versatilesLayers.push(hidden);
	}

	return {
		version: 8,
		// Kept from the VersaTiles style so its vector layers render correctly
		// (glyphs are unused after the symbol strip, but harmless; the sprite backs
		// the fill patterns the landcover layers use).
		glyphs: versatiles.glyphs,
		sprite: versatiles.sprite,
		sources: {
			...versatiles.sources,
			[OPENTOPO_SOURCE_ID]: opentopoSource,
			[TERRAIN_SOURCE_ID]: terrainSource,
			[HILLSHADE_SOURCE_ID]: hillshadeSource,
		},
		layers: [
			// OpenTopoMap raster: the 2D base, at the bottom and visible by default;
			// hidden when 3D is on.
			{
				id: OPENTOPO_SOURCE_ID,
				type: "raster",
				source: OPENTOPO_SOURCE_ID,
			},
			// VersaTiles landcover: the 3D base, hidden (and thus unloaded) until 3D.
			...versatilesLayers,
			// Client-side hillshade computed on the GPU from the Mapterhorn DEM, light
			// locked to the compass (anchor "map") from the south-west (225°) so it
			// does not swing with the camera. Drawn over the landcover; 3D only.
			{
				id: HILLSHADE_SOURCE_ID,
				type: "hillshade",
				source: HILLSHADE_SOURCE_ID,
				layout: { visibility: "none" },
				paint: {
					"hillshade-illumination-anchor": "map",
					"hillshade-illumination-direction": 225,
					"hillshade-exaggeration": 0.5,
				},
			},
		],
	};
}
