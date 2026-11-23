"""Prepare a Grayflag track for harvesting.

Copies the track (a zip) to <out>/<server-id>.miz with a MISSION START "DO SCRIPT" trigger that runs harvester.lua
(inlined, no file paths), and registers the scenario as disabled. The mission's own DO SCRIPT triggers (the server's
scripts) are removed so nothing else runs and there is no script error box. Run the .miz in DCS single player; the
script writes the data to dcs.log, which collect.py reads.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from ..core import servers
from ..paths import RES

HARVESTER = RES / "grayflag_dtc" / "harvest" / "harvester.lua"
COMMENT = "GFDTC harvester"


def lua_quote(s: str) -> str:
    out = s.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n")
    return f'"{out}"'


def lua_table_end(text: str, open_idx: int) -> int:
    """Index of the '}' closing the table whose '{' is at open_idx. Skips strings and comments."""
    depth, i, n = 0, open_idx, len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            q = c
            i += 1
            while text[i] != q:
                i += 2 if text[i] == "\\" else 1
        elif text.startswith("--", i):
            i = text.find("\n", i)
            if i < 0:
                break
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced Lua table")


def find_table(text: str, key: str, start: int = 0, end: int | None = None) -> tuple[int, int] | None:
    """(open, close) indexes of the table value for ["key"] = { ... } between start and end."""
    end = len(text) if end is None else end
    m = re.compile(r'\["%s"\]\s*=\s*\{' % re.escape(key)).search(text, start, end)
    if not m:
        return None
    o = m.end() - 1
    return o, lua_table_end(text, o)


def build_script(harvester_src: str, mission_id: str, cfg: dict) -> str:
    head = f"GFDTC_MISSION_ID = {lua_quote(mission_id)}\n"
    if cfg:
        pairs = []
        for k, v in cfg.items():
            pairs.append(f"{k} = {lua_quote(v) if isinstance(v, str) else json.dumps(v)}")
        head += "GFDTC_CONFIG = { " + ", ".join(pairs) + " }\n"
    return head + harvester_src


_ENTRY = re.compile(r'(\[\d+\]\s*=\s*)"((?:\\.|[^"\\])*)"', re.S)
# a "run once" trigger's action also clears its own handler (mission.trig.func[5]=nil;): keep that, drop the scripts
_KEEP = re.compile(r'mission\.trig\.(?:func\[\d+\]|events\[\\?"[^\]"\\]*\\?"\]\[\d+\])=nil;')


_RULE_SCRIPT = re.compile(r'\["predicate"\]\s*=\s*"a_do_script(?:_file)?"')
_NOOP_ACTION = '{\n\t\t\t\t\t["text"] = "return",\n\t\t\t\t\t["predicate"] = "a_do_script",\n\t\t\t\t}'


def child_tables(text: str, open_idx: int, close_idx: int) -> list[tuple[int, int]]:
    """(open, close) spans of the tables directly inside the table spanning open_idx..close_idx. Skips strings and comments."""
    out, depth, i, start = [], 0, open_idx + 1, 0
    while i < close_idx:
        c = text[i]
        if c == '"' or c == "'":
            q = c
            i += 1
            while text[i] != q:
                i += 2 if text[i] == "\\" else 1
        elif text.startswith("--", i):
            i = text.find("\n", i)
            if i < 0:
                break
        elif c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                out.append((start, i))
        i += 1
    return out


def _strip_trigrules(mission: str) -> tuple[str, int]:
    """The Mission Editor's copy of the triggers (`trigrules`): DCS runs the scripts from here too. Every DO SCRIPT /
    DO SCRIPT FILE action becomes a harmless `return`."""
    rules = find_table(mission, "trigrules")
    if not rules:
        return mission, 0
    edits: list[tuple[int, int]] = []
    for ro, rc in child_tables(mission, *rules):
        acts = find_table(mission, "actions", ro, rc)
        if not acts:
            continue
        for ao, ac in child_tables(mission, *acts):
            if _RULE_SCRIPT.search(mission[ao:ac + 1]):
                edits.append((ao, ac))
    for ao, ac in sorted(edits, reverse=True):
        mission = mission[:ao] + _NOOP_ACTION + mission[ac + 1:]
    return mission, len(edits)


def strip_scripts(mission: str) -> tuple[str, int]:
    """Remove every DO SCRIPT / DO SCRIPT FILE action from the mission's triggers (the server's own scripts: they load
    files from the server's disk and error out in single player), in both places DCS reads them from: the compiled
    `trig.actions` and the editor's `trigrules`. Returns (text, number of actions changed)."""
    mission, n_rules = _strip_trigrules(mission)
    t0 = mission.find('["trig"]')
    if t0 < 0:
        return mission, n_rules
    trig_o, trig_c = find_table(mission, "trig", t0 - 1)  # type: ignore[misc]
    actions = find_table(mission, "actions", trig_o, trig_c)
    if not actions:
        return mission, n_rules
    count = n_rules

    def repl(m: re.Match) -> str:
        nonlocal count
        if "a_do_script" not in m.group(2):
            return m.group(0)
        count += 1
        return f'{m.group(1)}"{"".join(_KEEP.findall(m.group(2))) or "return"}"'

    body = _ENTRY.sub(repl, mission[actions[0]:actions[1] + 1])
    return mission[:actions[0]] + body + mission[actions[1] + 1:], count


def inject(mission: str, script: str, strip: bool = True) -> str:
    """Add a MISSION START do-script trigger to a mission file's text (trig + trigrules tables).
    By default the mission's own script triggers are removed first (strip_scripts)."""
    if strip:
        mission, _ = strip_scripts(mission)
    t0 = mission.find('["trig"]')
    if t0 < 0:
        raise ValueError("no [\"trig\"] table in mission")
    trig_o, trig_c = find_table(mission, "trig", t0 - 1)  # type: ignore[misc]
    actions = find_table(mission, "actions", trig_o, trig_c)
    conds = find_table(mission, "conditions", trig_o, trig_c)
    events = find_table(mission, "events", trig_o, trig_c)
    if not (actions and conds and events):
        raise ValueError("trig table is missing actions/conditions/events")
    n = 1 + max(max_index_top(mission[a + 1:b]) for a, b in (actions, conds))
    for sub in re.findall(r"\[(\d+)\]", mission[events[0]:events[1]]):
        n = max(n, int(sub) + 1)

    action = (f"a_do_script({lua_quote(script)}); "
              f'mission.trig.events["mission start"][{n}]=nil;')
    cond = "return(true)"
    func = f"if mission.trig.conditions[{n}]() then mission.trig.actions[{n}]() end"

    edits: list[tuple[int, str]] = []  # (insert position, text); applied back to front
    edits.append((actions[1], f"\t\t\t[{n}] = {lua_quote(action)},\n\t\t"))
    edits.append((conds[1], f"\t\t\t[{n}] = {lua_quote(cond)},\n\t\t"))
    ms = find_table(mission, "mission start", events[0], events[1])
    if ms:
        edits.append((ms[1], f"\t\t\t\t[{n}] = {lua_quote(func)},\n\t\t\t"))
    else:
        edits.append((events[1], f'\t\t\t["mission start"] = {{ [{n}] = {lua_quote(func)}, }},\n\t\t'))

    # trigrules entry, so the Mission Editor shows the trigger too
    rules = find_table(mission, "trigrules", trig_c)
    if rules:
        rn = 1 + max_index_top(mission[rules[0] + 1:rules[1]])
        entry = (
            f"\t\t[{rn}] = \n\t\t{{\n\t\t\t[\"rules\"] = {{}},\n\t\t\t[\"eventlist\"] = \"mission start\",\n"
            f"\t\t\t[\"predicate\"] = \"triggerOnce\",\n\t\t\t[\"actions\"] = \n\t\t\t{{\n\t\t\t\t[1] = \n\t\t\t\t{{\n"
            f"\t\t\t\t\t[\"text\"] = {lua_quote(script)},\n\t\t\t\t\t[\"predicate\"] = \"a_do_script\",\n"
            f"\t\t\t\t}},\n\t\t\t}},\n\t\t\t[\"comment\"] = \"{COMMENT}\",\n\t\t}},\n\t"
        )
        edits.append((rules[1], entry))
    for pos, text in sorted(edits, key=lambda e: -e[0]):
        mission = mission[:pos] + text + mission[pos:]
    return mission


def max_index_top(body: str) -> int:
    """Highest top-level [n] key of a table body (depth 1 only)."""
    depth, best, i = 0, 0, 0
    for m in re.finditer(r'"(?:\\.|[^"\\])*"|\{|\}|^\s*\[(\d+)\]\s*=', body, re.M | re.S):
        tok = m.group(0)
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth -= 1
        elif m.group(1) and depth == 0:
            best = max(best, int(m.group(1)))
    return best


def prepare(track: Path, server_id: str, out_dir: Path, name: str | None = None, tag: str | None = None,
            obj_name_pat: str | None = None, cap_prefix: str | None = None, keep_scripts: bool = False) -> Path:
    """Write <out_dir>/<server_id>.miz (the track with the harvester injected) and register the scenario."""
    if not servers.SERVER_ID_RE.match(server_id):
        raise ValueError(f"server id must be a lowercase slug like 'pg-redux', got {server_id!r}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{server_id}.miz"
    cfg = dict((servers.find_server(server_id) or {}).get("harvest_config") or {})
    if obj_name_pat:
        cfg["obj_name_pat"] = obj_name_pat
    if cap_prefix:
        cfg["cap_prefix"] = cap_prefix
    with zipfile.ZipFile(track) as zin:
        if "mission" not in zin.namelist():
            raise ValueError(f"{track.name} is not a DCS track or mission (no 'mission' file inside)")
        mission = zin.read("mission").decode("utf-8")
        new_mission = inject(mission, build_script(HARVESTER.read_text(encoding="utf-8"), server_id, cfg), strip=not keep_scripts)
        tmp = out.with_suffix(".miz.tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = new_mission.encode("utf-8") if item.filename == "mission" else zin.read(item.filename)
                zout.writestr(item, data)
        tmp.replace(out)
    from . import dynspawn                        # imported here: dynspawn uses this module's Lua helpers
    try:                                          # dynamic-spawn bases come from the track's warehouses, not from DCS
        dyn = [r for r in dynspawn.extract_from_track(track) if r["coalition"] in ("blue", "red")]
    except (ValueError, KeyError, OSError):
        dyn = None
    servers.upsert_server(server_id, name=name, tag=tag, harvest_config=cfg or None, source_track=track.name, dynamic_spawns=dyn)
    return out
