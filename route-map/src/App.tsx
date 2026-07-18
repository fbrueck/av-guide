import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
	type DetailNav,
	GuideList,
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
import { guideParamSearch } from "./guideParam";
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
	// via effects. The Guide — and only the Guide — is reflected in a `?guide=<id>`
	// URL param (#134): read once on load to pick the initial Guide, written with
	// `history.replaceState` on switch (see handleSelectGuide) so a massif is
	// bookmarkable and survives reload.
	const [guides, setGuides] = useState<Guide[]>([]);
	const [selectedGuideId, setSelectedGuideId] = useState<string | null>(null);
	const [guideData, setGuideData] = useState<GuideData | null>(null);
	const [selection, setSelection] = useState<Entry[]>([]);
	const [searchText, setSearchText] = useState("");
	// The Guide overview state atom (#141, route-map/CLAUDE.md rule 5): plain React
	// state, no router. "overview" — no Guide loaded: the sidebar is a clickable
	// Guide list and the map draws the labelled boxes; "guide" — the existing app
	// (Entry sidebar, POIs). First load always enters the overview (the `?guide=`
	// deep-link semantics are #142); it is forward-only for now — entering a Guide
	// has no return affordance yet (also #142). The overview map boxes and the
	// guide POI layer never overlap: guideData is null in the overview.
	const [view, setView] = useState<"overview" | "guide">("overview");
	// The overview hover link (#141): the guide id currently emphasized across the
	// list and the map. A row hover (GuideList) and a box hover (the map's
	// onHoverGuide callback) both write it; an effect drives the map's box
	// highlight from it, and GuideList marks the matching row. Desktop only in
	// effect — touch fires no hover — matching rule 8's no-hover-on-touch.
	const [hoveredGuideId, setHoveredGuideId] = useState<string | null>(null);
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
	// Pick a Guide — the single door for BOTH an overview pick (a sidebar Guide-list
	// row or a map box, #141) and the in-guide switcher (#133). Setting
	// selectedGuideId drives the lazy reload + reframe effect below and enters the
	// guide state; here we reset the atoms that reference the *old* Guide — the
	// selection stack (a stale Entry would point at nothing), the search text (a
	// query into the old Guide's Entry list is meaningless against another), and the
	// overview hover. Terrain (2D/3D) and the mobile sheet mode PERSIST: both are
	// guide-independent display choices about *how* to render, not *what* is viewed
	// (rule 5). The selection stays Entry[] — a Guide is not pushed onto the stack
	// (ADR-0004); it is the context the stack lives in. Stable ([] deps) so the map
	// (constructed with it as onSelectGuide) is never re-created; a <select> only
	// fires onChange for a genuine change, so no re-pick guard is needed.
	//
	// The pick is reflected in the `?guide=<id>` URL param via
	// `history.replaceState` (#134): no new history entry, no router, and only the
	// Guide is written — selection, search, terrain, and sheet mode stay ephemeral.
	// The path and hash are preserved so the write is safe under the GitHub Pages
	// project-site base. (First-load reads of `?guide=` are deferred to #142; here
	// the param is only written on a pick.)
	const handleSelectGuide = useCallback((guideId: string) => {
		setSelectedGuideId(guideId);
		setView("guide");
		setSelection([]);
		setSearchText("");
		setHoveredGuideId(null);
		const { pathname, search, hash } = window.location;
		window.history.replaceState(
			null,
			"",
			`${pathname}${guideParamSearch(guideId, search)}${hash}`,
		);
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
			// The overview doors (#141): a box click picks that Guide (same as a
			// sidebar row / the switcher), a box hover lights up its row. Both are
			// stable, so the map is created once.
			onSelectGuide: handleSelectGuide,
			onHoverGuide: setHoveredGuideId,
		});
		mapRef.current = map;
		return () => {
			mapRef.current = null;
			map.destroy();
		};
	}, [handleSelectEntry, handleSelectGuide]);

	// Load the published-Guide manifest once. First load always enters the OVERVIEW
	// state (#141): no Guide is auto-selected — the reader picks one from the list
	// or a map box, which sets selectedGuideId and enters the guide state. The
	// `?guide=<id>` deep-link (opening straight into a Guide on load) is #142; here
	// the manifest only populates the overview. An empty manifest is surfaced as an
	// error — there is no Guide to show at all.
	useEffect(() => {
		let cancelled = false;
		loadGuidesManifest()
			.then((manifest) => {
				if (manifest.length === 0) {
					throw new Error("guides manifest is empty — no Guides to show");
				}
				if (!cancelled) {
					setGuides(manifest);
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

	// Draw or clear the Guide overview boxes off the view atom (#141). In the
	// overview state the map shows every Guide's labelled box, framed to fit them
	// all; entering a Guide clears them so the map is left clean for that Guide's
	// POIs. showGuideBoxes/frameOverview buffer until the style is ready, so
	// ordering against map creation and the manifest load does not matter.
	useEffect(() => {
		const map = mapRef.current;
		if (!map) {
			return;
		}
		if (view === "overview" && guides.length > 0) {
			map.showGuideBoxes(guides);
			map.frameOverview(guides);
		} else if (view === "guide") {
			map.clearGuideBoxes();
		}
	}, [view, guides]);

	// Drive the overview hover link into the map (#141): emphasize the hovered
	// Guide's box, so hovering a sidebar row lights up its box (the reverse — box
	// hover lighting the row — flows back via onHoverGuide). Only meaningful in the
	// overview; a null clears the emphasis.
	useEffect(() => {
		if (view === "overview") {
			mapRef.current?.highlightGuideBox(hoveredGuideId);
		}
	}, [hoveredGuideId, view]);

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
				    detail so switching Guides is possible from any view (#133). Only in
				    the guide state: the overview has no loaded Guide to switch away from,
				    and picks its Guide from the list/boxes instead (#141). */}
				<div className="panel-header">
					{view === "guide" ? (
						<GuideSwitcher
							guides={guides}
							currentGuideId={selectedGuideId}
							onSelectGuide={handleSelectGuide}
						/>
					) : null}
				</div>
				{/* The mobile sheet's handle: chevron buttons that step through the
				    three heights (rule 8). Hidden on desktop, where the panel is the
				    docked column. Smart peek content is #102. */}
				<SheetHandle
					mode={sheetMode}
					onExpand={handleSheetExpand}
					onCollapse={handleSheetCollapse}
				/>
				{view === "overview" ? (
					// Overview state (#141): the sidebar is the clickable Guide list; the
					// map draws the labelled boxes. A pick (row or box) enters the guide
					// state via handleSelectGuide.
					<GuideList
						guides={guides}
						onSelectGuide={handleSelectGuide}
						hoveredGuideId={hoveredGuideId}
						onHoverGuide={setHoveredGuideId}
					/>
				) : (
					<>
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
					</>
				)}
			</div>
		</div>
	);
}
