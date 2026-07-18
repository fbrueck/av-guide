import type { Basemap2dId } from "../map";

interface Basemap2dSwitcherProps {
	active: Basemap2dId;
	onSelect: (base: Basemap2dId) => void;
}

// The label shown for each 2D base. Proper names (route-map/CLAUDE.md rule 7 —
// domain/user-facing vocabulary), ordered default-first.
const OPTIONS: readonly { id: Basemap2dId; label: string }[] = [
	{ id: "opentopomap", label: "OpenTopoMap" },
	{ id: "skitourenguru", label: "Skitourenguru" },
];

// The flat 2D base-map switcher (#135). Presentational only: it reflects App's
// base2d state atom and reports the chosen id back; App drives the map through
// its imperative setBaseMap API (route-map/CLAUDE.md rules 4 + 5). A small
// segmented control, rendered only in 2D — App unmounts it while terrain is on,
// where the choice has no visible effect (the VersaTiles landcover is the base).
export function Basemap2dSwitcher({
	active,
	onSelect,
}: Basemap2dSwitcherProps) {
	return (
		// A <fieldset> is the semantic group for a set of related controls; its
		// default chrome (border/margin/padding) is reset in .basemap-switcher.
		<fieldset className="basemap-switcher" aria-label="Kartenhintergrund (2D)">
			{OPTIONS.map((option) => (
				<button
					key={option.id}
					type="button"
					className="basemap-switcher__option"
					aria-pressed={active === option.id}
					onClick={() => onSelect(option.id)}
				>
					{option.label}
				</button>
			))}
		</fieldset>
	);
}
