import type { Route } from "../domain";

interface RouteDetailProps {
	route: Route;
	onClose: () => void;
}

interface MetaRow {
	label: string;
	value: string | null;
}

// The detail panel for a selected Route (#22): its verbatim-German metadata and
// the full original German description, read next to the terrain it describes.
// Fields are verbatim strings and frequently null (grade, first ascent
// especially) — every row renders honestly with an em dash rather than breaking
// the panel. The description is rendered faithfully with line breaks preserved
// (CSS white-space: pre-wrap over the raw string, which contains "\n"). This
// ticket is route reading only; map highlighting of the POI set is #24.
export function RouteDetail({ route, onClose }: RouteDetailProps) {
	const rows: MetaRow[] = [
		{ label: "Gipfel", value: route.peak },
		{ label: "Schwierigkeit", value: route.grade },
		{ label: "Zeit", value: route.time },
		{ label: "Höhenmeter", value: route.heightM },
		{ label: "Erstbegehung", value: route.firstAscent },
	];

	return (
		<section className="route-detail" aria-label="Routendetails">
			<header className="route-detail__header">
				<h2 className="route-detail__title">{route.name}</h2>
				<button
					type="button"
					className="route-detail__close"
					onClick={onClose}
					aria-label="Details schließen"
				>
					×
				</button>
			</header>
			<dl className="route-detail__meta">
				{rows.map((row) => (
					<div key={row.label} className="route-detail__row">
						<dt>{row.label}</dt>
						<dd>{row.value ?? "—"}</dd>
					</div>
				))}
			</dl>
			{route.summary ? (
				<p className="route-detail__summary">{route.summary}</p>
			) : null}
			<h3 className="route-detail__subtitle">Beschreibung</h3>
			<p className="route-detail__description">{route.description ?? "—"}</p>
		</section>
	);
}
