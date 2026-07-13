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
	/** The Entry kind label, "Ort" or "Route". */
	kind: string;
	nav: DetailNav;
}

// Shared header for the Place and Route detail panels: an optional Back button
// (up the selection stack), the Entry name + its kind label, and a close button.
export function DetailHeader({ title, kind, nav }: DetailHeaderProps) {
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
				<h2 className="detail__title">{title}</h2>
				<p className="detail__kind">{kind}</p>
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
