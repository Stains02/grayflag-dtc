from grayflag_dtc.core.dataset import parse_dataset


def _ds():
    def obj(lane, seq, name, cps):
        return {"id": f"OBJ{lane}{seq}", "lane": lane, "seq": seq, "name": name, "placeholder": name.endswith(" Objective"),
                "center": {"lat": 25, "lon": 55}, "cps": cps}
    cp = lambda i, n: {"id": f"CAP-{i}", "name": n, "lat": 25, "lon": 55, "elev_m": 1, "dcs": {"x": i, "y": 0}}
    return parse_dataset({"server_id": "t", "server_name": "T", "theater": "Syria", "lanes": ["A", "B"], "objectives": [
        obj("A", 1, "Alpha Objective", [cp(1, "capture point")]), obj("A", 16, "Lar", [cp(2, "Lar Airport")]),
        obj("B", 5, "Some Plains", [cp(3, "Hut")])]}, tag="T")


def test_labels_are_two_digit_and_resolve_accepts_padded_or_plain():
    ds = _ds()
    assert [o.label for o in ds.objectives] == ["A01", "A16", "B05"]
    for tok in ("A1", "a1", "A01", "OBJA1", "obja01"):
        assert ds.resolve(tok).code == "A1", tok
    assert ds.resolve("B05").code == "B5" and ds.resolve("A016").code == "A16"
    import pytest
    with pytest.raises(KeyError):
        ds.resolve("A2")


def test_shipped_datasets_match_the_published_schema():
    import json
    from pathlib import Path

    import jsonschema
    root = Path(__file__).resolve().parent.parent
    schema = json.loads((root / "schema" / "dataset.schema.json").read_text(encoding="utf-8"))
    files = sorted((root / "data" / "theaters").glob("*.json"))
    assert files
    for f in files:
        jsonschema.validate(json.loads(f.read_text(encoding="utf-8")), schema)
