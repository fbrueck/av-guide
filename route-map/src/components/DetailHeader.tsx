import type { Entry } from "../domain";

// The navigation callbacks every detail panel needs, bundled so they travel as
// one type rather than three repeated props: close to the sidebar, optionally
// go back up the selection stack, and drill into a related Entry (a cross-link).
export interface DetailNav {
	onClose: () => void;
	onBack?: () => void;
	onNavigate: (entry: Entry) => void;
}

interface DetailHeaderProps {
	title: string;
	/**
	 * Optional muted qualifier rendered inline after the title, e.g. a Place's
	 * elevation so the heading reads "Kreuzjoch, 1719 m". Part of the <h2> so it
	 * belongs to the heading semantically; styled secondary so the name leads.
	 */
	titleSuffix?: string;
	nav: DetailNav;
}

// Shared header for the Place and Route detail panels: a top-left row of icon
// actions — a back arrow (up the selection stack; disabled when there is no
// history) then search (close the detail back to the searchable list) — above
// the Entry name (with an optional muted suffix).
export function DetailHeader({ title, titleSuffix, nav }: DetailHeaderProps) {
	return (
		<header className="detail__header">
			<div className="detail__header-actions">
				{/* The back arrow is always present so the header layout is stable;
				    when there is nowhere to go back to (nav.onBack undefined) it is
				    disabled and greyed rather than hidden. */}
				<button
					type="button"
					className="detail__action"
					onClick={nav.onBack}
					disabled={!nav.onBack}
					aria-label="Zurück"
					title="Zurück"
				>
					<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
						<path
							d="M19 12H5M11 6l-6 6 6 6"
							fill="none"
							stroke="currentColor"
							strokeWidth="2"
							strokeLinecap="round"
							strokeLinejoin="round"
						/>
					</svg>
				</button>
				{/* Search: closing the detail deselects and returns to the searchable
				    list, so it reads as a magnifier rather than a bare × close glyph. */}
				<button
					type="button"
					className="detail__action"
					onClick={nav.onClose}
					aria-label="Zur Suche"
					title="Zur Suche"
				>
					<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
						<circle
							cx="11"
							cy="11"
							r="7"
							fill="none"
							stroke="currentColor"
							strokeWidth="2"
						/>
						<line
							x1="16.5"
							y1="16.5"
							x2="21"
							y2="21"
							stroke="currentColor"
							strokeWidth="2"
							strokeLinecap="round"
						/>
					</svg>
				</button>
			</div>
			<h2 className="detail__title">
				{title}
				{titleSuffix ? (
					<span className="detail__title-suffix">, {titleSuffix}</span>
				) : null}
			</h2>
		</header>
	);
}
