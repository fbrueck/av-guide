// Which base-layer POIs show for the current selection (#77). By default the map
// shows only Place POIs — the coordinates of the book's Place Entries — so the
// place-first structure reads at a glance without mention noise. Selecting any
// Entry reveals exactly that Entry's Mentions on top. One rule: a mention-only
// POI is visible exactly when the selected Entry mentions it.
//
// This is a pure, map-free rule (Entry-or-null in, decision out) so it is
// unit-testable without a map instance — the same pattern as the pure POI colour
// table in poiStyle.ts. RouteMap translates the rule into the base layer's
// maplibre filter via poiVisibilityFilter; both derive from the one primitive
// below (revealedMentionPoiIds) so the applied filter and the tested rule cannot
// drift.

import type { Entry } from "../domain";

// The poi_ids a selected Entry reveals on the base layer — exactly its Mentions.
// Empty for no selection, or for an Entry with no Mentions (honest: nothing extra
// is revealed, no invented markers — route-map/CLAUDE.md rule 3).
export function revealedMentionPoiIds(entry: Entry | null): Set<string> {
	return new Set((entry?.mentions ?? []).map((poi) => poi.id));
}

// The base-layer feature props the visibility rule reads — a structural subset
// of RouteMap's PoiFeatureProps, which extends this. Named and owned here (not
// borrowed from RouteMap) so the pure rule stays map-free: RouteMap references
// this type, never the reverse, so no maplibre reaches this module. Single-
// sourcing the shape means an `id`/`isPlace` rename is one edit the compiler
// enforces across both, not two silent copies.
export interface PoiVisibilityFeature {
	id: string;
	isPlace: boolean;
}

// The visibility rule: a base-layer POI shows exactly when it is a Place's
// resolved coordinate (`isPlace` — always visible, so hiding Mentions never
// hides a Place, #77 story 10) OR the selected Entry mentions it. `isPlace` is
// the feature prop the base layer already carries.
export function isPoiVisible(
	feature: PoiVisibilityFeature,
	entry: Entry | null,
): boolean {
	return feature.isPlace || revealedMentionPoiIds(entry).has(feature.id);
}

// The maplibre `any` filter for the base POI layer, mirroring isPoiVisible: keep
// a feature when its `isPlace` prop is set, or its `id` is one of the selected
// Entry's revealed Mentions. Built here (not inline in RouteMap) so the map's
// applied filter stays beside the rule it implements — the same reason
// poiColorExpression lives beside the colour table. Returned as `unknown[]` (the
// poiStyle convention) so callers cast to the maplibre filter type at the seam.
export function poiVisibilityFilter(entry: Entry | null): unknown[] {
	const mentionIds = [...revealedMentionPoiIds(entry)];
	return [
		"any",
		["get", "isPlace"],
		["in", ["get", "id"], ["literal", mentionIds]],
	];
}
