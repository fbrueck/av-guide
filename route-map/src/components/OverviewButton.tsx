interface OverviewButtonProps {
	/** Called when the reader wants to return to the Guide overview. */
	onReturnToOverview: () => void;
}

// The return-to-overview affordance (#142): a book icon in the panel/sheet header
// shown in the guide state, replacing the retired switcher dropdown so there is
// exactly ONE way to pick a Guide (the overview). A tap clears the current Guide's
// selection + search and drops the `?guide=` param (handled by App) — the overview
// is the app's front door. Pure UI: it speaks a single callback and never touches
// maplibre-gl (rule 4). Mirrors DetailHeader's icon-button pattern (a bare
// `.detail__action` hit area over an inline currentColor SVG).
export function OverviewButton({ onReturnToOverview }: OverviewButtonProps) {
	return (
		<button
			type="button"
			className="detail__action"
			onClick={onReturnToOverview}
			aria-label="Zur Übersicht"
			title="Zur Übersicht"
		>
			{/* An open book — the guidebook overview. */}
			<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
				<path
					d="M12 6.5C10.5 5.4 8 5 4.5 5v12c3.5 0 6 0.4 7.5 1.5 1.5-1.1 4-1.5 7.5-1.5V5c-3.5 0-6 0.4-7.5 1.5zM12 6.5v12"
					fill="none"
					stroke="currentColor"
					strokeWidth="2"
					strokeLinecap="round"
					strokeLinejoin="round"
				/>
			</svg>
		</button>
	);
}
