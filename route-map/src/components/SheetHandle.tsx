// The mobile bottom sheet has three heights (route-map/CLAUDE.md rule 8):
// collapsed (only this handle shows), peek (the middle browsing height), and full
// (nearly the whole viewport). "collapsed" is the reader-owned atom's third mode.
export type SheetMode = "collapsed" | "peek" | "full";

interface SheetHandleProps {
	mode: SheetMode;
	/** Step one height taller: collapsed → peek → full. */
	onExpand: () => void;
	/** Step one height shorter: full → peek → collapsed. */
	onCollapse: () => void;
}

// The sheet's handle: chevron buttons that step it through the three heights —
// collapsed shows only an up chevron, peek (middle) shows both up and down, full
// shows only a down chevron. Chevrons (not a drag pill) signal the interaction is
// a TAP. Hidden on desktop, where the whole header is display:none and the panel
// is the docked column.
export function SheetHandle({ mode, onExpand, onCollapse }: SheetHandleProps) {
	return (
		<div className="sheet-header">
			{mode !== "full" ? (
				<button
					type="button"
					className="sheet-header__chevron-btn"
					onClick={onExpand}
					aria-label="Ausklappen"
				>
					<svg
						className="sheet-header__chevron"
						viewBox="0 0 24 24"
						width="22"
						height="22"
						aria-hidden="true"
					>
						<path
							d="M6 15l6-6 6 6"
							fill="none"
							stroke="currentColor"
							strokeWidth="2"
							strokeLinecap="round"
							strokeLinejoin="round"
						/>
					</svg>
				</button>
			) : null}
			{mode !== "collapsed" ? (
				<button
					type="button"
					className="sheet-header__chevron-btn"
					onClick={onCollapse}
					aria-label="Einklappen"
				>
					<svg
						className="sheet-header__chevron"
						viewBox="0 0 24 24"
						width="22"
						height="22"
						aria-hidden="true"
					>
						<path
							d="M6 9l6 6 6-6"
							fill="none"
							stroke="currentColor"
							strokeWidth="2"
							strokeLinecap="round"
							strokeLinejoin="round"
						/>
					</svg>
				</button>
			) : null}
		</div>
	);
}
