from pipeline.references import parse_references


def ids(text):
    return [r["ref_id"] for r in parse_references(text)]


def test_single_ref_forms():
    assert ids("Zustieg wie R 43.") == ["R43"]
    assert ids("siehe R 243") == ["R243"]
    assert ids("(R 243)") == ["R243"]


def test_surface_is_the_verbatim_r_span():
    refs = parse_references("Abstieg (R 243) nach Osten.")
    assert refs == [{"ref_id": "R243", "surface": "R 243"}]


def test_shared_r_list_comma_expands_under_one_surface():
    # One R heads several ids; later ids are bare. Each id becomes a ref,
    # all sharing the verbatim surface.
    refs = parse_references("Wie R 43, 243 zum Gipfel.")
    assert refs == [
        {"ref_id": "R43", "surface": "R 43, 243"},
        {"ref_id": "R243", "surface": "R 43, 243"},
    ]


def test_shared_r_list_und_expands():
    assert ids("R 43 und 45") == ["R43", "R45"]


def test_letter_suffixes_in_refs():
    assert ids("Wie R 1096 b") == ["R1096B"]
    assert ids("vgl. R1096d") == ["R1096D"]


def test_anaphora_surfaced_with_null_ref_id():
    refs = parse_references("Weiter wie dort.")
    assert refs == [{"ref_id": None, "surface": "Weiter wie dort"}]
    assert parse_references("Abstieg wie dort zurück.") == [
        {"ref_id": None, "surface": "wie dort"}
    ]


def test_wie_r_is_not_mistaken_for_anaphora():
    # "Wie R 43" is a real ref, not the "wie dort" anaphora.
    assert ids("Wie R 43") == ["R43"]


def test_multiple_refs_in_order_deduped_by_pair():
    text = "Zunächst wie R 43, später siehe R 243, am Ende wieder R 43."
    refs = parse_references(text)
    # R43 appears twice with the same surface → one entry; order preserved.
    assert refs == [
        {"ref_id": "R43", "surface": "R 43"},
        {"ref_id": "R243", "surface": "R 243"},
    ]


def test_no_refs():
    assert parse_references("Über den Grat zum Gipfel.") == []
    assert parse_references("") == []
