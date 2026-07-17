"""Stage 2a — deterministic OCR pre-clean (soft-hyphen dehyphenation).

Reads the raw text pages (`01_raw/pages/<stem>.txt`) and writes a lightly
repaired copy to `02_clean/prepared/<stem>.txt`, which the `ocr-cleaner`
subagent then reads instead of the raw page. This shrinks the LLM's mechanical
workload (#82) without an LLM in the loop — the deterministic core stays
offline and testable.

The one transform here is **soft-hyphen dehyphenation**: a lowercase word split
by a hyphen at a line break (`Verschnei-\ndung`) is rejoined into one word. The
rule is deliberately narrow so it can never corrupt tokens the later stages
depend on — it fires only for `<lowercase>-\n<lowercase>`:

  * a genuine hyphenated compound reads `NW-Grat` / `S-Seite` — the character
    before the hyphen (or the continuation) is uppercase, so it is left intact;
  * climbing grades (`VI-`, `V+`, roman numerals), entry ids (`• 337`), and
    reference sigils (`R 335`, `>`) never match the rule and pass through
    verbatim;
  * a blank line after the hyphen is a paragraph break, not a word wrap, so it
    is preserved.

Hyphenless line wraps and `l`/`i`/`I` confusions are *not* handled here — they
need a German lexicon to do safely, so they remain the LLM's job.

Run:  python -m pipeline.preclean --guide <id>
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from .config import GuideConfig, load_guide
from .records import PageMeta

# A lowercase word split by a hyphen at a line break: <lowercase>-\n[spaces]<lowercase>.
# The continuation may be indented (and the newline may be CRLF); the hyphen,
# newline and indent are dropped. Both flanks are lowercase (incl. äöüß) so
# compounds (`NW-Grat`) and a blank-line paragraph break are never fused. The
# continuation letter is matched as a lookahead — not consumed — so a word
# wrapped across two line breaks (`un-\nge-\nprüft`) is fully rejoined in one
# pass. See the module docstring for the guarantees.
_SOFT_HYPHEN = re.compile(r"([a-zäöüß])-\r?\n[^\S\r\n]*(?=[a-zäöüß])")


def dehyphenate(text: str) -> str:
    """Rejoin words split by a soft hyphen at a line break; everything else is
    returned verbatim."""
    return _SOFT_HYPHEN.sub(r"\1", text)


def _load_manifest(cfg: GuideConfig) -> list[PageMeta]:
    if not cfg.manifest.exists():
        sys.exit("Manifest not found — run `python -m pipeline.extract` first.")
    with cfg.manifest.open(encoding="utf-8") as f:
        return [PageMeta.from_dict(json.loads(line)) for line in f]


def preclean(cfg: GuideConfig) -> list[str]:
    """Dehyphenate each raw text page into `02_clean/prepared/`.

    Resumable: pages already prepared are skipped. Sketch pages carry no text to
    repair — the clean planner copies them straight to `02_clean/pages/` — so
    they are skipped here too.
    """
    cfg.clean_prepared.mkdir(parents=True, exist_ok=True)
    done: list[str] = []
    for r in _load_manifest(cfg):
        if r.is_sketch:
            continue
        out = cfg.clean_prepared / f"{r.stem}.txt"
        if out.exists():
            continue
        raw = (cfg.raw_pages / f"{r.stem}.txt").read_text(encoding="utf-8")
        out.write_text(dehyphenate(raw), encoding="utf-8")
        done.append(r.stem)
    return done


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Deterministically dehyphenate raw pages before LLM cleaning."
    )
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    args = ap.parse_args()
    cfg = load_guide(args.guide)

    done = preclean(cfg)
    print(f"Pre-cleaned {len(done)} pages -> {cfg.clean_prepared}")


if __name__ == "__main__":
    main()
