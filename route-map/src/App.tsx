import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
	type DetailNav,
	GuideSwitcher,
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
import type { Entry, Guide, GuideData, Poi } from "./domain";
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
	// The published-Guide manifest (ADR-0005) and the reader's current Guide. The
	// switcher lets the reader move between massifs in-app; selectedGuideId is a
	// state atom (route-map/CLAUDE.md rule 5) that drives the lazy reload + reframe
	// via effects. No `?guide=` URL param yet — that lands with #134 — so the Guide
	// lives purely in App state and resets to the manifest default on reload.
	const [guides, setGuides] = useState<Guide[]>([]);
	const [selectedGuideId, setSelectedGuideId] = useState<string | null>(null);
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
	// Switch the loaded Guide (#133, ADR-0005). Setting selectedGuideId drives the
	// lazy reload + reframe effect below; here we reset the two atoms that reference
	// the *old* Guide — the selection stack (a stale Entry would point at nothing)
	// and the search text (a query into the old Guide's Entry list is meaningless
	// against another). Terrain (2D/3D) and the mobile sheet mode PERSIST: both are
	// guide-independent display choices about *how* to render, not *what* is viewed
	// (rule 5). The selection stays Entry[] — a Guide is not pushed onto the stack
	// (ADR-0004); it is the context the stack lives in. Guarded so re-picking the
	// current Guide is a no-op (no needless reload/reset).
	const handleSelectGuide = useCallback(
		(guideId: string) => {
			if (guideId === selectedGuideId) {
				return;
			}
			setSelectedGuideId(guideId);
			setSelection([]);
			setSearchText("");
		},
		[selectedGuideId],
	);
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

	// Load the published-Guide manifest once and select the default Guide. The
	// default is the manifest's **first entry** (#132): with no `?guide=` param yet
	// (that lands in #134), dev and deploy both open on manifest order — `npm run
	// dev` still starts one-command onto a sensible Guide. Setting selectedGuideId
	// drives the data-load effect below.
	useEffect(() => {
		let cancelled = false;
		loadGuidesManifest()
			.then((manifest) => {
				const defaultGuide = manifest[0];
				if (!defaultGuide) {
					throw new Error(
						"guides manifest is empty — no default Guide to load",
					);
				}
				if (!cancelled) {
					setGuides(manifest);
					setSelectedGuideId(defaultGuide.id);
				}
			})
			.catch((error: unknown) => {
				console.error("[app] failed to load guides manifest", error);
			});
		return () => {
			cancelled = true;
		};
	}, []);

	// Load + join the selected Guide's artifacts through the src/data boundary and
	// hold the result in state, so the sidebar, search, and detail panels all read
	// from one source. Re-invoked on every Guide switch (#133, ADR-0005): loading
	// is lazy, one Guide at a time — only the current Guide's join is in memory.
	// Clearing guideData to null first reuses the existing first-load pending state,
	// so a switch shows the same brief, honest loading state as first load; the
	// downstream showPois/frameGuide effects then repaint + reframe onto the new
	// Guide's POIs when its data resolves.
	useEffect(() => {
		if (!selectedGuideId) {
			return;
		}
		let cancelled = false;
		setGuideData(null);
		loadGuideData(selectedGuideId)
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
	}, [selectedGuideId]);

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
				{/* Panel/sheet header: the Guide switcher docks here, right-aligned, in
				    BOTH layouts (rule 8) — a bordered bar at the top of the desktop
				    docked panel, and the mobile bottom-sheet header band (reachable at
				    peek) overlaid on the chevron grabber. It sits above the sidebar and
				    detail so switching Guides is possible from any view (#133). */}
				<div className="panel-header">
					<GuideSwitcher
						guides={guides}
						currentGuideId={selectedGuideId}
						onSelectGuide={handleSelectGuide}
					/>
				</div>
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
