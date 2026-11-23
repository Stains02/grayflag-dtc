import json

import pytest
from fastapi.testclient import TestClient

from grayflag_dtc.airframes import registry
from grayflag_dtc.airframes.ah64d import PLUGIN
from grayflag_dtc.airframes.base import BuildOptions, Point
from grayflag_dtc.core import farps as F
from grayflag_dtc.core.codes import CodeConfig
from grayflag_dtc.core.dataset import Farp, parse_dataset
from grayflag_dtc.core.selection import build_selection

CFG = registry.config("ah64d")


def _cp(i, x, y):
    return {"id": f"CAP-{i}", "name": f"Spot {i}", "lat": 25.0, "lon": 55.0, "elev_m": 10, "dcs": {"x": x, "y": y}}


def _farp(i, name, lane, avail, x, y, template="sixPadFarp"):
    return {"id": f"F{i}", "name": name, "lane": lane, "avail": avail, "template": template, "convoy": False,
            "lat": 25.0, "lon": 55.0, "elev_m": 20 + i, "dcs": {"x": x, "y": y}}


RAW = {"server_id": "t", "server_name": "T", "theater": "Syria", "lanes": ["A", "B"],
       "objectives": [
           {"id": "OBJA5", "lane": "A", "seq": 5, "name": "Five", "center": {"lat": 25, "lon": 55}, "cps": [_cp(1, 0, 0)]},
           {"id": "OBJA10", "lane": "A", "seq": 10, "name": "Ten", "center": {"lat": 25, "lon": 55}, "cps": [_cp(2, 50000, 0)]},
           {"id": "OBJB3", "lane": "B", "seq": 3, "name": "Three", "center": {"lat": 25, "lon": 55}, "cps": [_cp(3, 0, 50000)]}],
       "farps": [
           _farp(0, "Start FARP", "A", 0, 1000, 0),                     # open from the start
           _farp(1, "Near Base", "A", 5, 500, 0),                       # opens when A5 is the active objective
           _farp(2, "Later FARP", "A", 6, 200, 0),                      # locked while A5 is active
           _farp(3, "Far East FARP", "A", 9, 49000, 0),
           _farp(4, "Bee FARP", "B", 2, 0, 49000),
           _farp(5, "Red Kish Base", "A", 0, 10, 0, template=None),     # enemy base
           _farp(6, "Shiraz Fixed Wing Base", "A", 0, 20, 0),           # not a helicopter FARP
           _farp(7, "Some Hut", "A", 0, 30, 0, template=None)]}         # neither a template nor FARP/BASE in the name


def _ds():
    return parse_dataset(RAW, tag="T")


def test_which_bases_count_as_farps():
    ds = _ds()
    assert [f.name for f in ds.farps if F.is_farp(f)] == ["Start FARP", "Near Base", "Later FARP", "Far East FARP", "Bee FARP"]


def test_a_farp_is_open_when_the_active_objective_has_reached_its_number():
    ds = _ds()
    names = lambda lane, seq: sorted(f.name for f in F.open_farps(ds, lane, seq))
    assert names("A", 4) == ["Start FARP"]
    assert names("A", 5) == ["Near Base", "Start FARP"]
    assert names("A", 6) == ["Later FARP", "Near Base", "Start FARP"]
    assert names("B", 1) == [] and names("B", 3) == ["Bee FARP"]          # lattices unlock independently


def test_the_two_nearest_open_spawn_points_per_chosen_objective():
    ds = _ds()
    sel = build_selection(ds, ["A5", "A10", "B3"], capacity=49, labels=True, code_cfg=CodeConfig.load(), spawns_per_objective=2)
    got = {f.name: f for f in sel.farps}
    # A5: Near Base (500 m) and Start FARP (1000 m). A10: Far East (1 km) and Start FARP. B3: Bee FARP, then the nearest
    # FARP of another lattice that is open (Later FARP: lattice A is at 10 >= its unlock number 6).
    assert set(got) == {"Near Base", "Start FARP", "Far East FARP", "Later FARP", "Bee FARP"}
    assert [f.name for f in sel.farps] == ["Near Base", "Bee FARP", "Far East FARP", "Start FARP", "Later FARP"]   # first choices first
    assert got["Start FARP"].objectives == ["A05", "A10"] and got["Later FARP"].objectives == ["B03"]
    assert len({f.code for f in sel.farps}) == len(sel.farps) and all(len(f.code) <= 3 for f in sel.farps)
    solo = build_selection(ds, ["A5"], capacity=49, labels=True, code_cfg=CodeConfig.load(), spawns_per_objective=2)
    assert [f.name for f in solo.farps] == ["Near Base", "Start FARP"]    # Later FARP is locked; Bee FARP's lattice is unknown
    one = build_selection(ds, ["A10"], capacity=49, labels=True, code_cfg=CodeConfig.load(), spawns_per_objective=1)
    assert [f.name for f in one.farps] == ["Far East FARP"]
    none = build_selection(ds, ["A5"], capacity=49, labels=True, code_cfg=CodeConfig.load(), spawns_per_objective=0)
    assert none.farps == []


def test_a_start_farp_serves_every_lattice_but_other_locked_farps_do_not():
    ds = _ds()
    b3 = build_selection(ds, ["B3"], capacity=49, labels=True, code_cfg=CodeConfig.load(), spawns_per_objective=3)
    assert [f.name for f in b3.farps] == ["Bee FARP", "Start FARP"]        # Start FARP (unlock 0, lattice A) is open for B3
    # lattice A has no picked objective, so Near Base / Later FARP / Far East FARP (unlock 5, 6, 9) stay closed for B3
    with_a = build_selection(ds, ["B3", "A5"], capacity=49, labels=True, code_cfg=CodeConfig.load(), spawns_per_objective=9)
    assert "Near Base" in {f.name for f in with_a.farps}                      # a picked A5 reaches Near Base's unlock number (5)
    assert not {"Later FARP", "Far East FARP"} & {f.name for f in with_a.farps if "B03" in f.objectives}   # unlock 6 and 9 > 5


def _spawn_ds(extra_airfields):
    raw = json.loads(json.dumps(RAW))
    raw["airfields"] = extra_airfields
    return parse_dataset(raw, tag="T")


def _af(i, name, kind, x, y, slots):
    return {"id": i, "name": name, "kind": kind, "lat": 25, "lon": 55, "elev_m": 40 + i, "dcs": {"x": x, "y": y}, "slots": slots}


AH = {"AH-64D_BLK_II": 4}


def test_bases_with_apache_slots_are_spawn_points_and_far_ones_are_left_out():
    from grayflag_dtc.core.spawn import rank_spawns
    ds = _spawn_ds([_af(1, "Slot Field", "airdrome", 9000, 0, AH), _af(2, "No Slots Field", "airdrome", 1000, 0, {"A-10C": 2}),
                    _af(3, "Faraway Field", "airdrome", 300000, 0, AH), _af(4, "Pad One", "helipad", 2000, 2000, AH)])
    byc = {o.code: o for o in ds.objectives}
    farps, fields = rank_spawns(ds, [byc["B3"]], ("AH-64D_BLK_II",), CodeConfig.load(), per_objective=9, range_nm=20)
    assert [f.name for f in farps] == ["Bee FARP"] and fields == []         # the nearest is always offered; the rest are 26+ nm away
    farps, fields = rank_spawns(ds, [byc["A5"]], ("AH-64D_BLK_II",), CodeConfig.load(), per_objective=9, range_nm=40)
    assert [a.name for a in fields] == ["Slot Field"]                        # an airdrome with AH-64D slots, within range
    assert "Pad One" in [f.name for f in farps] and "Faraway Field" not in [a.name for a in fields]
    assert "No Slots Field" not in [a.name for a in fields]                  # no Apache slots there
    assert "Near Base" in [f.name for f in farps]


def test_a_slot_helipad_that_is_a_farp_zone_is_open_for_every_lattice():
    from grayflag_dtc.core.spawn import rank_spawns
    ds = _spawn_ds([_af(1, "Near Base", "helipad", 520, 10, AH)])            # same place and name as the (locked) Near Base zone
    byc = {o.code: o for o in ds.objectives}
    farps, _ = rank_spawns(ds, [byc["B3"]], ("AH-64D_BLK_II",), CodeConfig.load(), per_objective=9)
    assert "Near Base" in [f.name for f in farps]                            # static slots prove it is usable from the start
    assert [f.name for f in farps].count("Near Base") == 1                   # and it is not listed twice
    farps, _ = rank_spawns(_ds(), [byc["B3"]], ("AH-64D_BLK_II",), CodeConfig.load(), per_objective=9)
    assert "Near Base" not in [f.name for f in farps]                        # without the slots it stays closed for B3


def test_with_dynamic_spawn_data_only_dynamic_bases_and_slot_bases_are_spawn_points():
    from grayflag_dtc.core.dataset import DynSpawn
    from grayflag_dtc.core.spawn import rank_spawns
    ds = _spawn_ds([_af(1, "Slot Field", "airdrome", 9000, 0, AH)])
    byc = {o.code: o for o in ds.objectives}
    every, _ = rank_spawns(ds, [byc["A5"]], ("AH-64D_BLK_II",), CodeConfig.load(), per_objective=9)
    assert "Near Base" in [f.name for f in every]                            # no dynamic data: every FARP zone counts
    ds.dynamic_spawns = [DynSpawn("static", 1, "Near Base", 520.0, 10.0, ["AH-64D_BLK_II"]), DynSpawn("static", 2, "Other", 5.0, 5.0, ["UH-1H"])]
    farps, fields = rank_spawns(ds, [byc["A5"]], ("AH-64D_BLK_II",), CodeConfig.load(), per_objective=9)
    assert [f.name for f in farps] == ["Near Base"]                          # the only FARP zone that stocks the airframe
    assert [a.name for a in fields] == ["Slot Field"]                        # slots still count


def test_lattice_direction_and_what_is_behind_an_objective():
    ds = _ds()
    byc = {o.code: o for o in ds.objectives}
    assert F.lattice_direction(ds, byc["A10"]) == pytest.approx((1.0, 0.0))        # from A5 (0,0) to A10 (50000,0)
    assert F.lattice_direction(ds, byc["A5"]) == pytest.approx((1.0, 0.0))         # first objective: towards the next one
    assert F.lattice_direction(ds, byc["B3"]) is None                              # a lattice with a single objective
    assert F.is_behind(ds, byc["A10"], 30000, 0) and not F.is_behind(ds, byc["A10"], 60000, 0)
    assert F.is_behind(ds, byc["B3"], 1, 2)                                        # no direction known: nothing is "ahead"


def test_airfields_behind_the_objective_come_before_those_ahead_but_after_spawn_airfields():
    raw = json.loads(json.dumps(RAW))
    raw["airfields"] = [
        {"id": 1, "name": "Behind Far", "kind": "airdrome", "lat": 25, "lon": 55, "elev_m": 5, "dcs": {"x": 30000, "y": 0}, "slots": {}},
        {"id": 2, "name": "Ahead Near", "kind": "airdrome", "lat": 25, "lon": 55, "elev_m": 5, "dcs": {"x": 55000, "y": 0}, "slots": {}},
        {"id": 3, "name": "Slots Faraway", "kind": "airdrome", "lat": 25, "lon": 55, "elev_m": 5, "dcs": {"x": -90000, "y": 0}, "slots": {"F-16C_50": 4}}]
    ds = parse_dataset(raw, tag="T")
    sel = build_selection(ds, ["A10"], capacity=49, labels=True, code_cfg=CodeConfig.load(), spawn_types=("F-16C_50",))
    assert [a.name for a in sel.airfields] == ["Slots Faraway", "Behind Far", "Ahead Near"]
    assert [a.spawn for a in sel.airfields] == [True, False, False]


def _points(n):
    return [Point(index=i + 1, lat=0, lon=0, elev_m=1.0, x=float(i), y=0.0, code=f"C{i % 10}{chr(65 + i % 26)}", name=f"P{i}",
                  objective_id="OBJA5") for i in range(n)]


def _tpl():
    return json.loads(registry.template_path(CFG, "Syria").read_text(encoding="utf-8"))


def test_apache_writes_farps_as_fuel_and_ammo_control_measures_after_the_capture_points():
    ds = _ds()
    sel = build_selection(ds, ["A5"], capacity=49, labels=True, code_cfg=CodeConfig.load(), spawns_per_objective=2)
    out = PLUGIN.build(_tpl(), _points(3), BuildOptions(CFG, "Syria", farps=sel.farps))
    pts = out["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"]["POINTS"]
    assert [p["num"] for p in pts] == [51, 52, 53, 54, 55] and [p["id"] for p in pts] == [46, 46, 46, 68, 68]
    assert pts[3]["note"] == "Near Base" and pts[3]["text"] == sel.farps[0].code and pts[3]["x"] == 500 and pts[3]["alt"] == 21
    assert PLUGIN.validate(out) == [] and PLUGIN.farp_labels(3, CFG) == [f"C{n}" for n in range(54, 100)]


def test_farps_only_fill_the_slots_the_capture_points_leave():
    ds = _ds()
    sel = build_selection(ds, ["A5"], capacity=49, labels=True, code_cfg=CodeConfig.load(), spawns_per_objective=2)
    assert PLUGIN.farp_room(47, CFG) == 2 and PLUGIN.farp_room(48, CFG) == 1 and PLUGIN.farp_room(49, CFG) == 0
    out = PLUGIN.build(_tpl(), _points(48), BuildOptions(CFG, "Syria", farps=sel.farps))
    pts = out["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"]["POINTS"]
    assert len(pts) == 49 and pts[-1]["id"] == 68 and pts[-1]["text"] == sel.farps[0].code       # nearest kept, the rest dropped
    out = PLUGIN.build(_tpl(), _points(49), BuildOptions(CFG, "Syria", farps=sel.farps))
    assert len(out["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"]["POINTS"]) == 49 and PLUGIN.validate(out) == []


def test_preview_lists_farps_with_slots_and_says_when_there_is_no_room(isolated_data):
    from grayflag_dtc.core import servers
    (isolated_data / "theaters" / "t.json").write_text(json.dumps({**RAW, "harvested_at": "2026-11-20T00:00:00Z"}), encoding="utf-8")
    servers.upsert_server("t", name="T", tag="T", enabled=True)
    from grayflag_dtc.server import app
    c = TestClient(app)
    pv = c.post("/api/preview", json={"server": "t", "airframe": "ah64d", "objectives": ["A5", "A10"]}).json()
    assert pv["farps"][0]["name"] == "Near Base" and pv["farps"][0]["slot"] == "C53"             # 2 CPs -> FARPs start at C53
    assert all(f["slot"] for f in pv["farps"])
    assert set(pv["farps"][0]) >= {"name", "code", "objectives", "distance_nm", "elev_ft"}
    f16 = c.post("/api/preview", json={"server": "t", "airframe": "f16c", "objectives": ["A5"]}).json()
    assert f16["farps"] == []                                                                       # the Viper does not use FARPs


# ---------------------------------------------------------------- enemy QRF and supply bases
def _site(i, kind, name, lane, lim, x, y):
    return {"id": f"S{i}", "kind": kind, "name": name, "lane": lane, "lim": lim, "lat": 25.0, "lon": 55.0, "elev_m": 30 + i,
            "dcs": {"x": x, "y": y}}


SITES = [_site(0, "qrf", "Hill QRF", "A", 5, 3000, 0),               # 1.6 nm from A5
         _site(1, "supply", "Hill Supply", "A", 5, 3500, 100),       # its pair
         _site(2, "qrf", "Ridge QRF", "A", 10, 52000, 0),            # 1.1 nm from A10
         _site(3, "qrf", "Lost QRF", "B", 3, 0, 120000)]             # 65 nm from B3, nothing nearer


def _ds_sites():
    return parse_dataset({**RAW, "sites": SITES}, tag="T")


def test_nearest_qrf_and_supply_per_chosen_objective_within_range():
    from grayflag_dtc.core.sites import rank_sites
    ds = _ds_sites()
    byc = {o.code: o for o in ds.objectives}
    a5 = rank_sites(ds, [byc["A5"]], 20)
    assert [(s.kind, s.name, s.text) for s in a5] == [("qrf", "Hill QRF", "QRF"), ("supply", "Hill Supply", "SUP")]
    a10 = rank_sites(ds, [byc["A10"]], 20)
    assert [s.name for s in a10] == ["Ridge QRF"]                       # the only supply base is 27 nm away: left out
    both = rank_sites(ds, [byc["A5"], byc["A10"]], 20)
    assert [s.name for s in both] == ["Ridge QRF", "Hill QRF", "Hill Supply"] and both[1].objectives == ["A05"]   # nearest first
    assert rank_sites(ds, [byc["B3"]], 20) == []                        # too far from everything
    assert [s.name for s in rank_sites(ds, [byc["B3"]], 80)] == ["Hill Supply", "Hill QRF"]   # nearest of each kind, any lattice
    assert rank_sites(parse_dataset(RAW, tag="T"), [byc["A5"]], 20) == []   # datasets harvested before sites existed


def test_apache_draws_enemy_bases_as_eu_after_the_cps_and_before_the_farps():
    ds = _ds_sites()
    sel = build_selection(ds, ["A5", "A10"], capacity=49, labels=True, code_cfg=CodeConfig.load(), spawns_per_objective=2, sites_range_nm=20)
    assert [s.name for s in sel.sites] == ["Ridge QRF", "Hill QRF", "Hill Supply"] and len(sel.farps) == 3
    out = PLUGIN.build(_tpl(), _points(2), BuildOptions(CFG, "Syria", farps=sel.farps, sites=sel.sites))
    pts = out["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"]["POINTS"]
    assert [p["num"] for p in pts] == list(range(51, 51 + 2 + 3 + 3))
    assert [p["id"] for p in pts] == [46, 46] + [46, 46, 46] + [68] * 3          # CPs, enemy bases (EU), then FARPs
    assert [p["text"] for p in pts[2:5]] == ["QRF", "QRF", "SUP"] and pts[2]["note"] == "Ridge QRF" and pts[2]["alt"] == 32
    assert PLUGIN.validate(out) == []


def test_capture_points_win_then_enemy_bases_then_farps_when_slots_run_out():
    ds = _ds_sites()
    sel = build_selection(ds, ["A5", "A10"], capacity=49, labels=True, code_cfg=CodeConfig.load(), spawns_per_objective=2, sites_range_nm=20)
    out = PLUGIN.build(_tpl(), _points(46), BuildOptions(CFG, "Syria", farps=sel.farps, sites=sel.sites))
    ids = [p["id"] for p in out["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"]["POINTS"]]
    assert len(ids) == 49 and ids.count(46) == 49 and ids.count(68) == 0        # 46 CPs + all 3 enemy bases fill it: no FARPs
    out = PLUGIN.build(_tpl(), _points(48), BuildOptions(CFG, "Syria", farps=sel.farps, sites=sel.sites))
    pts = out["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"]["POINTS"]
    assert len(pts) == 49 and pts[-1]["text"] == "QRF"                           # one slot: the nearest enemy base, not a FARP


def test_preview_puts_enemy_bases_right_after_the_cps_and_farps_after_them(isolated_data):
    from grayflag_dtc.core import servers
    (isolated_data / "theaters" / "t.json").write_text(json.dumps({**RAW, "sites": SITES, "harvested_at": "2026-11-20T00:00:00Z"}), encoding="utf-8")
    servers.upsert_server("t", name="T", tag="T", enabled=True)
    from grayflag_dtc.server import app
    pv = TestClient(app).post("/api/preview", json={"server": "t", "airframe": "ah64d", "objectives": ["A5", "A10"]}).json()
    assert [(s["slot"], s["code"], s["name"]) for s in pv["sites"]] == [("C53", "QRF", "Ridge QRF"), ("C54", "QRF", "Hill QRF"), ("C55", "SUP", "Hill Supply")]
    assert pv["farps"][0]["slot"] == "C56" and all(f["slot"] for f in pv["farps"])
    assert TestClient(app).post("/api/preview", json={"server": "t", "airframe": "f16c", "objectives": ["A5"]}).json()["sites"] == []


def test_a_qrf_or_supply_base_the_front_has_passed_no_longer_matters():
    from grayflag_dtc.core.sites import rank_sites, still_matters
    raw = json.loads(json.dumps({**RAW, "sites": SITES}))
    raw["sites"] += [_site(5, "qrf", "Passed QRF", "A", 8, 50500, 0)]     # lim 8: closer to A10 than Ridge QRF, but the front is at 10
    ds = parse_dataset(raw, tag="T")
    byc = {o.code: o for o in ds.objectives}
    a10 = rank_sites(ds, [byc["A10"]], 20)
    assert [s.name for s in a10] == ["Ridge QRF"]                           # Passed QRF (lim 8 < 10) is skipped
    a5 = rank_sites(ds, [byc["A5"]], 20)
    assert "Hill QRF" in [s.name for s in a5]                               # lim 5 >= 5: still matters while A5 is the active objective
    site = {s.name: s for s in ds.sites}
    assert still_matters(site["Ridge QRF"], byc["A10"], {}) and not still_matters(site["Hill QRF"], byc["A10"], {})
    # another lattice: unknown front keeps the site, a picked objective on that lattice decides
    assert still_matters(site["Hill QRF"], byc["B3"], {"B": [3]})            # lattice A has no picked objective: kept
    assert not still_matters(site["Hill QRF"], byc["B3"], {"B": [3], "A": [10]})   # lattice A is at 10: Hill QRF (lim 5) is behind it
    assert still_matters(site["Hill QRF"], byc["B3"], {"B": [3], "A": [4, 10]})    # one picked objective (4) is still before it


def test_shipped_caucasus_gives_the_apache_farps_and_enemy_bases_and_the_viper_airfields():
    c = TestClient(__import__("grayflag_dtc.server", fromlist=["app"]).app)
    assert "caucasus" in [s["id"] for s in c.get("/api/servers").json()]
    d = c.get("/api/servers/caucasus").json()
    assert any(o["code"] == "A10" and len(o["cps"]) == 7 for o in d["objectives"])         # the OBJ10 typo zone is A10
    pv = c.post("/api/preview", json={"server": "caucasus", "airframe": "ah64d", "objectives": ["A10", "B10"]}).json()
    assert pv["farps"] and pv["sites"] and all(f["slot"].startswith("C") for f in pv["farps"] + pv["sites"])
    assert all(s["distance_nm"] <= 25 for s in pv["sites"])
    v = c.post("/api/preview", json={"server": "caucasus", "airframe": "f16c", "objectives": ["A10"]}).json()
    assert len(v["airfields"]) == 19 and v["airfields"][0]["spawn"] is True
    r = c.post("/api/build", json={"server": "caucasus", "airframe": "fa18c", "objectives": ["A10"], "deliver": "download"})
    assert r.status_code == 200 and r.json()["data"]["terrain"] == "Caucasus"


def test_shipped_pg_and_germany_have_farps_and_enemy_bases():
    c = TestClient(__import__("grayflag_dtc.server", fromlist=["app"]).app)
    names = {s["id"]: s for s in c.get("/api/servers").json()}
    assert {"pg-redux", "caucasus", "germany"} <= set(names) and names["germany"]["name"] == "Germany WIP_Modern"
    for sid, picks in (("pg-redux", ["A16", "B10"]), ("germany", ["A5", "B10"])):
        pv = c.post("/api/preview", json={"server": sid, "airframe": "ah64d", "objectives": picks}).json()
        assert pv["farps"] and pv["sites"], sid
        assert all(s["distance_nm"] <= 25 for s in pv["sites"])
        v = c.post("/api/preview", json={"server": sid, "airframe": "f16c", "objectives": picks[:1]}).json()
        assert len(v["airfields"]) == 19 and v["airfields"][0]["spawn"] is True, sid


def test_the_enemy_base_range_is_25_nm_and_germany_a10_is_inside_it():
    assert registry.config("ah64d")["sites_range_nm"] == 25
    c = TestClient(__import__("grayflag_dtc.server", fromlist=["app"]).app)
    pv = c.post("/api/preview", json={"server": "germany", "airframe": "ah64d", "objectives": ["A10", "C10"]}).json()
    assert {s["name"] for s in pv["sites"]} >= {"Bravo QRF Base", "Charlie QRF Base"}      # 21-22 nm away: in at 25, out at 20
    assert all(s["distance_nm"] <= 25 for s in pv["sites"])


def test_shipped_sinai_works_on_all_three_aircraft():
    from grayflag_dtc.core.build import build
    c = TestClient(__import__("grayflag_dtc.server", fromlist=["app"]).app)
    assert "sinai" in [s["id"] for s in c.get("/api/servers").json()]
    assert any(o["code"] == "C24" and o["cps"] for o in c.get("/api/servers/sinai").json()["objectives"])    # a circular objective zone
    for af in ("ah64d", "f16c", "fa18c"):
        dtc, sel = build("sinai", af, ["A10", "C24"], name="T")
        assert dtc["data"]["terrain"] == "SinaiMap" and sel.used > 0
    pv = c.post("/api/preview", json={"server": "sinai", "airframe": "ah64d", "objectives": ["A10", "C24"]}).json()
    assert pv["farps"] and all(s["distance_nm"] <= 25 for s in pv["sites"])


def test_every_shipped_scenario_has_farps_and_enemy_bases():
    from grayflag_dtc.core.dataset import load_one
    from grayflag_dtc.core.farps import is_farp
    c = TestClient(__import__("grayflag_dtc.server", fromlist=["app"]).app)
    ids = [s["id"] for s in c.get("/api/servers").json()]
    assert set(ids) >= {"pg-redux", "syria-coin", "caucasus", "germany", "sinai"}
    for sid in ids:
        ds = load_one(sid)
        assert any(is_farp(f) for f in ds.farps) and {"qrf", "supply"} <= {s.kind for s in ds.sites}, sid


def test_early_objectives_get_a_spawn_point_on_every_shipped_scenario(isolated_data):
    from grayflag_dtc.core import servers
    from grayflag_dtc.core.dataset import load_one
    c = TestClient(__import__("grayflag_dtc.server", fromlist=["app"]).app)
    pv = c.post("/api/preview", json={"server": "syria-coin", "airframe": "ah64d", "objectives": ["A1"]}).json()
    assert [s["name"] for s in pv["spawn_airfields"]] == ["Bassel Al-Assad"] and pv["farps"] == []     # Syria A01
    for sid in ("pg-redux", "syria-coin", "caucasus", "germany", "sinai"):
        early = [o.code for o in load_one(sid).objectives if o.cps and o.seq <= 3]
        for code in early:
            r = c.post("/api/preview", json={"server": sid, "airframe": "ah64d", "objectives": [code]}).json()
            assert r["farps"] or r["spawn_airfields"], f"{sid} {code}: no spawn point offered"


def test_dynamic_spawn_data_decides_which_farp_zones_are_spawn_points():
    from grayflag_dtc.core.dataset import load_one
    from grayflag_dtc.core.spawn import candidates
    for sid in ("pg-redux", "syria-coin", "caucasus", "germany", "sinai"):
        ds = load_one(sid)
        assert ds.dynamic_spawns and any(d.kind == "static" and "AH-64D_BLK_II" in d.types for d in ds.dynamic_spawns), sid
    names = {c.name for c in candidates(load_one("syria-coin"), ("AH-64D_BLK_II",))}
    assert "Bassel Al-Assad" in names                                    # a static-slot airfield
    assert "Taftanaz Base" not in names and "Marj as Sultan FARP" not in names     # airfield markers: no dynamic stock, no slots
    germany = {c.name for c in candidates(load_one("germany"), ("AH-64D_BLK_II",))}
    assert "H FRG 40" in germany and "Ramstein Main Base" not in germany  # the blue dynamic airport, not the airfield marker
    assert "Khassab Base" not in {c.name for c in candidates(load_one("pg-redux"), ("AH-64D_BLK_II",))}


def test_the_nearest_spawn_point_is_offered_even_when_far_but_the_second_must_be_near():
    from grayflag_dtc.core.spawn import rank_spawns
    ds = _ds()
    byc = {o.code: o for o in ds.objectives}
    far, _ = rank_spawns(ds, [byc["B3"]], (), CodeConfig.load(), per_objective=2, range_nm=1)     # nothing is within 1 nm of B3 except Bee
    assert [f.name for f in far] == ["Bee FARP"]
    only_far = _spawn_ds([])                                                                         # B3 with Bee FARP removed: nearest = 27 nm away
    only_far.farps = [f for f in only_far.farps if f.name != "Bee FARP"]
    far, _ = rank_spawns(only_far, [{o.code: o for o in only_far.objectives}["B3"]], (), CodeConfig.load(), per_objective=2, range_nm=5)
    assert len(far) == 1 and far[0].distance_m > 5 * 1852                                           # the far one is still shown, alone


def test_an_airfield_and_a_farp_at_the_same_base_are_offered_once():
    from grayflag_dtc.core.spawn import rank_spawns
    ds = _spawn_ds([_af(1, "Start Airfield", "airdrome", 1800, 400, AH)])         # 1.9 km from the open Start FARP zone
    byc = {o.code: o for o in ds.objectives}
    farps, fields = rank_spawns(ds, [byc["A5"]], ("AH-64D_BLK_II",), CodeConfig.load(), per_objective=3)
    assert "Start FARP" in [f.name for f in farps] and fields == []                  # the FARP is taken first; its airfield is the same base
    far = _spawn_ds([_af(1, "Other Airfield", "airdrome", 9000, 0, AH)])             # 8 km away: a different place
    farps, fields = rank_spawns(far, [{o.code: o for o in far.objectives}["A5"]], ("AH-64D_BLK_II",), CodeConfig.load(), per_objective=3)
    assert [a.name for a in fields] == ["Other Airfield"]


def test_an_enemy_airport_becomes_a_spawn_point_once_its_lattice_has_passed_it():
    from grayflag_dtc.core.dataset import load_one
    from grayflag_dtc.core.spawn import rank_spawns
    ds = load_one("syria-coin")
    byc = {o.code: o for o in ds.objectives}
    cfg = CodeConfig.load()                                    # Taftanaz (red) sits at A20
    for code, expect in (("A20", False), ("A22", True)):
        _, fields = rank_spawns(ds, [byc[code]], ("AH-64D_BLK_II",), cfg, per_objective=9, range_nm=500)
        assert ("Taftanaz" in [a.name for a in fields]) is expect, code


def test_enemy_farps_on_caucasus_open_once_their_lattice_has_passed_them():
    from grayflag_dtc.core.dataset import load_one
    from grayflag_dtc.core.spawn import candidates
    ds = load_one("caucasus")
    red = {c.name: c.after for c in candidates(ds, ("AH-64D_BLK_II",)) if c.after}
    assert red["Apsheronsk FARP"] == ("A", 35) and red["Tuapse FARP"] == ("A", 31)       # the "Red " prefix is dropped
    assert not any("Static Invisible FARP-2" in n for n in red)                           # 30 nm from any objective: never opens


def test_helipads_named_h_are_left_out_for_fixed_wing_but_kept_for_helicopters():
    from grayflag_dtc.core.codes import airfield_excluded
    from grayflag_dtc.core.dataset import load_one
    from grayflag_dtc.core.selection import build_selection
    for n in ("H FRG 40", "H GDR 13", "H Med GDR 01", "H Radar GDR 07"):
        assert airfield_excluded(n, fixed_wing=True) and not airfield_excluded(n)
    assert not airfield_excluded("Hamburg", fixed_wing=True) and not airfield_excluded("Hahn", fixed_wing=True)
    sel = build_selection(load_one("germany"), ["A31"], capacity=25, labels=True, code_cfg=CodeConfig.load(), spawn_types=("F-16C_50",))
    assert sel.airfields and not any(a.name.startswith("H ") for a in sel.airfields)
