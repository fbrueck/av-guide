import pytest

from pipeline.ids import normalize_entry_id, synthetic_id


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
