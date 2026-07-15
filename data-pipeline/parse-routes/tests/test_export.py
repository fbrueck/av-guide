import json

from pipeline.export import CONTRACT_FIELDS, project_entry, write_routes_json
from pipeline.records import Entry


def route_record(**overrides):
    """A Route Entry record as merge produces it — contract fields plus internals."""
    base = {
        "id": "R56",
        "id_source": "book",  # internal, not part of the contract
        "kind": "route",
        "source_page": 51,  # internal bookkeeping, not part of the contract
        "name": "Von Hammersbach",
        "peak": "Zugspitze",
        "grade": "II",
        "time": "3 Std.",
        "height_m": "800 mH",
        "first_ascent": None,
        "destination_id": "R55",
        "place_ids": [],
        "references": [{"ref_id": "R43", "surface": "R 43"}],
        "summary": "Kurzfassung.",
        "description": "Volltext.",
    }
    return {**base, **overrides}


def test_project_entry_keeps_only_contract_fields():
    projected = project_entry(Entry.from_dict(route_record()))
    assert set(projected) == set(CONTRACT_FIELDS)
    # Internal fields are dropped from the contract.
    assert "source_page" not in projected
    assert "id_source" not in projected
    assert projected["id"] == "R56"
    assert projected["kind"] == "route"
    assert projected["destination_id"] == "R55"
    assert projected["place_ids"] == []


def test_project_entry_places_carry_place_fields():
    place = {
        "id": "R55",
        "kind": "place",
        "name": "Kreuzeckhaus",
        "place_type": "hut",
        "elevation": "1652 m",
        "description": "Übersicht…",
    }
    projected = project_entry(Entry.from_dict(place))
    assert projected["place_type"] == "hut"
    assert projected["elevation"] == "1652 m"
    # A Place leaves the Route-only fields null but keeps the uniform shape.
    assert projected["grade"] is None
    assert set(projected) == set(CONTRACT_FIELDS)


def test_project_entry_link_fields_default_to_empty_list():
    # An Entry lacking place_ids/references still yields [] (never null), so a
    # consumer can iterate without a null check; the nullable scalar
    # destination_id defaults to None.
    projected = project_entry(
        Entry.from_dict({"id": "R1", "kind": "route", "name": "Sparse"})
    )
    assert projected["place_ids"] == []
    assert projected["references"] == []
    assert projected["destination_id"] is None
    assert projected["description"] is None
    assert set(projected) == set(CONTRACT_FIELDS)


def test_write_routes_json_reads_jsonl_and_emits_array(cfg):
    cfg.struct_dir.mkdir(parents=True, exist_ok=True)
    records = [route_record(id="R56"), route_record(id="R57")]
    with cfg.routes_jsonl.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = write_routes_json(cfg)

    assert n == 2
    data = json.loads(cfg.routes_json.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert [r["id"] for r in data] == ["R56", "R57"]
    assert all(set(r) == set(CONTRACT_FIELDS) for r in data)


def test_write_routes_json_prefers_passed_records_over_file(cfg):
    # merge passes its in-memory list; no routes.jsonl needed in that path.
    cfg.struct_dir.mkdir(parents=True, exist_ok=True)
    n = write_routes_json(cfg, [Entry.from_dict(route_record())])
    assert n == 1
    assert not cfg.routes_jsonl.exists()
    assert (
        json.loads(cfg.routes_json.read_text(encoding="utf-8"))[0]["name"]
        == "Von Hammersbach"
    )
