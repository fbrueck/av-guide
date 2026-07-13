import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
	type DetailNav,
	PlaceDetail,
	PoiLegend,
	RouteDetail,
	Sidebar,
	TerrainToggle,
} from "./components";
import { loadGuideData } from "./data";
import type { Entry, GuideData } from "./domain";
import { createRouteMap, type RouteMap } from "./map";

// Composition root and the app's minimal state (route-map/CLAUDE.md rule 5):
// GuideData, the selection, and the search text all live here as plain React
// state — no router, no state library. The map is created once behind its
// imperative API; React drives it through effects (rule 4).
//
// Selection is a small **stack** of Entries (#44): the sidebar (or a map popup)
// starts a fresh selection; drilling from a Place into a Route leading there, or
// following a Route's Anchor / Reference cross-link, pushes; a Back button pops.
// This is still plain React state (one array) — no router — and gives honest
// back-navigation through the place-first Entry graph.
export function App() {
	const containerRef = useRef<HTMLDivElement>(null);
	const mapRef = useRef<RouteMap | null>(null);
	const [guideData, setGuideData] = useState<GuideData | null>(null);
	const [selection, setSelection] = useState<Entry[]>([]);
	const [searchText, setSearchText] = useState("");
	// The third state atom (route-map/CLAUDE.md rule 5): 2D vs 3D terrain.
	const [terrainEnabled, setTerrainEnabled] = useState(false);

	const currentEntry = selection[selection.length - 1] ?? null;

	// Start a fresh selection (sidebar click, or a map POI popup cross-link). A
	// stable useCallback so the map-creation effect below does not re-create the
	// map. The map calls this too, so a popup selection goes through the exact
	// same door as a sidebar click — the map never owns selection (rule 4).
	const handleSelectEntry = useCallback((entry: Entry) => {
		setSelection([entry]);
	}, []);
	// Drill into a related Entry from within a detail panel (a Place's route,
	// a Route's Anchor Place, a resolved Reference target): push onto the stack.
	const handleNavigate = useCallback((entry: Entry) => {
		setSelection((stack) => [...stack, entry]);
	}, []);
	const handleBack = useCallback(() => {
		setSelection((stack) => stack.slice(0, -1));
	}, []);
	const handleClose = useCallback(() => {
		setSelection([]);
	}, []);

	// Create the map instance once and keep it in a ref for effects to drive.
	// Pass handleSelectEntry at construction so an Entry clicked in a POI popup
	// selects it through the exact same entry point as a sidebar click.
	// handleSelectEntry is a stable useCallback, available before data loads.
	useEffect(() => {
		const container = containerRef.current;
		if (!container) {
			return;
		}
		const map = createRouteMap(container, { onSelectEntry: handleSelectEntry });
		mapRef.current = map;
		return () => {
			mapRef.current = null;
			map.destroy();
		};
	}, [handleSelectEntry]);

	// Load + join the guide's artifacts once through the src/data boundary, then
	// hold the result in state so the sidebar, search, and detail panels all read
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

	// Push the loaded POIs + the poi->Entries index + the set of Place-coordinate
	// poi_ids (the primary markers) into the imperative map API. showPois buffers
	// until the style is ready, so ordering does not matter.
	useEffect(() => {
		if (guideData) {
			const placePoiIds = new Set(
				guideData.places
					.map((place) => place.poi?.id)
					.filter((id): id is string => id !== undefined),
			);
			mapRef.current?.showPois(
				guideData.pois,
				guideData.entriesByPoiId,
				placePoiIds,
			);
		}
	}, [guideData]);

	// Drive the terrain flag into the imperative map API; setTerrain buffers
	// until the style is ready, so ordering against map creation does not matter.
	useEffect(() => {
		mapRef.current?.setTerrain(terrainEnabled);
	}, [terrainEnabled]);

	// Highlight the selected Entry's POI set on the map and fit to it. Passing
	// null (nothing selected) clears the prior highlight. The base all-POIs layer
	// stays visible underneath — this is an emphasis layer, not a redraw.
	// highlightEntry buffers until the style is ready.
	useEffect(() => {
		mapRef.current?.highlightEntry(currentEntry);
	}, [currentEntry]);

	const canGoBack = selection.length > 1;
	// The detail panels' navigation callbacks, bundled into one prop (Back is
	// offered only when there is somewhere to go back to).
	const detailNav: DetailNav = useMemo(
		() => ({
			onClose: handleClose,
			onBack: canGoBack ? handleBack : undefined,
			onNavigate: handleNavigate,
		}),
		[handleClose, canGoBack, handleBack, handleNavigate],
	);

	return (
		<div className="app">
			<div className="map-pane">
				<div ref={containerRef} className="map-root" />
				<PoiLegend />
				<TerrainToggle enabled={terrainEnabled} onToggle={setTerrainEnabled} />
			</div>
			<div className="route-panel">
				<Sidebar
					places={guideData?.places ?? []}
					unfiledRoutes={guideData?.unfiledRoutes ?? []}
					searchText={searchText}
					onSearchChange={setSearchText}
					selectedEntry={currentEntry}
					onSelectEntry={handleSelectEntry}
				/>
				{currentEntry?.kind === "place" ? (
					<PlaceDetail place={currentEntry} nav={detailNav} />
				) : null}
				{currentEntry?.kind === "route" ? (
					<RouteDetail route={currentEntry} nav={detailNav} />
				) : null}
			</div>
		</div>
	);
}
