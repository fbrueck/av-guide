"""Parse book-internal cross-references out of an Entry's verbatim prose (#42).

A **Reference** is a pointer from one Entry to another by entry id, printed
inline in the prose with a reprint sigil: the Beulke/Wetterstein `R` (`Wie R
43`, `siehe R 243`, the parenthetical `(R 243)`) or the Klier/Karwendel Randzahl
arrow `➤` OCR'd as `>`/`>-` (`>273`, `(>446)`) — see `_REF_SIGIL` (#84). A sigil
may head a **shared list** of several ids (`R 43, 243`, `R 43 und 45`), and ids
carry letter suffixes (`R 1096 b`). We also surface
the **anaphoric** `Wie dort` / `Weiter wie dort` — a reference with no id — so a
reader knows a pointer exists even though it can't be resolved (see CONTEXT.md).

Deterministic regex over the verbatim description, no LLM: each reference is
captured as `{ref_id, surface}` — `ref_id` normalized to the canonical key
(`R43`, or None for anaphora), `surface` the verbatim span as printed. A
shared-sigil list expands into one entry per id, all sharing the list's surface.
Resolution against the id set happens later, at merge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .ids import ENTRY_ID_TOKEN, normalize_entry_id


@dataclass(frozen=True, slots=True)
class Reference:
    """A book-internal cross-reference parsed from prose (see CONTEXT.md): the
    `ref_id` normalized to the canonical key (`R43`, or None for anaphora) and
    the verbatim `surface` span as printed."""

    ref_id: str | None
    surface: str

    @classmethod
    def from_dict(cls, raw: dict[str, str | None]) -> Reference:
        return cls(ref_id=raw.get("ref_id"), surface=raw["surface"] or "")

    def to_dict(self) -> dict[str, str | None]:
        return {"ref_id": self.ref_id, "surface": self.surface}


# A single numbered id inside an R-group is one ENTRY_ID_TOKEN (digits + an
# optional lone-letter suffix, defined once in ids.py so the token grammar
# doesn't drift between the two modules).
#
# The reprint sigil that heads a cross-reference is one of the two AV-Führer
# conventions (#84): the Beulke/Wetterstein `R` (`Wie R 43`, `R43` — a space may
# follow) or the Klier/Karwendel Randzahl arrow `➤`, which this stage sees only
# through the OCR text layer as `>`, usually trailed by the arrow's shaft `-`
# (`>273`, `>-273`). The two surface forms are disjoint in practice, so accepting
# either keeps one grammar for both books rather than a per-guide setting.
#
# The id **abuts** the arrow (no space) so a bare `>` comparison such as
# `> 2000 m` is never read as a reference; only the `R` sigil admits a following
# space, which is why the optional whitespace lives inside the sigil alternative
# rather than after the group.
_REF_SIGIL = r"(?:R\s*|>-?)"
# An R-group: a sigil (not mid-word) heading one id, then any number of further
# ids joined by "," or "und" (the shared-sigil list).
_R_GROUP = re.compile(
    rf"(?<![A-Za-z]){_REF_SIGIL}{ENTRY_ID_TOKEN}(?:\s*(?:,|und)\s*{ENTRY_ID_TOKEN})*"
)

# Each id token within a matched R-group, for expanding a shared-sigil list.
_NUM_RE = re.compile(ENTRY_ID_TOKEN)

# The anaphoric pointer — "wie dort" / "weiter wie dort" — carries no id.
_ANAPHORA = re.compile(r"(?:[Ww]eiter\s+)?[Ww]ie\s+dort")


def parse_references(text: str | None) -> list[Reference]:
    """Extract `Reference`s from prose, in order of appearance.

    Shared-sigil lists expand to one ref per id (shared surface); `wie dort`
    anaphora yields `ref_id: None`. Duplicate `(ref_id, surface)` pairs are
    collapsed, keeping the first occurrence.
    """
    if not text:
        return []

    hits: list[tuple[int, Reference]] = []

    for m in _R_GROUP.finditer(text):
        surface = m.group(0)
        for num in _NUM_RE.findall(surface):
            ref_id = normalize_entry_id(num)
            hits.append((m.start(), Reference(ref_id=ref_id, surface=surface)))

    for m in _ANAPHORA.finditer(text):
        hits.append((m.start(), Reference(ref_id=None, surface=m.group(0))))

    hits.sort(key=lambda h: h[0])

    out: list[Reference] = []
    seen: set[tuple[str | None, str]] = set()
    for _, ref in hits:
        key = (ref.ref_id, ref.surface)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out
