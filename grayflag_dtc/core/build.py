"""Build a DTC from a server, an airframe and an ordered objective list. Shared by the CLI and the web app."""
from __future__ import annotations

import json
from pathlib import Path

from ..airframes import registry
from ..airframes.base import BuildOptions
from .codes import CodeConfig, load_overrides
from . import servers
from .dataset import load_one
from .selection import build_selection
from .settings import apply_overlay, effective_overlay


def sites_range(cfg: dict, qrf_supply: bool | None) -> float | None:
    """Range for enemy QRF/supply bases, or None when they are switched off (None = the airframe's default)."""
    on = cfg.get("sites_default", False) if qrf_supply is None else qrf_supply
    return (cfg.get("sites_range_nm") or 25.0) if on else None


class BuildError(ValueError):
    pass


def terrain_for(server_id: str, theater: str) -> str:
    s = servers.find_server(server_id) or {}
    return s.get("terrain") or theater


def build(server_id: str, airframe: str, objectives: list[str], template: Path | None = None, name: str = "",
          settings: dict | None = None, use_saved_settings: bool = True, qrf_supply: bool | None = None) -> tuple[dict, object]:
    ds = load_one(server_id)
    plugin = registry.plugins()[airframe]
    cfg = registry.config(airframe)
    tpl_path = template or registry.template_path(cfg, ds.theater)
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))
    tpl["data"]["terrain"] = terrain_for(server_id, ds.theater)
    overlay = dict(effective_overlay(airframe)) if use_saved_settings else {}
    overlay.update(settings or {})
    tpl = apply_overlay(tpl, plugin.settings_schema(), overlay)
    ccfg = CodeConfig.load(max_len=cfg.get("label_max_len", 3))
    sel = build_selection(ds, objectives, capacity=cfg.get("capacity"), labels=plugin.supports_labels,
                          code_cfg=ccfg, overrides=load_overrides(server_id),
                          spawn_types=getattr(plugin, "airfield_spawn_types", None),
                          spawns_per_objective=cfg.get("spawns_per_objective", 0),
                          sites_range_nm=sites_range(cfg, qrf_supply),
                          heli_spawn_types=getattr(plugin, "spawn_types", None),
                          spawn_range_nm=cfg.get("spawn_range_nm", 60.0))
    dtc = plugin.build(tpl, sel.points, BuildOptions(cfg, ds.theater, name=name, airfields=sel.airfields, farps=sel.farps, sites=sel.sites,
                                                                  spawn_airfields=sel.spawn_airfields))
    errs = plugin.validate(dtc)
    if errs:
        raise BuildError("validation failed:\n  " + "\n  ".join(errs))
    json.loads(json.dumps(dtc))   # must re-parse
    return dtc, sel
