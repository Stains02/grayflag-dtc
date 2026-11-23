"""Dataset loading: servers.json + data/theaters/<id>.json -> typed objects."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import servers



@dataclass
class CP:
    id: str
    name: str
    lat: float
    lon: float
    elev_m: float
    x: float            # DCS map x (north), meters
    y: float            # DCS map y (east), meters
    radius_m: float | None = None
    shape: str = "circle"


@dataclass
class Objective:
    id: str
    lane: str
    seq: int
    name: str
    placeholder: bool
    lat: float
    lon: float
    cps: list[CP] = field(default_factory=list)

    @property
    def code(self) -> str:
        """Short selection code as typed by the user: A16."""
        return f"{self.lane}{self.seq}"

    @property
    def label(self) -> str:
        """Display form of the code, two digits minimum: A01, B05, A16."""
        return f"{self.lane}{self.seq:02d}"


@dataclass
class Airfield:
    id: object
    name: str
    kind: str                       # airdrome | helipad
    lat: float
    lon: float
    elev_m: float
    x: float                        # DCS map x (north), meters
    y: float                        # DCS map y (east), meters
    slots: dict[str, int] = field(default_factory=dict)   # player-slot aircraft types here -> count


@dataclass
class Farp:
    id: str
    name: str
    lane: str
    avail: int                      # objective number at which it opens on its lattice (0 = from the start)
    lat: float
    lon: float
    elev_m: float
    x: float
    y: float
    template: str | None = None
    convoy: bool = False


@dataclass
class Site:
    """An enemy QRF or supply base."""
    id: str
    kind: str                       # qrf | supply
    name: str
    lane: str
    lim: int                        # objective number it belongs to (it sits at that objective or the next)
    lat: float
    lon: float
    elev_m: float
    x: float
    y: float


@dataclass
class DynSpawn:
    """A base where players can spawn aircraft without a placed slot (dynamic spawn), with what it stocks."""
    kind: str                    # airport | static (a FARP)
    id: int
    name: str
    x: float | None
    y: float | None
    types: list[str]
    coalition: str = "blue"     # red airports flip to blue when the lattice advances past them


@dataclass
class Dataset:
    server_id: str
    server_name: str
    tag: str | None
    theater: str
    lanes: list[str]
    objectives: list[Objective]
    airfields: list[Airfield] = field(default_factory=list)
    harvested_at: str | None = None
    farps: list[Farp] = field(default_factory=list)
    sites: list[Site] = field(default_factory=list)
    dynamic_spawns: list[DynSpawn] = field(default_factory=list)

    def by_id(self) -> dict[str, Objective]:
        return {o.id: o for o in self.objectives}

    def by_code(self) -> dict[str, Objective]:
        return {o.code: o for o in self.objectives}

    def resolve(self, token: str) -> Objective:
        """Accept 'A16', 'a16', the zone id 'OBJA16', or a zero-padded 'A07'."""
        t = token.strip().upper()
        objs = self.by_code()
        if t in objs:
            return objs[t]
        m = re.match(r"^(?:OBJ)?([A-Z]+)0*([0-9]+)$", t)
        if m and f"{m.group(1)}{m.group(2)}" in objs:
            return objs[f"{m.group(1)}{m.group(2)}"]
        ids = self.by_id()
        if t in ids:
            return ids[t]
        raise KeyError(f"unknown objective {token!r} on {self.server_id}")


def parse_dataset(raw: dict, tag: str | None = None) -> Dataset:
    objs = []
    for o in raw["objectives"]:
        cps = [CP(id=c["id"], name=c.get("name") or "", lat=c["lat"], lon=c["lon"], elev_m=c["elev_m"],
                  x=c["dcs"]["x"], y=c["dcs"]["y"], radius_m=c.get("radius_m"), shape=c.get("shape", "circle"))
               for c in o["cps"]]
        objs.append(Objective(id=o["id"], lane=o["lane"], seq=o["seq"], name=o["name"],
                              placeholder=bool(o.get("placeholder")), lat=o["center"]["lat"],
                              lon=o["center"]["lon"], cps=cps))
    afs = [Airfield(id=a["id"], name=a["name"], kind=a.get("kind", "airdrome"), lat=a["lat"], lon=a["lon"],
                    elev_m=a["elev_m"], x=a["dcs"]["x"], y=a["dcs"]["y"], slots=dict(a.get("slots") or {}))
           for a in raw.get("airfields", [])]
    farps = [Farp(id=f["id"], name=f["name"], lane=f["lane"], avail=int(f.get("avail") or 0), lat=f["lat"], lon=f["lon"],
                  elev_m=f["elev_m"], x=f["dcs"]["x"], y=f["dcs"]["y"], template=f.get("template"), convoy=bool(f.get("convoy")))
             for f in raw.get("farps", [])]
    sites = [Site(id=s["id"], kind=s["kind"], name=s["name"], lane=s["lane"], lim=int(s.get("lim") or 0), lat=s["lat"],
                  lon=s["lon"], elev_m=s["elev_m"], x=s["dcs"]["x"], y=s["dcs"]["y"]) for s in raw.get("sites", [])]
    dyn = [DynSpawn(kind=d["kind"], id=int(d["id"]), name=d.get("name") or "", x=d.get("x"), y=d.get("y"), types=list(d["types"]), coalition=d.get("coalition", "blue"))
           for d in raw.get("dynamic_spawns", [])]
    return Dataset(server_id=raw["server_id"], server_name=raw["server_name"], tag=tag, theater=raw["theater"],
                   lanes=list(raw["lanes"]), objectives=objs, airfields=afs, harvested_at=raw.get("harvested_at"), farps=farps, sites=sites, dynamic_spawns=dyn)


def load_servers() -> dict[str, Dataset]:
    """Every enabled server whose dataset file exists."""
    out: dict[str, Dataset] = {}
    for s in servers.enabled_servers():
        path = servers.dataset_path(s)
        if path.exists():
            out[s["id"]] = parse_dataset(json.loads(path.read_text(encoding="utf-8")), tag=s.get("tag"))
    return out


def load_one(server_id: str) -> Dataset:
    s = servers.find_server(server_id)
    if s is None:
        raise KeyError(f"unknown server {server_id!r}")
    return parse_dataset(json.loads(servers.dataset_path(s).read_text(encoding="utf-8")), tag=s.get("tag"))
