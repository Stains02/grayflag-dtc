"""F/A-18C plugin: waypoints only (WP 1-58, WP 59 left free: it is the default air-to-air waypoint).

Layout verified against a DTC exported from DCS (tests/fixtures/fa18c/FA-18C_ref.dtc) and
CoreMods/aircraft/FA-18C/DTC/WYPT/WYPT_NAV.lua. The waypoints are `data.WYPT.NAV_PTS[]`, each
{ id "STPT<n>", wypt_num n, x, y (DCS map meters), alt (meters), note, text_note, R1/R2/R3 route flags, ... }.
Hornet waypoints have no text label in the cockpit, so the capture point code goes in `note` (shown in the DTC editor's
table) and `text_note` (shown on the editor's map); the page's preview maps code -> capture point name.
No routes (sequences) are written: the waypoints are simply 1..N in nearest-neighbour order. Nothing else is exposed
yet; the rest of the DTC (radios, countermeasures, ...) comes from the base template unchanged.
"""
from __future__ import annotations

import copy
import math
import re

from ..core.settings import Field
from .base import AirframePlugin, BuildOptions, Point, site_points

WP_MAX = 58
TEXT_MAX = 24


def _waypoint(n: int, p: Point, note_max: int) -> dict:
    label = f"{p.code or ''} {p.name}".strip()[:note_max]
    return {
        "alt": round(p.elev_m, 1), "altitudeType": 1, "id": f"STPT{n}", "idOA": f"OA{n}", "idOA_Line": f"OA{n}Line",
        "isOA": False, "note": label, "OA_Alt": 0, "OA_Bearing": 0, "OA_Bearing_Units": 1, "OA_DeltaX": 0, "OA_DeltaY": 0,
        "OA_Elevation_Units": 1, "OA_Range": 0, "OA_Range_Units": 1, "OA_X": 0, "OA_Y": 0,
        "R1": False, "R2": False, "R3": False, "text_note": (p.code or "")[:3], "velocityType": 3, "wypt_num": n,
        "x": p.x, "y": p.y,
    }


class FA18C:
    id = "fa18c"
    display_name = "F/A-18C"
    supports_labels = True

    def slot_label(self, index: int, cfg: dict) -> str:
        return f"WP {index}"

    def build(self, template: dict, points: list[Point], opts: BuildOptions) -> dict:
        cfg = opts.airframe_config
        cap = cfg.get("capacity", WP_MAX)
        if len(points) > cap:
            raise ValueError(f"{len(points)} points do not fit waypoints 1-{cap}")
        points = points + site_points((opts.sites or [])[: max(0, cap - len(points))], len(points) + 1)   # QRF/supply follow the CPs
        dtc = copy.deepcopy(template)
        wypt = dtc["data"]["WYPT"]
        note_max = cfg.get("note_max_len", TEXT_MAX)
        wypt["NAV_PTS"] = [_waypoint(i + 1, p, note_max) for i, p in enumerate(points)]
        wypt["mirror_NAV_PTS"] = False                      # keep ours; do not re-sync from the mission editor
        if "terrain" in dtc["data"]:
            wypt["terrain"] = dtc["data"]["terrain"]
        if opts.name:
            dtc["name"] = opts.name
            dtc["data"]["name"] = opts.name
        return dtc

    def extras_labels(self, n_used: int, cfg: dict) -> list[str]:
        return [f"WP {n_used + 1 + i}" for i in range(max(0, cfg.get("capacity", WP_MAX) - n_used))]

    def settings_schema(self) -> list[Field]:
        return []

    def validate(self, dtc: dict) -> list[str]:
        errs: list[str] = []
        try:
            pts = dtc["data"]["WYPT"]["NAV_PTS"]
        except KeyError as e:
            return [f"missing {e}"]
        if len(pts) > 59:
            errs.append(f"{len(pts)} waypoints exceed WP 1-59")
        for i, p in enumerate(pts, 1):
            if p["wypt_num"] != i or p["id"] != f"STPT{i}":
                errs.append(f"waypoint {i}: bad number/id")
            if not all(isinstance(p[k], (int, float)) and math.isfinite(p[k]) for k in ("x", "y", "alt")):
                errs.append(f"{p['id']}: non-finite coordinate")
        return errs


PLUGIN: AirframePlugin = FA18C()
