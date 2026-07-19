"""Targeted anchor-repair pass for mismatched/ambiguous boundary anchors (#113).

The largest residual of unsliceable entries is not a slicer bug: the description
text **is** on the cleaned page, but the extractor's emitted anchor is not a
character-exact copy — one OCR-variant char (rn→m, ß, umlaut) or fragile symbol
(`®`, a `>-` arrow cross-ref) in a token breaks the match, or a too-short start
anchor repeats on the page. Those are the `start_not_found`, `start_ambiguous`,
and `end_mismatch` buckets of the unsliced report (#110).

This pass repairs them **without weakening the exact-by-construction guarantee**:
no fuzzy matching is added anywhere. Instead an LLM subagent is asked to emit
*corrected, character-exact* anchors for just those entries; merge then re-slices
deterministically, so the description stays verbatim page text.

Two deterministic entrypoints bracket the LLM step (the LLM lives in the
`anchor-repairer` subagent, never in this Python — data-pipeline/CLAUDE.md):

  python -m pipeline.repair plan  --guide <id> [--batch 15]
      Read the unsliced report, keep only the repairable buckets, and emit one
      JSON batch per line for the orchestrator to fan out to subagents. Each task
      carries the entry's id/page/name/kind, its failure reason, and its current
      (broken) anchors. Empty-anchor and stub buckets are NOT repaired here (they
      are handled by re-extraction, #112, and stub provenance, #114).

  python -m pipeline.repair apply --guide <id>
      Read the corrected-anchor files the subagents wrote under `repairs/` and
      write each entry's new anchors back into its page part file, matched by the
      book **entry id** (the part's Randziffer, unique even when headings repeat),
      falling back to the heading only when the id pins nothing. An entry that
      still cannot be placed unambiguously is skipped and surfaced — never
      guessed. Re-running `merge` then re-slices.

Re-running is safe/idempotent: `plan` only ever lists entries still in the
current unsliced report, so an entry that already sliced is never touched.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .config import GuideConfig, load_guide
from .ids import normalize_entry_id
from .records import PartEntry

# The unsliced-report reason buckets this pass repairs (#110). Empty-anchor
# entries lack anchors to correct (re-extraction, #112); stub entries have no gap
# to cut (provenance, #114) — neither is a fidelity problem, so both are excluded.
REPAIRABLE: frozenset[str] = frozenset(
    {"start_not_found", "start_ambiguous", "end_mismatch"}
)


@dataclass(frozen=True, slots=True)
class RepairTask:
    """One entry the repair pass hands a subagent: which entry to fix, on which
    page, why it failed, and its current (broken) anchors to correct."""

    entry_id: str
    source_page: int
    stem: str  # clean-page file stem the subagent reads (page_NNNN)
    name: str | None
    kind: str
    reason: str
    start_quote: str | None
    end_quote: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "source_page": self.source_page,
            "stem": self.stem,
            "name": self.name,
            "kind": self.kind,
            "reason": self.reason,
            "start_quote": self.start_quote,
            "end_quote": self.end_quote,
        }


@dataclass(frozen=True, slots=True)
class AnchorRepair:
    """The corrected anchors a subagent wrote for one entry (repairs/<id>.json),
    read back by `apply`. Matched to its part entry by book entry id (its
    Randziffer), falling back to (source_page, name) when the id pins nothing."""

    entry_id: str
    source_page: int
    name: str | None
    start_quote: str | None
    end_quote: str | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AnchorRepair:
        return cls(
            entry_id=raw["entry_id"],
            source_page=int(raw["source_page"]),
            name=raw.get("name"),
            start_quote=raw.get("start_quote"),
            end_quote=raw.get("end_quote"),
        )


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """What `apply` did: entries whose anchors were rewritten, and entries it
    could not place on their page (absent/ambiguous name) — surfaced, not
    guessed."""

    applied: list[str]
    skipped: list[str]


def _stem(page: int) -> str:
    return f"page_{page:04d}"


def _read_part_entries(cfg: GuideConfig, page: int) -> list[dict[str, Any]]:
    """The raw entry dicts of one page's part file (empty if it is absent). The
    wire dict is kept here (not parsed to PartEntry) because `apply` rewrites and
    re-serializes it in place — this is the I/O boundary itself."""
    part = cfg.struct_parts / f"{_stem(page)}.json"
    if not part.exists():
        return []
    data = json.loads(part.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = data.get("entries", [])
    return entries


def _match_entry(
    entries: list[dict[str, Any]], entry_id: str, name: str | None
) -> int | None:
    """Index of the single part entry a report/repair row targets, or None if it
    cannot be placed unambiguously — never a silent first-hit guess, mirroring the
    slicer's ambiguous-anchor rule.

    The book **entry id** is the strong key: match on the part entry's own
    Randziffer (`entry_id_raw`, normalized the same way merge keys it), which stays
    unique even when several entries on a page share a heading ("Von Süden" under
    different peaks — the case name-only matching could not place). Only when the
    id pins nothing (a dropped Randziffer left `entry_id_raw` null, or merge
    assigned an inferred/synthetic id) do we fall back to the heading, which must
    then be the lone match on the page."""
    by_id = [
        i
        for i, e in enumerate(entries)
        if normalize_entry_id(e.get("entry_id_raw")) == entry_id
    ]
    if len(by_id) == 1:
        return by_id[0]
    if name is None:
        return None
    by_name = [i for i, e in enumerate(entries) if e.get("name") == name]
    return by_name[0] if len(by_name) == 1 else None


def plan_repair(cfg: GuideConfig) -> list[RepairTask]:
    """Read the unsliced report and build a repair task per repairable entry, in
    page order. Each part file is read once; an entry's current anchors are read
    from it (matched by name) to hand the subagent as the thing to correct."""
    if not cfg.unsliced_report.exists():
        return []
    with cfg.unsliced_report.open(encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        if rec.get("reason") in REPAIRABLE:
            by_page[rec["source_page"]].append(rec)

    tasks: list[RepairTask] = []
    for page in sorted(by_page):
        entries = _read_part_entries(cfg, page)
        for rec in by_page[page]:
            idx = _match_entry(entries, rec["id"], rec.get("name"))
            current = PartEntry.from_dict(entries[idx]) if idx is not None else None
            tasks.append(
                RepairTask(
                    entry_id=rec["id"],
                    source_page=page,
                    stem=_stem(page),
                    name=rec.get("name"),
                    kind=rec["kind"],
                    reason=rec["reason"],
                    start_quote=current.start_quote if current else None,
                    end_quote=current.end_quote if current else None,
                )
            )
    return tasks


def _load_repairs(cfg: GuideConfig) -> list[AnchorRepair]:
    if not cfg.repairs_dir.exists():
        return []
    repairs: list[AnchorRepair] = []
    for path in sorted(cfg.repairs_dir.glob("*.json")):
        repairs.append(AnchorRepair.from_dict(json.loads(path.read_text("utf-8"))))
    return repairs


def apply_repairs(cfg: GuideConfig) -> ApplyResult:
    """Write each corrected anchor back into its page part file, matched by book
    entry id (heading fallback). Part files are read/written once per page. A
    repair that cannot be placed unambiguously is skipped and surfaced."""
    by_page: dict[int, list[AnchorRepair]] = defaultdict(list)
    for repair in _load_repairs(cfg):
        by_page[repair.source_page].append(repair)

    applied: list[str] = []
    skipped: list[str] = []
    for page in sorted(by_page):
        part = cfg.struct_parts / f"{_stem(page)}.json"
        if not part.exists():
            skipped.extend(r.entry_id for r in by_page[page])
            continue
        data = json.loads(part.read_text(encoding="utf-8"))
        entries: list[dict[str, Any]] = data.get("entries", [])
        changed = False
        for repair in by_page[page]:
            idx = _match_entry(entries, repair.entry_id, repair.name)
            if idx is None:
                skipped.append(repair.entry_id)
                continue
            entries[idx]["start_quote"] = repair.start_quote
            entries[idx]["end_quote"] = repair.end_quote
            applied.append(repair.entry_id)
            changed = True
        if changed:
            part.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return ApplyResult(applied=applied, skipped=skipped)


def _run_plan(cfg: GuideConfig, batch: int) -> None:
    tasks = plan_repair(cfg)
    for i in range(0, len(tasks), batch):
        chunk = [t.to_dict() for t in tasks[i : i + batch]]
        print(json.dumps({"batch": i // batch + 1, "tasks": chunk}, ensure_ascii=False))
    if not tasks:
        print(
            "[repair plan] nothing to repair — no repairable buckets.", file=sys.stderr
        )
    else:
        print(f"[repair plan] {len(tasks)} entries to repair.", file=sys.stderr)


def _run_apply(cfg: GuideConfig) -> None:
    result = apply_repairs(cfg)
    print(
        f"[repair apply] {len(result.applied)} anchors rewritten, "
        f"{len(result.skipped)} skipped (entry not placeable on page).",
        file=sys.stderr,
    )
    if result.skipped:
        print(f"  skipped: {result.skipped}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Plan/apply the targeted anchor-repair pass (#113)."
    )
    ap.add_argument("stage", choices=["plan", "apply"])
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    ap.add_argument("--batch", type=int, default=15, help="Repair tasks per batch.")
    args = ap.parse_args()

    cfg = load_guide(args.guide)
    if args.stage == "plan":
        _run_plan(cfg, args.batch)
    else:
        _run_apply(cfg)


if __name__ == "__main__":
    main()
