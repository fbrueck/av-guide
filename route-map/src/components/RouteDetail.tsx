import type { Route } from "../domain";
import { DetailHeader, type DetailNav } from "./DetailHeader";

interface RouteDetailProps {
	route: Route;
	nav: DetailNav;
}

interface MetaRow {
	label: string;
	value: string | null;
}

// The detail panel for a selected Route (#44): its verbatim-German metadata and
// the full original German description, plus the Entry graph around it — its
// **Anchors** (target Places, each a cross-link; the Route's coordinate is
// transitive through them), its **Mentions** (highlighted on the map), and its
// resolved **References** to other Entries as cross-links. Everything renders
// honestly (route-map/CLAUDE.md rule 3): an anchor-less Route, a Route with no
// Mentions, and a dangling Reference each say so rather than being hidden. The
// description keeps its line breaks (CSS white-space: pre-wrap over the raw "\n"
// string).
export function RouteDetail({ route, nav }: RouteDetailProps) {
	const rows: MetaRow[] = [
		{ label: "Gipfel", value: route.peak },
		{ label: "Schwierigkeit", value: route.grade },
		{ label: "Zeit", value: route.time },
		{ label: "Höhenmeter", value: route.heightM },
		{ label: "Erstbegehung", value: route.firstAscent },
	];

	// References with a resolved target are cross-links; a dangling one (unknown
	// ref_id) or an anaphora (null ref_id) is shown honestly as unresolved.
	const resolvedRefs = route.references.filter((ref) => ref.target !== null);
	const danglingRefs = route.references.filter((ref) => ref.target === null);

	return (
		<section className="detail" aria-label="Routendetails">
			<DetailHeader title={route.name} kind="Route" nav={nav} />

			<dl className="detail__meta">
				{rows.map((row) => (
					<div key={row.label} className="detail__row">
						<dt>{row.label}</dt>
						<dd>{row.value ?? "—"}</dd>
					</div>
				))}
			</dl>

			<h3 className="detail__subtitle">Anker ({route.anchors.length})</h3>
			{route.anchors.length === 0 ? (
				<p className="detail__note detail__note--unlinked">
					Kein Anker verknüpft — diese Route ist keinem Ort zugeordnet.
				</p>
			) : (
				<ul className="detail__links">
					{route.anchors.map((anchor) => (
						<li key={anchor.id}>
							<button
								type="button"
								className="detail__link"
								onClick={() => nav.onNavigate(anchor)}
							>
								<span className="detail__link-name">{anchor.name}</span>
								<span className="detail__link-meta">
									<span>{anchor.placeType ?? "—"}</span>
									<span
										className={
											anchor.poi ? undefined : "detail__note--unlinked"
										}
									>
										{anchor.poi ? anchor.poi.name : "kein POI"}
									</span>
								</span>
							</button>
						</li>
					))}
				</ul>
			)}

			<h3 className="detail__subtitle">Mentions ({route.mentions.length})</h3>
			{route.mentions.length === 0 ? (
				<p className="detail__note detail__note--unlinked">
					Keine Mentions verknüpft.
				</p>
			) : (
				<ul className="detail__chips">
					{route.mentions.map((poi) => (
						<li key={poi.id} className="detail__chip">
							{poi.name}
						</li>
					))}
				</ul>
			)}

			{route.references.length > 0 ? (
				<>
					<h3 className="detail__subtitle">
						Verweise ({route.references.length})
					</h3>
					{resolvedRefs.length > 0 ? (
						<ul className="detail__links">
							{resolvedRefs.map((ref) => (
								// A ref has no id of its own; the pipeline dedupes (ref_id,
								// surface) pairs per Entry, so that pair is a stable key.
								<li key={`${ref.refId}-${ref.surface}`}>
									<button
										type="button"
										className="detail__link"
										onClick={() => {
											if (ref.target) {
												nav.onNavigate(ref.target);
											}
										}}
									>
										<span className="detail__link-name">
											{ref.target?.name}
										</span>
										<span className="detail__link-meta">
											<span>
												{ref.target?.kind === "place" ? "Ort" : "Route"}
											</span>
											<span className="detail__link-grade">{ref.surface}</span>
										</span>
									</button>
								</li>
							))}
						</ul>
					) : null}
					{danglingRefs.length > 0 ? (
						<ul className="detail__chips">
							{danglingRefs.map((ref) => (
								<li
									key={`dangling-${ref.refId ?? "anaphora"}-${ref.surface}`}
									className="detail__chip detail__chip--unlinked"
									title={
										ref.refId
											? "Verweis nicht auflösbar"
											: "Anapher ohne Eintrag-Id"
									}
								>
									{ref.surface || ref.refId || "—"}
								</li>
							))}
						</ul>
					) : null}
				</>
			) : null}

			{route.summary ? (
				<p className="detail__summary">{route.summary}</p>
			) : null}
			<h3 className="detail__subtitle">Beschreibung</h3>
			<p className="detail__description">{route.description ?? "—"}</p>
		</section>
	);
}
