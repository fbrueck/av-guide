// React UI (sidebar, detail panels, popup, …) speaking domain types only.
// If a component needs the map it extends src/map/'s imperative API rather than
// touching maplibre-gl directly.
export type { DetailNav } from "./DetailHeader";
export { PlaceDetail } from "./PlaceDetail";
export { PoiLegend } from "./PoiLegend";
export { RouteDetail } from "./RouteDetail";
export { Sidebar } from "./Sidebar";
export { TerrainToggle } from "./TerrainToggle";
