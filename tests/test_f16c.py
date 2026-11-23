import pytest
import copy
import json
from pathlib import Path

from grayflag_dtc.airframes import registry
from grayflag_dtc.airframes.base import BuildOptions, Point

FIX = Path(__file__).parent / "fixtures" / "f16c" / "F-16CM_bl50_ref.dtc"
PLUGIN = registry.plugins()["f16c"]
CFG = registry.config("f16c")


def _pts(n):
    return [Point(index=i + 1, lat=0, lon=0, elev_m=100.0 + i, x=1000.0 + i, y=2000.0 + i,
                  code=f"A{i % 10}{chr(65 + i % 26)}" if i >= 0 else None, name=f"Point {i}",
                  objective_id="OBJA1") for i in range(n)]


def _tpl():
    return json.loads(Path(registry.template_path(CFG, "Syria")).read_text(encoding="utf-8"))


def test_golden_matches_dcs_reference():
    from grayflag_dtc.airframes.base import AirfieldPoint
    ref = json.loads(FIX.read_text(encoding="utf-8"))["data"]["MPD"]
    afs = [AirfieldPoint(name="x", code=d["text"], elev_m=d["alt"], x=d["x"], y=d["y"], spawn=False, distance_m=0)
           for d in ref["DEST"]]
    nav = [Point(index=i + 1, lat=0, lon=0, elev_m=d["alt"], x=d["x"], y=d["y"], code="N", name="",
                 objective_id="X") for i, d in enumerate(ref["NAV_PTS"])]
    out = PLUGIN.build(_tpl(), nav, BuildOptions(CFG, "Syria", airfields=afs))
    for got, want in zip(out["data"]["MPD"]["DEST"], ref["DEST"]):
        for k in ("alt", "id", "number", "text", "x", "y"):
            assert got[k] == want[k]
    for got, want in zip(out["data"]["MPD"]["NAV_PTS"], ref["NAV_PTS"]):
        for k in want:
            if k not in ("note", "alt", "x", "y", "routeAltitude", "speed", "R1"):
                assert got[k] == want[k], k


def test_capture_points_only_on_steerpoints_never_on_destinations():
    out = PLUGIN.build(_tpl(), _pts(25), BuildOptions(CFG, "Syria"))
    assert len(out["data"]["MPD"]["NAV_PTS"]) == 25 and out["data"]["MPD"]["DEST"] == []     # no airfields offered: empty
    assert PLUGIN.validate(out) == []
    assert CFG["capacity"] == 25
    with pytest.raises(ValueError, match="steerpoints 1-25"):
        PLUGIN.build(_tpl(), _pts(26), BuildOptions(CFG, "Syria"))


def test_vhf_modulation_follows_frequency():
    t = _tpl()
    t["data"]["COMM"]["COMM2"]["Channel_1"]["freq"] = 30
    t["data"]["COMM"]["COMM2"]["Channel_2"]["freq"] = 129.4
    out = PLUGIN.build(t, _pts(2), BuildOptions(CFG, "Syria"))
    assert out["data"]["COMM"]["COMM2"]["Channel_1"]["modulation"] == 2
    assert out["data"]["COMM"]["COMM2"]["Channel_2"]["modulation"] == 1


def test_validate_rejects_bad_label():
    from grayflag_dtc.airframes.base import AirfieldPoint
    afs = [AirfieldPoint(name="x", code="ABC", elev_m=1, x=1, y=1, spawn=False, distance_m=0)]
    out = PLUGIN.build(_tpl(), _pts(3), BuildOptions(CFG, "Syria", airfields=afs))
    out["data"]["MPD"]["DEST"][0]["text"] = "ab!"
    assert any("label" in e for e in PLUGIN.validate(out))


def test_radio_settings_are_two_columns_com1_then_com2():
    sc = [f for f in PLUGIN.settings_schema() if f.group == "Radios"]
    assert [f.sub for f in sc[:1]] == ["COM1"] and {f.sub for f in sc} == {"COM1", "COM2"}
    assert [f.row for f in sc if f.sub == "COM1"] == [str(i) for i in range(1, 21)]
    assert next(f for f in sc if f.sub == "COM1").path.startswith("COMM.COMM1.")   # COM1 = UHF
    assert next(f for f in sc if f.sub == "COM2").path.startswith("COMM.COMM2.")   # COM2 = VHF


def test_countermeasure_defaults_match_the_grayflag_table():
    from grayflag_dtc.core import settings as S
    sc = PLUGIN.settings_schema()
    assert len([f for f in sc if f.group == "Countermeasures"]) == 48
    over = S.effective_overlay("f16c", data=Path("/nonexistent"))
    out = S.apply_overlay(_tpl(), sc, over)
    P = out["data"]["MPD"]["CMDS"]["CMDSProgramSettings"]
    assert P["MAN1"]["Chaff"] == {"BurstQuantity": 4, "BurstInterval": 1.0, "SalvoQuantity": 1, "SalvoInterval": 1.0}
    assert P["MAN2"]["Chaff"] == {"BurstQuantity": 4, "BurstInterval": 0.5, "SalvoQuantity": 2, "SalvoInterval": 2.0}
    assert P["MAN3"]["Flare"] == {"BurstQuantity": 30, "BurstInterval": 1.0, "SalvoQuantity": 1, "SalvoInterval": 1.0}
    assert P["MAN4"]["Flare"] == {"BurstQuantity": 15, "BurstInterval": 0.5, "SalvoQuantity": 2, "SalvoInterval": 0.5}
    assert P["MAN5"]["Chaff"] == {"BurstQuantity": 2, "BurstInterval": 0.1, "SalvoQuantity": 3, "SalvoInterval": 0.5}
    assert P["MAN6"]["Flare"] == {"BurstQuantity": 2, "BurstInterval": 0.1, "SalvoQuantity": 3, "SalvoInterval": 0.5}
    assert all(v == 0 for v in P["MAN3"]["Chaff"].values()) and all(v == 0 for v in P["MAN1"]["Flare"].values())
    import pytest
    with pytest.raises(ValueError):
        S.apply_overlay(_tpl(), sc, {"MPD.CMDS.CMDSProgramSettings.MAN1.Chaff.BurstQuantity": 100})


def _ds_with_airfields(n_cps=3):
    from grayflag_dtc.core.dataset import parse_dataset
    cps = [{"id": f"CAP-{i}", "name": f"Spot {i}", "lat": 25.0 + i * 0.01, "lon": 55.0, "elev_m": 10, "dcs": {"x": i * 1000, "y": 0}}
           for i in range(n_cps)]
    afs = [{"id": i, "name": nm, "kind": "airdrome", "lat": 25.0 + off, "lon": 55.0, "elev_m": 5 + i,
            "dcs": {"x": 100.0 * i, "y": 50.0}, "slots": ({"F-16C_50": 2} if spawn else {})}
           for i, (nm, off, spawn) in enumerate([("Near Intl Airport", 0.02, False), ("Far Spawn AB", 3.0, True),
                                                 ("Mid Field", 0.5, False), ("Al Dhafra AB", 4.0, True)])]
    raw = {"server_id": "t", "server_name": "T", "theater": "Syria", "lanes": ["A"],
           "objectives": [{"id": "OBJA1", "lane": "A", "seq": 1, "name": "X", "center": {"lat": 25, "lon": 55}, "cps": cps}],
           "airfields": afs}
    return parse_dataset(raw, tag="T")


def test_airfields_spawn_first_then_nearest_and_fill_free_destinations():
    from grayflag_dtc.core.codes import CodeConfig
    from grayflag_dtc.core.selection import build_selection
    ds = _ds_with_airfields()
    sel = build_selection(ds, ["A1"], capacity=44, labels=True, code_cfg=CodeConfig.load(),
                          spawn_types=PLUGIN.airfield_spawn_types)
    assert [a.name for a in sel.airfields] == ["Far Spawn AB", "Al Dhafra AB", "Near Intl Airport", "Mid Field"]
    assert [a.spawn for a in sel.airfields] == [True, True, False, False]
    assert sel.airfields[0].distance_m < sel.airfields[1].distance_m           # nearest spawn airfield first
    out = PLUGIN.build(_tpl(), sel.points, BuildOptions(CFG, "Syria", airfields=sel.airfields))
    dest = out["data"]["MPD"]["DEST"]
    assert [d["id"] for d in dest] == ["DEST81", "DEST82", "DEST83", "DEST84"] and dest[0]["note"] == "Far Spawn AB"
    assert PLUGIN.validate(out) == []
    assert len({d["text"] for d in dest}) == 4
    assert PLUGIN.airfield_labels(3, CFG)[0] == "DEST 81" and len(PLUGIN.airfield_labels(3, CFG)) == 19


def test_more_than_25_capture_points_are_refused_not_spilled_into_destinations():
    import pytest
    from grayflag_dtc.core.codes import CodeConfig
    from grayflag_dtc.core.selection import CapacityError, build_selection
    ds = _ds_with_airfields(n_cps=30)
    with pytest.raises(CapacityError, match="30 capture points.*holds 25"):
        build_selection(ds, ["A1"], capacity=CFG["capacity"], labels=True, code_cfg=CodeConfig.load(),
                        spawn_types=PLUGIN.airfield_spawn_types)
    sel = build_selection(ds, ["A1"], capacity=CFG["capacity"], labels=True, code_cfg=CodeConfig.load(),
                          spawn_types=PLUGIN.airfield_spawn_types, enforce_capacity=False)
    assert sel.over and PLUGIN.airfield_labels(30, CFG)[0] == "DEST 81"      # airfields always start at DEST 81


def test_airfield_codes_drop_noise_words():
    from grayflag_dtc.core.codes import CodeConfig, airfield_code
    cfg = CodeConfig.load()
    assert airfield_code("Al Dhafra AB", cfg) == airfield_code("Al Dhafra", cfg)
    assert len(airfield_code("Kish International Airport", cfg)) == 3


def test_helipads_and_farps_are_not_offered_as_f16_airfields():
    from grayflag_dtc.core.codes import CodeConfig
    from grayflag_dtc.core.selection import build_selection
    ds = _ds_with_airfields()
    from grayflag_dtc.core.dataset import Airfield
    ds.airfields.append(Airfield(id=50, name="Right Here FARP", kind="helipad", lat=25.0, lon=55.0, elev_m=1, x=0, y=0,
                                 slots={"F-16C_50": 4}))
    sel = build_selection(ds, ["A1"], capacity=44, labels=True, code_cfg=CodeConfig.load(),
                          spawn_types=PLUGIN.airfield_spawn_types)
    assert "Right Here FARP" not in [a.name for a in sel.airfields] and len(sel.airfields) == 4


def test_many_colliding_airfield_names_do_not_exhaust_codes():
    from grayflag_dtc.core.codes import CodeConfig
    from grayflag_dtc.core.dataset import Airfield
    from grayflag_dtc.core.selection import build_selection
    ds = _ds_with_airfields()
    ds.airfields = [Airfield(id=i, name=f"Hamlet Landing {i}", kind="airdrome", lat=25.0 + i * 0.001, lon=55.0, elev_m=1, x=i, y=0,
                             slots={}) for i in range(225)]
    sel = build_selection(ds, ["A1"], capacity=44, labels=True, code_cfg=CodeConfig.load(),
                          spawn_types=PLUGIN.airfield_spawn_types)
    codes = [a.code for a in sel.airfields]
    assert len(codes) == 40 and len(set(codes)) == 40 and all(len(c) == 3 for c in codes)


def test_generated_helipad_strips_are_filtered_out_by_name():
    from grayflag_dtc.core.codes import airfield_excluded
    for junk in ("HS02", "HMed03", "HI07", "HStad04", "HOil01", "HL12", "H_med_orig_04", "Sanliurfa Heliport", "Al Maktoum FARP"):
        assert airfield_excluded(junk), junk
    for real in ("H3", "H4", "H3 Northwest", "H4 Emergency", "Hama", "Haifa", "Hatay", "Incirlik", "Al Dhafra AFB", "Lar", "T2"):
        assert not airfield_excluded(real), real
