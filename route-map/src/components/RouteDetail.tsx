import type { Place, Route } from "../domain";
import { DetailHeader, type DetailNav } from "./DetailHeader";

interface RouteDetailProps {
	route: Route;
	nav: DetailNav;
}

interface MetaRow {
	label: string;
	value: string;
}

// A metadata value counts as empty when the pipeline extracted nothing: null,
// whitespace-only, or a bare placeholder dash coming through as text (#71).
function hasValue(value: string | null): value is string {
	const trimmed = value?.trim() ?? "";
	return trimmed !== "" && trimmed !== "—" && trimmed !== "-";
}

// The detail panel for a selected Route (#44, #61): its verbatim-German metadata
// and the full original German description, plus the Entry graph around it — its
// **Ziel** (Destination — the primary target Place, the Route's transitive
// coordinate), its **Weitere Orte** (additional target Places), its **Mentions**
// (highlighted on the map), and its resolved **References** to other Entries as
// cross-links, ordered so the narrative reads top-down: key facts, prose
// (summary + Beschreibung), Ziel, supporting graph, cross-links. Metadata rows
// without an extracted value are hidden
// (#71); the graph sections render honestly (route-map/CLAUDE.md rule 3): a Route
// with no Destination ("kein Ziel"), no places, no Mentions, and a dangling
// Reference each say so rather than being hidden. The verbatim `peak` string is
// deliberately not shown (ADR-0002 — provenance metadata, not a rendered target).
// The description keeps its line breaks (CSS white-space: pre-wrap over the raw
// "\n" string).
export function RouteDetail({ route, nav }: RouteDetailProps) {
	// Only rows the pipeline actually extracted a value for are rendered; a
	// Route with no metadata at all renders no table (#71).
	const rows: MetaRow[] = [
		{ label: "Schwierigkeit", value: route.grade },
		{ label: "Zeit", value: route.time },
		{ label: "Höhenmeter", value: route.heightM },
		{ label: "Erstbegehung", value: route.firstAscent },
	].filter((row): row is MetaRow => hasValue(row.value));

	// References with a resolved target are cross-links; a dangling one (unknown
	// ref_id) or an anaphora (null ref_id) is shown honestly as unresolved.
	const resolvedRefs = route.references.filter((ref) => ref.target !== null);
	const danglingRefs = route.references.filter((ref) => ref.target === null);

	// A target Place as a cross-link: name + its type qualifier and whether it
	// resolved to a POI. Shared by the Destination ("Ziel") and the additional
	// target Places ("Weitere Orte"), so both read identically.
	const placeLink = (place: Place) => (
		<li key={place.id}>
			<button
				type="button"
				className="detail__link"
				onClick={() => nav.onNavigate(place)}
			>
				<span className="detail__link-name">{place.name}</span>
				<span className="detail__link-meta">
					<span>{place.placeType ?? "—"}</span>
					<span className={place.poi ? undefined : "detail__note--unlinked"}>
						{place.poi ? place.poi.name : "kein POI"}
					</span>
				</span>
			</button>
		</li>
	);

	return (
		<section className="detail" aria-label="Routendetails">
			<DetailHeader title={route.name} nav={nav} />

			{rows.length > 0 ? (
				<dl className="detail__meta">
					{rows.map((row) => (
						<div key={row.label} className="detail__row">
							<dt>{row.label}</dt>
							<dd>{row.value}</dd>
						</div>
					))}
				</dl>
			) : null}

			{route.summary ? (
				<p className="detail__summary">{route.summary}</p>
			) : null}
			<h3 className="detail__subtitle">Beschreibung</h3>
			<p className="detail__description">{route.description ?? "—"}</p>

			<h3 className="detail__subtitle">Ziel</h3>
			{route.destination === null ? (
				<p className="detail__note detail__note--unlinked">
					Kein Ziel — diese Route ist keinem Ort zugeordnet.
				</p>
			) : (
				<ul className="detail__links">{placeLink(route.destination)}</ul>
			)}

			<h3 className="detail__subtitle">Weitere Orte ({route.places.length})</h3>
			{route.places.length === 0 ? (
				<p className="detail__note detail__note--unlinked">
					Keine weiteren Orte verknüpft.
				</p>
			) : (
				<ul className="detail__links">{route.places.map(placeLink)}</ul>
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
		</section>
	);
}
