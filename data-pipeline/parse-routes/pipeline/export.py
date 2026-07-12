"""Export the route-map data contract: routes.jsonl -> routes.json.

The `route-map` webapp loads Route metadata as a plain JSON array so the
browser never parses JSONL (see route-map/CLAUDE.md, #17). This step reads the
merged `03_structured/routes.jsonl` and writes `03_structured/routes.json`: the
same routes, projected to a **stable, agreed set of contract fields**.

The projection is deliberate — it is the boundary the webapp depends on. Only
CONTRACT_FIELDS are emitted; internal bookkeeping (e.g. `source_page`) is not
part of the contract and is dropped. A field missing from a record is emitted
as null so the array shape is uniform.

  python -m pipeline.export --guide <id>

`merge` also calls `write_routes_json` after rebuilding the index, so
routes.json is regenerated with routes.jsonl and the two never drift.
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import GuideConfig, load_guide

# The route-map data contract. Order is preserved in the emitted objects.
CONTRACT_FIELDS: tuple[str, ...] = (
    "route_id",
    "name",
    "peak",
    "grade",
    "time",
    "height_m",
    "first_ascent",
    "summary",
    "description",
)


def project_route(record: dict) -> dict:
    """Project one route record onto the contract fields.

    Keeps only CONTRACT_FIELDS (dropping internal fields like source_page) and
    fills any absent field with None, so every emitted object has the same keys.
    """
    return {field: record.get(field) for field in CONTRACT_FIELDS}


def project_routes(records: list[dict]) -> list[dict]:
    """Project a list of route records onto the contract fields."""
    return [project_route(r) for r in records]


def write_routes_json(cfg: GuideConfig, records: list[dict] | None = None) -> int:
    """Write routes.json for a guide and return the record count.

    Reads records from routes.jsonl unless they are passed in (merge passes the
    list it already has in memory, avoiding a needless re-read).
    """
    if records is None:
        if not cfg.routes_jsonl.exists():
            sys.exit("No routes.jsonl — run `python -m pipeline.merge` first.")
        with cfg.routes_jsonl.open(encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]

    projected = project_routes(records)
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
    print(f"Wrote {n} routes -> {cfg.routes_json}")


if __name__ == "__main__":
    main()
