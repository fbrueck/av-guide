"""Deterministic planner for the agent-orchestrated LLM stages.

Claude Code (the orchestrator) calls this to get the work that still needs
an LLM — routes awaiting mention extraction, adjudication cases awaiting a
verdict — grouped into batches it can hand to subagents. No LLM here — just
filesystem bookkeeping, so reruns skip whatever is already done.

  python -m pipeline.plan extract --guide <id> [--batch 10]

Batches are formed over the *full* route list sorted by route_id, so batch
numbers and membership are stable across runs. A route is done once its part
file `02_mentions/parts/<route_id>.json` exists; a batch is emitted (with only
its missing routes) until every route in it is done, so an interrupted batch
resumes without redoing completed routes.

Output: one JSON object per line on stdout, e.g.
  {"batch": 1, "routes": [{"route_id": ..., "peak": ..., "description": ...}]}
A human-readable summary goes to stderr.

  python -m pipeline.plan adjudicate --guide <id> [--batch 10]

does the same for the LLM adjudication stage: the matcher's open cases
(03_matched/adjudication_queue.jsonl) are batched for `match-adjudicator`
subagents, each case carrying its candidate shortlist plus the route's peak
and description as context. A case is done once its verdict file
`03_matched/verdicts/<case_id>.json` exists, so interrupted runs resume
without re-adjudicating. Output: one JSON object per line, e.g.
  {"batch": 1, "cases": [{"case_id": ..., "route_id": ..., "mention": ...,
   "candidates": [...], "route": {"peak": ..., "description": ...}}]}

  python -m pipeline.plan funnel --guide <id>

prints the matcher's funnel (03_matched/funnel.json) as a per-type table —
mentions -> exact / fuzzy / llm / review / tie / skipped / unmatched — with a
totals row on stdout and the usual one-line summary on stderr. `llm` counts
adjudicator picks (cascade matches stay under exact/fuzzy); `review` counts
human-accepted decisions; `tie` counts only still-open cases.
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import GuideConfig, load_guide


def _load_routes(cfg: GuideConfig) -> list[dict]:
    if not cfg.routes_jsonl.exists():
        sys.exit(f"missing {cfg.routes_jsonl} — run the parse-routes pipeline first.")
    with cfg.routes_jsonl.open(encoding="utf-8") as f:
        routes = [json.loads(line) for line in f]
    return sorted(routes, key=lambda r: r["route_id"])


def _print_funnel(cfg: GuideConfig) -> None:
    if not cfg.funnel.exists():
        sys.exit(f"missing {cfg.funnel} — run the matcher first.")
    report = json.loads(cfg.funnel.read_text(encoding="utf-8"))

    cols = (
        "mentions",
        "exact",
        "fuzzy",
        "llm",
        "review",
        "tie",
        "skipped",
        "unmatched",
    )
    width = max(len("total"), *(len(t) for t in report["types"] or [""]))
    print("type".ljust(width) + "".join(c.rjust(11) for c in cols))
    for poi_type, row in report["types"].items():
        print(poi_type.ljust(width) + "".join(str(row[c]).rjust(11) for c in cols))
    totals = report["totals"]
    print("total".ljust(width) + "".join(str(totals[c]).rjust(11) for c in cols))

    routes = report["routes"]
    print(
        f"[plan funnel] {routes['with_mentions']}/{routes['total']} routes have "
        f"extracted mentions; {totals['tie']} open ties in {cfg.review}, "
        f"{totals['unmatched']} unmatched in {cfg.unmatched}.",
        file=sys.stderr,
    )


def _plan_adjudicate(cfg: GuideConfig, batch_size: int) -> None:
    if not cfg.adjudication_queue.exists():
        sys.exit(f"missing {cfg.adjudication_queue} — run the matcher first.")
    with cfg.adjudication_queue.open(encoding="utf-8") as f:
        cases = [json.loads(line) for line in f]
    routes = {r["route_id"]: r for r in _load_routes(cfg)}
    cfg.verdicts_dir.mkdir(parents=True, exist_ok=True)

    missing_routes = {c["route_id"] for c in cases} - routes.keys()
    if missing_routes:
        sys.exit(
            f"{cfg.adjudication_queue}: routes {', '.join(sorted(missing_routes))} "
            "are queued but no longer in the route index — rerun the matcher first."
        )

    remaining = 0
    batches = 0
    for i in range(0, len(cases), batch_size):
        missing = [
            {
                **case,
                "route": {
                    "peak": routes[case["route_id"]].get("peak"),
                    "description": routes[case["route_id"]]["description"],
                },
            }
            for case in cases[i : i + batch_size]
            if not (cfg.verdicts_dir / f"{case['case_id']}.json").exists()
        ]
        if missing:
            print(
                json.dumps(
                    {"batch": i // batch_size + 1, "cases": missing}, ensure_ascii=False
                )
            )
            remaining += len(missing)
            batches += 1

    done = len(cases) - remaining
    if remaining:
        print(
            f"[plan adjudicate] {done}/{len(cases)} open cases have verdicts; "
            f"{remaining} remaining in {batches} batches.",
            file=sys.stderr,
        )
    elif cases:
        print(
            f"[plan adjudicate] nothing to do — all {len(cases)} open cases have "
            "verdicts (rerun the matcher to consume them).",
            file=sys.stderr,
        )
    else:
        print(
            "[plan adjudicate] nothing to do — no open adjudication cases.",
            file=sys.stderr,
        )


def _plan_extract(cfg: GuideConfig, batch_size: int) -> None:
    routes = _load_routes(cfg)
    cfg.mention_parts.mkdir(parents=True, exist_ok=True)

    remaining = 0
    batches = 0
    for i in range(0, len(routes), batch_size):
        missing = [
            {
                "route_id": r["route_id"],
                "peak": r.get("peak"),
                "description": r["description"],
            }
            for r in routes[i : i + batch_size]
            if not (cfg.mention_parts / f"{r['route_id']}.json").exists()
        ]
        if missing:
            print(
                json.dumps(
                    {"batch": i // batch_size + 1, "routes": missing},
                    ensure_ascii=False,
                )
            )
            remaining += len(missing)
            batches += 1

    done = len(routes) - remaining
    if remaining:
        print(
            f"[plan extract] {done}/{len(routes)} routes extracted; "
            f"{remaining} remaining in {batches} batches.",
            file=sys.stderr,
        )
    else:
        print(
            f"[plan extract] nothing to do — all {len(routes)} routes extracted.",
            file=sys.stderr,
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Emit batches of routes needing work.")
    ap.add_argument("stage", choices=["extract", "adjudicate", "funnel"])
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    ap.add_argument(
        "--batch",
        type=int,
        default=10,
        help="Routes (extract) or cases (adjudicate) per subagent batch.",
    )
    args = ap.parse_args()

    cfg = load_guide(args.guide)

    if args.stage == "funnel":
        _print_funnel(cfg)
    elif args.stage == "adjudicate":
        _plan_adjudicate(cfg, args.batch)
    else:
        _plan_extract(cfg, args.batch)


if __name__ == "__main__":
    main()
