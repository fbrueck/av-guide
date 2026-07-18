import type { GuideData } from "../domain";
import { joinGuideData } from "./join";
import { loadRawArtifacts } from "./load";

// Re-export the Guide manifest loader through the single data boundary so the app
// fetches the published-Guide list the same way it loads a Guide's artifacts —
// via src/data, never by reaching at a file layout (rule 2).
export { loadGuidesManifest } from "./manifest";

// The single data boundary (route-map/CLAUDE.md rule 2): the ONLY place that
// knows the raw on-disk artifact shapes. It loads (load.ts), guards + joins
// (join.ts) the three artifacts into clean domain objects at startup, exposing
// one entry point. Every component depends on src/domain/ types, never on file
// layout. The Guide id namespaces the artifact URLs (route-map/CLAUDE.md rule 6)
// so one deployment can serve multiple Guides; the raw->domain join is
// unchanged.
export async function loadGuideData(guideId: string): Promise<GuideData> {
	const raw = await loadRawArtifacts(guideId);
	return joinGuideData(raw);
}
