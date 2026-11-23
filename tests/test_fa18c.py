import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from grayflag_dtc.airframes import registry
from grayflag_dtc.airframes.base import BuildOptions, Point
from grayflag_dtc.airframes.fa18c import PLUGIN
from grayflag_dtc.server import app

FIX = Path(__file__).resolve().parent / "fixtures" / "fa18c" / "FA-18C_ref.dtc"
CFG = registry.config("fa18c")
REF = json.loads(FIX.read_text(encoding="utf-8"))


def _tpl():
    return json.loads(registry.template_path(CFG, "SinaiMap").read_text(encoding="utf-8"))


def _pts(n):
    return [Point(index=i + 1, lat=0, lon=0, elev_m=100.0 + i, x=1000.0 + i, y=2000.0 + i, code=f"A{i % 10}{chr(65 + i % 26)}",
                  name=f"Point {i}", objective_id="OBJA1") for i in range(n)]


def test_golden_waypoints_match_the_dcs_export_field_for_field_and_in_key_order():
    ref = REF["data"]["WYPT"]["NAV_PTS"]
    pts = [Point(index=i + 1, lat=0, lon=0, elev_m=w["alt"], x=w["x"], y=w["y"], code="", name="", objective_id="X")
           for i, w in enumerate(ref)]
    out = PLUGIN.build(_tpl(), pts, BuildOptions(CFG, "SinaiMap"))
    got = out["data"]["WYPT"]["NAV_PTS"]
    assert len(got) == len(ref) == 4
    for g, r in zip(got, ref):
        assert list(g) == list(r)                                                       # same keys, same order as DCS writes
        assert {k: v for k, v in g.items()} == r                                       # and the same values (empty code/name)


def test_everything_else_in_the_dtc_passes_through_untouched():
    out = PLUGIN.build(_tpl(), _pts(5), BuildOptions(CFG, "SinaiMap", name="GF_X"))
    tpl = _tpl()
    assert out["name"] == out["data"]["name"] == "GF_X"
    for k in tpl["data"]:
        if k not in ("WYPT", "name"):
            assert out["data"][k] == tpl["data"][k], k
    assert out["data"]["WYPT"]["NAV_ROUTE"] == [[], [], []] and out["data"]["WYPT"]["NAV_SETTINGS"] == tpl["data"]["WYPT"]["NAV_SETTINGS"]
    assert out["data"]["WYPT"]["mirror_NAV_PTS"] is False and not any(p["R1"] or p["R2"] or p["R3"] for p in out["data"]["WYPT"]["NAV_PTS"])


def test_capacity_is_58_waypoints_and_waypoint_59_stays_free():
    out = PLUGIN.build(_tpl(), _pts(58), BuildOptions(CFG, "SinaiMap"))
    pts = out["data"]["WYPT"]["NAV_PTS"]
    assert [p["wypt_num"] for p in pts] == list(range(1, 59)) and pts[-1]["id"] == "STPT58" and CFG["capacity"] == 58
    assert PLUGIN.validate(out) == []
    with pytest.raises(ValueError, match="waypoints 1-58"):
        PLUGIN.build(_tpl(), _pts(59), BuildOptions(CFG, "SinaiMap"))
    assert out["data"]["WYPT"]["NAV_SETTINGS"]["AA_Waypoint"] == {"AA_WP_Enabled": False, "AA_WP_Number": 59}


def test_code_and_name_go_in_the_editor_notes_and_terrain_is_set_in_both_places():
    from grayflag_dtc.core.build import build
    dtc, sel = build("pg-redux", "fa18c", ["A16"], name="GF_T")
    assert dtc["data"]["terrain"] == "PersianGulf" and dtc["data"]["WYPT"]["terrain"] == "PersianGulf"
    w = dtc["data"]["WYPT"]["NAV_PTS"][0]
    assert w["note"].startswith(sel.points[0].code) and sel.points[0].name[:10] in w["note"] and w["text_note"] == sel.points[0].code
    assert PLUGIN.validate(dtc) == []


def test_hornet_is_offered_through_the_api_with_waypoint_slots_and_no_settings():
    c = TestClient(app)
    assert "F/A-18C" in [a["name"] for a in c.get("/api/airframes").json()]
    s = c.get("/api/airframes/fa18c/settings").json()
    assert s["schema"] == [] and s["values"] == {}
    sid = c.get("/api/servers").json()[0]["id"]
    pv = c.post("/api/preview", json={"server": sid, "airframe": "fa18c", "objectives": ["a1"]}).json()
    assert pv["capacity"] == 58 and pv["points"][0]["slot"] == "WP 1" and pv["airfields"] == [] and pv["farps"] == [] and pv["sites"] == []
    r = c.post("/api/build", json={"server": sid, "airframe": "fa18c", "objectives": ["a1"], "deliver": "download"})
    assert r.status_code == 200 and r.json()["data"]["WYPT"]["NAV_PTS"]
