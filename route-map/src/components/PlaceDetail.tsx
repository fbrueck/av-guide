import type { Place } from "../domain";
import { DetailHeader, type DetailNav } from "./DetailHeader";

interface PlaceDetailProps {
	place: Place;
	nav: DetailNav;
}

// The detail panel for a selected Place (#44, #72): the book's data for the
// target feature — name, Typ/Höhe, summary — with the long Übersicht tucked
// behind a collapsed-by-default disclosure so the sections below stay reachable,
// then the list of **Routes leading here** (routes that target this Place;
// selecting one drills into that Route's detail) and the Place's **Mentions**
// (same non-clickable chip pattern as the Route detail view). A Place that
// resolved to no POI renders honestly (route-map/CLAUDE.md rule 3): a note says
// so rather than hiding, so an unresolved Place is visible, not silent.
export function PlaceDetail({ place, nav }: PlaceDetailProps) {
	return (
		<section className="detail" aria-label="Ortsdetails">
			<DetailHeader title={place.name} kind="Ort" nav={nav} />

			<dl className="detail__meta">
				<div className="detail__row">
					<dt>Typ</dt>
					<dd>{place.placeType ?? "—"}</dd>
				</div>
				<div className="detail__row">
					<dt>Höhe</dt>
					<dd>{place.elevation ?? "—"}</dd>
				</div>
			</dl>

			{place.poi ? null : (
				<div className="detail__poi">
					<span className="detail__note detail__note--unlinked">
						Kein POI aufgelöst — keine Koordinate für diesen Ort.
					</span>
				</div>
			)}

			{place.summary ? (
				<p className="detail__summary">{place.summary}</p>
			) : null}
			{place.description ? (
				<details className="detail__disclosure">
					<summary className="detail__subtitle">Übersicht</summary>
					<p className="detail__description">{place.description}</p>
				</details>
			) : null}

			<h3 className="detail__subtitle">
				Routen hierher ({place.routes.length})
			</h3>
			{place.routes.length === 0 ? (
				<p className="detail__note detail__note--unlinked">
					Keine Route führt zu diesem Ort.
				</p>
			) : (
				<ul className="detail__links">
					{place.routes.map((route) => (
						<li key={route.id}>
							<button
								type="button"
								className="detail__link"
								onClick={() => nav.onNavigate(route)}
							>
								<span className="detail__link-name">{route.name}</span>
								<span className="detail__link-meta">
									<span>{route.peak ?? "—"}</span>
									<span className="detail__link-grade">
										{route.grade ?? "—"}
									</span>
								</span>
							</button>
						</li>
					))}
				</ul>
			)}

			<h3 className="detail__subtitle">Mentions ({place.mentions.length})</h3>
			{place.mentions.length === 0 ? (
				<p className="detail__note detail__note--unlinked">
					Keine Mentions verknüpft.
				</p>
			) : (
				<ul className="detail__chips">
					{place.mentions.map((poi) => (
						<li key={poi.id} className="detail__chip">
							{poi.name}
						</li>
					))}
				</ul>
			)}
		</section>
	);
}
