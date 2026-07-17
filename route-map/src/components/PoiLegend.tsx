import { useState } from "react";
import { POI_TYPE_STYLES } from "../map";

// A legend of the POI type colours, so the map can be read at a glance without
// clicking (#21 AC helper). It reads the SAME style table the map paints from,
// so the two can never drift.
//
// It is collapsible (#103): the title is a tap-open button. On mobile (≤768px)
// the legend is DEFAULT COLLAPSED — a small button that would otherwise cover the
// map — and taps open; on desktop the media query forces the list open and hides
// the toggle, so the always-visible desktop behaviour is unchanged.
//
// Collapse is view-local UI state, so it lives HERE in a local `useState`, not in
// App's atoms: route-map/CLAUDE.md rule 5 governs *app-level* state (selection,
// search, terrain, sheet), and this widget's open/closed is none of those — no
// other component or the map needs to read it.
export function PoiLegend() {
	const [expanded, setExpanded] = useState(false);
	return (
		<aside
			className={expanded ? "poi-legend poi-legend--expanded" : "poi-legend"}
			aria-label="POI-Typen"
		>
			<button
				type="button"
				className="poi-legend__toggle"
				aria-expanded={expanded}
				onClick={() => setExpanded((open) => !open)}
			>
				POI-Typen
			</button>
			<ul className="poi-legend__list">
				{POI_TYPE_STYLES.map((style) => (
					<li key={style.type} className="poi-legend__item">
						<span
							className="poi-legend__swatch"
							style={{ backgroundColor: style.color }}
						/>
						{style.label}
					</li>
				))}
			</ul>
		</aside>
	);
}
