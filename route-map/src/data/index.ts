import type { GuideData } from "../domain";
import { joinGuideData } from "./join";
import { loadRawArtifacts } from "./load";

// The single data boundary (route-map/CLAUDE.md rule 2): the ONLY place that
// knows the raw on-disk artifact shapes. It loads (load.ts), guards + joins
// (join.ts) the three artifacts into clean domain objects at startup, exposing
// one entry point. Every component depends on src/domain/ types, never on file
// layout.
export async function loadGuideData(): Promise<GuideData> {
	const raw = await loadRawArtifacts();
	return joinGuideData(raw);
}
