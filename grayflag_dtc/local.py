"""Things that only make sense on the machine that runs DCS: finding Saved Games\\DCS, writing DTCs into it, listing
tracks, reading dcs.log."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .paths import data_dir

KEEP_LAST = 10
PREFIX = "GF_"


def _config_path() -> Path:
    return data_dir() / "local.json"


def _read_config() -> dict:
    p = _config_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def candidates() -> list[Path]:
    """Saved Games\\DCS* folders that look like a DCS profile, most recently used first."""
    sg = Path(os.environ.get("GFDTC_SAVED_GAMES") or (Path.home() / "Saved Games"))
    if not sg.is_dir():
        return []
    found = []
    for d in sg.iterdir():
        if d.is_dir() and d.name.upper().startswith("DCS") and ((d / "Config").is_dir() or (d / "Logs").is_dir()):
            log = d / "Logs" / "dcs.log"
            found.append((log.stat().st_mtime if log.exists() else d.stat().st_mtime, d))
    return [d for _, d in sorted(found, reverse=True)]


def dcs_dir() -> Path | None:
    """The DCS profile folder: GFDTC_DCS_DIR, else the one saved in the UI, else the most recently used one."""
    for chosen in (os.environ.get("GFDTC_DCS_DIR"), _read_config().get("dcs_dir")):
        if chosen and Path(chosen).is_dir():
            return Path(chosen)
    c = candidates()
    return c[0] if c else None


def set_dcs_dir(path: str | None) -> None:
    cfg = _read_config()
    if path:
        if not Path(path).is_dir():
            raise ValueError(f"{path} is not a folder")
        cfg["dcs_dir"] = path
    else:
        cfg.pop("dcs_dir", None)
    _config_path().parent.mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def dtc_dir(subfolder: str = "") -> Path | None:
    d = dcs_dir()
    return None if d is None else d / "DTC" / subfolder if subfolder else d / "DTC"


def deliver(text: str, filename: str, subfolder: str = "", keep_last: int = KEEP_LAST) -> tuple[Path, int]:
    """Write filename into the DCS DTC folder (tmp then rename, so DCS never sees half a file) and prune old GF_ files.
    Returns (path, number of old files removed)."""
    folder = dtc_dir(subfolder)
    if folder is None:
        raise FileNotFoundError("DCS folder not found; set it in the page footer")
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / filename
    tmp = folder / (filename + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(final)
    mine = sorted((f for f in folder.glob(f"{PREFIX}*.dtc") if f != final), key=lambda f: f.stat().st_mtime, reverse=True)
    removed = 0
    for old in mine[max(0, keep_last - 1):]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return final, removed


def track_dirs() -> list[Path]:
    d = dcs_dir()
    return [] if d is None else [d / "Tracks" / "Multiplayer", d / "Tracks", d / "Missions"]


def list_tracks() -> list[dict]:
    seen, out = set(), []
    for folder in track_dirs():
        if not folder.is_dir():
            continue
        for f in folder.glob("*.trk") if folder.name != "Missions" else folder.glob("*.miz"):
            if f not in seen:
                seen.add(f)
                st = f.stat()
                out.append({"path": str(f), "name": f.name, "mtime": st.st_mtime, "mb": round(st.st_size / 1e6, 1)})
    return sorted(out, key=lambda t: -t["mtime"])


def harvest_dir() -> Path:
    d = dcs_dir()
    if d is None:
        raise FileNotFoundError("DCS folder not found; set it in the page footer")
    return d / "Missions" / "Harvest"


def log_path() -> Path:
    d = dcs_dir()
    if d is None:
        raise FileNotFoundError("DCS folder not found; set it in the page footer")
    return d / "Logs" / "dcs.log"
