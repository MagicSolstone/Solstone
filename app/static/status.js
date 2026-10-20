/* Solstone — public live status page. No sign-in: shows one server at a time on a big
   screen, refreshing every few seconds. Everything comes from /api/public/*, which only
   works while an admin has the status page turned on. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const POLL_MS = 5000;
// Skins on this page come through the public route, which only serves players of visible servers.
skinSource = (p) => p.uuid && st.sid ? `/api/public/skin/${encodeURIComponent(st.sid)}/${String(p.uuid).replace(/-/g, "")}.png` : null;
const st = { servers: [], sid: null, board: null, prevOnline: null, prevEventTs: 0, fetchedAt: 0, tod: null, todAt: 0, scene: null, map: null };

// ------------------------------------------------------------------ formatting
function fmtSpan(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return h ? `${h} h ${m} min` : m ? `${m} min` : "under a minute";
}
function fmtAgo(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : `${d} days ago`;
}
const hm = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const humanize = (s) => String(s).replace(/^.*[:/]/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];
function dimName(id) {
  const n = String(id || "minecraft:overworld").split(":").pop();
  return { overworld: "Overworld", the_nether: "The Nether", the_end: "The End" }[n] || humanize(n);
}
function dimKey(id) {
  const n = String(id || "minecraft:overworld").split(":").pop();
  return ["overworld", "the_nether", "the_end"].includes(n) ? n : "other";
}
function clockText(t) {
  const hour = Math.floor((t / 1000 + 6) % 24), min = Math.floor(((t % 1000) / 1000) * 60);
  return new Date(2000, 0, 1, hour, min).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function phaseOf(t) { return t < 12000 ? "Daytime" : t < 13000 ? "Sunset" : t < 23000 ? "Night" : "Sunrise"; }
function tpsInfo(tps) {
  if (tps == null) return null;
  if (tps >= 19.5) return { label: "Running smoothly", cls: "good" };
  if (tps >= 15) return { label: "A little laggy", cls: "warn" };
  return { label: "Very laggy", cls: "bad" };
}
const bodyUrl = (p) => `https://mc-heads.net/body/${p.uuid ? p.uuid.replace(/-/g, "") : encodeURIComponent(p.name)}/220`;
function itemImg(it, cls = "") {
  if (!it) return "";
  const [ns, n] = it.id.includes(":") ? it.id.split(":") : ["minecraft", it.id];
  return `<span class="sp-item ${it.glint ? "glint" : ""} ${cls}" style="--mask:url('/api/public/item/${encodeURIComponent(st.sid)}/${encodeURIComponent(ns)}/${encodeURIComponent(n)}.png')" title="${esc(it.name)}${it.count > 1 ? ` ×${it.count}` : ""}">
    <img src="/api/public/item/${encodeURIComponent(st.sid)}/${encodeURIComponent(ns)}/${encodeURIComponent(n)}.png" alt="" onerror="this.parentElement.classList.add('missing');this.remove()"></span>`;
}

// ------------------------------------------------------------------ data
async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) { const e = new Error(`${r.status}`); e.status = r.status; throw e; }
  return r.json();
}
function sidFromPath() {
  const m = location.pathname.match(/^\/status\/([^/]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}
async function loadServers() {
  try { const d = await getJSON("/api/public/status"); st.servers = d.servers || []; } catch { /* keep the last list */ }
  if (!st.sid || !st.servers.some((s) => s.id === st.sid)) {
    const want = sidFromPath();
    const pick = st.servers.find((s) => s.id === want)
      || [...st.servers].sort((a, b) => (b.online || 0) - (a.online || 0) || (b.running !== false) - (a.running !== false))[0];
    st.sid = pick?.id || null;
  }
  renderServerTabs();
}
function renderServerTabs() {
  const nav = $("#sp-servers");
  nav.innerHTML = st.servers.length > 1 ? st.servers.map((s) => {
    const dot = s.crashed ? "crash" : s.running !== false ? "on" : "";
    return `<a href="/status/${encodeURIComponent(s.id)}" data-sid="${esc(s.id)}" ${s.id === st.sid ? 'aria-current="page"' : ""}>
      <span class="status-dot ${dot}"></span>${esc(s.name)}${s.running !== false && s.online ? `<b>${s.online}</b>` : ""}</a>`;
  }).join("") : "";
}
$("#sp-servers")?.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-sid]");
  if (!a) return;
  e.preventDefault();
  if (a.dataset.sid === st.sid) return;
  st.sid = a.dataset.sid; st.board = null; st.prevOnline = null; st.prevEventTs = 0; st.map = null;
  delete $("#sp-main").dataset.sid;
  history.pushState(null, "", a.getAttribute("href"));
  renderServerTabs();
  poll();
});
addEventListener("popstate", () => { st.sid = null; loadServers().then(poll); });

let pollTimer = 0;
async function poll() {
  clearTimeout(pollTimer);
  if (!st.sid) {
    $("#sp-main").innerHTML = `<div class="sp-empty glass"><h2>No servers to show</h2><p class="muted">Servers appear here once Solstone finds them.</p></div>`;
    pollTimer = setTimeout(async () => { await loadServers(); poll(); }, 15000);
    return;
  }
  const sid = st.sid;
  try {
    const b = await getJSON(`/api/public/status/${encodeURIComponent(sid)}`);
    if (sid !== st.sid) return;
    st.fetchedAt = Date.now();
    noticeChanges(b);
    st.board = b;
    if (b.world) { st.tod = b.world.time_of_day; st.todAt = Date.now(); } else st.tod = null;
    render(b);
  } catch (e) {
    if (e.status === 404) { location.reload(); return; }   // turned off, or the server went away
    $("#sp-updated").textContent = "Can't reach Solstone, retrying…";
  }
  pollTimer = setTimeout(poll, document.hidden ? POLL_MS * 6 : POLL_MS);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });

// Fireworks for a join or a new advancement, so a big screen in the room notices.
function noticeChanges(b) {
  const names = new Set(b.players.map((p) => p.name));
  if (st.prevOnline) {
    const joined = [...names].filter((n) => !st.prevOnline.has(n));
    if (joined.length) { st.scene?.celebrate(4); toast(`${joined.map(esc).join(", ")} joined the game`); }
  }
  const newest = Math.max(0, ...b.recent.map((e) => e.ts));
  if (st.prevEventTs && newest > st.prevEventTs) {
    const adv = b.recent.find((e) => e.type === "advancement" && e.ts > st.prevEventTs);
    if (adv) { st.scene?.celebrate(2); toast(esc(adv.message)); }
  }
  st.prevOnline = names;
  st.prevEventTs = newest || st.prevEventTs;
}
let toastTimer = 0;
function toast(html) {
  const t = $("#sp-toast"); t.innerHTML = html; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), 6000);
}

// ------------------------------------------------------------------ rendering
const EVENT_ICON = { join: "→", leave: "←", death: "☠", advancement: "★", server: "⏻" };

// Sections are only replaced when their content changes, so the web map iframe and the
// position canvas aren't rebuilt on every refresh.
function setHtml(el, html) { if (el && el._html !== html) { el._html = html; el.innerHTML = html; } }
function render(b) {
  document.title = `${b.name} · Live status`;
  const main = $("#sp-main");
  if (main.dataset.sid !== b.id) {
    main.dataset.sid = b.id;
    main.innerHTML = `<div id="sp-hero"></div><div class="sp-grid"><section class="sp-col" id="sp-players" aria-label="Players online"></section>
      <aside class="sp-col"><div id="sp-mapwrap"></div><div id="sp-webwrap"></div><div id="sp-feedwrap"></div></aside></div>`;
  }
  setHtml($("#sp-hero"), heroHtml(b));
  setHtml($("#sp-players"), playersHtml(b));
  const hasPos = b.players.some((p) => p.position);
  setHtml($("#sp-mapwrap"), hasPos ? `<section class="sp-panel glass"><div class="sp-h"><h2>Where everyone is</h2><span class="muted" id="sp-map-dim"></span></div><div class="sp-map" id="sp-map"></div></section>` : "");
  setHtml($("#sp-webwrap"), b.web_map ? `<section class="sp-panel glass"><div class="sp-h"><h2>World map</h2><a class="muted" href="${esc(b.web_map)}" target="_blank" rel="noopener">Open full screen</a></div><iframe class="sp-webmap" src="${esc(b.web_map)}" title="World map" loading="lazy"></iframe></section>` : "");
  setHtml($("#sp-feedwrap"), b.recent.length ? `<section class="sp-panel glass"><div class="sp-h"><h2>Recent activity</h2></div><ul class="sp-feed">${b.recent.map((e) => `
    <li class="ev-${esc(e.type)}"><span class="ev-icon" aria-hidden="true">${EVENT_ICON[e.type] || "•"}</span><span class="ev-time">${esc(fmtAgo(e.ts))}</span><span>${esc(e.message).replace(/\[(.+)\]$/, '<span class="adv-name">$1</span>')}</span></li>`).join("")}</ul></section>` : "");
  if (hasPos) mountMap($("#sp-map"), b, st.map);
  else st.map = null;
  tick();
}

function heroHtml(b) {
  const on = b.running !== false;
  const pill = !on ? `<span class="state-pill"><span class="status-dot ${b.crashed ? "crash" : ""}"></span>${b.crashed ? "Crashed" : "Offline"}</span>`
    : `<span class="state-pill live"><span class="status-dot on"></span>Online</span>`;
  const icon = b.has_icon ? `<img src="/api/public/icon/${encodeURIComponent(b.id)}.png" alt="">` : esc((b.name || "?")[0]);
  const tps = on ? tpsInfo(b.tps) : null;
  const w = b.world;
  const weather = w ? (w.thundering ? "Thunderstorm" : w.raining ? "Raining" : w.raining === false ? "Clear skies" : "") : "";
  const tiles = [
    `<div class="sp-tile"><div class="v">${on ? `${b.online_count}<small> / ${b.max ?? "?"}</small>` : "–"}</div><div class="k">Playing now</div></div>`,
    w ? `<div class="sp-tile sky-tile ${w.time_of_day >= 13000 && w.time_of_day < 23000 ? "night" : ""}"><div class="v">Day ${w.day.toLocaleString()}</div><div class="k"><span id="sp-clock">${esc(clockText(w.time_of_day))}</span> · <span id="sp-phase">${esc(phaseOf(w.time_of_day))}</span>${weather ? ` · ${esc(weather)}` : ""}</div></div>` : "",
    tps ? `<div class="sp-tile"><div class="v">${b.tps.toFixed(1)}<small> TPS</small></div><div class="k status ${tps.cls}">${tps.label}</div></div>` : "",
    b.version ? `<div class="sp-tile"><div class="v sm">${b.java ? "Minecraft " : ""}${esc(b.version)}</div><div class="k">${esc(b.loader || b.game || "")}</div></div>` : "",
    on && b.started ? `<div class="sp-tile"><div class="v sm" id="sp-uptime" data-since="${esc(b.started)}"></div><div class="k">Server up</div></div>` : "",
  ].filter(Boolean).join("");
  return `<header class="sp-hero glass">
    <div class="sp-hero-id"><span class="sp-icon">${icon}</span><div><h1>${esc(b.name)}</h1><div class="motd">${motdHtml(b.motd)}</div></div>${pill}</div>
    <div class="sp-tiles">${tiles}</div></header>`;
}

function playersHtml(b) {
  if (b.running === false) return `<div class="sp-empty glass"><h2>${b.crashed ? "The server crashed" : "The server is offline"}</h2><p class="muted">Check back later.</p>${recentlyHtml(b)}</div>`;
  if (!b.players.length) return `<div class="sp-empty glass"><h2>Nobody's playing right now</h2><p class="muted">The server is up. Players show here the moment they join.</p>${recentlyHtml(b)}</div>`;
  return `<div class="sp-players ${b.players.length === 1 ? "solo" : ""}">${b.players.map(playerCardHtml).join("")}</div>${b.recently.length ? `<div class="sp-recent-wrap">${recentlyHtml(b)}</div>` : ""}`;
}
function recentlyHtml(b) {
  if (!b.recently.length) return "";
  return `<div class="sp-recently"><h3>Played recently</h3><ul>${b.recently.map((p) => `<li>${faceHtml(p, 32)}<span><b>${esc(p.name)}</b><small>${esc(fmtAgo(p.last_seen))}</small></span></li>`).join("")}</ul></div>`;
}
function playerCardHtml(p) {
  const vitals = p.health != null
    ? `<div class="sp-vitals">${heartsHtml(p.health, p.max_health)}${foodHtml(p.food)}${xpHtml(p.xp_level, p.xp_progress)}</div>` : "";
  const since = p.since ? `Playing for <span data-since-ts="${p.since}">${esc(fmtSpan(Date.now() / 1000 - p.since))}</span>` : "Playing now";
  const chips = [
    p.dimension ? `<span class="chip dim-tag dim-${dimKey(p.dimension)}">${esc(dimName(p.dimension))}</span>` : "",
    p.position ? `<span class="chip">X <b>${Math.round(p.position.x)}</b> Y <b>${Math.round(p.position.y)}</b> Z <b>${Math.round(p.position.z)}</b></span>` : "",
    p.gamemode && p.gamemode !== "survival" ? `<span class="chip">${esc(humanize(p.gamemode))}</span>` : "",
  ].join("");
  const gear = p.held || p.armor?.some(Boolean)
    ? `<div class="sp-gear">${p.held ? `<span class="sp-held">${itemImg(p.held)}<span><small>Holding</small><b>${esc(p.held.name)}</b>${p.held.count > 1 ? ` ×${p.held.count}` : ""}</span></span>` : ""}
       ${p.armor?.some(Boolean) ? `<span class="sp-armor" aria-label="Armour">${p.armor.map((a) => a ? itemImg(a) : `<span class="sp-item empty"></span>`).join("")}</span>` : ""}</div>` : "";
  const effects = p.effects?.length ? `<div class="chips sp-effects">${p.effects.map((e) => `<span class="chip">${esc(e.name)}${e.amplifier ? ` ${ROMAN[e.amplifier + 1] || e.amplifier + 1}` : ""}</span>`).join("")}</div>` : "";
  return `<article class="sp-player glass">
    <div class="sp-body"><img src="${bodyUrl(p)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('span'), { innerHTML: this.dataset.face }).firstChild)" data-face="${esc(faceHtml(p, 88))}"></div>
    <div class="sp-info">
      <h2>${esc(p.name)}${p.xp_level != null ? `<span class="lvl" title="Level">${p.xp_level}</span>` : ""}</h2>
      <div class="sp-meta"><span class="live-tag"><span class="status-dot on"></span>${since}</span>${p.today_seconds > 60 ? `<span>${esc(fmtSpan(p.today_seconds))} today</span>` : ""}</div>
      ${vitals}
      <div class="chips">${chips}</div>
      ${gear}${effects}
    </div></article>`;
}

// Once a second: "updated 3 s ago", the in-game clock (20 ticks per second), play timers.
function tick() {
  if (st.fetchedAt) {
    const s = Math.round((Date.now() - st.fetchedAt) / 1000);
    $("#sp-updated").innerHTML = `<span class="status-dot on"></span>Live${s > 2 ? ` · updated ${s} s ago` : ""}`;
  }
  if (st.tod != null && st.board?.online_count) {
    const t = Math.floor(st.tod + ((Date.now() - st.todAt) / 1000) * 20) % 24000;
    const c = $("#sp-clock"), ph = $("#sp-phase");
    if (c) c.textContent = clockText(t);
    if (ph) ph.textContent = phaseOf(t);
  }
  document.querySelectorAll("[data-since-ts]").forEach((el) => { el.textContent = fmtSpan(Date.now() / 1000 - Number(el.dataset.sinceTs)); });
  const up = $("#sp-uptime");
  if (up) {
    const since = new Date(up.dataset.since.replace(" ", "T")).getTime();
    up.textContent = Number.isFinite(since) ? fmtSpan((Date.now() - since) / 1000) : "";
  }
}
setInterval(tick, 1000);

// ------------------------------------------------------------------ position map
// A top-down plot (north up) of everyone in one dimension, with world spawn. Heads glide
// to their new spots between updates instead of jumping.
function mountMap(el, b, prev) {
  const dims = {};
  for (const p of b.players) if (p.position) (dims[dimKey(p.dimension)] ||= { id: p.dimension, players: [] }).players.push(p);
  const order = Object.keys(dims).sort((a, c) => dims[c].players.length - dims[a].players.length || (a === "overworld" ? -1 : 1));
  const dim = prev && dims[prev.dim] ? prev.dim : order[0];
  const sig = `${order.join(",")}|${dim}|${order.map((k) => dims[k].players.length).join(",")}`;
  if (el._sig !== sig || !$("canvas", el)) {
    el._sig = sig;
    el.innerHTML = `${order.length > 1 ? `<div class="seg sp-dims" role="group" aria-label="Dimension">${order.map((k) => `<button data-dim="${k}" aria-pressed="${k === dim}">${esc(dimName(dims[k].id))} · ${dims[k].players.length}</button>`).join("")}</div>` : ""}
    <canvas id="sp-map-canvas" role="img" aria-label="Map of player positions"></canvas>`;
    el.querySelectorAll("[data-dim]").forEach((btn) => btn.addEventListener("click", () => { st.map.dim = btn.dataset.dim; st.map.shown = {}; st.map.bounds = null; mountMap(el, st.board, st.map); }));
  }
  const cv = $("canvas", el);
  const map = prev || { heads: {}, shown: {}, bounds: null };
  st.map = map;
  map.dim = dim;
  map.players = dims[dim].players;
  map.spawn = dim === "overworld" ? b.spawn : null;
  map.anim = performance.now();
  $("#sp-map-dim").textContent = order.length === 1 ? dimName(dims[dim].id) : "";
  for (const p of map.players) {
    if (!map.heads[p.name]) {
      const img = new Image();
      img.onload = () => draw();
      img.onerror = () => { if (img.src !== backupSkin(p)) img.src = backupSkin(p); };
      img.src = skinSource(p) || backupSkin(p);
      map.heads[p.name] = img;
    }
    if (!map.shown[p.name]) map.shown[p.name] = { ...p.position };
  }
  const ctx = cv.getContext("2d");
  const colors = { overworld: ["#14261c", "#0c1712"], the_nether: ["#2a1212", "#170a0a"], the_end: ["#211a33", "#120e1d"], other: ["#18202e", "#0e131c"] }[dim];

  function targetBounds() {
    const pts = map.players.map((p) => p.position);
    if (map.spawn) pts.push(map.spawn);
    let x0 = Math.min(...pts.map((p) => p.x)), x1 = Math.max(...pts.map((p) => p.x));
    let z0 = Math.min(...pts.map((p) => p.z)), z1 = Math.max(...pts.map((p) => p.z));
    const span = Math.max(96, (x1 - x0) * 1.3, (z1 - z0) * 1.3);
    return { cx: (x0 + x1) / 2, cz: (z0 + z1) / 2, span };
  }
  function niceStep(span) {
    const raw = span / 5;
    for (const s of [16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384]) if (s >= raw) return s;
    return 32768;
  }
  function draw() {
    if (!cv.isConnected) return false;
    const dpr = devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const t = Math.min(1, (performance.now() - map.anim) / 900), ease = 1 - (1 - t) ** 3;
    const tb = targetBounds();
    const bnd = map.bounds ? { cx: map.bounds.cx + (tb.cx - map.bounds.cx) * ease, cz: map.bounds.cz + (tb.cz - map.bounds.cz) * ease, span: map.bounds.span + (tb.span - map.bounds.span) * ease } : tb;
    const scale = Math.min(w, h) / bnd.span;
    const sx = (x) => w / 2 + (x - bnd.cx) * scale, sz = (z) => h / 2 + (z - bnd.cz) * scale;
    const g = ctx.createRadialGradient(w / 2, h / 2, 10, w / 2, h / 2, Math.max(w, h) * 0.7);
    g.addColorStop(0, colors[0]); g.addColorStop(1, colors[1]);
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    // grid with block coordinates
    const step = niceStep(Math.max(w, h) / scale);
    ctx.strokeStyle = "rgba(255,255,255,.07)"; ctx.lineWidth = 1;
    ctx.fillStyle = "rgba(255,255,255,.35)"; ctx.font = "11px 'Atkinson Hyperlegible', system-ui";
    const wx0 = bnd.cx - w / 2 / scale, wz0 = bnd.cz - h / 2 / scale;
    for (let x = Math.ceil(wx0 / step) * step; sx(x) < w; x += step) { ctx.beginPath(); ctx.moveTo(Math.round(sx(x)) + 0.5, 0); ctx.lineTo(Math.round(sx(x)) + 0.5, h); ctx.stroke(); ctx.fillText(String(x), sx(x) + 4, h - 6); }
    for (let z = Math.ceil(wz0 / step) * step; sz(z) < h; z += step) { ctx.beginPath(); ctx.moveTo(0, Math.round(sz(z)) + 0.5); ctx.lineTo(w, Math.round(sz(z)) + 0.5); ctx.stroke(); ctx.fillText(String(z), 4, sz(z) - 4); }
    ctx.fillStyle = "rgba(255,255,255,.5)"; ctx.font = "bold 12px 'Atkinson Hyperlegible', system-ui"; ctx.fillText("N ↑", w - 34, 18);
    if (map.spawn) {
      const x = sx(map.spawn.x), y = sz(map.spawn.z);
      ctx.fillStyle = "#f2c14e"; ctx.beginPath(); ctx.moveTo(x, y - 7); ctx.lineTo(x + 7, y); ctx.lineTo(x, y + 7); ctx.lineTo(x - 7, y); ctx.closePath(); ctx.fill();
      ctx.fillStyle = "rgba(242,193,78,.9)"; ctx.font = "12px 'Atkinson Hyperlegible', system-ui"; ctx.fillText("Spawn", x + 10, y + 4);
    }
    ctx.font = "bold 13px 'Atkinson Hyperlegible', system-ui"; ctx.textAlign = "center";
    for (const p of map.players) {
      const from = map.shown[p.name], to = p.position;
      const cur = { x: from.x + (to.x - from.x) * ease, z: from.z + (to.z - from.z) * ease };
      if (t >= 1) map.shown[p.name] = { ...to };
      const x = sx(cur.x), y = sz(cur.z), s = 26;
      ctx.fillStyle = "rgba(0,0,0,.45)"; ctx.fillRect(x - s / 2 - 1, y - s / 2 + 2, s + 2, s + 2);
      ctx.fillStyle = "#fff"; ctx.fillRect(x - s / 2 - 2, y - s / 2 - 2, s + 4, s + 4);
      const img = map.heads[p.name];
      ctx.imageSmoothingEnabled = false;
      if (img?.complete && img.naturalWidth >= 64) {        // face, then the hat layer over it
        ctx.drawImage(img, 8, 8, 8, 8, x - s / 2, y - s / 2, s, s);
        ctx.drawImage(img, 40, 8, 8, 8, x - s / 2, y - s / 2, s, s);
      }
      else { ctx.fillStyle = "#4d74d6"; ctx.fillRect(x - s / 2, y - s / 2, s, s); }
      const label = p.name;
      const tw = ctx.measureText(label).width + 10;
      ctx.fillStyle = "rgba(8,10,18,.7)"; ctx.fillRect(x - tw / 2, y + s / 2 + 5, tw, 18);
      ctx.fillStyle = "#ebe6d9"; ctx.fillText(label, x, y + s / 2 + 18);
    }
    ctx.textAlign = "start";
    if (t >= 1) map.bounds = tb;
    return t < 1;
  }
  const loop = () => { if (draw()) requestAnimationFrame(loop); };
  if (!map.bounds) map.bounds = targetBounds();
  requestAnimationFrame(loop);
  if (!map.resizeBound) { map.resizeBound = true; addEventListener("resize", () => st.map === map && draw()); }
}

// ------------------------------------------------------------------ big-screen niceties
$("#sp-full")?.addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen?.();
  else document.documentElement.requestFullscreen?.().catch(() => {});
});
let wakeLock = null;
async function keepAwake() {
  try { if ("wakeLock" in navigator && !document.hidden) wakeLock = await navigator.wakeLock.request("screen"); } catch { /* optional */ }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && (!wakeLock || wakeLock.released)) keepAwake(); });

document.addEventListener("DOMContentLoaded", async () => {
  const sky = $("#status-sky");
  if (sky) {
    st.scene = startSkyScene(sky, { auto: false, sound: (t, i) => FWAudio.play(t, i) });
    startShowBar(st.scene, { key: "solstone-sky-status", defaultOn: true, hide: true,
      onEvent: (item) => { if (item.text && item.server_id === st.sid) toast(esc(item.text)); } });
  }
  keepAwake();
  await loadServers();
  poll();
  setInterval(loadServers, 30000);
});
