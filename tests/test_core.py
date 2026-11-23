import json
from pathlib import Path

import pytest

from grayflag_dtc.core import codes as C
from grayflag_dtc.core.dataset import CP, Dataset, Objective, parse_dataset
from grayflag_dtc.core.selection import CapacityError, build_selection, distance_m, order_cps

CFG = C.CodeConfig(words={"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "NORTHEAST": "NE",
                          "SOUTHEAST": "SE", "CENTRAL": "C"}, generic_names={"capture point"})


def code(name):
    base, _, _ = C.compose(name, CFG)
    return base


@pytest.mark.parametrize("name,expected", [
    ("Crossroads", "CRS"), ("Compound", "CMP"), ("Southeast", "SE"), ("North Village", "NVL"),
    ("Hill Town", "HTW"), ("East Shore", "ESH"), ("Airport Industrial Park", "AIP"),
    ("West Village", "WVL"), ("Oasis", "OSS"), ("Hidden Valley Indy", "HVI"),
])
def test_design_examples(name, expected):
    assert code(name) == expected


def test_objective_prefix():
    assert C.objective_prefix("Lar") == "LR"
    assert C.objective_prefix("Bandar Lengeh") == "BL"
    assert C.objective_prefix("Alpha Objective") == "AO"


def mk_obj(name, cp_names, oid="OBJA1"):
    cps = [CP(id=f"CAP-{i}", name=n, lat=27 + i * 1e-4, lon=54, elev_m=0, x=0, y=0) for i, n in enumerate(cp_names)]
    return Objective(id=oid, lane="A", seq=1, name=name, placeholder=False, lat=27, lon=54, cps=cps)


def test_generic_names_get_prefix_and_index():
    r = C.generate_objective_codes(mk_obj("Lar", ["capture point", "Crossroads", "capture point", ""]), CFG)
    assert [r[f"CAP-{i}"].code for i in range(4)] == ["LR1", "CRS", "LR2", "LR3"]
    assert r["CAP-0"].rule == "generic" and r["CAP-1"].rule == "one-word"


def test_per_objective_collisions_are_deterministic_and_unique():
    obj = mk_obj("Lar", ["Southeast", "Southeast", "Southeast", "North Village", "North Village"])
    a = C.generate_objective_codes(obj, CFG)
    b = C.generate_objective_codes(obj, CFG)
    got = [a[f"CAP-{i}"].code for i in range(5)]
    assert got == [b[f"CAP-{i}"].code for i in range(5)]
    assert len(set(got)) == 5
    assert got[0] == "SE" and got[1] == "SE2" and got[3] == "NVL"
    assert got[4] != "NVL" and a["CAP-4"].note.startswith("was NVL")


def test_override_wins_and_reserves_its_code():
    obj = mk_obj("Lar", ["North Village", "North Village"])
    r = C.generate_objective_codes(obj, CFG, {"CAP-1": "nvl"})
    assert r["CAP-1"].code == "NVL" and r["CAP-1"].rule == "override"
    assert r["CAP-0"].code != "NVL"


def test_letter_fallback_setting():
    cfg = C.CodeConfig(words={}, digit_fallback=False)
    assert next(C._suffix_variants("NVL", cfg)) == "NVA"
    assert next(C._suffix_variants("NVL", C.CodeConfig(words={}, digit_fallback=True))) == "NV2"


def test_codes_only_use_az09_and_fit_length():
    names = ["St. John's Hill", "Al-Qaim", "Ft. Bragg 2", "Point #4", "X", "Ãd Dîn"]
    for n in names:
        b = code(n)
        assert 1 <= len(b) <= 3 and b.isalnum() and b.isascii() or n == "Ãd Dîn"


# ---- selection
def ds_two():
    def cp(i, lat, lon, name="n"):
        return {"id": f"CAP-{i}", "name": name, "lat": lat, "lon": lon, "elev_m": 10, "radius_m": 1,
                "shape": "circle", "dcs": {"x": i, "y": i}}
    raw = {"server_id": "t", "server_name": "T", "theater": "X", "lanes": ["A"], "objectives": [
        {"id": "OBJA1", "lane": "A", "seq": 1, "name": "One", "placeholder": False, "center": {"lat": 0, "lon": 0},
         "cps": [cp(1, 27.0, 54.0, "Southeast"), cp(2, 27.2, 54.0, "Southeast"), cp(3, 27.01, 54.0, "Crossroads")]},
        {"id": "OBJA2", "lane": "A", "seq": 2, "name": "Two", "placeholder": False, "center": {"lat": 0, "lon": 0},
         "cps": [cp(4, 27.3, 54.0, "Southeast"), cp(5, 27.25, 54.0, "capture point")]},
    ]}
    return parse_dataset(raw, "T")


def test_nearest_neighbor_order_from_first_cp():
    ds = ds_two()
    got = [c.id for c in order_cps(ds.objectives[0].cps, None)]
    assert got == ["CAP-1", "CAP-3", "CAP-2"]


def test_second_objective_starts_nearest_previous_last_cp():
    ds = ds_two()
    sel = build_selection(ds, ["A1", "A2"], capacity=10, labels=False)
    assert [p.cp_id for p in sel.points] == ["CAP-1", "CAP-3", "CAP-2", "CAP-5", "CAP-4"]
    assert [p.index for p in sel.points] == [1, 2, 3, 4, 5]


def test_capacity_refuses_never_truncates():
    ds = ds_two()
    with pytest.raises(CapacityError, match="5 capture points.*holds 4"):
        build_selection(ds, ["A1", "A2"], capacity=4, labels=False)
    sel = build_selection(ds, ["A1", "A2"], capacity=4, labels=False, enforce_capacity=False)
    assert sel.over and sel.used == 5 and len(sel.points) == 5


def test_same_code_in_different_objectives_is_left_alone():
    ds = ds_two()
    sel = build_selection(ds, ["a1", "OBJA2"], capacity=10, labels=True, code_cfg=CFG)
    per_obj = {}
    for p in sel.points:
        per_obj.setdefault(p.objective_id, []).append(p.code)
    assert all(len(set(v)) == len(v) for v in per_obj.values())      # unique inside one objective
    codes = [p.code for p in sel.points]
    assert codes == [p.code for p in build_selection(ds, ["a1", "OBJA2"], capacity=10, labels=True, code_cfg=CFG).points]
    solo = {o: sorted(p.code for p in build_selection(ds, [o], capacity=10, labels=True, code_cfg=CFG).points)
            for o in ("A1", "A2")}
    assert sorted(per_obj["OBJA1"]) == solo["A1"] and sorted(per_obj["OBJA2"]) == solo["A2"]   # together = alone
    assert set(per_obj["OBJA1"]) & set(per_obj["OBJA2"])              # and the shared code (SE) was not renamed


def test_unknown_objective_and_duplicates():
    ds = ds_two()
    with pytest.raises(KeyError):
        ds.resolve("Z9")
    sel = build_selection(ds, ["A1", "a1"], capacity=10, labels=False)
    assert sel.used == 3


def test_distance():
    assert distance_m(27, 54, 27.001, 54) == pytest.approx(111.3, abs=0.5)
