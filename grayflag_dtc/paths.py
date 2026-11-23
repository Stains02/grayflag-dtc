"""Where things live.

* RES  - read-only resources shipped with the program: config/, templates/, the bundled datasets, static files.
         The repo root when run from source, the PyInstaller bundle folder when run as the exe.
* data_dir() - the writable folder: datasets (theaters/), saved settings, scenarios you added, code overrides.
         GFDTC_DATA (or --data) wins; the exe uses %LOCALAPPDATA%\\grayflag-dtc\\data (so it can sit on a desktop or in
         Downloads), or a `data` folder next to itself if you create one (portable use); from source it is `data/` in the repo.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
RES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) if FROZEN else Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """GFDTC_DATA (or --data), else a `data` folder you created next to the exe (portable use),
    else %LOCALAPPDATA%\\grayflag-dtc\\data. From source: data/ in the repo."""
    env = os.environ.get("GFDTC_DATA")
    if env:
        return Path(env)
    if not FROZEN:
        return RES / "data"
    portable = Path(sys.executable).resolve().parent / "data"
    if portable.is_dir():
        return portable
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "grayflag-dtc" / "data"


def _harvested_at(p: Path) -> str:
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("harvested_at") or "")
    except (OSError, ValueError):
        return ""


def seed_data() -> list[str]:
    """Put the datasets bundled with the program into the data folder: when a file is missing, or when the bundled one
    was harvested later than the one there. A copy you harvested yourself that is newer than the bundled one is kept."""
    src, dst = RES / "data" / "theaters", data_dir() / "theaters"
    if not src.is_dir() or src.resolve() == dst.resolve():
        return []
    dst.mkdir(parents=True, exist_ok=True)
    added = []
    for f in sorted(src.glob("*.json")):
        mine = dst / f.name
        if not mine.exists() or _harvested_at(f) > _harvested_at(mine):
            shutil.copy2(f, mine)
            added.append(f.name)
    return added
