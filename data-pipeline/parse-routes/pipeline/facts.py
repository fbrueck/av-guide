"""Emit a guide's bibliographic facts as a block the orchestrator injects into
the LLM subagents.

Deterministic, no LLM. The parse-routes orchestrator runs this once per guide
and pastes the rendered block into each `ocr-cleaner` (and future guide-aware
subagent) invocation. That keeps the subagent prompts guide-agnostic: the
guidebook's title/author/edition/year/language flow from `guides/<id>/config.yml`
at invocation time, never baked into a prompt body (#147).

  python -m pipeline.facts --guide <id>

Output: the rendered facts block on stdout.
"""

from __future__ import annotations

import argparse

from .config import GuideFacts, load_guide


def render_facts_block(facts: GuideFacts) -> str:
    """Render the guide facts as a plain block for a subagent prompt."""
    return "\n".join(
        [
            "Guide facts for this run (the guidebook these scanned pages are from):",
            f"- Title: {facts.title}",
            f"- Author: {facts.author}",
            f"- Edition: {facts.edition}",
            f"- Year: {facts.year}",
            f"- Language: {facts.language}",
        ]
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Emit a guide's facts block for the subagents."
    )
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    args = ap.parse_args()
    print(render_facts_block(load_guide(args.guide).facts))


if __name__ == "__main__":
    main()
