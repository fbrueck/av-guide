import { useMemo } from "react";
import type { Entry, Place, Route } from "../domain";

interface SidebarProps {
	places: Place[];
	unfiledRoutes: Route[];
	searchText: string;
	onSearchChange: (text: string) => void;
	selectedEntry: Entry | null;
	onSelectEntry: (entry: Entry) => void;
}

// Place-first navigation (#44): the guide is browsed by its target Places, not a
// flat Route list. A searchable Place list (name, place_type, elevation, and how
// many Routes lead here) sits above an **Unfiled routes** bucket — Routes with
// no Anchor, kept visible and never hidden so incomplete anchor resolution is
// honest rather than papered over (route-map/CLAUDE.md rule 3). Speaks domain
// types only; selection is delegated up through onSelectEntry, the single seam
// the map highlight and the detail panels build on. A plain scrollable list: a
// few hundred rows need no virtualization, and the filter is O(n).
export function Sidebar({
	places,
	unfiledRoutes,
	searchText,
	onSearchChange,
	selectedEntry,
	onSelectEntry,
}: SidebarProps) {
	const needle = searchText.trim().toLowerCase();

	const filteredPlaces = useMemo(() => {
		if (!needle) {
			return places;
		}
		return places.filter((place) => {
			const haystack = `${place.name} ${place.placeType ?? ""}`.toLowerCase();
			return haystack.includes(needle);
		});
	}, [places, needle]);

	const filteredUnfiled = useMemo(() => {
		if (!needle) {
			return unfiledRoutes;
		}
		return unfiledRoutes.filter((route) => {
			const haystack = `${route.name} ${route.peak ?? ""}`.toLowerCase();
			return haystack.includes(needle);
		});
	}, [unfiledRoutes, needle]);

	return (
		<aside className="sidebar" aria-label="Orte und Routen">
			<div className="sidebar__search">
				<input
					type="search"
					name="entry-search"
					className="sidebar__input"
					placeholder="Orte durchsuchen (Name, Typ)…"
					value={searchText}
					onChange={(event) => onSearchChange(event.target.value)}
					aria-label="Orte durchsuchen"
				/>
				<p className="sidebar__count">
					{filteredPlaces.length} von {places.length} Orten
				</p>
			</div>
			<div className="sidebar__scroll">
				<ul className="sidebar__list" aria-label="Orte">
					{filteredPlaces.map((place) => (
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
					))}
				</ul>

				<section
					className="sidebar__section"
					aria-label="Nicht zugeordnete Routen"
				>
					<h2 className="sidebar__section-title">
						Nicht zugeordnete Routen ({filteredUnfiled.length})
					</h2>
					{filteredUnfiled.length === 0 ? (
						<p className="sidebar__empty">
							{unfiledRoutes.length === 0
								? "Alle Routen haben einen Anker."
								: "Keine Treffer in dieser Gruppe."}
						</p>
					) : (
						<ul className="sidebar__list">
							{filteredUnfiled.map((route) => (
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
