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
    const html = list.map((it) => `<div class="bn bn-${esc(it.style)} bn-k-${esc(it.kind)}" data-id="${esc(it.id)}" role="status">
      ${it.emoji ? `<span class="bn-emoji" aria-hidden="true">${esc(it.emoji)}</span>` : ""}
      <div class="bn-text"><b>${it.link && it.link.startsWith("/app#/") ? `<a href="${esc(it.link)}">${esc(it.text)}</a>` : esc(it.text)}</b>${it.detail ? `<small>${esc(it.detail)}</small>` : ""}</div>
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
    bigText(`${it.emoji ? `${it.emoji} ` : ""}${it.done_text || it.text}`);
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
        const r = await fetch(`/api/public/board?where=${encodeURIComponent(opts.where || "status")}&sid=${encodeURIComponent(sid)}`, { credentials: "same-origin", cache: "no-store" });
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
