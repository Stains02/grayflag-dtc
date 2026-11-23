"""Which bases spawn aircraft dynamically, read from a track (no DCS needed).

A DCS mission's `warehouses` section holds, per airbase and per FARP static, whether *dynamic spawn* is on (players can
spawn without a pre-placed slot), who owns it, and the stock per aircraft type (`initialAmount`, `unlimited`, or the
warehouse-wide `unlimitedAircrafts`). A FARP's warehouse id is the unit id of one of its invisible pads, so the pad's
name and position (from the mission's static units) say which FARP it is. Only bases with dynamic spawn on and at least
one aircraft type in stock are kept.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from .inject import child_tables, find_table, lua_table_end


def _flag(text: str, key: str) -> bool | None:
    m = re.search(r'\["%s"\]\s*=\s*(true|false)' % key, text)
    return None if m is None else m.group(1) == "true"


def _in_stock(entry: str) -> list[str]:
    """Helicopter types a warehouse entry can spawn dynamically: in stock, or everything when the warehouse is unlimited."""
    all_unlimited = _flag(entry, "unlimitedAircrafts") is True
    acr = find_table(entry, "aircrafts")
    if not acr:
        return []
    out = set()
    # walk the category tables by hand: each child is ["Type"] = { initialAmount, unlimited, ... }
    for co, cc in child_tables(entry, *acr):
        if not re.search(r'\["helicopters"\]\s*=\s*$', entry[max(0, co - 40):co]):
            continue                                              # helicopters only: that is what spawns at FARPs
        pos = co + 1
        while pos < cc:
            m = re.compile(r'\["([^"]+)"\]\s*=\s*\{').search(entry, pos, cc)
            if not m:
                break
            o = m.end() - 1
            c = lua_table_end(entry, o)
            body = entry[o:c + 1]
            amt = re.search(r'\["initialAmount"\]\s*=\s*(\d+)', body)
            unl = _flag(body, "unlimited") is True
            if all_unlimited or unl or (amt and int(amt.group(1)) > 0):
                out.add(m.group(1))
            pos = c + 1
    return sorted(out)


def _entries(warehouses: str, key: str) -> dict[int, str]:
    tbl = find_table(warehouses, key)
    if not tbl:
        return {}
    out = {}
    for o, c in child_tables(warehouses, *tbl):
        before = warehouses[max(0, o - 60):o]
        m = re.search(r"\[(\d+)\]\s*=\s*$", before)
        if m:
            out[int(m.group(1))] = warehouses[o:c + 1]
    return out


def _field(unit: str, key: str, number: bool = False):
    if number:
        m = re.search(r'\["%s"\]\s*=\s*(-?[\d.]+(?:e[+-]?\d+)?)' % key, unit)
        return float(m.group(1)) if m else None
    m = re.search(r'\["%s"\]\s*=\s*"((?:\\.|[^"\\])*)"' % key, unit)
    return m.group(1).replace('\\"', '"').replace("\\\\", "\\") if m else None


def _static_units(mission: str, wanted: set[int]) -> dict[int, dict]:
    """unitId -> {name, group, type, x, y} for the static units whose id is in `wanted`."""
    found: dict[int, dict] = {}
    for m in re.finditer(r'\["static"\]\s*=\s*\{', mission):
        o = m.end() - 1
        c = lua_table_end(mission, o)
        grp_tbl = find_table(mission, "group", o, c)
        if not grp_tbl:
            continue
        for go, gc in child_tables(mission, *grp_tbl):
            gtext = mission[go:gc + 1]
            units = find_table(gtext, "units")
            if not units:
                continue
            gname = None
            tail = gtext[units[1] + 1:]
            gname = _field(tail, "name") or _field(gtext[:units[0]], "name")
            for uo, uc in child_tables(gtext, *units):
                u = gtext[uo:uc + 1]
                uid = _field(u, "unitId", number=True)
                if uid is not None and int(uid) in wanted:
                    found[int(uid)] = {"name": _field(u, "name"), "group": gname, "type": _field(u, "type"),
                                       "x": _field(u, "x", True), "y": _field(u, "y", True)}
    return found


def extract(warehouses: str, mission: str) -> list[dict]:
    airports = _entries(warehouses, "airports")
    statics = _entries(warehouses, "warehouses")
    keep: list[tuple[str, int, str, list[str]]] = []
    for kind, tbl in (("airport", airports), ("static", statics)):
        for wid, entry in tbl.items():
            if _flag(entry, "dynamicSpawn") is not True:
                continue
            types = _in_stock(entry)
            if types:
                coal = (re.search(r'\["coalition"\]\s*=\s*"([^"]+)"', entry) or [None, ""])[1].lower()
                keep.append((kind, wid, coal, types))
    units = _static_units(mission, {w for k, w, _, _ in keep if k == "static"})
    out = []
    for kind, wid, coal, types in keep:
        row = {"kind": kind, "id": wid, "coalition": coal, "types": types}
        if kind == "static":
            u = units.get(wid)
            if not u or u["x"] is None:
                continue                                   # a warehouse with no unit in the mission: nothing to place
            row.update({"name": u["group"] or u["name"], "unit_type": u["type"], "x": round(u["x"], 1), "y": round(u["y"], 1)})
        out.append(row)
    return sorted(out, key=lambda r: (r["kind"], str(r.get("name", "")), r["id"]))


def extract_from_track(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "warehouses" not in names or "mission" not in names:
            raise ValueError(f"{Path(path).name} has no warehouses or mission file")
        return extract(z.read("warehouses").decode("utf-8", "replace"), z.read("mission").decode("utf-8", "replace"))
