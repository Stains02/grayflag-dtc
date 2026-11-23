"""Turn a harvester run in dcs.log into <data>/theaters/<server-id>.json.

Reassembles the newest complete GFDTC|<part>/<total>| sequence, validates it, normalizes it (sort by lane/seq,
placeholder flag, harvest metadata) and writes the dataset. A clean dataset enables the scenario; anomalies are
reported, the dataset is still written, and the scenario stays disabled unless forced.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..core import servers

LINE_RE = re.compile(rb"GFDTC\|(\d+)/(\d+)\|(.*?)\r?\n?$", re.S)
PLACEHOLDER_RE = re.compile(r"^(Alpha|Bravo|Charlie|Delta) Objective$")


def reassemble(log_bytes: bytes) -> bytes:
    """Newest complete chunk sequence in the log (a sequence restarts at part 1)."""
    seqs: list[dict[int, bytes]] = []
    totals: list[int] = []
    for line in log_bytes.split(b"\n"):
        i = line.find(b"GFDTC|")
        if i < 0:
            continue
        m = LINE_RE.match(line[i:])
        if not m:
            continue
        part, total, data = int(m.group(1)), int(m.group(2)), m.group(3)
        if part == 1:
            seqs.append({})
            totals.append(total)
        if not seqs:
            continue
        seqs[-1][part] = data
    for parts, total in zip(reversed(seqs), reversed(totals)):
        if len(parts) == total and all(p in parts for p in range(1, total + 1)):
            return b"".join(parts[p] for p in range(1, total + 1))
    raise SystemExit("no complete GFDTC harvest found in the log (check for 'GFDTC harvest FAILED' lines)")


def normalize(raw: dict, server: dict, source_track: str | None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    objs = raw["objectives"]
    for o in objs:
        o["placeholder"] = bool(PLACEHOLDER_RE.match(o["name"]))
    objs.sort(key=lambda o: (o["lane"], o["seq"], o["id"]))
    ordered = []
    for o in objs:
        ordered.append({k: o[k] for k in ("id", "lane", "seq", "name", "placeholder", "center", "cps")})
    return {
        "schema": 1,
        "server_id": server["id"],
        "server_name": server.get("name") or server["id"],
        "theater": raw["theater"],
        "mission_id": raw.get("mission_id"),
        "harvested_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_track": source_track,
        "lanes": sorted({o["lane"] for o in ordered}),
        "objectives": ordered,
        "airfields": sorted(raw.get("airfields", []), key=lambda a: (a["name"], str(a["id"]))),
        "sites": sorted(raw.get("sites", []), key=lambda s: (s["kind"], s["lane"], s["lim"], s["name"], s["id"])),
        "farps": sorted(raw.get("farps", []), key=lambda f: (f["lane"], f["avail"], f["name"], f["id"])),
        "dynamic_spawns": list(server.get("dynamic_spawns") or []),
        "anomalies": raw.get("anomalies", []),
    }


def validate(ds: dict) -> list[str]:
    """Problems that should stop the server being enabled (beyond harvester-reported anomalies)."""
    problems = [f"{a['kind']}: {a['id']} ({a['detail']})" for a in ds["anomalies"]]
    if not ds.get("airfields"):
        problems.append("no airfields harvested (run the harvest mission again with the current version of this program)")
    seen: set[str] = set()
    for o in ds["objectives"]:
        if o["id"] in seen:
            problems.append(f"duplicate objective id {o['id']}")
        seen.add(o["id"])
        for cp in o["cps"]:
            if not (-90 <= cp["lat"] <= 90 and -180 <= cp["lon"] <= 180):
                problems.append(f"{cp['id']}: lat/lon out of range")
    if not ds["objectives"]:
        problems.append("no objectives found: zone naming probably differs from the usual Grayflag objective zones; see zone_kinds")
    elif sum(len(o["cps"]) for o in ds["objectives"]) == 0:
        problems.append("no capture points found: check cap_prefix")
    return problems


def summary(ds: dict) -> str:
    lines = [f"{ds['server_name']}  theater={ds['theater']}  mission={ds['mission_id']}"]
    for lane in ds["lanes"]:
        os_ = [o for o in ds["objectives"] if o["lane"] == lane]
        lines.append(f"  lane {lane}: {len(os_)} objectives, {sum(len(o['cps']) for o in os_)} CPs")
    lines.append(f"  total: {len(ds['objectives'])} objectives, {sum(len(o['cps']) for o in ds['objectives'])} CPs, "
                 f"{len(ds['anomalies'])} anomalies")
    return "\n".join(lines)


@dataclass
class CollectResult:
    server_id: str
    dataset_path: Path
    summary: str
    zone_kinds: dict
    problems: list[str] = field(default_factory=list)
    enabled: bool = False


def collect(server_id: str, log: Path, force_enable: bool = False, expect_objectives: int | None = None,
            expect_cps: int | None = None) -> CollectResult:
    server = servers.find_server(server_id)
    if server is None:
        raise LookupError(f"{server_id} is not a known scenario; prepare its harvest mission first")
    raw = json.loads(reassemble(log.read_bytes()).decode("utf-8"))
    found = raw.get("mission_id")
    if found and found != server_id:      # the harvest script stamps the scenario id it was prepared for
        raise ValueError(f"the newest harvest in dcs.log is for '{found}', not '{server_id}': has the {server_id} mission "
                         f"started in DCS yet? (A harvest runs when the mission starts, not while it is still loading.)")
    ds = normalize(raw, server, server.get("source_track"))
    problems = validate(ds)
    n_obj = len(ds["objectives"])
    n_cp = sum(len(o["cps"]) for o in ds["objectives"])
    if expect_objectives is not None and n_obj != expect_objectives:
        problems.append(f"expected {expect_objectives} objectives, got {n_obj}")
    if expect_cps is not None and n_cp != expect_cps:
        problems.append(f"expected {expect_cps} CPs, got {n_cp}")
    out = servers.dataset_path(server)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ds, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    enable = not problems or force_enable
    servers.upsert_server(server_id, enabled=enable)
    return CollectResult(server_id, out, summary(ds), raw.get("zone_kinds") or {}, problems, enable)
