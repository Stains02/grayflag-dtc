"""Airframe plugin contract (docs/DESIGN.md, "Plugin interface")."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Point:
    index: int                  # 1-based order in this DTC
    lat: float
    lon: float
    elev_m: float
    x: float                    # DCS map x (north), meters: AH-64D files use this, not lat/lon
    y: float                    # DCS map y (east), meters
    code: str | None            # resolved CP code
    name: str                   # in-game CP name (logs and UI only)
    objective_id: str
    cp_id: str = ""


def site_points(sites, start: int) -> list[Point]:
    """Enemy QRF / supply bases as plain points (code QRF or SUP, name = the base) numbered from `start`."""
    return [Point(index=start + i, lat=0.0, lon=0.0, elev_m=s.elev_m, x=s.x, y=s.y, code=s.text, name=s.name, objective_id="")
            for i, s in enumerate(sites)]


@dataclass
class AirfieldPoint:
    """An airfield offered to an airframe that lists reference points (F-16C destinations)."""
    name: str
    code: str
    elev_m: float
    x: float
    y: float
    spawn: bool                 # has player slots for this airframe
    distance_m: float           # to the nearest selected CP


@dataclass
class BuildOptions:
    airframe_config: dict
    theater: str
    name: str = ""              # DTC name shown in the cockpit list (file stem)
    airfields: list | None = None   # AirfieldPoint list, spawn airfields first then nearest first
    farps: list | None = None       # FarpPoint list (core.farps), best first
    sites: list | None = None       # SitePoint list (core.sites): enemy QRF / supply bases, nearest first
    spawn_airfields: list | None = None   # SpawnAirfield list (core.spawn): airfields with slots for this airframe


class AirframePlugin(Protocol):
    id: str
    display_name: str
    supports_labels: bool

    def settings_schema(self) -> list: ...   # list[app.core.settings.Field]
    def build(self, template: dict, points: list[Point], opts: BuildOptions) -> dict: ...
    def validate(self, dtc: dict) -> list[str]: ...
