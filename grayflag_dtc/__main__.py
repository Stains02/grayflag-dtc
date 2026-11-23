"""Command line: `grayflag-dtc` (the exe) or `python -m grayflag_dtc`.

    grayflag-dtc                       serve the web page on localhost and open the browser (default)
    grayflag-dtc serve [--port N] [--no-browser] [--data DIR]
    grayflag-dtc prepare TRACK --id ID [--name N] [--tag T]    harvest step 1: write the harvest mission
    grayflag-dtc collect ID [--log FILE] [--force]             harvest step 2: read dcs.log, write the dataset
    grayflag-dtc build SERVER AIRFRAME OBJ... --out FILE       build one DTC without the web page
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import __version__


def _free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 50)):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("no free port found")


def cmd_serve(a) -> int:
    import uvicorn

    from . import paths
    from .server import app

    added = paths.seed_data()
    port = _free_port(a.port)
    url = f"http://127.0.0.1:{port}/"
    print(f"grayflag-dtc {__version__}\n  data folder: {paths.data_dir()}" + (f"\n  added datasets: {', '.join(added)}" if added else ""))
    print(f"  open {url}  (Ctrl+C to quit)")
    if not a.no_browser:
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def cmd_prepare(a) -> int:
    from . import local
    from .harvest import inject

    out_dir = a.out_dir or local.harvest_dir()
    out = inject.prepare(a.track, a.id, out_dir, name=a.name, tag=a.tag, obj_name_pat=a.obj_name_pat, cap_prefix=a.cap_prefix,
                         keep_scripts=a.keep_scripts)
    print(f"wrote {out}\nNext: run it in DCS single player, wait for the mission to start, then:\n  grayflag-dtc collect {a.id}")
    return 0


def cmd_collect(a) -> int:
    from . import local
    from .harvest import collect

    res = collect.collect(a.id, a.log or local.log_path(), force_enable=a.force)
    print(res.summary)
    if res.zone_kinds:
        print("  zone kinds:", ", ".join(f"{k}={v}" for k, v in res.zone_kinds.items()))
    print(f"wrote {res.dataset_path}")
    for p in res.problems[:50]:
        print("  -", p)
    print("scenario enabled" if res.enabled else "scenario left DISABLED (fix the problems or use --force)")
    return 0 if not res.problems else 1


def cmd_build(a) -> int:
    from .core.build import BuildError, build
    from .core.selection import CapacityError

    try:
        dtc, sel = build(a.server, a.airframe, a.objectives, name=a.name or a.out.stem, use_saved_settings=not a.no_settings, qrf_supply=a.qrf_supply)
    except (CapacityError, BuildError, KeyError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(dtc, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {a.out}: {sel.used} points" + (f" / capacity {sel.capacity}" if sel.capacity else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="grayflag-dtc", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--data", type=Path, help="data folder (datasets, saved settings); default: next to the exe")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    p = sub.add_parser("prepare")
    p.add_argument("track", type=Path)
    p.add_argument("--id", required=True, help="slug, e.g. pg-redux")
    p.add_argument("--name")
    p.add_argument("--tag", help="short tag for file names, e.g. PG")
    p.add_argument("--obj-name-pat", help="Lua pattern for objective zone names (default ^OBJ(%%a*)(%%d+)$)")
    p.add_argument("--cap-prefix", help="capture point zone prefix (default CAP)")
    p.add_argument("--keep-scripts", action="store_true", help="keep the server DO SCRIPT triggers (normally removed)")
    p.add_argument("--out-dir", type=Path, help="where to write the .miz (default: Saved Games\\DCS\\Missions\\Harvest)")
    c = sub.add_parser("collect")
    c.add_argument("id")
    c.add_argument("--log", type=Path, help="dcs.log (default: the one in your DCS folder)")
    c.add_argument("--force", action="store_true", help="enable the scenario even if the harvest reported problems")
    b = sub.add_parser("build")
    b.add_argument("server")
    b.add_argument("airframe")
    b.add_argument("objectives", nargs="+")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--name")
    b.add_argument("--no-settings", action="store_true")
    b.add_argument("--qrf-supply", action=argparse.BooleanOptionalAction, default=None, help="include enemy QRF/supply bases (default: Apache only)")
    a = ap.parse_args(argv)
    if a.data:
        os.environ["GFDTC_DATA"] = str(a.data)
    if a.cmd in (None, "serve"):
        if a.cmd is None:
            a.port, a.no_browser = 8765, False
        return cmd_serve(a)
    try:
        return {"prepare": cmd_prepare, "collect": cmd_collect, "build": cmd_build}[a.cmd](a)
    except FileNotFoundError as e:
        print(f"error: not found: {e.filename or e}. Run the harvest mission in DCS first, or pass --log.", file=sys.stderr)
        return 2
    except (LookupError, ValueError, SystemExit) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
