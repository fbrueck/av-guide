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

// Shared header for the Place and Route detail panels: an optional Back button
// (up the selection stack), the Entry name (with an optional muted suffix), and
// a close button.
export function DetailHeader({ title, titleSuffix, nav }: DetailHeaderProps) {
	return (
		<header className="detail__header">
			<div className="detail__header-titles">
				{nav.onBack ? (
					<button
						type="button"
						className="detail__back"
						onClick={nav.onBack}
						aria-label="Zurück"
					>
						‹ Zurück
					</button>
				) : null}
				<h2 className="detail__title">
					{title}
					{titleSuffix ? (
						<span className="detail__title-suffix">, {titleSuffix}</span>
					) : null}
				</h2>
			</div>
			<button
				type="button"
				className="detail__close"
				onClick={nav.onClose}
				aria-label="Details schließen"
			>
				×
			</button>
		</header>
	);
}
