"""FARPs for the helicopter DTCs: which Grayflag FARPs are open and the closest ones to each chosen objective.

Grayflag's `base` zones carry a lattice letter and an `avail` number. A FARP with avail N sits at objective N-1 (its
own lattice) and opens when that objective is captured, which is exactly when the active objective of the lattice
becomes N. So a FARP is open when avail <= the active objective's number. avail 0 means open from the start.
The program does not know the campaign state, but the selected objective is the active one on its lattice.

Every lattice advances in a fixed order and direction, so the FARPs behind the active objective are where helicopters
are most likely to spawn. `lattice_direction` gives the local direction of advance, used to tell which bases lie behind
an objective. Choosing the spawn points for an objective is in spawn.py.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

from ..paths import RES, data_dir
from .dataset import Dataset, Farp, Objective


@dataclass
class FarpPoint:
    name: str
    code: str
    elev_m: float
    x: float
    y: float
    objectives: list[str] = field(default_factory=list)   # chosen objectives it is one of the closest open FARPs for
    distance_m: float = 0.0                                # to the nearest of them


@lru_cache(maxsize=2)
def _filters(root: str):
    f = RES / "config" / "farp_filters.json"
    raw = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    return (tuple(re.compile(x, re.I) for x in raw.get("exclude_name_regex", [])),
            re.compile(raw["keep_if_name_matches"], re.I) if raw.get("keep_if_name_matches") else None)


def is_farp(f: Farp) -> bool:
    exclude, keep = _filters(str(RES))
    if any(p.search(f.name) for p in exclude):
        return False
    return bool(f.template) or (keep is not None and bool(keep.search(f.name)))


def load_farp_overrides(server_id: str) -> dict[str, str]:
    p = data_dir() / "codes" / f"{server_id}.farps.json"
    return {k: v.upper()[:3] for k, v in json.loads(p.read_text(encoding="utf-8")).items()} if p.exists() else {}


def centroid(o: Objective) -> tuple[float, float]:
    return (sum(c.x for c in o.cps) / len(o.cps), sum(c.y for c in o.cps) / len(o.cps)) if o.cps else (0.0, 0.0)


def open_farps(ds: Dataset, lane: str, active_seq: int) -> list[Farp]:
    return [f for f in ds.farps if is_farp(f) and f.lane == lane and f.avail <= active_seq]


def lattice_direction(ds: Dataset, o: Objective) -> tuple[float, float] | None:
    """Unit vector of the lattice's advance at objective `o`: from the previous objective of the same lattice to `o`
    (or from `o` to the next one for the first objective). None when the lattice has only this objective."""
    lane = sorted((x for x in ds.objectives if x.lane == o.lane and x.cps), key=lambda x: x.seq)
    before = [x for x in lane if x.seq < o.seq]
    after = [x for x in lane if x.seq > o.seq]
    cx, cy = centroid(o)
    if before:
        bx, by = centroid(before[-1])
        dx, dy = cx - bx, cy - by
    elif after:
        ax, ay = centroid(after[0])
        dx, dy = ax - cx, ay - cy
    else:
        return None
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n else None


def is_behind(ds: Dataset, o: Objective, x: float, y: float) -> bool:
    """True when (x, y) lies on the already-captured side of objective `o` along its lattice."""
    d = lattice_direction(ds, o)
    if d is None:
        return True
    cx, cy = centroid(o)
    return (x - cx) * d[0] + (y - cy) * d[1] < 0
