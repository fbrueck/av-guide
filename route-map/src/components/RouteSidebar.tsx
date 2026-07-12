import { useMemo } from "react";
import type { Route } from "../domain";

interface RouteSidebarProps {
	routes: Route[];
	searchText: string;
	onSearchChange: (text: string) => void;
	selectedRoute: Route | null;
	onSelectRoute: (route: Route) => void;
}

// Lists every Route (738 for wetterstein) with its name, Anchor peak, and grade,
// plus a free-text search box filtering over Route name + peak (#22). Speaks
// domain types only; selection is delegated up through onSelectRoute — the
// single seam #24 (map highlight) and #25 (popup cross-link) build on. A plain
// scrollable list: 738 rows need no virtualization, and the filter is O(n).
export function RouteSidebar({
	routes,
	searchText,
	onSearchChange,
	selectedRoute,
	onSelectRoute,
}: RouteSidebarProps) {
	const filtered = useMemo(() => {
		const needle = searchText.trim().toLowerCase();
		if (!needle) {
			return routes;
		}
		return routes.filter((route) => {
			const haystack = `${route.name} ${route.peak ?? ""}`.toLowerCase();
			return haystack.includes(needle);
		});
	}, [routes, searchText]);

	return (
		<aside className="route-sidebar" aria-label="Routen">
			<div className="route-sidebar__search">
				<input
					type="search"
					name="route-search"
					className="route-sidebar__input"
					placeholder="Routen durchsuchen (Name, Gipfel)…"
					value={searchText}
					onChange={(event) => onSearchChange(event.target.value)}
					aria-label="Routen durchsuchen"
				/>
				<p className="route-sidebar__count">
					{filtered.length} von {routes.length} Routen
				</p>
			</div>
			<ul className="route-sidebar__list">
				{filtered.map((route) => (
					<li key={route.id}>
						<button
							type="button"
							className={
								route.id === selectedRoute?.id
									? "route-row route-row--selected"
									: "route-row"
							}
							onClick={() => onSelectRoute(route)}
						>
							<span className="route-row__name">{route.name}</span>
							<span className="route-row__meta">
								<span className="route-row__peak">{route.peak ?? "—"}</span>
								<span className="route-row__grade">{route.grade ?? "—"}</span>
							</span>
						</button>
					</li>
				))}
			</ul>
		</aside>
	);
}
