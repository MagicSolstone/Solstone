/* Solstone — announcement banners, shared by the app, the sign-in page and the status page.
   Notes and countdowns (from Announcements), bedtime and the holiday of the day.
   Countdowns tick here every second; at zero a note can set off a show. */
"use strict";

function fmtCountdown(sec) {
  sec = Math.max(0, Math.ceil(sec));
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (d) return `${d} d ${h} h`;
  if (h) return `${h} h ${String(m).padStart(2, "0")} min`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// el: where the banners go. opts: where ("app" | "status" | "login"), sid() -> server in view,
// scene() -> the sky (for shows at zero), dismiss (let people hide a banner), onItems(items),
// max (show this many, with "+N more"), ticker() -> true to show one at a time, cycling (TV mode).
// An announcement's text with its formatting (bold, italic, links, colours: the same as posts, from postfmt.js),
// escaped first so it can't carry HTML of its own. Plain where postfmt.js isn't loaded.
function annFmt(text) {
  return typeof inline === "function" ? inline(esc(text || "")) : esc(text || "");
}
// A banner's own colours (the "Your colours" look): a gradient of two or three, see-through enough to read on.
function annLook(it) {
  const cs = (it.style === "custom" && it.colors?.length ? it.colors : []).filter((c) => /^#[0-9a-f]{6}$/i.test(c));
  if (!cs.length) return "";
  const rgba = (h, a) => `rgba(${parseInt(h.slice(1, 3), 16)}, ${parseInt(h.slice(3, 5), 16)}, ${parseInt(h.slice(5, 7), 16)}, ${a})`;
  const stops = (cs.length === 1 ? [cs[0], "#141928"] : cs).map((c, i) => rgba(c, i === 0 ? 0.62 : 0.5));
  return ` style="border-left-color:${cs[0]};background:linear-gradient(90deg, ${stops.join(", ")})"`;
}
// A holiday reward's items with their pictures ("🥧 3 × Pumpkin Pie"), for the Events pages and its banner.
function rewardItemsHtml(items) {
  return (items || []).map((x) => {
    const [ns, n] = x.item.includes(":") ? x.item.split(":") : ["minecraft", x.item];
    return `<span class="rw-item"><img src="/api/public/reward-item/${encodeURIComponent(ns)}/${encodeURIComponent(n)}.png" alt="" width="20" height="20" loading="lazy" data-fail="remove">${esc(String(x.count))} × ${esc(x.name)}</span>`;
  }).join("");
}
// A holiday's reward on the Events pages: its own line under the holiday.
function rewardLineHtml(r) {
  if (!r?.items?.length) return "";
  return `<div class="up-reward"><span class="up-reward-tag">🎁 Reward</span>${rewardItemsHtml(r.items)}${r.note ? `<span class="up-reward-note">${annFmt(r.note)}</span>` : ""}
    <span class="muted small">Play ${r.first === r.last ? "on" : "any time"} ${esc(r.when)}</span></div>`;
}
// A holiday's reward on its banner: 🎁, its description, the items with their pictures, and the last day for it.
// The game's clock: a time of day (0-23999 ticks, 0 = 6 AM) as a clock time, its part of the day, and an emoji.
function mcClock(t) {
  const hour = Math.floor((t / 1000 + 6) % 24), min = Math.floor(((t % 1000) / 1000) * 60);
  return new Date(2000, 0, 1, hour, min).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
const mcPhase = (t) => (t < 6000 ? "Morning" : t < 12000 ? "Afternoon" : t < 13000 ? "Sunset" : t < 23000 ? "Night" : "Sunrise");
function mcWeather(w) { return w.thunder ? "Thunderstorm" : w.rain ? "Raining" : "Clear skies"; }
function mcEmoji(t, w) {
  if (w.thunder) return "⛈️";
  if (w.rain) return "🌧️";
  const p = mcPhase(t);
  return p === "Night" ? "🌙" : p === "Sunset" || p === "Sunrise" ? "🌅" : "☀️";
}
// Where the clock is now: counted on from when the server said it, while it's running with people on (20 ticks a second)
const mcNow = (w) => Math.floor(w.t + (w.ticking ? Math.max(0, Date.now() / 1000 - w.as_of) * 20 : 0)) % 24000;
// Events that finished in the last few days, and how they went (never who): under the timeline on the Events pages.
function upPastHtml(past, cls = "panel") {
  if (!past?.length) return "";
  const when = (p) => { const d = new Date(p.at * 1000), days = Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 864e5);
    return `${days === 0 ? "Today" : days === 1 ? "Yesterday" : d.toLocaleDateString([], { weekday: "long" })}, ${p.time}`; };
  return `<section class="up-past"><h2>Lately</h2><ul class="up-past-list ${cls}">${past.map((p) => `<li><span class="up-emoji" aria-hidden="true">${esc(p.emoji)}</span>
    <div class="up-main"><b>${esc(p.title)}</b><span class="muted small">${esc([p.how, p.server].filter(Boolean).join(" · "))}</span></div>
    <span class="up-when muted small">${esc(when(p))}</span></li>`).join("")}</ul></section>`;
}
function bnRewardHtml(it) {
  return `<small class="bn-reward"><span class="bn-gift" aria-hidden="true">🎁</span>${it.reward_note ? `<span class="bn-rnote">${annFmt(it.reward_note)}</span>` : ""}${rewardItemsHtml(it.items)}${it.reward_until ? `<span class="bn-until">${esc(it.reward_until)}</span>` : ""}</small>`;
}
// An Events row's title: formatted when it has formatting of its own (a holiday's name).
const upTitle = (it) => (it.title_fmt ? annFmt(it.title_fmt) : esc(it.title));
// A holiday's card on Events takes its banner's look (the same colours everywhere for that holiday).
function upLook(it) {
  if (!it.look) return { cls: "", style: "" };
  return { cls: ` up-look bn-${esc(it.look.style)}`, style: annLook(it.look) };
}
// The Events page as a timeline down the page: today at the top (with what's on now), then a dot for each day with
// something on, and a dotted stretch saying how long between them. Kept simple: a holiday is one dot (a gold ring when
// it has a reward); the reward's own dates are on its card. One extra: a reward that's already started, for a holiday
// still ahead, is said under Today, so nobody misses it.
// row(it) draws each card; cls: the list's own class ("panel" in the app, "glass" outside).
function upTimeline(items, row, cls = "panel") {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const toDay = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const long = (d) => d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  const between = (a, b) => Math.round((b - a) / 86400000);
  const short = (isoDay) => { const d = toDay(isoDay); return `${d.toLocaleDateString([], { weekday: "short" })} ${d.getDate()} ${d.toLocaleDateString([], { month: "short" })}`; };
  const now = items.filter((x) => x.live || x.date === iso(today) || toDay(x.date) < today);
  const groups = [];
  for (const it of items.filter((x) => !now.includes(x))) {
    const g = groups[groups.length - 1];
    if (g && g.date === it.date) g.items.push(it); else groups.push({ date: it.date, items: [it] });
  }
  const until = (d) => { const n = between(today, d); return n === 1 ? "Tomorrow" : `In ${n} days`; };
  const list = (l) => `<ul class="up-list ${cls}">${l.map(row).join("")}</ul>`;
  const name = (x) => (x.title_fmt ? annFmt(x.title_fmt) : esc(x.title));
  const t = iso(today);
  const onNow = items.filter((x) => !now.includes(x) && x.reward?.first && x.reward.first <= t && t <= x.reward.last)
    .map((x) => `<p class="tl-rnow"><span aria-hidden="true">🎁</span> <b>${name(x)}'s reward is on now</b> <span class="muted">· play any day until ${esc(short(x.reward.last))}</span></p>`).join("");
  const gift = (l) => (l.some((x) => x.reward) ? " tl-has-reward" : "");
  let html = `<ol class="tl"><li class="tl-step tl-now${gift(now)}"><span class="tl-node" aria-hidden="true"></span>
    <div class="tl-date"><b>Today</b><span>${esc(long(today))}</span></div>
    ${onNow}${now.length ? list(now) : onNow ? "" : `<p class="muted small tl-quiet">Nothing on right now.</p>`}</li>`;
  let prev = today;
  for (const g of groups) {
    const d = toDay(g.date), gap = between(prev, d);
    if (gap > 1) html += `<li class="tl-gap" aria-hidden="true"><span>${gap} days</span></li>`;
    html += `<li class="tl-step${gift(g.items)}"><span class="tl-node" aria-hidden="true"></span>
      <div class="tl-date"><b>${esc(long(d))}</b><span>${until(d)}</span></div>${list(g.items)}</li>`;
    prev = d;
  }
  return `${html}</ol>`;
}
// Which Minecraft: small pixel pictures of our own (not the official logos), the same everywhere.
//   java: a grass block · bedrock: a stone block · friend: a game controller (joining through a friend)
const ED_PIX = {
  java: ["GGGGGGGG", "GgGGGgGG", "dGdGGdGd", "DdddDddd", "ddDdddDd", "dddDdddd", "dDddddDd", "ddddDddd"],
  bedrock: ["SsSSsSSs", "SSSsSSSs", "sSkSSsSS", "SSSSkSsS", "SsSSSSSk", "kSSsSSsS", "SSkSSkSS", "sSSSsSSs"],
  friend: ["........", ".XXXXXX.", "XXbXXXaX", "XbbbXcXy", "XXbXXXzX", "XXXXXXXX", "XX....XX", "........"],
};
const ED_COL = { G: "#5bbf3a", g: "#7fd94f", d: "#8a5a35", D: "#6e4426", S: "#8e9399", s: "#a9adb2", k: "#5d6166",
  X: "#2f3b33", b: "#e8f2ea", a: "#7fd94f", c: "#4fb3ff", y: "#ffd34f", z: "#ff6b5b" };
function edIcon(kind, size = 16) {
  const rows = ED_PIX[kind] || [];
  const rects = rows.flatMap((row, y) => [...row].map((ch, x) => (ED_COL[ch] ? `<rect x="${x}" y="${y}" width="1" height="1" fill="${ED_COL[ch]}"/>` : ""))).join("");
  return `<svg class="ed-ico" viewBox="0 0 8 8" width="${size}" height="${size}" shape-rendering="crispEdges" aria-hidden="true">${rects}</svg>`;
}
// Bedrock players come in through Floodgate: a "." before their name, and an id starting with zeros.
const isBedrockPlayer = (p) => !!(p?.bedrock || p?.name?.startsWith(".") || /^00000000-0000-0000-000/.test(p?.uuid || ""));
// Joining through the Xbox friend (MCXboxBroadcast): is it working right now? (xboxwatch.py)
const XBOX_STATE = {
  ok: ["ok", "Online", "friends can join right now"],
  reconnecting: ["wait", "Reconnecting", "usually back in a few seconds"],
  down: ["down", "Not working right now", "use the server address below for now"],
  off: ["off", "Offline", "the server is off right now"],
  unknown: ["off", "Checking", "waiting to hear from the friend account"],
};
function xboxStateHtml(x, cls = "hp-xbox-st") {
  if (!x) return "";
  const [k, word, more] = XBOX_STATE[x.state] || XBOX_STATE.unknown;
  return `<p class="${cls} ${k}" role="status"><span class="xb-dot" aria-hidden="true"></span><b>${word}</b><span class="muted"> · ${more}</span></p>`;
}
// A player's edition, as a small badge beside their name.
function edBadge(bedrock) {
  return `<span class="ed-badge ${bedrock ? "bedrock" : "java"}" title="${bedrock ? "Playing on Bedrock" : "Playing on Java"}">${edIcon(bedrock ? "bedrock" : "java", 12)}${bedrock ? "Bedrock" : "Java"}</span>`;
}
// Distances, in kilometres or miles (Website → Site details → Distances in). A block is a metre: short ones stay in blocks.
const USE_MILES = document.querySelector('meta[name="solstone-units"]')?.content === "miles";
function fmtDist(meters, dp = 1) {
  const m = Number(meters) || 0;
  if (USE_MILES) return m >= 1609.344 ? `${(m / 1609.344).toLocaleString([], { maximumFractionDigits: m >= 160934 ? 0 : dp })} mi` : `${Math.round(m).toLocaleString()} blocks`;
  return m >= 1000 ? `${(m / 1000).toLocaleString([], { maximumFractionDigits: m >= 100000 ? 0 : dp })} km` : `${Math.round(m).toLocaleString()} blocks`;
}
// Solstone's own activity lines say "travelled 1.5 km": in miles when that's chosen.
function distText(text) {
  return USE_MILES ? String(text || "").replace(/([\d.]+) km\b/g, (_, n) => `${(parseFloat(n) / 1.609344).toFixed(1)} mi`) : String(text || "");
}
// The same without the formatting, for places that only take plain text.
function annPlain(text) {
  return String(text || "").replace(/\[([^\]]+)\]\([^)\s]+\)/g, "$1").replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/(^|[\s(])[*_]([^*_]+)[*_]/g, "$1$2").replace(/\{\/?[a-z]+\}/g, "");
}

function startBoard(el, opts = {}) {
  if (!el) return null;
  let items = [], offset = 0, pollT = 0, tickT = 0, stopped = false, expanded = false, turn = 0, turnAt = Date.now();
  const seenLive = new Set();          // countdowns this page watched tick (so a reload doesn't replay the zero moment)
  const fired = new Set();
  const lsGet = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } };
  const dismissed = () => new Set(lsGet("solstone-dismissed", []));
  const now = () => (Date.now() + offset) / 1000;

  const overlay = document.createElement("div");
  overlay.className = "fw-countdown board-cd"; overlay.hidden = true;
  document.body.append(overlay);
  let overlayT = 0;
  const bigText = (text, ms = 6000) => {
    overlay.hidden = false; overlay.classList.add("msg"); overlay.textContent = text;
    clearTimeout(overlayT); overlayT = setTimeout(() => { overlay.hidden = true; overlay.classList.remove("msg"); }, ms);
  };

  const visible = () => { const gone = dismissed(); return items.filter((i) => !gone.has(i.id)); };
  const cdHtml = (it) => {
    if (!it.countdown) return "";
    const left = it.countdown - now();
    return `<span class="bn-cd" data-cd="${it.countdown}">${left > 0 ? esc(fmtCountdown(left)) : esc(it.done_text || "Now!")}</span>`;
  };
  function render() {
    const all = visible();
    el.hidden = !all.length;
    const ticker = opts.ticker?.() && all.length > 1;
    let list = all, more = "";
    if (ticker) list = [all[turn % all.length]];
    else if (opts.max && all.length > opts.max + 1 && !expanded) { list = all.slice(0, opts.max); more = `<button class="bn-more" type="button" data-more>+${all.length - opts.max} more</button>`; }
    else if (opts.max && all.length > opts.max + 1) more = `<button class="bn-more" type="button" data-more>Show less</button>`;
    el.classList.toggle("ticker", !!ticker);
    const html = list.map((it) => `<div class="bn bn-${esc(it.style)} bn-k-${esc(it.kind)}" data-id="${esc(it.id)}" role="status"${annLook(it)}>
      ${it.emoji ? `<span class="bn-emoji" aria-hidden="true">${esc(it.emoji)}</span>` : ""}
      <div class="bn-text"><b>${it.link && it.link.startsWith("/app#/") ? `<a href="${esc(it.link)}">${esc(annPlain(it.text))}</a>` : annFmt(it.text)}</b>${it.detail ? `<small>${annFmt(it.detail)}</small>` : ""}${it.items ? bnRewardHtml(it) : ""}</div>
      ${cdHtml(it)}${opts.dismiss ? `<button class="bn-x" type="button" data-dismiss="${esc(it.id)}" aria-label="Hide this">×</button>` : ""}</div>`).join("")
      + more + (ticker ? `<div class="bn-dots" aria-hidden="true">${all.map((_, i) => `<i class="${i === turn % all.length ? "on" : ""}"></i>`).join("")}</div>` : "");
    if (el._html !== html) { el._html = html; el.innerHTML = html; }
    opts.onItems?.(list);
  }
  el.addEventListener("click", (e) => {
    if (e.target.closest("[data-more]")) { expanded = !expanded; render(); return; }
    const b = e.target.closest("[data-dismiss]");
    if (!b) return;
    const gone = dismissed(); gone.add(b.dataset.dismiss);
    lsSet("solstone-dismissed", [...gone].slice(-80));
    render();
  });

  function fire(it) {
    const scene = opts.scene?.();
    if (it.kind === "bedtime") { bigText(it.done_text || "Time for bed!"); return; }
    bigText(`${it.emoji ? `${it.emoji} ` : ""}${it.done_text || annPlain(it.text)}`);
    if (!scene) return;
    if (it.show) scene.boost(60, it.show);
    else if (it.style === "party") scene.celebrate(8);
  }
  function tick() {
    const t = now();
    let big = null;
    for (const it of items) {
      if (!it.countdown) continue;
      const left = it.countdown - t;
      if (left > 0) seenLive.add(it.id);
      if (it.kind === "note" && left > 0 && left <= 10 && (it.show || it.style === "party")) big = Math.ceil(left);
      if (left <= 0 && left > -30 && seenLive.has(it.id) && !fired.has(it.id)) { fired.add(it.id); fire(it); }
    }
    if (big != null) { clearTimeout(overlayT); overlay.hidden = false; overlay.classList.remove("msg"); overlay.textContent = String(big); }
    else if (!overlay.classList.contains("msg")) overlay.hidden = true;
    el.querySelectorAll("[data-cd]").forEach((s) => {
      const it = items.find((i) => String(i.countdown) === s.dataset.cd);
      const left = Number(s.dataset.cd) - t;
      s.textContent = left > 0 ? fmtCountdown(left) : (it?.done_text || "Now!");
      s.classList.toggle("soon", left > 0 && left < 300);
    });
    if (opts.ticker?.() && Date.now() - turnAt > 7000) { turn++; turnAt = Date.now(); render(); }
    tickT = setTimeout(tick, 1000 - (Date.now() % 1000) + 5);
  }
  async function poll() {
    clearTimeout(pollT);
    if (stopped) return;
    if (!document.hidden) {
      try {
        const sid = opts.sid?.() || "";
        const r = await fetch(`/api/public/board?where=${encodeURIComponent(opts.where || "home")}&sid=${encodeURIComponent(sid)}`, { credentials: "same-origin", cache: "no-store" });
        if (r.ok) {
          const d = await r.json();
          offset = d.now * 1000 - Date.now();
          items = d.items || [];
          render();
        } else if (r.status === 404 || r.status === 401) { items = []; render(); }
      } catch { /* try again soon */ }
    }
    pollT = setTimeout(poll, 30000);
  }
  poll(); tick();
  return {
    refresh: poll,
    render,
    get items() { return visible(); },
    remove() { stopped = true; clearTimeout(pollT); clearTimeout(tickT); overlay.remove(); el.innerHTML = ""; el.hidden = true; },
  };
}
