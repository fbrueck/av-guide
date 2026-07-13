"""Parse book-internal cross-references out of an Entry's verbatim prose (#42).

A **Reference** is a pointer from one Entry to another by entry id, printed
inline in the prose with an `R` sigil: `Wie R 43`, `siehe R 243`, the
parenthetical `(R 243)`, a **shared-`R` list** where one `R` heads several ids
(`R 43, 243`, `R 43 und 45`), and letter suffixes (`R 1096 b`). We also surface
the **anaphoric** `Wie dort` / `Weiter wie dort` — a reference with no id — so a
reader knows a pointer exists even though it can't be resolved (see CONTEXT.md).

Deterministic regex over the verbatim description, no LLM: each reference is
captured as `{ref_id, surface}` — `ref_id` normalized to the canonical key
(`R43`, or None for anaphora), `surface` the verbatim span as printed. A
shared-`R` list expands into one entry per id, all sharing the list's surface.
Resolution against the id set happens later, at merge.
"""

from __future__ import annotations

import re

from .ids import ENTRY_ID_TOKEN, normalize_entry_id

# A single numbered id inside an R-group is one ENTRY_ID_TOKEN (digits + an
# optional lone-letter suffix, defined once in ids.py so the token grammar
# doesn't drift between the two modules).
# An R-group: an uppercase `R` sigil (not mid-word) heading one id, then any
# number of further ids joined by "," or "und" (the shared-`R` list).
_R_GROUP = re.compile(
    rf"(?<![A-Za-z])R\s*{ENTRY_ID_TOKEN}(?:\s*(?:,|und)\s*{ENTRY_ID_TOKEN})*"
)

# Each id token within a matched R-group, for expanding a shared-`R` list.
_NUM_RE = re.compile(ENTRY_ID_TOKEN)

# The anaphoric pointer — "wie dort" / "weiter wie dort" — carries no id.
_ANAPHORA = re.compile(r"(?:[Ww]eiter\s+)?[Ww]ie\s+dort")


def parse_references(text: str | None) -> list[dict]:
    """Extract `{ref_id, surface}` references from prose, in order of appearance.

    Shared-`R` lists expand to one ref per id (shared surface); `wie dort`
    anaphora yields `ref_id: None`. Duplicate `(ref_id, surface)` pairs are
    collapsed, keeping the first occurrence.
    """
    if not text:
        return []

    hits: list[tuple[int, dict]] = []

    for m in _R_GROUP.finditer(text):
        surface = m.group(0)
        for num in _NUM_RE.findall(surface):
            ref_id = normalize_entry_id(num)
            hits.append((m.start(), {"ref_id": ref_id, "surface": surface}))

    for m in _ANAPHORA.finditer(text):
        hits.append((m.start(), {"ref_id": None, "surface": m.group(0)}))

    hits.sort(key=lambda h: h[0])

    out: list[dict] = []
    seen: set[tuple[str | None, str]] = set()
    for _, ref in hits:
        key = (ref["ref_id"], ref["surface"])
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out
