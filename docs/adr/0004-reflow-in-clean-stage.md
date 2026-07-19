# Text reflow moves into the ocr-cleaner clean pass, feeding the deterministic slicer

## Status

accepted — supersedes the anchor-based slicer's reliance on raw OCR line-wrapping
introduced by #95/#80 (the deterministic slice is kept; the text it cuts from is
now reflowed upstream in `02_clean`).

## Context

#95/#80 removed the single largest LLM-output cost in `parse-routes`: the
`entry-extractor` used to re-emit each Entry's full **description** verbatim,
which drifted on long copies and cost ~250K output tokens on Wetterstein. In its
place, the extractor now emits two short **boundary anchors** per Entry — a
`start_quote` at its first words and an `end_quote` at its last — and a
deterministic step (`slicing.py`) cuts the **description** out of the `02_clean`
page text between those anchors at merge, so the stored text is
exact-by-construction (`description_source: sliced`). The slice therefore
inherits the OCR's line-wrapping from the cleaned page.

The `ocr-cleaner` subagent that writes `02_clean` already reads and rewrites
every page, and already rejoins words split by a **hyphenated** line break
(`Verschnei-\ndung` → `Verschneidung`), while preserving the structural line
breaks between headings, route names, and Randziffern that the `entry-extractor`
depends on to segment the page. What it does **not** do is reflow a
*non-hyphenated* mid-word or intra-paragraph wrap: `Hochalm\nsattel` stays split,
and the slicer collapses the wrap to a single space, yielding `"Hochalm
sattel"`. When the extractor emits an anchor in its natural joined form
(`Hochalmsattel`), it no longer matches the still-split cleaned text, and the
slice returns None.

Karwendel — the first Guide run at scale through this slicer — regressed sharply
against Wetterstein: **107 unsliced Entries (9%)**, **91 empty descriptions**,
and broken mid-word splits surfacing as `"Hochalm sattel"`. The raw OCR is **not**
the cause; measured page quality is comparable to Wetterstein. The cause is
methodological: Wetterstein predates #95/#80, so its descriptions came from the
old LLM full re-emit, which *implicitly* reflowed prose as a side effect of
rewriting it — a benefit that was paid for at the ~250K-output-token cost #95/#80
deliberately removed, and that the anchor-slice path never reproduced.

## Decision

Reflow **non-hyphenated, within-paragraph** line wraps **inside the existing
`ocr-cleaner` clean pass**, so the `02_clean` page text a slice is cut from
reads as continuous prose.

- The reflow lives where the rewrite already happens. `ocr-cleaner` already reads
  and rewrites every page and already rejoins hyphenated wraps; joining a
  non-hyphenated intra-paragraph wrap is the same class of repair, on text
  already in hand. It is **not** a new stage and adds **no** new LLM pass.
- **Structural line breaks are preserved.** The breaks between headings, route
  names, entries, and Randziffern that the `entry-extractor` needs to segment a
  page are kept exactly as before; only wraps *within* a paragraph of prose are
  reflowed. Reflow of prose, not of structure.
- The **slice stays deterministic and verbatim** with respect to the cleaned
  text. `slicing.py` is unchanged in contract: it still locates the two anchors
  and cuts between them, and it still returns None (surfaced in the merge report,
  never a silently wrong slice) when an anchor cannot be located. Because the
  cleaned text now matches the joined form the extractor naturally emits, far
  more anchors locate.
- The **verbatim guarantee is, and always was, with respect to the cleaned
  text** — not the raw scan. This is not a new concession: `ocr-cleaner` already
  rejoins hyphenated wraps, so `02_clean` already differs from `01_raw` by
  design. Reflowing non-hyphenated wraps extends the same existing rule.

## Considered options

- **Reflow inside `slicing.py` instead** (join non-hyphenated wraps in the
  deterministic slicer, as it already does for hyphenated ones) — rejected: the
  slicer only sees the narrow span between two anchors and has no paragraph-vs-
  structure signal, so it cannot tell a within-paragraph wrap from a
  heading/entry break without re-deriving the page structure the cleaner already
  understands. Fixing the text where it is rewritten keeps the slicer a pure
  cut-between-anchors step.
- **Have the `entry-extractor` emit anchors in the split form** (match the
  wrapped clean text) — rejected: it pushes an OCR artifact into the anchor
  contract, is brittle to exactly how a given page wrapped, and still leaves the
  stored description reading as broken mid-word prose.
- **Re-add the LLM full re-emit** that #95/#80 removed — rejected: it re-incurs
  the ~250K-output-token cost and the long-copy drift that motivated the switch
  to anchors in the first place. The clean pass is already paid for; reflow rides
  on it for free.

## Consequences

- Recovers most of the regression: roughly **56 of the 107** unsliced Karwendel
  Entries are pure intra-word breaks that a within-paragraph reflow fixes, and
  the cleaned prose reads correctly (`"Hochalmsattel"`, not `"Hochalm sattel"`).
- **No new token cost.** The reflow is folded into the clean pass that already
  reads and rewrites every page; it does **not** re-add the ~250K-output-token
  re-emit #95/#80 removed.
- **Karwendel output shifts.** Re-cleaning changes `02_clean`, and the clean pass
  plus re-extraction are non-deterministic (LLM subagents), so re-running to pick
  up the reflow moves Karwendel's descriptions and anchors — an expected,
  one-time shift, not drift to be alarmed by.
- The `02_clean` → slice contract is otherwise unchanged: the slice is still
  deterministic and still verbatim with respect to the cleaned page, and the
  merge report still surfaces any anchor that fails to locate.
