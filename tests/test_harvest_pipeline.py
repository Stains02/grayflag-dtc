import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from grayflag_dtc.core import servers  # noqa: E402
from grayflag_dtc.harvest import collect as collect_harvest, inject as inject_harvester  # noqa: E402

LUA = shutil.which("lua5.1") or shutil.which("lua")
pytestmark = pytest.mark.skipif(LUA is None, reason="lua5.1 not installed")
SYN = ROOT / "tests" / "data" / "synthetic_mission.lua"


def make_miz(tmp_path):
    miz = tmp_path / "in.trk"
    with zipfile.ZipFile(miz, "w") as z:
        z.writestr("mission", SYN.read_text(encoding="utf-8"))
        z.writestr("options", "options = {}")
    return miz


def run_injected(tmp_path, cfg=None, strip=True):
    text = SYN.read_text(encoding="utf-8")
    script = inject_harvester.build_script((ROOT / "grayflag_dtc" / "harvest" / "harvester.lua").read_text(encoding="utf-8"), "test-mission", cfg or {})
    injected = inject_harvester.inject(text, script, strip=strip)
    f = tmp_path / "injected.lua"
    f.write_text(injected, encoding="utf-8")
    out = subprocess.run([LUA, str(ROOT / "tests" / "lua_harness.lua"), str(f)], capture_output=True, check=True)
    return injected, out.stdout


def test_injected_mission_still_loads_and_adds_one_trigger(tmp_path):
    injected, _ = run_injected(tmp_path)
    assert 'GFDTC_MISSION_ID' in injected and '[2]=nil' in injected
    assert "GFDTC harvester" in injected


def test_harvester_output_round_trips_through_collector(tmp_path):
    _, log = run_injected(tmp_path)
    raw = json.loads(collect_harvest.reassemble(log).decode())
    assert raw["theater"] == "Syria" and raw["mission_id"] == "test-mission"
    ds = collect_harvest.normalize(raw, {"id": "t", "name": "T"}, "x.trk")
    assert [o["id"] for o in ds["objectives"]] == ["OBJA2", "OBJA10", "OBJ12", "OBJA30"]   # numeric seq order, not string order
    typo = ds["objectives"][2]                                              # "OBJ12": no lattice letter in the zone name
    assert (typo["lane"], typo["seq"], typo["name"], len(typo["cps"])) == ("A", 12, "Typo Town", 1)   # lane from the zone's lat property
    rnd = ds["objectives"][3]                                               # a circular objective zone: capture points inside the circle
    assert (rnd["id"], rnd["name"], [c["id"] for c in rnd["cps"]]) == ("OBJA30", "Round Town", ["CAP-5"])
    assert ds["objectives"][0]["placeholder"] is True
    a10 = ds["objectives"][1]
    assert a10["name"] == "Café Town"                                       # UTF-8 survives the ASCII log
    assert [c["id"] for c in a10["cps"]] == ["CAP", "CAP-1"]
    assert a10["cps"][1]["name"] == 'North "Village"'
    assert ds["objectives"][0]["cps"][0]["id"] == "CAP-2"
    cp = a10["cps"][0]
    assert cp["lat"] == pytest.approx(30 + 500 / 100000) and cp["lon"] == pytest.approx(50 + 500 / 100000)
    assert cp["elev_m"] == pytest.approx(105.0)
    assert cp["dcs"] == {"x": 500.0, "y": 500.0}
    assert ds["lanes"] == ["A"]                                             # lowercase lane property normalized
    kinds = {a["kind"] for a in ds["anomalies"]}
    assert kinds == {"cp_unassigned"}                                       # the stray CP-3
    assert collect_harvest.validate(ds)                                     # anomalies block auto-enable


def test_chunking_reassembles_when_small_chunks(tmp_path):
    _, log = run_injected(tmp_path, {"chunk_size": 50})
    assert log.count(b"GFDTC|") > 10
    json.loads(collect_harvest.reassemble(log).decode())


def test_reassemble_takes_newest_complete_sequence():
    log = (b"x GFDTC|1/2|{\"a\":\nx GFDTC|2/2|1}\n"      # old complete run
           b"x GFDTC|1/2|{\"a\":\nx GFDTC|2/2|2}\n"      # newest complete run
           b"x GFDTC|1/3|{\"a\":\n")                      # truncated newest
    assert json.loads(collect_harvest.reassemble(log)) == {"a": 2}


def test_reassemble_fails_without_harvest():
    with pytest.raises(SystemExit):
        collect_harvest.reassemble(b"nothing here\n")


def test_prepare_and_collect_cli_register_and_enable_scenario(tmp_path, isolated_data):
    from grayflag_dtc.__main__ import main
    track = make_miz(tmp_path)
    out_dir = tmp_path / "harvest"
    assert main(["prepare", str(track), "--id", "mine-coin", "--tag", "MC", "--name", "Mine COIN", "--out-dir", str(out_dir)]) == 0
    out = out_dir / "mine-coin.miz"
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == {"mission", "options"}
        assert "GFDTC_MISSION_ID" in z.read("mission").decode()
    entry = servers.find_server("mine-coin")
    assert entry["tag"] == "MC" and entry["enabled"] is False and entry["source_track"] == "in.trk"
    assert (isolated_data / "servers.json").exists()                      # your scenarios live in the data folder

    f = tmp_path / "i.lua"; f.write_text(zipfile.ZipFile(out).read("mission").decode(), encoding="utf-8")
    log = subprocess.run([LUA, str(ROOT / "tests" / "lua_harness.lua"), str(f)], capture_output=True, check=True).stdout
    (tmp_path / "dcs.log").write_bytes(log)
    assert main(["collect", "mine-coin", "--log", str(tmp_path / "dcs.log")]) == 1     # the stray CP is an anomaly
    ds = json.loads((isolated_data / "theaters" / "mine-coin.json").read_text(encoding="utf-8"))
    assert ds["server_id"] == "mine-coin" and ds["source_track"] == "in.trk" and ds["airfields"]
    assert servers.find_server("mine-coin")["enabled"] is False
    assert main(["collect", "mine-coin", "--log", str(tmp_path / "dcs.log"), "--force"]) == 1
    assert servers.find_server("mine-coin")["enabled"] is True
    assert "mine-coin" in [s["id"] for s in servers.enabled_servers()] and "pg-redux" in [s["id"] for s in servers.enabled_servers()]


def test_server_id_must_be_a_slug():
    with pytest.raises(ValueError):
        servers.upsert_server("Bad Id")


def test_airfields_harvested_with_player_slots(tmp_path):
    _, log = run_injected(tmp_path)
    ds = collect_harvest.normalize(json.loads(collect_harvest.reassemble(log).decode()), {"id": "t", "name": "T"}, "x.trk")
    by = {a["name"]: a for a in ds["airfields"]}
    assert set(by) == {"Alpha AB", "Beta Field", "Far Strip"}               # the carrier (ship) is skipped
    assert by["Alpha AB"]["slots"] == {"F-16C_50": 2}                       # matched by airdromeId; "High" AI unit ignored
    assert by["Beta Field"]["slots"] == {"F-16C_50": 1}                     # no id: nearest airbase within the radius
    assert by["Far Strip"]["slots"] == {} and by["Alpha AB"]["kind"] == "airdrome"
    assert by["Alpha AB"]["dcs"] == {"x": 100.0, "y": 200.0} and by["Alpha AB"]["elev_m"] == pytest.approx(101.0)


def test_server_scripts_are_removed_but_run_once_bookkeeping_stays():
    mission = (
        'mission = { ["trig"] = { ["actions"] = {\n'
        '  [1] = "a_do_script_file(getValueResourceByKey(\\"ResKey_Action_1\\"));a_do_script(\\"saveName = \\\\\\"X.lua\\\\\\"\\");",\n'
        '  [2] = "a_do_script(\\"addCVFleet(1)\\"); mission.trig.func[5]=nil;",\n'
        '  [3] = "a_out_text_delay(\\"hello\\", 5);",\n'
        '}, ["conditions"] = { [1] = "return(true)", }, ["events"] = {}, ["func"] = {}, }, }'
    )
    out, n = inject_harvester.strip_scripts(mission)
    assert n == 2
    assert '[1] = "return"' in out and '[2] = "mission.trig.func[5]=nil;"' in out
    assert 'a_out_text_delay(\\"hello\\", 5);' in out and "a_do_script" not in out
    assert inject_harvester.strip_scripts(out)[1] == 0                      # nothing left to strip
    assert inject_harvester.strip_scripts("no triggers here") == ("no triggers here", 0)


def test_prepared_mission_runs_only_the_harvest_not_the_server_script(tmp_path):
    _, log = run_injected(tmp_path)
    assert b"MARK server_script_ran=false" in log
    assert collect_harvest.reassemble(log)                                  # and the harvest itself still works
    _, kept = run_injected(tmp_path, strip=False)
    assert b"MARK server_script_ran=true" in kept                           # control: the synthetic server script does run


def test_base_zones_are_harvested_as_farps(tmp_path):
    _, log = run_injected(tmp_path)
    ds = collect_harvest.normalize(json.loads(collect_harvest.reassemble(log).decode()), {"id": "t", "name": "T"}, "x.trk")
    by = {f["name"]: f for f in ds["farps"]}
    start, mid = by["Start FARP"], by["Mid FARP"]                       # names are trimmed
    assert (start["lane"], start["avail"], start["template"], start["convoy"]) == ("A", 0, "sixPadFarp", False)
    assert (mid["lane"], mid["avail"], mid["template"], mid["convoy"]) == ("A", 12, None, True)
    assert start["dcs"] == {"x": 200.0, "y": 300.0} and start["elev_m"] == pytest.approx(102.0)   # land.getHeight stub: 100 + x/100
    assert [f["avail"] for f in ds["farps"] if f["lane"] == "A"] == sorted(f["avail"] for f in ds["farps"] if f["lane"] == "A")


def test_qrf_and_supply_zones_are_harvested_as_sites(tmp_path):
    _, log = run_injected(tmp_path)
    ds = collect_harvest.normalize(json.loads(collect_harvest.reassemble(log).decode()), {"id": "t", "name": "T"}, "x.trk")
    by = {s["kind"]: s for s in ds["sites"]}
    assert set(by) == {"qrf", "supply"}                                       # the synthetic mission also has an hrf zone: ignored
    assert (by["qrf"]["name"], by["qrf"]["lane"], by["qrf"]["lim"]) == ("Hill QRF", "A", 14)           # name trimmed, lane upper-cased
    assert by["supply"]["dcs"] == {"x": 650.0, "y": 720.0} and by["supply"]["elev_m"] == pytest.approx(106.5)


def test_editor_trigger_rules_are_stripped_too_because_dcs_runs_the_scripts_from_there(tmp_path):
    text = SYN.read_text(encoding="utf-8")
    out, n = inject_harvester.strip_scripts(text)
    assert n == 3                                                          # 1 compiled action + 2 editor rule actions
    f = tmp_path / "stripped.lua"
    f.write_text(out, encoding="utf-8")
    res = subprocess.run([LUA, "-e", f'''
dofile("{f}")
local acts = mission.trigrules[1].actions
print("rule1:", acts[1].predicate, acts[1].text, "|", acts[1].file)
print("rule2:", acts[2].predicate, acts[2].text)
print("rule3:", acts[3].predicate, acts[3].text, acts[3].seconds)
print("trig:", mission.trig.actions[1])
'''], capture_output=True, text=True, check=True).stdout.replace("\t", " ")
    assert "rule1: a_do_script return | nil" in res and "rule2: a_do_script return" in res
    assert 'rule3: a_out_text_delay hello {braces} "quoted" 5' in res           # the non-script action is untouched
    assert "a_do_script_file" not in out and "ResKey_Action_6" not in out


def test_prepared_missions_have_no_script_left_in_either_table(tmp_path):
    _, log = run_injected(tmp_path)                                         # run_injected strips and injects
    assert b"MARK server_script_ran=false" in log
    injected = (tmp_path / "injected.lua").read_text(encoding="utf-8")
    res = subprocess.run([LUA, "-e", f'''
dofile("{tmp_path / "injected.lua"}")
local n = 0
for _, rule in ipairs(mission.trigrules) do
  for _, a in ipairs(rule.actions or {{}}) do
    if (a.predicate == "a_do_script" and a.text ~= "return" and not tostring(a.text):find("GFDTC")) or a.predicate == "a_do_script_file" then n = n + 1 end
  end
end
print("server script actions left in trigrules: " .. n)
'''], capture_output=True, text=True, check=True).stdout
    assert "left in trigrules: 0" in res


def test_collect_refuses_a_log_whose_newest_harvest_belongs_to_another_scenario(tmp_path, isolated_data):
    from grayflag_dtc.__main__ import main
    track = make_miz(tmp_path)
    out_dir = tmp_path / "h"
    assert main(["prepare", str(track), "--id", "first-one", "--out-dir", str(out_dir)]) == 0
    assert main(["prepare", str(track), "--id", "second-one", "--out-dir", str(out_dir)]) == 0
    f = tmp_path / "i.lua"; f.write_text(zipfile.ZipFile(out_dir / "first-one.miz").read("mission").decode(), encoding="utf-8")
    (tmp_path / "dcs.log").write_bytes(subprocess.run([LUA, str(ROOT / "tests" / "lua_harness.lua"), str(f)], capture_output=True, check=True).stdout)
    with pytest.raises(ValueError, match="is for 'first-one', not 'second-one'"):
        collect_harvest.collect("second-one", tmp_path / "dcs.log")
    assert not (isolated_data / "theaters" / "second-one.json").exists()          # nothing was written
    assert servers.find_server("second-one")["enabled"] is False
    assert collect_harvest.collect("first-one", tmp_path / "dcs.log", force_enable=True).enabled is True


def _warehouse(entry_id, dynamic, coalition, heli_amount, unlimited="false", all_unlimited="false"):
    return (f'[{entry_id}] = {{ ["dynamicSpawn"] = {dynamic}, ["unlimitedAircrafts"] = {all_unlimited}, ["coalition"] = "{coalition}",'
            f' ["aircrafts"] = {{ ["helicopters"] = {{ ["AH-64D_BLK_II"] = {{ ["initialAmount"] = {heli_amount}, ["wsType"] = {{ [1] = 1, }}, '
            f'["unlimited"] = {unlimited}, }}, }}, ["planes"] = {{ ["F-16C_50"] = {{ ["initialAmount"] = 9, ["unlimited"] = false, }}, }}, }}, }},\n')


def test_dynamic_spawn_bases_come_from_the_warehouses_and_static_pad_positions():
    from grayflag_dtc.harvest.dynspawn import extract
    wh = ('warehouses = {\n["airports"] = {\n' + _warehouse(7, "true", "blue", 0, all_unlimited="true") + _warehouse(8, "false", "blue", 5)
          + '},\n["warehouses"] = {\n' + _warehouse(501, "true", "blue", 3) + _warehouse(502, "true", "blue", 0) + _warehouse(503, "true", "blue", 0, unlimited="true") + '},\n}')
    mission = ('mission = { ["coalition"] = { ["blue"] = { ["country"] = { [1] = { ["static"] = { ["group"] = {\n'
               '[1] = { ["name"] = "Alpha FARP", ["units"] = { [1] = { ["unitId"] = 501, ["name"] = "pad", ["type"] = "Invisible FARP", ["x"] = 10.5, ["y"] = -20, }, }, },\n'
               '[2] = { ["name"] = "Empty FARP", ["units"] = { [1] = { ["unitId"] = 502, ["name"] = "pad2", ["type"] = "Invisible FARP", ["x"] = 1, ["y"] = 2, }, }, },\n'
               '[3] = { ["name"] = "Free FARP", ["units"] = { [1] = { ["unitId"] = 503, ["name"] = "pad3", ["type"] = "Invisible FARP", ["x"] = 3, ["y"] = 4, }, }, },\n'
               '}, }, }, }, }, }, }')
    rows = extract(wh, mission)
    by = {(r["kind"], r["id"]): r for r in rows}
    assert set(by) == {("airport", 7), ("static", 501), ("static", 503)}                 # 8 not dynamic, 502 has no stock
    assert by[("static", 501)]["name"] == "Alpha FARP" and (by[("static", 501)]["x"], by[("static", 501)]["y"]) == (10.5, -20.0)
    assert by[("airport", 7)]["types"] == ["AH-64D_BLK_II"] and "F-16C_50" not in by[("static", 501)]["types"]   # helicopters only
