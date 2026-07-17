# POIs are display-only, never a selection target

When we enabled the deployed snapshot for smartphone use, we removed the
anchored MapLibre popup that appeared on tapping a **mention-only** POI (a POI
named by Entries but not itself a Place's coordinate). A popup pinned to a
marker is cramped and clips at the screen edges on a phone, and honoring it
would have made a POI a first-class selectable thing — widening the `selection`
stack from `Entry[]` to `(Entry | POI)[]` and adding a POI detail view.

**Decision:** POIs are **display-only**. They are rendered (Place coordinates
always; mention-only POIs revealed on Entry selection, per #89) but are never a
selection target. Tapping a Place-coordinate marker selects that Place (an
Entry, unchanged); tapping a mention-only marker does nothing. The popup is
deleted in **both** delivery modes — this is a desktop change too, not only
mobile — so `selection` stays `Entry[]` and route-map/CLAUDE.md rule 5 holds.

## Considered options

- **Route marker taps into the panel/sheet** as a POI view (mobile) or keep the
  popup (desktop) — rejected: two behaviors to maintain, and it makes a POI
  selectable.
- **Widen `selection` to `(Entry | POI)[]`** with a `PoiDetail` view — rejected:
  more state surface and a new view for a reverse path we decided we don't need.

## Consequences

Navigation is now **one-directional**: Entry → its POIs. The reverse lookup
"which Entries name this POI?" (which lived only in the popup's cross-link list)
is **dropped**. The `entriesByPoiId` index still exists in the join, so the path
is recoverable later if a POI-first view is ever wanted — but no UI surfaces it
today. A future reader seeing the popup gone and mention-only markers inert
should read that as deliberate, not a regression against #89.
