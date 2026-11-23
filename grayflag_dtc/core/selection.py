"""Turn an ordered objective selection into the DTC point list: ordering, codes, capacity."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..airframes.base import AirfieldPoint, Point
from .codes import CodeConfig, _suffix_variants, airfield_code, airfield_excluded, generate_codes, load_airfield_overrides
from .dataset import CP, Dataset
from .farps import FarpPoint, is_behind, load_farp_overrides
from .sites import SitePoint, rank_sites
from .spawn import SpawnAirfield, rank_spawns


class CapacityError(ValueError):
    pass


@dataclass
class Selection:
    points: list[Point]
    capacity: int | None
    used: int
    airfields: list[AirfieldPoint] = field(default_factory=list)   # spawn airfields first, then nearest first
    farps: list[FarpPoint] = field(default_factory=list)           # open FARPs nearest each chosen objective, nearest first
    sites: list[SitePoint] = field(default_factory=list)           # nearest enemy QRF / supply base per chosen objective
    spawn_airfields: list[SpawnAirfield] = field(default_factory=list)   # airfields with slots for this airframe near the objectives

    @property
    def over(self) -> bool:
        return self.capacity is not None and self.used > self.capacity


def distance_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Equirectangular approximation, plenty accurate at objective scale."""
    k = 111_320.0
    dx = (b_lon - a_lon) * k * math.cos(math.radians((a_lat + b_lat) / 2))
    dy = (b_lat - a_lat) * k
    return math.hypot(dx, dy)


def order_cps(cps: list[CP], start: tuple[float, float] | None) -> list[CP]:
    """Nearest-neighbor from the CP closest to `start`, or from the first CP when start is None."""
    left = list(cps)
    if not left:
        return []
    if start is None:
        cur = left.pop(0)
    else:
        cur = min(left, key=lambda c: (distance_m(start[0], start[1], c.lat, c.lon), c.id))
        left.remove(cur)
    out = [cur]
    while left:
        cur = min(left, key=lambda c: (distance_m(cur.lat, cur.lon, c.lat, c.lon), c.id))
        left.remove(cur)
        out.append(cur)
    return out


def _free_code(used: set[str]) -> str:
    """Last resort when a base code and all its suffixed variants are taken: the first unused 3-char A-Z0-9 code."""
    import itertools
    import string
    for t in itertools.product(string.ascii_uppercase + string.digits, repeat=3):
        c = "".join(t)
        if c not in used:
            return c
    raise RuntimeError("no free airfield code")


def rank_airfields(ds: Dataset, points: list[Point], spawn_types: tuple[str, ...], code_cfg: CodeConfig,
                   overrides: dict[str, str] | None = None, kinds: tuple[str, ...] = ("airdrome",),
                   limit: int = 40, objectives: list | None = None) -> list[AirfieldPoint]:
    """Airfields with player slots for `spawn_types` first (nearest to the selection first), then the others: those
    behind a chosen objective along its lattice (where the campaign has already been won) before those ahead of it,
    nearest first within each group. Codes are unique among the airfields."""
    if not ds.airfields:
        return []
    ov = overrides or {}
    used: set[str] = set()      # airfield codes are unique among airfields; sharing a code with a CP is fine
    out: list[AirfieldPoint] = []
    scored = []
    for a in (x for x in ds.airfields if x.kind in kinds and not airfield_excluded(x.name, fixed_wing=True)):
        d = min((math.hypot(a.x - p.x, a.y - p.y) for p in points), default=0.0)
        spawn = any(t in a.slots for t in spawn_types)
        ahead = bool(objectives) and not any(is_behind(ds, o, a.x, a.y) for o in objectives)
        scored.append(((not spawn, ahead and not spawn), d, a.name, a, spawn))
    for _, d, _, a, spawn in sorted(scored, key=lambda t: t[:3])[:limit]:   # codes only for the ones that can matter
        base = ov.get(a.name) or airfield_code(a.name, code_cfg)
        code = base
        if code in used:
            code = next((v for v in _suffix_variants(base, code_cfg) if v not in used), None) or _free_code(used)
        used.add(code)
        out.append(AirfieldPoint(name=a.name, code=code, elev_m=a.elev_m, x=a.x, y=a.y, spawn=spawn, distance_m=d))
    return out


def build_selection(ds: Dataset, objective_tokens: list[str], *, capacity: int | None, labels: bool,
                    code_cfg: CodeConfig | None = None, overrides: dict[str, str] | None = None,
                    enforce_capacity: bool = True, spawn_types: tuple[str, ...] | None = None,
                    airfield_kinds: tuple[str, ...] = ("airdrome",), spawns_per_objective: int = 0,
                    sites_range_nm: float | None = None, heli_spawn_types: tuple[str, ...] | None = None,
                    spawn_range_nm: float = 60.0) -> Selection:
    """objective_tokens in the order picked (A16, b21, OBJD31). Duplicates are ignored."""
    seen: set[str] = set()
    objs = []
    for t in objective_tokens:
        o = ds.resolve(t)
        if o.id not in seen:
            seen.add(o.id)
            objs.append(o)

    total = sum(len(o.cps) for o in objs)
    if enforce_capacity and capacity is not None and total > capacity:
        raise CapacityError(f"{total} capture points selected but this airframe holds {capacity}; "
                            f"remove {total - capacity}")

    codes = generate_codes(ds, code_cfg, overrides) if labels and code_cfg else {}
    points: list[Point] = []
    last: tuple[float, float] | None = None
    for o in objs:
        for cp in order_cps(o.cps, last):
            points.append(Point(index=len(points) + 1, lat=cp.lat, lon=cp.lon, elev_m=cp.elev_m, x=cp.x, y=cp.y,
                                code=codes[o.id][cp.id].code if codes else None, name=cp.name,
                                objective_id=o.id, cp_id=cp.id))
            last = (cp.lat, cp.lon)

    afs = []
    if spawn_types is not None and code_cfg:
        afs = rank_airfields(ds, points, spawn_types, code_cfg, load_airfield_overrides(ds.server_id), airfield_kinds,
                             objectives=objs)
    fps, spawn = [], []
    if spawns_per_objective and code_cfg:
        ov = {**load_farp_overrides(ds.server_id), **load_airfield_overrides(ds.server_id)}
        fps, spawn = rank_spawns(ds, objs, heli_spawn_types or (), code_cfg, spawns_per_objective, spawn_range_nm, ov)
    sites = rank_sites(ds, objs, sites_range_nm) if sites_range_nm else []
    return Selection(points=points, capacity=capacity, used=total, airfields=afs, farps=fps, sites=sites, spawn_airfields=spawn)
