import json
import sys

from grayflag_dtc import paths


def test_exe_data_dir_defaults_to_localappdata_and_portable_folder_wins(tmp_path, monkeypatch):
    monkeypatch.delenv("GFDTC_DATA", raising=False)
    monkeypatch.setattr(paths, "FROZEN", True)
    exe_dir = tmp_path / "Desktop"
    exe_dir.mkdir()
    monkeypatch.setattr(sys, "executable", str(exe_dir / "grayflag-dtc.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert paths.data_dir() == tmp_path / "Local" / "grayflag-dtc" / "data"       # nothing is written next to the exe
    (exe_dir / "data").mkdir()                                                    # opt in to portable use
    assert paths.data_dir() == exe_dir / "data"
    monkeypatch.setenv("GFDTC_DATA", str(tmp_path / "x"))                          # --data / env beats both
    assert paths.data_dir() == tmp_path / "x"


def test_seed_copies_missing_and_newer_bundled_but_keeps_newer_user_data(tmp_path, monkeypatch):
    bundled = tmp_path / "res" / "data" / "theaters"
    bundled.mkdir(parents=True)
    for name, when in (("a.json", "2026-11-20T10:00:00Z"), ("b.json", "2026-11-20T10:00:00Z"), ("c.json", "2026-11-20T10:00:00Z")):
        (bundled / name).write_text(json.dumps({"harvested_at": when, "from": "bundle"}), encoding="utf-8")
    monkeypatch.setattr(paths, "RES", tmp_path / "res")
    mine = tmp_path / "mine"
    (mine / "theaters").mkdir(parents=True)
    (mine / "theaters" / "b.json").write_text(json.dumps({"harvested_at": "2026-11-01T00:00:00Z", "from": "old"}), encoding="utf-8")
    (mine / "theaters" / "c.json").write_text(json.dumps({"harvested_at": "2026-12-01T00:00:00Z", "from": "mine"}), encoding="utf-8")
    monkeypatch.setenv("GFDTC_DATA", str(mine))
    assert paths.seed_data() == ["a.json", "b.json"]                              # c.json is newer than the bundle: kept
    read = lambda n: json.loads((mine / "theaters" / n).read_text(encoding="utf-8"))["from"]
    assert (read("a.json"), read("b.json"), read("c.json")) == ("bundle", "bundle", "mine")
    assert paths.seed_data() == []                                                # idempotent
