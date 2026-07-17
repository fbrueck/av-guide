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

Some Place headings print their Randziffer as reverse-video text on a shaded
banner, which the OCR text layer intermittently drops entirely (#86) — the
number is then in no `get_text` mode, so it cannot be re-read from the PDF. But
Randziffern ascend strictly in book order, so `infer_sequence_ids` recovers a
dropped number from its neighbours where the sequence pins it unambiguously,
falling back to the synthetic id otherwise. Purely ordinal and guide-agnostic:
no per-book numbering assumptions (see #86 for why a "multiples of five" rule
would not be).
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


def entry_id_number(canonical: str | None) -> int | None:
    """The integer part of a canonical entry id (`R280A` -> 280), or None.

    The sequence gap-fill orders entries by this ordinal; the `R` sigil and any
    letter suffix don't affect a Randziffer's position, so they are ignored.
    """
    if not canonical:
        return None
    m = re.search(r"\d+", canonical)
    return int(m.group(0)) if m else None


def infer_sequence_ids(numbers: list[int | None]) -> list[int | None]:
    """Recover dropped Randziffern from the book-ordered sequence (#86).

    `numbers` is the entries' integer ids in book order, `None` where the number
    was lost to OCR. Randziffern ascend strictly, so the `k` missing entries just
    before a recovered `next` take `next-k … next-1`. We anchor on the RIGHT, not
    `prev+1`, because the book skips numbers: an entry sits immediately before the
    following one, not immediately after the last (a dropped hut is `first_route
    - 1`, regardless of how many numbers were skipped before it).

    A run is filled only when it stays strictly above the previous recovered
    number and positive; otherwise those slots stay `None` and the caller keeps
    its deterministic synthetic fallback. Purely ordinal — no per-book numbering
    assumptions (see the module docstring), so it holds across guides. Returns a
    new list; the input is not mutated.
    """
    out = list(numbers)
    i, n = 0, len(numbers)
    while i < n:
        if numbers[i] is not None:
            i += 1
            continue
        j = i
        while j < n and numbers[j] is None:
            j += 1
        _fill_gap(out, i, j, prev=numbers[i - 1] if i > 0 else None)
        i = j
    return out


def _fill_gap(out: list[int | None], start: int, stop: int, prev: int | None) -> None:
    """Right-anchor the `None` run `out[start:stop]` from the recovered `out[stop]`.

    A no-op (run left as `None`) when there is no right anchor or the fill would
    not stay strictly above `prev` / positive — the guard against inventing an id
    the sequence doesn't pin down.
    """
    nxt = out[stop] if stop < len(out) else None
    if nxt is None:
        return
    k = stop - start
    floor = prev if prev is not None else 0
    if nxt - k <= floor:
        return
    for offset in range(k):
        out[start + offset] = nxt - k + offset


def synthetic_id(page: int, seq: int) -> str:
    """Deterministic fallback id for an Entry whose Randziffer is unrecoverable.

    Derived from the book page and the entry's 1-based sequence on it, so a
    re-run of the deterministic merge produces the identical id (no clock, no
    randomness). Flagged `id_source: synthetic` on the record.
    """
    return f"p{page:04d}_{seq:02d}"
