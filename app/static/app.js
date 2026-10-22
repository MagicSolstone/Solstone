/* Solstone frontend — vanilla JS, hash routing. */
"use strict";

// Replaced at image build time with "beta" (push to main) or "stable" (version tag).
const BUILD_CHANNEL = "__BUILD_CHANNEL__";

// ================================================================ utilities
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const nf = new Intl.NumberFormat();
const fmtNum = (n) => nf.format(Math.round(n || 0));

async function api(path, opts = {}) {
  const headers = { "X-Solstone": "1", ...(opts.headers || {}) };
  if (opts.body && typeof opts.body === "string" && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const r = await fetch(path, { ...opts, headers, credentials: "same-origin" });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { msg = (await r.json()).detail || msg; } catch {}
    if (r.status === 401 && !path.startsWith("/api/auth/")) showLogin();
    const err = new Error(msg); err.status = r.status; throw err;
  }
  return r.json();
}
const post = (path, body = {}, method = "POST") => api(path, { method, body: JSON.stringify(body) });

// ================================================================ accounts
const me = { user: null };
const appSky = { scene: null, bar: null, board: null };
let appBuild = null;  // the night sky behind the signed-in app
const isAdmin = () => me.user?.role === "admin";

function showLogin(message = "") {
  clearTimers?.();
  me.user = null;
  document.body.classList.add("logged-out");
  if (appSky.scene) { appSky.scene.stop(); appSky.bar?.remove(); FWMusic.stop(); appSky.scene = appSky.bar = null; }
  appSky.board?.remove(); appSky.board = null;
  const root = $("#login-root");
  root.hidden = false;
  root.innerHTML = `<canvas id="login-sky" aria-hidden="true"></canvas>
    <div class="login-wrap"><div id="login-board" class="board-stack" hidden></div><form class="login-card" id="login-form" autocomplete="on">
      <img src="/static/solstone.svg" alt="" width="56" height="56">
      <div class="login-title"><h1>Solstone</h1><p class="tagline">Server explorer for Minecraft</p></div>
      <label>Username<input class="input" name="username" autocomplete="username" autocapitalize="off" required></label>
      <label>Password<input class="input" type="password" name="password" autocomplete="current-password" required></label>
      <p class="login-error" role="alert">${esc(message)}</p>
      <button class="btn primary" type="submit">Sign in</button>
    </form><a class="login-status glass" id="login-status-link" href="/status" hidden></a></div>`;
  const form = $("#login-form");
  form.querySelector("input").focus();
  loadPublicStatus().then(() => startLoginScene());
  state.loginRefresh && clearInterval(state.loginRefresh);
  state.loginRefresh = setInterval(() => { if (!me.user) loadPublicStatus(); }, 30000);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(form), btn = form.querySelector("button");
    btn.disabled = true;
    try {
      const r = await post("/api/auth/login", { username: f.get("username"), password: f.get("password") });
      signedIn(r.user);
    } catch (err) {
      $(".login-error", form).textContent = err.status === 401 ? "Wrong username or password." : err.message;
      btn.disabled = false;
      form.querySelector('[name="password"]').select();
    }
  });
}

async function signedIn(user) {
  me.user = user;
  document.body.classList.remove("logged-out");
  document.body.classList.toggle("is-admin", user.role === "admin");
  stopLoginScene();
  clearInterval(state.loginRefresh);
  if (!appSky.scene && $("#app-sky")) {
    // A bright in-game day is dimmed behind the panels (but not when the page is hidden to watch).
    appSky.scene = startSkyScene($("#app-sky"), { auto: false, sound: (t, i) => FWAudio.play(t, i),
      dim: () => (document.body.classList.contains("ui-hidden") ? 0 : 0.5) });
    appSky.bar = startShowBar(appSky.scene, { key: "solstone-sky-app", defaultOn: false, hide: true, skyServer: () => curSid || "",
      onEvent: (item) => { if (item.text) showToast(`🎆 ${esc(item.text)}${item.server && item.server !== "Test" ? ` <span class="muted">· ${esc(item.server)}</span>` : ""}`, 4000); } });
  }
  const root = $("#login-root"); root.hidden = true; root.innerHTML = "";
  if (!appSky.board) appSky.board = startBoard($("#app-board"), { where: "app", sid: () => curSid || "", scene: () => appSky.scene, dismiss: true, max: innerWidth < 700 ? 1 : 2 });
  $("#account-name").textContent = user.username;
  $("#account-role").textContent = user.role === "admin" ? "Admin" : "Viewer (read-only)";
  fetch("/api/public/status").then((r) => r.json()).then((d) => { $("#btn-status").hidden = !d.enabled; appBuild = d.build; }).catch(() => {});
  // Left open for a while? Say when Solstone has been updated (a reload loads it).
  clearInterval(state.buildCheck);
  state.buildCheck = setInterval(async () => {
    try { const d = await (await fetch("/api/public/status")).json(); if (appBuild && d.build && d.build !== appBuild) { showToast('Solstone has been updated. <a href="" data-reload>Reload to get the new version</a>', 0); clearInterval(state.buildCheck); } } catch { /* offline for a moment */ }
  }, 5 * 60 * 1000);
  await loadServers();
  route();
}

function wireAccountMenu() {
  const btn = $("#btn-account"), menu = $("#account-menu");
  // The sidebar scrolls, which clips anything that pops out of it, so the menu lives on
  // <body> and is positioned next to the button whenever it opens.
  document.body.append(menu);
  const place = () => {
    const r = btn.getBoundingClientRect(), mh = menu.offsetHeight, mw = menu.offsetWidth;
    const below = innerHeight - r.bottom, above = r.top;
    menu.style.left = `${Math.max(8, Math.min(r.left, innerWidth - mw - 8))}px`;
    menu.style.top = below >= mh + 12 || below >= above ? `${r.bottom + 6}px` : `${Math.max(8, r.top - mh - 6)}px`;
  };
  const close = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  const open = () => { menu.hidden = false; place(); btn.setAttribute("aria-expanded", "true"); menu.querySelector("button")?.focus(); };
  btn.addEventListener("click", (e) => { e.stopPropagation(); menu.hidden ? open() : close(); });
  document.addEventListener("click", (e) => { if (!menu.contains(e.target)) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { close(); btn.focus(); } });
  addEventListener("resize", close);
  addEventListener("scroll", close, { passive: true });
  $("#btn-logout").addEventListener("click", async () => { close(); await post("/api/auth/logout").catch(() => {}); showLogin(); });
  $("#btn-password").addEventListener("click", () => { close(); openPasswordChange(); });
}

function openPasswordChange() {
  openModal(`<h2>Change password</h2><form id="pw-form">
      <label>Current password<input class="input" type="password" name="current" autocomplete="current-password" required></label>
      <label>New password <small>At least 8 characters</small><input class="input" type="password" name="new" minlength="8" autocomplete="new-password" required></label>
      <div class="actions"><button type="button" class="btn" data-close-modal>Cancel</button><button class="btn primary" type="submit">Change password</button></div>
    </form>`, (m) => {
    $("#pw-form", m).addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      try { await post("/api/auth/password", { current: f.get("current"), new: f.get("new") }); closeModal(); showToast("Password changed", 2500); }
      catch (err) { showToast(esc(err.message), 4000); }
    });
  });
}

function fmtDuration(ticks) {
  const s = Math.floor((ticks || 0) / 20);
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}
function fmtDistance(cm) {
  const m = (cm || 0) / 100;
  if (m >= 1000) return `${(m / 1000).toFixed(m >= 100000 ? 0 : 1)} km`;
  return `${Math.round(m)} m`;
}
function fmtAgo(ts) {
  if (!ts) return "never";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  if (d < 30) return d === 1 ? "yesterday" : `${d} days ago`;
  return new Date(ts * 1000).toLocaleDateString();
}
const ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];
const roman = (n) => ROMAN[n] || String(n);
const humanize = (s) => String(s).replace(/^.*[:/]/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const splitId = (id) => { const [a, b] = String(id).includes(":") ? String(id).split(":") : ["minecraft", id]; return [a, b]; };
function fmtSeconds(sec) { return fmtDuration((sec || 0) * 20); }
function hashColor(str) {
  let h = 0; for (const c of str) h = (h * 31 + c.charCodeAt(0)) | 0;
  return `hsl(${Math.abs(h) % 360} 32% 42%)`;
}

// ================================================================ state
const state = {
  servers: [],
  lang: {},          // sid -> lang map
  assets: {},        // sid -> asset status
  advDefs: {},       // sid -> advancement defs
  timers: [],
  cleanups: [],      // run when leaving a page (e.g. stop the editor's preview sky)
  items: new Map(),  // item registry for tooltips
  itemSeq: 0,
};
function clearTimers() {
  if (typeof closeFwPreview === "function") closeFwPreview();
  state.timers.forEach(clearInterval); state.timers = []; state.onVisible?.clear();
  state.cleanups.splice(0).forEach((f) => { try { f(); } catch { /* best effort */ } });
}
// Page refreshes pause while the tab is in the background and catch up once when it's back.
function every(ms, fn) {
  const run = () => { if (!document.hidden) fn(); };
  const t = setInterval(run, ms);
  state.timers.push(t);
  (state.onVisible ||= new Map()).set(t, fn);
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden || !state.onVisible) return;
  for (const [t, fn] of state.onVisible) if (state.timers.includes(t)) { try { fn(); } catch { /* next tick */ } } else state.onVisible.delete(t);
});

// ================================================================ language
let curSid = null;
const L = () => state.lang[curSid] || {};
function tr(key, fallback) { return L()[key] ?? fallback ?? humanize(key); }
function itemName(item) {
  const id = typeof item === "string" ? item : item.id;
  const [ns, n] = splitId(id);
  const lang = L();
  if (typeof item === "object" && item.potion && /potion|tipped_arrow/.test(n)) {
    const p = splitId(item.potion)[1];
    const k = `item.${ns}.${n}.effect.${p}`;
    if (lang[k]) return lang[k];
  }
  return lang[`item.${ns}.${n}`] || lang[`block.${ns}.${n}`] || humanize(n);
}
const entityName = (id) => { const [ns, n] = splitId(id); return L()[`entity.${ns}.${n}`] || humanize(n); };
const enchName = (id) => { const [ns, n] = splitId(id); return L()[`enchantment.${ns}.${n}`] || humanize(n); };
const effectName = (id) => { const [ns, n] = splitId(id); return L()[`effect.${ns}.${n}`] || humanize(n); };
function statName(id) {
  const [ns, n] = splitId(id);
  return L()[`stat.${ns}.${n}`] || humanize(n);
}
function dimName(id) {
  const n = splitId(id || "minecraft:overworld")[1];
  return { overworld: "Overworld", the_nether: "The Nether", the_end: "The End" }[n] || humanize(n);
}
function dimClass(id) {
  const n = splitId(id || "minecraft:overworld")[1];
  return ["overworld", "the_nether", "the_end"].includes(n) ? `dim-${n}` : "dim-other";
}

// ================================================================ assets
function iconUrl(id) {
  const [ns, n] = splitId(id);
  const a = state.assets[curSid] || {};
  return `/api/servers/${encodeURIComponent(curSid)}/assets/item/${encodeURIComponent(ns)}/${encodeURIComponent(n)}.png?v=${encodeURIComponent(a.version || "")}&s=${a.state || ""}`;
}
function textureUrl(path) {
  const a = state.assets[curSid] || {};
  return `/api/servers/${encodeURIComponent(curSid)}/assets/texture/${path}.png?v=${encodeURIComponent(a.version || "")}`;
}
function placeholderHtml(id) {
  const n = splitId(id)[1];
  const letters = n.split("_").filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
  return `<span class="placeholder" style="--ph:${hashColor(n)}">${esc(letters)}</span>`;
}
window.lsIconFail = (img) => {
  const wrap = img.parentElement;
  if (!wrap) return;
  wrap.classList.remove("glint");
  img.outerHTML = placeholderHtml(img.dataset.id || "");
};
function itemIcon(item, extra = "") {
  const id = item.id;
  const glint = item.enchantments?.length || item.stored_enchantments?.length || item.glint;
  const url = iconUrl(id);
  return `<span class="item ${glint ? "glint" : ""} ${extra}" style="--mask:url('${url}')"><img class="item-img" src="${url}" alt="" loading="lazy" data-id="${esc(id)}" data-fail="icon"></span>`;
}

async function ensureServerAssets(sid) {
  try {
    const st = await api(`/api/servers/${sid}/assets/status`);
    const prev = state.assets[sid]?.state;
    state.assets[sid] = st;
    if (st.state === "ready" && (!state.lang[sid] || Object.keys(state.lang[sid]).length < 50 || prev !== "ready")) {
      state.lang[sid] = await api(`/api/servers/${sid}/assets/lang`);
      state.advDefs[sid] = await api(`/api/servers/${sid}/assets/advancements`);
      if (prev && prev !== "ready") { hideToast(); route(); }
    } else if (st.state === "downloading") {
      showToast(`Downloading Minecraft ${esc(st.version)} assets for item icons… ${Math.round(st.progress * 100)}%`);
      setTimeout(() => sid === curSid && ensureServerAssets(sid), 2500);
      if (!state.lang[sid]) state.lang[sid] = await api(`/api/servers/${sid}/assets/lang`).catch(() => ({}));
    } else if (!state.lang[sid]) {
      state.lang[sid] = await api(`/api/servers/${sid}/assets/lang`).catch(() => ({}));
    }
  } catch { /* assets are optional */ }
}

// ================================================================ heads
function headHtml(p, size = 56) { return faceHtml(p, size); }
const miniHead = (p, size = 28) => faceHtml(p, size);

// ================================================================ slots + tooltip
function slotHtml(item, opts = {}) {
  const cls = ["slot"];
  if (opts.selected) cls.push("selected");
  if (!item) {
    const ghost = opts.ghost ? `<img class="ghost" src="${textureUrl(`gui/sprites/container/slot/${opts.ghost}`)}" alt="" data-fail="remove">` : "";
    return `<div class="${cls.join(" ")}">${ghost}</div>`;
  }
  cls.push("filled");
  const key = `i${++state.itemSeq}`;
  state.items.set(key, item);
  let extras = "";
  if (item.count > 1) extras += `<span class="count">${item.count}</span>`;
  if (item.max_damage && item.damage > 0) {
    const left = Math.max(0, 1 - item.damage / item.max_damage);
    extras += `<span class="dura"><span style="width:${left * 100}%;background:hsl(${Math.round(left * 120)} 100% 50%)"></span></span>`;
  }
  if (item.contents?.length) extras += `<span class="container-mark" title="Has items inside"></span>`;
  const label = `${itemName(item)}${item.count > 1 ? ` ×${item.count}` : ""}`;
  return `<div class="${cls.join(" ")}" data-item="${key}" tabindex="0" aria-label="${esc(label)}">${itemIcon(item)}${extras}</div>`;
}

function gridHtml(items, size, indexed = true) {
  const arr = new Array(size).fill(null);
  if (indexed) items.forEach((it) => { if (it && it.slot != null && it.slot < size) arr[it.slot] = it; });
  else items.forEach((it, i) => { if (i < size) arr[i] = it; });
  return arr.map((it) => slotHtml(it)).join("");
}

function tooltipHtml(item) {
  const ench = item.enchantments?.length > 0;
  let h = `<div class="t-name ${ench || item.stored_enchantments?.length ? "ench" : ""} ${item.name ? "custom" : ""}">${esc(item.name || itemName(item))}</div>`;
  for (const e of [...(item.enchantments || []), ...(item.stored_enchantments || [])])
    h += `<div class="t-ench">${esc(enchName(e.id))}${e.level > 1 || !["minecraft:mending", "minecraft:silk_touch", "minecraft:infinity", "minecraft:flame", "minecraft:channeling", "minecraft:aqua_affinity", "minecraft:multishot"].includes(e.id) ? " " + roman(e.level) : ""}</div>`;
  if (item.potion) h += `<div class="t-blue">${esc(humanize(item.potion))}</div>`;
  if (item.trim) h += `<div class="t-ench">Trim: ${esc(humanize(item.trim.pattern))} (${esc(humanize(item.trim.material))})</div>`;
  if (item.color != null && item.id.includes("leather")) h += `<div class="t-ench">Dyed #${item.color.toString(16).padStart(6, "0")}</div>`;
  for (const line of item.lore || []) h += `<div class="t-lore">${esc(line)}</div>`;
  if (item.attributes?.length) h += `<div class="t-attrs">${item.attributes.map(attrLine).join("")}</div>`;
  if (item.contents) {
    if (item.contents.length) {
      const isBundle = item.id.includes("bundle");
      h += `<div class="mini-grid">${isBundle ? gridHtml(item.contents, Math.max(9, Math.ceil(item.contents.length / 9) * 9), false) : gridHtml(item.contents, 27)}</div>`;
      h += `<div class="t-hint">Click to open</div>`;
    } else h += `<div class="t-ench">Empty</div>`;
  }
  if (item.unbreakable) h += `<div class="t-blue">Unbreakable</div>`;
  if (item.max_damage) h += `<div class="t-ench">Durability: ${item.max_damage - (item.damage || 0)} / ${item.max_damage}</div>`;
  if (item.count > 1) h += `<div class="t-ench">Count: ${item.count}</div>`;
  if (item.mod_data?.length) h += `<div class="t-dim">Mod data: ${esc(item.mod_data.map(humanize).join(", "))}</div>`;
  h += `<div class="t-dim">${esc(item.id)}</div>`;
  return h;
}

// Attribute modifiers, as shown on gear from RPG mods ("+4 Attack Damage", "+10% Speed").
function attrName(id) {
  const [ns, n] = splitId(id), l = L();
  return l[`attribute.name.${n}`] || l[`attribute.name.generic.${n}`] || l[`attribute.name.player.${n}`]
    || l[`attribute.name.${ns}.${n}`] || l[`attribute.${ns}.${n}`] || l[`attribute.name.${ns}.${n.replace(/\//g, ".")}`] || humanize(n);
}
function attrLine(a) {
  const pct = a.operation !== "add_value" && a.operation !== "0" && a.operation !== 0;
  const v = pct ? `${+(a.amount * 100).toFixed(1)}%` : `${+a.amount.toFixed(2)}`;
  return `<div class="${a.amount < 0 ? "t-neg" : "t-blue"}">${a.amount >= 0 ? "+" : ""}${esc(v)} ${esc(attrName(a.type))}</div>`;
}

const tip = () => $("#tooltip");
function showTip(el, x, y) {
  const item = state.items.get(el.dataset.item);
  if (!item) return;
  const t = tip();
  t.innerHTML = tooltipHtml(item);
  t.hidden = false;
  placeTip(x, y);
}
function placeTip(x, y) {
  const t = tip();
  const pad = 14, r = t.getBoundingClientRect();
  let left = x + pad, top = y - 10;
  if (left + r.width > innerWidth - 8) left = x - r.width - pad;
  if (top + r.height > innerHeight - 8) top = innerHeight - r.height - 8;
  t.style.left = `${Math.max(8, left)}px`;
  t.style.top = `${Math.max(8, top)}px`;
}
function hideTip() { tip().hidden = true; }
document.addEventListener("mouseover", (e) => {
  const el = e.target.closest?.("[data-item]");
  if (el && !el.closest(".mc-tooltip")) showTip(el, e.clientX, e.clientY);
  else if (!e.target.closest?.(".mc-tooltip")) hideTip();
});
document.addEventListener("mousemove", (e) => { if (!tip().hidden) placeTip(e.clientX, e.clientY); });
document.addEventListener("focusin", (e) => {
  const el = e.target.closest?.("[data-item]");
  if (el) { const r = el.getBoundingClientRect(); showTip(el, r.right, r.top); } else hideTip();
});
document.addEventListener("click", (e) => {
  const el = e.target.closest?.("[data-item]");
  if (!el) return;
  const item = state.items.get(el.dataset.item);
  if (item?.contents?.length) { hideTip(); openContainer(item); }
  else if (matchMedia("(hover: none)").matches) showTip(el, e.clientX, e.clientY);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { hideTip(); closeModal(); }
  if (e.key === "Enter") {
    const el = document.activeElement?.closest?.("[data-item]");
    if (el) el.click();
  }
});
addEventListener("scroll", hideTip, { passive: true });

// ================================================================ modal + toast
function openModal(html, onMount) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-backdrop"><div class="modal" role="dialog" aria-modal="true">${html}</div></div>`;
  root.querySelector(".modal-backdrop").addEventListener("mousedown", (e) => { if (e.target.classList.contains("modal-backdrop")) closeModal(); });
  onMount?.(root.querySelector(".modal"));
  root.querySelector("input, button, [tabindex]")?.focus();
}
// ---------------------------------------------------------------- map check (admin)
// Re-reads the region files where players are and reports what happened, so a blank map
// can be explained (and the text pasted into a bug report).
function openMapCheck(sid, dims) {
  const ids = [...new Set(["minecraft:overworld", ...dims])];
  openModal(`<h2>Map drawing check</h2>
    <p class="muted small">Reads the region files where players last were and tries to draw them. Nothing is changed.</p>
    <div class="btn-row"><select class="input sm" id="mc-dim">${ids.map((d) => `<option value="${esc(d)}">${esc(dimName(d))}</option>`).join("")}</select>
      <button class="btn sm primary" type="button" id="mc-run">Check</button><button class="btn sm" type="button" id="mc-copy" hidden>Copy</button></div>
    <div id="mc-sum" class="mc-sum"></div><pre class="mc-out" id="mc-out" hidden></pre>
    <div class="actions"><button type="button" class="btn" data-close-modal>Close</button></div>`, (m) => {
    m.classList.add("mc-modal");
    const run = async () => {
      $("#mc-sum", m).textContent = "Reading the world…"; $("#mc-out", m).hidden = true;
      try {
        const r = await api(`/api/servers/${encodeURIComponent(sid)}/map/check?dim=${encodeURIComponent($("#mc-dim", m).value)}`);
        const rows = r.checked || [];
        const ok = rows.filter((x) => x.drawn > 0).length;
        $("#mc-sum", m).innerHTML = r.error ? `<b>${esc(r.error)}</b>`
          : `<div>${r.regions} region files. Checked ${rows.length}: <b>${ok} drew fine</b>${rows.length - ok ? `, <b class="warn">${rows.length - ok} came out empty</b>` : ""}.</div>`
            + rows.map((x) => `<div class="small">${esc(x.file)}: ${x.drawn} of ${x.chunks} chunks drawn${x.failed ? `, ${x.failed} unreadable` : ""}${x.error ? ` — ${esc(x.error)}` : ""}${x.layout?.checked ? ` · matches the game's height map ${Math.round(x.layout.agree * 100)}%` : ""}${x.layout?.narrow_sections ? ` · ${x.layout.narrow_sections} narrow-packed sections` : ""}${x.layout?.layouts && Object.keys(x.layout.layouts).some((k) => k !== "yzx") ? ` · block layout: ${Object.entries(x.layout.layouts).map(([k, n]) => `${k} ×${n}`).join(", ")}` : ""}${x.layout?.moved ? ` · ${x.layout.moved} chunks moved` : ""}</div>`).join("");
        $("#mc-out", m).textContent = JSON.stringify(r, null, 1); $("#mc-out", m).hidden = false; $("#mc-copy", m).hidden = false;
      } catch (e) { $("#mc-sum", m).textContent = e.message; }
    };
    $("#mc-run", m).addEventListener("click", run);
    $("#mc-copy", m).addEventListener("click", async () => { try { await navigator.clipboard.writeText($("#mc-out", m).textContent); showToast("Copied", 1500); } catch { showToast("Select the text and copy it", 2500); } });
    run();
  });
}

// ---------------------------------------------------------------- give items
// One dialog used by the player page and the control screen: search with icons, pick an
// amount, give. It stays open so you can hand out a few things in a row.
async function itemCatalog(sid) {
  state.itemCatalog ||= {};
  if (state.itemCatalog[sid]?.length) return state.itemCatalog[sid];
  let list = await api(`/api/servers/${encodeURIComponent(sid)}/assets/items`).catch(() => []);
  if (!list.length) {                      // game files not downloaded yet: use the names we have
    const lang = state.lang[sid] || {};
    list = Object.keys(lang).filter((k) => /^(item|block)\.minecraft\.[a-z0-9_]+$/.test(k))
      .map((k) => ({ id: `minecraft:${k.split(".")[2]}`, name: lang[k] })).sort((a, b) => a.name.localeCompare(b.name));
  }
  state.itemCatalog[sid] = list;
  return list;
}
const GIVE_RECENT = "solstone-give-recent";
function giveRecent() { try { return JSON.parse(localStorage.getItem(GIVE_RECENT) || "[]").slice(0, 10); } catch { return []; } }
function giveRemember(id) { try { localStorage.setItem(GIVE_RECENT, JSON.stringify([id, ...giveRecent().filter((x) => x !== id)].slice(0, 10))); } catch { /* private window */ } }

// opts.pick(item, count): choose an item for something else (a challenge prize) instead of giving it.
async function openGiveItem(sid, player, opts = {}) {
  const list = await itemCatalog(sid);
  const byId = new Map(list.map((x) => [x.id, x]));
  let pick = null;
  openModal(`<h2>${opts.pick ? esc(opts.title || "Choose an item") : `Give items to ${esc(player)}`}</h2>
    <input class="input" id="gv-q" type="search" placeholder="Search items, like diamond or torch" autocomplete="off" aria-label="Search items">
    <div class="gv-label muted small" id="gv-label"></div>
    <div class="gv-grid" id="gv-grid" role="listbox" aria-label="Items"></div>
    <div class="gv-pick" id="gv-pick" hidden></div>
    <div class="gv-amount"><label>How many <input class="input sm num-in" id="gv-n" type="number" min="1" max="6400" value="${Number(opts.count) || 1}"></label>
      <span class="gv-chips">${[1, 8, 16, 32, 64].map((n) => `<button type="button" class="chip" data-n="${n}">${n}</button>`).join("")}</span></div>
    <div class="actions"><button type="button" class="btn" data-close>${opts.pick ? "Cancel" : "Done"}</button><button type="button" class="btn primary" id="gv-go" disabled>${opts.pick ? "Use this" : "Give"}</button></div>`, (m) => {
    m.classList.add("gv-modal");
    const q = $("#gv-q", m), grid = $("#gv-grid", m), label = $("#gv-label", m), go = $("#gv-go", m), num = $("#gv-n", m);
    const cell = (x) => `<button type="button" class="gv-item ${pick?.id === x.id ? "on" : ""}" data-id="${esc(x.id)}" role="option" aria-selected="${pick?.id === x.id}" title="${esc(x.name)}">${itemIcon({ id: x.id })}<span>${esc(x.name)}</span></button>`;
    const draw = () => {
      const t = q.value.trim().toLowerCase();
      let rows, head;
      if (!t) {
        const recent = giveRecent().map((id) => byId.get(id) || { id, name: itemName({ id }) });
        rows = recent.length ? recent : list.slice(0, 48); head = recent.length ? "Given recently" : `${list.length} items`;
      } else {
        const words = t.split(/\s+/);
        const hits = list.filter((x) => { const h = `${x.name} ${x.id}`.toLowerCase(); return words.every((w) => h.includes(w)); });
        hits.sort((a, b) => (b.name.toLowerCase().startsWith(t) - a.name.toLowerCase().startsWith(t)) || a.name.length - b.name.length);
        rows = hits.slice(0, 60);
        head = hits.length > 60 ? `First 60 of ${hits.length}. Keep typing to narrow it down.` : `${hits.length} found`;
        if (!hits.length && /^[a-z0-9_.-]+(:[a-z0-9_./-]+)?$/.test(t)) {           // a mod item we don't know about
          const id = t.includes(":") ? t : `minecraft:${t}`;
          rows = [{ id, name: id }]; head = "Not in the list. Give it by its id?";
        }
      }
      label.textContent = head;
      grid.innerHTML = rows.map(cell).join("") || `<p class="muted small">Nothing matches.</p>`;
    };
    const choose = (x) => {
      pick = x; go.disabled = !pick;
      const pk = $("#gv-pick", m); pk.hidden = false;
      pk.innerHTML = `${itemIcon({ id: x.id })}<div><b>${esc(x.name)}</b><div class="muted small">${esc(x.id)}</div></div>`;
      grid.querySelectorAll(".gv-item").forEach((b) => { const on = b.dataset.id === x.id; b.classList.toggle("on", on); b.setAttribute("aria-selected", on); });
      go.textContent = opts.pick ? "Use this" : `Give ${Math.max(1, +num.value || 1)}`;
    };
    grid.addEventListener("click", (e) => { const b = e.target.closest(".gv-item"); if (b) choose(byId.get(b.dataset.id) || { id: b.dataset.id, name: b.dataset.id }); });
    grid.addEventListener("dblclick", (e) => { if (e.target.closest(".gv-item")) go.click(); });
    q.addEventListener("input", draw);
    q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); const first = grid.querySelector(".gv-item"); if (first && !pick) first.click(); else if (pick) go.click(); } });
    const chips = () => m.querySelectorAll("[data-n]").forEach((c) => c.classList.toggle("on", c.dataset.n === String(+num.value)));
    const goLabel = () => { if (pick) go.textContent = opts.pick ? "Use this" : `Give ${Math.max(1, +num.value || 1)}`; };
    m.querySelectorAll("[data-n]").forEach((b) => b.addEventListener("click", () => { num.value = b.dataset.n; chips(); goLabel(); }));
    num.addEventListener("input", () => { chips(); goLabel(); });
    chips();
    $("[data-close]", m).addEventListener("click", closeModal);
    go.addEventListener("click", async () => {
      if (!pick) return;
      const n = Math.max(1, Math.min(6400, Math.round(+num.value || 1)));
      if (opts.pick) { giveRemember(pick.id); closeModal(); opts.pick(pick, n); return; }
      go.disabled = true;
      try {
        const r = await post(`/api/servers/${encodeURIComponent(sid)}/control/player/${encodeURIComponent(player)}/give`, { item: pick.id, count: n });
        const bad = (r.results || []).find((x) => x.ok === false);
        if (bad) showToast(esc((bad.output || "The game said no").slice(0, 160)), 6000);
        else { showToast(`Gave ${n} × ${esc(pick.name)} to ${esc(player)}`, 2500); giveRemember(pick.id); }
      } catch (err) { showToast(esc(err.message), 6000); }
      go.disabled = false;
    });
    draw();
    setTimeout(() => q.focus(), 0);
  });
}

function closeModal() { $("#modal-root").innerHTML = ""; }
function openContainer(item) {
  const isBundle = item.id.includes("bundle");
  const grid = isBundle ? gridHtml(item.contents, Math.max(9, Math.ceil(item.contents.length / 9) * 9), false) : gridHtml(item.contents, 27);
  openModal(`<h2>${esc(item.name || itemName(item))}</h2><div class="mc-panel"><div class="mc-grid">${grid}</div></div>
    <div class="actions"><button class="btn" data-close-modal>Close</button></div>`);
}
let toastTimer;
function showToast(msg, ms = 0) {
  const t = $("#toast"); t.innerHTML = msg; t.hidden = false;
  clearTimeout(toastTimer); if (ms) toastTimer = setTimeout(hideToast, ms);
}
function hideToast() { $("#toast").hidden = true; }

// ================================================================ rail
function railHtml(activeSid) {
  return state.servers.map((s) => {
    const dot = s.crashed ? "crash" : s.running || (s.running == null && s.folder_found) ? "on" : "";
    const sub = s.running === false ? "Offline" : s.online ? `${s.online.length} playing` : "";
    return `<a class="rail-item" href="#/s/${encodeURIComponent(s.id)}" ${s.id === activeSid ? 'aria-current="page"' : ""}>
      ${serverIconHtml(s)}<div><div class="name">${esc(s.name)}</div><div class="sub">${esc(sub)}</div></div></a>`;
  }).join("");
}
function serverIconHtml(s, withDot = true) {
  const dot = withDot ? `<span class="status-dot ${s.crashed ? "crash" : s.running ? "on" : ""}"></span>` : "";
  const inner = s.has_icon ? `<img src="/api/servers/${encodeURIComponent(s.id)}/icon.png" alt="">` : esc((s.name || "?")[0]);
  return `<span class="server-icon">${inner}${dot}</span>`;
}
async function loadServers() {
  const uuids = api("/api/players/uuids").then((m) => Object.assign(knownUuids, m)).catch(() => null);
  try { state.servers = await api("/api/servers"); } catch (e) { state.servers = state.servers || []; }
  await uuids;
  $("#rail-servers").innerHTML = railHtml(curSid);
}

// ================================================================ views
const view = () => $("#view");
function setView(html) { state.items.clear(); hideTip(); view().innerHTML = html; }

async function viewHome() {
  curSid = null;
  document.title = "Solstone";
  await loadServers();
  if (state.servers.length === 1) { location.replace(`#/s/${encodeURIComponent(state.servers[0].id)}`); return; }
  if (!state.servers.length) {
    const st = await api("/api/status").catch(() => ({}));
    setView(`<h1 style="margin-bottom:18px">No servers yet</h1>${setupHelp(st)}`);
    return;
  }
  setView(`<h1 style="margin-bottom:20px">Servers</h1><div class="home-grid">${state.servers.map((s) => `
    <a class="server-card" href="#/s/${encodeURIComponent(s.id)}">${serverIconHtml(s)}
      <div><h2>${esc(s.name)}</h2>
        <div class="muted" style="font-size:.9rem">${s.running === false ? "Offline" : `${s.online?.length || 0} of ${s.max_players ?? "?"} playing`} · ${esc(s.version || "unknown version")} ${esc(s.loader || "")}</div>
        <div class="who">${(s.online || []).map((n) => `<span title="${esc(n)}">${faceHtml({ name: n }, 24)}</span>`).join("")}</div>
      </div></a>`).join("")}</div>`);
  every(15000, async () => { await loadServers(); });
}

function setupHelp(st) {
  const lines = [];
  if (!st.crafty?.configured) lines.push(`Set <code>CRAFTY_URL</code> and <code>CRAFTY_TOKEN</code> so Solstone can list your Crafty servers.`);
  else if (st.crafty?.error) lines.push(`Crafty answered with an error: <code>${esc(st.crafty.error)}</code>. Check the URL and API token.`);
  if (!st.servers_dir_found) lines.push(`Mount Crafty's <code>servers</code> folder at <code>${esc(st.servers_dir)}</code> (read-only is fine).`);
  return `<div class="empty"><h3>Connect Solstone to Crafty</h3>${lines.map((l) => `<p style="margin-top:6px">${l}</p>`).join("") || "<p>Start a server in Crafty and it will appear here.</p>"}</div>`;
}

function serverHeader(s, tab) {
  const statePill = s.running === false
    ? `<span class="state-pill"><span class="status-dot ${s.crashed ? "crash" : ""}"></span>${s.crashed ? "Crashed" : "Offline"}</span>`
    : `<span class="state-pill"><span class="status-dot on"></span>${s.online?.length || 0} / ${s.max_players ?? "?"} playing</span>`;
  const facts = [
    s.version && `<span>${s.game && s.game !== "minecraft-java" ? "Version" : "Minecraft"} <b>${esc(s.version)}</b></span>`,
    s.game && s.game !== "minecraft-java" && `<span><b>${esc(s.game_label)}</b></span>`,
    s.loader && `<span><b>${esc(s.loader)}</b></span>`,
    s.started && s.running && `<span>Up since <b>${esc(new Date(s.started.replace(" ", "T")).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }))}</b></span>`,
    s.cpu != null && s.running && `<span>CPU <b>${esc(Number(s.cpu).toFixed(1))}%</b></span>`,
    s.mem && s.running && `<span>RAM <b>${esc(s.mem)}</b></span>`,
    s.world_size && `<span>World <b>${esc(s.world_size)}</b></span>`,
    s.perf && s.running && `<span>TPS <b>${esc(s.perf.tps.toFixed(1))}</b></span>`,
    s.backup?.found && `<span class="${s.backup.stale ? "warn-fact" : ""}" title="${esc(s.backup.latest.name)}">Backup <b>${esc(fmtAgo(s.backup.latest.ts))}</b></span>`,
    s.port && `<span>Port <b>${esc(s.port)}</b></span>`,
  ].filter(Boolean).join("");
  const base = `#/s/${encodeURIComponent(s.id)}`;
  const java = !s.game || s.game === "minecraft-java";
  const tabs = [["overview", "Overview", base], ["performance", "Performance", `${base}/performance`],
    ...(java ? [["world", "World", `${base}/world`], ["leaderboards", "Leaderboards", `${base}/leaderboards`], ["mods", "Mods", `${base}/mods`]] : []),
    ...(isAdmin() && java ? [["chat", "Chat", `${base}/chat`], ["challenges", "Challenges", `${base}/challenges`]] : []),
    ...(isAdmin() ? [["control", "Control", `${base}/control`]] : []),
    ...(isAdmin() && java ? [["check", "Check", `${base}/check`]] : [])];
  return `<header class="server-head">
      <div class="big-icon">${s.has_icon ? `<img src="/api/servers/${encodeURIComponent(s.id)}/icon.png" alt="">` : esc((s.name || "?")[0])}</div>
      <div><h1>${esc(s.name)}</h1><div class="motd">${motdHtml(s.motd)}</div><div class="facts">${facts}</div></div>
      <div class="head-actions">${statePill}${isAdmin() ? '<button class="icon-btn" id="btn-settings" title="Server settings" aria-label="Server settings">⚙</button>' : ""}</div>
    </header>
    ${!java ? `<div class="notice">${esc(s.game_label)} server: Solstone shows its status, who's online, play time and performance. Inventories, stats and world details are Minecraft Java only for now.</div>` : ""}
    ${java && !s.folder_found ? `<div class="notice">Solstone can't find this server's files at <code>${esc(s.folder)}</code>. Mount Crafty's servers folder so player data can be read.</div>` : ""}
    ${s.rcon?.error && s.running ? `<div class="notice">Live data is unavailable: ${esc(s.rcon.error)}. Showing the last saved data instead.</div>` : ""}
    ${s.backup?.found && s.backup.stale ? `<div class="notice">The last backup was ${esc(fmtAgo(s.backup.latest.ts))}. Check the backup schedule in Crafty.</div>` : ""}
    ${s.backup?.configured && !s.backup.found ? `<div class="notice">No backups found for this server in Crafty's backups folder.</div>` : ""}
    <nav class="tabs" aria-label="Server sections">${tabs.map(([k, label, href]) => `<a href="${href}" ${k === tab ? 'aria-current="page"' : ""}>${label}</a>`).join("")}</nav>`;
}

async function serverFrame(sid, tab) {
  curSid = sid;
  if (!state.servers.find((s) => s.id === sid)) await loadServers();
  else $("#rail-servers").innerHTML = railHtml(sid);
  const s = await api(`/api/servers/${encodeURIComponent(sid)}`);
  const idx = state.servers.findIndex((x) => x.id === sid);
  if (idx >= 0) state.servers[idx] = s;
  document.title = `${s.name} · Solstone`;
  if (!s.game || s.game === "minecraft-java") ensureServerAssets(sid);
  if (!state.lang[sid]) await api(`/api/servers/${sid}/assets/lang`).then((l) => (state.lang[sid] = l)).catch(() => {});
  return s;
}
function wireHeader(s) {
  $("#btn-settings")?.addEventListener("click", () => openSettings(s));
}

// ---------------------------------------------------------------- overview tab
// Players down the side, play time and the activity timeline in the main column.
function playerRow(p) {
  const href = p.uuid ? `#/s/${encodeURIComponent(curSid)}/p/${p.uuid}` : null;
  const h = p.headline || {};
  const sub = p.online
    ? `<span class="live-tag"><span class="status-dot on"></span>Playing</span>${p.dimension ? `<span>${esc(dimName(p.dimension))}</span>` : ""}`
    : `<span>Last seen ${esc(fmtAgo(p.last_seen))}</span>`;
  const vitals = p.online && p.health != null
    ? `<span title="Health">❤ ${p.health}</span>${p.food != null ? `<span title="Hunger">🍗 ${p.food}</span>` : ""}`
    : "";
  const right = p.online && p.today_seconds ? `<span class="pr-val" title="Played today">${fmtSeconds(p.today_seconds)}<small>today</small></span>`
    : `<span class="pr-val" title="Time played in total">${fmtDuration(h.play_time)}<small>total</small></span>`;
  const inner = `${headHtml(p, 40)}
    <div class="pr-main"><div class="pr-name">${esc(p.name)}${p.xp_level != null ? `<span class="lvl" title="Level">${p.xp_level}</span>` : ""}${p.op ? '<span class="op-badge">OP</span>' : ""}</div>
      <div class="pr-sub">${sub}${vitals}</div></div>${right}`;
  const cls = `pl-row ${p.online ? "is-online" : ""}`;
  return href ? `<a class="${cls}" href="${href}">${inner}</a>` : `<div class="${cls}">${inner}</div>`;
}
function playersListHtml(data) {
  const on = data.players.filter((p) => p.online), off = data.players.filter((p) => !p.online);
  if (!data.players.length) return `<div class="empty"><h3>Nobody has joined yet</h3><p>Players appear here after their first visit.</p></div>`;
  return `${on.length ? `<div class="pl-group"><div class="pl-label">Playing now · ${on.length}</div>${on.map(playerRow).join("")}</div>` : `<p class="muted pl-none">Nobody is playing right now.</p>`}
    ${off.length ? `<div class="pl-group"><div class="pl-label">${on.length ? "Everyone else" : "Players"}</div>${off.map(playerRow).join("")}</div>` : ""}`;
}
async function viewOverview(sid) {
  const s = await serverFrame(sid, "overview");
  const data = await api(`/api/servers/${sid}/players`);
  setView(serverHeader(s, "overview") + `<div class="overview">
      <aside class="ov-side" aria-label="Players"><div class="section-head"><h2>Players</h2><span class="muted">${data.players.length} joined</span></div>
        <div id="players-body">${playersListHtml(data)}</div></aside>
      <div class="ov-main"><section class="rc-wrap" id="ov-recap" aria-label="Daily recap"></section><div id="ov-activity"></div></div></div>`);
  wireHeader(s);
  const refreshRecap = mountRecap($("#ov-recap"), sid);
  const refreshActivity = mountActivity($("#ov-activity"), sid, data.players.map((p) => p.name));
  every(10000, async () => {
    const d = await api(`/api/servers/${sid}/players`).catch(() => null);
    if (d && $("#players-body")) $("#players-body").innerHTML = playersListHtml(d);
  });
  every(30000, refreshActivity);
  every(120000, refreshRecap);
}

// Today so far, yesterday, any day back to the first one on record, and "on this day".
function mountRecap(el, sid) {
  let day = null, data = null;
  const load = async () => {
    try { data = await api(`/api/servers/${encodeURIComponent(sid)}/recap${day ? `?day=${day}` : ""}`); } catch { return; }
    if (!el.isConnected) return;
    const isToday = data.day === data.today;
    const title = isToday ? "Today so far" : recapDate(data.day);
    const y = isToday && data.yesterday;
    const cards = recapCardHtml(data.recap, title) + (y && (y.players.length || y.advancements.length) ? recapCardHtml(y, "Yesterday") : "");
    el.innerHTML = `<div class="section-head"><h2>Recap</h2>
        <div class="rc-nav"><button class="btn sm" data-go="${esc(data.prev || "")}" ${data.prev ? "" : "disabled"} title="Earlier day with play">‹</button>
          <input class="input sm" type="date" value="${esc(data.day)}" min="${esc(data.first || data.today)}" max="${esc(data.today)}" aria-label="Pick a day">
          <button class="btn sm" data-go="${esc(data.next || "")}" ${data.next ? "" : "disabled"} title="Later day with play">›</button>
          ${isToday ? "" : `<button class="btn sm" data-go="${esc(data.today)}">Today</button>`}</div></div>
      <div class="rc-cards">${cards}</div>${onThisDayHtml(data.on_this_day)}`;
  };
  el.addEventListener("click", (e) => { const b = e.target.closest("[data-go]"); if (b?.dataset.go) { day = b.dataset.go === data?.today ? null : b.dataset.go; load(); } });
  el.addEventListener("change", (e) => { if (e.target.type === "date" && e.target.value) { day = e.target.value; load(); } });
  load();
  return () => { if (!day) load(); };
}

// ---------------------------------------------------------------- player page
async function viewPlayer(sid, uuid, tab = "inventory") {
  const s = await serverFrame(sid, "overview");
  let p;
  try { p = await api(`/api/servers/${sid}/players/${uuid}`); }
  catch (e) { setView(serverHeader(s, "overview") + `<div class="empty"><h3>Player not found</h3><p>${esc(e.message)}</p></div>`); wireHeader(s); return; }
  const base = `#/s/${encodeURIComponent(sid)}/p/${uuid}`;
  const tabs = [["inventory", "Inventory"], ["history", "Play history"], ["stats", "Statistics"], ["advancements", "Advancements"]];
  setView(`<a class="back" href="#/s/${encodeURIComponent(sid)}">← ${esc(s.name)}</a>
    <div id="hero">${playerHero(p)}</div>
    <div id="strip">${statStrip(p)}</div>
    <nav class="tabs" aria-label="Player sections">${tabs.map(([k, l]) => `<a href="${base}${k === "inventory" ? "" : "/" + k}" ${k === tab ? 'aria-current="page"' : ""}>${l}</a>`).join("")}</nav>
    <div id="player-tab"></div>`);
  document.title = `${p.name} · ${s.name}`;
  const renderTab = () => {
    state.items.clear();
    const el = $("#player-tab");
    if (!el) return;
    if (tab === "inventory") el.innerHTML = inventoryHtml(p);
    else if (tab === "stats") renderStats(el, p);
    else if (tab === "advancements") el.innerHTML = advancementsHtml(p);
    else if (tab === "history") renderPlayerHistory(el, sid, p);
  };
  renderTab();
  $("#hero").addEventListener("click", (e) => { if (e.target.closest("[data-give]")) openGiveItem(sid, p.name); });
  $("#hero").addEventListener("change", async (e) => {
    const sel = e.target.closest("[data-tp]");
    if (!sel?.value) return;
    const [action, target] = sel.value.split(":");
    const text = sel.selectedOptions[0].textContent;
    sel.value = "";
    try {
      const r = await post(`/api/servers/${encodeURIComponent(sid)}/control/player/${encodeURIComponent(p.name)}/${action}`, { target });
      const bad = (r.results || []).find((x) => x.ok === false);
      showToast(bad ? esc((bad.output || "The game said no").slice(0, 160)) : `${esc(text)}: done`, bad ? 5000 : 2500);
    } catch (err) { showToast(esc(err.message), 5000); }
  });
  if (p.online) {
    let last = JSON.stringify(p.data);
    every(4000, async () => {
      const n = await api(`/api/servers/${sid}/players/${uuid}`).catch(() => null);
      if (!n || !$("#hero")) return;
      const sig = JSON.stringify(n.data);
      $("#hero").innerHTML = playerHero(n);
      if (sig !== last) {
        last = sig; p = n;
        $("#strip").innerHTML = statStrip(n);
        if (tab === "inventory" && !document.querySelector(".modal")) { hideTip(); renderTab(); }
      }
    });
  }
}

// Giving needs the player in the game, and only admins can do it.
// Teleporting likewise; "others" are the other players online now.
const giveBtn = (p) => {
  if (!isAdmin() || !p.online) return "";
  const others = (state.servers.find((x) => x.id === curSid)?.online || []).filter((n) => n.toLowerCase() !== p.name.toLowerCase());
  return `<div class="btn-row hero-actions"><button class="btn sm" type="button" data-give>🎁 Give items</button>
    <select class="input sm" data-tp aria-label="Teleport ${esc(p.name)}"><option value="">📍 Teleport…</option>
      <option value="tp_spawn">Send to spawn</option><option value="tp_bed">Send to their bed</option>
      ${others.map((n) => `<option value="tp_to_player:${esc(n)}">Send to ${esc(n)}</option>`).join("")}
      ${others.map((n) => `<option value="bring:${esc(n)}">Bring ${esc(n)} here</option>`).join("")}</select></div>`;
};

function playerHero(p) {
  const d = p.data;
  const body = p.uuid ? `<img src="https://mc-heads.net/body/${p.uuid.replace(/-/g, "")}/240" alt="${esc(p.name)}'s skin" data-fail="letter" data-letter="${esc(p.name[0])}">` : "";
  let presence;
  if (p.online) {
    presence = p.source === "live"
      ? `<span class="live-tag"><span class="status-dot on"></span>Playing now · live</span>`
      : `<span class="live-tag"><span class="status-dot on"></span>Playing now</span><span>Inventory from last save, ${esc(fmtAgo(p.as_of))}${p.live_available ? "" : " (turn on RCON for live data)"}</span>`;
  } else presence = `<span>Last seen ${esc(fmtAgo(p.last_seen))}</span>`;
  if (!d) return `<div class="player-hero"><div class="body-render">${body}</div><div><h1>${esc(p.name)}</h1><div class="presence">${presence}</div><p class="muted" style="margin-top:12px">No saved player data yet.</p>${giveBtn(p)}</div></div>`;
  const pos = d.position;
  const effects = (d.effects || []).map((e) => `<span class="chip"><img src="${textureUrl(`mob_effect/${splitId(e.id)[1]}`)}" alt="" data-fail="remove"><b>${esc(effectName(e.id))} ${roman(e.amplifier + 1)}</b> ${e.duration > 0 && e.duration < 1e6 ? fmtDuration(e.duration) : ""}</span>`).join("");
  return `<div class="player-hero">
    <div class="body-render">${body}</div>
    <div>
      <h1>${esc(p.name)} ${p.op ? '<span class="op-badge">OP</span>' : ""}</h1>
      <div class="presence">${presence}</div>
      <div class="vitals">${heartsHtml(d.health, d.max_health)}${foodHtml(d.food)}${xpHtml(d.xp_level, d.xp_progress)}</div>
      <div class="chips">
        <span class="chip dim-tag ${dimClass(pos.dimension)}">${esc(dimName(pos.dimension))}</span>
        <span class="chip">X <b>${Math.round(pos.x)}</b> Y <b>${Math.round(pos.y)}</b> Z <b>${Math.round(pos.z)}</b></span>
        <span class="chip">${esc(humanize(d.gamemode))}${d.flying ? " · flying" : ""}</span>
        ${d.respawn ? `<span class="chip" title="Respawn point">Bed <b>${d.respawn.x}, ${d.respawn.y}, ${d.respawn.z}</b></span>` : ""}
        ${d.last_death ? `<span class="chip" title="Where they last died">Last death <b>${d.last_death.x}, ${d.last_death.y}, ${d.last_death.z}</b> ${esc(dimName(d.last_death.dimension))}</span>` : ""}
        ${effects}
      </div>
      ${giveBtn(p)}
    </div></div>`;
}

function statStrip(p) {
  const h = p.headline || {};
  const cells = [
    [fmtDuration(h.play_time), "Time played"], [fmtNum(h.mob_kills), "Mobs defeated"], [fmtNum(h.deaths), "Deaths"],
    [fmtNum(h.blocks_mined), "Blocks mined"], [fmtDistance(h.distance_cm), "Distance travelled"], [fmtNum(h.items_crafted), "Items crafted"],
  ];
  return `<div class="stat-strip">${cells.map(([v, k]) => `<div><div class="v">${esc(v)}</div><div class="k">${esc(k)}</div></div>`).join("")}</div>`;
}

function inventoryHtml(p) {
  const d = p.data;
  if (!d) return `<div class="empty"><h3>No inventory saved yet</h3><p>Minecraft writes player data when the world saves or the player logs out.</p></div>`;
  const inv = d.inventory;
  const body = p.uuid ? `<img src="https://mc-heads.net/body/${p.uuid.replace(/-/g, "")}/160" alt="" data-fail="remove">` : "";
  const armor = [["head", "helmet"], ["chest", "chestplate"], ["legs", "leggings"], ["feet", "boots"]]
    .map(([k, g]) => slotHtml(inv.armor[k], { ghost: g })).join("");
  const hotbar = inv.hotbar.map((it, i) => slotHtml(it, { selected: i === d.selected_slot })).join("");
  const asOf = p.source === "live" ? "Live" : `Saved ${fmtAgo(p.as_of)}`;
  return `<div class="inv-layout">
    <div>
      <div class="mc-panel">
        <h3>Inventory <span style="float:right;font-size:.85rem;color:#666">${esc(asOf)}</span></h3>
        <div class="inv-top"><div class="armor-col">${armor}</div>
          <div class="inv-stage"><div class="mini-body">${body}</div>${slotHtml(inv.offhand, { ghost: "shield" })}</div></div>
        <div class="mc-grid">${inv.main.map((it) => slotHtml(it)).join("")}</div>
        <div class="hotbar-gap"></div>
        <div class="mc-grid">${hotbar}</div>
      </div>
    </div>
    <div>
      <div class="mc-panel"><h3>Ender Chest</h3><div class="mc-grid">${gridHtml(d.ender_chest, 27)}</div></div>
      ${(d.mod_items || []).map((g) => `<div class="mc-panel mod-slots"><h3>${esc(g.label.split(" › ").map(humanize).join(" › "))}</h3>
        <div class="mc-grid">${gridHtml(g.items, Math.max(9, Math.ceil(g.items.length / 9) * 9), false)}</div></div>`).join("")}
      <p class="muted" style="margin-top:12px;font-size:.9rem;max-width:480px">Hover an item for details. Shulker boxes and bundles with a gold corner can be opened.</p>
    </div>
  </div>`;
}

// ---------------------------------------------------------------- statistics
const TIME_STATS = /play_time|play_one_minute|time_since|sneak_time|total_world_time/;
function fmtCustom(key, v) {
  if (TIME_STATS.test(key)) return fmtDuration(v);
  if (key.endsWith("_one_cm")) return fmtDistance(v);
  if (key.includes("damage")) return `${fmtNum(v / 20)} ♥`;
  return fmtNum(v);
}
const ITEM_COLS = [["mined", "Mined"], ["crafted", "Crafted"], ["used", "Used"], ["broken", "Broken"], ["picked_up", "Picked up"], ["dropped", "Dropped"]];
function renderStats(el, p) {
  const st = p.stats || {};
  const ui = { mode: "general", q: "", sort: "total", dir: -1 };
  const draw = () => {
    const q = ui.q.toLowerCase();
    let body = "";
    if (ui.mode === "general") {
      const custom = Object.entries(st["minecraft:custom"] || {})
        .map(([k, v]) => [statName(k), fmtCustom(k, v)])
        .filter(([n]) => n.toLowerCase().includes(q)).sort((a, b) => a[0].localeCompare(b[0]));
      body = custom.length ? `<div class="general-grid">${custom.map(([n, v]) => `<div class="row"><span>${esc(n)}</span><span>${esc(v)}</span></div>`).join("")}</div>` : emptyStats();
    } else if (ui.mode === "items") {
      const rows = new Map();
      for (const [cat] of ITEM_COLS) for (const [id, v] of Object.entries(st[`minecraft:${cat}`] || {})) {
        if (!rows.has(id)) rows.set(id, { id, total: 0 });
        rows.get(id)[cat] = v; rows.get(id).total += v;
      }
      let list = [...rows.values()].map((r) => ({ ...r, name: itemName(r.id) })).filter((r) => r.name.toLowerCase().includes(q));
      list.sort((a, b) => ui.sort === "name" ? a.name.localeCompare(b.name) * -ui.dir : ((a[ui.sort] || 0) - (b[ui.sort] || 0)) * ui.dir);
      const th = (k, l) => `<th data-sort="${k}" ${ui.sort === k ? `aria-sort="${ui.dir < 0 ? "descending" : "ascending"}"` : ""}>${l}${ui.sort === k ? (ui.dir < 0 ? " ▾" : " ▴") : ""}</th>`;
      body = list.length ? `<div class="table-wrap"><table class="data"><thead><tr>${th("name", "Item")}${ITEM_COLS.map(([k, l]) => th(k, l)).join("")}</tr></thead><tbody>
        ${list.slice(0, 400).map((r) => `<tr><td><div class="namecell">${itemIcon(r)}${esc(r.name)}</div></td>${ITEM_COLS.map(([k]) => `<td class="${r[k] ? "" : "zero"}">${r[k] ? fmtNum(r[k]) : "–"}</td>`).join("")}</tr>`).join("")}
        </tbody></table></div>` : emptyStats();
    } else {
      const ids = new Set([...Object.keys(st["minecraft:killed"] || {}), ...Object.keys(st["minecraft:killed_by"] || {})]);
      let list = [...ids].map((id) => ({ id, name: entityName(id), killed: st["minecraft:killed"]?.[id] || 0, killed_by: st["minecraft:killed_by"]?.[id] || 0 }))
        .filter((r) => r.name.toLowerCase().includes(q));
      const key = ["killed", "killed_by", "name"].includes(ui.sort) ? ui.sort : "killed";
      list.sort((a, b) => key === "name" ? a.name.localeCompare(b.name) * -ui.dir : (a[key] - b[key]) * ui.dir);
      const th = (k, l) => `<th data-sort="${k}" ${key === k ? `aria-sort="${ui.dir < 0 ? "descending" : "ascending"}"` : ""}>${l}${key === k ? (ui.dir < 0 ? " ▾" : " ▴") : ""}</th>`;
      body = list.length ? `<div class="table-wrap"><table class="data"><thead><tr>${th("name", "Mob")}${th("killed", "Defeated")}${th("killed_by", "Defeated by")}</tr></thead><tbody>
        ${list.map((r) => `<tr><td>${esc(r.name)}</td><td class="${r.killed ? "" : "zero"}">${r.killed ? fmtNum(r.killed) : "–"}</td><td class="${r.killed_by ? "" : "zero"}">${r.killed_by ? fmtNum(r.killed_by) : "–"}</td></tr>`).join("")}
        </tbody></table></div>` : emptyStats();
    }
    $("#stats-body", el).innerHTML = body;
    $$("th[data-sort]", el).forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.sort; if (ui.sort === k) ui.dir *= -1; else { ui.sort = k; ui.dir = k === "name" ? 1 : -1; } draw();
    }));
  };
  el.innerHTML = `<div class="toolbar">
      <div class="seg" role="group" aria-label="Statistic type">${[["general", "General"], ["items", "Items"], ["mobs", "Mobs"]].map(([k, l]) => `<button data-mode="${k}" aria-pressed="${k === ui.mode}">${l}</button>`).join("")}</div>
      <input class="input" type="search" placeholder="Filter statistics" aria-label="Filter statistics" style="flex:1;max-width:320px">
    </div><div id="stats-body"></div>`;
  $$(".seg button", el).forEach((b) => b.addEventListener("click", () => {
    ui.mode = b.dataset.mode; ui.sort = ui.mode === "mobs" ? "killed" : "total"; ui.dir = -1;
    $$(".seg button", el).forEach((x) => x.setAttribute("aria-pressed", x === b)); draw();
  }));
  $("input", el).addEventListener("input", (e) => { ui.q = e.target.value; draw(); });
  draw();
}
const emptyStats = () => `<div class="empty"><h3>Nothing here yet</h3><p>Statistics fill in as this player explores, mines and fights.</p></div>`;

// ---------------------------------------------------------------- advancements
const ADV_ORDER = ["story", "nether", "end", "adventure", "husbandry"];
const ADV_TITLES = { story: "Minecraft", nether: "Nether", end: "The End", adventure: "Adventure", husbandry: "Husbandry" };
function compText(c) {
  if (!c) return "";
  if (typeof c === "string") return c;
  if (c.translate) return tr(c.translate, c.fallback || humanize(c.translate.replace(/\.(title|description)$/, "")));
  return c.text || "";
}
function advancementsHtml(p) {
  const defs = state.advDefs[curSid] || [];
  const mine = p.advancements || {};
  if (!defs.length) {
    const done = Object.entries(mine).filter(([k, v]) => v.done && !k.includes("recipes/"));
    if (!done.length) return `<div class="empty"><h3>No advancements yet</h3><p>Completed advancements show up here.</p></div>`;
    return `<div class="adv-grid">${done.map(([k, v]) => `<div class="adv done"><div class="frame"></div><div><div class="t">${esc(humanize(k))}</div><div class="when">${esc(v.completed_at || "")}</div></div></div>`).join("")}</div>`;
  }
  const byCat = {};
  for (const d of defs) (byCat[d.category] ||= []).push(d);
  const cats = Object.keys(byCat).sort((a, b) => ((ADV_ORDER.indexOf(a) + 1 || 99) - (ADV_ORDER.indexOf(b) + 1 || 99)) || a.localeCompare(b));
  const catTitle = (cat) => ADV_TITLES[cat] || (byCat[cat][0].category_title ? compText(byCat[cat][0].category_title) : humanize(cat.split(":")[0]));
  return `<div class="adv-cats">${cats.map((cat) => {
    const list = treeOrder(byCat[cat]);
    const done = list.filter((d) => mine[d.id]?.done).length;
    return `<section><div class="adv-cat-head"><h2>${esc(catTitle(cat))}</h2><span class="num muted">${done} / ${list.length}</span>
      <div class="adv-progress"><span style="width:${(done / list.length) * 100}%"></span></div></div>
      <div class="adv-grid">${list.map((d) => {
        const m = mine[d.id], isDone = !!m?.done, secret = d.hidden && !isDone;
        return `<div class="adv ${isDone ? "done" : "locked"}">
          <div class="frame ${esc(d.frame)}">${d.icon && !secret ? itemIcon({ id: d.icon }) : ""}</div>
          <div><div class="t">${secret ? "Hidden advancement" : esc(compText(d.title))}</div>
            <div class="d">${secret ? "Keep playing to discover this one." : esc(compText(d.description))}</div>
            ${isDone && m.completed_at ? `<div class="when">${esc(new Date(m.completed_at.replace(" ", "T").replace(/ ([+-]\d\d)(\d\d)$/, "$1:$2")).toLocaleDateString() || m.completed_at)}</div>` : ""}
          </div></div>`;
      }).join("")}</div></section>`;
  }).join("")}</div>`;
}
function treeOrder(list) {
  const ids = new Set(list.map((d) => d.id));
  const kids = {};
  const roots = [];
  for (const d of list) { if (d.parent && ids.has(d.parent)) (kids[d.parent] ||= []).push(d); else roots.push(d); }
  const out = [];
  const walk = (d) => { out.push(d); (kids[d.id] || []).sort((a, b) => a.id.localeCompare(b.id)).forEach(walk); };
  roots.sort((a, b) => a.id.localeCompare(b.id)).forEach(walk);
  return out;
}

// ---------------------------------------------------------------- leaderboards
async function viewLeaderboards(sid) {
  const s = await serverFrame(sid, "leaderboards");
  const data = await api(`/api/servers/${sid}/leaderboard`);
  const boards = (data.boards || []).map(({ key: k, title, kind }) => {
    const rows = data.players.filter((r) => r[k] > 0).sort((a, b) => b[k] - a[k]).slice(0, 8);
    if (!rows.length) return "";
    const max = rows[0][k];
    return `<div class="board"><h3>${esc(title)}</h3><ol>${rows.map((r, i) => `<li>
      <span class="rank">${i + 1}</span>${miniHead(r)}<a href="#/s/${encodeURIComponent(sid)}/p/${r.uuid}">${esc(r.name)}</a><span class="val">${esc(fmtStat(kind, r[k]))}</span>
      <span></span><span></span><div class="bar-bg"><span style="width:${(r[k] / max) * 100}%"></span></div></li>`).join("")}</ol></div>`;
  }).join("");
  setView(serverHeader(s, "leaderboards") + (boards ? `<div class="boards">${boards}</div>` : `<div class="empty"><h3>No scores yet</h3><p>Leaderboards appear once players have some statistics.</p></div>`));
  wireHeader(s);
}

// ---------------------------------------------------------------- world
function skyHtml(w) {
  if (w.time_of_day == null) {
    const replies = w.debug?.rcon_replies || {};
    const asked = Object.keys(replies).length > 0 && !replies.error;
    const msg = asked
      ? "Solstone asked the server but couldn't understand its reply. This Minecraft version may word it differently. The details below show exactly what came back."
      : "Not available yet. Turn on RCON for this server and the current day and time will show here.";
    const details = w.debug ? `<details class="debug"><summary>Details for troubleshooting</summary><pre>${esc(
      [...Object.entries(replies).map(([k, v]) => `> ${k}\n${v || "(empty reply)"}`), "", "Time-related save data:", ...(w.debug.time_related_keys.length ? w.debug.time_related_keys : ["(none found)"]),
       "", `Files read: ${w.debug.data_files.join(", ")}`].join("\n"))}</pre></details>` : "";
    return `<div class="sky" style="background:linear-gradient(#3b4252,#4c566a)"><h2>World time</h2><div class="sub">${esc(msg)}</div>${details}</div>`;
  }
  const t = w.time_of_day;
  const hour = Math.floor((t / 1000 + 6) % 24), min = Math.floor(((t % 1000) / 1000) * 60);
  const clock = new Date(2000, 0, 1, hour, min).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const isNight = t >= 13000 && t < 23000;
  const phase = t < 12000 ? "Daytime" : t < 13000 ? "Sunset" : t < 23000 ? "Night" : "Sunrise";
  const bg = w.thundering ? "linear-gradient(#2c3240,#4a5262)" : w.raining ? "linear-gradient(#4f5d73,#7a8798)"
    : isNight ? "linear-gradient(#0b1230,#1d2a55)" : phase === "Sunset" || phase === "Sunrise" ? "linear-gradient(#3b4f8c,#e08a5a)" : "linear-gradient(#5f8ee8,#a9c8ff)";
  const frac = isNight ? (t - 13000) / 10000 : ((t + 1000) % 24000) / 14000;
  const left = 8 + Math.min(Math.max(frac, 0), 1) * 78;
  const top = 18 + Math.abs(0.5 - Math.min(Math.max(frac, 0), 1)) * 70;
  const orb = isNight
    ? `<svg class="orb" style="left:${left}%;top:${top}px" viewBox="0 0 8 8" shape-rendering="crispEdges"><rect x="1" y="1" width="6" height="6" fill="#dfe6f5"/><rect x="2" y="2" width="2" height="2" fill="#b9c3d8"/><rect x="5" y="4" width="1" height="2" fill="#b9c3d8"/></svg>`
    : `<svg class="orb" style="left:${left}%;top:${top}px" viewBox="0 0 8 8" shape-rendering="crispEdges"><rect x="0" y="0" width="8" height="8" fill="#ffe46b"/><rect x="1" y="1" width="6" height="6" fill="#fff6b0"/></svg>`;
  const weather = w.raining == null ? null : w.thundering ? "Thunderstorm" : w.raining ? "Raining" : "Clear skies";
  const bits = [clock, phase, weather].filter(Boolean).map(esc).join(" · ");
  const src = w.time_source === "live" ? "Live from the server" : "From the last world save";
  return `<div class="sky" style="background:${bg}">${orb}<h2>Day ${fmtNum(w.day)}</h2><div class="sub">${bits}</div><div class="sub" style="font-size:.8rem;opacity:.8">${src}</div></div>`;
}
async function viewWorld(sid) {
  const s = await serverFrame(sid, "world");
  const [w, pl] = await Promise.all([api(`/api/servers/${sid}/world`), api(`/api/servers/${sid}/players`)]);
  const ruleVal = (v) => v === "true" || v === true ? '<span class="on">On</span>' : v === "false" || v === false ? '<span class="off">Off</span>' : esc(v);
  const maxChunks = Math.max(1, ...w.dimensions.map((d) => d.chunks));
  const located = pl.players.filter((p) => p.position);
  const map = s.map_url
    ? `<iframe class="map-frame" src="${esc(s.map_url)}" title="World map" loading="lazy"></iframe><p class="muted" style="margin-top:8px;font-size:.9rem"><a href="${esc(s.map_url)}" target="_blank" rel="noopener">Open the map full screen</a></p>`
    : `<div class="empty"><h3>Add a live map</h3><p>Install the <b>BlueMap</b> or <b>squaremap</b> Fabric mod on this server, then paste its web address (for example <code>http://your-server:8100</code>) in server settings. The map will show here.</p><p style="margin-top:12px"><button class="btn primary" id="btn-map">Add map address</button></p></div>`;
  setView(serverHeader(s, "world") + `
    <div class="world-top"><div id="world-sky" class="world-sky">${skyHtml(w)}</div>
      <div class="panel"><dl class="kv">
        <dt>World</dt><dd>${esc(w.level_name)}</dd>
        <dt>Seed</dt><dd>${w.seed ? `<span class="num">${esc(w.seed)}</span><button class="copy" data-copy="${esc(w.seed)}">Copy</button>` : "Unknown"}</dd>
        <dt>Difficulty</dt><dd>${esc(humanize(w.difficulty || "?"))}${w.hardcore ? " · Hardcore" : ""}</dd>
        <dt>Game mode</dt><dd>${esc(humanize(w.default_gamemode))}</dd>
        <dt>World spawn</dt><dd>${w.spawn ? `<span class="num">${w.spawn.x}, ${w.spawn.y}, ${w.spawn.z}</span>` : "Unknown"}</dd>
        <dt>Total ticks</dt><dd>${fmtDuration(w.game_time)} of world time</dd>
      </dl></div></div>
    <section class="section"><div class="section-head"><h2>Map</h2></div>${map}</section>
    <section class="section"><div class="section-head"><h2>Where everyone is</h2><span class="muted">Live for players online with RCON, otherwise from their last save</span></div>
      ${located.length ? `<div class="where">${located.map((p) => `<a class="where-row" href="#/s/${encodeURIComponent(sid)}/p/${p.uuid}">${miniHead(p, 32)}
        <div><b>${esc(p.name)}</b> ${p.online ? '<span class="live-tag" style="font-size:.85rem"><span class="status-dot on"></span>online</span>' : `<span class="faint" style="font-size:.85rem">${esc(fmtAgo(p.last_seen))}</span>`}
          <div class="coords">${Math.round(p.position.x)}, ${Math.round(p.position.y)}, ${Math.round(p.position.z)}</div></div>
        <span class="dim-tag ${dimClass(p.position.dimension)}">${esc(dimName(p.position.dimension))}</span></a>`).join("")}</div>` : `<div class="empty"><p>No player positions saved yet.</p></div>`}
    </section>
    <section class="section"><div class="section-head"><h2>Explored</h2><span class="muted">Chunks generated in each dimension</span>${isAdmin() ? '<button class="btn sm" id="btn-mapcheck" style="margin-left:auto">🔍 Check the map drawing</button>' : ""}</div>
      <div class="panel dims">${w.dimensions.map((d) => `<div class="dim-bar"><span class="dim-tag ${dimClass(d.id)}" style="justify-self:start">${esc(dimName(d.id))}</span>
        <div class="bar-bg"><span style="width:${(d.chunks / maxChunks) * 100}%"></span></div><span class="num">${fmtNum(d.chunks)}</span></div>`).join("") || '<p class="muted">No region files found.</p>'}</div>
    </section>
    <section class="section"><div class="section-head"><h2>Game rules</h2></div>
      ${Object.keys(w.game_rules).length ? `<div class="rules">${Object.entries(w.game_rules).sort().map(([k, v]) => `<div><span>${esc(humanize(k.replace(/([a-z])([A-Z])/g, "$1_$2")))}</span>${ruleVal(v)}</div>`).join("")}</div>` : '<p class="muted">Using default game rules.</p>'}
    </section>
    ${w.datapacks.enabled.length ? `<section class="section"><div class="section-head"><h2>Data packs</h2></div><div class="chips">${w.datapacks.enabled.map((d) => `<span class="chip">${esc(d.replace(/^file\//, ""))}</span>`).join("")}</div></section>` : ""}`);
  wireHeader(s);
  $("#btn-mapcheck")?.addEventListener("click", () => openMapCheck(sid, w.dimensions.map((d) => d.id)));
  // The clock moves on its own (20 ticks a second while people play) and checks back with
  // the server every 20 seconds, so the time, sun and weather stay current.
  let wd = w, readAt = Date.now() - (w.age || 0) * 1000;
  const paintSky = () => {
    const el = $("#world-sky");
    if (!el || wd.time_of_day == null) return;
    const playing = (s.online?.length || 0) > 0 && wd.time_source === "live";
    const total = wd.time_of_day + (playing ? ((Date.now() - readAt) / 1000) * 20 : 0);
    const html = skyHtml({ ...wd, time_of_day: Math.floor(total) % 24000, day: wd.day + Math.floor(total / 24000) });
    if (el._html !== html) { el._html = html; el.innerHTML = html; }
  };
  every(1000, paintSky);
  every(20000, async () => {
    const [nw, ns] = await Promise.all([api(`/api/servers/${sid}/world`).catch(() => null), api(`/api/servers/${encodeURIComponent(sid)}`).catch(() => null)]);
    if (nw) { wd = nw; readAt = Date.now() - (nw.age || 0) * 1000; }
    if (ns) s.online = ns.online;
    paintSky();
  });
  $("#btn-map")?.addEventListener("click", () => openSettings(s));
  $$("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch { b.textContent = "Select it"; }
  }));
}

// ---------------------------------------------------------------- mods
async function viewMods(sid) {
  const s = await serverFrame(sid, "mods");
  const data = await api(`/api/servers/${sid}/mods`);
  setView(serverHeader(s, "mods") + `<div class="section-head"><h2>${data.mods.length} ${data.mods.length === 1 ? "mod" : "mods"}</h2><span class="muted">${esc(data.loader)}</span></div>` +
    (data.mods.length ? `<div class="mods">${data.mods.map((m) => `<div class="mod"><div class="mn"><span>${esc(m.name)}</span><span class="mv">${esc(m.version || "")}</span></div>${m.description ? `<p>${esc(m.description)}</p>` : ""}</div>`).join("")}</div>`
      : `<div class="empty"><h3>No mods installed</h3><p>This server runs ${esc(data.loader)} without a mods folder.</p></div>`));
  wireHeader(s);
}

// ---------------------------------------------------------------- settings
async function openSettings(s) {
  const cur = await api(`/api/servers/${encodeURIComponent(s.id)}/settings`).catch(() => ({}));
  openModal(`<h2>Server settings</h2>
    <form id="settings-form">
      <label>Display name<input class="input" name="display_name" value="${esc(cur.display_name || "")}" placeholder="${esc(s.name)}"></label>
      <label>Map address <small>BlueMap, squaremap or Dynmap web address shown on the World tab</small><input class="input" name="map_url" value="${esc(cur.map_url || "")}" placeholder="http://192.168.1.10:8100"></label>
      <label>RCON host <small>Used for live inventories. Leave blank to use ${esc(s.rcon?.host || "the Crafty host")}.</small><input class="input" name="rcon_host" value="${esc(cur.rcon_host || "")}"></label>
      <label>RCON port <small>Leave blank to use rcon.port from server.properties</small><input class="input" name="rcon_port" inputmode="numeric" value="${esc(cur.rcon_port || "")}"></label>
      <label>RCON password <small>${cur.rcon_password_set ? "Saved. Type a new one to replace it." : "Leave blank to use rcon.password from server.properties"}</small><input class="input" type="password" name="rcon_password" autocomplete="off"></label>
      <label class="check"><input type="checkbox" name="hidden" ${cur.hidden ? "checked" : ""}> Hide this server from Solstone</label>
      <div class="actions"><button type="button" class="btn" data-close-modal>Cancel</button><button class="btn primary" type="submit">Save settings</button></div>
    </form>`, (m) => {
    $("#settings-form", m).addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const body = { display_name: f.get("display_name"), map_url: f.get("map_url"), rcon_host: f.get("rcon_host"),
        rcon_port: f.get("rcon_port") ? Number(f.get("rcon_port")) : "", hidden: f.get("hidden") ? true : "" };
      if (f.get("rcon_password")) body.rcon_password = f.get("rcon_password");
      try {
        await post(`/api/servers/${encodeURIComponent(s.id)}/settings`, body, "PUT");
        closeModal(); showToast("Settings saved", 2500);
        await loadServers(); route();
      } catch (err) { showToast(`Couldn't save settings: ${esc(err.message)}`, 5000); }
    });
  });
}

// ================================================================ router
async function route() {
  clearTimers();
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent).filter(Boolean);
  try {
    if (!me.user) return;
    if (parts[0] === "admin") { await viewAdmin(); return; }
    if (parts[0] === "announcements") { await viewAnnouncements(); return; }
    if (parts[0] === "coming-up") { await viewUpcoming(); return; }
    if (parts[0] === "music") { await viewMusic(parts[1], parts[2]); return; }
    if (parts[0] === "fireworks" && parts[1] === "settings") { await viewFireworkSettings(); return; }
    if (parts[0] === "fireworks") { await viewFireworkEditor(parts[1]); return; }
    if (parts[0] === "s" && parts[1]) {
      const sid = parts[1];
      if (parts[2] === "p" && parts[3]) await viewPlayer(sid, parts[3], parts[4] || "inventory");
      else if (parts[2] === "world") await viewWorld(sid);
      else if (parts[2] === "activity") location.replace(`#/s/${encodeURIComponent(sid)}`);
      else if (parts[2] === "control") await viewControl(sid);
      else if (parts[2] === "check") await viewCheck(sid);
      else if (parts[2] === "chat") await viewChat(sid);
      else if (parts[2] === "challenges" && parts[3] === "races") await viewRaces(sid);
      else if (parts[2] === "challenges" && parts[3] === "games") await viewGames(sid);
      else if (parts[2] === "challenges") await viewChallenges(sid);
      else if (parts[2] === "performance") await viewPerformance(sid);
      else if (parts[2] === "leaderboards") await viewLeaderboards(sid);
      else if (parts[2] === "mods") await viewMods(sid);
      else await viewOverview(sid);
    } else await viewHome();
  } catch (e) {
    setView(`<div class="empty"><h3>Something went wrong loading this page</h3><p>${esc(e.message)}</p><p style="margin-top:12px"><a href="#/">Back to servers</a></p></div>`);
    console.error(e);
  }
}
let boardSid = null;
addEventListener("hashchange", async () => {
  await route(); view().focus({ preventScroll: true }); scrollTo(0, 0); appSky.bar?.skyChanged();
  if ((curSid || "") !== boardSid) { boardSid = curSid || ""; appSky.board?.refresh(); }   // bedtime banners follow the server in view
});
document.addEventListener("DOMContentLoaded", async () => {
  $("#btn-notify")?.addEventListener("click", openNotifications);
  wireAccountMenu();
  const ch = $("#build-channel");
  if (ch && BUILD_CHANNEL === "beta") { ch.textContent = "Beta build"; ch.hidden = false; }
  try { signedIn((await api("/api/auth/me")).user); }
  catch { showLogin(); }
});
