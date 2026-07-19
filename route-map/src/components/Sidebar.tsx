import { useMemo } from "react";
import type { Entry, Place, Route } from "../domain";
import { OverviewButton } from "./OverviewButton";

interface SidebarProps {
	/** Every Place (mapped and unmapped). The main list shows the mapped ones
	 *  (poi !== null); the unmapped ones live in the "Orte ohne Koordinate"
	 *  bucket, passed separately as `uncoordinatedPlaces`. */
	places: Place[];
	uncoordinatedPlaces: Place[];
	placelessRoutes: Route[];
	searchText: string;
	onSearchChange: (text: string) => void;
	selectedEntry: Entry | null;
	onSelectEntry: (entry: Entry) => void;
	/** Return to the Guide overview. On desktop the book docks inline next to the
	 *  search field (there is no header bar); on mobile it is hidden here and rides
	 *  the sheet header band instead (App's .panel-header). */
	onReturnToOverview: () => void;
}

// Does a Place match the search needle? Name + place_type, case-insensitive —
// the one predicate the main list and the "Orte ohne Koordinate" bucket share.
function placeMatches(place: Place, needle: string): boolean {
	return `${place.name} ${place.placeType ?? ""}`
		.toLowerCase()
		.includes(needle);
}

// Apply the search needle then order by how many Routes lead here, most first —
// the busiest Places lead the list (#44), so the highest-impact coordinate gaps
// sort to the top of the bucket too. The one shape the mapped list and the
// "Orte ohne Koordinate" bucket share. Copy before sorting so the source prop is
// never mutated; ties keep source order (Array.sort is stable).
function filterAndSortPlaces(places: Place[], needle: string): Place[] {
	const matched = needle
		? places.filter((place) => placeMatches(place, needle))
		: places;
	return [...matched].sort((a, b) => b.routes.length - a.routes.length);
}

// Place-first navigation (#44): the guide is browsed by its target Places, not a
// flat Route list. The primary list holds the Places that resolved to a POI (a
// pin on the map), name/place_type/elevation and how many Routes lead here. Two
// always-visible buckets sit below it, a matched pair of honest gaps kept
// visible and never hidden (route-map/CLAUDE.md rule 3): **Orte ohne Koordinate**
// — Places whose `poi` is null — and **Routen ohne Ort** — Routes with no target
// Place at all (no Destination, no places). Speaks domain types only; selection
// is delegated up through onSelectEntry, the single seam the map highlight and
// the detail panels build on. A plain scrollable list: a few hundred rows need
// no virtualization, and the filter is O(n).
export function Sidebar({
	places,
	uncoordinatedPlaces,
	placelessRoutes,
	searchText,
	onSearchChange,
	selectedEntry,
	onSelectEntry,
	onReturnToOverview,
}: SidebarProps) {
	const needle = searchText.trim().toLowerCase();

	// The mapped list: only Places with a coordinate, so "X von Y Orten" honestly
	// describes what has a pin on the map.
	const mappedPlaces = useMemo(
		() => places.filter((place) => place.poi !== null),
		[places],
	);

	const filteredPlaces = useMemo(
		() => filterAndSortPlaces(mappedPlaces, needle),
		[mappedPlaces, needle],
	);

	const filteredUncoordinated = useMemo(
		() => filterAndSortPlaces(uncoordinatedPlaces, needle),
		[uncoordinatedPlaces, needle],
	);

	const filteredPlaceless = useMemo(() => {
		if (!needle) {
			return placelessRoutes;
		}
		return placelessRoutes.filter((route) => {
			const haystack = `${route.name} ${route.peak ?? ""}`.toLowerCase();
			return haystack.includes(needle);
		});
	}, [placelessRoutes, needle]);

	// One Place row, shared by the main list and the "Orte ohne Koordinate"
	// bucket so the two read as one list cut by has-a-pin.
	const renderPlaceRow = (place: Place) => (
		<li key={place.id}>
			<button
				type="button"
				className={
					place.id === selectedEntry?.id
						? "entry-row entry-row--selected"
						: "entry-row"
				}
				onClick={() => onSelectEntry(place)}
			>
				<span className="entry-row__name">{place.name}</span>
				<span className="entry-row__meta">
					<span className="entry-row__type">
						{place.placeType ?? "—"}
						{place.elevation ? ` · ${place.elevation}` : ""}
					</span>
					<span className="entry-row__count">
						{place.routes.length}{" "}
						{place.routes.length === 1 ? "Route" : "Routen"}
					</span>
				</span>
			</button>
		</li>
	);

	return (
		<aside className="sidebar" aria-label="Orte und Routen">
			<div className="sidebar__search">
				<div className="sidebar__search-row">
					{/* The book docks left of the search field on desktop; hidden on mobile
					    (CSS), where it rides the sheet header band instead. */}
					<OverviewButton onReturnToOverview={onReturnToOverview} />
					<input
						type="search"
						name="entry-search"
						className="sidebar__input"
						placeholder="Orte durchsuchen (Name, Typ)…"
						value={searchText}
						onChange={(event) => onSearchChange(event.target.value)}
						aria-label="Orte durchsuchen"
					/>
				</div>
				<p className="sidebar__count">
					{filteredPlaces.length} von {mappedPlaces.length} Orten
				</p>
			</div>
			<div className="sidebar__scroll">
				<ul className="sidebar__list" aria-label="Orte">
					{filteredPlaces.map(renderPlaceRow)}
				</ul>

				<section className="sidebar__section" aria-label="Orte ohne Koordinate">
					<h2 className="sidebar__section-title">
						Orte ohne Koordinate ({filteredUncoordinated.length})
					</h2>
					{filteredUncoordinated.length === 0 ? (
						<p className="sidebar__empty">
							{uncoordinatedPlaces.length === 0
								? "Alle Orte haben eine Koordinate."
								: "Keine Treffer in dieser Gruppe."}
						</p>
					) : (
						<ul className="sidebar__list">
							{filteredUncoordinated.map(renderPlaceRow)}
						</ul>
					)}
				</section>

				<section className="sidebar__section" aria-label="Routen ohne Ort">
					<h2 className="sidebar__section-title">
						Routen ohne Ort ({filteredPlaceless.length})
					</h2>
					{filteredPlaceless.length === 0 ? (
						<p className="sidebar__empty">
							{placelessRoutes.length === 0
								? "Alle Routen haben einen Ort."
								: "Keine Treffer in dieser Gruppe."}
						</p>
					) : (
						<ul className="sidebar__list">
							{filteredPlaceless.map((route) => (
								<li key={route.id}>
									<button
										type="button"
										className={
											route.id === selectedEntry?.id
												? "entry-row entry-row--selected"
												: "entry-row"
										}
										onClick={() => onSelectEntry(route)}
									>
										<span className="entry-row__name">{route.name}</span>
										<span className="entry-row__meta">
											<span className="entry-row__type">
												{route.peak ?? "—"}
											</span>
											<span className="entry-row__grade">
												{route.grade ?? "—"}
											</span>
										</span>
									</button>
								</li>
							))}
						</ul>
					)}
				</section>
			</div>
		</aside>
	);
}
