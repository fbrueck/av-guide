"""Slice an Entry's verbatim description out of the cleaned page text.

The entry-extractor no longer re-emits each entry's full text (that was the
single largest LLM-output cost and drifts on long copies, #80). Instead it emits
two short **boundary anchors** per entry — a `start_quote` at the entry's first
words and an `end_quote` at its last — and this deterministic step cuts the text
between them out of the `02_clean` page text during merge, so the stored
description is exact-by-construction.

What it handles (grounded in the real OCR):

- **Whitespace drift.** Anchors are matched token-by-token with flexible
  whitespace, so a quote the LLM emitted with spaces still matches text the OCR
  wrapped across lines.
- **Page-break spans.** An entry can start near the bottom of one page and end
  on the next; when the `end_quote` is not on the start page, the slice stitches
  the start page's tail onto the next page's head.
- **Footer noise + hyphenation.** Running page-number footers (a bare integer on
  its own line) are dropped, hyphenated line breaks (`De-\nzember`) are rejoined,
  and the remaining line wrapping is reflowed to single spaces.
- **Anchor words split by a hyphenated line break.** The anchors are located on
  the raw page first (unchanged, exact); only if that fails is the same
  locate-and-slice retried on the *reflowed* page, so an anchor whose word the
  OCR split across a line (`Landes-\nkrankenhaus`) still matches (#111). The raw
  attempt always wins when it succeeds, so slices that worked before are
  byte-identical; the fallback rejoins hyphenation only — it adds **no** fuzzy
  matching, so a near-miss anchor still returns None.

An anchor that cannot be located — or a start anchor that is *ambiguous* (occurs
more than once on the page) — returns None, and the caller (merge) surfaces the
gap in its report rather than storing a silently wrong slice.
"""

from __future__ import annotations

import re

# A bare page-number footer: a 1-4 digit integer alone on its line.
_FOOTER_LINE = re.compile(r"(?m)^[ \t]*\d{1,4}[ \t]*$")
# A hyphenated line break (optionally with a footer's blank line between).
_HYPHEN_BREAK = re.compile(r"-\n\s*")
_WHITESPACE = re.compile(r"\s+")


def _quote_pattern(quote: str) -> re.Pattern[str] | None:
    """A regex matching the quote's tokens with flexible whitespace between them
    (so a space-joined quote still matches text the OCR wrapped across lines).
    None if the quote has no word tokens."""
    tokens = quote.split()
    if not tokens:
        return None
    return re.compile(r"\s+".join(re.escape(tok) for tok in tokens))


def _locate(pattern: re.Pattern[str], text: str, pos: int = 0) -> re.Match[str] | None:
    """The single match of `pattern` in `text` at/after `pos`, or None if it is
    absent OR occurs more than once. An ambiguous anchor must never be silently
    resolved to its first hit — that could slice the wrong entry."""
    first = pattern.search(text, pos)
    if first is None or pattern.search(text, first.end()) is not None:
        return None
    return first


def _reflow(text: str) -> str:
    """Drop footer page-number lines, rejoin hyphenated line breaks, and reflow
    the remaining line wrapping to single spaces."""
    text = _FOOTER_LINE.sub("", text)
    text = _HYPHEN_BREAK.sub("", text)
    return _WHITESPACE.sub(" ", text).strip()


def _locate_and_slice(
    page_text: str,
    next_page_text: str | None,
    start_pat: re.Pattern[str],
    end_pat: re.Pattern[str],
) -> str | None:
    """Cut the span between the two anchors out of one page's text, reflowed.

    The start anchor must pinpoint one entry: a duplicate on the page is
    ambiguous and reported (None). The end anchor, by contrast, is the entry's
    tail — taken as the first match after the start; a tail phrase (e.g.
    "siehe R 55.") legitimately recurs across later entries, so it is not
    required to be unique. If the `end_quote` is not on this page, the entry
    spans the page break: stitch on the head of `next_page_text`."""
    start = _locate(start_pat, page_text)
    if start is None:
        return None

    same_page_end = end_pat.search(page_text, start.end())
    if same_page_end is not None:
        return _reflow(page_text[start.start() : same_page_end.end()])

    if next_page_text:
        spill = end_pat.search(next_page_text)
        if spill is not None:
            return _reflow(
                page_text[start.start() :] + "\n" + next_page_text[: spill.end()]
            )

    return None


def slice_description(
    page_text: str,
    next_page_text: str | None,
    start_quote: str | None,
    end_quote: str | None,
) -> str | None:
    """Cut the text between the two anchors out of `page_text`, reflowed. If the
    `end_quote` is not on this page, stitch on the head of `next_page_text` (the
    entry spans the page break). Returns None if either anchor is missing, cannot
    be located, or the start anchor is ambiguous — never a partial or misplaced
    slice.

    Anchors are matched on the raw page first (exact, unchanged). Only if that
    fails is the same locate-and-slice retried on the *reflowed* page, so an
    anchor whose word was split by a hyphenated line break still matches (#111).
    The raw attempt wins whenever it succeeds — slices that worked before are
    identical — and the fallback rejoins hyphenation only, introducing no fuzzy
    matching."""
    if not start_quote or not end_quote:
        return None
    start_pat = _quote_pattern(start_quote)
    end_pat = _quote_pattern(end_quote)
    if start_pat is None or end_pat is None:
        return None

    raw = _locate_and_slice(page_text, next_page_text, start_pat, end_pat)
    if raw is not None:
        return raw

    # Reflow-fallback (#111): the same exact locate-and-slice on the reflowed
    # page(s), which rejoins hyphen-split anchor words. Still exact — an anchor
    # that does not occur token-for-token in the reflowed text stays unmatched.
    reflowed = _reflow(page_text)
    reflowed_next = _reflow(next_page_text) if next_page_text else None
    return _locate_and_slice(reflowed, reflowed_next, start_pat, end_pat)


# The reason buckets `unsliced_reason` classifies an unsliceable entry into.
# They partition the unsliced set — every failure gets exactly one (#110).
UnslicedReason = str  # one of: empty_anchor | stub | start_not_found |
#                                start_ambiguous | end_mismatch


def _token_key(quote: str) -> str:
    """The whitespace-normalized key of a quote, matching how `_quote_pattern`
    tokenizes it — so two anchors compare equal iff they differ only in spacing."""
    return " ".join(quote.split())


def unsliced_reason(
    page_text: str,
    next_page_text: str | None,
    start_quote: str | None,
    end_quote: str | None,
) -> UnslicedReason:
    """Classify *why* `slice_description` failed for this entry, into one bucket
    (#110). Call only when `slice_description` returned None; the buckets are:

    - `empty_anchor`  — an anchor is missing/blank (no word tokens to match).
    - `stub`          — start and end anchors are equal: no gap to cut (the
                        body-less `□` cross-ref stubs, #114).
    - `start_not_found` — the start anchor occurs nowhere (OCR-variant char).
    - `start_ambiguous` — the start anchor occurs more than once (can't pinpoint).
    - `end_mismatch`  — the start is unique but no end anchor is reachable.

    The start diagnosis mirrors the slicer's raw-then-reflow fallback: the first
    page text the start appears in decides start-vs-end, so a hyphen-split start
    is judged on the reflowed text, not miscalled `start_not_found`."""
    if not start_quote or not end_quote:
        return "empty_anchor"
    start_pat = _quote_pattern(start_quote)
    end_pat = _quote_pattern(end_quote)
    if start_pat is None or end_pat is None:
        return "empty_anchor"
    if _token_key(start_quote) == _token_key(end_quote):
        return "stub"
    for text in (page_text, _reflow(page_text)):
        hits = sum(1 for _ in start_pat.finditer(text))
        if hits == 0:
            continue
        return "start_ambiguous" if hits > 1 else "end_mismatch"
    return "start_not_found"
