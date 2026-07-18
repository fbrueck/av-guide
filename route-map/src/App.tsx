import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
	type DetailNav,
	MapAttribution,
	PlaceDetail,
	PoiLegend,
	RouteDetail,
	SheetHandle,
	type SheetMode,
	Sidebar,
	TerrainToggle,
} from "./components";
import { loadGuideData, loadGuidesManifest } from "./data";
import type { Entry, GuideData, Poi } from "./domain";
import { createRouteMap, type RouteMap } from "./map";

// Composition root and the app's minimal state (route-map/CLAUDE.md rule 5):
// GuideData, the selection, and the search text all live here as plain React
// state — no router, no state library. The map is created once behind its
// imperative API; React drives it through effects (rule 4).
//
// Selection is a small **stack** of Entries (#44): the sidebar (or a
// Place-coordinate marker tap) starts a fresh selection; drilling from a Place
// into a Route leading there, or following a Route's Destination / Reference
// cross-link, pushes; a Back button pops.
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
	// Mobile-only state atom (route-map/CLAUDE.md rules 5 & 8): the bottom sheet's
	// height, one of three modes — collapsed (only the handle shows), peek (the
	// middle browsing height), full (nearly the whole viewport). Below 768px the
	// route-panel is this sheet, stepped through the modes by its handle; above it
	// the atom is inert (the panel is the docked desktop column). The reader drives
	// it via the handle; the one exception is that a fresh selection snaps it to
	// peek (see handleSelectEntry) so the tapped detail is visible. Default peek so
	// content is visible on load.
	const [sheetMode, setSheetMode] = useState<SheetMode>("peek");

	const currentEntry = selection[selection.length - 1] ?? null;

	// Start a fresh selection (sidebar click, or a Place-coordinate marker tap). A
	// stable useCallback so the map-creation effect below does not re-create the
	// map. The map calls this too, so a marker-tap selection goes through the exact
	// same door as a sidebar click — the map never owns selection (rule 4). On
	// mobile a fresh selection always snaps the sheet to peek (the half height), so
	// the tapped detail is visible without covering the map — never to full, and it
	// lifts the sheet out of collapsed. Inert on desktop (setSheetMode is a no-op
	// for the docked column).
	const handleSelectEntry = useCallback((entry: Entry) => {
		setSelection([entry]);
		setSheetMode("peek");
	}, []);
	// Drill into a related Entry from within a detail panel (a Place's route,
	// a Route's Destination or a further target Place, a resolved Reference
	// target): push onto the stack.
	const handleNavigate = useCallback((entry: Entry) => {
		setSelection((stack) => [...stack, entry]);
	}, []);
	const handleBack = useCallback(() => {
		setSelection((stack) => stack.slice(0, -1));
	}, []);
	const handleClose = useCallback(() => {
		setSelection([]);
	}, []);
	// Step the sheet one height taller / shorter through collapsed <-> peek <->
	// full (CSS height transition, no drag). Only wired below 768px where the
	// handle is shown; inert on desktop (rule 8).
	const handleSheetExpand = useCallback(() => {
		setSheetMode((mode) => (mode === "collapsed" ? "peek" : "full"));
	}, []);
	const handleSheetCollapse = useCallback(() => {
		setSheetMode((mode) => (mode === "full" ? "peek" : "collapsed"));
	}, []);

	// Create the map instance once and keep it in a ref for effects to drive.
	// Pass handleSelectEntry at construction so a Place-coordinate marker tap
	// selects its Place (POIs are display-only, ADR-0004) through the same door the
	// sidebar uses — selection stays single-doored (rule 4) and the map never owns
	// selection or the sheet. It is a stable useCallback, available before data
	// loads.
	useEffect(() => {
		const container = containerRef.current;
		if (!container) {
			return;
		}
		const map = createRouteMap(container, {
			onSelectEntry: handleSelectEntry,
		});
		mapRef.current = map;
		return () => {
			mapRef.current = null;
			map.destroy();
		};
	}, [handleSelectEntry]);

	// Load the published-Guide manifest, then load + join the default Guide's
	// artifacts through the src/data boundary and hold the result in state so the
	// sidebar, search, and detail panels all read from one source. The default is
	// the manifest's **first entry** (#132): no `?guide=` selection yet (that lands
	// with the switcher, #128), so dev and deploy both open on manifest order —
	// `npm run dev` still starts one-command onto a sensible Guide.
	useEffect(() => {
		let cancelled = false;
		loadGuidesManifest()
			.then((guides) => {
				const defaultGuide = guides[0];
				if (!defaultGuide) {
					throw new Error(
						"guides manifest is empty — no default Guide to load",
					);
				}
				return loadGuideData(defaultGuide.id);
			})
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

	// Frame the opening view on the loaded Guide's Place-POI extent (#131). The map
	// is constructed without initial bounds (the POIs aren't known yet), so this
	// effect drives the reframe once guide data resolves — the app opens fitted to
	// whichever Guide it loaded, computed from its POIs rather than a constant.
	// Frames the **Place** POIs specifically: those are the primary markers and the
	// only POIs shown by default (rule #77 — mention-only / gazetteer POIs stay
	// hidden until an Entry is selected), so the opening view fits exactly what is
	// visible. Framing the full POI set would zoom out to a handful of far-flung
	// gazetteer outliers and swamp the massif in dead space.
	useEffect(() => {
		if (guideData) {
			const placePois = guideData.places
				.map((place) => place.poi)
				.filter((poi): poi is Poi => poi !== null);
			mapRef.current?.frameGuide(placePois);
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
				<MapAttribution terrainEnabled={terrainEnabled} />
			</div>
			<div className={`route-panel route-panel--${sheetMode}`}>
				{/* The mobile sheet's handle: chevron buttons that step through the
				    three heights (rule 8). Hidden on desktop, where the panel is the
				    docked column. Smart peek content is #102. */}
				<SheetHandle
					mode={sheetMode}
					onExpand={handleSheetExpand}
					onCollapse={handleSheetCollapse}
				/>
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
