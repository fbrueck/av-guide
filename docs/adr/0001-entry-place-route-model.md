# Entries split into Places and Routes, anchored structurally by book id

## Context

The Alpenvereinsführer is organised place-first: a **target place** (summit,
hut, pass) is described in its own right, and the **routes** that reach it are
filed under it. Both kinds of item carry the book's own **entry id** — printed
as a bulleted bare number in the margin (a *Randziffer*, `•43`) and reprinted
with an `R` sigil in prose cross-references (`Wie R 43`); we normalize both to
one canonical key (`R43`). Places and routes interleave in a single running
number sequence.

The pipeline originally modelled *everything* as a `Route` with a synthetic,
page-derived id (`p0051_01`). Place descriptions were forced into the Route
shape; a Route's target came from fuzzy-matching a verbatim `peak` string to a
POI downstream (the old "Anchor"); and the book's real entry ids and
cross-references were discarded (`mention-extractor` was told to drop route
cross-refs as "not places").

## Decision

Introduce an **Entry** supertype with `kind ∈ {place, route}` sharing **one id
namespace**, keyed by the book's printed entry id (deterministic synthetic
fallback, flagged `id_source`).

- A **Place** is the target book entry; it **resolves to at most one POI** and
  carries a best-effort `place_type` from the gazetteer taxonomy to guard
  matching.
- A **Route** links to its target Places via **`anchor_ids` (zero-or-many)**,
  captured **structurally** from the book's nesting at parse (primary anchor,
  id-to-id) with additional traverse targets resolved by name at merge. The old
  `peak` string is retained only as verbatim metadata.
- **Anchor** is redefined from "the POI matched from `peak`" to "a Route's
  target **Place**"; the anchor coordinate is **transitive** (`places[anchor_id]
  .poi`), so the coordinate has a single source of truth. `fetch-pois` emits a
  new `place_pois` link and `route_pois` becomes `entry_pois` (mentions-only, no
  `is_anchor`).
- **Mention** is generalised to a POI named in *any* Entry's prose.
- **References** (`{ref_id, surface}`) capture book-internal id cross-refs at
  parse, resolved at join.

The map reorients to **place-first** navigation (browse Places → routes leading
to each), matching the book's structure.

## Considered options

- *Keep one flat Route type, add a `kind` flag only* — rejected: Place-specific
  data (its own POI resolution, place_type) and the place-first UI need Places
  as first-class entries, not tagged routes.
- *Match a Route's target by `peak` string downstream* (status quo) — rejected:
  structural nesting gives a reliable id-to-id link; string matching is lossy
  and duplicates the anchor coordinate.
- *Separate id namespaces per kind* — rejected: cross-references point by a bare
  id, so a shared namespace lets a Reference resolve to either kind uniformly.
- *Direct route→POI anchor link* (status quo) — rejected in favour of transitive
  resolution via the Place, to avoid the anchor coordinate drifting between two
  places.

## Consequences

- The change spans all three modules and is sequenced in pipeline order
  (`parse-routes` → `fetch-pois` → `route-map`), one issue/PR each.
- Extraction must classify Place vs Route and read the entry-id format. The
  classification signal and id scheme were fixed from a verbatim book sample in
  #41: classify by heading shape (`name, <elev> m` ⇒ Place vs itinerary phrase
  ⇒ Route) plus body opening (Übersicht vs metadata block), via LLM judgment on
  those cues rather than a strict regex; the id is the bulleted *Randziffer*
  normalized to `R43`.
