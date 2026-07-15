"""Deterministic planner for the agent-orchestrated LLM stages.

Claude Code (the orchestrator) calls this to get the work that still needs
an LLM — entries awaiting mention extraction, adjudication cases awaiting a
verdict — grouped into batches it can hand to subagents. No LLM here — just
filesystem bookkeeping, so reruns skip whatever is already done.

  python -m pipeline.plan extract --guide <id> [--batch 10]

Batches are formed over the *full* entry list sorted by entry id, so batch
numbers and membership are stable across runs. Mention extraction runs over
**any** Entry's prose (a Route description or a Place Übersicht), so every
entry is batched. An entry is done once its part file
`02_mentions/parts/<entry_id>.json` exists; a batch is emitted (with only its
missing entries) until every entry in it is done, so an interrupted batch
resumes without redoing completed entries.

Output: one JSON object per line on stdout, e.g.
  {"batch": 1, "entries": [{"entry_id": ..., "kind": ..., "name": ...,
   "description": ...}]}
A human-readable summary goes to stderr.

  python -m pipeline.plan adjudicate --guide <id> [--batch 10]

does the same for the LLM adjudication stage: the matcher's open cases
(03_matched/adjudication_queue.jsonl) are batched for `match-adjudicator`
subagents, each case carrying its candidate shortlist plus the owning entry's
name/kind/peak, its resolved Destination (name + that Place's POI, a geographic
prior), and description as context. A case is done once its verdict file
`03_matched/verdicts/<case_id>.json` exists, so interrupted runs resume
without re-adjudicating. Output: one JSON object per line, e.g.
  {"batch": 1, "cases": [{"case_id": ..., "entry_id": ..., "mention": ...,
   "candidates": [...], "entry": {"name": ..., "kind": ..., "peak": ...,
   "destination": {"name": ..., "poi": {...}} | null, "description": ...}}]}

  python -m pipeline.plan funnel --guide <id>

prints the matcher's funnel (03_matched/funnel.json) as a per-type table —
mentions -> exact / fuzzy / llm / review / tie / skipped / unmatched — with a
totals row on stdout and the usual one-line summary on stderr. The `place` row
counts Place->POI resolution; the other rows count mentions by type. `llm`
counts adjudicator picks (cascade matches stay under exact/fuzzy); `review`
counts human-accepted decisions; `tie` counts only still-open cases.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .config import GuideConfig, load_guide


def _load_entries(cfg: GuideConfig) -> list[dict[str, Any]]:
    if not cfg.routes_jsonl.exists():
        sys.exit(f"missing {cfg.routes_jsonl} — run the parse-routes pipeline first.")
    with cfg.routes_jsonl.open(encoding="utf-8") as f:
        entries = [json.loads(line) for line in f]
    return sorted(entries, key=lambda e: e["id"])


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

    entries = report["entries"]
    print(
        f"[plan funnel] {entries['with_mentions']}/{entries['total']} entries have "
        f"extracted mentions; {totals['tie']} open ties in {cfg.review}, "
        f"{totals['unmatched']} unmatched in {cfg.unmatched}.",
        file=sys.stderr,
    )


def _load_place_pois(cfg: GuideConfig) -> dict[str, dict[str, Any]]:
    """Map a Place's entry id to its resolved POI record (name/type/ele/coords),
    joining place_pois.jsonl through pois.jsonl. Empty when the matcher has not
    yet produced its final artifacts — a Destination then carries a null POI."""
    if not cfg.place_pois_jsonl.exists() or not cfg.pois_jsonl.exists():
        return {}
    poi_by_id: dict[str, dict[str, Any]] = {}
    with cfg.pois_jsonl.open(encoding="utf-8") as f:
        for line in f:
            poi = json.loads(line)
            poi_by_id[poi["poi_id"]] = poi
    place_poi: dict[str, dict[str, Any]] = {}
    with cfg.place_pois_jsonl.open(encoding="utf-8") as f:
        for line in f:
            link = json.loads(line)
            poi = poi_by_id.get(link["poi_id"])
            if poi is not None:
                place_poi[link["place_id"]] = poi
    return place_poi


def _destination_context(
    entry: dict[str, Any],
    entries: dict[str, dict[str, Any]],
    place_poi: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """The owning entry's resolved Destination as a geographic prior for the
    adjudicator: the parent Place's name plus that Place's POI (a compact
    coordinate/type/elevation projection, or null when the Place resolved to no
    POI). None when the entry has no Destination (`destination_id` null, or a
    Place, which never has one)."""
    dest_id = entry.get("destination_id")
    if dest_id is None:
        return None
    place = entries.get(dest_id)
    poi = place_poi.get(dest_id)
    return {
        "name": place.get("name") if place else None,
        "poi": (
            {
                "name": poi["name"],
                "type": poi["type"],
                "ele": poi["ele"],
                "lat": poi["lat"],
                "lon": poi["lon"],
            }
            if poi
            else None
        ),
    }


def _plan_adjudicate(cfg: GuideConfig, batch_size: int) -> None:
    if not cfg.adjudication_queue.exists():
        sys.exit(f"missing {cfg.adjudication_queue} — run the matcher first.")
    with cfg.adjudication_queue.open(encoding="utf-8") as f:
        cases = [json.loads(line) for line in f]
    entries = {e["id"]: e for e in _load_entries(cfg)}
    place_poi = _load_place_pois(cfg)
    cfg.verdicts_dir.mkdir(parents=True, exist_ok=True)

    missing_entries = {c["entry_id"] for c in cases} - entries.keys()
    if missing_entries:
        sys.exit(
            f"{cfg.adjudication_queue}: entries {', '.join(sorted(missing_entries))} "
            "are queued but no longer in the entry index — rerun the matcher first."
        )

    remaining = 0
    batches = 0
    for i in range(0, len(cases), batch_size):
        missing = [
            {
                **case,
                "entry": {
                    "name": entries[case["entry_id"]].get("name"),
                    "kind": entries[case["entry_id"]]["kind"],
                    "peak": entries[case["entry_id"]].get("peak"),
                    "destination": _destination_context(
                        entries[case["entry_id"]], entries, place_poi
                    ),
                    "description": entries[case["entry_id"]]["description"],
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
    entries = _load_entries(cfg)
    cfg.mention_parts.mkdir(parents=True, exist_ok=True)

    remaining = 0
    batches = 0
    for i in range(0, len(entries), batch_size):
        missing = [
            {
                "entry_id": e["id"],
                "kind": e["kind"],
                "name": e.get("name"),
                "description": e["description"],
            }
            for e in entries[i : i + batch_size]
            if not (cfg.mention_parts / f"{e['id']}.json").exists()
        ]
        if missing:
            print(
                json.dumps(
                    {"batch": i // batch_size + 1, "entries": missing},
                    ensure_ascii=False,
                )
            )
            remaining += len(missing)
            batches += 1

    done = len(entries) - remaining
    if remaining:
        print(
            f"[plan extract] {done}/{len(entries)} entries extracted; "
            f"{remaining} remaining in {batches} batches.",
            file=sys.stderr,
        )
    else:
        print(
            f"[plan extract] nothing to do — all {len(entries)} entries extracted.",
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
