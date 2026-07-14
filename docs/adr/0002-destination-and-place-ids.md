# Route targets split into a Destination and additional place_ids; "Anchor" retired

## Status

accepted — amends ADR-0001 (the "Anchor" vocabulary and the single
`anchor_ids` list it introduced are superseded by this decision).

## Context

ADR-0001 gave a Route a single **`anchor_ids`** list of target Places whose
first element was the *primary* anchor (the structural parent Place the route is
filed under) and whose remaining elements were traverse targets, and kept the
verbatim German **`peak`** string only as demoted metadata. In practice the
primary target — the parent Place a route leads to — is a different kind of
thing from the extra places a traverse passes through, but the model flattened
both into one list and used one word, "Anchor", for both. The primary target
also had no name of its own; it was positional (`anchor_ids[0]`).

## Decision

Give a Route a first-class **`destination_id`** and demote the list:

- **`destination_id`** — a single, **nullable** (0-or-1) reference to the
  Route's **primary/parent target Place** (the nearest preceding Place in book
  order — exactly the link merge already captured as `anchor_ids[0]`). A
  parent-less Route has `destination_id: null`, surfaced in the merge report,
  never invented.
- **`anchor_ids` → `place_ids`** — the *additional* target Places only
  (traverse waypoints), **disjoint** from `destination_id`. A Route's full
  target set is `[destination_id, *place_ids]`.
- The verbatim **`peak` string is kept as-is** (name unchanged) as
  provenance/metadata. It is deliberately **not** folded into `destination` —
  the printed summit-string and the structural parent Place are different facts
  (a route filed under a hut can print a summit as its `peak`).
- **"Anchor" is retired** from the ubiquitous language. The coordinate rule is
  unchanged and now attaches to Destination: a Route has no geometry of its own;
  its Destination's coordinate is **transitive** via that Place's POI
  (`places[destination_id].poi`), never a direct route→POI link.

Downstream, following the pipeline:

- **parse-routes** — extractor `anchor_names` → `place_names`; merge internals
  and the report key `unresolved_anchors` → `unresolved_places`.
- **fetch-pois** — the match-adjudicator's per-Route context gains the resolved
  `destination` (name + its POI) alongside the existing `peak` string, as a
  stronger geographic prior for Mention matching. `place_pois` (the Place→POI
  link) is unchanged.
- **route-map** — the join exposes `route.destination` (resolved Place object)
  and `route.places` (array), replacing `route.anchors`. `RouteDetail` shows a
  **"Ziel"** row = destination name + a type qualifier (peak|hut|pass…), "kein
  Ziel" when null; the verbatim `peak` string is no longer displayed;
  `place_ids` render under **"Weitere Orte"**.

## Considered options

- *Rename `peak` → `destination` (the literal opening ask)* — rejected: the
  verbatim summit-string and the structural parent are different facts and can
  disagree, so a rename would conflate them. We add `destination` and keep
  `peak`.
- *Keep `destination` inside `place_ids` as a derived `[0]` convenience* —
  rejected: stores the primary twice and lets the two drift, the same
  single-source-of-truth concern ADR-0001 raised about the anchor coordinate.
- *Keep "Anchor" as an umbrella glossary term with no matching field* —
  rejected: a concept-word matching no field rots; the roles are named directly
  (Destination + `place_ids`).

## Consequences

- One data-contract change (`anchor_ids` → `destination_id` + `place_ids`,
  `anchor_names` → `place_names`) delivered as a **single atomic issue/PR**
  across all three modules, since fetch-pois context and route-map UI both
  depend on parse-routes emitting the new fields — no intermediate contract
  skew.
- Coordinate and map-rendering behavior are otherwise unchanged: a Route
  highlights `[destination, *place_ids]`'s POIs plus its Mentions' POIs.
