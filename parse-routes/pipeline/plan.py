"""Deterministic planner for the agent-orchestrated pipeline.

Claude Code (the orchestrator) calls this to get the list of pages that still
need work, grouped into batches it can hand to subagents. No LLM here — just
filesystem bookkeeping, so the agent spends its turns on the actual cleaning
and structuring, and reruns skip whatever is already done.

  python -m pipeline.plan clean     --guide <id> [--batch 15]   # pages needing OCR cleanup
  python -m pipeline.plan structure --guide <id> [--batch 15]   # pages needing route extraction

For `clean`, image/sketch pages are passed through (raw -> clean) here, so
subagents only ever receive real text pages.

Output: one JSON object per line on stdout, e.g.
  {"batch": 1, "pages": ["page_0006", "page_0007", ...]}
A human-readable summary goes to stderr.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys

from .config import GuideConfig, load_guide


def _load_manifest(cfg: GuideConfig) -> list[dict]:
    if not cfg.manifest.exists():
        sys.exit("Manifest not found — run `python -m pipeline.extract` first.")
    with cfg.manifest.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _todo_clean(records: list[dict], cfg: GuideConfig) -> list[str]:
    cfg.clean_pages.mkdir(parents=True, exist_ok=True)
    todo, passthrough = [], 0
    for r in records:
        out = cfg.clean_pages / f"{r['stem']}.txt"
        if out.exists():
            continue
        if r["is_sketch"]:
            # No text to clean — copy the raw page through verbatim.
            shutil.copyfile(cfg.raw_pages / f"{r['stem']}.txt", out)
            passthrough += 1
            continue
        todo.append(r["stem"])
    print(
        f"[plan clean] {passthrough} sketch pages passed through; "
        f"{len(todo)} text pages need cleaning.",
        file=sys.stderr,
    )
    return todo


def _todo_structure(records: list[dict], cfg: GuideConfig) -> list[str]:
    cfg.struct_parts.mkdir(parents=True, exist_ok=True)
    todo = []
    for r in records:
        if r["is_sketch"]:
            continue
        if not (cfg.clean_pages / f"{r['stem']}.txt").exists():
            continue  # not cleaned yet
        if (cfg.struct_parts / f"{r['stem']}.json").exists():
            continue  # already structured
        todo.append(r["stem"])
    print(
        f"[plan structure] {len(todo)} cleaned pages need route extraction.",
        file=sys.stderr,
    )
    return todo


def main() -> None:
    ap = argparse.ArgumentParser(description="Emit batches of pages needing work.")
    ap.add_argument("stage", choices=["clean", "structure"])
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    ap.add_argument("--batch", type=int, default=15, help="Pages per subagent batch.")
    args = ap.parse_args()

    cfg = load_guide(args.guide)
    records = _load_manifest(cfg)
    todo = (
        _todo_clean(records, cfg)
        if args.stage == "clean"
        else _todo_structure(records, cfg)
    )

    for i in range(0, len(todo), args.batch):
        chunk = todo[i : i + args.batch]
        print(
            json.dumps(
                {"batch": i // args.batch + 1, "pages": chunk}, ensure_ascii=False
            )
        )

    if not todo:
        print(
            f"[plan {args.stage}] nothing to do — all pages complete.", file=sys.stderr
        )


if __name__ == "__main__":
    main()
