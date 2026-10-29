/* Solstone — play history, performance charts, activity feed, notification settings.
   Loaded after app.js and uses its helpers ($, esc, api, fmt*, serverFrame, ...). */
"use strict";

// ================================================================ colours
// Categorical slots (validated for the dark surface, see README). Colour follows the
// player, not their rank: slots are assigned by alphabetical order of everyone known.
// 16 colours far enough apart to tell players apart in charts; a 17th player onward is grey.
const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767",
  "#1aa3c4", "#86b81c", "#b85bd6", "#a0663a", "#d4c21a", "#4a55c9", "#ff8c69", "#5fcf9f"];
const OTHER = "#737a86";
let playerSlots = {};
function setPlayerSlots(names) {
  const sorted = [...new Set(names.map((n) => n.toLowerCase()))].sort();
  playerSlots = {};
  sorted.forEach((n, i) => { playerSlots[n] = i < SERIES.length ? SERIES[i] : OTHER; });
}
const playerColor = (name) => playerSlots[(name || "").toLowerCase()] || OTHER;

// ================================================================ chart tooltip
function chartTip() {
  let t = $("#chart-tip");
  if (!t) { t = document.createElement("div"); t.id = "chart-tip"; t.className = "chart-tip"; t.hidden = true; document.body.append(t); }
  return t;
}
function showChartTip(html, x, y) {
  const t = chartTip(); t.innerHTML = html; t.hidden = false;
  const r = t.getBoundingClientRect();
  let left = x + 14, top = y - r.height - 10;
  if (left + r.width > innerWidth - 8) left = x - r.width - 14;
  if (top < 8) top = y + 16;
  t.style.left = `${Math.max(8, left)}px`; t.style.top = `${top}px`;
}
const hideChartTip = () => { const t = $("#chart-tip"); if (t) t.hidden = true; };
addEventListener("scroll", hideChartTip, { passive: true });

function niceMax(v) {
  if (!v || v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}
const resizeObservers = new WeakMap();
function onResize(el, fn) {
  if (resizeObservers.has(el)) resizeObservers.get(el).disconnect();
  let w = el.clientWidth;
  const ro = new ResizeObserver(() => { if (Math.abs(el.clientWidth - w) > 4) { w = el.clientWidth; fn(); } });
  ro.observe(el); resizeObservers.set(el, ro);
}

// ================================================================ line chart
// spec: { points:[{t, v, running}], max?, min?, fmt(v), target?: {v, label}, bucket, since, until, height? }
function renderLine(el, spec) {
  const draw = () => {
    const W = Math.max(280, el.clientWidth), H = spec.height || 170;
    const m = { l: 46, r: 12, t: 10, b: 24 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const t0 = spec.since, t1 = spec.until;
    const vals = spec.points.map((p) => p.v).filter((v) => v != null);
    // Four gridline steps of a "nice" size, so axis labels are round numbers.
    const maxV = spec.max ?? niceMax((Math.max(...vals, spec.target?.v || 0, 0) * 1.1) / 4) * 4;
    const minV = spec.min ?? 0;
    const X = (t) => m.l + ((t - t0) / (t1 - t0)) * iw;
    const Y = (v) => m.t + ih - ((v - minV) / (maxV - minV || 1)) * ih;
    let grid = "";
    for (let i = 0; i <= 4; i++) {
      const v = minV + ((maxV - minV) * i) / 4, y = Y(v);
      grid += `<line x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}" class="grid"/><text x="${m.l - 8}" y="${y + 4}" class="axis" text-anchor="end">${esc(spec.fmt(v, true))}</text>`;
    }
    const span = t1 - t0, ticks = W < 520 ? 3 : 5;
    for (let i = 0; i <= ticks; i++) {
      const t = t0 + (span * i) / ticks;
      const d = new Date(t * 1000);
      const label = span <= 86400 * 1.01 ? d.toLocaleTimeString([], { hour: "numeric" }) : d.toLocaleDateString([], { month: "short", day: "numeric" });
      grid += `<text x="${X(t)}" y="${H - 6}" class="axis" text-anchor="${i === 0 ? "start" : i === ticks ? "end" : "middle"}">${esc(label)}</text>`;
    }
    // Downtime bands
    let bands = "";
    for (const p of spec.points) if (p.running === 0) bands += `<rect x="${X(p.t)}" y="${m.t}" width="${Math.max(1, (spec.bucket / span) * iw)}" height="${ih}" class="down"/>`;
    // Path with gaps; a point with no neighbour on either side is drawn as a dot,
    // otherwise a fresh install's first measurements would be invisible.
    let d = "", prev = null, dots = "";
    const pv = spec.points;
    const joined = (a, b) => a && b && a.v != null && b.v != null && Math.abs(b.t - a.t) <= spec.bucket * 2.5;
    pv.forEach((p, i) => {
      if (p.v == null) { prev = null; return; }
      const gap = prev && p.t - prev.t > spec.bucket * 2.5;
      d += `${!prev || gap ? "M" : "L"}${X(p.t).toFixed(1)},${Y(Math.min(p.v, maxV)).toFixed(1)} `;
      if (!joined(pv[i - 1], p) && !joined(p, pv[i + 1])) dots += `<circle cx="${X(p.t).toFixed(1)}" cy="${Y(Math.min(p.v, maxV)).toFixed(1)}" r="3" style="fill:${spec.color || SERIES[0]}"/>`;
      prev = p;
    });
    const target = spec.target ? `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(spec.target.v)}" y2="${Y(spec.target.v)}" class="target"/><text x="${W - m.r}" y="${Y(spec.target.v) - 5}" class="axis" text-anchor="end">${esc(spec.target.label)}</text>` : "";
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(spec.label || "")}">
      ${bands}${grid}${target}<path d="${d}" class="line" style="stroke:${spec.color || SERIES[0]}"/>${dots}
      <line class="cross" y1="${m.t}" y2="${m.t + ih}" visibility="hidden"/><circle class="dot" r="4" visibility="hidden" style="fill:${spec.color || SERIES[0]}"/>
      <rect class="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}"/></svg>`;
    const svg = el.querySelector("svg"), cross = svg.querySelector(".cross"), dot = svg.querySelector(".dot");
    const pts = spec.points.filter((p) => p.v != null || p.running === 0);
    const move = (e) => {
      const r = svg.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * W;
      const t = t0 + ((x - m.l) / iw) * span;
      let best = null, bd = Infinity;
      for (const p of pts) { const dd = Math.abs(p.t - t); if (dd < bd) { bd = dd; best = p; } }
      if (!best || bd > spec.bucket * 3) { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideChartTip(); return; }
      const bx = X(best.t);
      cross.setAttribute("x1", bx); cross.setAttribute("x2", bx); cross.setAttribute("visibility", "visible");
      if (best.v != null) { dot.setAttribute("cx", bx); dot.setAttribute("cy", Y(Math.min(best.v, maxV))); dot.setAttribute("visibility", "visible"); }
      else dot.setAttribute("visibility", "hidden");
      const when = new Date(best.t * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
      showChartTip(`<div class="tt-when">${esc(when)}</div><div class="tt-val">${best.running === 0 ? "Server offline" : esc(spec.fmt(best.v))}</div>`, e.clientX, e.clientY);
    };
    svg.querySelector(".hit").addEventListener("mousemove", move);
    svg.querySelector(".hit").addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideChartTip(); });
  };
  draw(); onResize(el, draw);
}

// ================================================================ stacked daily bars
// days: [{date, players:{name: seconds}}], series: [names] in stacking order
function renderDailyBars(el, days, series, opts = {}) {
  const draw = () => {
    const W = Math.max(280, el.clientWidth), H = opts.height || 200;
    const m = { l: 40, r: 8, t: 10, b: 26 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const totals = days.map((d) => series.reduce((a, n) => a + (d.players[n] || 0), 0));
    const rawStep = Math.max(...totals, 1800) / 3600 / 4;
    const maxH = ([0.25, 0.5, 1, 2, 3, 4, 6].find((st) => st >= rawStep) || 6) * 4;
    const Y = (sec) => m.t + ih - (sec / 3600 / maxH) * ih;
    const slot = iw / days.length, bw = Math.max(4, Math.min(34, slot * 0.66));
    let g = "";
    for (let i = 0; i <= 4; i++) {
      const h = (maxH * i) / 4, y = Y(h * 3600);
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}" class="grid"/><text x="${m.l - 8}" y="${y + 4}" class="axis" text-anchor="end">${h < 1 && h > 0 ? `${Math.round(h * 60)}m` : `${h % 1 ? h.toFixed(1) : h}h`}</text>`;
    }
    const every = Math.ceil(days.length / Math.max(2, Math.floor(iw / 56)));
    days.forEach((d, i) => {
      const cx = m.l + slot * i + slot / 2;
      let y = Y(0);
      const segs = series.filter((n) => d.players[n] > 0);
      segs.forEach((n, j) => {
        const h = Y(0) - Y(d.players[n]);
        const top = y - h, gap = j < segs.length - 1 ? 2 : 0;
        const hh = Math.max(1, h - (j > 0 ? 2 : 0));
        const yy = top + (j > 0 ? 0 : 0);
        g += j === segs.length - 1 ? roundedTop(cx - bw / 2, yy, bw, hh, Math.min(4, hh), opts.color || playerColor(n)) : `<rect x="${cx - bw / 2}" y="${yy}" width="${bw}" height="${hh}" fill="${opts.color || playerColor(n)}"/>`;
        y = top - gap;
      });
      const last = i === days.length - 1;
      if (last || (i % every === 0 && days.length - 1 - i >= every * 0.75)) {
        const dt = new Date(`${d.date}T12:00:00`);
        g += `<text x="${cx}" y="${H - 7}" class="axis" text-anchor="middle">${esc(last ? "Today" : dt.toLocaleDateString([], { month: "short", day: "numeric" }))}</text>`;
      }
      g += `<rect class="hit" data-i="${i}" x="${m.l + slot * i}" y="${m.t}" width="${slot}" height="${ih}"/>`;
    });
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(opts.label || "Time played per day")}">${g}</svg>`;
    el.querySelectorAll(".hit").forEach((r) => {
      r.addEventListener("mousemove", (e) => {
        const d = days[+r.dataset.i];
        const dt = new Date(`${d.date}T12:00:00`).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
        const rows = series.filter((n) => d.players[n] > 0).sort((a, b) => d.players[b] - d.players[a])
          .map((n) => `<div class="tt-row"><span class="sw" style="background:${opts.color || playerColor(n)}"></span>${esc(n)}<b>${fmtSeconds(d.players[n])}</b></div>`).join("");
        showChartTip(`<div class="tt-when">${esc(dt)}</div>${rows || '<div class="tt-val">Nobody played</div>'}`, e.clientX, e.clientY);
      });
      r.addEventListener("mouseleave", hideChartTip);
    });
  };
  draw(); onResize(el, draw);
}
function roundedTop(x, y, w, h, r, fill) {
  return `<path d="M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z" fill="${fill}"/>`;
}
function legendHtml(names) {
  return `<div class="legend">${names.map((n) => `<span><i style="background:${playerColor(n)}"></i>${esc(n)}</span>`).join("")}</div>`;
}

// ================================================================ activity feed
const EVENT_ICON = { join: "→", leave: "←", chat: "💬", death: "☠", advancement: "★", server: "⚙", challenge: "🏆", race: "🏁", fish: "🎣", bigfish: "🐟", game: "🎲", webchat: "💬", webdm: "✉" };
function dayLabel(ts) {
  const d = new Date(ts * 1000), today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
}
// One timeline: each play session is a block in the player's colour holding what they
// did while online (deaths, advancements, chat). Joins/leaves are the block's edges, so
// they aren't repeated. Server events and anything outside a session stand alone.
const COUNT_LABELS = { death: ["death", "deaths"], advancement: ["advancement", "advancements"], chat: ["message", "messages"] };
const hm = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const NEST_SHOWN = 6;

function eventLineHtml(e, withName, colorNames = false) {
  let msg;
  const name = () => `<b${colorNames ? ` class="pname-c" style="color:${nameInk(e.player)}"` : ""}>${esc(e.player)}</b>`;
  if (e.type === "chat") msg = withName ? `${name()} ${esc(e.message)}` : esc(e.message);
  else {
    msg = esc(e.message);
    if (e.player) msg = withName ? msg.replace(esc(e.player), name()) : msg.replace(`${esc(e.player)} `, "");
    if (e.type === "advancement") msg = msg.replace(/\[(.+)\]$/, '<span class="adv-name">$1</span>');
    if (!withName) msg = msg.charAt(0).toUpperCase() + msg.slice(1);
  }
  return `<li class="feed-item ev-${esc(e.type)}"><span class="ev-icon" aria-hidden="true">${EVENT_ICON[e.type] || "•"}</span><span class="ev-time">${esc(hm(e.ts))}</span><span class="ev-msg">${msg}</span></li>`;
}

// Player names inside group blocks use a lighter tint of their series colour so the
// text stays readable on the dark panel (the colour bar carries the identity).
function nameInk(player) {
  const hex = playerColor(player).slice(1);
  const n = parseInt(hex, 16), mix = (c) => Math.round(c + (255 - c) * 0.45);
  return `rgb(${mix((n >> 16) & 255)} ${mix((n >> 8) & 255)} ${mix(n & 255)})`;
}

// Routine game and fishing lines (every catch, every bullseye) fold into one line per kind inside a
// session, which opens to show them all. Big catches, challenge and race results, chat, deaths and
// advancements stay as their own lines.
const BUNDLES = {
  fish: { types: ["fish"], icon: "🎣", one: "catch", many: "catches", min: 2 },
  big: { types: ["bigfish"], icon: "🐟", one: "big catch", many: "big catches", min: 3 },
  game: { types: ["game"], icon: "🎲", one: "game moment", many: "game moments", min: 2 },
};
// Trophy and Mythic fish and "caught every kind" are rare enough to always get their own line.
const ALWAYS_SHOWN = /\b(Trophy|Mythic)\b|every kind/;
function bundleOf(e) {
  if (ALWAYS_SHOWN.test(e.message || "")) return null;
  for (const [k, b] of Object.entries(BUNDLES)) if (b.types.includes(e.type)) return k;
  return null;
}
// Lines for a block's events, with routine ones bundled where the first of them happened.
function condensedLines(evs, withName, colorNames) {
  const groups = {};
  evs.forEach((e) => { const k = bundleOf(e); if (k) (groups[k] = groups[k] || []).push(e); });
  const out = [];
  const placed = new Set();
  for (const e of evs) {
    const k = bundleOf(e);
    if (!k || groups[k].length < BUNDLES[k].min) { out.push(eventLineHtml(e, withName, colorNames)); continue; }
    if (placed.has(k)) continue;
    placed.add(k);
    const g = groups[k], b = BUNDLES[k];
    const who = [...new Set(g.map((x) => x.player).filter(Boolean))];
    const span = `${hm(g[0].ts)}–${hm(g[g.length - 1].ts)}`;
    const whoText = withName && who.length ? ` · ${who.length > 3 ? `${who.length} players` : who.map(esc).join(", ")}` : "";
    out.push(`<li class="feed-item ev-bundle ev-${k}"><details><summary><span class="ev-icon" aria-hidden="true">${b.icon}</span><span class="ev-time">${esc(span)}</span><span class="ev-msg"><b>${g.length} ${g.length === 1 ? b.one : b.many}</b>${whoText}</span></summary>
      <ul class="nested">${g.map((x) => eventLineHtml(x, withName, colorNames)).join("")}</ul></details></li>`);
  }
  return out;
}

function groupBlockHtml(b) {
  const range = b.open
    ? `${hm(b.start)} – now <span class="live-tag"><span class="status-dot on"></span>playing</span>`
    : hasTime(b.seconds) ? `${hm(b.start)} – ${hm(b.end)}` : hm(b.start);     // without lengths (not an admin): when it started
  const people = b.players.map((n) => {
    const sess = b.sessions.filter((x) => x.player === n);
    const secs = sess.reduce((a, x) => a + (x.seconds || 0), 0), timed = sess.some((x) => hasTime(x.seconds));
    const uuid = sess[0]?.uuid;
    return `<a class="tl-who" href="#/s/${encodeURIComponent(curSid)}/p/${uuid || ""}" ${timed ? `title="${esc(n)} played ${esc(fmtSeconds(secs))}"` : ""}>${miniHead({ uuid, name: n }, 26)}<b style="color:${nameInk(n)}">${esc(n)}</b>${timed ? `<span class="muted tl-each">${secs >= 60 ? fmtSeconds(secs) : "<1m"}</span>` : ""}</a>`;
  }).join("");
  const summary = Object.entries(COUNT_LABELS).filter(([k]) => b.counts[k])
    .map(([k, [one, many]]) => `<span class="cnt ev-${k}"><span aria-hidden="true">${EVENT_ICON[k]}</span> ${b.counts[k]} ${b.counts[k] === 1 ? one : many}</span>`).join("");
  const evs = condensedLines(b.events, true, true);
  const hidden = Math.max(0, evs.length - NEST_SHOWN * 2);
  const stripes = b.players.map((n, i, a) => `${playerColor(n)} ${(i / a.length) * 100}% ${((i + 1) / a.length) * 100}%`).join(", ");
  return `<li class="tl-session tl-group" style="--stripe:linear-gradient(${stripes})">
    <div class="tl-head"><span class="tl-together">Played together</span><span class="tl-range">${range}</span>${hasTime(b.seconds) ? `<span class="tl-dur">${b.seconds >= 60 ? fmtSeconds(b.seconds) : "under a minute"}</span>` : ""}</div>
    <div class="tl-people">${people}</div>
    ${summary ? `<div class="tl-sum">${summary}</div>` : ""}
    ${evs.length ? `<ul class="nested">${evs.map((line, i) => line.replace('<li class="', `<li ${i >= NEST_SHOWN * 2 ? "hidden " : ""}class="`)).join("")}</ul>
      ${hidden ? `<button class="link-btn show-all" type="button">Show ${hidden} more</button>` : ""}` : ""}
  </li>`;
}

function sessionBlockHtml(b, showPlayer) {
  const color = playerColor(b.player);
  const range = b.open
    ? `${hm(b.start)} – now <span class="live-tag"><span class="status-dot on"></span>playing</span>`
    : hasTime(b.seconds) ? `${hm(b.start)} – ${hm(b.end || b.last_seen)}` : hm(b.start);
  const summary = Object.entries(COUNT_LABELS).filter(([k]) => b.counts[k])
    .map(([k, [one, many]]) => `<span class="cnt ev-${k}"><span aria-hidden="true">${EVENT_ICON[k]}</span> ${b.counts[k]} ${b.counts[k] === 1 ? one : many}</span>`).join("");
  const evs = condensedLines(b.events, false, false);
  const hidden = Math.max(0, evs.length - NEST_SHOWN);
  const body = evs.length
    ? `<ul class="nested">${evs.map((line, i) => line.replace('<li class="', `<li ${i >= NEST_SHOWN ? "hidden " : ""}class="`)).join("")}</ul>
       ${hidden ? `<button class="link-btn show-all" type="button">Show ${hidden} more</button>` : ""}`
    : "";
  const head = showPlayer
    ? `<a class="tl-who" href="#/s/${encodeURIComponent(curSid)}/p/${b.uuid || ""}">${miniHead({ uuid: b.uuid, name: b.player }, 26)}<b>${esc(b.player)}</b></a>`
    : "";
  return `<li class="tl-session" style="--pc:${color}">
    <div class="tl-head">${head}<span class="tl-range">${range}</span>${hasTime(b.seconds) ? `<span class="tl-dur">${b.seconds >= 60 ? fmtSeconds(b.seconds) : "under a minute"}</span>` : ""}</div>
    ${summary ? `<div class="tl-sum">${summary}</div>` : ""}${body}</li>`;
}

function timelineItemsHtml(items, state, showPlayer) {
  let out = "";
  for (const it of items) {
    const ts = it.kind === "event" ? it.ts : it.start;
    const day = dayLabel(ts);
    if (day !== state.lastDay) { out += `<li class="feed-day">${esc(day)}</li>`; state.lastDay = day; }
    out += it.kind === "group" ? groupBlockHtml(it)
      : it.kind === "session" ? sessionBlockHtml(it, showPlayer)
      : `<li class="tl-loose"><ul class="nested">${eventLineHtml(it, true)}</ul></li>`;
  }
  return out;
}

function mountTimeline(el, sid, player = "") {
  const st = { lastDay: null, before: null, chat: true, pages: 0, expanded: false };
  el.innerHTML = `<div class="toolbar"><label class="check toggle"><input type="checkbox" checked> Show chat</label></div>
    <ul class="timeline"></ul><button class="btn more" hidden>Show older</button>`;
  const list = $(".timeline", el), more = $(".more", el);
  const load = async (reset) => {
    if (reset) { st.lastDay = null; st.before = null; st.pages = 0; st.expanded = false; }
    st.pages += 1;
    const qs = new URLSearchParams({ sessions: "20", chat: st.chat ? "true" : "false" });
    if (player) qs.set("player", player);
    if (st.before) qs.set("before", st.before);
    const data = await api(`/api/servers/${encodeURIComponent(sid)}/timeline?${qs}`).catch(() => ({ items: [], next_before: null }));
    const html = timelineItemsHtml(data.items, st, !player);
    if (reset) list.innerHTML = html || `<li class="feed-empty">Nothing recorded yet. Play sessions and activity from the server log appear here as they happen.</li>`;
    else list.insertAdjacentHTML("beforeend", html);
    st.before = data.next_before;
    more.hidden = !data.next_before;
  };
  list.addEventListener("click", (e) => {
    const btn = e.target.closest(".show-all");
    if (!btn) return;
    btn.parentElement.querySelectorAll(":scope > .nested > li[hidden]").forEach((li) => (li.hidden = false));
    btn.remove();
    st.expanded = true;
  });
  $("input", el).addEventListener("change", (e) => { st.chat = e.target.checked; load(true); });
  more.addEventListener("click", () => load(false));
  load(true);
  // Auto-refresh only while the reader is on the first page and hasn't expanded anything.
  return () => { if (st.pages <= 1 && !st.expanded) load(true); };
}

// ================================================================ Activity (part of the Overview tab)
// Daily play-time chart plus the session timeline. Returns a refresh function.
function mountActivity(el, sid, playerNames) {
  setPlayerSlots(playerNames);
  let days = 14;
  el.innerHTML = `
    <section class="section"><div class="section-head"><h2 id="act-title">Time played</h2>
      <div class="seg" role="group" aria-label="Days shown" id="days-seg">${[7, 14, 30].map((d) => `<button data-d="${d}" aria-pressed="${d === days}">${d} days</button>`).join("")}</div></div>
      <div class="panel"><div id="today-row" class="today-row"></div><div id="legend"></div><div class="chart" id="daily-chart"></div></div>
    </section>
    <section class="section"><div class="section-head"><h2>Activity</h2><span class="muted">One block per play session. Players online at the same time share a block</span></div>
      <div id="feed"></div></section>`;
  const refreshFeed = mountTimeline($("#feed", el), sid);
  const load = async () => {
    const a = await api(`/api/servers/${sid}/activity?days=${days}`);
    if (!$("#daily-chart")) return;
    const names = [...new Set(a.daily.flatMap((d) => Object.keys(d.players)))].sort((x, y) => playerColor(x).localeCompare(playerColor(y)));
    const order = Object.keys(playerSlots).map((k) => names.find((n) => n.toLowerCase() === k)).filter(Boolean);
    const today = a.daily[a.daily.length - 1].players, timed = a.durations !== false;
    const todayNames = Object.keys(today).sort((x, y) => (timed ? today[y] - today[x] : x.localeCompare(y)));
    $("#act-title").textContent = timed ? "Time played" : "Who played";
    $("#today-row").innerHTML = todayNames.length
      ? `<span class="muted">Today</span>${todayNames.map((n) => `<span class="chip"><span class="sw" style="background:${playerColor(n)}"></span><b>${esc(n)}</b>${timed ? ` ${fmtSeconds(today[n])}` : ""}</span>`).join("")}`
      : `<span class="muted">Nobody has played today yet.</span>`;
    if (!timed) { $("#legend").innerHTML = ""; renderDaysPlayed($("#daily-chart"), a.daily, order); return; }
    if (!order.length) {
      $("#legend").innerHTML = "";
      $("#daily-chart").innerHTML = `<div class="empty"><h3>No play time recorded yet</h3><p>Solstone checks who's online every 30 seconds. Daily totals build up from today onward.</p></div>`;
    } else {
      $("#legend").innerHTML = order.length > 1 ? legendHtml(order) : "";
      renderDailyBars($("#daily-chart"), a.daily, order);
    }
  };
  $$("#days-seg button", el).forEach((b) => b.addEventListener("click", () => {
    days = +b.dataset.d; $$("#days-seg button", el).forEach((x) => x.setAttribute("aria-pressed", x === b)); load();
  }));
  load();
  return () => { load(); refreshFeed(); };
}

// ================================================================ Performance tab
function tpsStatus(tps) {
  if (tps == null) return null;
  if (tps >= 19.5) return { label: "Smooth", cls: "good", icon: "●" };
  if (tps >= 15) return { label: "A little laggy", cls: "warn", icon: "▲" };
  return { label: "Lagging", cls: "bad", icon: "■" };
}
async function viewPerformance(sid) {
  const s = await serverFrame(sid, "performance");
  let range = "24h";
  setView(serverHeader(s, "performance") + `
    <div class="section-head"><h2>Performance</h2>
      <div class="seg" role="group" aria-label="Time range" id="range-seg">${["6h", "24h", "7d", "30d"].map((r) => `<button data-r="${r}" aria-pressed="${r === range}">${r}</button>`).join("")}</div></div>
    <div id="perf-tiles"></div><div id="perf-body"></div>`);
  wireHeader(s);
  const load = async () => {
    let mt;
    try { mt = await api(`/api/servers/${sid}/metrics?range=${range}`); }
    catch (err) {
      $("#perf-tiles").innerHTML = "";
      $("#perf-body").innerHTML = `<div class="notice">Couldn't load performance history: ${esc(err.message)}</div>`;
      return;
    }
    const pts = mt.points, until = Date.now() / 1000;
    const rec = mt.recorder || {};
    const l = mt.latest;
    const fresh = l && until - l.ts < 180;
    const st = fresh && l.running ? tpsStatus(l.tps) : null;
    const peak = Math.max(0, ...pts.map((p) => p.players || 0));
    const tiles = [
      [fresh && l.running && l.tps != null ? l.tps.toFixed(1) : "–", "TPS (20 is perfect)", st],
      [fresh && l.running && l.mspt != null ? `${l.mspt.toFixed(1)} ms` : "–", "Tick time (under 50 ms is fine)"],
      [fresh && l.running && l.cpu != null ? `${l.cpu.toFixed(1)}%` : "–", "CPU"],
      [fresh && l.running && l.mem_mb != null ? `${(l.mem_mb / 1024).toFixed(2)} GB` : "–", "Memory"],
      [mt.uptime != null ? `${(mt.uptime * 100).toFixed(mt.uptime > 0.999 ? 0 : 1)}%` : "–", `Uptime, last ${range}`],
      [String(peak), `Most players at once, last ${range}`],
    ];
    $("#perf-tiles").innerHTML = `<div class="stat-strip">${tiles.map(([v, k, status]) => `<div><div class="v">${esc(v)}</div><div class="k">${esc(k)}</div>${status ? `<div class="status ${status.cls}"><span aria-hidden="true">${status.icon}</span> ${esc(status.label)}</div>` : ""}</div>`).join("")}</div>`;
    const notes = [];
    if (rec.error) notes.push(`<div class="notice">Recording this server is failing: <code>${esc(rec.error)}</code></div>`);
    else if (!rec.running) notes.push(`<div class="notice">The background recorder isn't running, so no new measurements are being saved.</div>`);
    else if (rec.last_poll && until - rec.last_poll > rec.interval * 4) notes.push(`<div class="notice">The last measurement was ${esc(fmtAgo(rec.last_poll))}. The recorder may be stuck; check the container logs.</div>`);
    if (!pts.length) {
      $("#perf-body").innerHTML = notes.join("") + `<div class="empty"><h3>No measurements yet</h3><p>Solstone records performance every ${Math.round(rec.interval || 30)} seconds while it's running. Check back in a few minutes.</p></div>`;
      return;
    }
    if (mt.first_ts && until - mt.first_ts < 3600) {
      notes.push(`<p class="muted" style="margin-bottom:14px">Recording started ${esc(fmtAgo(mt.first_ts))}. The charts fill in over the next hour; until then each measurement shows as a dot.</p>`);
    }
    const hasTps = pts.some((p) => p.tps != null);
    $("#perf-body").innerHTML = notes.join("") + `<div class="charts">
      <div class="panel"><h3>TPS</h3>${hasTps ? '<div class="chart" id="c-tps"></div>' : `<p class="muted">TPS needs RCON on Minecraft 1.20.3 or newer.</p>`}</div>
      <div class="panel"><h3>Tick time</h3>${hasTps ? '<div class="chart" id="c-mspt"></div>' : `<p class="muted">Tick time needs RCON on Minecraft 1.20.3 or newer.</p>`}</div>
      <div class="panel"><h3>Players online</h3><div class="chart" id="c-players"></div></div>
      <div class="panel"><h3>CPU</h3>${pts.some((p) => p.cpu != null) ? '<div class="chart" id="c-cpu"></div>' : '<p class="muted">CPU comes from Crafty. Set CRAFTY_URL and CRAFTY_TOKEN to record it.</p>'}</div>
      <div class="panel"><h3>Memory</h3>${pts.some((p) => p.mem_mb != null) ? '<div class="chart" id="c-mem"></div>' : '<p class="muted">Memory comes from Crafty. Set CRAFTY_URL and CRAFTY_TOKEN to record it.</p>'}</div>
    </div><p class="muted" style="margin-top:12px;font-size:.88rem">Shaded areas are times the server was offline.</p>`;
    const base = { bucket: mt.bucket, since: mt.since, until };
    const safe = (id, spec) => {
      const el = $(id);
      if (!el) return;
      try { renderLine(el, spec); } catch (err) { el.innerHTML = `<p class="muted">This chart couldn't be drawn: ${esc(err.message)}</p>`; console.error(err); }
    };
    const series = (k) => pts.map((p) => ({ t: p.t, v: p[k], running: p.running }));
    if (hasTps) {
      safe("#c-tps", { ...base, points: pts.map((p) => ({ t: p.t, v: p.tps_min ?? p.tps, running: p.running })), max: 20, fmt: (v) => v == null ? "–" : v.toFixed(1), label: "TPS over time" });
      safe("#c-mspt", { ...base, points: series("mspt"), fmt: (v, axis) => v == null ? "–" : `${axis ? Math.round(v) : v.toFixed(1)} ms`, target: { v: 50, label: "50 ms limit" }, label: "Tick time over time" });
    }
    safe("#c-players", { ...base, points: series("players"), max: Math.max(4, niceMax(peak)), fmt: (v, axis) => v == null ? "–" : axis ? String(Math.round(v)) : `${v} online`, label: "Players online over time" });
    safe("#c-cpu", { ...base, points: series("cpu"), fmt: (v, axis) => v == null ? "–" : `${axis ? Math.round(v) : v.toFixed(1)}%`, label: "CPU over time" });
    const memGb = pts.map((p) => ({ t: p.t, v: p.mem_mb == null ? null : p.mem_mb / 1024, running: p.running }));
    safe("#c-mem", { ...base, points: memGb, fmt: (v, axis) => v == null ? "–" : axis ? `${+v.toFixed(2)} GB` : `${v.toFixed(2)} GB`, label: "Memory over time" });
  };
  $$("#range-seg button").forEach((b) => b.addEventListener("click", () => {
    range = b.dataset.r; $$("#range-seg button").forEach((x) => x.setAttribute("aria-pressed", x === b)); load();
  }));
  await load();
  every(30000, load);
}

// Which days each person played (a square for each day), for anyone who doesn't see how long.
function renderDaysPlayed(el, daily, names) {
  if (!names.length) { el.innerHTML = `<div class="empty"><p>Nobody has played in these days yet.</p></div>`; return; }
  const day = (iso) => new Date(`${iso}T12:00:00`);
  const label = (iso) => day(iso).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  el.innerHTML = `<div class="dp-grid" style="--days:${daily.length}">
    <span></span>${daily.map((d, i) => `<span class="dp-day">${i === daily.length - 1 ? "Today" : day(d.date).getDate()}</span>`).join("")}
    ${names.map((n) => `<b class="dp-name" style="color:${nameInk(n)}">${esc(n)}</b>${daily.map((d) => `<span class="dp-cell ${d.players[n] ? "on" : ""}" style="--pc:${playerColor(n)}" title="${esc(n)} · ${esc(label(d.date))}${d.players[n] ? "" : " (didn't play)"}"></span>`).join("")}`).join("")}
  </div>`;
}

// ================================================================ player history tab
async function renderPlayerHistory(el, sid, p) {
  el.innerHTML = `<section class="section"><div class="section-head"><h2>Time played per day</h2><span class="muted" id="h-total"></span></div>
      <div class="panel"><div class="chart" id="p-daily"></div></div></section>
    <section class="section"><div class="section-head"><h2>Sessions and activity</h2></div><div id="p-feed"></div></section>`;
  const all = await api(`/api/servers/${sid}/players`).catch(() => ({ players: [] }));
  setPlayerSlots(all.players.map((x) => x.name));
  const h = await api(`/api/servers/${sid}/players/${p.uuid}/history?days=30`);
  if (h.durations === false) {           // which days they played, not for how long
    el.querySelector(".section-head h2").textContent = "Days played";
    const n = h.daily.filter((d) => d.played).length;
    $("#h-total").textContent = `${n} of the last ${h.daily.length} days`;
    renderDaysPlayed($("#p-daily"), h.daily.map((d) => ({ date: d.date, players: d.played ? { [p.name]: 1 } : {} })), [p.name]);
    mountTimeline($("#p-feed"), sid, p.name);
    return;
  }
  const total = h.daily.reduce((a, d) => a + d.seconds, 0);
  const week = h.daily.slice(-7).reduce((a, d) => a + d.seconds, 0);
  $("#h-total").textContent = `${fmtSeconds(week)} this week · ${fmtSeconds(total)} in 30 days`;
  if (!total) $("#p-daily").innerHTML = `<div class="empty"><p>No play time recorded yet. Daily totals build up from when Solstone started recording.</p></div>`;
  else renderDailyBars($("#p-daily"), h.daily.map((d) => ({ date: d.date, players: { [p.name]: d.seconds } })), [p.name], { color: playerColor(p.name), label: `${p.name}'s time played per day` });
  mountTimeline($("#p-feed"), sid, p.name);
}

// ================================================================ notification settings
async function viewNotifications() {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = `Notifications · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  const c = await api("/api/settings/notifications").catch(() => null);
  if (!c) { setView('<div class="panel"><p>Couldn\'t load the notification settings.</p></div>'); return; }
  const labels = { join: "Someone joins", leave: "Someone leaves", death: "Someone dies", advancement: "Advancements",
    server: "Server starts, stops or crashes", backup: "Backups are overdue", blocked: "Someone the whitelist turned away (with their exact name, to let them in from Control)",
    updates: "New builds of the server's mods (Geyser and Floodgate first: Bedrock players need them up to date)",
    messages: "A player sends a message (Manage → Messages)" };
  const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const hourLabel = (h) => new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" });
  setView(`<div class="fwe-head"><h1>Notifications</h1>
      <p class="muted">Get a message on your phone (ntfy) or in Discord when things happen on the servers.</p></div>
    <form id="notify-form" class="panel notify-page">
      <label>ntfy topic URL <small>For example https://ntfy.sh/your-secret-topic or your own ntfy server</small><input class="input" name="ntfy_url" value="${esc(c.ntfy_url || "")}" placeholder="https://ntfy.sh/solstone-abc123"></label>
      <label>ntfy access token <small>${c.ntfy_token_set ? "Saved. Type a new one to replace it." : "Only needed if your topic is protected"}</small><input class="input" type="password" name="ntfy_token" autocomplete="off"></label>
      <label>Discord webhook URL <small>${c.discord_webhook_set ? "Saved. Paste a new one to replace it." : "Server Settings → Integrations → Webhooks in Discord"}</small><input class="input" type="password" name="discord_webhook" autocomplete="off"></label>
      <fieldset class="checks"><legend>Send a notification when</legend>
        ${c.event_types.map((t) => `<label class="check"><input type="checkbox" name="ev" value="${t}" ${c.events.includes(t) ? "checked" : ""}> ${esc(labels[t] || t)}</label>`).join("")}
      </fieldset>
      <p class="muted small">Daily screen-time limits and bedtimes are in <a href="#/manage/playtime">Manage → Play time</a>. You're notified here when someone reaches their limit.</p>
      <fieldset class="checks"><legend>Weekly digest</legend>
        <label class="check"><input type="checkbox" name="digest_enabled" ${c.digest_enabled ? "checked" : ""}> Send a weekly summary of who played, deaths and advancements</label>
        <div class="row2">
          <label>Day<select class="input" name="digest_day">${days.map((d, i) => `<option value="${i}" ${i === c.digest_day ? "selected" : ""}>${d}</option>`).join("")}</select></label>
          <label>Time<select class="input" name="digest_hour">${Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${h === c.digest_hour ? "selected" : ""}>${hourLabel(h)}</option>`).join("")}</select></label>
        </div>
        <button type="button" class="link-btn" id="btn-digest">Preview this week's digest</button>
        <pre class="digest-preview" id="digest-preview" hidden></pre>
      </fieldset>
      <fieldset class="checks"><legend>Each server</legend>
        <p class="muted" style="font-size:.85rem;margin:0 0 8px">Leave a server on <b>Same as above</b>, turn it off, or give it its own choices and quiet hours.</p>
        ${(state.servers || []).map((s) => { const o = c.servers?.[s.id] || { mode: "same", events: c.events, quiet_enabled: false, quiet_start: "22:00", quiet_end: "07:00" };
          return `<div class="ns-server" data-sid="${esc(s.id)}"><div class="ns-head"><b>${esc(s.name)}</b>
            <select class="input sm" data-ns-mode aria-label="Notifications for ${esc(s.name)}">${[["same", "Same as above"], ["off", "No notifications"], ["own", "Its own choices"]].map(([k, l]) => `<option value="${k}" ${o.mode === k ? "selected" : ""}>${l}</option>`).join("")}</select></div>
            <div class="ns-own" ${o.mode === "own" ? "" : "hidden"}>${c.event_types.map((t) => `<label class="check"><input type="checkbox" data-ns-ev value="${t}" ${(o.events || []).includes(t) ? "checked" : ""}> ${esc(labels[t] || t)}</label>`).join("")}
              <label class="check"><input type="checkbox" data-ns-quiet ${o.quiet_enabled ? "checked" : ""}> Quiet hours for this server</label>
              <div class="row2"><label>From<input class="input" type="time" data-ns-from value="${esc(o.quiet_start || "22:00")}"></label><label>Until<input class="input" type="time" data-ns-until value="${esc(o.quiet_end || "07:00")}"></label></div></div></div>`; }).join("")}
      </fieldset>
      <label class="switch-row"><span><b>Quiet hours</b><br><small class="muted">No notifications between these times${c.quiet_now ? " (they're on right now)" : ""}. A server with its own choices uses its own.</small></span>
        <input type="checkbox" role="switch" name="quiet_enabled" ${c.quiet_enabled ? "checked" : ""}></label>
      <div class="row2" id="quiet-times">
        <label>Quiet from<input class="input" type="time" name="quiet_start" value="${esc(c.quiet_start || "22:00")}"></label>
        <label>Until<input class="input" type="time" name="quiet_end" value="${esc(c.quiet_end || "07:00")}"></label>
      </div>
      <div class="actions"><button type="button" class="btn" id="btn-test">Send test</button><span style="flex:1"></span>
        <button class="btn primary" type="submit">Save notifications</button></div>
    </form>`);
  {
    const m = view();
    const form = $("#notify-form", m);
    const quiet = () => { const on = form.quiet_enabled.checked; $$("#quiet-times input", form).forEach((i) => { i.disabled = !on; }); $("#quiet-times", form).classList.toggle("off", !on); };
    form.quiet_enabled.addEventListener("change", quiet); quiet();
    $$("[data-ns-mode]", form).forEach((sel) => sel.addEventListener("change", () => { sel.closest(".ns-server").querySelector(".ns-own").hidden = sel.value !== "own"; }));
    const body = () => {
      const f = new FormData(form);
      const b = { ntfy_url: f.get("ntfy_url"), events: f.getAll("ev"), quiet_enabled: !!f.get("quiet_enabled"), quiet_start: form.quiet_start.value, quiet_end: form.quiet_end.value,
        digest_enabled: !!f.get("digest_enabled"), digest_day: Number(f.get("digest_day")), digest_hour: Number(f.get("digest_hour")) };
      b.servers = {};
      $$(".ns-server", form).forEach((el) => {
        const mode = $("[data-ns-mode]", el).value;
        b.servers[el.dataset.sid] = { mode, events: $$("[data-ns-ev]", el).filter((i) => i.checked).map((i) => i.value),
          quiet_enabled: $("[data-ns-quiet]", el).checked, quiet_start: $("[data-ns-from]", el).value, quiet_end: $("[data-ns-until]", el).value };
      });
      if (f.get("ntfy_token")) b.ntfy_token = f.get("ntfy_token");
      if (f.get("discord_webhook")) b.discord_webhook = f.get("discord_webhook");
      return b;
    };
    const adminFetch = (url, opts) => api(url, opts);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await adminFetch("/api/settings/notifications", { method: "PUT", body: JSON.stringify(body()) }); showToast("Notifications saved", 2500); }
      catch (err) { showError(`Couldn't save notifications: ${esc(err.message)}`, 5000); }
    });
    $("#btn-digest", m).addEventListener("click", async () => {
      const pre = $("#digest-preview", m);
      pre.hidden = false; pre.textContent = "Building…";
      try { pre.textContent = (await api("/api/settings/notifications/digest", { method: "POST" })).text; }
      catch (err) { pre.textContent = `Couldn't build the digest: ${err.message}`; }
    });
    $("#btn-test", m).addEventListener("click", async () => {
      try {
        await adminFetch("/api/settings/notifications", { method: "PUT", body: JSON.stringify(body()) });
        const r = await adminFetch("/api/settings/notifications/test", { method: "POST" });
        showToast(r.ok ? "Test notification sent" : `Test failed: ${esc(r.errors.join("; "))}`, 6000);
      } catch (err) { showToast(`Test failed: ${esc(err.message)}`, 6000); }
    });
  }
}
