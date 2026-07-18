import type { Guide } from "./domain";

// The `?guide=<id>` URL param (ADR-0005, route-map/CLAUDE.md rule 5): the ONE
// piece of app state reflected in the URL, so a massif is bookmarkable/shareable
// and survives reload. Read once on load, written with `history.replaceState` on
// a Guide switch — no router, no history stack, and ONLY the Guide (selection,
// search, terrain, and sheet mode stay ephemeral). A query param (not a path)
// keeps GitHub Pages serving the single index.html without a 404.html SPA
// redirect hack; the client reads `location.search`, and static hosting ignores
// the param for the per-Guide data fetches (which resolve to real files).
//
// These helpers are PURE — they take/return plain strings so they are unit-
// testable without a DOM. App owns the impure `location.search` read and the
// `history.replaceState` write, threading the values through here.

const GUIDE_PARAM = "guide";

// Read the requested guide id out of a `location.search` string. Returns the raw
// value (unvalidated — it may name no Guide), or null when the param is absent.
export function readGuideParam(search: string): string | null {
	return new URLSearchParams(search).get(GUIDE_PARAM);
}

// Resolve the `?guide=` deep-link on first load (#142, route-map/CLAUDE.md rule
// 5): the requested id when it names a manifest Guide (open straight into that
// guide, skipping the overview) — otherwise `null`, meaning stay on the overview.
// Absent OR unknown both resolve to null: with the overview as the app's front
// door there is no default Guide, so a stale or mistyped link honestly shows the
// picker rather than silently opening some arbitrary massif.
export function deepLinkGuideId(
	rawParam: string | null,
	guides: Guide[],
): string | null {
	if (rawParam !== null && guides.some((guide) => guide.id === rawParam)) {
		return rawParam;
	}
	return null;
}

// Build the `location.search` string that reflects the selected Guide, for the
// `replaceState` write on switch. Preserves any other query params and sets only
// `guide=` (rule 5: the URL reflects the Guide alone).
export function guideParamSearch(guideId: string, search: string): string {
	const params = new URLSearchParams(search);
	params.set(GUIDE_PARAM, guideId);
	return `?${params.toString()}`;
}
