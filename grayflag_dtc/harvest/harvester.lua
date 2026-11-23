-- Grayflag DTC harvester. Runs once per Grayflag mission, in single player, from a MISSION START DO SCRIPT.
-- Reads env.mission.triggers.zones, assigns every capture point (CAP) to the objective quad containing it,
-- converts positions with DCS itself (coord.LOtoLL, land.getHeight) and writes one dataset JSON to dcs.log
-- in chunks prefixed "GFDTC|<part>/<total>|". tools/collect_harvest.py reassembles them.
--
-- Optional globals set by tools/inject_harvester.py before this code:
--   GFDTC_MISSION_ID  string  mission identifier (default: theatre name)
--   GFDTC_CONFIG      table   overrides for the defaults below (a new scenario with different zone names
--                             should only need a config change, not a code change)

local CFG = {
  obj_type_value = "obj",   -- zone property type=<this> marks an objective
  lane_key       = "lat",   -- property holding the lane letter
  name_key       = "str",   -- property holding the display name
  obj_name_pat   = "^OBJ(%a*)(%d+)$", -- zone name -> lane letter(s), sequence. The letter may be missing (a typo seen in the
                                       -- Caucasus mission: "OBJ10"); the lane then comes from the zone's own lane property
  cap_prefix     = "CAP",   -- capture point zones: "CAP" or "CAP-<n>"
  base_type_value = "base", -- zone property type=<this> marks a base/FARP site (name in name_key, "avail" = objective number)
  site_types      = { qrf = "qrf", supply = "supply" }, -- enemy QRF and supply bases: zone type -> kind reported ("lim" = objective number). The `hrf` zones mark a kind of enemy convoy and are ignored.
  chunk_size     = 1800,
  slot_radius_m  = 8000,    -- a slot not tied to an airbase id belongs to the nearest airbase within this distance
}
if type(GFDTC_CONFIG) == "table" then
  for k, v in pairs(GFDTC_CONFIG) do CFG[k] = v end
end

local function log(msg) env.info(msg) end

-- ---------------------------------------------------------------- JSON (ASCII-only output)
local function utf8_escape(s)
  -- Decode UTF-8 and emit \uXXXX so the log carries pure ASCII (chunk-safe, no mangling).
  local out, i, n = {}, 1, #s
  while i <= n do
    local c = s:byte(i)
    local cp, len
    if c < 0x80 then cp, len = c, 1
    elseif c >= 0xC0 and c < 0xE0 then cp, len = c % 0x20, 2
    elseif c >= 0xE0 and c < 0xF0 then cp, len = c % 0x10, 3
    elseif c >= 0xF0 and c < 0xF8 then cp, len = c % 0x08, 4
    else cp, len = 0xFFFD, 1 end
    for j = 1, len - 1 do
      local cc = s:byte(i + j)
      if not cc or cc < 0x80 or cc >= 0xC0 then cp, len = 0xFFFD, 1 break end
      cp = cp * 64 + (cc % 64)
    end
    i = i + len
    if cp == 0x22 then out[#out + 1] = '\\"'
    elseif cp == 0x5C then out[#out + 1] = '\\\\'
    elseif cp < 0x20 or cp == 0x7F then out[#out + 1] = string.format("\\u%04x", cp)
    elseif cp < 0x7F then out[#out + 1] = string.char(cp)
    elseif cp < 0x10000 then out[#out + 1] = string.format("\\u%04x", cp)
    else
      cp = cp - 0x10000
      out[#out + 1] = string.format("\\u%04x\\u%04x", 0xD800 + math.floor(cp / 0x400), 0xDC00 + cp % 0x400)
    end
  end
  return table.concat(out)
end

local JSON_NULL = {}
local function encode(v)
  local t = type(v)
  if v == JSON_NULL or v == nil then return "null"
  elseif t == "boolean" then return v and "true" or "false"
  elseif t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    if v == math.floor(v) and math.abs(v) < 1e15 then return string.format("%d", v) end
    return string.format("%.10g", v)
  elseif t == "string" then return '"' .. utf8_escape(v) .. '"'
  elseif t == "table" then
    if v.__order then -- ordered object
      local parts = {}
      for _, k in ipairs(v.__order) do
        parts[#parts + 1] = '"' .. k .. '":' .. encode(v[k])
      end
      return "{" .. table.concat(parts, ",") .. "}"
    end
    local parts = {}
    for i = 1, #v do parts[i] = encode(v[i]) end
    return "[" .. table.concat(parts, ",") .. "]"
  end
  return "null"
end

local function obj(order, t) t.__order = order return t end

-- ---------------------------------------------------------------- geometry
local function point_in_poly(px, py, poly)
  local inside, n = false, #poly
  local j = n
  for i = 1, n do
    local xi, yi, xj, yj = poly[i].x, poly[i].y, poly[j].x, poly[j].y
    if ((yi > py) ~= (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi) then
      inside = not inside
    end
    j = i
  end
  return inside
end

local function mean_center(poly)
  local sx, sy = 0, 0
  for i = 1, #poly do sx = sx + poly[i].x sy = sy + poly[i].y end
  return sx / #poly, sy / #poly
end

local function props_map(zone)
  local m = {}
  if type(zone.properties) == "table" then
    for _, p in pairs(zone.properties) do
      if type(p) == "table" and p.key ~= nil then m[tostring(p.key)] = p.value end
    end
  end
  return m
end

-- Quad vertices MUST be read by index 1..n (never pairs()): hash order scrambles the corners.
local function quad_vertices(zone)
  local poly = {}
  local src = zone.verticies or zone.vertices
  if type(src) ~= "table" then return nil end
  local i = 1
  while src[i] do
    poly[#poly + 1] = { x = src[i].x, y = src[i].y }
    i = i + 1
  end
  if #poly < 3 then return nil end
  return poly
end

local function round(v, places)
  local m = 10 ^ places
  return math.floor(v * m + (v >= 0 and 0.5 or -0.5)) / m
end

local function latlon(x, y)
  local lat, lon = coord.LOtoLL({ x = x, y = 0, z = y })
  return lat, lon
end

-- ---------------------------------------------------------------- airfields
-- Every airdrome/FARP on the map (ships skipped: they move) plus the aircraft types that have player slots there,
-- so an airframe can list "airfields I can spawn at" first. Slot airfield = airdromeId/helipadId of the group's first
-- route point when it matches an airbase id, else the nearest airbase within slot_radius_m of the unit.
local function harvest_airfields()
  if type(world) ~= "table" or type(world.getAirbases) ~= "function" then return {}, nil end
  local bases = {}
  for _, ab in ipairs(world.getAirbases()) do
    local ok, rec = pcall(function()
      local desc = ab:getDesc() or {}
      local cat = desc.category
      if cat == 2 then return nil end                      -- ship
      local p = ab:getPoint()
      return { ab = ab, id = ab:getID(), name = tostring(ab:getName()),
               kind = (cat == 1) and "helipad" or "airdrome", x = p.x, y = p.z,
               elev = land.getHeight({ x = p.x, y = p.z }), slots = {} }
    end)
    if ok and rec then bases[#bases + 1] = rec end
  end
  local by_id = {}
  for _, b in ipairs(bases) do if b.id ~= nil then by_id[b.id] = b end end
  local function nearest(x, y)
    local best, bd
    for _, b in ipairs(bases) do
      local d = math.sqrt((b.x - x) ^ 2 + (b.y - y) ^ 2)
      if not bd or d < bd then best, bd = b, d end
    end
    if best and bd <= CFG.slot_radius_m then return best end
  end
  local m = env.mission
  for _, co in pairs(m.coalition or {}) do
    for _, country in ipairs(co.country or {}) do
      for _, cat in ipairs({ "plane", "helicopter" }) do
        local grp = country[cat] and country[cat].group
        for _, g in ipairs(grp or {}) do
          local p1 = g.route and g.route.points and g.route.points[1]
          for _, u in ipairs(g.units or {}) do
            if u.skill == "Client" or u.skill == "Player" then
              local b = p1 and (by_id[p1.airdromeId] or by_id[p1.helipadId]) or nil
              b = b or nearest(u.x, u.y)
              if b then b.slots[u.type] = (b.slots[u.type] or 0) + 1 end
            end
          end
        end
      end
    end
  end
  table.sort(bases, function(a, b) return a.name < b.name end)
  local out = {}
  for _, b in ipairs(bases) do
    local lat, lon = latlon(b.x, b.y)
    local types = {}
    for t in pairs(b.slots) do types[#types + 1] = t end
    table.sort(types)
    local slots = { __order = types }
    for _, t in ipairs(types) do slots[t] = b.slots[t] end
    out[#out + 1] = obj(
      { "id", "name", "kind", "lat", "lon", "elev_m", "dcs", "slots" },
      { id = b.id, name = b.name, kind = b.kind, lat = round(lat, 8), lon = round(lon, 8),
        elev_m = round(b.elev, 1), dcs = obj({ "x", "y" }, { x = round(b.x, 1), y = round(b.y, 1) }), slots = slots })
  end
  return out
end

-- ---------------------------------------------------------------- harvest
local function is_cap_name(name)
  if name == CFG.cap_prefix then return true end
  local esc = CFG.cap_prefix:gsub("(%W)", "%%%1")
  return name:match("^" .. esc .. "%-%d+$") ~= nil
end

local function harvest()
  local m = env.mission
  local zones = m and m.triggers and m.triggers.zones
  if type(zones) ~= "table" then error("no env.mission.triggers.zones") end

  local anomalies = {}
  local function anomaly(kind, id, detail)
    anomalies[#anomalies + 1] = obj({ "kind", "id", "detail" }, { kind = kind, id = id, detail = detail })
  end

  local objectives, caps, byname = {}, {}, {}
  local farps, sites = {}, {}
  local kinds = {}            -- count of zones per type property, for onboarding a new scenario
  local lane_set = {}

  local i = 1
  while zones[i] do
    local z = zones[i]
    local name = tostring(z.name or "")
    local p = props_map(z)
    local ztype = p.type
    kinds[ztype or "(none)"] = (kinds[ztype or "(none)"] or 0) + 1

    if ztype == CFG.obj_type_value then
      local poly = quad_vertices(z)
      local lane, seq = name:match(CFG.obj_name_pat)
      local lat_prop = p[CFG.lane_key]
      local lane_letter = lat_prop and tostring(lat_prop):upper() or nil
      -- an objective is normally a quad; a circular zone (radius, no vertices) is accepted too (seen in the Sinai mission)
      local circle = (not poly) and type(z.radius) == "number" and z.radius > 0 and z.x and z.y and { x = z.x, y = z.y, r = z.radius } or nil
      if not poly and not circle then
        anomaly("objective_not_quad", name, "no usable vertices and no radius")
      else
        if not lane_letter or not lane_letter:match("^%u$") then
          anomaly("bad_lane", name, "lane property = " .. tostring(lat_prop))
          lane_letter = (lane and lane:upper():sub(1, 1)) or "?"
        end
        if not seq then anomaly("bad_objective_name", name, "name does not match " .. CFG.obj_name_pat) end
        if not p[CFG.name_key] then anomaly("missing_name", name, "no " .. CFG.name_key .. " property") end
        if byname[name] then anomaly("duplicate_objective", name, "zone name seen twice") end
        local o = {
          id = name, lane = lane_letter, seq = tonumber(seq) or 0,
          name = p[CFG.name_key] and tostring(p[CFG.name_key]) or name,
          poly = poly, circle = circle, cps = {},
        }
        local cx, cy
        if poly then cx, cy = mean_center(poly) else cx, cy = circle.x, circle.y end
        o.cx, o.cy = cx, cy
        byname[name] = o
        objectives[#objectives + 1] = o
        lane_set[lane_letter] = true
      end
    elseif ztype == CFG.base_type_value then
      -- Grayflag base / FARP sites: position, name, lane and the objective number at which they unlock
      local poly = quad_vertices(z)
      local cx, cy
      if z.type == 2 and poly then cx, cy = mean_center(poly) else cx, cy = z.x, z.y end
      local lat, lon = latlon(cx, cy)
      local lane_letter = p[CFG.lane_key] and tostring(p[CFG.lane_key]):upper() or "?"
      local display = p[CFG.name_key] and tostring(p[CFG.name_key]):gsub("^%s+", ""):gsub("%s+$", "") or name
      farps[#farps + 1] = obj(
        { "id", "name", "lane", "avail", "template", "convoy", "lat", "lon", "elev_m", "dcs" },
        {
          id = name, name = display, lane = lane_letter, avail = tonumber(p.avail) or 0,
          template = p.template and tostring(p.template) or JSON_NULL, convoy = p.convoy ~= nil,
          lat = round(lat, 8), lon = round(lon, 8), elev_m = round(land.getHeight({ x = cx, y = cy }), 1),
          dcs = obj({ "x", "y" }, { x = round(cx, 1), y = round(cy, 1) }),
        })
    elseif (function() for _, v in pairs(CFG.site_types) do if v == ztype then return true end end end)() then
      local kind
      for k, v in pairs(CFG.site_types) do if v == ztype then kind = k end end
      local poly = quad_vertices(z)
      local cx, cy
      if z.type == 2 and poly then cx, cy = mean_center(poly) else cx, cy = z.x, z.y end
      local lat, lon = latlon(cx, cy)
      local display = p[CFG.name_key] and tostring(p[CFG.name_key]):gsub("^%s+", ""):gsub("%s+$", "") or name
      sites[#sites + 1] = obj(
        { "id", "kind", "name", "lane", "lim", "lat", "lon", "elev_m", "dcs" },
        {
          id = name, kind = kind, name = display, lane = p[CFG.lane_key] and tostring(p[CFG.lane_key]):upper() or "?",
          lim = tonumber(p.lim) or 0, lat = round(lat, 8), lon = round(lon, 8),
          elev_m = round(land.getHeight({ x = cx, y = cy }), 1), dcs = obj({ "x", "y" }, { x = round(cx, 1), y = round(cy, 1) }),
        })
    elseif is_cap_name(name) then
      local cx, cy, shape, radius
      local poly = quad_vertices(z)
      if z.type == 2 and poly then
        cx, cy = mean_center(poly)
        shape, radius = "quad", JSON_NULL
      else
        cx, cy, shape, radius = z.x, z.y, "circle", z.radius
      end
      caps[#caps + 1] = {
        id = name, name = p[CFG.name_key] and tostring(p[CFG.name_key]) or "",
        cx = cx, cy = cy, shape = shape, radius = radius,
      }
    end
    i = i + 1
  end

  -- assign CPs to objectives (point in polygon, DCS x/y)
  for _, cp in ipairs(caps) do
    local hits = {}
    for _, o in ipairs(objectives) do
      if o.poly and point_in_poly(cp.cx, cp.cy, o.poly) then hits[#hits + 1] = o end
    end
    if #hits == 0 then            -- not inside any quad: try the circular objectives, the one it is deepest inside first
      local best, bestd
      for _, o in ipairs(objectives) do
        if o.circle then
          local d = math.sqrt((cp.cx - o.circle.x) ^ 2 + (cp.cy - o.circle.y) ^ 2) / o.circle.r
          if d <= 1 and (not bestd or d < bestd) then best, bestd = o, d end
        end
      end
      if best then hits[1] = best end
    end
    if #hits == 0 then
      anomaly("cp_unassigned", cp.id, "inside no objective")
    else
      if #hits > 1 then anomaly("cp_multi", cp.id, "inside " .. #hits .. " objectives; used first") end
      local lat, lon = latlon(cp.cx, cp.cy)
      local o = hits[1]
      o.cps[#o.cps + 1] = obj(
        { "id", "name", "lat", "lon", "elev_m", "radius_m", "shape", "dcs" },
        {
          id = cp.id, name = cp.name,
          lat = round(lat, 8), lon = round(lon, 8),
          elev_m = round(land.getHeight({ x = cp.cx, y = cp.cy }), 1),
          radius_m = type(cp.radius) == "number" and round(cp.radius, 1) or JSON_NULL,
          shape = cp.shape,
          dcs = obj({ "x", "y" }, { x = round(cp.cx, 1), y = round(cp.cy, 1) }),
        })
    end
  end

  local out_objs = {}
  for _, o in ipairs(objectives) do
    if #o.cps == 0 then anomaly("objective_no_cps", o.id, "no capture points inside") end
    local lat, lon = latlon(o.cx, o.cy)
    out_objs[#out_objs + 1] = obj(
      { "id", "lane", "seq", "name", "center", "cps" },
      {
        id = o.id, lane = o.lane, seq = o.seq, name = o.name,
        center = obj({ "lat", "lon" }, { lat = round(lat, 8), lon = round(lon, 8) }),
        cps = o.cps,
      })
  end

  local lanes = {}
  for l in pairs(lane_set) do lanes[#lanes + 1] = l end
  table.sort(lanes)

  local kind_list = {}
  for k, c in pairs(kinds) do kind_list[#kind_list + 1] = k end
  table.sort(kind_list)
  local kind_obj = { __order = kind_list }
  for _, k in ipairs(kind_list) do kind_obj[k] = kinds[k] end

  local okf, airfields = pcall(harvest_airfields)
  if not okf then
    anomaly("airfields_failed", "airfields", tostring(airfields))
    airfields = {}
  end

  return obj(
    { "schema", "theater", "mission_id", "lanes", "zone_kinds", "objectives", "airfields", "farps", "sites", "anomalies" },
    {
      schema = 1, airfields = airfields, farps = farps, sites = sites,
      theater = tostring(m.theatre or ""),
      mission_id = GFDTC_MISSION_ID or tostring(m.theatre or ""),
      lanes = lanes, zone_kinds = kind_obj, objectives = out_objs, anomalies = anomalies,
    })
end

local function emit(json)
  local size = CFG.chunk_size
  local total = math.max(1, math.ceil(#json / size))
  for part = 1, total do
    log(string.format("GFDTC|%d/%d|%s", part, total, json:sub((part - 1) * size + 1, part * size)))
  end
  log(string.format("GFDTC harvest complete: %d bytes in %d chunks", #json, total))
end

local ok, result = pcall(harvest)
if not ok then
  log("GFDTC harvest FAILED: " .. tostring(result))
else
  local ok2, json = pcall(encode, result)
  if not ok2 then log("GFDTC encode FAILED: " .. tostring(json)) else emit(json) end
end
