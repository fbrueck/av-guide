from pipeline.references import Reference, parse_references


def ids(text):
    return [r.ref_id for r in parse_references(text)]


def test_single_ref_forms():
    assert ids("Zustieg wie R 43.") == ["R43"]
    assert ids("siehe R 243") == ["R243"]
    assert ids("(R 243)") == ["R243"]


def test_surface_is_the_verbatim_r_span():
    refs = parse_references("Abstieg (R 243) nach Osten.")
    assert refs == [Reference(ref_id="R243", surface="R 243")]


def test_shared_r_list_comma_expands_under_one_surface():
    # One R heads several ids; later ids are bare. Each id becomes a ref,
    # all sharing the verbatim surface.
    refs = parse_references("Wie R 43, 243 zum Gipfel.")
    assert refs == [
        Reference(ref_id="R43", surface="R 43, 243"),
        Reference(ref_id="R243", surface="R 43, 243"),
    ]


def test_shared_r_list_und_expands():
    assert ids("R 43 und 45") == ["R43", "R45"]


def test_letter_suffixes_in_refs():
    assert ids("Wie R 1096 b") == ["R1096B"]
    assert ids("vgl. R1096d") == ["R1096D"]


def test_anaphora_surfaced_with_null_ref_id():
    refs = parse_references("Weiter wie dort.")
    assert refs == [Reference(ref_id=None, surface="Weiter wie dort")]
    assert parse_references("Abstieg wie dort zurück.") == [
        Reference(ref_id=None, surface="wie dort")
    ]


def test_wie_r_is_not_mistaken_for_anaphora():
    # "Wie R 43" is a real ref, not the "wie dort" anaphora.
    assert ids("Wie R 43") == ["R43"]


def test_multiple_refs_in_order_deduped_by_pair():
    text = "Zunächst wie R 43, später siehe R 243, am Ende wieder R 43."
    refs = parse_references(text)
    # R43 appears twice with the same surface → one entry; order preserved.
    assert refs == [
        Reference(ref_id="R43", surface="R 43"),
        Reference(ref_id="R243", surface="R 243"),
    ]


def test_no_refs():
    assert parse_references("Über den Grat zum Gipfel.") == []
    assert parse_references("") == []


# --- Klier/Karwendel Randzahl-arrow sigil (#84) -----------------------------
# The Karwendel book (Klier/Walter) reprints a cross-reference with the Randzahl
# arrow `➤` — OCR'd as `>`, often trailed by the arrow's shaft `-` — where the
# Beulke/Wetterstein book uses the `R` sigil. Both must parse to the same key.


def test_arrow_sigil_single_ref():
    assert ids(">273") == ["R273"]
    assert ids("auf >273 umgek.") == ["R273"]


def test_arrow_sigil_with_shaft_dash():
    # The arrow OCRs as `>-`; the dash is part of the sigil, not the id.
    assert ids(">-273") == ["R273"]
    assert ids(">-2775") == ["R2775"]


def test_arrow_sigil_parenthesised():
    assert ids("(>446)") == ["R446"]
    assert ids("(>325)") == ["R325"]


def test_arrow_sigil_verbatim_page_prose():
    # Verbatim span from the Karwendel Dammkarhütte access description.
    text = "Zugang von Mittenwald, 1½ Std., >-273 (Karwendelsteig)."
    assert parse_references(text) == [Reference(ref_id="R273", surface=">-273")]


def test_arrow_and_r_sigils_coexist():
    # A page may carry both forms; each resolves to the canonical key.
    assert ids("Wie R 43, später >-273") == ["R43", "R273"]


def test_bare_arrow_comparison_is_not_a_reference():
    # The arrow sigil requires the id to abut it; a spaced `>` comparison
    # (e.g. an elevation/height note) must not be read as a reference (#84).
    assert ids("Anstieg bis > 2000 m Höhe") == []
    assert ids("mehr als > 40 Kehren") == []
