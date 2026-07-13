"""Canonical entry-id handling for the Entry model (#42).

Every Entry (Place or Route) is identified by the book's own **entry id**: a
bulleted bare number printed in the margin (a *Randziffer*, `•43`), optionally
with a lowercase letter suffix (`•376 A`). Prose cross-references reprint the
same id with an `R` sigil (`Wie R 43`). Both surface forms normalize to one
canonical key — strip the bullet/sigil and inter-token space, drop leading
zeros, uppercase the suffix — so `•376 A`, `R 376 a` and `R376A` all resolve to
`R376A` and a Reference maps straight onto the Entry it points at (see
CONTEXT.md, ADR 0001).

Pure string logic, no LLM: the extractor subagent reads the mangled OCR bullet
and hands us its best literal reading of the id token; normalization here turns
that into the canonical key and is fully unit-tested. `references.py` reuses
`ENTRY_ID_TOKEN` so the token grammar lives in exactly one place.
"""

from __future__ import annotations

import re

# The shape of a printed entry-id token: a run of digits then an optional
# *lone*-letter suffix. The whitespace sits inside the optional suffix group so
# a trailing word is neither consumed nor mistaken for a suffix — a traverse
# token like "271 Unterleutasch" yields just "271", not "271 U". Non-capturing
# so it can be embedded (and repeated) inside a larger pattern in references.py.
ENTRY_ID_TOKEN = r"\d+(?:\s*[A-Za-z](?![A-Za-z]))?"

# Anything before the digits (an OCR-mangled bullet `•`/`°`/`«`/`*`, an `R`
# sigil, whitespace) is ignored — search finds the first token in the string.
_TOKEN_RE = re.compile(ENTRY_ID_TOKEN)


def normalize_entry_id(raw: str | None) -> str | None:
    """Normalize a printed/reprinted id token to the canonical key (`R376A`).

    Returns None when no integer is recoverable (OCR loss, an unnumbered
    heading) — the caller then assigns a deterministic `synthetic_id`.
    """
    if not raw:
        return None
    m = _TOKEN_RE.search(raw)
    if not m:
        return None
    token = m.group(0).replace(" ", "")
    if token[-1].isalpha():
        number, suffix = int(token[:-1]), token[-1].upper()
    else:
        number, suffix = int(token), ""  # int() drops any zero-padding
    return f"R{number}{suffix}"


def synthetic_id(page: int, seq: int) -> str:
    """Deterministic fallback id for an Entry whose Randziffer is unrecoverable.

    Derived from the book page and the entry's 1-based sequence on it, so a
    re-run of the deterministic merge produces the identical id (no clock, no
    randomness). Flagged `id_source: synthetic` on the record.
    """
    return f"p{page:04d}_{seq:02d}"
