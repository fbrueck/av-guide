# CONTEXT — av-guide ubiquitous language

## Entry
A single numbered item in the Alpenvereinsführer, identified by the book's own
**entry id**. The book prints this as a bulleted bare number in the margin
(a *Randziffer*, e.g. `•43`), optionally with a lowercase suffix (`•376 A`);
prose cross-references reprint it with an `R` sigil (`R 43`). We normalize both
to one canonical key — `R43`, `R376A` (strip the inter-token space, uppercase
the suffix) — so a [[Reference]] parsed from `Wie R 43` maps straight to the
Entry. Every Entry is either a [[Place]] or a [[Route]] — that is its `kind`.
The entry id is the Entry's identity across the whole pipeline; when the number
is unrecoverable (OCR loss, unnumbered heading) a deterministic synthetic id is
assigned and flagged (`id_source: book | synthetic`). Places and Routes share
one id namespace, so a [[Reference]] resolves to whichever kind carries that id.
_Avoid_: record, item.

## Place
An Entry (`kind = place`) whose subject is a **target feature** — a summit,
alpine hut, pass, or other important place the guidebook describes in its own
right and files [[Route]]s under. Carries the book's prose (Übersicht),
verbatim metadata (elevation), and a **best-effort `place_type`** drawn from the
[[Gazetteer]] taxonomy (peak, hut, pass, …). A Place **resolves to at most one
[[POI]]** — its coordinate. A Place is a *book entry*, not a coordinate; the
[[POI]] is the OSM point it resolves to.
_Avoid_: target, feature, summit (as a general term).

## Route
An Entry (`kind = route`) describing an **itinerary** — how to reach a target.
A Route has **no geometry of its own**: it is prose plus verbatim-German
metadata (grade, time, height gain, first ascent, the `peak` string) and links
to other concepts. Its target Places are its [[Anchor]]s (`anchor_ids`,
zero-or-many); place-names in its prose are [[Mention]]s. "Rendering a Route on
the map" means highlighting its linked [[POI]] set (its Anchors' POIs plus its
Mentions), never drawing a path.

## POI
A named alpine feature (peak, hut, pass, …) resolved to a single OpenStreetMap
coordinate. Always a point, even for linear features like paths. Identified by
`poi_id`. A [[Place]] resolves to a POI; a [[Mention]] resolves to a POI.
_Avoid_: point, marker, location.

## Anchor
A [[Route]]'s **target [[Place]]** — the place the route leads to. A Route has
zero or more Anchors (`anchor_ids`): the primary one is the Place the route is
filed under in the book (resolved id-to-id at parse); a traverse may name
further target Places (resolved by name at merge). A Route's *anchor
coordinate* is transitive — it is its Anchor Place's [[POI]], never a direct
route→POI link. Distinct from a [[Mention]].
_Avoid_: peak (that is a verbatim string field on a Route, not the Anchor).

## Mention
A place-name extracted from **any [[Entry]]'s** description prose (a [[Route]]'s
or a [[Place]]'s Übersicht) and matched to a [[POI]]. An Entry can have many
Mentions. Their order in the prose is currently **not preserved** in the link
table. Distinct from an [[Anchor]] (a target Place) and from a [[Reference]] (a
pointer to another Entry).

## Reference
A book-internal pointer from one [[Entry]] to another by entry id, found inline
in prose (e.g. "Wie R 43", "(R 43, 243)"). Captured verbatim at parse as
`{ref_id, surface}` and resolved to the target [[Entry]] at join time; an
unresolvable ref_id is surfaced, not invented. Distinct from a [[Mention]]
(which points at a [[POI]], not an Entry).
_Avoid_: cross-link, link.

## Gazetteer
The registry of all named alpine features fetched from OpenStreetMap within the
guide's bounding box, before any matching to [[Entry]]s. Its taxonomy (peak,
hut, pass, …) is the same vocabulary a [[Place]]'s `place_type` draws from.
