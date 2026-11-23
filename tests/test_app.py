from pathlib import Path

from fastapi.testclient import TestClient

from grayflag_dtc.server import app

c = TestClient(app)


def test_healthz():
    assert c.get("/healthz").json() == {"ok": True}


def test_only_enabled_servers_listed():
    from grayflag_dtc.core import servers
    assert [s["id"] for s in c.get("/api/servers").json()] == [s["id"] for s in servers.all_servers() if s["enabled"]]


def test_server_detail_lists_cp_names():
    sid = c.get("/api/servers").json()[0]["id"]
    d = c.get(f"/api/servers/{sid}").json()
    o = next(o for o in d["objectives"] if o["cps"])
    assert o["code"] == f"{o['lane']}{o['seq']}" and o["cps"][0]["name"] is not None and o["cps"][0]["code"]


def test_preview_and_build():
    sid = c.get("/api/servers").json()[0]["id"]
    body = {"server": sid, "airframe": "f16c", "objectives": ["a1", "B2"]}
    pv = c.post("/api/preview", json=body).json()
    assert pv["used"] == len(pv["points"]) and pv["capacity"] == 25
    assert pv["points"][0]["slot"] == "STPT 1" and all(p["code"] for p in pv["points"])
    r = c.post("/api/build", json={**body, "deliver": "download"})
    assert r.status_code == 200 and ".dtc" in r.headers["content-disposition"]
    assert r.json()["data"]["MPD"]["NAV_PTS"]
    assert c.post("/api/build", json={**body, "deliver": "ftp"}).status_code == 422
    assert c.post("/api/preview", json={**body, "objectives": ["ZZ99"]}).status_code == 422


def test_preview_flags_over_capacity_and_build_refuses():
    sid = c.get("/api/servers").json()[0]["id"]
    d = c.get(f"/api/servers/{sid}").json()
    allc = [o["code"] for o in d["objectives"]]
    body = {"server": sid, "airframe": "ah64d", "objectives": allc}
    assert c.post("/api/preview", json=body).json()["over"] is True
    assert c.post("/api/build", json=body).status_code == 422


def test_settings_roundtrip():
    s = c.get("/api/airframes/f16c/settings").json()
    assert s["values"]["COMM.COMM1.Channel_1.freq"] == 267.75 and not s["has_saved"]
    vals = dict(s["values"]); vals["COMM.COMM1.Channel_1.freq"] = "300.5"
    s2 = c.put("/api/airframes/f16c/settings/defaults", json=vals).json()
    assert s2["has_saved"] and s2["values"]["COMM.COMM1.Channel_1.freq"] == 300.5
    assert c.put("/api/airframes/f16c/settings/defaults", json={"COMM.COMM1.Channel_1.freq": 50}).status_code == 422
    assert not c.delete("/api/airframes/f16c/settings/defaults").json()["has_saved"]


def test_index_versions_assets_and_nothing_is_cacheable():
    r = c.get("/")
    import re
    assert re.search(r'/static/app\.js\?v=[0-9a-f]{10}"', r.text) and re.search(r'/static/style\.css\?v=[0-9a-f]{10}"', r.text)
    assert r.headers["cache-control"] == "no-store"
    assert c.get("/static/app.js").headers["cache-control"] == "no-store"


def test_send_to_dcs_writes_into_the_dtc_folder_and_prunes(tmp_path, monkeypatch):
    dcs = tmp_path / "Saved Games" / "DCS"
    (dcs / "Config").mkdir(parents=True)
    monkeypatch.setenv("GFDTC_DCS_DIR", str(dcs))
    assert c.get("/api/local").json()["dcs_dir"] == str(dcs)
    sid = c.get("/api/servers").json()[0]["id"]
    body = {"server": sid, "airframe": "ah64d", "objectives": ["a1"], "deliver": "dcs"}
    dtc = dcs / "DTC"
    dtc.mkdir()
    for i in range(12):                                            # old GF_ files and a file that is not ours
        (dtc / f"GF_OLD_{i:02d}.dtc").write_text("{}", encoding="utf-8")
        import os; os.utime(dtc / f"GF_OLD_{i:02d}.dtc", (1_000_000 + i, 1_000_000 + i))
    (dtc / "MyOwn.dtc").write_text("{}", encoding="utf-8")
    r = c.post("/api/build", json=body)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["pruned"] == 3
    written = dtc / r.json()["name"]
    assert written.exists() and '"CTRLM"' in written.read_text(encoding="utf-8") and not list(dtc.glob("*.tmp"))
    assert (dtc / "MyOwn.dtc").exists() and len(list(dtc.glob("GF_*.dtc"))) == 10


def test_send_to_dcs_without_a_dcs_folder_is_a_clear_error():
    sid = c.get("/api/servers").json()[0]["id"]
    r = c.post("/api/build", json={"server": sid, "airframe": "ah64d", "objectives": ["a1"], "deliver": "dcs"})
    assert r.status_code == 409 and "DCS" in r.json()["detail"]


def test_dcs_folder_is_found_from_saved_games_and_can_be_overridden(tmp_path, monkeypatch):
    sg = tmp_path / "sg"
    for name in ("DCS", "DCS.openbeta", "NotDCS"):
        (sg / name / "Logs").mkdir(parents=True)
    import os
    os.utime(sg / "DCS" / "Logs", (1, 1))
    (sg / "DCS.openbeta" / "Logs" / "dcs.log").write_text("x", encoding="utf-8")
    monkeypatch.setenv("GFDTC_SAVED_GAMES", str(sg))
    assert c.get("/api/local").json()["dcs_dir"].endswith("DCS.openbeta")        # most recently used wins
    assert c.put("/api/local", json={"dcs_dir": str(sg / "DCS")}).json()["dcs_dir"].endswith("DCS")
    assert c.put("/api/local", json={"dcs_dir": str(sg / "nope")}).status_code == 422


def test_harvest_endpoints_prepare_and_collect(tmp_path, monkeypatch):
    import subprocess, zipfile, shutil
    lua = shutil.which("lua5.1") or shutil.which("lua")
    if lua is None:
        import pytest; pytest.skip("lua5.1 not installed")
    dcs = tmp_path / "DCS"
    (dcs / "Config").mkdir(parents=True)
    (dcs / "Logs").mkdir()
    (dcs / "Tracks" / "Multiplayer").mkdir(parents=True)
    root = Path(__file__).resolve().parent
    trk = dcs / "Tracks" / "Multiplayer" / "Grayflag Test A-1.trk"
    with zipfile.ZipFile(trk, "w") as z:
        z.writestr("mission", (root / "data" / "synthetic_mission.lua").read_text(encoding="utf-8"))
    monkeypatch.setenv("GFDTC_DCS_DIR", str(dcs))
    tracks = c.get("/api/harvest/tracks").json()
    assert [t["name"] for t in tracks] == ["Grayflag Test A-1.trk"]
    r = c.post("/api/harvest/prepare", json={"track": tracks[0]["path"], "server_id": "test-run", "name": "Test Run", "tag": "TR"})
    assert r.status_code == 200
    miz = dcs / "Missions" / "Harvest" / "test-run.miz"
    assert miz.exists()
    r = c.post("/api/harvest/collect", json={"server_id": "test-run"})
    assert r.status_code == 409 and "dcs.log not found" in r.json()["detail"]                     # DCS has not run yet
    (dcs / "Logs" / "dcs.log").write_text("nothing here\n", encoding="utf-8")
    assert c.post("/api/harvest/collect", json={"server_id": "test-run"}).status_code == 409      # log without a harvest
    f = tmp_path / "i.lua"
    f.write_text(zipfile.ZipFile(miz).read("mission").decode(), encoding="utf-8")
    (dcs / "Logs" / "dcs.log").write_bytes(subprocess.run([lua, str(root / "lua_harness.lua"), str(f)], capture_output=True, check=True).stdout)
    out = c.post("/api/harvest/collect", json={"server_id": "test-run"}).json()
    assert "objectives" in out["summary"] and out["enabled"] is False and out["problems"]   # the synthetic stray CP
    out = c.post("/api/harvest/collect", json={"server_id": "test-run", "force": True}).json()
    assert out["enabled"] is True
    assert "test-run" in [s["id"] for s in c.get("/api/servers").json()]
    assert c.get("/api/servers/test-run").json()["objectives"]


def test_servers_report_the_date_their_data_was_read_and_version_is_in_changelog():
    import re
    from pathlib import Path
    from grayflag_dtc import __version__
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s["data_date"]) for s in c.get("/api/servers").json())
    log = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {__version__}" in log                      # every released version is described


def test_preview_counts_break_the_selection_down_by_kind():
    c = TestClient(__import__("grayflag_dtc.server", fromlist=["app"]).app)
    n = c.post("/api/preview", json={"server": "caucasus", "airframe": "ah64d", "objectives": ["A34", "A35", "C9"]}).json()["counts"]
    assert n["cps"] > 0 and n["sites"] > 0 and n["farps"] > 0
    assert n["total"] == n["cps"] + n["sites"] + n["farps"]


def test_f16_counts_keep_airfield_destinations_apart_from_steerpoints():
    c = TestClient(__import__("grayflag_dtc.server", fromlist=["app"]).app)
    n = c.post("/api/preview", json={"server": "caucasus", "airframe": "f16c", "objectives": ["A34", "A35"]}).json()["counts"]
    assert n["total"] == n["cps"] and n["dest_capacity"] == 19 and n["dest"] <= 19


def test_qrf_supply_checkbox_adds_enemy_bases_as_steerpoints_after_the_cps_on_every_aircraft():
    c = TestClient(__import__("grayflag_dtc.server", fromlist=["app"]).app)
    body = {"server": "caucasus", "airframe": "f16c", "objectives": ["A34", "A35"]}
    assert c.post("/api/preview", json=body).json()["counts"]["sites"] == 0                       # off by default on the F-16
    pv = c.post("/api/preview", json={**body, "qrf_supply": True}).json()
    n = pv["counts"]
    assert n["sites"] > 0 and n["total"] == n["cps"] + n["sites"] <= pv["capacity"]
    assert [s["slot"] for s in pv["sites"]][0] == f"STPT {n['cps'] + 1}"
    r = c.post("/api/build", json={**body, "qrf_supply": True, "deliver": "download"})
    nav = r.json()["data"]["MPD"]["NAV_PTS"]
    assert len(nav) == n["cps"] + n["sites"] and nav[-1]["note"].split()[0] in ("QRF", "SUP") and nav[-1]["R1"] is True
    assert c.post("/api/preview", json={**body, "airframe": "ah64d"}).json()["counts"]["sites"] > 0   # Apache: on by default
    assert c.post("/api/preview", json={**body, "airframe": "ah64d", "qrf_supply": False}).json()["counts"]["sites"] == 0
    h = c.post("/api/build", json={**body, "airframe": "fa18c", "qrf_supply": True, "deliver": "download"}).json()
    assert h["data"]["WYPT"]["NAV_PTS"][-1]["text_note"] in ("QRF", "SUP")
