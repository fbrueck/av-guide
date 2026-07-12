# CONTEXT — av-guide ubiquitous language

## Route
A single numbered climbing/hiking itinerary from the Alpenvereinsführer (e.g. "50 Von Hammersbach über den Stangensteig"). A Route has **no geometry of its own** — it is prose plus metadata (grade, time, height gain, first ascent, all verbatim German strings) and links to POIs. "Rendering a Route on the map" means highlighting its linked POI set, never drawing a path.

## POI
A named alpine feature (peak, hut, pass, …) resolved to a single OpenStreetMap coordinate. Always a point, even for linear features like paths. Identified by `poi_id`.

## Anchor
The POI matched from a Route's `peak` field — the summit/target the guidebook files the route under. Every Route has at most one Anchor. Distinct from a [[Mention]].

## Mention
A place name the LLM extracted from a Route's description prose, matched to a POI. A Route can have many Mentions; their order in the prose is currently **not preserved** in the link table.

## Gazetteer
The registry of all named alpine features fetched from OpenStreetMap within the Wetterstein bounding box, before any matching to Routes.
