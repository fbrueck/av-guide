interface TerrainToggleProps {
	enabled: boolean;
	onToggle: (enabled: boolean) => void;
}

// The 2D/3D-terrain switch (#23). Presentational only: it reflects the App's
// terrainEnabled state atom and reports intent back; App drives the map through
// its imperative setTerrain API (route-map/CLAUDE.md rules 4 + 5). Sits in the
// map pane's top-left corner, under the POI legend.
export function TerrainToggle({ enabled, onToggle }: TerrainToggleProps) {
	return (
		<button
			type="button"
			className="terrain-toggle"
			aria-pressed={enabled}
			onClick={() => onToggle(!enabled)}
		>
			{enabled ? "3D-Gelände: an" : "3D-Gelände: aus"}
		</button>
	);
}
