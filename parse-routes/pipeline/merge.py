"""Merge per-page route JSON into one file per route, plus a combined index.

The route-extractor subagents write one part file per page
(`03_structured/parts/page_0051.json`) containing the routes that *start*
on that page. This step explodes those into the final artifact: one JSON file
per route under `03_structured/routes/`, each self-contained with the
verbatim `description`, the generated `summary`, the extracted fields, a stable
`route_id`, and the `source_page` linking it back to the book.

It also writes a combined `routes.jsonl` index for search/loading.

The parts files are the source of truth, so this rebuilds the routes/ directory
from scratch on every run (deterministic, no stale files).

  python -m pipeline.merge --guide <id>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys

from .config import GuideConfig, load_guide


def merge(cfg: GuideConfig) -> None:
    if not cfg.struct_parts.exists():
        sys.exit("No parts dir — run the structure stage first.")

    # Rebuild routes/ from scratch so a re-merge never leaves stale route files.
    if cfg.routes_dir.exists():
        shutil.rmtree(cfg.routes_dir)
    cfg.routes_dir.mkdir(parents=True, exist_ok=True)

    all_routes: list[dict] = []
    bad = 0
    for part in sorted(cfg.struct_parts.glob("page_*.json")):
        page = int(part.stem.split("_")[1])
        try:
            data = json.loads(part.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            bad += 1
            print(f"  WARN: {part.name} is not valid JSON — skipped", file=sys.stderr)
            continue
        for seq, route in enumerate(data.get("routes", []), start=1):
            route_id = f"p{page:04d}_{seq:02d}"
            record = {"route_id": route_id, "source_page": page, **route}
            (cfg.routes_dir / f"{route_id}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            all_routes.append(record)

    all_routes.sort(key=lambda r: r["route_id"])
    with cfg.routes_jsonl.open("w", encoding="utf-8") as f:
        for route in all_routes:
            f.write(json.dumps(route, ensure_ascii=False) + "\n")

    n_pages = len(list(cfg.struct_parts.glob("page_*.json")))
    print(f"Wrote {len(all_routes)} route files -> {cfg.routes_dir}")
    print(f"Combined index -> {cfg.routes_jsonl}  ({n_pages} pages, {bad} unreadable)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Merge per-page route parts into routes.jsonl."
    )
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    args = ap.parse_args()
    merge(load_guide(args.guide))


if __name__ == "__main__":
    main()
