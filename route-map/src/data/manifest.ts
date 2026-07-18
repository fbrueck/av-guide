import type { Guide } from "../domain";

// The Guide manifest loader — part of the single data boundary (route-map/
// CLAUDE.md rule 2). `guides.json` is the committed, hand-maintained statement of
// which Guides the deployment serves (ADR-0005), served the same two ways as
// every artifact: in dev by the `configureServer` middleware from
// `guides/guides.json`, in the build by a committed snapshot under
// `public/guide-data/guides.json`. It is app/maintainer metadata, NOT pipeline
// output, so it sits at `/guide-data/guides.json` (no id segment — it is the
// index over ids, not one Guide's data).

// The manifest URL, BASE_URL-prefixed exactly like the artifact URLs so it
// resolves under the GitHub Pages project-site base when deployed and stays bare
// in dev. Pure (no I/O) so it is unit-testable without mocking `fetch`.
export function guidesManifestUrl(): string {
	return `${import.meta.env.BASE_URL}guide-data/guides.json`;
}

// Guard the raw parsed `guides.json` into `Guide[]` (rule 2 "guard the seams").
// The manifest is hand-maintained, so a malformed entry is drift to surface, not
// to crash on: skip it with a `console.warn` and keep the well-formed Guides,
// mirroring how the join warn-and-skips bad records. Pure: parsed JSON in,
// domain `Guide[]` out — the impure fetch lives in `loadGuidesManifest`.
export function parseGuidesManifest(raw: unknown): Guide[] {
	if (!Array.isArray(raw)) {
		console.warn("[data] guides.json is not an array; ignoring manifest");
		return [];
	}
	const guides: Guide[] = [];
	for (const entry of raw) {
		if (typeof entry !== "object" || entry === null) {
			console.warn("[data] skipping non-object guides.json entry", entry);
			continue;
		}
		const record = entry as Record<string, unknown>;
		if (typeof record.id !== "string" || typeof record.label !== "string") {
			console.warn(
				"[data] skipping guides.json entry missing string id/label",
				entry,
			);
			continue;
		}
		if (typeof record.name !== "string" || record.name.trim() === "") {
			console.warn(
				"[data] skipping guides.json entry missing non-blank string name",
				entry,
			);
			continue;
		}
		if (!isBbox(record.bbox)) {
			console.warn(
				"[data] skipping guides.json entry with invalid bbox (need 4 finite numbers)",
				entry,
			);
			continue;
		}
		guides.push({
			id: record.id,
			name: record.name,
			label: record.label,
			bbox: record.bbox,
		});
	}
	return guides;
}

// A bbox is exactly four finite numbers, `[south, west, north, east]`. Cheap
// explicit guard (no schema library, rule 2): reject a non-array, a wrong
// length, or any non-finite element (NaN/Infinity/string).
function isBbox(value: unknown): value is [number, number, number, number] {
	return (
		Array.isArray(value) &&
		value.length === 4 &&
		value.every((n) => typeof n === "number" && Number.isFinite(n))
	);
}

// Fetch + guard the manifest — the impure I/O half. A failed fetch throws (the
// app cannot pick a default Guide without it); a well-formed-but-partly-bad
// manifest yields the salvageable Guides via the guard above.
export async function loadGuidesManifest(): Promise<Guide[]> {
	const url = guidesManifestUrl();
	const res = await fetch(url);
	if (!res.ok) {
		throw new Error(
			`Failed to load guides manifest ${url}: ${res.status} ${res.statusText}`,
		);
	}
	const raw: unknown = await res.json();
	return parseGuidesManifest(raw);
}
