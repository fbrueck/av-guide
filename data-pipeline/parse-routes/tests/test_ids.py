import pytest

from pipeline.ids import (
    entry_id_number,
    infer_sequence_ids,
    normalize_entry_id,
    synthetic_id,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Bare bulleted number → R + integer.
        ("55", "R55"),
        ("•55", "R55"),
        ("43", "R43"),
        # Lowercase letter suffix is uppercased, inter-token space stripped.
        ("376 A", "R376A"),
        ("1096 b", "R1096B"),
        ("1096d", "R1096D"),
        # Prose reprints the id with an R sigil — the sigil is dropped, not doubled.
        ("R 43", "R43"),
        ("R376A", "R376A"),
        ("r 243", "R243"),
        # OCR bullet variants the LLM may leave on the token.
        ("°337", "R337"),
        ("«271", "R271"),
        ("*337 A", "R337A"),
        # Leading zeros from zero-padding collapse (it's an integer).
        ("055", "R55"),
    ],
)
def test_normalize_entry_id(raw, expected):
    assert normalize_entry_id(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "   ", "—", "Nordwestgrat", "R"])
def test_normalize_entry_id_unrecoverable(raw):
    # No integer to recover → None, so the caller assigns a synthetic id.
    assert normalize_entry_id(raw) is None


def test_normalize_entry_id_takes_first_number():
    # A traverse heading token like "271 Unterleutasch" carries the id first.
    assert normalize_entry_id("271 Unterleutasch") == "R271"


def test_synthetic_id_is_deterministic_and_flagged_shape():
    assert synthetic_id(51, 1) == "p0051_01"
    assert synthetic_id(51, 12) == "p0051_12"
    # Stable across calls (no clock / randomness).
    assert synthetic_id(7, 3) == synthetic_id(7, 3)


@pytest.mark.parametrize(
    "canonical,expected",
    [
        ("R280", 280),
        ("R376A", 376),  # the letter suffix is not part of the ordinal position
        ("R55", 55),
        (None, None),
        ("", None),
    ],
)
def test_entry_id_number(canonical, expected):
    assert entry_id_number(canonical) == expected


# --- infer_sequence_ids (gap-fill) --------------------------------------------


def test_infer_fills_single_gap_right_anchored():
    # 276 (route), [Randziffer dropped], 281 (route): the entry is 280 = next-1,
    # NOT prev+1 (=277) — the book skipped 277–279, so we anchor on the right.
    assert infer_sequence_ids([276, None, 281]) == [276, 280, 281]


def test_infer_fills_consecutive_run_from_the_right():
    assert infer_sequence_ids([285, None, None, 288]) == [285, 286, 287, 288]


def test_infer_declines_when_fill_would_not_stay_above_prev():
    # Only two integers of room (286, 287) but three missing → filling would
    # collide with prev, so the slots stay None (deterministic synthetic later).
    assert infer_sequence_ids([285, None, None, None, 288]) == [
        285,
        None,
        None,
        None,
        288,
    ]


def test_infer_declines_without_a_next_anchor():
    # A trailing run has nothing to anchor to on the right.
    assert infer_sequence_ids([285, None, None]) == [285, None, None]


def test_infer_leading_gap_fills_only_while_positive():
    assert infer_sequence_ids([None, 3]) == [2, 3]
    assert infer_sequence_ids([None, None, 1]) == [None, None, 1]  # would hit 0/neg


def test_infer_is_guide_agnostic_no_block_of_five_assumption():
    # Plain consecutive numbering (Wetterstein-style) fills naturally; the rule
    # never snaps to a multiple of five.
    assert infer_sequence_ids([41, None, 43]) == [41, 42, 43]


def test_infer_leaves_a_fully_recovered_sequence_untouched():
    assert infer_sequence_ids([10, 11, 12]) == [10, 11, 12]
