import json

from pipeline.merge import merge


def write_part(cfg, stem, routes):
    cfg.struct_parts.mkdir(parents=True, exist_ok=True)
    (cfg.struct_parts / f"{stem}.json").write_text(
        json.dumps({"routes": routes}, ensure_ascii=False), encoding="utf-8"
    )


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def route(name, **fields):
    base = {
        "name": name,
        "peak": None,
        "grade": None,
        "first_ascent": None,
        "time": None,
        "height_m": None,
        "description": name,
        "summary": None,
    }
    return {**base, **fields}


def test_merge_explodes_parts_into_routes_and_index(cfg):
    write_part(cfg, "page_0051", [route("Route A", peak="Zugspitze"), route("Route B")])
    write_part(cfg, "page_0052", [route("Route C")])

    merge(cfg)

    # route_id = p<page>_<seq>, source_page filled in, index sorted.
    routes = load_jsonl(cfg.routes_jsonl)
    assert [r["route_id"] for r in routes] == ["p0051_01", "p0051_02", "p0052_01"]
    assert routes[0]["source_page"] == 51
    assert routes[0]["peak"] == "Zugspitze"

    # One self-contained file per route under routes/.
    a = json.loads((cfg.routes_dir / "p0051_01.json").read_text(encoding="utf-8"))
    assert a["name"] == "Route A"

    # merge also emits the route-map contract (routes.json) in sync: a JSON
    # array of the same routes, without internal fields like source_page.
    contract = json.loads(cfg.routes_json.read_text(encoding="utf-8"))
    assert [r["route_id"] for r in contract] == ["p0051_01", "p0051_02", "p0052_01"]
    assert "source_page" not in contract[0]


def test_merge_rebuilds_from_scratch(cfg):
    write_part(cfg, "page_0051", [route("Route A")])
    merge(cfg)
    # A stale route file from a previous run must not survive a re-merge.
    (cfg.routes_dir / "p9999_99.json").write_text("{}", encoding="utf-8")

    write_part(cfg, "page_0051", [route("Renamed")])
    merge(cfg)

    assert not (cfg.routes_dir / "p9999_99.json").exists()
    routes = load_jsonl(cfg.routes_jsonl)
    assert [r["name"] for r in routes] == ["Renamed"]
