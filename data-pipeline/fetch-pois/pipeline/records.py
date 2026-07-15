"""Typed domain records shared across the fetch-pois stages.

A `dict` is the JSONL/GeoJSON wire format only (see data-pipeline/CLAUDE.md):
read functions parse it into the records named here for their CONTEXT.md
concept, and write functions serialize them back. No bare record `dict` crosses
a boundary in the matcher's core — no `verdict["pick"]` access.

  - `GazetteerEntry` — one named OSM feature in the guide's bbox (stage 1).
  - `Item` — the humble cascade unit: a Place or a Mention resolved to a POI.
  - `Provenance` — how a POI's best match was made (method + optional score/reason).
  - `Poi` — a resolved OSM point in the registry, with aliases and provenance.
  - `Verdict` — an LLM adjudicator's pick (or explicit no-match) with a reason.
  - `PlaceLink` / `EntryLink` — the Place->POI and Entry-mention->POI link rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GazetteerEntry:
    """A named alpine feature fetched from OSM: its taxonomy `type`, a
    representative coordinate, an elevation where OSM has one, and the OSM
    reference `osm` (`node/1001`)."""

    name: str
    type: str
    lat: float
    lon: float
    ele: float | None
    osm: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GazetteerEntry:
        return cls(
            name=raw["name"],
            type=raw["type"],
            lat=raw["lat"],
            lon=raw["lon"],
            ele=raw.get("ele"),
            osm=raw["osm"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "lat": self.lat,
            "lon": self.lon,
            "ele": self.ele,
            "osm": self.osm,
        }


@dataclass(frozen=True, slots=True)
class Item:
    """The unit the cascade resolves: a Place (`kind: place`, resolving to <=1
    POI, typed by its `place_type` hint) or a Mention (`kind: mention`) extracted
    from an Entry's prose. `type` is None for an untyped Place (no type guard);
    `elevation_m` guards the match when both sides state one."""

    surface: str
    name: str
    type: str | None
    elevation_m: float | None
    kind: str  # "place" | "mention"


@dataclass(frozen=True, slots=True)
class Verdict:
    """An adjudicator verdict for one case: `pick` is a candidate OSM ref or
    None (explicit no-match), always with a non-empty `reason`."""

    pick: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"pick": self.pick, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class Provenance:
    """How a POI's best match was made. `score` rides fuzzy/llm matches;
    `reason` rides the LLM adjudicator's pick. Exact/review carry neither."""

    method: str  # "review" | "exact" | "fuzzy" | "llm"
    score: float | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"method": self.method}
        if self.score is not None:
            out["score"] = self.score
        if self.reason is not None:
            out["reason"] = self.reason
        return out


@dataclass(slots=True)
class Poi:
    """A resolved OSM point in the registry. Mutable on purpose: aliases and the
    best-method provenance accumulate as items resolve onto the same POI."""

    poi_id: str
    name: str
    type: str
    lat: float
    lon: float
    ele: float | None
    osm: str
    aliases: list[str] = field(default_factory=list)
    match: Provenance | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "poi_id": self.poi_id,
            "name": self.name,
            "type": self.type,
            "lat": self.lat,
            "lon": self.lon,
            "ele": self.ele,
            "osm": self.osm,
            "aliases": self.aliases,
            "match": self.match.to_dict() if self.match else None,
        }


@dataclass(frozen=True, slots=True)
class PlaceLink:
    """A Place's single POI resolution (place_pois.jsonl)."""

    place_id: str
    poi_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"place_id": self.place_id, "poi_id": self.poi_id}


@dataclass(frozen=True, slots=True)
class EntryLink:
    """An Entry mention -> POI link (entry_pois.jsonl), keyed by (entry, POI)."""

    entry_id: str
    poi_id: str
    surface: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "poi_id": self.poi_id,
            "surface": self.surface,
        }
