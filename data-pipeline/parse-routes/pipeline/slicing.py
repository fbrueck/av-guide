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
    slice."""
    if not start_quote or not end_quote:
        return None
    start_pat = _quote_pattern(start_quote)
    end_pat = _quote_pattern(end_quote)
    if start_pat is None or end_pat is None:
        return None

    # The start anchor must pinpoint one entry: a duplicate on the page is
    # ambiguous and reported. The end anchor, by contrast, is the entry's tail —
    # taken as the first match after the start; a tail phrase (e.g. "siehe R 55.")
    # legitimately recurs across later entries, so it is not required to be unique.
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
