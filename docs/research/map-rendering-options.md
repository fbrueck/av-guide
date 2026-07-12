# Rendering the AV-Guide GeoJSON on a map: open source options (2026)

Research date: 2026-07-12. All version/license claims checked against primary sources (repos, LICENSE files, official docs) on that date.

## TL;DR

- **Best 2D pick: [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js)** — BSD-3-Clause, actively developed (v5.24.0, Apr 2026), vector tiles, native GeoJSON sources, and built-in 3D terrain + hillshade. One library covers both the 2D and "2.5D/3D terrain" cases.
- **Best 3D pick: MapLibre's built-in 3D terrain** for this use case (tilt the same map, drape the same GeoJSON over a DEM). Only reach for **[CesiumJS](https://github.com/CesiumGS/cesium)** (Apache-2.0) if you need a true globe / quantized-mesh terrain — and note its hosted assets (Cesium ion) are **non-commercial on the free tier**.
- **Best basemap for the Alps:** self-hosted vector tiles as a **[PMTiles](https://docs.protomaps.com/)** file (Protomaps basemap or [OpenMapTiles](https://github.com/openmaptiles/openmaptiles) schema) — zero-server hosting on S3/CDN. Quick-start alternative: [OpenTopoMap](https://opentopomap.org/about) raster tiles (contours + hillshade out of the box, CC-BY-SA, best-effort server).
- **Best terrain tiles: [Mapterhorn](https://github.com/mapterhorn/mapterhorn)** — free public terrarium-encoded terrain tiles (`https://tiles.mapterhorn.com/{z}/{x}/{y}.webp`), built from open DEMs, positioned as the successor to the AWS/Mapzen terrain tiles, and what MapLibre's own [3D terrain example](https://maplibre.org/maplibre-gl-js/docs/examples/3d-terrain/) uses.
- **Mountaineering overlays:** [Waymarked Trails](https://wiki.openstreetmap.org/wiki/Waymarked_Trails) hiking overlay, [swisstopo slope classes >30°](https://www.geo.admin.ch/en/dataset-26012026) (open data, avalanche-relevant), [OpenSlopeMap](https://www.openslopemap.org/projekt/hintergruende-erlaeuterungen/) for Alps-wide slope shading.

---

## 2D rendering libraries

| Library | License | Latest release (checked 2026-07) | Rendering | GeoJSON input | Notes |
|---|---|---|---|---|---|
| [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js) | BSD-3-Clause | v5.24.0 (2026-04-23) | WebGL, vector tiles | [`geojson` source type](https://maplibre.org/maplibre-style-spec/sources/#geojson) + style layers (data-driven styling, clustering) | Community fork of Mapbox GL JS v1 after [Mapbox GL JS v2 moved to a proprietary license](https://github.com/mapbox/mapbox-gl-js/blob/main/LICENSE.txt) (Dec 2020). Built-in 3D terrain, hillshade layer, globe view. |
| [Leaflet](https://github.com/Leaflet/Leaflet) | BSD-2-Clause | v1.9.4 stable (2023-05-18); **v2.0 still alpha** (v2.0.0-alpha.1, 2025-08-16, per [GitHub releases](https://github.com/Leaflet/Leaflet/releases)) | DOM/Canvas, raster-tile centric | [`L.geoJSON()`](https://leafletjs.com/reference.html#geojson) | Simplest API, huge plugin ecosystem. No native vector tiles or terrain; rotation/tilt not supported. Stable branch effectively frozen while 2.0 gestates. |
| [OpenLayers](https://github.com/openlayers/openlayers) | BSD-2-Clause | v10.9.0 (2026-04-15) | Canvas + WebGL layers, vector tiles | [`ol/format/GeoJSON`](https://openlayers.org/en/latest/apidoc/module-ol_format_GeoJSON-GeoJSON.html) + `VectorLayer` | Most complete GIS feature set: first-class WMTS, custom projections (useful for swisstopo LV95 services), editing. Heavier API; no 3D (pairs with Cesium via ol-cesium). |

**Verdict:** MapLibre unless you specifically want Leaflet's simplicity or OpenLayers' WMTS/projection machinery. All three are permissively licensed and consume the repo's GeoJSON directly.

## 3D options

| Option | License | Status | Terrain input | GeoJSON input | Notes |
|---|---|---|---|---|---|
| [MapLibre GL JS 3D terrain](https://maplibre.org/maplibre-gl-js/docs/examples/3d-terrain/) | BSD-3-Clause | Active (part of core) | `raster-dem` source (terrarium or Mapbox terrain-RGB encoding); `terrain: {source, exaggeration}` in style or `map.setTerrain()` | Same `geojson` sources — symbols/lines drape onto terrain | Official example streams [Mapterhorn](https://tiles.mapterhorn.com/tilejson.json) tiles. Also gives hillshading from the same DEM. Camera stays map-like (pitch ≤ ~85°), not a free-flight globe. |
| [CesiumJS](https://github.com/CesiumGS/cesium) | Apache-2.0 | Very active (v1.143, 2026-07-01) | Quantized-mesh terrain, 3D Tiles; streams from any source | [`GeoJsonDataSource.load()`](https://cesium.com/learn/cesiumjs/ref-doc/GeoJsonDataSource.html) with `clampToGround` | True 3D globe. **Gotcha:** the library is open, but hosted assets (Cesium World Terrain, Google Photorealistic 3D Tiles) come via Cesium ion, whose [free Community tier is personal/non-commercial only](https://cesium.com/pricing/) (5 GB storage, 15 GB/mo streaming). Fully-open route: self-host terrain built from Copernicus/Sonny DEMs. |
| [deck.gl](https://github.com/visgl/deck.gl) | MIT | Active (v9.3.6, 2026-07-02) | [`TerrainLayer`](https://deck.gl/docs/api-reference/geo-layers/terrain-layer) reconstructs meshes from RGB-encoded height tiles; `elevationDecoder` handles terrarium/Mapbox encodings | [`GeoJsonLayer`](https://deck.gl/docs/api-reference/layers/geojson-layer) | Best for large-data/analytical overlays; interleaves with a MapLibre basemap. More assembly required than MapLibre terrain alone. |
| [procedural-gl-js](https://github.com/felixpalmer/procedural-gl-js) | MPL-2.0 | **Unmaintained** — last commit 2021-04-16 (GitHub API) | own terrain streaming | overlay JSON | Beautiful demos, but dead for 5 years. **Avoid.** |
| [three-geo](https://github.com/w3reality/three-geo) | MIT | **Dormant** — last release v1.4.5 (2022-06); sparse commits since (last 2025-02) | builds three.js terrain from RGB DEM tiles | manual | Fine for experiments; not a foundation. |

**Verdict:** MapLibre's raster-dem terrain gives you 90% of the "fly around the Bernina in 3D" value with zero extra dependencies. CesiumJS is the serious step up, at the cost of a second stack and license care around ion-hosted content.

## Basemap / tile sources for the Alps

| Source | Coverage | License / terms | Format | Mountaineering value |
|---|---|---|---|---|
| [OpenStreetMap](https://www.openstreetmap.org) data | global | Data: ODbL. osm.org raster tiles are donated infra under a [strict usage policy](https://operations.osmfoundation.org/policies/tiles/) — not for production apps | raster / raw data | The data everything below is built from; huts, paths, via ferratas all in OSM. |
| [OpenTopoMap](https://opentopomap.org/about) | global | Tiles CC-BY-SA; attribution "Kartendaten: © OpenStreetMap-Mitwirkende, SRTM \| Kartendarstellung: © OpenTopoMap (CC-BY-SA)"; best-effort server, they ask to be notified of embedding | raster `{a\|b\|c}.tile.opentopomap.org/{z}/{x}/{y}.png` | Alpine-club-style cartography: contours + hillshading built in. Fastest possible start. |
| [Protomaps / PMTiles](https://docs.protomaps.com/) | global | Software BSD, basemap data ODbL | **PMTiles single-file archive** served via HTTP range requests from S3/CDN — no tile server | Best self-hosting story; official MapLibre/Leaflet/OpenLayers integrations. |
| [OpenMapTiles](https://github.com/openmaptiles/openmaptiles) | global | Code BSD, schema/cartography CC-BY (visible "OpenMapTiles.org" credit required), data ODbL | vector tiles (self-generate); active — v3.16, 2025-12-18 | The standard vector-tile schema; many open styles fit it. More pipeline work than Protomaps. |
| [swisstopo](https://shop.swisstopo.admin.ch/en/free-geodata) | CH + border | **Open data since 1 Mar 2021**; free incl. commercial use, attribution "©swisstopo" required ([terms](https://www.swisstopo.admin.ch/en/terms-of-use-free-geodata-and-geoservices)); access may be throttled for excessive geoservice use | WMTS/WMS (national maps, orthophotos), downloads; also vector tiles | The best mountain cartography in existence for the Swiss Alps (ski + hiking route layers, SAC huts). |
| [basemap.at](https://basemap.at/en/) | AT | Open Government Data Austria, **CC-BY 4.0**, commercial use OK, credit "basemap.at" | raster + **vector tiles**, incl. contour product (BMAPVHL), 1 m terrain/surface shading, 29 cm orthophoto | Official Austrian basemap — ideal for the Eastern Alps guidebook areas. |
| [basemap.de](https://basemap.de/open-data/) | DE | mostly dl-de/BY-2.0 (attribution) or dl-de/zero per Land | vector tiles, raster, GeoPackage | Only relevant for the Bavarian Alps fringe. |
| [MapTiler Cloud](https://www.maptiler.com/cloud/pricing/) | global (hosted service, **not** open infra) | Free tier: 100k requests/mo, 5k map sessions, MapTiler logo required, **non-commercial/testing only** | vector + raster + terrain-RGB | Convenient, but a vendor dependency with tier limits. |
| [Stadia Maps](https://stadiamaps.com/pricing/) | global (hosted service) | Free tier 200k credits/mo, **commercial use not allowed** | vector + raster | Same caveat as MapTiler. |

## Terrain / elevation sources for 3D

| Source | Resolution / coverage | License | Format | Notes |
|---|---|---|---|---|
| [Mapterhorn](https://github.com/mapterhorn/mapterhorn) | global tiles, higher-res where open DEMs exist | code BSD-3-Clause; data per-source, see [attribution page](https://mapterhorn.com/attribution) | terrarium-encoded WebP, 512 px, free endpoint `tiles.mapterhorn.com/{z}/{x}/{y}.webp` | Active (v0.0.11, 2026-05-12); explicitly a replacement for AWS elevation tiles; used by MapLibre's official terrain example. **First choice.** |
| [AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) (Mapzen/Tilezen) | global, ~30 m-class in the Alps (SRTM-era mix) | open, [attribution per source](https://github.com/tilezen/joerd/blob/master/docs/attribution.md) | terrarium/normal/GeoTIFF/skadi on `s3://elevation-tiles-prod` (+ EU replica) | Still available (verified 2026-07), but dated source DEMs; Mapterhorn supersedes it. |
| [Copernicus DEM GLO-30](https://registry.opendata.aws/copernicus-dem/) | 30 m global | free worldwide license, attribution notice required ([license PDF](https://docs.sentinel-hub.com/api/latest/static/files/data/dem/resources/license/License-COPDEM-30.pdf)) | GeoTIFF (raw DEM) | The modern baseline DEM; input if you build your own terrain tiles. |
| [Sonny's LiDAR DTMs](https://sonny.4lima.de/) | **0.5″/10 m for the alpine countries**, 1″/3″ Europe-wide | **CC-BY 4.0** (credit Sonny + link) | .hgt / GeoTIFF downloads | Verified real and current (Europe v25, updated 2025-08). Best open high-res DEM covering the *whole* Alps — raw data, needs tiling (e.g., to terrain-RGB/terrarium). |
| [swisstopo swissALTI3D](https://www.swisstopo.admin.ch/en/height-model-swissalti3d) | 0.5 m, CH only | swisstopo OGD (free, attribution) | GeoTIFF/XYZ | Ultra-high-res but Switzerland only. |
| MapTiler terrain-RGB | global (hosted) | MapTiler Cloud free-tier terms (see above) | terrain-RGB tiles | Easiest hosted option; same vendor caveats. |

## Mountaineering-specific overlays

- **Contours + hillshading:** free with OpenTopoMap raster tiles; as vector data via basemap.at BMAPVHL (AT) or self-generated from DEMs. In MapLibre you get **hillshade for free** from any `raster-dem` source via the [`hillshade` layer type](https://maplibre.org/maplibre-style-spec/layers/#hillshade) — same tiles that power 3D terrain.
- **Hiking routes:** [Waymarked Trails](https://wiki.openstreetmap.org/wiki/Waymarked_Trails) renders OSM hiking relations as a transparent overlay, tile server `https://tile.waymarkedtrails.org/hiking/{z}/{x}/{y}.png` (site code GPLv3, data ODbL). Caveat: I could not find a formal published tile-usage policy (the old `/help/legal` URL 404s); it is volunteer-run infrastructure, so treat as best-effort and cache politely.
- **Slope-angle (avalanche/steepness):**
  - [swisstopo "Slope classes over 30°"](https://www.geo.admin.ch/en/dataset-26012026) (`ch.swisstopo.hangneigung-ueber_30` [WMTS/WMS](https://opendata.swiss/en/dataset/hangneigungsklassen-ab-30-grad)): 10 m DEM-derived classes incl. a new >50° class added with SLF and SAC input; covers CH/LI **plus border terrain from FR/IT/AT/DE DEMs**; free under swisstopo OGD.
  - [OpenSlopeMap](https://www.openslopemap.org/projekt/hintergruende-erlaeuterungen/): community slope-angle map for alpinists/ski tourers covering the Alps, offered via WMTS and offline MBTiles; site maintained (© 2026). Check their [license page](https://www.openslopemap.org/projekt/lizenzen/) per-region before redistribution.
- **Ski touring / pistes:** [OpenSnowMap](https://www.opensnowmap.org/) — worldwide piste/ski-route overlay from OSM (ODbL) + open DEMs.

## How each option consumes this repo's GeoJSON

| Renderer | One-liner |
|---|---|
| MapLibre | `map.addSource('poi', {type:'geojson', data:'/objectives.geojson'})` + `symbol`/`line` layers; supports clustering and data-driven styling ([spec](https://maplibre.org/maplibre-style-spec/sources/#geojson)) |
| Leaflet | `L.geoJSON(data, {onEachFeature}).addTo(map)` ([docs](https://leafletjs.com/reference.html#geojson)) |
| OpenLayers | `new VectorLayer({source: new VectorSource({url, format: new GeoJSON()})})` ([docs](https://openlayers.org/en/latest/apidoc/module-ol_format_GeoJSON-GeoJSON.html)) |
| CesiumJS | `viewer.dataSources.add(Cesium.GeoJsonDataSource.load(url, {clampToGround:true}))` ([docs](https://cesium.com/learn/cesiumjs/ref-doc/GeoJsonDataSource.html)) |
| deck.gl | `new GeoJsonLayer({data: url, ...})` ([docs](https://deck.gl/docs/api-reference/layers/geojson-layer)) |

## Suggested stack for av-guide

1. **Renderer: MapLibre GL JS** (BSD-3). One library, 2D + 3D terrain + hillshade + GeoJSON, no API key required.
2. **Basemap:** start with **OpenTopoMap raster** (instant alpine cartography) behind a config switch; graduate to a **self-hosted PMTiles vector basemap** (Protomaps build clipped to the Alps) for production — a single file on S3/CDN, no tile server, no vendor terms.
3. **Terrain (3D + hillshade): Mapterhorn terrarium tiles** as the `raster-dem` source. If you later want sharper relief, tile **Sonny's CC-BY 10 m Alps DTMs** (or swissALTI3D for CH) into your own terrarium PMTiles.
4. **Overlays:** Waymarked Trails hiking overlay as an optional raster layer; swisstopo slope-classes WMTS for the ski-touring view (CH + border areas); render the guidebook's peaks/huts/routes GeoJSON on top with `symbol` + `line` layers, clustered at low zooms.
5. **Skip:** procedural-gl (unmaintained since 2021), three-geo (dormant); use CesiumJS only if a true globe becomes a requirement — and then self-host terrain rather than relying on the non-commercial Cesium ion free tier.
