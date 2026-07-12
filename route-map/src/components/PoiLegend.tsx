import { POI_TYPE_STYLES } from "../map";

// A small always-on legend of the POI type colours, so the map can be read at a
// glance without clicking (#21 AC helper). It reads the SAME style table the
// map paints from, so the two can never drift.
export function PoiLegend() {
	return (
		<aside className="poi-legend" aria-label="POI-Typen">
			<h2 className="poi-legend__title">POI-Typen</h2>
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
