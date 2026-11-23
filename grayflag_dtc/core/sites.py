"""Enemy QRF and supply bases near the chosen objectives (Grayflag `qrf` and `supply` zones).

For each chosen objective the nearest QRF base and the nearest supply base are offered, unless they are farther away than
`max_nm` nautical miles. QRF and supply bases are usually paired and close together, but not always, so they are picked
separately. They are enemy positions, so the Apache draws them as enemy-unit control measures labelled QRF and SUP.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .dataset import Dataset, Objective, Site
from .farps import centroid

SITE_TEXT = {"qrf": "QRF", "supply": "SUP"}
NM = 1852.0


@dataclass
class SitePoint:
    kind: str                  # qrf | supply
    text: str                  # QRF | SUP: the 3-character label
    name: str
    elev_m: float
    x: float
    y: float
    objectives: list[str] = field(default_factory=list)
    distance_m: float = 0.0    # to the nearest chosen objective it was picked for


def still_matters(site: Site, o: Objective, selected_by_lane: dict[str, list[int]]) -> bool:
    """A site belongs to objective number `lim` of its lattice; once the front has moved past that objective it no longer
    matters. On the objective's own lattice that is `lim >= active objective`. For a site of another lattice the program
    knows the front only if an objective of that lattice was picked; if not, the site is kept."""
    if site.lane == o.lane:
        return site.lim >= o.seq
    seqs = selected_by_lane.get(site.lane)
    return True if not seqs else any(q <= site.lim for q in seqs)


def rank_sites(ds: Dataset, objectives: list[Objective], max_nm: float = 25.0) -> list[SitePoint]:
    """Nearest QRF and nearest supply base per chosen objective within `max_nm` that the front has not passed yet,
    merged, nearest first."""
    if not ds.sites or not objectives:
        return []
    by_lane: dict[str, list[int]] = {}
    for o in objectives:
        by_lane.setdefault(o.lane, []).append(o.seq)
    chosen: dict[str, SitePoint] = {}
    for o in objectives:
        cx, cy = centroid(o)
        for kind in SITE_TEXT:
            cands = [(math.hypot(s.x - cx, s.y - cy), s) for s in ds.sites
                     if s.kind == kind and still_matters(s, o, by_lane)]
            if not cands:
                continue
            d, s = min(cands, key=lambda t: (t[0], t[1].name))
            if d > max_nm * NM:
                continue
            sp = chosen.get(s.id)
            if sp is None:
                chosen[s.id] = SitePoint(kind, SITE_TEXT[kind], s.name, s.elev_m, s.x, s.y, [o.label], d)
            else:
                sp.objectives.append(o.label)
                sp.distance_m = min(sp.distance_m, d)
    return sorted(chosen.values(), key=lambda p: (p.distance_m, p.kind, p.name))
