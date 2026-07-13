import type { Place } from "../domain";
import { DetailHeader, type DetailNav } from "./DetailHeader";

interface PlaceDetailProps {
	place: Place;
	nav: DetailNav;
}

// The detail panel for a selected Place (#44): the book's data for the target
// feature — name, elevation, place_type, Übersicht — with a link to verify its
// resolved POI on OpenStreetMap, and the list of **Routes leading here** (its
// Anchor's routes). Selecting one drills into that Route's detail. A Place that
// resolved to no POI renders honestly (route-map/CLAUDE.md rule 3): the OSM row
// says so rather than hiding, so an unresolved Place is visible, not silent.
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

			<div className="detail__poi">
				{place.poi ? (
					<a
						className="detail__osm"
						href={place.poi.osmUrl}
						target="_blank"
						rel="noopener noreferrer"
					>
						{place.poi.name} auf OpenStreetMap prüfen ↗
					</a>
				) : (
					<span className="detail__note detail__note--unlinked">
						Kein POI aufgelöst — keine Koordinate für diesen Ort.
					</span>
				)}
			</div>

			{place.summary ? (
				<p className="detail__summary">{place.summary}</p>
			) : null}
			{place.description ? (
				<>
					<h3 className="detail__subtitle">Übersicht</h3>
					<p className="detail__description">{place.description}</p>
				</>
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
		</section>
	);
}
