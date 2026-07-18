import type { Guide } from "../domain";

interface GuideSwitcherProps {
	/** The published Guides from the committed manifest (ADR-0005). */
	guides: Guide[];
	/** The id of the Guide currently loaded, or null before the manifest resolves. */
	currentGuideId: string | null;
	/** Called with the chosen Guide's id when the reader picks another. */
	onSelectGuide: (guideId: string) => void;
}

// The in-app Guide switcher (#133, ADR-0005): a native <select> — zero deps,
// accessible, responsive — over the published-Guide manifest. It speaks domain
// types only (a Guide[] list, the current id, an onSelectGuide callback) and
// never touches maplibre-gl (rule 4): a switch flows up through App state, which
// drives the lazy reload + reframe + selection/search reset via effects. Docked
// right-aligned in the panel/sheet header in both layouts (rule 8). Renders
// nothing until the manifest resolves — there is no Guide to offer yet.
export function GuideSwitcher({
	guides,
	currentGuideId,
	onSelectGuide,
}: GuideSwitcherProps) {
	if (guides.length === 0) {
		return null;
	}
	return (
		<div className="guide-switcher">
			<label className="guide-switcher__label" htmlFor="guide-switcher-select">
				Führer
			</label>
			<select
				id="guide-switcher-select"
				className="guide-switcher__select"
				value={currentGuideId ?? ""}
				onChange={(event) => onSelectGuide(event.target.value)}
				aria-label="Führer auswählen"
			>
				{guides.map((guide) => (
					<option key={guide.id} value={guide.id}>
						{guide.label}
					</option>
				))}
			</select>
		</div>
	);
}
