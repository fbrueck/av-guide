// React UI (sidebar, detail panels, …) speaking domain types only.
// If a component needs the map it extends src/map/'s imperative API rather than
// touching maplibre-gl directly.
export { Basemap2dSwitcher } from "./Basemap2dSwitcher";
export type { DetailNav } from "./DetailHeader";
export { MapAttribution } from "./MapAttribution";
export { PlaceDetail } from "./PlaceDetail";
export { PoiLegend } from "./PoiLegend";
export { RouteDetail } from "./RouteDetail";
export { SheetHandle, type SheetMode } from "./SheetHandle";
export { Sidebar } from "./Sidebar";
export { TerrainToggle } from "./TerrainToggle";
