import json

from pipeline.merge import DanglingRef, UnresolvedPlace, assemble_entries, merge


def write_part(cfg, stem, entries):
    cfg.struct_parts.mkdir(parents=True, exist_ok=True)
    (cfg.struct_parts / f"{stem}.json").write_text(
        json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8"
    )


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def place(entry_id_raw, name, **fields):
    base = {
        "kind": "place",
        "entry_id_raw": entry_id_raw,
        "name": name,
        "description": name,
        "summary": None,
        "place_type": None,
        "elevation": None,
    }
    return {**base, **fields}


def route(entry_id_raw, name, **fields):
    base = {
        "kind": "route",
        "entry_id_raw": entry_id_raw,
        "name": name,
        "peak": None,
        "grade": None,
        "first_ascent": None,
        "time": None,
        "height_m": None,
        "description": name,
        "summary": None,
        "place_names": [],
    }
    return {**base, **fields}


# --- assemble_entries (pure) --------------------------------------------------


def test_book_id_normalized_and_flagged():
    records, report = assemble_entries(
        [(51, [place("•55", "Kreuzeckhaus"), route("•56 A", "Nordwestgrat")])]
    )
    assert [r.id for r in records] == ["R55", "R56A"]
    assert all(r.id_source == "book" for r in records)
    assert report.synthetic == 0


def test_synthetic_id_when_randziffer_unrecoverable():
    records, report = assemble_entries([(51, [route(None, "Nameless")])])
    assert records[0].id == "p0051_01"
    assert records[0].id_source == "synthetic"
    assert report.synthetic == 1


def test_destination_is_structural_parent_place():
    # Place then two routes filed under it → both take the place as Destination.
    records, _ = assemble_entries(
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
    records, _ = assemble_entries(
        [(51, [place("•55", "Haus")]), (52, [route("•56", "Zustieg")])]
    )
    assert records[1].destination_id == "R55"


def test_orphan_route_has_null_destination_surfaced():
    records, report = assemble_entries([(51, [route("•56", "Von Hammersbach")])])
    assert records[0].destination_id is None
    assert records[0].place_ids == []
    # The gap is surfaced in the merge report, never invented.
    assert report.missing_destination == ["R56"]


def test_traverse_place_resolved_by_name_disjoint_from_destination():
    records, report = assemble_entries(
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
    records, _ = assemble_entries(
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
    records, report = assemble_entries(
        [(51, [place("•55", "Haus"), route("•56", "Trav", place_names=["Nirgendwo"])])]
    )
    r = next(r for r in records if r.kind == "route")
    assert r.destination_id == "R55"
    assert r.place_ids == []  # nothing resolvable
    assert report.unresolved_places == [UnresolvedPlace(route="R56", name="Nirgendwo")]


def test_references_parsed_and_dangling_reported():
    records, report = assemble_entries(
        [
            (
                51,
                [
                    place("•55", "Haus"),
                    route(
                        "•56", "R", description="Zustieg wie R 55, dann siehe R 999."
                    ),
                ],
            )
        ]
    )
    r = next(r for r in records if r.kind == "route")
    assert {ref.ref_id for ref in r.references} == {"R55", "R999"}
    # R55 exists; R999 does not → exactly one dangling ref surfaced.
    assert report.dangling_refs == [DanglingRef(from_id="R56", ref_id="R999")]


def test_book_id_collision_rekeyed_synthetic():
    records, report = assemble_entries(
        [(51, [route("•56", "First"), route("•56", "Dup")])]
    )
    assert records[0].id == "R56"
    assert records[1].id == "p0051_02"  # collision → synthetic fallback
    assert records[1].id_source == "synthetic"
    assert report.id_collisions == ["R56"]
    # A collision is a recoverable-but-duplicate number, NOT an OCR-unrecoverable
    # one, so it must not inflate the synthetic (OCR-unrecoverable) count.
    assert report.synthetic == 0


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
