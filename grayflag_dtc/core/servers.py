"""The list of scenarios (servers): the bundled config/servers.json plus the ones you added in <data>/servers.json.

A scenario you add (harvest) with the same id as a bundled one replaces it. `dataset` paths are relative to the data folder.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..paths import RES, data_dir

SERVER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _read(p: Path) -> list[dict]:
    return json.loads(p.read_text(encoding="utf-8")).get("servers", []) if p.exists() else []


def user_servers_path() -> Path:
    return data_dir() / "servers.json"


def all_servers() -> list[dict]:
    merged = {s["id"]: s for s in _read(RES / "config" / "servers.json")}
    for s in _read(user_servers_path()):
        merged[s["id"]] = {**merged.get(s["id"], {}), **s}
    return list(merged.values())


def enabled_servers() -> list[dict]:
    return [s for s in all_servers() if s.get("enabled")]


def find_server(server_id: str) -> dict | None:
    return next((s for s in all_servers() if s["id"] == server_id), None)


def dataset_path(server: dict) -> Path:
    return data_dir() / server["dataset"]


def upsert_server(server_id: str, **fields) -> dict:
    """Create or update a scenario in <data>/servers.json. None-valued fields are ignored."""
    if not SERVER_ID_RE.match(server_id):
        raise ValueError(f"server id must be a lowercase slug like 'pg-redux', got {server_id!r}")
    p = user_servers_path()
    mine = _read(p)
    entry = next((s for s in mine if s["id"] == server_id), None)
    if entry is None:
        base = find_server(server_id) or {"id": server_id, "name": server_id, "tag": None,
                                          "dataset": f"theaters/{server_id}.json", "enabled": False, "harvest_config": {}}
        entry = dict(base)
        mine.append(entry)
    for k, v in fields.items():
        if v is not None:
            entry[k] = v
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"servers": mine}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return entry
