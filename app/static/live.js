/* Solstone — the live servers on the home page. No sign-in: one server at a time, refreshing
   every few seconds. Everything comes from /api/public/*, which only works while an admin has
   live server info turned on. home.js starts it with startLive() when the home page is shown;
   it stops by itself once the page changes. */
"use strict";

(() => {
const $ = (sel, root = document) => root.querySelector(sel);
const POLL_MS = 5000;
// Skins on this page come through the public route, which only serves players of visible servers.
skinSource = (p) => p.uuid && st.sid ? `/api/public/skin/${encodeURIComponent(st.sid)}/${String(p.uuid).replace(/-/g, "")}.png` : null;
const st = { servers: [], sid: null, want: null, board: null, prevOnline: null, prevEventTs: 0, fetchedAt: 0, tod: null, todAt: 0, scene: null, map: null,
  recap: null, recapAt: 0, leaders: null, leadersAt: 0, toast: null, on: false };

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
// A front view of the player in their current skin, drawn by Solstone from Mojang's copy.
const bodyUrl = (p) => p.uuid && st.sid ? `/api/public/skin/${encodeURIComponent(st.sid)}/${String(p.uuid).replace(/-/g, "")}/body.png?size=224` : "data:,";
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
async function loadServers() {
  try {
    const d = await getJSON("/api/public/status");
    // A wall screen stays open for days: when Solstone has been updated, load the new version.
    if (d.build && st.build && d.build !== st.build) { location.reload(); return; }
    st.build = d.build || st.build;
    if (!d.enabled) { stop(); return; }
    st.servers = d.servers || [];
  } catch { /* keep the last list */ }
  if (!st.sid || !st.servers.some((s) => s.id === st.sid)) {
    const pick = st.servers.find((s) => s.id === st.want)
      || [...st.servers].sort((a, b) => (b.online || 0) - (a.online || 0) || (b.running !== false) - (a.running !== false))[0];
    st.sid = pick?.id || null;
  }
  renderServerTabs();
}
function renderServerTabs() {
  const nav = $("#sp-servers");
  if (!nav) return;
  nav.innerHTML = st.servers.length > 1 ? st.servers.map((s) => {
    const dot = s.crashed ? "crash" : s.running !== false ? "on" : "";
    return `<a href="#live" data-sid="${esc(s.id)}" ${s.id === st.sid ? 'aria-current="page"' : ""}>
      <span class="status-dot ${dot}"></span>${esc(s.name)}${s.running !== false && s.online ? `<b>${s.online}</b>` : ""}</a>`;
  }).join("") : "";
}
document.addEventListener("click", (e) => {
  const a = e.target.closest("#sp-servers a[data-sid]");
  if (!a) return;
  e.preventDefault();
  if (a.dataset.sid === st.sid) return;
  switchServer(a.dataset.sid, true);
});
function switchServer(sid, push) {
  st.sid = sid; st.board = null; st.prevOnline = null; st.prevEventTs = 0; st.map = null; st.recap = st.leaders = null; st.recapAt = st.leadersAt = 0;
  delete $("#sp-main").dataset.sid;
  renderServerTabs();
  poll();
}
// Pick a server from outside (the server cards above): show it and scroll down to it.
function showServer(sid) {
  if (sid && sid !== st.sid && st.servers.some((s) => s.id === sid)) switchServer(sid);
  else if (sid) st.want = sid;
  $("#live")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

let pollTimer = 0;
async function poll() {
  clearTimeout(pollTimer);
  if (!st.on || !$("#sp-main")) { st.on = false; return; }     // the page changed: stop
  if (!st.sid) {
    $("#sp-main").innerHTML = `<div class="sp-empty glass"><h2>No servers to show</h2><p class="muted">Servers appear here once Solstone finds them.</p></div>`;
    pollTimer = setTimeout(async () => { await loadServers(); poll(); }, 15000);
    return;
  }
  const sid = st.sid;
  try {
    const b = await getJSON(`/api/public/status/${encodeURIComponent(sid)}`);
    if (sid !== st.sid || !$("#sp-main")) return;
    st.fetchedAt = Date.now();
    noticeChanges(b);
    st.board = b;
    if (b.world) { st.tod = b.world.time_of_day; st.todAt = Date.now() - (b.world.age || 0) * 1000; } else st.tod = null;
    render(b);
  } catch (e) {
    if (e.status === 404) { st.sid = null; await loadServers(); if (!st.on) return; }   // turned off, or the server went away
    else if ($("#sp-updated")) $("#sp-updated").textContent = "Can't reach Solstone, retrying…";
  }
  pollTimer = setTimeout(poll, document.hidden ? POLL_MS * 6 : POLL_MS);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && st.on) poll(); });     // back from the background: refresh now

// Fireworks for a join or a new advancement, so a screen in the room notices.
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
function toast(html) { st.toast?.(html); }

// ------------------------------------------------------------------ rendering
const EVENT_ICON = { join: "→", leave: "←", death: "☠", advancement: "★", level: "⬆", server: "⏻", challenge: "🏆", race: "🏁", bigfish: "🐟", game: "🎲" };

// Sections are only replaced when their content changes, so the web map iframe and the
// position canvas aren't rebuilt on every refresh.
function setHtml(el, html) { if (el && el._html !== html) { el._html = html; el.innerHTML = html; } }
// Routine lines (every catch, every bullseye) fold into one line per kind, placed at the newest of
// them, so a busy afternoon doesn't push everything else off the list. Rare fish stay as their own line.
const ROUTINE = { fish: ["catch", "catches"], game: ["game moment", "game moments"], bigfish: ["big catch", "big catches"] };
const ROUTINE_MIN = { fish: 2, game: 2, bigfish: 3 };
function condenseRecent(list) {
  const routine = (e) => ROUTINE[e.type] && !/\b(Trophy|Mythic)\b|every kind/.test(e.message || "");
  const byType = {};
  list.forEach((e) => { if (routine(e)) (byType[e.type] = byType[e.type] || []).push(e); });
  const out = [], done = new Set();
  for (const e of list) {
    const g = routine(e) ? byType[e.type] : null;
    if (!g || g.length < ROUTINE_MIN[e.type]) { out.push(e); continue; }
    if (done.has(e.type)) continue;
    done.add(e.type);
    const who = [...new Set(g.map((x) => x.player).filter(Boolean))];
    const names = who.length <= 2 ? who.join(" and ") : `${who.slice(0, 2).join(", ")} and ${who.length - 2} more`;
    const [one, many] = ROUTINE[e.type];
    out.push({ ...e, player: null, message: `${g.length} ${g.length === 1 ? one : many}${names ? ` · ${names}` : ""}` });
  }
  return out;
}
function feedHtml(b) {
  return `<ul class="sp-feed">${condenseRecent(b.recent).map((e) => `
    <li class="ev-${esc(e.type)}"><span class="ev-icon" aria-hidden="true">${EVENT_ICON[e.type] || "•"}</span><span class="ev-time">${esc(fmtAgo(e.ts))}</span><span>${esc(e.message).replace(/\[(.+)\]$/, '<span class="adv-name">$1</span>')}</span></li>`).join("")}</ul>`;
}
// The screens (Playing now, the map, leaderboards...) with their names as tabs: pick one.
function render(b) {
  if (!$("#sp-main")) return;
  loadExtras(b);
  renderTv(b);
}

// Contests, races and games that are on right now: the scoreboard and a countdown.
function liveHtml(b, big = false) {
  const items = b.live || [];
  if (!items.length) return "";
  const uuids = Object.fromEntries([...(b.players || []), ...(b.recently || [])].filter((p) => p.uuid).map((p) => [p.name.toLowerCase(), p.uuid]));
  const cards = items.map((it) => {
    const rows = it.rows.length ? `<ol class="live-rows">${it.rows.map((r, i) => `<li class="${i === 0 && it.rows.length > 1 ? "lead" : ""}"><span class="rank">${i + 1}</span>${faceHtml({ name: r.name, uuid: uuids[r.name.toLowerCase()] }, big ? 40 : 28)}<b>${esc(r.name)}</b>${r.note ? `<small>${esc(r.note)}</small>` : ""}<span class="val">${esc(r.value)}</span></li>`).join("")}</ol>`
      : it.empty ? `<p class="muted">${esc(it.empty)}</p>` : "";
    return `<article class="live-card glass"><header><span class="live-emoji" aria-hidden="true">${esc(it.emoji)}</span><div><h3>${esc(it.title)}</h3>${it.sub ? `<p class="muted">${esc(it.sub)}</p>` : ""}</div>
      ${it.ends_at ? `<span class="live-cd" data-cd="${it.ends_at}">${esc(fmtCountdown(Math.max(0, it.ends_at - Date.now() / 1000)))}</span>` : ""}</header>${rows}</article>`;
  }).join("");
  return big ? `<div class="live-grid big">${cards}</div>` : `<section class="sp-live"><h2 class="sp-live-h"><span class="status-dot on"></span>Happening now</h2><div class="live-grid">${cards}</div></section>`;
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
  return `<div class="sp-players ${b.players.length === 1 ? "solo" : b.players.length > 4 ? "many" : ""}">${b.players.map(playerCardHtml).join("")}</div>${b.recently.length ? `<div class="sp-recent-wrap">${recentlyHtml(b)}</div>` : ""}`;
}
function recentlyHtml(b) {
  if (!b.recently.length) return "";
  return `<div class="sp-recently"><h3>Played recently</h3><ul>${b.recently.map((p) => `<li>${faceHtml(p, 32)}<span><b>${esc(p.name)}</b><small>${esc(fmtAgo(p.last_seen))}</small></span></li>`).join("")}</ul></div>`;
}
function playerCardHtml(p) {
  // Short and sweet: numbers instead of rows of hearts and drumsticks, so more players fit.
  const num = (v) => Math.round(v * 2) / 2;
  const vitals = p.health != null
    ? `<div class="sp-stats"><span title="Health">❤️ <b>${num(p.health / 2)}</b>/${num((p.max_health || 20) / 2)}</span><span title="Food">🍗 <b>${num((p.food ?? 20) / 2)}</b>/10</span></div>` : "";
  const since = "Playing now";       // never for how long
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
      <div class="sp-meta"><span class="live-tag"><span class="status-dot on"></span>${since}</span></div>
      ${vitals}
      <div class="chips">${chips}</div>
      ${gear}${effects}
    </div></article>`;
}

// Once a second: "updated 3 s ago", the in-game clock (20 ticks per second), play timers.
function tick() {
  if (st.fetchedAt) {
    const s = Math.round((Date.now() - st.fetchedAt) / 1000);
    const u = $("#sp-updated");
    if (u) u.innerHTML = `<span class="status-dot on"></span>Live${s > 2 ? ` · updated ${s} s ago` : ""}`;
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
    <div class="map-box"><canvas id="sp-map-canvas" role="img" aria-label="Map of player positions. Drag to move around, scroll or pinch to zoom."></canvas>
      <div class="map-ctl"><button type="button" data-z="in" aria-label="Zoom in">+</button><button type="button" data-z="out" aria-label="Zoom out">−</button>
        <button type="button" data-reset ${prev?.user ? "" : "hidden"}>Reset view</button></div></div>`;
    el.querySelectorAll("[data-dim]").forEach((btn) => btn.addEventListener("click", () => { st.map.dim = btn.dataset.dim; st.map.shown = {}; st.map.bounds = null; st.map.user = null; mountMap(el, st.board, st.map); }));
    wireMapMoves(el);
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
    const bnd = map.user ? map.user : map.bounds ? { cx: map.bounds.cx + (tb.cx - map.bounds.cx) * ease, cz: map.bounds.cz + (tb.cz - map.bounds.cz) * ease, span: map.bounds.span + (tb.span - map.bounds.span) * ease } : tb;
    map.cur = bnd;
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
    if (t >= 1 && !map.user) map.bounds = tb;
    return t < 1;
  }
  const loop = () => { if (draw()) requestAnimationFrame(loop); };
  map.redraw = () => { if (cv.isConnected) draw(); };
  map.play = () => requestAnimationFrame(loop);
  if (!map.bounds) map.bounds = targetBounds();
  requestAnimationFrame(loop);
  if (!map.resizeBound) { map.resizeBound = true; addEventListener("resize", () => st.map === map && draw()); }
}

// Drag to move around the map, scroll or pinch to zoom, and Reset view to go back to following everyone.
function wireMapMoves(el) {
  const cv = $("canvas", el), reset = $("[data-reset]", el);
  const view = () => { const m = st.map; return { ...(m.user || m.cur || m.bounds) }; };
  const scaleOf = (v) => Math.min(cv.clientWidth, cv.clientHeight) / v.span;
  const setView = (v) => {
    const m = st.map;
    if (!m || !v.span) return;
    m.user = { cx: v.cx, cz: v.cz, span: Math.max(24, Math.min(6000, v.span)) };
    reset.hidden = false;
    m.redraw();
  };
  // zoom keeping one spot of the world under the same spot on the screen
  const zoomAt = (f, px, py) => {
    const v = view(), r = cv.getBoundingClientRect(), s1 = scaleOf(v);
    const ox = px - r.left - r.width / 2, oy = py - r.top - r.height / 2;
    const wx = v.cx + ox / s1, wz = v.cz + oy / s1, span = Math.max(24, Math.min(6000, v.span * f)), s2 = Math.min(r.width, r.height) / span;
    setView({ span, cx: wx - ox / s2, cz: wz - oy / s2 });
  };
  const pts = new Map();
  cv.addEventListener("pointerdown", (e) => { cv.setPointerCapture?.(e.pointerId); pts.set(e.pointerId, { x: e.clientX, y: e.clientY }); cv.classList.add("grabbing"); });
  cv.addEventListener("pointermove", (e) => {
    const prev = pts.get(e.pointerId);
    if (!prev) return;
    const now = { x: e.clientX, y: e.clientY };
    if (pts.size === 1) {
      const v = view(), s1 = scaleOf(v);
      setView({ ...v, cx: v.cx - (now.x - prev.x) / s1, cz: v.cz - (now.y - prev.y) / s1 });
    } else if (pts.size === 2) {
      const other = [...pts].find(([id]) => id !== e.pointerId)[1];
      const d0 = Math.hypot(prev.x - other.x, prev.y - other.y), d1 = Math.hypot(now.x - other.x, now.y - other.y);
      if (d0 > 0 && d1 > 0) zoomAt(d0 / d1, (now.x + other.x) / 2, (now.y + other.y) / 2);
    }
    pts.set(e.pointerId, now);
  });
  const up = (e) => { pts.delete(e.pointerId); if (!pts.size) cv.classList.remove("grabbing"); };
  cv.addEventListener("pointerup", up); cv.addEventListener("pointercancel", up);
  cv.addEventListener("wheel", (e) => { e.preventDefault(); zoomAt(Math.exp(Math.max(-1, Math.min(1, e.deltaY / 300))), e.clientX, e.clientY); }, { passive: false });
  const r = () => cv.getBoundingClientRect();
  $("[data-z=in]", el).addEventListener("click", () => zoomAt(1 / 1.6, r().left + r().width / 2, r().top + r().height / 2));
  $("[data-z=out]", el).addEventListener("click", () => zoomAt(1.6, r().left + r().width / 2, r().top + r().height / 2));
  reset.addEventListener("click", () => {
    const m = st.map;
    if (!m) return;
    m.bounds = m.user; m.user = null; m.anim = performance.now(); reset.hidden = true;
    m.play();                                   // glide back to everyone
  });
}

// ------------------------------------------------------------------ recap, leaderboards (fetched now and then)
async function loadExtras(b) {
  const sid = b.id, now = Date.now();
  if (now - st.recapAt > 120000) {
    st.recapAt = now;
    getJSON(`/api/public/recap/${encodeURIComponent(sid)}`).then((r) => { if (sid === st.sid) { st.recap = r; if (st.board) render(st.board); } }).catch(() => { st.recap = null; });
  }
  if (now - st.leadersAt > 300000) {
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

// ------------------------------------------------------------------ screens
// One screen at a time, picked by its name; screens with nothing to show are left out.
const SCREENS = [["live", "Happening now"], ["now", "Playing now"], ["map", "Where everyone is"], ["leaders", "Leaderboards"], ["recap", "Today on the server"], ["feed", "Recent activity"]];
const tv = { idx: -1, shown: null, pick: null };

function tvAvailable(k, b) {
  if (k === "now") return true;
  if (k === "live") return (b.live || []).length > 0;
  if (k === "map") return hasMap(b);
  if (k === "leaders") return !!st.leaders?.players?.some((r) => st.leaders.boards.some((bd) => r[bd.key] > 0));
  if (k === "recap") return !!st.recap && (st.recap.recap.players.length || st.recap.yesterday?.players.length || st.recap.on_this_day.length);
  if (k === "feed") return b.recent.length > 0;
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
// Always beside the slides: what's playing, and the last few things that happened.
function tvSideFeedHtml(b) {
  const list = condenseRecent(b.recent).slice(0, 7);
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
function renderTv(b) {
  const main = $("#sp-main");
  if (main.dataset.sid !== b.id || main.dataset.mode !== "tv") {
    main.dataset.sid = b.id; main.dataset.mode = "tv";
    main.innerHTML = `<nav class="tv-dots" id="tv-dots" aria-label="Screens"></nav><div class="tv-wrap"><div class="tv-main"><div class="tv-stage">${SCREENS.map(([k, title]) => `<section class="tv-slide" data-slide="${k}" aria-hidden="true">
        <h2 class="tv-title">${esc(title)}<span class="tv-sub" data-sub="${k}"></span></h2><div class="tv-scroll"><div class="tv-inner" id="tv-${k}"></div></div></section>`).join("")}</div></div>
      <aside class="tv-side" aria-label="Recent events"><div id="tv-side-feed"></div></aside></div>`;
    st.map = null; tv.idx = -1; tv.shown = null;
  }
  setHtml($("#tv-now"), heroHtml(b) + playersHtml(b));
  const hasPos = hasMap(b);
  setHtml($("#tv-map"), hasPos ? `<div class="sp-map tv-map" id="sp-map"></div><span class="muted" id="sp-map-dim"></span>` : "");
  if (hasPos && tv.shown === "map") mountMap($("#sp-map"), b, st.map);
  setHtml($("#tv-live"), liveHtml(b, true));
  setHtml($("#tv-leaders"), tvLeadersHtml());
  setHtml($("#tv-recap"), tvRecapHtml());
  setHtml($("#tv-feed"), b.recent.length ? `<div class="glass tv-feed">${feedHtml(b)}</div>` : "");
  setHtml($("#tv-side-feed"), tvSideFeedHtml(b));
  document.querySelectorAll(".tv-events [data-ago]").forEach((el) => { el.textContent = fmtAgo(Number(el.dataset.ago)); });
  const sub = $('[data-sub="now"]');
  if (sub) sub.textContent = ` on ${b.name}`;
  if (tv.idx < 0) tvShow(tvAvailable("live", b) ? "live" : tv.pick && tvAvailable(tv.pick, b) ? tv.pick : "now");
  else if (!tvAvailable(tv.shown, b)) tvShow("now");       // what was showing has nothing left in it
  tvDots(b);
  requestAnimationFrame(alignSide);
}
function tvDots(b) {
  const dots = $("#tv-dots");
  if (!dots) return;
  const html = SCREENS.filter(([k]) => tvAvailable(k, b)).map(([k, t]) => `<button type="button" data-tv="${k}" class="${k === tv.shown ? "on" : ""}" aria-current="${k === tv.shown}">${esc(t)}</button>`).join("");
  setHtml(dots, html);
  if (!dots._wired) {
    dots._wired = true;
    dots.addEventListener("click", (e) => { const btn = e.target.closest("[data-tv]"); if (btn) tvShow(btn.dataset.tv); });
  }
}
// The "Lately" panel starts level with the screen's first card, not with the tabs and title above it.
function alignSide() {
  const side = $(".tv-side"), main = $(".tv-main"), first = $(".tv-slide.on .tv-inner .glass, .tv-slide.on .tv-inner canvas, .tv-slide.on .tv-inner iframe") || $(".tv-slide.on .tv-inner > *");
  if (!side || !main) return;
  if (!first || innerWidth <= 1000) { side.style.marginTop = ""; return; }
  side.style.marginTop = `${Math.max(0, Math.round(first.getBoundingClientRect().top - main.getBoundingClientRect().top))}px`;
}
addEventListener("resize", () => requestAnimationFrame(alignSide));
// Show one screen (also when its name is clicked); it stays until another is picked.
function tvShow(key) {
  const b = st.board;
  if (!b) return;
  tv.pick = key;
  tv.idx = SCREENS.findIndex(([k]) => k === key); tv.shown = key;
  document.querySelectorAll(".tv-slide").forEach((el) => {
    const on = el.dataset.slide === tv.shown;
    el.classList.toggle("on", on); el.setAttribute("aria-hidden", String(!on));
  });
  if (tv.shown === "map" && hasMap(b)) { st.map = null; mountMap($("#sp-map"), b, null); }
  requestAnimationFrame(alignSide);
  tvDots(b);
}
setInterval(() => {
  document.querySelectorAll(".live-cd[data-cd]").forEach((el) => { const left = Number(el.dataset.cd) - Date.now() / 1000; el.textContent = left > 0 ? fmtCountdown(left) : "Time's up"; });
}, 1000);

// ------------------------------------------------------------------ start and stop
function stop() {
  st.on = false; clearTimeout(pollTimer);
  const box = $("#live");
  if (box) box.hidden = true;
}
// opts: scene (the sky, for fireworks on joins), toast(html), sid (a server to show first)
async function startLive(opts = {}) {
  if (!$("#sp-main")) return;
  Object.assign(st, { scene: opts.scene || null, toast: opts.toast || null, want: opts.sid || st.want, sid: null, board: null, prevOnline: null, prevEventTs: 0, map: null, recap: null, leaders: null, recapAt: 0, leadersAt: 0, on: true });
  tv.idx = -1; tv.shown = null;
  await loadServers();
  if (st.on) { $("#live").hidden = false; poll(); }
}
setInterval(() => { if (st.on && !document.hidden && $("#sp-main")) loadServers(); }, 30000);
window.startLive = startLive;
window.showLiveServer = showServer;
})();
