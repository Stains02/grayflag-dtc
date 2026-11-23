"""F-16C plugin. Layout verified against a DTC exported from DCS (tests/fixtures/f16c/F-16CM_bl50_ref.dtc) and
CoreMods/aircraft/F-16C/DTC/MPD/{NAV_PTS,DEST}.lua.

data.MPD.NAV_PTS   steerpoints 1-25 (STPT<n>), no text label; x/y = DCS map meters, alt = meters
data.MPD.DEST      destinations 81-99 (DEST<n>, number 1-19), 3-char `text` label shown in the cockpit
data.COMM.COMM1    UHF channels 1-20 {freq MHz, modulation 1=AM 2=FM}; COMM2 = VHF (FM 30-87.975, AM 116-155.975)

NAV points are all placed on route 1 (R1): the HSD only draws steerpoints that belong to a route.
Capture points fill the steerpoints (nearest-neighbor order, at most 25). Destinations 81-99 hold airfields only:
those with F-16 player slots first, then the nearest to the selection. Capture points never overflow into destinations. NAV points have no label, so the
CP code goes in their editor-only `note`; the web preview maps code -> CP name.
"""
from __future__ import annotations

import copy
import math
import re

from ..core.settings import Field
from .base import AirframePlugin, BuildOptions, Point, site_points

NAV_MAX, DEST_MAX = 25, 19
TEXT_RE = re.compile(r"^[A-Z0-9]{1,3}$")
FM_MAX, AM_MIN = 87.975, 116.0


def _nav_entry(n: int, p: Point, note: str) -> dict:
    return {
        "alt": p.elev_m, "altitudeType": 1, "FIX_Time": False,
        "id": f"STPT{n}", "idOA1": f"OA1{n}", "idOA1_Line": f"OA1{n}Line",
        "idOA2": f"OA2{n}", "idOA2_Line": f"OA2{n}Line",
        "isOAP_1": False, "isOAP_2": False, "isTOSEnabled": False, "note": note, "number": n,
        "OAP_1_Alt": 0, "OAP_1_Bearing": 0, "OAP_1_DeltaX": 0, "OAP_1_DeltaY": 0, "OAP_1_Range": 0,
        "OAP_1_X": 0, "OAP_1_Y": 0,
        "OAP_2_Alt": 0, "OAP_2_Bearing": 0, "OAP_2_DeltaX": 0, "OAP_2_DeltaY": 0, "OAP_2_Range": 0,
        "OAP_2_X": 0, "OAP_2_Y": 0,
        "R1": True, "R2": False, "R3": False, "routeAltitude": 2000, "speed": 790, "TOS": -1,
        "type": "STPT", "velocityType": 3, "x": p.x, "y": p.y,
    }


class F16C:
    id = "f16c"
    display_name = "F-16C"
    supports_labels = True
    airfield_spawn_types = ("F-16C_50",)

    def free_dest_slots(self, n_points: int, cfg: dict) -> int:
        """Destinations 81-99 are for airfields only; capture points never spill into them."""
        return cfg.get("dest_slots", DEST_MAX)

    def airfield_labels(self, n_points: int, cfg: dict) -> list[str]:
        return [f"DEST {81 + i}" for i in range(self.free_dest_slots(n_points, cfg))]

    def build(self, template: dict, points: list[Point], opts: BuildOptions) -> dict:
        cfg = opts.airframe_config
        nav_max = cfg.get("nav_slots", NAV_MAX)
        if len(points) > nav_max:
            raise ValueError(f"{len(points)} points do not fit steerpoints 1-{nav_max}")
        points = points + site_points((opts.sites or [])[: max(0, nav_max - len(points))], len(points) + 1)   # QRF/supply follow the CPs
        dtc = copy.deepcopy(template)
        mpd = dtc["data"]["MPD"]
        note_max = cfg.get("note_max_len", 24)
        mpd["NAV_PTS"] = [_nav_entry(i + 1, p, f"{p.code or ''} {p.name}".strip()[:note_max])
                          for i, p in enumerate(points)]
        mpd["DEST"] = []
        for af in (opts.airfields or [])[: self.free_dest_slots(len(points), cfg)]:
            n = len(mpd["DEST"]) + 1
            mpd["DEST"].append({"alt": af.elev_m, "id": f"DEST{80 + n}", "note": af.name[:note_max], "number": n,
                                "text": af.code.upper()[:3], "x": af.x, "y": af.y})
        mpd["mirror_NAV_PTS"] = False       # keep our points; do not re-sync from the mission editor
        mpd["mirror_DEST"] = False
        if "terrain" in dtc["data"]:
            mpd["terrain"] = dtc["data"]["terrain"]
        # VHF (COMM2) modulation follows the frequency: 30-87.975 FM (2), 116-155.975 AM (1). UHF is AM.
        for ch in dtc["data"]["COMM"]["COMM2"].values():
            ch["modulation"] = 2 if ch["freq"] <= FM_MAX else 1
        if opts.name:
            dtc["name"] = opts.name
            dtc["data"]["name"] = opts.name
        return dtc

    def slot_label(self, index: int, cfg: dict) -> str:
        return f"STPT {index}"

    def extras_labels(self, n_used: int, cfg: dict) -> list[str]:
        return [f"STPT {n_used + 1 + i}" for i in range(max(0, cfg.get("nav_slots", NAV_MAX) - n_used))]

    def settings_schema(self) -> list[Field]:
        fields: list[Field] = []
        for radio, col, lo, hi in (("COMM1", "COM1", 225, 399.975), ("COMM2", "COM2", 30, 155.975)):
            for i in range(1, 21):
                fields.append(Field(f"COMM.{radio}.Channel_{i}.freq", f"{col} channel {i} (MHz)", "Radios",
                                    "number", min=lo, max=hi, sub=col, row=str(i)))
        cm = (("BQ", "BurstQuantity", "int", 99), ("BI", "BurstInterval", "number", 10),
              ("SQ", "SalvoQuantity", "int", 99), ("SI", "SalvoInterval", "number", 10))
        for kind in ("Chaff", "Flare"):
            for short, key, typ, hi in cm:
                for n in range(1, 7):
                    fields.append(Field(f"MPD.CMDS.CMDSProgramSettings.MAN{n}.{kind}.{key}", f"{kind} {short} {n}",
                                        "Countermeasures", typ, min=0, max=hi, sub=str(n), row=short, block=kind))
        return fields

    def validate(self, dtc: dict) -> list[str]:
        errs: list[str] = []
        try:
            mpd = dtc["data"]["MPD"]
            nav, dest = mpd["NAV_PTS"], mpd["DEST"]
            vhf = dtc["data"]["COMM"]["COMM2"]
        except KeyError as e:
            return [f"missing {e}"]
        if len(nav) > NAV_MAX:
            errs.append(f"{len(nav)} steerpoints exceed NAV 1-{NAV_MAX}")
        if len(dest) > DEST_MAX:
            errs.append(f"{len(dest)} destinations exceed 81-{80 + DEST_MAX}")
        for i, p in enumerate(nav, 1):
            if p["number"] != i or p["id"] != f"STPT{i}":
                errs.append(f"steerpoint {i}: bad number/id")
        for i, p in enumerate(dest, 1):
            if p["number"] != i or p["id"] != f"DEST{80 + i}":
                errs.append(f"destination {i}: bad number/id")
            if not TEXT_RE.match(p["text"]):
                errs.append(f"DEST{80 + i}: label {p['text']!r} must be 1-3 characters A-Z/0-9")
        for p in nav + dest:
            if not all(isinstance(p[k], (int, float)) and math.isfinite(p[k]) for k in ("x", "y", "alt")):
                errs.append(f"{p['id']}: non-finite coordinate")
        for name, ch in vhf.items():
            if FM_MAX < ch["freq"] < AM_MIN:
                errs.append(f"VHF {name} {ch['freq']} MHz is in the unusable gap 88-116")
        return errs


PLUGIN: AirframePlugin = F16C()
