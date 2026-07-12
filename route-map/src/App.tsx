import { useEffect, useRef } from "react";
import { createRouteMap } from "./map";

// Walking skeleton: mount the topographic basemap full-screen. React state
// (selected Route, search, terrain toggle) will drive the imperative map API
// in later tickets — for now App only owns the map's lifecycle.
export function App() {
	const containerRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		const container = containerRef.current;
		if (!container) {
			return;
		}
		const map = createRouteMap(container);
		return () => {
			map.destroy();
		};
	}, []);

	return <div ref={containerRef} className="map-root" />;
}
