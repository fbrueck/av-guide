"""Deterministic planner for the agent-orchestrated LLM stages.

Claude Code (the orchestrator) calls this to get the work that still needs
an LLM — routes awaiting mention extraction, adjudication cases awaiting a
verdict — grouped into batches it can hand to subagents. No LLM here — just
filesystem bookkeeping, so reruns skip whatever is already done.

  python -m pipeline.plan extract [--batch 10]

Batches are formed over the *full* route list sorted by route_id, so batch
numbers and membership are stable across runs. A route is done once its part
file `02_mentions/parts/<route_id>.json` exists; a batch is emitted (with only
its missing routes) until every route in it is done, so an interrupted batch
resumes without redoing completed routes.

Output: one JSON object per line on stdout, e.g.
  {"batch": 1, "routes": [{"route_id": ..., "peak": ..., "description": ...}]}
A human-readable summary goes to stderr.

  python -m pipeline.plan adjudicate [--batch 10]

does the same for the LLM adjudication stage: the matcher's open cases
(03_matched/adjudication_queue.jsonl) are batched for `match-adjudicator`
subagents, each case carrying its candidate shortlist plus the route's peak
and description as context. A case is done once its verdict file
`03_matched/verdicts/<case_id>.json` exists, so interrupted runs resume
without re-adjudicating. Output: one JSON object per line, e.g.
  {"batch": 1, "cases": [{"case_id": ..., "route_id": ..., "mention": ...,
   "candidates": [...], "route": {"peak": ..., "description": ...}}]}

  python -m pipeline.plan funnel

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

from . import config


def _load_routes() -> list[dict]:
    if not config.ROUTES_JSONL.exists():
        sys.exit(f"missing {config.ROUTES_JSONL} — run the digitization pipeline first.")
    with config.ROUTES_JSONL.open(encoding="utf-8") as f:
        routes = [json.loads(line) for line in f]
    return sorted(routes, key=lambda r: r["route_id"])


def _print_funnel() -> None:
    if not config.FUNNEL.exists():
        sys.exit(f"missing {config.FUNNEL} — run the matcher first.")
    report = json.loads(config.FUNNEL.read_text(encoding="utf-8"))

    cols = ("mentions", "exact", "fuzzy", "llm", "review", "tie", "skipped", "unmatched")
    width = max(len("total"), *(len(t) for t in report["types"] or [""]))
    print("type".ljust(width) + "".join(c.rjust(11) for c in cols))
    for poi_type, row in report["types"].items():
        print(poi_type.ljust(width) + "".join(str(row[c]).rjust(11) for c in cols))
    totals = report["totals"]
    print("total".ljust(width) + "".join(str(totals[c]).rjust(11) for c in cols))

    routes = report["routes"]
    print(
        f"[plan funnel] {routes['with_mentions']}/{routes['total']} routes have "
        f"extracted mentions; {totals['tie']} open ties in {config.REVIEW}, "
        f"{totals['unmatched']} unmatched in {config.UNMATCHED}.",
        file=sys.stderr,
    )


def _plan_adjudicate(batch_size: int) -> None:
    if not config.ADJUDICATION_QUEUE.exists():
        sys.exit(f"missing {config.ADJUDICATION_QUEUE} — run the matcher first.")
    with config.ADJUDICATION_QUEUE.open(encoding="utf-8") as f:
        cases = [json.loads(line) for line in f]
    routes = {r["route_id"]: r for r in _load_routes()}
    config.VERDICTS_DIR.mkdir(parents=True, exist_ok=True)

    missing_routes = {c["route_id"] for c in cases} - routes.keys()
    if missing_routes:
        sys.exit(
            f"{config.ADJUDICATION_QUEUE}: routes {', '.join(sorted(missing_routes))} "
            "are queued but no longer in the route index — rerun the matcher first.")

    remaining = 0
    batches = 0
    for i in range(0, len(cases), batch_size):
        missing = [
            {**case,
             "route": {"peak": routes[case["route_id"]].get("peak"),
                       "description": routes[case["route_id"]]["description"]}}
            for case in cases[i : i + batch_size]
            if not (config.VERDICTS_DIR / f"{case['case_id']}.json").exists()
        ]
        if missing:
            print(json.dumps({"batch": i // batch_size + 1, "cases": missing}, ensure_ascii=False))
            remaining += len(missing)
            batches += 1

    done = len(cases) - remaining
    if remaining:
        print(f"[plan adjudicate] {done}/{len(cases)} open cases have verdicts; "
              f"{remaining} remaining in {batches} batches.", file=sys.stderr)
    elif cases:
        print(f"[plan adjudicate] nothing to do — all {len(cases)} open cases have "
              "verdicts (rerun the matcher to consume them).", file=sys.stderr)
    else:
        print("[plan adjudicate] nothing to do — no open adjudication cases.",
              file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Emit batches of routes needing work.")
    ap.add_argument("stage", choices=["extract", "adjudicate", "funnel"])
    ap.add_argument("--batch", type=int, default=10,
                    help="Routes (extract) or cases (adjudicate) per subagent batch.")
    args = ap.parse_args()

    if args.stage == "funnel":
        _print_funnel()
        return
    if args.stage == "adjudicate":
        _plan_adjudicate(args.batch)
        return

    routes = _load_routes()
    config.MENTION_PARTS.mkdir(parents=True, exist_ok=True)

    remaining = 0
    batches = 0
    for i in range(0, len(routes), args.batch):
        missing = [
            {"route_id": r["route_id"], "peak": r.get("peak"), "description": r["description"]}
            for r in routes[i : i + args.batch]
            if not (config.MENTION_PARTS / f"{r['route_id']}.json").exists()
        ]
        if missing:
            print(json.dumps({"batch": i // args.batch + 1, "routes": missing}, ensure_ascii=False))
            remaining += len(missing)
            batches += 1

    done = len(routes) - remaining
    if remaining:
        print(f"[plan extract] {done}/{len(routes)} routes extracted; "
              f"{remaining} remaining in {batches} batches.", file=sys.stderr)
    else:
        print(f"[plan extract] nothing to do — all {len(routes)} routes extracted.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
