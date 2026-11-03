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
// The Events page as a timeline down the page: today at the top (with what's on now), then a dot for each day
// with something on, a dotted stretch and how long between them, and a gold stretch with the dates for a
// holiday's reward. row(it) draws each card; cls: the list's own class ("panel" in the app, "glass" outside).
function upTimeline(items, row, cls = "panel") {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const toDay = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const long = (d) => d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  const between = (a, b) => Math.round((b - a) / 86400000);
  const now = items.filter((x) => x.live || x.date === iso(today) || toDay(x.date) < today);
  const groups = [];
  for (const it of items.filter((x) => !now.includes(x))) {
    const g = groups[groups.length - 1];
    if (g && g.date === it.date) g.items.push(it); else groups.push({ date: it.date, items: [it] });
  }
  const rewards = (list) => list.filter((x) => x.reward).map((x) => `<div class="tl-reward"><span aria-hidden="true">🎁</span> Reward: ${esc(x.reward.when)}</div>`).join("");
  const list = (l) => `<ul class="up-list ${cls}">${l.map(row).join("")}</ul>`;
  let html = `<ol class="tl"><li class="tl-step tl-now${now.some((x) => x.reward) ? " tl-has-reward" : ""}"><span class="tl-node" aria-hidden="true"></span>
    <div class="tl-date"><b>Today</b><span>${esc(long(today))}</span></div>
    ${now.length ? `${rewards(now)}${list(now)}` : `<p class="muted small tl-quiet">Nothing on right now.</p>`}</li>`;
  let prev = today;
  for (const g of groups) {
    const d = toDay(g.date), gap = between(prev, d), until = between(today, d);
    if (gap > 1) html += `<li class="tl-gap" aria-hidden="true"><span>${gap % 7 ? `${gap} days` : gap === 7 ? "a week" : `${gap / 7} weeks`}</span></li>`;
    html += `<li class="tl-step${g.items.some((x) => x.reward) ? " tl-has-reward" : ""}"><span class="tl-node" aria-hidden="true"></span>
      <div class="tl-date"><b>${esc(long(d))}</b><span>${until === 1 ? "Tomorrow" : until < 7 ? `In ${until} days` : until < 14 ? "Next week" : `In ${Math.round(until / 7)} weeks`}</span></div>
      ${rewards(g.items)}${list(g.items)}</li>`;
    prev = d;
  }
  return `${html}</ol>`;
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
