"""Where a helicopter can spawn near the chosen objectives: open FARPs and bases with slots for the airframe.

One pool, behind the front first and then nearest first:

* **FARPs** (Grayflag `base` zones). Open when their unlock number is at or below the active objective of their own
  lattice; start FARPs (unlock 0) are open for every lattice (they are the campaign's main bases); a FARP of another
  lattice is also open if you picked an objective there that has reached its unlock number.
* **Bases with player slots** for the airframe (airfields and helipads). The harvest records which aircraft types have
  slots at each airbase, so a base with AH-64D slots is a spawn point by definition, open from the start.

The nearest candidate is always offered, even when it is far; further ones only within `range_nm` (60): a second spawn
point that far away is no use for planning, and airfields are usually that far (hence the FARPs).

Dynamic spawn: most Grayflag scenarios let helicopters spawn at FARPs without placed slots. That is a per-base setting
in the mission's warehouses (dynamic spawn on, helicopter stock), which the harvest reads from the track into the
dataset's `dynamic_spawns`. With that data a FARP zone is a spawn point only if it is a dynamic base stocking the airframe
(or has slots); FARP zones that are just airfield markers (Taftanaz Base, Ramstein) drop out. Without the data every
FARP zone counts.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .codes import CodeConfig, _suffix_variants, airfield_code, airfield_excluded
from .dataset import Dataset, Farp, Objective
from .farps import FarpPoint, centroid, is_behind, is_farp

NM = 1852.0
SAME_PLACE_M = 800.0      # a slot helipad this close to a FARP zone is that FARP
DYN_MATCH_M = 400.0       # a dynamic-spawn pad this close to a FARP zone belongs to it
RED_BASE_M = 8 * 1852.0   # an enemy airport belongs to the objective within this distance
SAME_BASE_M = 3000.0      # an airfield and a FARP zone this close are the same base: offer one


@dataclass
class SpawnAirfield:
    name: str
    code: str
    elev_m: float
    x: float
    y: float
    objectives: list[str] = field(default_factory=list)
    distance_m: float = 0.0


@dataclass
class _Cand:
    kind: str                      # farp | airfield
    key: str
    name: str
    elev_m: float
    x: float
    y: float
    zone: Farp | None = None       # the base zone, if there is one
    slots: bool = False            # the airframe has player slots here: open from the start
    after: tuple[str, int] | None = None   # (lane, seq): an enemy airport that turns blue once that objective is passed
    live: bool = True              # a real spawn point for the airframe


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def _flips_after(ds: Dataset, x: float, y: float) -> tuple[str, int] | None:
    """(lane, seq) of the objective an enemy base belongs to (the nearest, within RED_BASE_M), or None."""
    near = [(math.hypot(centroid(o)[0] - x, centroid(o)[1] - y), o) for o in ds.objectives if o.cps]
    if not near:
        return None
    dist, o = min(near, key=lambda t: t[0])
    return (o.lane, o.seq) if dist <= RED_BASE_M else None


def candidates(ds: Dataset, spawn_types: tuple[str, ...]) -> list[_Cand]:
    """Every base the airframe can spawn at. With dynamic-spawn data (read from the track's warehouses) a FARP zone counts
    only if it is a dynamic-spawn base stocking the airframe, or has player slots; without it, every FARP zone counts."""
    if not spawn_types:
        return [_Cand("farp", "z:" + f.id, f.name, f.elev_m, f.x, f.y, zone=f) for f in ds.farps if is_farp(f)]
    dyn = [d for d in ds.dynamic_spawns if any(t in d.types for t in spawn_types)]
    known = bool(ds.dynamic_spawns)

    def _pad(d, f) -> bool:
        return d.kind == "static" and d.x is not None and (_norm(d.name) == _norm(f.name) or math.hypot(d.x - f.x, d.y - f.y) <= DYN_MATCH_M)

    out: list[_Cand] = []
    for f in ds.farps:
        red_pad = known and any(_pad(d, f) for d in dyn if d.coalition != "blue")
        if not is_farp(f) and not red_pad:                        # an enemy FARP zone ("Red ... FARP") is named like a filtered one
            continue
        c = _Cand("farp", "z:" + f.id, f.name, f.elev_m, f.x, f.y, zone=f, live=not known or any(_pad(d, f) for d in dyn if d.coalition == "blue"))
        if known and not c.live and any(_pad(d, f) for d in dyn if d.coalition != "blue"):
            c.name = re.sub(r"^red\s+", "", f.name, flags=re.I)    # it is ours by the time it is offered
            c.after = _flips_after(ds, f.x, f.y)                  # an enemy FARP: usable once its lattice has passed it
            c.live = c.after is not None
        out.append(c)
    by_id = {a.id: a for a in ds.airfields}
    for d in dyn:
        a = by_id.get(d.id) if d.kind == "airport" else None
        if a is None or airfield_excluded(a.name):
            continue
        c = _Cand("airfield", f"a:{a.id}", a.name, a.elev_m, a.x, a.y, slots=True, live=True)
        if d.coalition != "blue":
            c.after = _flips_after(ds, a.x, a.y)
            if c.after is None:
                continue                                   # not tied to an objective: never opens
        out.append(c)
    seen = {c.key for c in out}
    for a in ds.airfields:
        if not any(t in a.slots for t in spawn_types) or airfield_excluded(a.name) or f"a:{a.id}" in seen:
            continue
        if a.kind == "airdrome":                           # an airfield is its own spawn point, never a FARP zone's twin
            out.append(_Cand("airfield", f"a:{a.id}", a.name, a.elev_m, a.x, a.y, slots=True, live=True))
            continue
        zones = [c for c in out if c.zone]                  # a slot helipad is the FARP zone with its name, else the nearest one
        twin = next((c for c in zones if _norm(c.name) == _norm(a.name)), None)
        if twin is None:
            near = [c for c in zones if math.hypot(c.x - a.x, c.y - a.y) <= SAME_PLACE_M]
            twin = min(near, key=lambda c: math.hypot(c.x - a.x, c.y - a.y)) if near else None
        if twin is not None:
            twin.slots = twin.live = True                  # proven static spawn: open for everyone
        else:
            out.append(_Cand("farp", f"a:{a.id}", a.name, a.elev_m, a.x, a.y, slots=True, live=True))
    return [c for c in out if c.live]


def _open_for(c: _Cand, o: Objective, by_lane: dict[str, list[int]]) -> bool:
    if c.after:                                            # open once an objective beyond its own is chosen on that lattice
        return any(q > c.after[1] for q in by_lane.get(c.after[0], []))
    if c.slots or c.zone is None:
        return True
    f = c.zone
    if f.lane == o.lane:
        return f.avail <= o.seq
    if f.avail == 0:
        return True                                        # a start FARP serves every lattice
    seqs = by_lane.get(f.lane)
    return bool(seqs) and any(q >= f.avail for q in seqs)


def rank_spawns(ds: Dataset, objectives: list[Objective], spawn_types: tuple[str, ...], code_cfg: CodeConfig,
                per_objective: int = 2, range_nm: float = 60.0,
                overrides: dict[str, str] | None = None) -> tuple[list[FarpPoint], list[SpawnAirfield]]:
    """(FARP-type points, airfield points): the `per_objective` best spawn candidates of each chosen objective, merged,
    best first. Capacity trimming later drops from the end of each list."""
    if per_objective <= 0 or not objectives:
        return [], []
    pool = candidates(ds, spawn_types)
    if not pool:
        return [], []
    by_lane: dict[str, list[int]] = {}
    for o in objectives:
        by_lane.setdefault(o.lane, []).append(o.seq)
    chosen: dict[str, tuple[int, _Cand, list[str], float]] = {}
    for o in objectives:
        cx, cy = centroid(o)
        scored = []
        for c in pool:
            if not _open_for(c, o, by_lane):
                continue
            d = math.hypot(c.x - cx, c.y - cy)
            behind = True if (c.zone is not None and not c.slots and c.zone.lane == o.lane) else is_behind(ds, o, c.x, c.y)
            scored.append((not behind, d, c.name, c))
        scored.sort(key=lambda t: t[:3])
        picked: list[_Cand] = []
        for _, d, _, c in scored:                                   # best first; skip an airfield and a FARP at the same place
            if len(picked) >= per_objective:
                break
            if picked and d > range_nm * NM:                        # the nearest is always offered, later ones only near
                continue
            if any(p.kind != c.kind and math.hypot(c.x - p.x, c.y - p.y) <= SAME_BASE_M for p in picked):
                continue
            picked.append(c)
        dist = {c.key: d for _, d, _, c in scored}
        for rank, c in enumerate(picked):
            d = dist[c.key]
            hit = chosen.get(c.key)
            if hit is None:
                chosen[c.key] = (rank, c, [o.label], d)
            else:
                chosen[c.key] = (min(hit[0], rank), c, hit[2] + [o.label], min(hit[3], d))
    ordered = sorted(chosen.values(), key=lambda t: (t[0], t[3], t[1].name))
    ov, used = overrides or {}, set()
    farps: list[FarpPoint] = []
    fields: list[SpawnAirfield] = []
    for _, c, objs, d in ordered:
        base = ov.get(c.name) or airfield_code(c.name, code_cfg)
        code = base if base not in used else next((v for v in _suffix_variants(base, code_cfg) if v not in used), base)
        used.add(code)
        if c.kind == "farp":
            farps.append(FarpPoint(c.name, code, c.elev_m, c.x, c.y, objs, d))
        else:
            fields.append(SpawnAirfield(c.name, code, c.elev_m, c.x, c.y, objs, d))
    return farps, fields
