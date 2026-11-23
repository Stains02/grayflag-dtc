import copy
import json
from pathlib import Path

import pytest

from grayflag_dtc.airframes import registry
from grayflag_dtc.airframes.ah64d import PLUGIN
from grayflag_dtc.airframes.base import BuildOptions, Point

FIX = Path(__file__).resolve().parent / "fixtures" / "ah64d"
REF = json.loads((FIX / "AH-64D_BLK_II_DTC.dtc").read_text(encoding="utf-8"))
TEMPLATE = json.loads((Path(__file__).resolve().parent.parent / "templates" / "dtc" / "ah64d.dtc").read_text(encoding="utf-8"))
CFG = {"note_mode": "blank", "first_slot": 51, "mission_slot": 1}


def ref_points():
    pts = REF["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"]["POINTS"]
    return [Point(index=i + 1, lat=0, lon=0, elev_m=p["alt"], x=p["x"], y=p["y"], code=p["text"], name="",
                  objective_id="OBJA1") for i, p in enumerate(pts)]


def test_golden_matches_dcs_exported_reference_field_for_field():
    out = PLUGIN.build(TEMPLATE, ref_points(), BuildOptions(CFG, "GermanyCW", name=""))
    assert out == REF
    assert json.dumps(out, sort_keys=False) == json.dumps(REF, sort_keys=False)   # key order preserved too


def test_template_is_not_mutated_and_only_ctrlm_changes():
    before = copy.deepcopy(TEMPLATE)
    out = PLUGIN.build(TEMPLATE, ref_points()[:2], BuildOptions(CFG, "GermanyCW", name="GF_X"))
    assert TEMPLATE == before
    out["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"] = TEMPLATE["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"]
    out["name"], out["data"]["name"] = TEMPLATE["name"], TEMPLATE["data"]["name"]
    assert out == TEMPLATE


def test_numbers_are_51_up_and_note_uses_cp_name():
    pts = [Point(index=i + 1, lat=0, lon=0, elev_m=12.34, x=1.0, y=2.0, code="NVL", name="North Village",
                 objective_id="OBJA1") for i in range(3)]
    for p, c in zip(pts, ("NVL", "NV2", "NV3")):
        p.code = c
    out = PLUGIN.build(TEMPLATE, pts, BuildOptions({"first_slot": 51}, "GermanyCW", name="GF_T"))
    cm = out["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"]
    assert cm["isEnabled"] is True
    assert [p["num"] for p in cm["POINTS"]] == [51, 52, 53]
    assert cm["POINTS"][0] == {"alt": 12.3, "id": 46, "note": "North Village", "num": 51, "text": "NVL",
                               "x": 1.0, "y": 2.0}
    assert out["name"] == out["data"]["name"] == "GF_T"
    assert PLUGIN.validate(out) == []


def test_capacity_49_fits_and_50_refused():
    mk = lambda n: [Point(index=i + 1, lat=0, lon=0, elev_m=0, x=i, y=i, code=f"A{i:02d}"[:3], name="x",
                          objective_id="O") for i in range(n)]
    out = PLUGIN.build(TEMPLATE, mk(49), BuildOptions({}, "GermanyCW"))
    assert out["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"]["POINTS"][-1]["num"] == 99
    with pytest.raises(ValueError):
        PLUGIN.build(TEMPLATE, mk(50), BuildOptions({}, "GermanyCW"))


def test_validate_catches_problems():
    out = PLUGIN.build(TEMPLATE, ref_points(), BuildOptions(CFG, "GermanyCW"))
    pts = out["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"]["POINTS"]
    pts[0]["text"] = "TOOLONG"
    pts[1]["id"] = 5
    pts[2]["num"] = 3
    errs = PLUGIN.validate(out)
    assert len(errs) == 3


def test_registry_discovers_plugin_and_is_ready_with_base_template():
    assert "ah64d" in registry.plugins()
    assert registry.not_ready_reasons("ah64d", "Syria") == []
    assert registry.not_ready_reasons("zzz", "x") == ["no plugin"]


def test_schema_paths_exist_in_dcs_exported_dtc_and_overlay_applies():
    from grayflag_dtc.core import settings as S
    schema = PLUGIN.settings_schema()
    cur = S.current_values(REF, schema)            # every declared path must exist in a real DCS file
    assert len(cur) == len(schema) == 4 + 40 + 16
    out = S.apply_overlay(REF, schema, {"Presets.COMM.2.COMMS.UHF.Frequency": 251.5, "Laser.ChannelsCodes.A": "1636",
                                        "Radios.InitialRadioSettings.FM1": 40})
    assert out["data"]["Presets"]["COMM"][2]["COMMS"]["UHF"]["Frequency"] == 251.5
    assert out["data"]["Radios"]["InitialRadioSettings"]["FM1"]["Frequency"] == 40
    assert out["data"]["Radios"]["InitialRadioSettings"]["FM1"]["Mode"] == 1          # manual
    assert out["data"]["Laser"]["ChannelsCodes"]["A"] == {"Four": 1, "Three": 6, "Two": 3, "One": 6}
    assert S.current_values(out, schema)["Laser.ChannelsCodes.A"] == "1636"
    assert REF["data"]["Presets"]["COMM"][2]["COMMS"]["UHF"]["Frequency"] != 251.5      # input untouched
    with pytest.raises(ValueError):
        S.apply_overlay(REF, schema, {"Radios.InitialRadioSettings.UHF": 100})   # out of range
    with pytest.raises(ValueError):
        S.apply_overlay(REF, schema, {"IFF.Mode3A.Code": "7700"})                        # not exposed


def test_laser_code_validation_and_order():
    from grayflag_dtc.core import settings as S
    schema = PLUGIN.settings_schema()
    assert [(f.sub, f.row, f.type) for f in schema[:4]] == [(r, "Tune", "tune") for r in ("VHF", "UHF", "FM1", "FM2")]
    assert [f.row for f in schema[4:8]] == ["Preset 1"] * 4 and [f.sub for f in schema[4:8]] == ["VHF", "UHF", "FM1", "FM2"]
    assert not [f for f in schema if f.sub == "Channels"]
    for good in ("1636", "1688", "2788", "5111", "4778"):
        assert S.laser_code_error(good) is None
    for bad in ("3111", "1811", "1191", "1119", "163", "16366", "abcd", "0111", "1709"):
        assert S.laser_code_error(bad), bad
    with pytest.raises(ValueError):
        S.apply_overlay(REF, schema, {"Laser.ChannelsCodes.B": "3111"})


def test_tune_box_preset_or_manual_frequency():
    from grayflag_dtc.core import settings as S
    schema = PLUGIN.settings_schema()
    over = {"Presets.COMM.1.COMMS.UHF.Frequency": 231.8, "Radios.InitialRadioSettings.UHF": 2,
            "Radios.InitialRadioSettings.VHF": 130.8}
    out = S.apply_overlay(REF, schema, over)
    r = out["data"]["Radios"]["InitialRadioSettings"]
    assert (r["UHF"]["Mode"], r["UHF"]["Preset"], r["UHF"]["Frequency"]) == (0, 2, 231.8)   # preset: freq follows the preset
    assert (r["VHF"]["Mode"], r["VHF"]["Frequency"]) == (1, 130.8)                         # manual
    cur = S.current_values(out, schema)
    assert cur["Radios.InitialRadioSettings.UHF"] == 2 and cur["Radios.InitialRadioSettings.VHF"] == 130.8
    for bad in (0, 11, 2.5, 20, 500, "x"):
        with pytest.raises(ValueError):
            S.apply_overlay(REF, schema, {"Radios.InitialRadioSettings.UHF": bad})
