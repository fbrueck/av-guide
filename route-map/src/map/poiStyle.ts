// How POI markers are coloured by `type` so the mix of feature types reads at a
// glance, without clicking (route-map/CLAUDE.md rule 4; #21 AC). One ordered
// table is the single source of truth for both the map's data-driven paint
// expression AND the legend component, so they can never drift apart.

export interface PoiTypeStyle {
	/** Raw POI `type` value from the artifact. */
	type: string;
	/** Human label for the legend (domain vocabulary; German where it reads). */
	label: string;
	/** Marker fill colour. */
	color: string;
}

// Types present in the current Wetterstein data, most-frequent first. Unknown /
// future types fall through to POI_DEFAULT_COLOR so new pipeline output never
// breaks the render — it just shows in the fallback colour.
export const POI_TYPE_STYLES: readonly PoiTypeStyle[] = [
	{ type: "peak", label: "Gipfel (peak)", color: "#b5651d" },
	{ type: "hut", label: "Hütte (hut)", color: "#d62728" },
	{ type: "pass", label: "Pass", color: "#9467bd" },
	{ type: "path", label: "Weg (path)", color: "#7f7f7f" },
	{ type: "station", label: "Station", color: "#1f77b4" },
	{ type: "settlement", label: "Ort (settlement)", color: "#e377c2" },
	{ type: "water", label: "Gewässer (water)", color: "#17becf" },
	{ type: "locality", label: "Flur (locality)", color: "#bcbd22" },
	{ type: "valley", label: "Tal (valley)", color: "#2ca02c" },
	{ type: "bridge", label: "Brücke (bridge)", color: "#ff7f0e" },
	{ type: "ridge", label: "Grat (ridge)", color: "#8c564b" },
];

// Fallback for any type not in the table above.
export const POI_DEFAULT_COLOR = "#404040";

// A maplibre `match` expression: type -> colour, with the default last. Built
// from the table so the map and legend stay in lockstep.
export function poiColorExpression(): unknown[] {
	const expr: unknown[] = ["match", ["get", "type"]];
	for (const style of POI_TYPE_STYLES) {
		expr.push(style.type, style.color);
	}
	expr.push(POI_DEFAULT_COLOR);
	return expr;
}
