import type { Guide } from "../domain";

interface GuideListProps {
	/** The published Guides from the committed manifest (ADR-0005). */
	guides: Guide[];
	/** Called with the chosen Guide's id when a row is clicked. */
	onSelectGuide: (guideId: string) => void;
	/** The guide id currently hover-emphasized (a row or its map box), or null. */
	hoveredGuideId: string | null;
	/** Called on row hover in/out so the map box lights up in step — one picker
	 *  across the list and the map. Desktop only in effect: touch fires no hover. */
	onHoverGuide: (guideId: string | null) => void;
}

// The Guide overview sidebar list (#141): the reader lands here with no Guide
// loaded and picks one. Each row is a clickable Guide — the massif `name` as the
// title, the fuller edition `label` as secondary text. Clicking a row loads that
// Guide (App's enter-guide door, shared with a map-box click); hovering a row
// emphasizes its box on the map, and hovering a box emphasizes its row, so the
// list and the map read as one picker. Speaks domain types only (Guide) and never
// touches the map — the hover link flows up through App state (rule 4). On touch
// no hover fires, so mobile has no hover-link, matching rule 8.
export function GuideList({
	guides,
	onSelectGuide,
	hoveredGuideId,
	onHoverGuide,
}: GuideListProps) {
	return (
		<aside className="guide-list" aria-label="Führer auswählen">
			<div className="guide-list__intro">
				<h2 className="guide-list__title">Führer auswählen</h2>
				<p className="guide-list__count">{guides.length} Führer</p>
			</div>
			<div className="guide-list__scroll">
				<ul className="guide-list__list" aria-label="Führer">
					{guides.map((guide) => (
						<li key={guide.id}>
							<button
								type="button"
								className={
									guide.id === hoveredGuideId
										? "guide-row guide-row--hovered"
										: "guide-row"
								}
								onClick={() => onSelectGuide(guide.id)}
								onMouseEnter={() => onHoverGuide(guide.id)}
								onMouseLeave={() => onHoverGuide(null)}
							>
								<span className="guide-row__name">{guide.name}</span>
								<span className="guide-row__label">{guide.label}</span>
							</button>
						</li>
					))}
				</ul>
			</div>
		</aside>
	);
}
