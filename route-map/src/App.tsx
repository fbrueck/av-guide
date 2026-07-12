import { useCallback, useEffect, useRef, useState } from "react";
import { PoiLegend, RouteDetail, RouteSidebar } from "./components";
import { loadGuideData } from "./data";
import type { GuideData, Route } from "./domain";
import { createRouteMap, type RouteMap } from "./map";

// Composition root and the app's minimal state (route-map/CLAUDE.md rule 5):
// GuideData, the selected Route, and the search text all live here as plain
// React state — no router, no state library. The map is created once behind its
// imperative API; React drives it through effects (rule 4).
//
// Selection seam for later tickets: handleSelectRoute is the single entry point
// that sets selectedRoute. #24 will add an effect keying off selectedRoute to
// drive map.highlightPois(...); #25 will call this same handler from the POI
// popup. Keep this the one obvious door for both.
export function App() {
	const containerRef = useRef<HTMLDivElement>(null);
	const mapRef = useRef<RouteMap | null>(null);
	const [guideData, setGuideData] = useState<GuideData | null>(null);
	const [selectedRoute, setSelectedRoute] = useState<Route | null>(null);
	const [searchText, setSearchText] = useState("");

	// Create the map instance once and keep it in a ref for effects to drive.
	useEffect(() => {
		const container = containerRef.current;
		if (!container) {
			return;
		}
		const map = createRouteMap(container);
		mapRef.current = map;
		return () => {
			mapRef.current = null;
			map.destroy();
		};
	}, []);

	// Load + join the guide's artifacts once through the src/data boundary, then
	// hold the result in state so the sidebar, search, and detail panel all read
	// from one source.
	useEffect(() => {
		let cancelled = false;
		loadGuideData()
			.then((guide) => {
				if (!cancelled) {
					setGuideData(guide);
				}
			})
			.catch((error: unknown) => {
				console.error("[app] failed to load guide data", error);
			});
		return () => {
			cancelled = true;
		};
	}, []);

	// Push the loaded POIs into the imperative map API. showPois buffers until the
	// style is ready, so ordering against map creation does not matter.
	useEffect(() => {
		if (guideData) {
			mapRef.current?.showPois(guideData.pois);
		}
	}, [guideData]);

	const handleSelectRoute = useCallback((route: Route) => {
		setSelectedRoute(route);
	}, []);
	const handleClearSelection = useCallback(() => {
		setSelectedRoute(null);
	}, []);

	return (
		<div className="app">
			<div className="map-pane">
				<div ref={containerRef} className="map-root" />
				<PoiLegend />
			</div>
			<div className="route-panel">
				<RouteSidebar
					routes={guideData?.routes ?? []}
					searchText={searchText}
					onSearchChange={setSearchText}
					selectedRoute={selectedRoute}
					onSelectRoute={handleSelectRoute}
				/>
				{selectedRoute ? (
					<RouteDetail route={selectedRoute} onClose={handleClearSelection} />
				) : null}
			</div>
		</div>
	);
}
