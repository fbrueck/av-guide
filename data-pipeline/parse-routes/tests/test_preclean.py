import json

from pipeline.preclean import dehyphenate, preclean
from pipeline.records import PageMeta


def test_soft_hyphen_across_line_break_is_rejoined():
    # The canonical case: a lowercase word split by a hyphen at a line break.
    assert dehyphenate("Verschnei-\ndung") == "Verschneidung"
    assert dehyphenate("Häufig be-\ngangen") == "Häufig begangen"


def test_join_tolerates_leading_whitespace_on_continuation():
    assert dehyphenate("Verschnei-\n  dung") == "Verschneidung"


def test_multiple_soft_hyphens_in_one_text():
    text = "sonst meist leich-\nter und be-\ngangen"
    assert dehyphenate(text) == "sonst meist leichter und begangen"


def test_umlaut_and_eszett_boundaries_join():
    assert dehyphenate("Fuß-\nweg") == "Fußweg"
    assert dehyphenate("Wän-\nde") == "Wände"


def test_uppercase_before_hyphen_is_a_compound_and_is_kept():
    # `NW-Grat`, `S-Seite` etc. are genuine compounds — never fuse across the
    # hyphen; the newline stays so structure is preserved (a later LLM/reflow
    # step may still merge the line, but the deterministic pass must not corrupt).
    assert dehyphenate("NW-\nGrat") == "NW-\nGrat"
    assert dehyphenate("S-\nSeite") == "S-\nSeite"


def test_capitalised_continuation_is_kept():
    # A capitalised second part signals a real compound part, not a wrapped word.
    assert dehyphenate("alpin-\nTechnik") == "alpin-\nTechnik"


def test_grades_and_roman_numerals_are_untouched():
    # Climbing grades carry `-`/`+` and roman numerals; none match the
    # lowercase-hyphen-newline-lowercase rule, so they survive verbatim.
    assert dehyphenate("(VI-)\nAufschwung") == "(VI-)\nAufschwung"
    assert dehyphenate("III— (zwei Stellen)") == "III— (zwei Stellen)"
    assert dehyphenate("V+, A0") == "V+, A0"


def test_entry_ids_and_reference_sigils_are_untouched():
    assert dehyphenate("• 337 Nordwestgrat") == "• 337 Nordwestgrat"
    assert (
        dehyphenate("Zugang wie R 335 auf den Grat.")
        == "Zugang wie R 335 auf den Grat."
    )
    assert dehyphenate("(R 243)") == "(R 243)"


def test_mid_line_hyphen_and_em_dash_are_untouched():
    assert dehyphenate("Wiener-Neustädter Hütte") == "Wiener-Neustädter Hütte"
    assert dehyphenate("5—6 Std.") == "5—6 Std."
    assert dehyphenate("die S-Seite desselben") == "die S-Seite desselben"


def test_trailing_hyphen_at_end_of_text_is_kept():
    # No continuation line → nothing to join, leave the hyphen as printed.
    assert dehyphenate("Origi-") == "Origi-"
    assert dehyphenate("Origi-\n") == "Origi-\n"


def test_blank_line_after_hyphen_is_not_joined():
    # A paragraph break (blank line) is a real structural break, not a word wrap.
    assert dehyphenate("Origi-\n\ndung") == "Origi-\n\ndung"


def test_no_hyphen_text_is_returned_unchanged():
    assert dehyphenate("Über den Grat zum Gipfel.") == "Über den Grat zum Gipfel."
    assert dehyphenate("") == ""


def _write_page(cfg, stem, text):
    cfg.raw_pages.mkdir(parents=True, exist_ok=True)
    (cfg.raw_pages / f"{stem}.txt").write_text(text, encoding="utf-8")


def _write_manifest(cfg, metas):
    cfg.manifest.parent.mkdir(parents=True, exist_ok=True)
    with cfg.manifest.open("w", encoding="utf-8") as f:
        for m in metas:
            f.write(json.dumps(m.to_dict()) + "\n")


def _meta(stem, *, is_sketch=False):
    return PageMeta(
        page=int(stem.split("_")[1]),
        stem=stem,
        char_count=0 if is_sketch else 400,
        rotation=0,
        n_images=0,
        largest_image=None,
        is_sketch=is_sketch,
    )


def test_preclean_writes_dehyphenated_pages_and_skips_sketches(cfg):
    _write_page(cfg, "page_0001", "Häufig be-\ngangen.")
    _write_page(cfg, "page_0002", "just a sketch")  # sketch: no text to repair
    _write_manifest(cfg, [_meta("page_0001"), _meta("page_0002", is_sketch=True)])

    done = preclean(cfg)

    assert done == ["page_0001"]
    assert (cfg.clean_prepared / "page_0001.txt").read_text() == "Häufig begangen."
    assert not (cfg.clean_prepared / "page_0002.txt").exists()


def test_preclean_is_resumable_and_skips_already_prepared_pages(cfg):
    _write_page(cfg, "page_0001", "be-\ngangen")
    _write_manifest(cfg, [_meta("page_0001")])

    assert preclean(cfg) == ["page_0001"]
    # A second run finds the page already prepared and does no work.
    assert preclean(cfg) == []
