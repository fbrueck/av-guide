import {
	BASEMAP_CREDITS,
	BASEMAP_CREDITS_3D,
	type MapCredit,
	TERRAIN_CREDIT,
} from "../map";

interface MapAttributionProps {
	// Terrain-enabled is also the 3D-base-map flag: enabling terrain swaps the
	// flat OpenTopoMap for the VersaTiles landcover map and adds the Mapterhorn
	// relief, so the credits change with it. The terrain credit is shown only
	// while terrain is enabled — the Mapterhorn DEM tiles are not loaded on the
	// flat map, so crediting them there would be dishonest (route-map/CLAUDE.md
	// rule 3 — render honestly).
	terrainEnabled: boolean;
}

// The map's license-required attribution (OSM data, OpenTopoMap rendering, and —
// when terrain is on — Mapterhorn relief). Rendered as our own React overlay
// instead of maplibre's AttributionControl so it can be COLLAPSED BY DEFAULT: a
// native <details> starts closed (a small ⓘ in the corner) and opens the credits
// on click. This mirrors MapLibre's accepted compact presentation — the credits
// are one click away — while giving us the declarative collapsed default the
// library itself does not offer. It reads the credits from src/map (the single
// source of truth), so the two can never drift.
export function MapAttribution({ terrainEnabled }: MapAttributionProps) {
	const credits: readonly MapCredit[] = terrainEnabled
		? [...BASEMAP_CREDITS_3D, TERRAIN_CREDIT]
		: BASEMAP_CREDITS;
	return (
		<details className="map-attribution">
			<summary
				className="map-attribution__toggle"
				title="Kartennachweis"
				aria-label="Kartennachweis anzeigen"
			>
				ⓘ
			</summary>
			<div className="map-attribution__body">
				{credits.map((credit) => (
					<span key={credit.name} className="map-attribution__credit">
						{credit.prefix}
						<a href={credit.href} target="_blank" rel="noreferrer">
							{credit.name}
						</a>
						{credit.suffix}
					</span>
				))}
			</div>
		</details>
	);
}
