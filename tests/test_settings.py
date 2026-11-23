import pytest

from grayflag_dtc.core import settings as S

SCHEMA = [S.Field("A.B", "b", "g", "number", min=1, max=5), S.Field("L.0.x", "x", "g", "int", min=1, max=8),
          S.Field("m", "m", "g", "enum", options=["x", "y"])]
DTC = {"data": {"A": {"B": 2.0}, "L": [{"x": 3}], "m": "x", "other": 1}}


def test_layers_factory_then_saved(tmp_path, monkeypatch):
    fac = tmp_path / "zz.defaults.json"
    fac.write_text('{"A.B": 4, "m": "y"}', encoding="utf-8")
    monkeypatch.setattr(S, "factory_path", lambda airframe: fac)
    assert S.effective_overlay("zz") == {"A.B": 4, "m": "y"}
    S.save_defaults("zz", SCHEMA, {"A.B": 5})
    assert S.effective_overlay("zz") == {"A.B": 5, "m": "y"}
    S.reset_defaults("zz")
    assert S.effective_overlay("zz") == {"A.B": 4, "m": "y"}


def test_apply_and_validate():
    out = S.apply_overlay(DTC, SCHEMA, {"A.B": "3.5", "L.0.x": 7, "m": "y"})
    assert out["data"]["A"]["B"] == 3.5 and out["data"]["L"][0]["x"] == 7 and out["data"]["other"] == 1
    assert DTC["data"]["A"]["B"] == 2.0
    for bad in ({"A.B": 9}, {"L.0.x": "a"}, {"m": "z"}, {"nope": 1}):
        with pytest.raises(ValueError):
            S.apply_overlay(DTC, SCHEMA, bad)


def test_save_rejects_unknown_and_writes_atomically():
    with pytest.raises(ValueError):
        S.save_defaults("zz", SCHEMA, {"nope": 1})
    p = S.save_defaults("zz", SCHEMA, {"A.B": 3})
    assert p.exists() and not p.with_suffix(".tmp").exists()


def test_never_invents_structure():
    with pytest.raises(KeyError):
        S.set_path({"data": {}}, "A.B", 1)
