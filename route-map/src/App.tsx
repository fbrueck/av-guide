import { useEffect, useRef } from "react";
import { PoiLegend } from "./components";
import { loadGuideData } from "./data";
import { createRouteMap } from "./map";

// Mounts the topographic basemap full-screen and renders the guide's POIs as
// typed markers (#21). GuideData is loaded once through the src/data boundary
// and pushed into the imperative map API; React never touches maplibre-gl
// directly (route-map/CLAUDE.md rule 4). Selected-route / search / terrain
// state arrive in later tickets.
export function App() {
	const containerRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		const container = containerRef.current;
		if (!container) {
			return;
		}
		const map = createRouteMap(container);
		let cancelled = false;

		loadGuideData()
			.then((guide) => {
				if (!cancelled) {
					map.showPois(guide.pois);
				}
			})
			.catch((error: unknown) => {
				console.error("[app] failed to load guide data", error);
			});

		return () => {
			cancelled = true;
			map.destroy();
		};
	}, []);

	return (
		<>
			<div ref={containerRef} className="map-root" />
			<PoiLegend />
		</>
	);
}
