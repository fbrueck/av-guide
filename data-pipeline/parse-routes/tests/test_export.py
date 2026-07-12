import json

from pipeline.export import CONTRACT_FIELDS, project_route, write_routes_json


def full_record(**overrides):
    """A route record as merge produces it — contract fields plus internals."""
    base = {
        "route_id": "p0051_01",
        "source_page": 51,  # internal bookkeeping, not part of the contract
        "name": "Route A",
        "peak": "Zugspitze",
        "grade": "II",
        "time": "3 Std.",
        "height_m": "800 mH",
        "first_ascent": None,
        "summary": "Kurzfassung.",
        "description": "Volltext.",
    }
    return {**base, **overrides}


def test_project_route_keeps_only_contract_fields():
    projected = project_route(full_record())
    assert set(projected) == set(CONTRACT_FIELDS)
    # Internal fields are dropped from the contract.
    assert "source_page" not in projected
    assert projected["route_id"] == "p0051_01"
    assert projected["peak"] == "Zugspitze"


def test_project_route_fills_missing_fields_with_none():
    # A record lacking several contract fields still yields the uniform shape.
    projected = project_route({"route_id": "p0001_01", "name": "Sparse"})
    assert set(projected) == set(CONTRACT_FIELDS)
    assert projected["grade"] is None
    assert projected["description"] is None


def test_write_routes_json_reads_jsonl_and_emits_array(cfg):
    cfg.struct_dir.mkdir(parents=True, exist_ok=True)
    records = [full_record(route_id="p0051_01"), full_record(route_id="p0052_01")]
    with cfg.routes_jsonl.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = write_routes_json(cfg)

    assert n == 2
    data = json.loads(cfg.routes_json.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert [r["route_id"] for r in data] == ["p0051_01", "p0052_01"]
    assert all(set(r) == set(CONTRACT_FIELDS) for r in data)


def test_write_routes_json_prefers_passed_records_over_file(cfg):
    # merge passes its in-memory list; no routes.jsonl needed in that path.
    cfg.struct_dir.mkdir(parents=True, exist_ok=True)
    n = write_routes_json(cfg, [full_record()])
    assert n == 1
    assert not cfg.routes_jsonl.exists()
    assert (
        json.loads(cfg.routes_json.read_text(encoding="utf-8"))[0]["name"] == "Route A"
    )
