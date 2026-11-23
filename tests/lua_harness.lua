-- Runs with lua5.1: loads a mission file, optionally injected by tools/inject_harvester.py, and fires the
-- MISSION START trigger the way DCS would, with stubbed env/coord/land. Prints dcs.log-style lines.
local path, mode = arg[1], arg[2]
dofile(path)
env = { mission = mission, info = function(msg) print("2026-11-19 12:00:00.000 INFO    SCRIPTING (Main): " .. msg) end }
coord = { LOtoLL = function(p) return 30 + p.x / 100000, 50 + p.z / 100000, 0 end }
land = { getHeight = function(p) return 100 + p.x / 100 end }
local function ab(id, name, cat, x, z)
  return { getID = function() return id end, getName = function() return name end,
           getDesc = function() return { category = cat } end, getPoint = function() return { x = x, y = 5, z = z } end }
end
world = { getAirbases = function() return { ab(7, "Beta Field", 0, 5000, 5000), ab(4, "Alpha AB", 0, 100, 200),
                                            ab(99, "Carrier", 2, 9, 9), ab(12, "Far Strip", 0, 90000, 90000) } end }
a_do_script = function(code)
  local f, err = loadstring(code)
  if not f then error("do-script compile error: " .. tostring(err)) end
  f()
end
mission.trig.conditions = (function()
  local out = {}
  for i, c in pairs(mission.trig.conditions) do out[i] = assert(loadstring(c)) end
  return out
end)()
local acts = {}
for i, a in pairs(mission.trig.actions) do acts[i] = a end
mission.trig.actions = {}
for i, a in pairs(acts) do mission.trig.actions[i] = assert(loadstring(a)) end
for i, fn in pairs(mission.trig.events["mission start"]) do
  assert(loadstring(fn))()
end

print("MARK server_script_ran=" .. tostring(x == 1))
