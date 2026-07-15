"""Export the route-map data contract: routes.jsonl -> routes.json.

The `route-map` webapp loads Entry metadata as a plain JSON array so the browser
never parses JSONL (see route-map/CLAUDE.md, #17). This step reads the merged
`03_structured/routes.jsonl` and writes `03_structured/routes.json`: the same
Entries (Places and Routes), projected to a **stable, agreed set of contract
fields**.

The projection is deliberate — it is the boundary the webapp (#44) and the
downstream fetch-pois pipeline (#43) depend on. Only CONTRACT_FIELDS are
emitted; internal bookkeeping (e.g. `source_page`, `id_source`) is not part of
the contract and is dropped. A scalar field missing from a record is emitted as
null (including the nullable scalar `destination_id`), and the zero-or-many link
fields (`place_ids`, `references`) default to an empty list, so the array shape
is uniform across Places and Routes.

  python -m pipeline.export --guide <id>

`merge` also calls `write_routes_json` after rebuilding the index, so
routes.json is regenerated with routes.jsonl and the two never drift.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .config import GuideConfig, load_guide
from .records import Entry

# The route-map/fetch-pois data contract (Entry model, #42). Order is preserved
# in the emitted objects. `id` + `kind` head every Entry; `place_type`/
# `elevation` carry for Places, the climbing metadata for Routes, and each kind
# leaves the other's fields null. `destination_id` (nullable scalar: a Route's
# primary target Place), `place_ids` (additional target Places) and `references`
# are the link fields.
CONTRACT_FIELDS: tuple[str, ...] = (
    "id",
    "kind",
    "name",
    "place_type",
    "elevation",
    "peak",
    "grade",
    "time",
    "height_m",
    "first_ascent",
    "destination_id",
    "place_ids",
    "references",
    "summary",
    "description",
)


def project_entry(entry: Entry) -> dict[str, Any]:
    """Project one Entry onto the contract fields.

    Keeps only CONTRACT_FIELDS (dropping internal fields like source_page).
    The link fields (`place_ids`, `references`) are emitted as lists,
    everything else as its scalar (None when the kind leaves it unset), so
    every emitted object has the same uniform shape across Places and Routes.
    """
    out: dict[str, Any] = {}
    for field in CONTRACT_FIELDS:
        if field == "references":
            out[field] = [r.to_dict() for r in entry.references]
        elif field == "place_ids":
            out[field] = list(entry.place_ids)
        else:
            out[field] = getattr(entry, field)
    return out


def project_entries(records: list[Entry]) -> list[dict[str, Any]]:
    """Project a list of Entries onto the contract fields."""
    return [project_entry(r) for r in records]


def write_routes_json(cfg: GuideConfig, records: list[Entry] | None = None) -> int:
    """Write routes.json for a guide and return the record count.

    Reads and parses records from routes.jsonl unless they are passed in (merge
    passes the Entries it already has in memory, avoiding a needless re-read).
    """
    if records is None:
        if not cfg.routes_jsonl.exists():
            sys.exit("No routes.jsonl — run `python -m pipeline.merge` first.")
        with cfg.routes_jsonl.open(encoding="utf-8") as f:
            records = [Entry.from_dict(json.loads(line)) for line in f if line.strip()]

    projected = project_entries(records)
    cfg.routes_json.write_text(
        json.dumps(projected, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(projected)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Export routes.jsonl to the route-map routes.json contract."
    )
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    args = ap.parse_args()
    cfg = load_guide(args.guide)
    n = write_routes_json(cfg)
    print(f"Wrote {n} entries -> {cfg.routes_json}")


if __name__ == "__main__":
    main()
