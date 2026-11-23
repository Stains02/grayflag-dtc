"""Plugin discovery. An airframe is offered for a theater only when its plugin exists, its config is enabled,
capacity and DTC subfolder are set, and a template for that theater is present."""
from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path

from . import __name__ as _pkg
from ..paths import RES
from .base import AirframePlugin

_SKIP = {"base", "registry"}
# Listed explicitly as well as discovered: a frozen exe cannot always list the modules inside itself.
# A new airframe is one module with a PLUGIN attribute: add its name here and a config/airframes/<id>.json.
_KNOWN = ("ah64d", "f16c", "fa18c")


def plugins() -> dict[str, AirframePlugin]:
    out: dict[str, AirframePlugin] = {}
    pkg = importlib.import_module(_pkg)
    names = list(_KNOWN) + [m.name for m in pkgutil.iter_modules(pkg.__path__) if m.name not in _SKIP and m.name not in _KNOWN]
    for name in names:
        mod = importlib.import_module(f"{_pkg}.{name}")
        plugin = getattr(mod, "PLUGIN", None)
        if plugin is not None:
            out[plugin.id] = plugin
    return out


def config(airframe_id: str) -> dict:
    return json.loads((RES / "config" / "airframes" / f"{airframe_id}.json").read_text(encoding="utf-8"))


def template_path(cfg: dict, theater: str) -> Path:
    return RES / cfg["template"].replace("{theater}", theater)


def not_ready_reasons(airframe_id: str, theater: str) -> list[str]:
    """Why an airframe cannot be offered for this theater (empty list = ready)."""
    if airframe_id not in plugins():
        return ["no plugin"]
    try:
        cfg = config(airframe_id)
    except FileNotFoundError:
        return ["no config"]
    why = []
    if not cfg.get("enabled"):
        why.append("disabled in config")
    if cfg.get("capacity") is None:
        why.append("capacity not set")
    if cfg.get("dcs_dtc_subfolder") is None:   # "" means the DTC folder itself
        why.append("DTC subfolder not set")
    if not template_path(cfg, theater).exists():
        why.append(f"no template for {theater}")
    return why
