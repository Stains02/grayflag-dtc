"""AH-64D plugin: one Control Measure of type EU per CP, labelled with the CP code; then the nearest enemy QRF and supply bases (type EU, labelled QRF/SUP), then the best open FARPs as type FC, then airfields with Apache slots as type AG.

Layout verified against a DTC exported from DCS (tests/fixtures/ah64d/AH-64D_BLK_II_DTC.dtc): points live in
data.NAV.Mission_1.Points.CTRLM.POINTS as {alt (m), id (46 = EU), note, num (51..99), text (3 chars), x, y}
with x/y in DCS map meters. Only that list (and its isEnabled flag) is written; everything else in the
template passes through untouched.
"""
from __future__ import annotations

import copy
import math
import re

from ..core.settings import Field
from .base import AirframePlugin, BuildOptions, Point

FIRST_NUM, LAST_NUM = 51, 99
EU_ID = 46
AIRFIELD_ID = 62            # control measure AG: airfield, general
FARP_FUEL_AMMO_ID = 68      # control measure FC: FARP, fuel and ammunition (every Grayflag FARP has both)
TEXT_RE = re.compile(r"^[A-Z0-9]{1,3}$")


class AH64D:
    id = "ah64d"
    display_name = "AH-64D"
    supports_labels = True
    spawn_types = ("AH-64D_BLK_II",)      # airfields with player slots for this airframe are spawn points

    def build(self, template: dict, points: list[Point], opts: BuildOptions) -> dict:
        cfg = opts.airframe_config
        slot = cfg.get("mission_slot", 1)
        first = cfg.get("first_slot") or FIRST_NUM
        if len(points) > LAST_NUM - first + 1:
            raise ValueError(f"{len(points)} points do not fit control measures C{first}-C{LAST_NUM}")
        dtc = copy.deepcopy(template)
        ctrlm = dtc["data"]["NAV"][f"Mission_{slot}"]["Points"]["CTRLM"]
        ctrlm["POINTS"] = [self._point(p, first + i, cfg) for i, p in enumerate(points)]
        sites = (opts.sites or [])[: self.extras_room(len(points), cfg)]                  # enemy QRF / supply: EU, after the CPs
        for k, sp in enumerate(sites):
            ctrlm["POINTS"].append({"alt": round(sp.elev_m, 1), "id": cfg.get("point_type_id", EU_ID),
                                    "note": sp.name[: cfg.get("note_max_len", 24)], "num": first + len(points) + k,
                                    "text": sp.text, "x": sp.x, "y": sp.y})
        used = len(points) + len(sites)
        for k, fp in enumerate((opts.farps or [])[: self.extras_room(used, cfg)]):          # FARPs only fill what is left
            n = first + used + k
            ctrlm["POINTS"].append({"alt": round(fp.elev_m, 1), "id": cfg.get("farp_type_id", FARP_FUEL_AMMO_ID),
                                    "note": fp.name[: cfg.get("note_max_len", 24)], "num": n,
                                    "text": fp.code.upper()[:3], "x": fp.x, "y": fp.y})
        used += min(len(opts.farps or []), self.extras_room(used, cfg))
        for k, sa in enumerate((opts.spawn_airfields or [])[: self.extras_room(used, cfg)]):    # then airfields with Apache slots
            ctrlm["POINTS"].append({"alt": round(sa.elev_m, 1), "id": cfg.get("airfield_type_id", AIRFIELD_ID),
                                    "note": sa.name[: cfg.get("note_max_len", 24)], "num": first + used + k,
                                    "text": sa.code.upper()[:3], "x": sa.x, "y": sa.y})
        ctrlm["isEnabled"] = bool(points) or ctrlm.get("isEnabled", False)
        if opts.name:
            dtc["name"] = opts.name
            dtc["data"]["name"] = opts.name
        return dtc

    @staticmethod
    def _point(p: Point, num: int, cfg: dict) -> dict:
        mode = cfg.get("note_mode", "name")
        note = "" if mode == "blank" else f"{p.name}"[: cfg.get("note_max_len", 24)]
        return {
            "alt": round(p.elev_m, 1),
            "id": cfg.get("point_type_id", EU_ID),
            "note": note,
            "num": num,
            "text": (p.code or "").upper()[:3],
            "x": p.x,
            "y": p.y,
        }

    def slot_label(self, index: int, cfg: dict) -> str:
        """Cockpit name of the nth point (1-based): control measure C51.."""
        return f"C{(cfg.get('first_slot') or FIRST_NUM) + index - 1}"

    def extras_room(self, n_used: int, cfg: dict) -> int:
        """Control measure slots still free after `n_used` points (capture points first, then QRF/supply, then FARPs)."""
        return max(0, LAST_NUM - (cfg.get("first_slot") or FIRST_NUM) + 1 - n_used)

    farp_room = extras_room

    def extras_labels(self, n_used: int, cfg: dict) -> list[str]:
        first = (cfg.get("first_slot") or FIRST_NUM) + n_used
        return [f"C{first + i}" for i in range(self.extras_room(n_used, cfg))]

    farp_labels = extras_labels

    def settings_schema(self) -> list[Field]:
        """Radios, presets and laser codes. IFF is deliberately not exposed."""
        fields: list[Field] = []
        ranges = {"VHF": (108, 151.975), "UHF": (225, 399.975), "FM1": (30, 87.975), "FM2": (30, 87.975)}
        for r, (lo, hi) in ranges.items():      # one box per radio: 1-10 tunes that preset, larger is a manual MHz
            fields.append(Field(f"Radios.InitialRadioSettings.{r}", f"{r} tune", "Radios", "tune", min=lo, max=hi,
                                sub=r, row="Tune"))
        for i in range(10):
            for r, (lo, hi) in ranges.items():
                fields.append(Field(f"Presets.COMM.{i}.COMMS.{r}.Frequency", f"{r} preset {i + 1} (MHz)", "Radios",
                                    "number", min=lo, max=hi, sub=r, row=f"Preset {i + 1}"))
        for ch in "ABCDEFGHJKLMNPQR":   # DCS skips I and O
            fields.append(Field(f"Laser.ChannelsCodes.{ch}", ch, "Laser Codes", "laser"))
        return fields

    def validate(self, dtc: dict) -> list[str]:
        errs: list[str] = []
        try:
            pts = dtc["data"]["NAV"]["Mission_1"]["Points"]["CTRLM"]["POINTS"]
        except KeyError as e:
            return [f"missing {e}"]
        if len(pts) > LAST_NUM - FIRST_NUM + 1:
            errs.append(f"{len(pts)} control measures exceed the {LAST_NUM - FIRST_NUM + 1} available")
        nums = [p["num"] for p in pts]
        if len(set(nums)) != len(nums):
            errs.append("duplicate point numbers")
        for p in pts:
            if not FIRST_NUM <= p["num"] <= LAST_NUM:
                errs.append(f"point number {p['num']} outside C{FIRST_NUM}-C{LAST_NUM}")
            if p["id"] not in (EU_ID, FARP_FUEL_AMMO_ID, AIRFIELD_ID):
                errs.append(f"C{p['num']}: type id {p['id']} is not EU ({EU_ID}), FARP fuel+ammo ({FARP_FUEL_AMMO_ID}) or airfield ({AIRFIELD_ID})")
            if not TEXT_RE.match(p["text"]):
                errs.append(f"C{p['num']}: label {p['text']!r} must be 1-3 characters A-Z/0-9")
            if not all(isinstance(p[k], (int, float)) and math.isfinite(p[k]) for k in ("x", "y", "alt")):
                errs.append(f"C{p['num']}: non-finite coordinate")
        return errs


PLUGIN: AirframePlugin = AH64D()
