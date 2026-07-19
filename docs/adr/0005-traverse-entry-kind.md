# A third Entry kind, Traverse, for range-wide itineraries filed under no Place

## Status

accepted — extends ADR-0001 (the `kind` set) and ADR-0002 (Destination /
`place_ids`).

## Context

ADR-0001 modelled every book Entry as `kind ∈ {place, route}`: a **Place** is a
target feature (summit, hut, pass) described in its own right, and a **Route** is
an itinerary **filed under** the Place that precedes it, linked to that parent by
`destination_id` (ADR-0002). This matches the guidebook's place-first spine.

But an Alpenvereinsführer also has a section — headed `Weitwanderwege,
Rundtouren` / `Übergänge und Höhenwege` — that groups **range-wide itineraries**:
multi-day traverses (`Die klassische Karwendeldurchquerung von West nach Ost`),
round tours (`Große Karwendel-Rundwanderung`), named long-distance trails (`Der
Adlerweg`), and single-day hut-to-hut Übergänge. These are **filed under no
Place**. The heading that opens the section is not a target feature, so the merge
step — which sets a Route's Destination to the *nearest preceding Place* — bolts
every one of them onto whatever unrelated Place happened to come last (in the
Karwendel guide, ~40 entries all inherited the small `Seewaldhütte`). The model
had no way to say "this itinerary legitimately has no parent", so a correct fact
(no Destination) was indistinguishable from a parse gap (a Route that *should*
have a parent but lost it), and both were silently mis-linked instead of
surfaced.

## Decision

Add a third kind: **`kind = traverse`**, sharing the one id namespace with Places
and Routes.

- A **Traverse** is structurally a **Route with no Destination**: it carries the
  same verbatim itinerary metadata (`grade`, `time`, `height_m`, `first_ascent`,
  `peak`) and the same links (`place_ids`, `references`, Mentions), but its
  `destination_id` is **null by construction**.
- That null is **not a gap**. Merge does not add a Traverse to the
  `missing_destination` report (that report stays meaningful: a *Route* with no
  structural parent). A Traverse also **does not reset** the running parent
  Place, so a Route following the section still resolves its Destination
  normally.
- Because a Traverse has no Destination to prepend, **every** target Place it
  names resolves into `place_ids` (its full target set), by the same by-name
  index merge already uses for a Route's extra waypoints.
- **Classification is anchored to the book's own structure via its
  Inhaltsverzeichnis.** A new **toc-extractor** subagent reads the guide's table
  of contents once and writes a **section map** (`03_structured/sections.json`):
  the top-level sections (`Täler und Talorte`, `Hütten und Zugangswege`,
  `Übergänge und Höhenwege`, `Gipfel und Gipfelrouten`, …), each mapped to a
  canonical `role` and the book page it opens on. The deterministic
  `pipeline.sections` step renders that map into a block the orchestrator injects
  into every **entry-extractor**, which then classifies each entry by the section
  it falls in — an itinerary in the `traverses` section is a `traverse`;
  elsewhere it is a `route`. Reading the OCR'd TOC is fuzzy (an LLM subagent);
  applying the map is deterministic. Section titles vary by guide, so the map is
  per-guide data, not a hardcoded string.

## Considered options

- *Keep `route`; represent "no parent" as `destination_id: null`* — rejected: a
  null Destination already means "a Route that should have a parent but doesn't"
  (a surfaced gap). Overloading it erases the distinction between a real gap and
  a by-design parentless tour, exactly the ambiguity that hid the mis-linking.
- *Make the section heading a `place` so its tours file under it* — rejected: it
  is not a target feature, resolves to no POI, and would pollute the place-first
  navigation and the gazetteer match with a non-place.
- *Add a boolean flag (`is_traverse`) on Route instead of a new kind* — rejected:
  `kind` is the Entry's one discriminator across the whole pipeline and the
  route-map/fetch-pois contract; a parallel boolean would need every `kind`
  switch to also check the flag. A third enum value is the cheaper invariant.
- *A separate top-level record type, not an Entry* — rejected: Traverses share
  the id namespace (cross-references point at them), the itinerary metadata, and
  the Mention/Reference machinery; they are Entries.
- *Classify by spotting the section heading inline* (the extractor flips to
  `traverse` when it sees a `Weitwanderwege / Übergänge` heading mid-stream) —
  rejected: batches are page-windowed and may not contain the heading, the OCR'd
  heading can be mangled, and each batch would re-derive the boundary
  independently. The Inhaltsverzeichnis gives one authoritative, book-wide map
  that every batch shares.
- *Apply the section map deterministically in merge (by page range)* instead of
  in the extractor — rejected: place-vs-route within a section still needs the
  extractor's heading judgment, and the two boundary pages (a section starts
  mid-page) need per-entry resolution the extractor already does; splitting the
  one classification across two stages is worse than keeping it in one.

## Consequences

- `parse-routes`: `Kind` gains `traverse`; merge nulls a Traverse's Destination
  and skips the gap report. A new `toc-extractor` subagent + `pipeline.sections`
  step build and render the section map (`sections.json`) from the guide's
  Inhaltsverzeichnis (its scan page(s) named by a new `toc_pages` config fact);
  the orchestrator injects the rendered block into every entry-extractor. The
  `routes.json` contract gains `traverse` as a possible `kind` value — the field
  set is unchanged (a Traverse serializes in the Route shape with
  `destination_id: null`).
- Downstream, sequenced per ADR-0001 (one issue/PR per module):
  - `fetch-pois` already treats any non-`place` Entry as a Mention source, so a
    Traverse's waypoints resolve without change; no code change is required, but
    it should be re-run so the re-classified entries flow through.
  - `route-map` renders `place` and `route` explicitly; its contract type and
    entry view must widen to handle `traverse` (a follow-up ticket).
- The Karwendel guides must be re-extracted for the section's ~40 entries to be
  re-classified and un-orphaned from `Seewaldhütte`.
