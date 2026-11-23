"""Per-airframe editable settings: schema (declared by the plugin), overlay storage, and applying an overlay.

An overlay is a flat {dotted path inside DTC `data`: value} dict, e.g. "Presets.COMM.0.COMMS.FM1.Frequency": 31.5.
Numeric path parts index lists. Only paths declared in the plugin's schema are ever read or written.
Layers, lowest to highest: the base template, config/airframes/<id>.defaults.json (factory "Grayflag standard"),
data/settings/<id>.json (the user's saved defaults), then per-request changes from the UI.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..paths import RES, data_dir


@dataclass
class Field:
    path: str                       # dotted path inside dtc["data"]
    label: str
    group: str                      # UI section
    type: str = "number"            # number | int | enum | text | laser (4-digit code) | tune (preset 1-10 or MHz)
    options: list | None = None     # enum choices
    min: float | None = None
    max: float | None = None
    sub: str = ""                   # optional sub-group (a radio name, a preset number, a laser channel)
    row: str = ""                   # when set, the group renders as a table: rows = row, columns = sub
    block: str = ""                 # tables only: one captioned table per block


def _split(path: str) -> list[str | int]:
    return [int(p) if p.isdigit() else p for p in path.split(".")]


def get_path(data: dict, path: str):
    cur = data
    for k in _split(path):
        cur = cur[k]
    return cur


def set_path(data: dict, path: str, value) -> None:
    parts = _split(path)
    cur = data
    for k in parts[:-1]:
        cur = cur[k]
    cur[parts[-1]]  # must already exist: we never invent structure inside a DCS file
    cur[parts[-1]] = value


# Apache laser PRF code, typed first digit first. DCS stores it as {Four, Three, Two, One}; limits from ED's
# CoreMods/aircraft/AH-64D/DTC/Weapon/Laser.lua: first digit 1/2/4/5 (never 3), second 1-7, third and fourth 1-8.
LASER_ORDER = ("Four", "Three", "Two", "One")


def laser_code_error(code: str) -> str | None:
    if not (isinstance(code, str) and len(code) == 4 and code.isdigit()):
        return "must be exactly 4 digits"
    a, b, c, d = (int(x) for x in code)
    if a not in (1, 2, 4, 5):
        return "first digit must be 1, 2, 4 or 5"
    if not 1 <= b <= 7:
        return "second digit must be 1-7"
    if not (1 <= c <= 8 and 1 <= d <= 8):
        return "third and fourth digits must be 1-8"
    return None


def laser_to_str(d: dict) -> str:
    return "".join(str(int(d[k])) for k in LASER_ORDER)


PRESET_MODE, MANUAL_MODE = 0, 1          # Apache InitialRadioSettings.<radio>.Mode (ED's RADIOS.lua)


def tune_to_value(d: dict):
    """What the UI shows for an Apache start-up radio: the preset number, or the manual frequency."""
    return d["Preset"] if d["Mode"] == PRESET_MODE else d["Frequency"]


def _apply_tune(data: dict, f: Field, value) -> None:
    """1-10 = tune that preset (frequency, modulation and encryption follow the preset); larger = manual MHz."""
    radio = f.path.rsplit(".", 1)[-1]
    cur = get_path(data, f.path)
    if value <= 10:
        n = int(value)
        pre = get_path(data, f"Presets.COMM.{n - 1}.COMMS.{radio}")
        cur["Mode"], cur["Preset"] = PRESET_MODE, n
        for k in ("Frequency", "Modulation", "Encryption"):
            if k in pre and k in cur:
                cur[k] = pre[k]
    else:
        cur["Mode"], cur["Frequency"] = MANUAL_MODE, value


def _set_value(data: dict, f: Field, value) -> None:
    if f.type == "tune":
        _apply_tune(data, f, value)
    elif f.type == "laser":
        for k, ch in zip(LASER_ORDER, value):
            set_path(data, f"{f.path}.{k}", int(ch))
    else:
        set_path(data, f.path, value)


def coerce(f: Field, value):
    if f.type == "tune":
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{f.label}: {value!r} is not a preset (1-10) or a frequency") from None
        if 1 <= num <= 10:
            if num != int(num):
                raise ValueError(f"{f.label}: presets are whole numbers 1-10")
            return int(num)
        if f.min is not None and num < f.min or f.max is not None and num > f.max:
            raise ValueError(f"{f.label}: {num:g} is neither a preset (1-10) nor a frequency in {f.min}..{f.max} MHz")
        return num
    if f.type == "laser":
        code = str(value).strip()
        err = laser_code_error(code)
        if err:
            raise ValueError(f"Laser code {f.label}: {code!r} {err}")
        return code
    if f.type == "enum":
        if value not in (f.options or []):
            raise ValueError(f"{f.label}: {value!r} not one of {f.options}")
        return value
    if f.type == "text":
        return str(value)
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{f.label}: {value!r} is not a number") from None
    if f.min is not None and num < f.min or f.max is not None and num > f.max:
        raise ValueError(f"{f.label}: {num:g} outside {f.min}..{f.max}")
    return int(num) if f.type == "int" else num


def validate_overlay(schema: list[Field], overlay: dict) -> dict:
    """Coerced overlay; unknown paths and bad values raise ValueError."""
    by = {f.path: f for f in schema}
    out = {}
    for path, v in overlay.items():
        if path not in by:
            raise ValueError(f"unknown setting {path!r}")
        out[path] = coerce(by[path], v)
    return out


def apply_overlay(dtc: dict, schema: list[Field], overlay: dict) -> dict:
    """Return a copy of dtc with the overlay written into dtc['data']."""
    out = copy.deepcopy(dtc)
    by = {f.path: f for f in schema}
    clean = validate_overlay(schema, overlay)
    # start-up tuning reads the presets, so apply it after every other field
    for path in sorted(clean, key=lambda p: by[p].type == "tune"):
        _set_value(out["data"], by[path], clean[path])
    return out


def current_values(dtc: dict, schema: list[Field]) -> dict:
    def one(f):
        v = get_path(dtc["data"], f.path)
        return laser_to_str(v) if f.type == "laser" else tune_to_value(v) if f.type == "tune" else v
    return {f.path: one(f) for f in schema}


def _read(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def factory_path(airframe: str) -> Path:
    return RES / "config" / "airframes" / f"{airframe}.defaults.json"


def saved_path(airframe: str, data: Path | None = None) -> Path:
    return (data or data_dir()) / "settings" / f"{airframe}.json"


def effective_overlay(airframe: str, data: Path | None = None) -> dict:
    return {**_read(factory_path(airframe)), **_read(saved_path(airframe, data))}


def save_defaults(airframe: str, schema: list[Field], overlay: dict, data: Path | None = None) -> Path:
    clean = validate_overlay(schema, overlay)
    p = saved_path(airframe, data)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def reset_defaults(airframe: str, data: Path | None = None) -> None:
    saved_path(airframe, data).unlink(missing_ok=True)
