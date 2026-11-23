"use strict";
const $ = (s) => document.querySelector(s);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
};
const st = { local: {}, servers: [], airframes: [], server: null, airframe: null, data: null, lane: null, sel: [], settings: null, edits: {} };

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (e) { /* not json */ }
    throw new Error(msg);
  }
  return r;
}
const jpost = (p, b, m = "POST") => api(p, { method: m, headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function init() {
  [st.servers, st.airframes] = await Promise.all([api("/api/servers").then((r) => r.json()), api("/api/airframes").then((r) => r.json())]);
  const sv = $("#server");
  sv.innerHTML = serverOptions();
  const saved = store.get("gf.server");
  st.server = st.servers.some((s) => s.id === saved) ? saved : (st.servers[0] || {}).id;
  sv.value = st.server;
  sv.onchange = () => { st.server = sv.value; store.set("gf.server", st.server); st.sel = []; loadServer(); };
  const sa = store.get("gf.airframe");
  st.airframe = st.airframes.some((a) => a.id === sa) ? sa : (st.airframes[0] || {}).id;
  renderAirframes();
  $("#quick").oninput = onQuick;
  $("#clear").onclick = () => { st.sel = []; $("#quick").value = ""; renderObjectives(); refresh(); };
  $("#download").onclick = download;
  $("#send").onclick = sendToDcs;
  initLocal();
  $("#saveDefaults").onclick = saveDefaults;
  $("#resetDefaults").onclick = resetDefaults;
  await Promise.all([loadServer(), loadSettings()]);
}

const serverOptions = () => st.servers.map((s) =>
  `<option value="${esc(s.id)}">${esc(s.name)}${s.data_date ? ` · data ${esc(s.data_date)}` : ""}</option>`).join("");

const qrfOn = () => {                                   // include enemy QRF/supply bases? remembered per aircraft
  const a = st.airframes.find((x) => x.id === st.airframe) || {};
  const v = store.get("gf.qrf." + st.airframe);
  return v == null ? !!a.sites_default : v === "1";
};

function renderAirframes() {
  const sel = $("#airframe");
  sel.innerHTML = st.airframes.map((a) =>
    `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join("");
  sel.value = st.airframe;
  $("#qrf").checked = qrfOn();
  $("#qrf").onchange = () => { store.set("gf.qrf." + st.airframe, $("#qrf").checked ? "1" : "0"); refresh(); };
  sel.onchange = () => {
    st.airframe = sel.value; store.set("gf.airframe", st.airframe); st.edits = {}; $("#qrf").checked = qrfOn();
    loadSettings(); refresh();
  };
}

async function loadServer() {
  st.data = await api(`/api/servers/${encodeURIComponent(st.server)}`).then((r) => r.json());
  st.lane = st.data.lanes[0];
  renderLanes(); renderObjectives(); refresh();
}

function renderLanes() {
  $("#lanes").innerHTML = st.data.lanes.map((l) => `<button data-l="${esc(l)}" class="${l === st.lane ? "on" : ""}">Lattice ${esc(l)}</button>`).join("");
  document.querySelectorAll("#lanes button").forEach((b) => b.onclick = () => { st.lane = b.dataset.l; renderLanes(); renderObjectives(); });
}

function renderObjectives() {
  const box = $("#objectives");
  box.innerHTML = st.data.objectives.filter((o) => o.lane === st.lane).map((o) => {
    const cps = o.cps.map((c) => (c.generic ? `<i>${esc(c.code)}</i>` : `${esc(c.name)} <i>${esc(c.code)}</i>`)).join(" · ");
    const shown = o.display_name === o.label ? "" : o.display_name !== o.name ? `${esc(o.display_name)} <span class="k">(${esc(o.name)})</span>` : esc(o.name);
    return `<div class="obj ${st.sel.includes(o.code) ? "sel" : ""}" data-c="${esc(o.code)}">
      <div class="t"><span class="c">${esc(o.label)}</span><span class="n">${shown}</span><span class="k">${o.cps.length} CPs</span></div>
      <div class="cps">${cps}</div></div>`;
  }).join("");
  box.querySelectorAll(".obj").forEach((d) => d.onclick = () => toggle(d.dataset.c));
}

function toggle(code) {
  const i = st.sel.indexOf(code);
  if (i >= 0) st.sel.splice(i, 1); else st.sel.push(code);
  $("#quick").value = st.sel.map((c) => labelOf(c)).join(" ");
  renderObjectives(); refresh();
}
const labelOf = (code) => { const o = st.data.objectives.find((x) => x.code === code); return o ? o.label : code; };

function onQuick() {
  const known = new Map(st.data.objectives.map((o) => [o.code, o]));
  const toks = $("#quick").value.toUpperCase().split(/[\s,]+/).filter(Boolean);
  const bad = [], ok = [];
  for (const t of toks) {
    const m = t.replace(/^OBJ/, "").match(/^([A-Z]+)0*([0-9]+)$/);   // A07 and A7 are the same objective
    const code = m ? m[1] + m[2] : t;
    if (known.has(code)) { if (!ok.includes(code)) ok.push(code); } else bad.push(t);
  }
  st.sel = ok;
  const m = $("#quickmsg");
  m.className = "msg" + (bad.length ? " bad" : "");
  m.textContent = bad.length ? `Unknown: ${bad.join(", ")}` : "";
  renderObjectives(); refresh();
}

function renderTray(pv) {
  const byCode = new Map(st.data.objectives.map((o) => [o.code, o]));
  $("#trayList").innerHTML = st.sel.map((c, i) => {
    const o = byCode.get(c);
    return `<li><span><b>${esc(o.label)}</b> ${o.display_name === o.label ? "" : esc(o.display_name) + " "}· ${o.cps.length}</span>
      <button data-a="up" data-i="${i}">↑</button><button data-a="down" data-i="${i}">↓</button><button data-a="rm" data-i="${i}">✕</button></li>`;
  }).join("");
  $("#trayList").querySelectorAll("button").forEach((b) => b.onclick = () => {
    const i = +b.dataset.i, a = b.dataset.a;
    if (a === "rm") st.sel.splice(i, 1);
    else { const j = a === "up" ? i - 1 : i + 1; if (j >= 0 && j < st.sel.length) [st.sel[i], st.sel[j]] = [st.sel[j], st.sel[i]]; }
    $("#quick").value = st.sel.map((c) => labelOf(c)).join(" "); renderObjectives(); refresh();
  });
  const c = $("#counter"), box = $("#counts");
  c.textContent = ""; c.className = "";
  if (pv && pv.counts) {
    const n = pv.counts, split = n.dest_capacity != null;
    const rows = [[n.cps, "CPs"], [n.sites, "QRF/supply"], ...(split ? [] : [[n.airports, "airports"], [n.farps, "FARPs"]])]
      .filter(([v], i) => v || i === 0).map(([v, l]) => `<li>${v} ${l}</li>`);
    const tot = (v, cap, label, bad) => `<li class="total ${bad}">${v}${cap ? "/" + cap : ""} ${label}</li>`;
    rows.push(tot(n.total, pv.capacity, split ? "STEERPOINTS" : "TOTAL", pv.over ? "over" : pv.over_soft ? "soft" : ""));
    if (split) {
      rows.push(tot(n.dest, n.dest_capacity, "DESTINATIONS", n.dest > n.dest_capacity ? "over" : ""));
    }
    if (n.dropped) rows.push(`<li class="soft">${n.dropped} more did not fit</li>`);
    box.innerHTML = rows.join("");
  } else box.innerHTML = "";
}

let seq = 0;
async function refresh() {
  const mine = ++seq;
  if (!st.sel.length) {
    renderTray(null); $("#pv tbody").innerHTML = ""; $("#afBox").hidden = true; $("#fpBox").hidden = true; $("#stBox").hidden = true; $("#saBox").hidden = true; $("#warn").textContent = ""; setActions(true); return;
  }
  try {
    const pv = await jpost("/api/preview", { server: st.server, airframe: st.airframe, objectives: st.sel, qrf_supply: qrfOn() }).then((r) => r.json());
    if (mine !== seq) return;
    renderTray(pv);
    $("#pv tbody").innerHTML = pv.points.map((p) =>
      `<tr><td>${esc(p.slot)}</td><td>${esc(p.objective)}</td><td>${p.cp_generic ? "–" : esc(p.cp_name)}</td><td class="code">${esc(p.code || "")}</td><td>${p.elev_ft}</td></tr>`).join("");
    const sts = pv.sites || [];
    $("#stBox").hidden = !sts.length;
    $("#stSum").textContent = `Enemy QRF and supply bases: ${sts.length} within range of your objectives` + (sts.some((s) => !s.slot) ? `, ${sts.filter((s) => !s.slot).length} without room` : "");
    $("#st tbody").innerHTML = sts.map((s) =>
      `<tr><td>${s.slot ? esc(s.slot) : "no room"}</td><td>${esc(s.name)} <small>${esc(s.objectives.join(" "))} · ${s.distance_nm} nm</small></td><td class="code">${esc(s.code)}</td><td>${s.elev_ft}</td></tr>`).join("");
    const sas = pv.spawn_airfields || [];
    $("#saBox").hidden = !sas.length;
    $("#saSum").textContent = `Airfields with your slots near your objectives: ${sas.length}` + (sas.some((s) => !s.slot) ? `, ${sas.filter((s) => !s.slot).length} without room` : "");
    $("#sa tbody").innerHTML = sas.map((s) =>
      `<tr><td>${s.slot ? esc(s.slot) : "no room"}</td><td>${esc(s.name)} <small>${esc(s.objectives.join(" "))} · ${s.distance_nm} nm</small></td><td class="code">${esc(s.code)}</td><td>${s.elev_ft}</td></tr>`).join("");
    const fps = pv.farps || [];
    $("#fpBox").hidden = !fps.length;
    $("#fpSum").textContent = `FARPs (fuel and ammo): ${fps.length} open near your objectives` + (fps.some((f) => !f.slot) ? `, ${fps.filter((f) => !f.slot).length} without room` : "");
    $("#fp tbody").innerHTML = fps.map((f) =>
      `<tr><td>${f.slot ? esc(f.slot) : "no room"}</td><td>${esc(f.name)} <small>${esc(f.objectives.join(" "))} · ${f.distance_nm} nm</small></td><td class="code">${esc(f.code)}</td><td>${f.elev_ft}</td></tr>`).join("");
    const afs = pv.airfields || [];
    $("#afBox").hidden = !afs.length;
    $("#afSum").textContent = `Destinations: ${afs.length} airfields (${afs.filter((a) => a.spawn).length} with your slots)`;
    $("#af tbody").innerHTML = afs.map((a) =>
      `<tr><td>${esc(a.slot)}</td><td>${esc(a.name)}${a.spawn ? " <b>slot</b>" : ""} <small>${a.distance_nm} nm</small></td><td class="code">${esc(a.code)}</td><td>${a.elev_ft}</td></tr>`).join("");
    const w = $("#warn");
    if (pv.over) { w.className = "msg bad"; w.textContent = `Over capacity: remove ${pv.used - pv.capacity} CPs.`; }
    else if (pv.over_soft) { w.className = "msg warn"; w.textContent = `Above ${pv.soft_capacity}: the last datalink-reserved slots may be overwritten in flight.`; }
    else { w.className = "msg"; w.textContent = ""; }
    setActions(pv.over);
  } catch (e) {
    if (mine === seq) { $("#warn").className = "msg bad"; $("#warn").textContent = e.message; setActions(true); }
  }
}

function setActions(blocked) {
  $("#download").disabled = blocked;
  $("#send").disabled = blocked || !st.local.dcs_dir;
  $("#send").title = st.local.dcs_dir ? `Writes into ${st.local.dtc_dir}` : "DCS folder not found: set it in the footer";
}

async function sendToDcs() {
  const res = $("#result");
  try {
    const r = await jpost("/api/build", { server: st.server, airframe: st.airframe, objectives: st.sel, deliver: "dcs", settings: st.edits, qrf_supply: qrfOn() }).then((x) => x.json());
    res.className = "msg"; res.textContent = `Wrote ${r.path}` + (r.pruned ? ` (removed ${r.pruned} old GF_ files)` : "") + ". In the cockpit, load it from the DTC list (Apache: DTU page, Viper: DTE page).";
  } catch (e) { res.className = "msg bad"; res.textContent = e.message; }
}

async function download() {
  const res = $("#result");
  try {
    const r = await jpost("/api/build", { server: st.server, airframe: st.airframe, objectives: st.sel, deliver: "download", settings: st.edits, qrf_supply: qrfOn() });
    const cd = r.headers.get("content-disposition") || "";
    const name = (cd.match(/filename="([^"]+)"/) || [])[1] || "grayflag.dtc";
    const url = URL.createObjectURL(await r.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    res.className = "msg"; res.textContent = `Built ${name}`;
  } catch (e) { res.className = "msg bad"; res.textContent = e.message; }
}

// ------------------------------------------------------------ settings
const valOf = (p) => (st.settings.values[p] == null ? "" : st.settings.values[p]);
async function loadSettings() {
  st.settings = await api(`/api/airframes/${encodeURIComponent(st.airframe)}/settings`).then((r) => r.json());
  st.edits = {};
  $("#setbar").hidden = !st.settings.schema.length;                 // an aircraft with no settings (yet) shows no buttons
  if (!st.settings.schema.length) {
    $("#settings").innerHTML = `<p class="msg">No settings for this aircraft yet: everything but the waypoints comes from the base DTC.</p>`;
    $("#setmsg").textContent = "";
    return;
  }
  const groups = new Map();
  for (const f of st.settings.schema) {
    if (!groups.has(f.group)) groups.set(f.group, new Map());
    const g = groups.get(f.group);
    if (!g.has(f.sub)) g.set(f.sub, []);
    g.get(f.sub).push(f);
  }
  let html = "";
  for (const [g, subs] of groups) {
    html += `<details class="grpbox"><summary>${esc(g)}</summary>`;
    const all = [...subs.values()].flat();
    if (all.some((f) => f.row)) {          // tables: one column per sub, one row per row label, one table per block
      const blocks = [...new Set(all.map((f) => f.block || ""))];
      for (const blk of blocks) {
        const fs = all.filter((f) => (f.block || "") === blk);
        const cols = [...new Set(fs.map((f) => f.sub))], rows = [...new Set(fs.map((f) => f.row))];
        const show = (f) => valOf(f.path);
        const cell = (r, c) => { const f = fs.find((x) => x.row === r && x.sub === c);
          return f ? `<td><input data-p="${esc(f.path)}" inputmode="decimal" value="${esc(show(f))}"></td>` : "<td></td>"; };
        html += (blk ? `<div class="grp">${esc(blk)}</div>` : "") +
          `<table class="grid ${g === "Countermeasures" ? "cm" : ""}"><thead><tr><th></th>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
          rows.map((r) => `<tr><th>${esc(r)}</th>${cols.map((c) => cell(r, c)).join("")}</tr>`).join("") + `</tbody></table>`;
      }
      if (g === "Countermeasures") html += `<div class="msg">BQ burst quantity, BI burst interval (s), SQ salvo quantity, SI salvo interval (s). 0 = off. Columns are manual programs 1-6.</div>`;
      html += `</details>`; continue;
    }
    for (const [sub, fields] of subs) {
      const one = "";
      html += `<div class="sub${one}">${sub ? `<b>${esc(sub)}</b>` : ""}` + fields.map((f) => {
        const laser = f.type === "laser";
        const attrs = laser ? 'maxlength="4" inputmode="numeric" pattern="[0-9]{4}" size="4" class="laser"' : 'inputmode="decimal"';
        return `<label>${esc(f.label.replace(/ \(MHz\)$/, ""))}<br><input data-p="${esc(f.path)}" ${attrs} value="${esc(valOf(f.path))}"></label>`;
      }).join("") + `</div>`;
    }
    html += `</details>`;
  }
  $("#settings").innerHTML = html;
  $("#settings").querySelectorAll("input").forEach((i) => i.oninput = () => {
    const p = i.dataset.p;
    if (i.value.trim() === String(valOf(p))) { delete st.edits[p]; i.classList.remove("dirty"); }
    else { st.edits[p] = i.value.trim(); i.classList.add("dirty"); }
  });
  $("#setmsg").textContent = st.settings.has_saved ? "Using your saved defaults." : "Using the Grayflag standard.";
}

function allValues() {
  const v = {};
  $("#settings").querySelectorAll("input").forEach((i) => v[i.dataset.p] = i.value.trim());
  return v;
}

async function saveDefaults() {
  const m = $("#setmsg");
  try {
    await jpost(`/api/airframes/${encodeURIComponent(st.airframe)}/settings/defaults`, allValues(), "PUT");
    await loadSettings(); m.className = "msg"; m.textContent = "Saved as your defaults.";
  } catch (e) { m.className = "msg bad"; m.textContent = e.message; }
}

async function resetDefaults() {
  if (!confirm("Discard your saved defaults and go back to the Grayflag standard?")) return;
  try {
    await api(`/api/airframes/${encodeURIComponent(st.airframe)}/settings/defaults`, { method: "DELETE" });
    await loadSettings(); $("#setmsg").className = "msg"; $("#setmsg").textContent = "Reset to the Grayflag standard.";
  } catch (e) { $("#setmsg").className = "msg bad"; $("#setmsg").textContent = e.message; }
}

init().catch((e) => { document.body.insertAdjacentHTML("afterbegin", `<p class="msg bad" style="padding:16px">${esc(e.message)}</p>`); });


// ------------------------------------------------------------ this PC: DCS folder and harvest
async function initLocal() {
  st.local = await api("/api/local").then((r) => r.json());
  $("#localSum").textContent = st.local.dcs_dir ? `DCS folder: ${st.local.dcs_dir}` : "DCS folder not found: set it here";
  $("#dcsDir").value = st.local.dcs_dir || "";
  $("#aboutLine").innerHTML = `grayflag-dtc ${esc(st.local.version)} · <a href="https://github.com/Stains02/grayflag-dtc/releases" target="_blank" rel="noopener">releases</a> · data folder ${esc(st.local.data_dir)}`;
  if (!st.local.dcs_dir) $("#local").open = true;
  setActions($("#download").disabled);
  $("#saveDcs").onclick = async () => {
    const m = $("#localMsg");
    try { await jpost("/api/local", { dcs_dir: $("#dcsDir").value }, "PUT"); m.className = "msg"; m.textContent = "Saved."; await initLocal(); }
    catch (e) { m.className = "msg bad"; m.textContent = e.message; }
  };
  $("#hvPrepare").onclick = hvPrepare;
  $("#hvCollect").onclick = hvCollect;
  $("#hvTrack").onchange = hvSuggest;
  let loaded = false;
  $("#harvest").addEventListener("toggle", () => { if ($("#harvest").open && !loaded) { loaded = true; loadTracks(); } });
}

async function loadTracks() {
  const tracks = await api("/api/harvest/tracks").then((r) => r.json());
  $("#hvTrack").innerHTML = tracks.length
    ? tracks.map((t) => `<option value="${esc(t.path)}">${esc(t.name)} (${t.mb} MB)</option>`).join("")
    : `<option value="">no tracks found in your DCS folder</option>`;
  const sc = await api("/api/harvest/scenarios").then((r) => r.json());
  st.scenarios = sc;
  $("#hvIds").innerHTML = sc.map((x) => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("");
  $("#hvId").oninput = () => {              // typing an existing id refreshes that scenario: keep its name and tag
    const k = st.servers.find((x) => x.id === $("#hvId").value.trim());
    if (k) { $("#hvName").value = k.name; $("#hvTag").value = k.tag || ""; }
  };
  hvSuggest();
}

function hvSuggest() {
  const opt = $("#hvTrack").selectedOptions[0];
  if (!opt || !opt.value) return;
  const base = opt.textContent.replace(/\s*\(.*$/, "").replace(/\.trk$/i, "").replace(/\s+A-\d{8}-\d{6}$/, "");
  const name = base.replace(/^Grayflag\s+/i, "");
  $("#hvName").value = name;
  $("#hvId").value = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  $("#hvTag").value = name.split(/\s+/).map((w) => w[0]).join("").toUpperCase().slice(0, 4);
}

async function hvPrepare() {
  const m = $("#hvMsg1");
  try {
    const r = await jpost("/api/harvest/prepare", { track: $("#hvTrack").value, server_id: $("#hvId").value.trim(), name: $("#hvName").value.trim(), tag: $("#hvTag").value.trim(), keep_scripts: $("#hvKeep").checked }).then((x) => x.json());
    m.className = "msg"; m.textContent = `Wrote ${r.mission}`;
  } catch (e) { m.className = "msg bad"; m.textContent = e.message; }
}

async function hvCollect() {
  const m = $("#hvMsg3");
  try {
    const r = await jpost("/api/harvest/collect", { server_id: $("#hvId").value.trim(), force: $("#hvForce").checked }).then((x) => x.json());
    m.className = "msg" + (r.problems.length ? " warn" : "");
    m.textContent = r.summary.replace(/\n/g, " | ") + (r.problems.length ? ` | ${r.problems.length} problem(s): ${r.problems.slice(0, 3).join("; ")}` : "") + (r.enabled ? " | scenario added" : " | scenario NOT enabled");
    if (r.enabled) { st.servers = await api("/api/servers").then((x) => x.json()); $("#server").innerHTML = serverOptions(); $("#server").value = st.server; }
  } catch (e) { m.className = "msg bad"; m.textContent = e.message; }
}
