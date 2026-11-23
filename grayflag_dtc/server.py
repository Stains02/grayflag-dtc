"""FastAPI app: JSON API plus the static single-page frontend. Runs on your own PC (see __main__.py)."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .airframes import registry
from .core import settings as st
from .core.build import BuildError, build, sites_range
from .core.codes import CodeConfig, generate_codes, load_overrides
from . import __version__, local
from .core import servers as srv
from .core.dataset import Dataset, load_one
from .harvest import collect as hcollect, inject as hinject
from .paths import RES, data_dir
from .core.selection import CapacityError, build_selection

app = FastAPI(title="grayflag-dtc")


@app.middleware("http")
async def no_cache_for_ui(request, call_next):
    """The page and its script/CSS change together; never let a browser mix an old page with a new script."""
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp
STATIC = RES / "grayflag_dtc" / "static"
M_TO_FT = 3.280839895


def _enabled() -> list[dict]:
    return srv.enabled_servers()


_cache: dict[str, tuple[float, Dataset]] = {}


def _dataset(server_id: str) -> Dataset:
    s = next((x for x in _enabled() if x["id"] == server_id), None)
    if not s:
        raise HTTPException(404, f"unknown or disabled server {server_id!r}")
    path = srv.dataset_path(s)
    if not path.exists():
        raise HTTPException(503, f"dataset for {server_id} is missing ({path})")
    m = path.stat().st_mtime
    hit = _cache.get(server_id)
    if not hit or hit[0] != m:
        _cache[server_id] = (m, load_one(server_id))
    return _cache[server_id][1]


def _names(server_id: str) -> dict[str, str]:
    p = data_dir() / "names" / f"{server_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _airframe(airframe_id: str):
    plugin = registry.plugins().get(airframe_id)
    if plugin is None:
        raise HTTPException(404, f"unknown airframe {airframe_id!r}")
    cfg = registry.config(airframe_id)
    if not cfg.get("enabled"):
        raise HTTPException(404, f"airframe {airframe_id!r} is not enabled")
    return plugin, cfg


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/servers")
def servers():
    out = []
    for s in _enabled():
        path = srv.dataset_path(s)
        date = None
        if path.exists():
            try:
                date = (_dataset(s["id"]).harvested_at or "")[:10] or None
            except Exception:
                date = None
        out.append({**s, "data_date": date})
    return out


@app.get("/api/servers/{server_id}")
def server_detail(server_id: str):
    ds = _dataset(server_id)
    names = _names(server_id)
    cfg = CodeConfig.load()
    codes = generate_codes(ds, cfg, load_overrides(server_id))
    # The REDUX-era "Alpha/Bravo/Delta Objective" placeholders carry no information: show their code (A01, B05) instead.
    objs = [{
        "id": o.id, "code": o.code, "label": o.label, "lane": o.lane, "seq": o.seq, "name": o.name,
        "display_name": names.get(o.code) or names.get(o.id) or (o.label if o.placeholder else o.name),
        "placeholder": o.placeholder,
        "cps": [{"id": c.id, "name": c.name, "code": codes[o.id][c.id].code, "generic": _generic_cp(c.name, cfg)}
                for c in o.cps],
    } for o in sorted(ds.objectives, key=lambda o: (o.lane, o.seq))]
    return {"id": ds.server_id, "name": ds.server_name, "tag": ds.tag, "theater": ds.theater,
            "lanes": sorted(ds.lanes), "objectives": objs}


def _generic_cp(name: str, cfg: CodeConfig) -> bool:
    """CP names that say nothing ("capture point"): the UI shows only the code."""
    return not name.strip() or name.strip().lower() in cfg.generic_names


@app.get("/api/servers/{server_id}/codes")
def server_codes(server_id: str):
    ds = _dataset(server_id)
    codes = generate_codes(ds, CodeConfig.load(), load_overrides(server_id))
    return [{"lane": o.lane, "objective": o.code, "objective_name": o.name, "cp": c.id, "cp_name": c.name,
             "code": codes[o.id][c.id].code, "rule": codes[o.id][c.id].rule}
            for o in ds.objectives for c in o.cps]


@app.get("/api/airframes")
def airframes():
    out = []
    for aid, plugin in registry.plugins().items():
        cfg = registry.config(aid)
        if cfg.get("enabled"):
            out.append({"id": aid, "name": plugin.display_name, "capacity": cfg.get("capacity"),
                        "soft_capacity": cfg.get("soft_capacity"), "labels": plugin.supports_labels,
                        "sites_default": bool(cfg.get("sites_default"))})
    return out


# ------------------------------------------------------------------ settings
def _template(cfg: dict, ds_theater: str = "") -> dict:
    return json.loads(registry.template_path(cfg, ds_theater).read_text(encoding="utf-8"))


@app.get("/api/airframes/{airframe_id}/settings")
def get_settings(airframe_id: str):
    plugin, cfg = _airframe(airframe_id)
    schema = plugin.settings_schema()
    base = _template(cfg)
    factory = st._read(st.factory_path(airframe_id))
    saved = st._read(st.saved_path(airframe_id))
    values = st.current_values(st.apply_overlay(base, schema, {**factory, **saved}), schema)
    return {"schema": [asdict(f) for f in schema], "values": values, "has_saved": bool(saved)}


@app.put("/api/airframes/{airframe_id}/settings/defaults")
def save_settings(airframe_id: str, values: dict = Body(...)):
    plugin, _ = _airframe(airframe_id)
    try:
        st.save_defaults(airframe_id, plugin.settings_schema(), values)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return get_settings(airframe_id)


@app.delete("/api/airframes/{airframe_id}/settings/defaults")
def reset_settings(airframe_id: str):
    _airframe(airframe_id)
    st.reset_defaults(airframe_id)
    return get_settings(airframe_id)


# ------------------------------------------------------------------ preview / build
def _body(b: dict) -> tuple[str, str, list[str], dict]:
    try:
        return b["server"], b["airframe"], list(b.get("objectives") or []), dict(b.get("settings") or {})
    except (KeyError, TypeError):
        raise HTTPException(422, "body needs server, airframe, objectives") from None


@app.post("/api/preview")
def preview(b: dict = Body(...)):
    server_id, airframe_id, tokens, _ = _body(b)
    ds = _dataset(server_id)
    plugin, cfg = _airframe(airframe_id)
    try:
        sel = build_selection(ds, tokens, capacity=cfg.get("capacity"), labels=plugin.supports_labels,
                              code_cfg=CodeConfig.load(max_len=cfg.get("label_max_len", 3)),
                              overrides=load_overrides(server_id), enforce_capacity=False,
                              spawn_types=getattr(plugin, "airfield_spawn_types", None),
                              spawns_per_objective=cfg.get("spawns_per_objective", 0),
                              sites_range_nm=sites_range(cfg, b.get("qrf_supply")),
                              heli_spawn_types=getattr(plugin, "spawn_types", None),
                              spawn_range_nm=cfg.get("spawn_range_nm", 60.0))
    except KeyError as e:
        raise HTTPException(422, str(e.args[0])) from None
    by_id = ds.by_id()
    cfg_codes = CodeConfig.load()
    slot = getattr(plugin, "slot_label", None)
    pts = [{
        "index": p.index, "slot": slot(p.index, cfg) if slot and p.index <= (sel.capacity or 10**6) else "",
        "objective": by_id[p.objective_id].label, "objective_name": by_id[p.objective_id].name,
        "cp_id": p.cp_id, "cp_name": p.name, "cp_generic": _generic_cp(p.name, cfg_codes), "code": p.code,
        "elev_ft": round(p.elev_m * M_TO_FT),
    } for p in sel.points]
    labels = plugin.airfield_labels(len(sel.points), cfg) if hasattr(plugin, "airfield_labels") else []
    afs = [{"slot": lab, "name": a.name, "code": a.code, "spawn": a.spawn,
            "distance_nm": round(a.distance_m / 1852, 1), "elev_ft": round(a.elev_m * M_TO_FT)}
           for lab, a in zip(labels, sel.airfields)]
    room = plugin.extras_labels(len(sel.points), cfg) if hasattr(plugin, "extras_labels") else []     # slots after the CPs
    sts = [{"slot": room[i] if i < len(room) else "", "kind": s.kind, "name": s.name, "code": s.text, "objectives": s.objectives,
            "distance_nm": round(s.distance_m / 1852, 1), "elev_ft": round(s.elev_m * M_TO_FT)}
           for i, s in enumerate(sel.sites)]
    after = room[len([s for s in sts if s["slot"]]):]                                                    # then the FARPs
    fps = [{"slot": after[i] if i < len(after) else "", "name": f.name, "code": f.code, "objectives": f.objectives,
            "distance_nm": round(f.distance_m / 1852, 1), "elev_ft": round(f.elev_m * M_TO_FT)}
           for i, f in enumerate(sel.farps)]
    after2 = after[len([f for f in fps if f["slot"]]):]                                                  # then spawn airfields
    sas = [{"slot": after2[i] if i < len(after2) else "", "name": s.name, "code": s.code, "objectives": s.objectives,
            "distance_nm": round(s.distance_m / 1852, 1), "elev_ft": round(s.elev_m * M_TO_FT)}
           for i, s in enumerate(sel.spawn_airfields)]
    soft = cfg.get("soft_capacity")
    placed = lambda rows: sum(1 for r in rows if r["slot"])                      # extras that got a slot in this DTC
    airports = placed(sas) if sas else len(afs)
    counts = {"cps": len(pts), "sites": placed(sts), "airports": airports, "farps": placed(fps),
              "dropped": sum(1 for r in sts + fps + sas if not r["slot"])}
    counts["total"] = counts["cps"] + counts["sites"] + counts["farps"] + placed(sas)
    if cfg.get("dest_slots"):                                                    # airfields are destinations, not steerpoints
        counts["dest"] = len(afs)
        counts["dest_capacity"] = cfg["dest_slots"]
    return {"counts": counts, "airfields": afs, "spawn_airfields": sas, "farps": fps, "sites": sts, "points": pts, "used": sel.used, "capacity": sel.capacity, "over": sel.over,
            "soft_capacity": soft, "over_soft": bool(soft and sel.used > soft and not sel.over)}


def _filename(ds: Dataset, tokens: list[str]) -> str:
    codes = [ds.resolve(t).code for t in tokens]
    tag = re.sub(r"[^A-Za-z0-9]", "", ds.tag or ds.server_id).upper()
    return f"GF_{tag}_{'-'.join(codes)[:60]}_{datetime.now():%m%d-%H%M}"


@app.post("/api/build")
def build_route(b: dict = Body(...)):
    server_id, airframe_id, tokens, settings = _body(b)
    ds = _dataset(server_id)
    _airframe(airframe_id)
    if not tokens:
        raise HTTPException(422, "no objectives selected")
    deliver = b.get("deliver", "download")
    if deliver not in ("download", "dcs"):
        raise HTTPException(422, f"deliver must be 'download' or 'dcs', not {deliver!r}")
    try:
        name = _filename(ds, tokens)
        dtc, _ = build(server_id, airframe_id, tokens, name=name, settings=settings, qrf_supply=b.get("qrf_supply"))
    except KeyError as e:
        raise HTTPException(422, str(e.args[0])) from None
    except (CapacityError, BuildError, ValueError) as e:
        raise HTTPException(422, str(e)) from None
    text = json.dumps(dtc, indent=4, ensure_ascii=False)
    if deliver == "dcs":
        try:
            path, pruned = local.deliver(text, f"{name}.dtc", registry.config(airframe_id).get("dcs_dtc_subfolder", ""))
        except (OSError, FileNotFoundError) as e:
            raise HTTPException(409, f"could not write to DCS: {e}") from None
        return {"ok": True, "name": f"{name}.dtc", "path": str(path), "pruned": pruned}
    return Response(text, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}.dtc"'})


# ------------------------------------------------------------------ this PC: DCS folder, harvest
@app.get("/api/local")
def local_info():
    d = local.dcs_dir()
    return {"version": __version__, "data_dir": str(data_dir()), "dcs_dir": str(d) if d else None,
            "dtc_dir": str(local.dtc_dir()) if d else None, "candidates": [str(c) for c in local.candidates()]}


@app.put("/api/local")
def set_local(b: dict = Body(...)):
    try:
        local.set_dcs_dir((b.get("dcs_dir") or "").strip() or None)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return local_info()


@app.get("/api/harvest/tracks")
def harvest_tracks():
    return local.list_tracks()


@app.get("/api/harvest/scenarios")
def harvest_scenarios():
    out = []
    for s in srv.all_servers():
        out.append({"id": s["id"], "name": s["name"], "enabled": bool(s.get("enabled")),
                    "has_data": srv.dataset_path(s).exists(), "source_track": s.get("source_track")})
    return out


@app.post("/api/harvest/prepare")
def harvest_prepare(b: dict = Body(...)):
    try:
        track = Path(b["track"])
        out = hinject.prepare(track, b["server_id"], local.harvest_dir(), name=b.get("name") or None, tag=b.get("tag") or None,
                              keep_scripts=bool(b.get("keep_scripts")))
    except KeyError as e:
        raise HTTPException(422, f"missing {e.args[0]}") from None
    except (ValueError, OSError, FileNotFoundError) as e:
        raise HTTPException(422, str(e)) from None
    _cache.clear()
    return {"mission": str(out), "next": f"In DCS, run {out.name} (Missions, Harvest folder) in single player, "
                                         "wait for the mission to start, then press Collect."}


@app.post("/api/harvest/collect")
def harvest_collect(b: dict = Body(...)):
    try:
        res = hcollect.collect(b["server_id"], local.log_path(), force_enable=bool(b.get("force")))
    except KeyError as e:
        raise HTTPException(422, f"missing {e.args[0]}") from None
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except FileNotFoundError as e:
        raise HTTPException(409, f"dcs.log not found ({e.filename or 'DCS folder'}): run the harvest mission in DCS first") from None
    except (SystemExit, ValueError, OSError) as e:
        raise HTTPException(409, str(e) or "no complete harvest found in dcs.log (did the mission start?)") from None
    _cache.clear()
    return {"summary": res.summary, "problems": res.problems, "enabled": res.enabled, "zone_kinds": res.zone_kinds}


def _versioned(path: str) -> str:
    """URL with a content hash: Cloudflare (and browsers) cache by full URL, so any change to the file is a new URL."""
    import hashlib
    f = STATIC / path.removeprefix("/static/")
    return f"{path}?v={hashlib.sha256(f.read_bytes()).hexdigest()[:10]}"


@app.get("/")
def index():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for asset in ("/static/app.js", "/static/style.css"):
        html = html.replace(f'"{asset}"', f'"{_versioned(asset)}"')
    return Response(html, media_type="text/html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
