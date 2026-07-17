"""Slicer tests, driven by real cleaned-page excerpts from the wetterstein guide
(footer noise, line wrapping, dropped hyphens, and a genuine page-break span)."""

from pipeline.slicing import slice_description, unsliced_reason

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


# --- reflow-fallback for hyphenated-line-break anchors (#111) ------------------

# Real karwendel page-15 excerpt (Hochzirl •15): the closing sentence's
# "Landeskrankenhaus" is printed split across a hyphenated line break
# ("Landes-\nkrankenhaus"), so the raw text has no token "Landeskrankenhaus" for
# the end anchor to match. It slices only once the reflow rejoins the hyphen.
KARWENDEL_P15_HOCHZIRL = (
    "Hochzirl, 922 m\n"
    "Station der Karwendelbahn, Ausgangspunkt für Solsteinhaus und Mag-\n"
    "deburger Hütte. Parkmöglichkeit knapp unterhalb an der Straße. Landes-\n"
    "krankenhaus oberhalb im Wald.\n"
    "16"
)


def test_reflow_fallback_recovers_hyphen_split_end_anchor():
    # The end anchor's word is split by a hyphenated line break; the raw match
    # fails, and the reflow-fallback rejoins it and slices the full description.
    desc = slice_description(
        KARWENDEL_P15_HOCHZIRL,
        None,
        "Hochzirl, 922 m",
        "Landeskrankenhaus oberhalb im Wald.",
    )
    assert desc == (
        "Hochzirl, 922 m Station der Karwendelbahn, Ausgangspunkt für "
        "Solsteinhaus und Magdeburger Hütte. Parkmöglichkeit knapp unterhalb an "
        "der Straße. Landeskrankenhaus oberhalb im Wald."
    )


def test_reflow_fallback_recovers_hyphen_split_start_anchor():
    # A start anchor whose word is hyphen-split is likewise recovered by reflow.
    desc = slice_description(
        KARWENDEL_P15_HOCHZIRL,
        None,
        "Magdeburger Hütte.",
        "Landeskrankenhaus oberhalb im Wald.",
    )
    assert desc == (
        "Magdeburger Hütte. Parkmöglichkeit knapp unterhalb an der Straße. "
        "Landeskrankenhaus oberhalb im Wald."
    )


def test_raw_match_still_wins_when_it_succeeds():
    # When the raw text already matches, the fallback must not change the result:
    # the slice is identical to the pre-#111 behaviour (no double-reflow drift).
    desc = slice_description(
        PAGE_34, None, "Trögelhütte (Forstamtshütte), 1489 m", "und Kreuzeck."
    )
    assert desc == (
        "Trögelhütte (Forstamtshütte), 1489 m Halbwegs zwischen "
        "Rießerkopfhütte und Kreuzeck."
    )


def test_near_miss_end_anchor_stays_none_no_fuzzy_match():
    # The reflow-fallback rejoins hyphenation only — it introduces NO fuzzy
    # matching. A plausible-but-inexact end anchor ("im Walde." vs printed
    # "im Wald.") must still slice to None, not snap to the near-miss (#113).
    assert (
        slice_description(
            KARWENDEL_P15_HOCHZIRL,
            None,
            "Hochzirl, 922 m",
            "oberhalb im Walde.",
        )
        is None
    )


# --- unsliced_reason classification (#110) ------------------------------------

_PAGE = "55\nKreuzeckhaus, 1652 m\nGroße Hütte, siehe R 40. Ende hier."


def test_reason_empty_anchor_for_missing_or_wordless_anchor():
    assert unsliced_reason(_PAGE, None, None, "Ende hier.") == "empty_anchor"
    assert unsliced_reason(_PAGE, None, "Kreuzeckhaus", None) == "empty_anchor"
    # An anchor with no word tokens (whitespace only) cannot be matched either.
    assert unsliced_reason(_PAGE, None, "   ", "Ende hier.") == "empty_anchor"


def test_reason_stub_when_start_equals_end():
    # start == end (up to whitespace) → no gap to cut: the body-less □ stubs.
    assert (
        unsliced_reason(_PAGE, None, "Kreuzeckhaus, 1652 m", "Kreuzeckhaus,  1652 m")
        == "stub"
    )


def test_reason_start_not_found_for_absent_start_anchor():
    assert (
        unsliced_reason(_PAGE, None, "Nicht vorhanden", "Ende hier.")
        == "start_not_found"
    )


def test_reason_start_ambiguous_when_start_repeats():
    page = "Gipfelweg, 100 m\nErster Text.\nGipfelweg, 100 m\nZweiter Text."
    assert (
        unsliced_reason(page, None, "Gipfelweg, 100 m", "kommt nicht vor")
        == "start_ambiguous"
    )


def test_reason_end_mismatch_when_start_unique_but_end_absent():
    assert (
        unsliced_reason(_PAGE, None, "Kreuzeckhaus, 1652 m", "gibt es nicht")
        == "end_mismatch"
    )


# --- body-less stub: identical anchors have no span to cut (#114) --------------


def test_identical_start_and_end_anchors_slice_to_none():
    # A body-less □ cross-ref stub: the extractor emits start == end, so there is
    # no gap between them to cut — the slicer returns None (merge stores the
    # one-line text and flags it `stub` instead).
    page = "□ 1362 Durch das Große Ödkar, I\nWie >-1361, jedoch weiter rechts.\n□ 1363"
    quote = "Durch das Große Ödkar, I"  # extractor emits start == end
    assert slice_description(page, None, quote, quote) is None
    assert unsliced_reason(page, None, quote, quote) == "stub"
