/* Solstone — public live status page. No sign-in: shows one server at a time on a big
   screen, refreshing every few seconds. Everything comes from /api/public/*, which only
   works while an admin has the status page turned on. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const POLL_MS = 5000;
// Skins on this page come through the public route, which only serves players of visible servers.
skinSource = (p) => p.uuid && st.sid ? `/api/public/skin/${encodeURIComponent(st.sid)}/${String(p.uuid).replace(/-/g, "")}.png` : null;
const st = { servers: [], sid: null, board: null, prevOnline: null, prevEventTs: 0, fetchedAt: 0, tod: null, todAt: 0, scene: null, map: null,
  tv: new URLSearchParams(location.search).has("tv"), tvCfg: { seconds: 15, slides: {}, rotate: false }, recap: null, recapAt: 0, leaders: null, leadersAt: 0, banners: null };

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
// The in-game time now: the server's reading plus however long ago it was taken (20 ticks a second while people play).
function nowTod(w) { return st.board?.online_count ? Math.floor(w.time_of_day + (w.age || 0) * 20) % 24000 : w.time_of_day; }
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
    <img src="/api/public/item/${encodeURIComponent(st.sid)}/${encodeURIComponent(ns)}/${encodeURIComponent(n)}.png" alt="" data-fail="missing"></span>`;
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
  try {
    const d = await getJSON("/api/public/status");
    // A wall screen stays open for days: when Solstone has been updated, load the new version.
    if (d.build && st.build && d.build !== st.build) { location.reload(); return; }
    st.build = d.build || st.build;
    st.servers = d.servers || []; if (d.tv) st.tvCfg = d.tv;
  } catch { /* keep the last list */ }
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
    return `<a href="/status/${encodeURIComponent(s.id)}${st.tv ? "?tv=1" : ""}" data-sid="${esc(s.id)}" ${s.id === st.sid ? 'aria-current="page"' : ""}>
      <span class="status-dot ${dot}"></span>${esc(s.name)}${s.running !== false && s.online ? `<b>${s.online}</b>` : ""}</a>`;
  }).join("") : "";
}
$("#sp-servers")?.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-sid]");
  if (!a) return;
  e.preventDefault();
  if (a.dataset.sid === st.sid) return;
  switchServer(a.dataset.sid, true);
});
function switchServer(sid, push) {
  st.sid = sid; st.board = null; st.prevOnline = null; st.prevEventTs = 0; st.map = null; st.recap = st.leaders = null; st.recapAt = st.leadersAt = 0;
  st.bar?.skyChanged(); st.banners?.refresh();
  delete $("#sp-main").dataset.sid;
  const url = `/status/${encodeURIComponent(sid)}${st.tv ? "?tv=1" : ""}`;
  if (push) history.pushState(null, "", url); else history.replaceState(null, "", url);
  renderServerTabs();
  poll();
}
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
    if (b.world) { st.tod = b.world.time_of_day; st.todAt = Date.now() - (b.world.age || 0) * 1000; } else st.tod = null;
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
const EVENT_ICON = { join: "→", leave: "←", death: "☠", advancement: "★", level: "⬆", server: "⏻", challenge: "🏆", race: "🏁" };

// Sections are only replaced when their content changes, so the web map iframe and the
// position canvas aren't rebuilt on every refresh.
function setHtml(el, html) { if (el && el._html !== html) { el._html = html; el.innerHTML = html; } }
function feedHtml(b) {
  return `<ul class="sp-feed">${b.recent.map((e) => `
    <li class="ev-${esc(e.type)}"><span class="ev-icon" aria-hidden="true">${EVENT_ICON[e.type] || "•"}</span><span class="ev-time">${esc(fmtAgo(e.ts))}</span><span>${esc(e.message).replace(/\[(.+)\]$/, '<span class="adv-name">$1</span>')}</span></li>`).join("")}</ul>`;
}
function render(b) {
  document.title = `${b.name} · Live status`;
  loadExtras(b);
  if (st.tv) { renderTv(b); return; }
  const main = $("#sp-main");
  if (main.dataset.sid !== b.id || main.dataset.mode !== "page") {
    main.dataset.sid = b.id; main.dataset.mode = "page";
    main.innerHTML = `<div id="sp-hero"></div><div class="sp-grid"><section class="sp-col" id="sp-players" aria-label="Players online"></section>
      <aside class="sp-col"><div id="sp-mapwrap"></div><div id="sp-webwrap"></div><div id="sp-recapwrap"></div><div id="sp-feedwrap"></div></aside></div>`;
  }
  setHtml($("#sp-hero"), heroHtml(b));
  setHtml($("#sp-players"), playersHtml(b));
  const hasPos = hasMap(b);
  setHtml($("#sp-mapwrap"), hasPos ? `<section class="sp-panel glass"><div class="sp-h"><h2>${mapPeople(b).away ? "Where everyone was last" : "Where everyone is"}</h2><span class="muted" id="sp-map-dim"></span></div><div class="sp-map" id="sp-map"></div></section>` : "");
  setHtml($("#sp-webwrap"), b.web_map ? `<section class="sp-panel glass"><div class="sp-h"><h2>World map</h2><a class="muted" href="${esc(b.web_map)}" target="_blank" rel="noopener">Open full screen</a></div><iframe class="sp-webmap" src="${esc(b.web_map)}" title="World map" loading="lazy"></iframe></section>` : "");
  setHtml($("#sp-feedwrap"), b.recent.length ? `<section class="sp-panel glass"><div class="sp-h"><h2>Recent activity</h2></div>${feedHtml(b)}</section>` : "");
  setHtml($("#sp-recapwrap"), recapPanelHtml());
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
    w ? `<div class="sp-tile sky-tile ${w.time_of_day >= 13000 && w.time_of_day < 23000 ? "night" : ""}"><div class="v">Day ${w.day.toLocaleString()}</div><div class="k"><span id="sp-clock">${esc(clockText(nowTod(w)))}</span> · <span id="sp-phase">${esc(phaseOf(nowTod(w)))}</span>${weather ? ` · ${esc(weather)}` : ""}</div></div>` : "",
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
    <div class="sp-body"><img src="${bodyUrl(p)}" alt="" data-fail="face" data-face="${esc(faceHtml(p, 88))}"></div>
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
  document.querySelectorAll(".tv-events [data-ago]").forEach((el) => { el.textContent = fmtAgo(Number(el.dataset.ago)); });
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
// Who goes on the map: everyone online, or with nobody on, where each recent player last was.
function mapPeople(b) {
  const on = b.players.filter((p) => p.position);
  return on.length ? { list: on, away: false } : { list: (b.recently || []).filter((p) => p.position), away: true };
}
const hasMap = (b) => mapPeople(b).list.length > 0 || !!b.spawn;

function mountMap(el, b, prev) {
  const dims = {};
  const people = mapPeople(b);
  for (const p of people.list) (dims[dimKey(p.dimension)] ||= { id: p.dimension || "minecraft:overworld", players: [] }).players.push(p);
  if (!Object.keys(dims).length && b.spawn) dims.overworld = { id: "minecraft:overworld", players: [] };     // nobody at all: around spawn
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
  map.away = people.away;
  map.race = b.race && (b.race.dim || "minecraft:overworld") === (dims[dim].id || "minecraft:overworld") ? b.race : null;
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
  // The real map under everything: region pictures drawn by Solstone from the world files.
  map.tiles ||= {}; map.regionSets ||= {};
  const dimId = dims[dim].id || "minecraft:overworld";
  const rs = map.regionSets[dimId];
  if (!rs || Date.now() - rs.at > 300000) {
    map.regionSets[dimId] = { at: Date.now(), set: rs?.set || null };
    fetch(`/api/public/map/${encodeURIComponent(b.id)}/regions?dim=${encodeURIComponent(dimId)}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null)).then((d) => { if (d) { map.regionSets[dimId] = { at: Date.now(), set: new Set(d.regions.map(([x, z]) => `${x},${z}`)) }; map.redraw?.(); } else map.regionSets[dimId].failed = true; }).catch(() => { map.regionSets[dimId].failed = true; });
  }
  const tileFor = (rx, rz) => {
    const key = `${dimId}|${rx},${rz}`;
    let t = map.tiles[key];
    if (t && (t.state === "loading" || t.state === "none" || (t.state === "wait" && Date.now() < t.retry))) return t;
    if (t && t.state === "ready" && Date.now() - t.at < 180000) return t;            // fresh enough; redrawn every few minutes
    t = map.tiles[key] = { ...(t || {}), state: t?.img ? "ready" : "loading", loading: true };
    fetch(`/api/public/map/${encodeURIComponent(b.id)}/tile?dim=${encodeURIComponent(dimId)}&x=${rx}&z=${rz}&t=${Math.floor(Date.now() / 60000)}`, { cache: "no-store" })
      .then(async (r) => {
        if (r.status === 202) { t.state = t.img ? "ready" : "wait"; t.retry = Date.now() + 3000; t.at = t.img ? Date.now() - 170000 : 0; setTimeout(() => map.redraw?.(), 3100); return; }
        if (!r.ok) { t.state = "none"; return; }
        const bmp = await createImageBitmap(await r.blob());
        // a 1x1 picture means nothing could be drawn; the server says why
        t.empty = bmp.width <= 1 ? { chunks: r.headers.get("X-Map-Chunks") || "", error: r.headers.get("X-Map-Error") || "" } : null;
        t.img = bmp; t.state = "ready"; t.at = Date.now(); map.redraw?.();
      }).catch(() => { t.state = "wait"; t.retry = Date.now() + 10000; });
    return t;
  };
  const colors = { overworld: ["#14261c", "#0c1712"], the_nether: ["#2a1212", "#170a0a"], the_end: ["#211a33", "#120e1d"], other: ["#18202e", "#0e131c"] }[dim];

  function targetBounds() {
    const pts = map.players.map((p) => p.position);
    if (map.spawn) pts.push(map.spawn);
    if (map.race) pts.push(...map.race.points);              // keep the whole course in view during a race
    let x0 = Math.min(...pts.map((p) => p.x)), x1 = Math.max(...pts.map((p) => p.x));
    let z0 = Math.min(...pts.map((p) => p.z)), z1 = Math.max(...pts.map((p) => p.z));
    const span = Math.max(map.players.length ? 96 : 384, (x1 - x0) * 1.3, (z1 - z0) * 1.3);
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
    // the world itself, one region picture (512 x 512 blocks) at a time
    const set = map.regionSets[dimId]?.set;
    if (set) {
      const x0 = bnd.cx - w / 2 / scale, x1 = bnd.cx + w / 2 / scale, z0 = bnd.cz - h / 2 / scale, z1 = bnd.cz + h / 2 / scale;
      let n = 0, waiting = 0, empty = null, drawn = 0;
      ctx.imageSmoothingEnabled = scale < 1;
      for (let rx = Math.floor(x0 / 512); rx <= Math.floor(x1 / 512) && n < 36; rx++) {
        for (let rz = Math.floor(z0 / 512); rz <= Math.floor(z1 / 512) && n < 36; rz++) {
          if (!set.has(`${rx},${rz}`)) continue;
          n++;
          const t = tileFor(rx, rz);
          if (!t.img && t.state !== "none") waiting++;
          if (t.img && t.empty) empty = t.empty; else if (t.img) drawn++;
          if (t.img) ctx.drawImage(t.img, Math.round(sx(rx * 512)), Math.round(sz(rz * 512)), Math.ceil(512 * scale) + 1, Math.ceil(512 * scale) + 1);
        }
      }
      ctx.fillStyle = "rgba(6, 10, 18, .18)"; ctx.fillRect(0, 0, w, h);          // a touch darker, so names and heads stand out
      map.note = waiting ? "Drawing the map…" : !n ? "No map here yet: this part of the world hasn't been saved"
        : empty && !drawn ? `The map came out empty (${empty.chunks.split("/")[1] || "?"} chunks, none drawn)${empty.error ? `: ${empty.error.slice(0, 70)}` : ""}` : "";
    } else map.note = map.regionSets[dimId]?.failed ? "The map isn't available" : "Loading the map…";
    // grid with block coordinates
    const step = niceStep(Math.max(w, h) / scale);
    ctx.strokeStyle = "rgba(255,255,255,.07)"; ctx.lineWidth = 1;
    ctx.fillStyle = "rgba(255,255,255,.35)"; ctx.font = "11px 'Atkinson Hyperlegible', system-ui";
    const wx0 = bnd.cx - w / 2 / scale, wz0 = bnd.cz - h / 2 / scale;
    for (let x = Math.ceil(wx0 / step) * step; sx(x) < w; x += step) { ctx.beginPath(); ctx.moveTo(Math.round(sx(x)) + 0.5, 0); ctx.lineTo(Math.round(sx(x)) + 0.5, h); ctx.stroke(); ctx.fillText(String(x), sx(x) + 4, h - 6); }
    for (let z = Math.ceil(wz0 / step) * step; sz(z) < h; z += step) { ctx.beginPath(); ctx.moveTo(0, Math.round(sz(z)) + 0.5); ctx.lineTo(w, Math.round(sz(z)) + 0.5); ctx.stroke(); ctx.fillText(String(z), 4, sz(z) - 4); }
    ctx.fillStyle = "rgba(255,255,255,.5)"; ctx.font = "bold 12px 'Atkinson Hyperlegible', system-ui"; ctx.fillText("N ↑", w - 34, 18);
    if (map.note) { ctx.font = "12px 'Atkinson Hyperlegible', system-ui"; const tw = ctx.measureText(map.note).width + 14; ctx.fillStyle = "rgba(8,10,18,.65)"; ctx.fillRect(8, 8, tw, 20); ctx.fillStyle = "rgba(235,230,217,.85)"; ctx.fillText(map.note, 15, 22); }
    if (map.race) {                                        // the course: dashed route, S / 1..n / F
      const rp = map.race.points, last = rp.length - 1;
      ctx.lineWidth = 3; ctx.strokeStyle = "rgba(242,193,78,.85)"; ctx.setLineDash([8, 6]);
      ctx.beginPath(); rp.forEach((p, i) => (i ? ctx.lineTo(sx(p.x), sz(p.z)) : ctx.moveTo(sx(p.x), sz(p.z)))); ctx.stroke(); ctx.setLineDash([]);
      ctx.font = "bold 12px 'Atkinson Hyperlegible', system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      rp.forEach((p, i) => {
        const x = sx(p.x), y = sz(p.z);
        ctx.fillStyle = i === 0 ? "#ebe6d9" : i === last ? "#f2c14e" : "#4cd964";
        ctx.beginPath(); ctx.arc(x, y, 11, 0, Math.PI * 2); ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = "rgba(0,0,0,.6)"; ctx.stroke();
        ctx.fillStyle = "#101826"; ctx.fillText(i === 0 ? "S" : i === last ? "F" : String(i), x, y + 0.5);
      });
      ctx.textAlign = "start"; ctx.textBaseline = "alphabetic";
    }
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
      ctx.globalAlpha = map.away ? 0.6 : 1;                 // not here now: a faded head where they left
      if (img?.complete && img.naturalWidth >= 64) {        // face, then the hat layer over it
        ctx.drawImage(img, 8, 8, 8, 8, x - s / 2, y - s / 2, s, s);
        ctx.drawImage(img, 40, 8, 8, 8, x - s / 2, y - s / 2, s, s);
      }
      else { ctx.fillStyle = "#4d74d6"; ctx.fillRect(x - s / 2, y - s / 2, s, s); }
      ctx.globalAlpha = 1;
      const rr = map.race?.racers?.[p.name];
      const label = map.away && p.last_seen ? `${p.name} · ${fmtAgo(p.last_seen)}`
        : rr ? `${p.name} · ${rr.finished != null ? "🏁" : `${rr.next - 1}/${map.race.points.length - 1}`}` : p.name;
      const tw = ctx.measureText(label).width + 10;
      ctx.fillStyle = "rgba(8,10,18,.7)"; ctx.fillRect(x - tw / 2, y + s / 2 + 5, tw, 18);
      ctx.fillStyle = "#ebe6d9"; ctx.fillText(label, x, y + s / 2 + 18);
    }
    ctx.textAlign = "start";
    if (t >= 1) map.bounds = tb;
    return t < 1;
  }
  const loop = () => { if (draw()) requestAnimationFrame(loop); };
  map.redraw = () => { if (cv.isConnected) draw(); };
  if (!map.bounds) map.bounds = targetBounds();
  requestAnimationFrame(loop);
  if (!map.resizeBound) { map.resizeBound = true; addEventListener("resize", () => st.map === map && draw()); }
}

// ------------------------------------------------------------------ recap, leaderboards (fetched now and then)
async function loadExtras(b) {
  const sid = b.id, now = Date.now();
  if (now - st.recapAt > 120000) {
    st.recapAt = now;
    getJSON(`/api/public/recap/${encodeURIComponent(sid)}`).then((r) => { if (sid === st.sid) { st.recap = r; if (st.board) render(st.board); } }).catch(() => { st.recap = null; });
  }
  if (st.tv && st.tvCfg.slides.leaders !== false && now - st.leadersAt > 300000) {
    st.leadersAt = now;
    getJSON(`/api/public/leaderboard/${encodeURIComponent(sid)}`).then((r) => { if (sid === st.sid) { st.leaders = r; if (st.board) render(st.board); } }).catch(() => { st.leaders = null; });
  }
}
function recapPanelHtml() {
  const r = st.recap;
  if (!r) return "";
  const today = r.recap, y = r.yesterday;
  const busy = (x) => x && (x.players.length || x.advancements.length);
  if (!busy(today) && !busy(y) && !r.on_this_day.length) return "";
  return `<section class="sp-panel glass sp-recap"><div class="sp-h"><h2>Recap</h2></div>
    ${busy(today) ? recapCardHtml(today, "Today so far", { max: 4 }) : ""}${busy(y) ? recapCardHtml(y, "Yesterday", { max: 4 }) : ""}${onThisDayHtml(r.on_this_day)}</section>`;
}

// ------------------------------------------------------------------ TV mode
// One slide at a time, big, for a screen on the wall. Slides with nothing to show are skipped;
// long ones scroll gently while they're up.
const TV_SLIDES = [["now", "Playing now"], ["map", "Where everyone is"], ["leaders", "Leaderboards"], ["recap", "Today on the server"], ["feed", "Recent activity"], ["news", "Announcements"]];
const tv = { idx: -1, timer: 0, shown: null, loops: 0, dur: 0 };
const TV_SCROLL_PX_S = 34;                    // how fast a long screen glides down (pixels per second)
function nf(n) { return new Intl.NumberFormat([], { maximumFractionDigits: n < 10 ? 1 : 0 }).format(n || 0); }

function tvAvailable(k, b) {
  if (st.tvCfg.slides[k] === false) return false;
  if (k === "now") return true;
  if (k === "map") return hasMap(b);
  if (k === "leaders") return !!st.leaders?.players?.some((r) => r.play_time > 0);
  if (k === "recap") return !!st.recap && (st.recap.recap.players.length || st.recap.yesterday?.players.length || st.recap.on_this_day.length);
  if (k === "feed") return b.recent.length > 0;
  if (k === "news") return (st.banners?.items || []).length > 0;
  return false;
}
function tvLeadersHtml() {
  const rows = st.leaders?.players || [];
  // Same boards, same order as the app's Leaderboards tab (the server sends the list).
  const boards = (st.leaders?.boards || []).map(({ key: k, title, kind }) => {
    const top = rows.filter((r) => r[k] > 0).sort((a, b) => b[k] - a[k]).slice(0, 5);
    if (!top.length) return "";
    return `<div class="tv-board glass"><h3>${esc(title)}</h3><ol>${top.map((r, i) => `<li><span class="rank">${i + 1}</span>${faceHtml(r, 36)}<b>${esc(r.name)}</b><span class="val">${esc(fmtStat(kind, r[k]))}</span></li>`).join("")}</ol></div>`;
  }).filter(Boolean);
  return `<div class="tv-boards">${boards.join("")}</div>`;
}
function tvRecapHtml() {
  const r = st.recap;
  if (!r) return "";
  const busy = (x) => x && (x.players.length || x.advancements.length);
  return `<div class="tv-recap"><div class="tv-recap-days">${recapCardHtml(r.recap, "Today so far", { big: true, max: 5 })}${busy(r.yesterday) ? recapCardHtml(r.yesterday, "Yesterday", { big: true, max: 4 }) : ""}</div>
    ${r.on_this_day.length ? `<div class="glass tv-otd">${onThisDayHtml(r.on_this_day, { big: true })}</div>` : ""}</div>`;
}
function tvNewsHtml() {
  const items = st.banners?.items || [];
  return `<div class="tv-news">${items.map((it) => `<div class="tv-news-item glass bn-${esc(it.style)}">
    <span class="tv-news-emoji">${esc(it.emoji || "📣")}</span><div><h2>${esc(it.text)}</h2>${it.detail ? `<p>${esc(it.detail)}</p>` : ""}</div>
    ${it.countdown ? `<span class="bn-cd big" data-cd="${it.countdown}"></span>` : ""}</div>`).join("")}</div>`;
}
// Always beside the slides: what's playing, and the last few things that happened.
function tvSideFeedHtml(b) {
  const list = b.recent.slice(0, 7);
  if (!list.length) return "";
  const uuids = Object.fromEntries([...b.players, ...b.recently].filter((p) => p.uuid).map((p) => [p.name.toLowerCase(), p.uuid]));
  return `<section class="tv-side-box glass"><h3>Lately</h3><ul class="tv-events">${list.map((e) => {
    const name = e.player ? `<b>${esc(e.player)}</b>` : "";
    const rest = e.player && e.message.startsWith(e.player) ? esc(e.message.slice(e.player.length)) : esc(e.message);
    return `<li class="ev-${esc(e.type)}">${e.player ? faceHtml({ name: e.player, uuid: uuids[e.player.toLowerCase()] }, 28) : `<span class="tv-ev-ic">${EVENT_ICON[e.type] || "•"}</span>`}
      <span class="tv-ev-text"><span class="tv-ev-ic-sm" aria-hidden="true">${EVENT_ICON[e.type] || ""}</span> ${name}${rest.replace(/\[(.+)\]$/, '<span class="adv-name">$1</span>')}</span>
      <time data-ago="${e.ts}"></time></li>`;
  }).join("")}</ul></section>`;
}
function renderTvMusic() {
  const el = $("#tv-side-music");
  if (!el) return;
  const t = FWMusic.current;
  if (!FW.music || !FWMusic.tracks.length || !t) { setHtml(el, ""); return; }
  const next = FWMusic.tracks.length > 1 ? FWMusic.tracks[(FWMusic.idx + 1) % FWMusic.tracks.length] : null;
  setHtml(el, `<section class="tv-side-box glass tv-music ${FWMusic.playing ? "playing" : ""}">
    <div class="tv-np"><span class="tv-np-art"><img src="${FWMusic.artUrl(t)}" alt="" data-fail="remove"></span>
      <div><small>${FWMusic.playing ? "♪ Now playing" : FWMusic.waiting ? "Click to carry on" : "Paused"}</small><b>${esc(t.title)}</b>${t.artist ? `<span>${esc(t.artist)}</span>` : ""}</div></div>
    <div class="tv-np-bar"><i id="tv-np-fill"></i></div>
    <div class="tv-np-times"><span id="tv-np-t">0:00</span><span>${FWMusic.duration ? fmtClockSecs(FWMusic.duration) : ""}</span></div>
    ${next && !FWMusic.shuffle ? `<p class="tv-np-next">Up next: <b>${esc(next.title)}</b>${next.artist ? ` · ${esc(next.artist)}` : ""}</p>` : FWMusic.shuffle ? `<p class="tv-np-next">🔀 Shuffling ${esc(FWMusic.source?.name || "")}</p>` : ""}
  </section>`);
  tvMusicTime();
}
const fmtClockSecs = (t) => { t = Math.max(0, Math.floor(t || 0)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
function tvMusicTime() {
  const f = $("#tv-np-fill"), tt = $("#tv-np-t");
  if (!f) return;
  const d = FWMusic.duration;
  f.style.width = `${d ? Math.min(100, (FWMusic.time / d) * 100) : 0}%`;
  if (tt) tt.textContent = fmtClockSecs(FWMusic.time);
}
FWMusic.on((what) => { if (!st.tv) return; if (what === "time") tvMusicTime(); else renderTvMusic(); });

function renderTv(b) {
  const main = $("#sp-main");
  if (main.dataset.sid !== b.id || main.dataset.mode !== "tv") {
    main.dataset.sid = b.id; main.dataset.mode = "tv";
    main.innerHTML = `<div class="tv-wrap"><div class="tv-main"><div class="tv-stage">${TV_SLIDES.map(([k, title]) => `<section class="tv-slide" data-slide="${k}" aria-hidden="true">
        <h2 class="tv-title">${esc(title)}<span class="tv-sub" data-sub="${k}"></span></h2><div class="tv-scroll"><div class="tv-inner" id="tv-${k}"></div></div></section>`).join("")}</div>
      <nav class="tv-dots" id="tv-dots" aria-label="Screens"></nav></div>
      <aside class="tv-side" aria-label="Now playing and recent events"><div id="tv-side-music"></div><div id="tv-side-feed"></div></aside></div>`;
    st.map = null; tv.idx = -1; tv.shown = null; tv.loops = 0;
  }
  setHtml($("#tv-now"), heroHtml(b) + playersHtml(b));
  const hasPos = hasMap(b);
  setHtml($("#tv-map"), hasPos ? `<div class="sp-map tv-map" id="sp-map"></div><span class="muted" id="sp-map-dim"></span>` : "");
  if (hasPos && tv.shown === "map") mountMap($("#sp-map"), b, st.map);
  setHtml($("#tv-leaders"), tvLeadersHtml());
  setHtml($("#tv-recap"), tvRecapHtml());
  setHtml($("#tv-feed"), b.recent.length ? `<div class="glass tv-feed">${feedHtml(b)}</div>` : "");
  setHtml($("#tv-news"), tvNewsHtml());
  setHtml($("#tv-side-feed"), tvSideFeedHtml(b));
  document.querySelectorAll(".tv-events [data-ago]").forEach((el) => { el.textContent = fmtAgo(Number(el.dataset.ago)); });
  renderTvMusic();
  const sub = $('[data-sub="now"]');
  if (sub) sub.textContent = ` on ${b.name}`;
  if (tv.idx < 0) tvNext();
  else if (tv.shown) {                     // the showing screen got more (or less) to scroll through: start it again
    const inner = $(`.tv-slide[data-slide="${tv.shown}"] .tv-inner`);
    if (inner && Math.abs(inner.scrollHeight - (tv.measured || 0)) > 40) tvShow(tv.shown);
  }
  tvDots(b);
}
function tvDots(b) {
  const dots = $("#tv-dots");
  if (!dots) return;
  const html = TV_SLIDES.filter(([k]) => tvAvailable(k, b)).map(([k, t]) => `<button type="button" data-tv="${k}" class="${k === tv.shown ? "on" : ""}" aria-current="${k === tv.shown}"><i style="--dur:${k === tv.shown && tv.dur ? tv.dur / 1000 : st.tvCfg.seconds}s"></i>${esc(t)}</button>`).join("");
  setHtml(dots, html);
  if (!dots._wired) {
    dots._wired = true;
    dots.addEventListener("click", (e) => { const btn = e.target.closest("[data-tv]"); if (btn) tvShow(btn.dataset.tv); });
  }
}
function tvNext() {
  clearTimeout(tv.timer);
  const b = st.board;
  if (!b || !st.tv) return;
  const keys = TV_SLIDES.map(([k]) => k);
  let next = tv.idx;
  for (let i = 0; i < keys.length; i++) {
    next = (next + 1) % keys.length;
    if (next === 0 && tv.idx >= 0) tv.loops++;
    if (tvAvailable(keys[next], b)) break;
  }
  // Every server in turn: after a full loop, move on (skipping ones that are off).
  if (st.tvCfg.rotate && tv.loops > 0 && st.servers.length > 1) {
    const order = st.servers.filter((x) => x.running !== false || x.id === st.sid);
    const at = order.findIndex((x) => x.id === st.sid);
    const to = order[(at + 1) % order.length];
    tv.loops = 0;
    if (to && to.id !== st.sid) { switchServer(to.id, false); return; }
  }
  tvShow(keys[next]);
}
// Show one screen now and start its timer (also used when a screen's name is clicked).
function tvShow(key) {
  clearTimeout(tv.timer);
  const b = st.board;
  if (!b || !st.tv) return;
  const keys = TV_SLIDES.map(([k]) => k);
  tv.idx = keys.indexOf(key); tv.shown = key;
  document.querySelectorAll(".tv-slide").forEach((el) => {
    const on = el.dataset.slide === tv.shown;
    el.classList.toggle("on", on); el.setAttribute("aria-hidden", String(!on));
  });
  if (tv.shown === "map" && hasMap(b)) { st.map = null; mountMap($("#sp-map"), b, null); }
  // A screen taller than the display stays up long enough to glide through all of it.
  tv.dur = tvScroll($(`.tv-slide[data-slide="${tv.shown}"] .tv-scroll`));
  tvDots(b);
  tv.timer = setTimeout(tvNext, tv.dur);
}
// Too tall for the screen: hold, glide down to the end, hold.
// Returns how long the screen should stay up: the usual time, or longer when there's more to
// scroll through (hold at the top, glide down slowly, hold at the bottom).
function tvScroll(box) {
  const base = st.tvCfg.seconds * 1000;
  if (!box) return base;
  const inner = box.firstElementChild;
  inner.getAnimations?.().forEach((a) => a.cancel());
  tv.measured = inner.scrollHeight;
  const over = inner.scrollHeight - box.clientHeight;
  if (over <= 8 || !inner.animate) return base;
  const hold = 3500, glide = (over / TV_SCROLL_PX_S) * 1000;
  const ms = Math.max(base, hold + glide + hold);
  const top = hold / ms, end = 1 - hold / ms;
  inner.animate([{ transform: "translateY(0)", offset: 0 }, { transform: "translateY(0)", offset: top },
    { transform: `translateY(${-over}px)`, offset: end }, { transform: `translateY(${-over}px)`, offset: 1 }], { duration: ms, easing: "linear", fill: "forwards" });
  return ms;
}
function setTvMode(on) {
  st.tv = on;
  document.body.classList.toggle("tv", on);
  clearTimeout(tv.timer); tv.idx = -1; tv.shown = null;
  const url = new URL(location.href);
  if (on) url.searchParams.set("tv", "1"); else url.searchParams.delete("tv");
  history.replaceState(null, "", url);
  renderServerTabs();
  delete $("#sp-main").dataset.sid;
  st.leadersAt = 0;
  st.banners?.render();
  if (st.board) render(st.board);
  if (on) document.documentElement.requestFullscreen?.().catch(() => {});
}
$("#sp-tv")?.addEventListener("click", () => setTvMode(!st.tv));
// The wall clock, and a hidden cursor when nobody's touching it.
let tvIdle = 0;
addEventListener("pointermove", () => { document.body.classList.remove("tv-idle"); clearTimeout(tvIdle); tvIdle = setTimeout(() => document.body.classList.add("tv-idle"), 3000); });
setInterval(() => {
  const c = $("#tv-clock");
  if (c && st.tv) c.textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  document.querySelectorAll(".tv-news [data-cd]").forEach((el) => { const left = Number(el.dataset.cd) - Date.now() / 1000; el.textContent = left > 0 ? fmtCountdown(left) : "Now!"; });
}, 1000);

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
    st.scene = startSkyScene(sky, { auto: false, sound: (t, i) => FWAudio.play(t, i), dim: () => (document.body.classList.contains("ui-hidden") ? 0 : 0.35) });
    st.bar = startShowBar(st.scene, { key: "solstone-sky-status", defaultOn: true, hide: true, skyServer: () => st.sid || "",
      onEvent: (item) => { if (item.text && item.server_id === st.sid) toast(esc(item.text)); } });
  }
  st.banners = startBoard($("#sp-board"), { where: "status", sid: () => st.sid || "", scene: () => st.scene, max: innerWidth < 700 ? 1 : 3, ticker: () => st.tv });
  if (st.tv) document.body.classList.add("tv");
  keepAwake();
  await loadServers();
  poll();
  setInterval(() => { if (!document.hidden) loadServers(); }, 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });     // back from the background: refresh now
});
