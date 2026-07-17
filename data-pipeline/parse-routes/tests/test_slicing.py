"""Slicer tests, driven by real cleaned-page excerpts from the wetterstein guide
(footer noise, line wrapping, dropped hyphens, and a genuine page-break span)."""

from pipeline.slicing import slice_description

# Real page 33 tail (wetterstein 02_clean): a previous entry, then entry •65
# Stuibenhütte, whose text wraps ("Stuibenmauer ge\nlegene"), loses a hyphen at
# the very bottom ("Hüttenwart De-"), and ends with the "61" page-number footer.
PAGE_33 = (
    "Hochalm, 1705 m\n"
    "Almhütte, im Sommer bewirtschaftet.\n"
    "65\n"
    "Stuibenhütte, 1620 m\n"
    "Auf der Stuibenalm über der Waldgrenze hart an der Stuibenmauer ge\n"
    "legene Skihütte der DAV S. Garmisch-Partenkirchen. Hüttenwart De-\n"
    "61"
)
# Real page 34 head: the "zember" continuation of entry •65, then entry •66.
PAGE_34 = (
    "zember bis April. 30 M.\n"
    "Zugang: In 1 1/4 Std. vom Kreuzeck, siehe R 55.\n"
    "•\n"
    "66\n"
    "Trögelhütte (Forstamtshütte), 1489 m\n"
    "Halbwegs zwischen Rießerkopfhütte und Kreuzeck.\n"
    "63"
)


def test_slices_entry_that_spans_a_page_break():
    # •65 starts near the bottom of page 33 and finishes on page 34: the footer
    # is dropped, the "De-\nzember" hyphenation rejoined, wrapping reflowed.
    desc = slice_description(PAGE_33, PAGE_34, "Stuibenhütte, 1620 m", "siehe R 55.")
    assert desc == (
        "Stuibenhütte, 1620 m Auf der Stuibenalm über der Waldgrenze hart an der "
        "Stuibenmauer ge legene Skihütte der DAV S. Garmisch-Partenkirchen. "
        "Hüttenwart Dezember bis April. 30 M. Zugang: In 1 1/4 Std. vom Kreuzeck, "
        "siehe R 55."
    )


def test_slices_entry_contained_on_one_page():
    desc = slice_description(
        PAGE_34, None, "Trögelhütte (Forstamtshütte), 1489 m", "und Kreuzeck."
    )
    assert desc == (
        "Trögelhütte (Forstamtshütte), 1489 m Halbwegs zwischen "
        "Rießerkopfhütte und Kreuzeck."
    )


def test_start_anchor_skips_an_earlier_entry_on_the_page():
    # The start anchor is matched at the entry, not the "Hochalm" text above it.
    desc = slice_description(
        PAGE_33, PAGE_34, "Stuibenhütte, 1620 m", "Skihütte der DAV"
    )
    assert desc.startswith("Stuibenhütte, 1620 m Auf der Stuibenalm")
    assert "Hochalm" not in desc


def test_anchor_whitespace_is_matched_flexibly():
    # The quote is space-joined; the text wrapped it across a newline — still matches.
    desc = slice_description(
        PAGE_33, PAGE_34, "an der Stuibenmauer ge legene", "Skihütte der DAV"
    )
    assert desc == "an der Stuibenmauer ge legene Skihütte der DAV"


def test_unlocatable_end_anchor_returns_none():
    assert (
        slice_description(PAGE_33, PAGE_34, "Stuibenhütte, 1620 m", "kommt nicht vor")
        is None
    )


def test_unlocatable_start_anchor_returns_none():
    assert slice_description(PAGE_33, PAGE_34, "gibt es nicht", "siehe R 55.") is None


def test_missing_anchor_returns_none():
    assert slice_description(PAGE_33, PAGE_34, None, "siehe R 55.") is None
    assert slice_description(PAGE_33, PAGE_34, "Stuibenhütte, 1620 m", None) is None


def test_ambiguous_start_anchor_returns_none():
    # A start anchor that occurs twice on the page can't pinpoint one entry, so
    # it is reported (None) rather than silently resolved to its first hit.
    page = "Gipfelweg, 100 m\nErster Text. Ende eins.\nGipfelweg, 100 m\nZweiter Text. Ende zwei."
    assert slice_description(page, None, "Gipfelweg, 100 m", "Ende eins.") is None


def test_recurring_end_anchor_is_not_ambiguous():
    # A tail phrase that recurs in a later entry is fine — the end is the first
    # match after the (unique) start, giving this entry's own text.
    page = "Erster Gipfel\nWeg dorthin, siehe R 5.\nZweiter Gipfel\nAnderer Weg, siehe R 5."
    desc = slice_description(page, None, "Erster Gipfel", "siehe R 5.")
    assert desc == "Erster Gipfel Weg dorthin, siehe R 5."
