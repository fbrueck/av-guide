import json

from pipeline.merge import DanglingRef, UnresolvedPlace, assemble_entries, merge
from pipeline.records import PartEntry


def write_part(cfg, stem, entries):
    cfg.struct_parts.mkdir(parents=True, exist_ok=True)
    # Strip the test-only "_text" scaffolding so the part file looks real.
    wire = [{k: v for k, v in e.items() if k != "_text"} for e in entries]
    (cfg.struct_parts / f"{stem}.json").write_text(
        json.dumps({"entries": wire}, ensure_ascii=False), encoding="utf-8"
    )


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _anchored(base, name, text, fields):
    """Attach boundary anchors derived from the entry's body `text` (its first
    and last words), plus a `_text` scaffold so `assemble` can synthesize the
    page the slicer reads. Defaults `text` to the heading."""
    text = text if text is not None else name
    words = text.split()
    base["start_quote"] = " ".join(words[:4]) or None
    base["end_quote"] = " ".join(words[-4:]) or None
    base["_text"] = text
    return {**base, **fields}


def place(entry_id_raw, name, text=None, **fields):
    base = {
        "kind": "place",
        "entry_id_raw": entry_id_raw,
        "name": name,
        "summary": None,
        "place_type": None,
        "elevation": None,
    }
    return _anchored(base, name, text, fields)


def route(entry_id_raw, name, text=None, **fields):
    base = {
        "kind": "route",
        "entry_id_raw": entry_id_raw,
        "name": name,
        "peak": None,
        "grade": None,
        "first_ascent": None,
        "time": None,
        "height_m": None,
        "summary": None,
        "place_names": [],
    }
    return _anchored(base, name, text, fields)


def traverse(entry_id_raw, name, text=None, **fields):
    # A range-wide itinerary (Weitwanderweg / Rundtour / Übergang, ADR-0005):
    # route-shaped fields, but filed under no Place.
    base = {
        "kind": "traverse",
        "entry_id_raw": entry_id_raw,
        "name": name,
        "peak": None,
        "grade": None,
        "first_ascent": None,
        "time": None,
        "height_m": None,
        "summary": None,
        "place_names": [],
    }
    return _anchored(base, name, text, fields)


def assemble(pages):
    """Feed dict fixtures through the real parse+slice boundary, as merge does:
    synthesize each page's text from its entries' bodies, then assemble. Pure
    tests build wire dicts; the dict->PartEntry + description-slice step lives
    here."""
    parts = []
    page_texts = {}
    for page, entries in pages:
        page_texts[page] = "\n\n".join(e["_text"] for e in entries)
        parts.append((page, [PartEntry.from_dict(e) for e in entries]))
    return assemble_entries(parts, page_texts)


def test_part_entry_from_dict_defaults_and_kind_fields():
    # Absent fields fall back to defaults; place_names normalizes to [].
    r = PartEntry.from_dict({"kind": "route", "entry_id_raw": "56", "name": "X"})
    assert r.kind == "route"
    assert r.entry_id_raw == "56"
    assert r.start_quote is None
    assert r.place_names == []

    p = PartEntry.from_dict({"kind": "place", "name": "Haus", "elevation": "1652 m"})
    assert p.kind == "place"
    assert p.elevation == "1652 m"
    assert p.place_names == []


# --- assemble_entries (pure) --------------------------------------------------


def test_book_id_normalized_and_flagged():
    records, report = assemble(
        [(51, [place("•55", "Kreuzeckhaus"), route("•56 A", "Nordwestgrat")])]
    )
    assert [r.id for r in records] == ["R55", "R56A"]
    assert all(r.id_source == "book" for r in records)
    assert report.synthetic == 0


def test_synthetic_id_when_randziffer_unrecoverable():
    records, report = assemble([(51, [route(None, "Nameless")])])
    assert records[0].id == "p0051_01"
    assert records[0].id_source == "synthetic"
    assert report.synthetic == 1


def test_destination_is_structural_parent_place():
    # Place then two routes filed under it → both take the place as Destination.
    records, _ = assemble(
        [
            (
                51,
                [
                    place("•55", "Kreuzeckhaus"),
                    route("•56", "Von Hammersbach"),
                    route("•57", "Durch das Bodenlahntal"),
                ],
            )
        ]
    )
    routes = [r for r in records if r.kind == "route"]
    assert all(r.destination_id == "R55" for r in routes)
    assert all(r.place_ids == [] for r in routes)


def test_destination_carries_across_pages():
    records, _ = assemble(
        [(51, [place("•55", "Haus")]), (52, [route("•56", "Zustieg")])]
    )
    assert records[1].destination_id == "R55"


def test_orphan_route_has_null_destination_surfaced():
    records, report = assemble([(51, [route("•56", "Von Hammersbach")])])
    assert records[0].destination_id is None
    assert records[0].place_ids == []
    # The gap is surfaced in the merge report, never invented.
    assert report.missing_destination == ["R56"]


def test_traverse_has_null_destination_and_is_not_a_gap():
    # A Traverse is filed under no Place (ADR-0005): its Destination stays null
    # by definition and is NOT reported as a missing-Destination gap, even though
    # a Place precedes it in book order.
    records, report = assemble(
        [
            (
                46,
                [
                    place("•355", "Seewaldhütte"),
                    traverse("•361", "Klassische Karwendeldurchquerung"),
                ],
            )
        ]
    )
    t = next(r for r in records if r.kind == "traverse")
    assert t.destination_id is None
    assert report.missing_destination == []


def test_traverse_resolves_waypoint_place_ids_without_a_destination():
    # A Traverse still resolves the target Places it names into place_ids, but
    # takes none of them (nor the preceding Place) as a Destination.
    records, report = assemble(
        [
            (
                46,
                [
                    place("•251", "Karwendelhaus"),
                    place("•355", "Seewaldhütte"),
                    traverse("•361", "Durchquerung", place_names=["Karwendelhaus"]),
                ],
            )
        ]
    )
    t = next(r for r in records if r.kind == "traverse")
    assert t.destination_id is None
    assert t.place_ids == ["R251"]
    assert report.unresolved_places == []


def test_traverse_does_not_reset_the_running_destination():
    # A Traverse must not consume the running Place: a Route after it still takes
    # the last real Place as its Destination.
    records, report = assemble(
        [
            (
                46,
                [
                    place("•55", "Haus"),
                    traverse("•361", "Übergang"),
                    route("•56", "Zustieg"),
                ],
            )
        ]
    )
    r = next(r for r in records if r.kind == "route")
    assert r.destination_id == "R55"
    assert report.missing_destination == []


def test_traverse_place_resolved_by_name_disjoint_from_destination():
    records, report = assemble(
        [
            (
                51,
                [
                    place("•10", "Mittenwald"),
                    place("•55", "Kreuzeckhaus"),
                    route("•56", "Überschreitung", place_names=["Mittenwald"]),
                ],
            )
        ]
    )
    r = next(r for r in records if r.kind == "route")
    # Destination is the structural parent Kreuzeckhaus; the traverse target
    # Mittenwald lands in place_ids, disjoint from the Destination.
    assert r.destination_id == "R55"
    assert r.place_ids == ["R10"]
    assert report.unresolved_places == []


def test_traverse_place_naming_the_destination_is_not_duplicated():
    # A traverse whose prose names its own parent Place must not repeat it in
    # place_ids — the two target roles stay disjoint.
    records, _ = assemble(
        [
            (
                51,
                [
                    place("•55", "Kreuzeckhaus"),
                    route("•56", "Rundtour", place_names=["Kreuzeckhaus"]),
                ],
            )
        ]
    )
    r = next(r for r in records if r.kind == "route")
    assert r.destination_id == "R55"
    assert r.place_ids == []


def test_unresolved_traverse_place_surfaced_not_invented():
    records, report = assemble(
        [(51, [place("•55", "Haus"), route("•56", "Trav", place_names=["Nirgendwo"])])]
    )
    r = next(r for r in records if r.kind == "route")
    assert r.destination_id == "R55"
    assert r.place_ids == []  # nothing resolvable
    assert report.unresolved_places == [UnresolvedPlace(route="R56", name="Nirgendwo")]


def test_references_parsed_and_dangling_reported():
    records, report = assemble(
        [
            (
                51,
                [
                    place("•55", "Haus"),
                    route("•56", "R", text="Zustieg wie R 55, dann siehe R 999."),
                ],
            )
        ]
    )
    r = next(r for r in records if r.kind == "route")
    assert {ref.ref_id for ref in r.references} == {"R55", "R999"}
    # R55 exists; R999 does not → exactly one dangling ref surfaced.
    assert report.dangling_refs == [DanglingRef(from_id="R56", ref_id="R999")]


def test_book_id_collision_rekeyed_synthetic():
    records, report = assemble([(51, [route("•56", "First"), route("•56", "Dup")])])
    assert records[0].id == "R56"
    assert records[1].id == "p0051_02"  # collision → synthetic fallback
    assert records[1].id_source == "synthetic"
    assert report.id_collisions == ["R56"]
    # A collision is a recoverable-but-duplicate number, NOT an OCR-unrecoverable
    # one, so it must not inflate the synthetic (OCR-unrecoverable) count.
    assert report.synthetic == 0


# --- dropped-Randziffer recovery from the sequence (#86) -----------------------


def test_dropped_place_randziffer_inferred_from_sequence():
    # A hut heading whose Randziffer the OCR dropped (entry_id_raw=None) sits
    # between route 276 and route 281; the strictly-ascending sequence pins it to
    # R280 (next-1), even though the book skipped 277–279. No synthetic fallback.
    records, report = assemble(
        [
            (
                40,
                [
                    route("•276", "Abstieg"),
                    place(None, "Dammkarhütte"),
                    route("•281", "Von Mittenwald"),
                ],
            )
        ]
    )
    hut = next(r for r in records if r.kind == "place")
    assert hut.id == "R280"
    assert hut.id_source == "inferred"
    assert report.inferred == 1
    assert report.synthetic == 0


def test_inferred_hut_id_resolves_a_previously_dangling_reference():
    # The Aschauer-Alm case (#86): with the hut's Randziffer dropped it was keyed
    # synthetically, so a cross-ref to its book id dangled. Once the sequence keys
    # the hut R290, that reference resolves against a real Entry.
    records, report = assemble(
        [
            (
                41,
                [
                    route("•287", "Von der Fereinalm"),
                    place(None, "Aschauer Alm"),
                    route("•291", "Von Mittenwald"),
                    route(
                        "•296",
                        "Zustieg",
                        text="Von der Aschauer Alm wie R 290 hinauf zur Alm.",
                    ),
                ],
            )
        ]
    )
    hut = next(r for r in records if r.name == "Aschauer Alm")
    assert hut.id == "R290"
    assert hut.id_source == "inferred"
    assert report.dangling_refs == []  # R290 now exists, so the >290 ref resolves


def test_dropped_id_without_a_next_anchor_stays_synthetic():
    # Nothing to anchor on the right → the number is genuinely unrecoverable, so
    # the deterministic synthetic fallback stands (never invented).
    records, report = assemble(
        [(41, [route("•287", "Zustieg"), place(None, "Namenlose Alm")])]
    )
    hut = next(r for r in records if r.kind == "place")
    assert hut.id == "p0041_02"
    assert hut.id_source == "synthetic"
    assert report.synthetic == 1
    assert report.inferred == 0


def test_gap_that_cannot_stay_above_prev_stays_synthetic():
    # next-1 would be 280 = the previous id: filling it would break strict
    # ascension / collide, so the entry stays synthetic, not a duplicate.
    records, report = assemble(
        [(40, [route("•280", "A"), place(None, "Dup"), route("•281", "B")])]
    )
    dup = next(r for r in records if r.name == "Dup")
    assert dup.id_source == "synthetic"
    assert report.inferred == 0


def test_inferred_id_never_steals_a_number_recovered_elsewhere():
    # A garbled ordering where the gap would infer 287, but 287 is a real
    # recovered entry: keep the synthetic fallback rather than double-key it.
    records, _ = assemble(
        [
            (
                40,
                [
                    route("•285", "A"),
                    place(None, "Ghost"),
                    route("•288", "B"),
                    route("•287", "C"),
                ],
            )
        ]
    )
    ghost = next(r for r in records if r.name == "Ghost")
    assert ghost.id_source == "synthetic"
    assert "R287" in {r.id for r in records}  # the real 287 keeps its number


# --- merge (filesystem) -------------------------------------------------------


def test_merge_writes_entry_files_and_index(cfg):
    write_part(cfg, "page_0051", [place("•55", "Haus"), route("•56", "Zustieg")])
    write_part(cfg, "page_0052", [route("•57", "Weiterweg")])

    merge(cfg)

    entries = load_jsonl(cfg.routes_jsonl)
    assert [e["id"] for e in entries] == ["R55", "R56", "R57"]
    assert entries[0]["kind"] == "place"
    assert entries[0]["source_page"] == 51

    # One self-contained file per entry, keyed by entry id; no internal keys.
    haus = json.loads((cfg.entries_dir / "R55.json").read_text(encoding="utf-8"))
    assert haus["name"] == "Haus"
    assert not any(k.startswith("_") for k in haus)

    # route-map contract emitted in sync, without internal bookkeeping.
    contract = json.loads(cfg.routes_json.read_text(encoding="utf-8"))
    assert [e["id"] for e in contract] == ["R55", "R56", "R57"]
    assert "source_page" not in contract[0]


def test_merge_rebuilds_from_scratch(cfg):
    write_part(cfg, "page_0051", [route("•56", "A")])
    merge(cfg)
    (cfg.entries_dir / "STALE.json").write_text("{}", encoding="utf-8")

    write_part(cfg, "page_0051", [route("•56", "Renamed")])
    merge(cfg)

    assert not (cfg.entries_dir / "STALE.json").exists()
    entries = load_jsonl(cfg.routes_jsonl)
    assert [e["name"] for e in entries] == ["Renamed"]


def write_clean_page(cfg, stem, text):
    cfg.clean_pages.mkdir(parents=True, exist_ok=True)
    (cfg.clean_pages / f"{stem}.txt").write_text(text, encoding="utf-8")


def test_merge_slices_verbatim_description_from_the_cleaned_page(cfg):
    # An entry that spills across the page break: the footer "61" is dropped, the
    # "De-\nzember" hyphenation rejoined, wrapping reflowed — description is sliced
    # deterministically, not carried on the part file.
    write_clean_page(
        cfg,
        "page_0051",
        "55\nKreuzeckhaus, 1652 m\nGroße Hütte hoch über dem Tal, siehe R 40. "
        "Bewirtschaftet De-\n61",
    )
    write_clean_page(cfg, "page_0052", "zember bis April. Toll.\n62")
    write_part(
        cfg,
        "page_0051",
        [
            place(
                "•55",
                "Kreuzeckhaus",
                start_quote="Kreuzeckhaus, 1652 m",
                end_quote="April. Toll.",
            )
        ],
    )

    merge(cfg)

    entries = load_jsonl(cfg.routes_jsonl)
    assert entries[0]["description"] == (
        "Kreuzeckhaus, 1652 m Große Hütte hoch über dem Tal, siehe R 40. "
        "Bewirtschaftet Dezember bis April. Toll."
    )
    # References are still parsed from the sliced description.
    assert entries[0]["references"] == [{"ref_id": "R40", "surface": "R 40"}]


def test_merge_reports_entry_whose_anchors_are_not_found(cfg):
    write_clean_page(cfg, "page_0051", "55\nKreuzeckhaus, 1652 m\nEin Text.")
    write_part(
        cfg,
        "page_0051",
        [place("•55", "Kreuzeckhaus", start_quote="Nicht", end_quote="vorhanden")],
    )

    merge(cfg)

    entries = load_jsonl(cfg.routes_jsonl)
    # No silently wrong slice — description is null and the entry is still written.
    assert entries[0]["id"] == "R55"
    assert entries[0]["description"] is None


def test_merge_writes_unsliced_report_with_reason_buckets(cfg):
    # Two entries fail to slice for different reasons; the report identifies each
    # (id/source_page/name/kind) and tags its reason bucket (#110).
    write_clean_page(cfg, "page_0051", "55\nKreuzeckhaus, 1652 m\nEin kurzer Text.")
    write_part(
        cfg,
        "page_0051",
        [
            # Start anchor is absent from the page → start_not_found.
            place(
                "•55", "Kreuzeckhaus", start_quote="Gibt es nicht", end_quote="Text."
            ),
            # A missing end anchor → empty_anchor.
            route("•56", "Weg", start_quote="Ein kurzer", end_quote=None),
        ],
    )

    merge(cfg)

    report = load_jsonl(cfg.unsliced_report)
    by_id = {r["id"]: r for r in report}
    assert by_id["R55"]["reason"] == "start_not_found"
    assert by_id["R55"]["kind"] == "place"
    assert by_id["R55"]["name"] == "Kreuzeckhaus"
    assert by_id["R55"]["source_page"] == 51
    assert by_id["R56"]["reason"] == "empty_anchor"
    # Every reason is a known bucket, one per record; the total matches the count
    # of entries that ended up with a null description.
    assert all(
        r["reason"]
        in {
            "empty_anchor",
            "stub",
            "start_not_found",
            "start_ambiguous",
            "end_mismatch",
        }
        for r in report
    )
    entries = load_jsonl(cfg.routes_jsonl)
    assert len(report) == sum(1 for e in entries if e["description"] is None)


def test_merge_writes_empty_unsliced_report_when_everything_slices(cfg):
    # Absent/empty-safe: the artifact is rebuilt every run, empty when nothing is
    # unsliced (no stale records carried over).
    write_clean_page(cfg, "page_0051", "55\nKreuzeckhaus, 1652 m\nGanzer Text hier.")
    write_part(
        cfg,
        "page_0051",
        [
            place(
                "•55",
                "Kreuzeckhaus",
                start_quote="Kreuzeckhaus, 1652 m",
                end_quote="Ganzer Text hier.",
            )
        ],
    )

    merge(cfg)

    assert cfg.unsliced_report.exists()
    assert load_jsonl(cfg.unsliced_report) == []


def test_merge_description_source_provenance_sliced_stub_none(cfg):
    # Three entries exercising each provenance value (#114): one slices verbatim,
    # one is a body-less stub (start == end), one cannot be located at all.
    write_clean_page(
        cfg,
        "page_0051",
        "55\nKreuzeckhaus, 1652 m\nGroße Hütte, ganzer Text.\n"
        "56\nDurch das Große Ödkar, I\nWie R 55, weiter rechts.\n"
        "57\nZustieg\nEin dritter Text.",
    )
    write_part(
        cfg,
        "page_0051",
        [
            # Sliceable → "sliced".
            place(
                "•55",
                "Kreuzeckhaus",
                start_quote="Kreuzeckhaus, 1652 m",
                end_quote="ganzer Text.",
            ),
            # Body-less stub: start == end → "stub", keeps its one-line heading.
            route(
                "•56",
                "Durch das Große Ödkar",
                start_quote="Durch das Große Ödkar, I",
                end_quote="Durch das Große Ödkar, I",
            ),
            # Anchors not on the page → null description, "none".
            route("•57", "Zustieg", start_quote="Gibt", end_quote="es nicht"),
        ],
    )

    merge(cfg)

    entries = {e["id"]: e for e in load_jsonl(cfg.routes_jsonl)}
    assert entries["R55"]["description_source"] == "sliced"
    assert entries["R55"]["description"].startswith("Kreuzeckhaus, 1652 m")

    assert entries["R56"]["description_source"] == "stub"
    assert entries["R56"]["description"] == "Durch das Große Ödkar, I"

    assert entries["R57"]["description_source"] == "none"
    assert entries["R57"]["description"] is None

    # The stub and the unlocatable entry are both surfaced in the unsliced report,
    # tagged with their buckets; the sliced one is not.
    report = {r["id"]: r["reason"] for r in load_jsonl(cfg.unsliced_report)}
    assert report == {"R56": "stub", "R57": "start_not_found"}

    # The provenance field is part of the route-map contract too.
    contract = {e["id"]: e for e in json.loads(cfg.routes_json.read_text("utf-8"))}
    assert contract["R56"]["description_source"] == "stub"
