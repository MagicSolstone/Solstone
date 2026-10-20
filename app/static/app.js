/* Solstone frontend — vanilla JS, hash routing. */
"use strict";

// Replaced at image build time with "beta" (push to main) or "stable" (version tag).
const BUILD_CHANNEL = "__BUILD_CHANNEL__";

// ================================================================ utilities
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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
const isAdmin = () => me.user?.role === "admin";

function showLogin(message = "") {
  clearTimers?.();
  me.user = null;
  document.body.classList.add("logged-out");
  const root = $("#login-root");
  root.hidden = false;
  root.innerHTML = `<canvas id="login-sky" aria-hidden="true"></canvas>
    <div class="login-wrap"><form class="login-card" id="login-form" autocomplete="on">
      <img src="/static/solstone.svg" alt="" width="56" height="56">
      <div class="login-title"><h1>Solstone</h1><p class="tagline">Server explorer for Minecraft</p></div>
      <label>Username<input class="input" name="username" autocomplete="username" autocapitalize="off" required></label>
      <label>Password<input class="input" type="password" name="password" autocomplete="current-password" required></label>
      <p class="login-error" role="alert">${esc(message)}</p>
      <button class="btn primary" type="submit">Sign in</button>
    </form><section class="login-servers" id="login-servers" aria-label="Servers" hidden></section></div>`;
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
  const root = $("#login-root"); root.hidden = true; root.innerHTML = "";
  $("#account-name").textContent = user.username;
  $("#account-role").textContent = user.role === "admin" ? "Admin" : "Viewer (read-only)";
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
      <div class="actions"><button type="button" class="btn" onclick="closeModal()">Cancel</button><button class="btn primary" type="submit">Change password</button></div>
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
  items: new Map(),  // item registry for tooltips
  itemSeq: 0,
};
function clearTimers() { state.timers.forEach(clearInterval); state.timers = []; }
function every(ms, fn) { state.timers.push(setInterval(fn, ms)); }

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
  return `<span class="item ${glint ? "glint" : ""} ${extra}" style="--mask:url('${url}')"><img class="item-img" src="${url}" alt="" loading="lazy" data-id="${esc(id)}" onerror="lsIconFail(this)"></span>`;
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

// ================================================================ pixel HUD icons
const HEART = [".##.##.", "#######", "#######", ".#####.", "..###..", "...#..."];
const FOOD = [".....##.", "....####", "...#####", "...####.", "..##....", ".##.....", "#.#.....", ".#......"];
function pixelSvg(pattern, fillFn, title = "") {
  const h = pattern.length, w = pattern[0].length;
  const filled = (x, y) => y >= 0 && y < h && x >= 0 && x < w && pattern[y][x] === "#";
  let rects = "";
  for (let y = -1; y <= h; y++) for (let x = -1; x <= w; x++) {
    if (!filled(x, y) && (filled(x - 1, y) || filled(x + 1, y) || filled(x, y - 1) || filled(x, y + 1)))
      rects += `<rect x="${x + 1}" y="${y + 1}" width="1" height="1" fill="#111"/>`;
  }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++)
    if (filled(x, y)) rects += `<rect x="${x + 1}" y="${y + 1}" width="1" height="1" fill="${fillFn(x, y, w, h)}"/>`;
  return `<svg viewBox="0 0 ${w + 2} ${h + 2}" shape-rendering="crispEdges" aria-hidden="true">${title ? `<title>${esc(title)}</title>` : ""}${rects}</svg>`;
}
function heartsHtml(health, max = 20) {
  const n = Math.ceil(max / 2);
  let out = "";
  for (let i = 0; i < n; i++) {
    const v = health - i * 2; // 2 = full, 1 = half
    out += pixelSvg(HEART, (x, y, w) => {
      const red = v >= 2 || (v >= 1 && x < Math.ceil(w / 2));
      if (!red) return "#3a1414";
      return x === 1 && y === 1 ? "#ffb3a8" : "#e0302a";
    });
  }
  return `<div class="hud-row" role="img" aria-label="Health ${health} of ${max}">${out}</div>`;
}
function foodHtml(food) {
  let out = "";
  for (let i = 0; i < 10; i++) {
    const v = food - i * 2;
    out += pixelSvg(FOOD, (x, y, w) => {
      const on = v >= 2 || (v >= 1 && x >= 4);
      if (!on) return "#3a2a1a";
      if (x <= 2 && y >= 5) return "#f1e7d0";
      return y <= 1 || (x === 4 && y === 2) ? "#e8a05a" : "#b3602a";
    });
  }
  return `<div class="hud-row food" role="img" aria-label="Hunger ${food} of 20">${out}</div>`;
}
function xpHtml(level, progress) {
  return `<div class="xp" role="img" aria-label="Level ${level}"><span class="lvl-num">${level}</span><div class="xp-bar"><span style="width:${Math.round((progress || 0) * 100)}%"></span></div></div>`;
}

// ================================================================ heads
function headHtml(p, size = 56, cls = "head") {
  const initial = esc((p.name || "?")[0].toUpperCase());
  if (!p.uuid) return `<div class="${cls}">${initial}</div>`;
  return `<div class="${cls}"><img src="https://mc-heads.net/avatar/${p.uuid.replace(/-/g, "")}/${size * 2}" alt="" loading="lazy" onerror="this.replaceWith(document.createTextNode('${initial}'))"></div>`;
}
const miniHead = (p) => p.uuid
  ? `<img src="https://mc-heads.net/avatar/${p.uuid.replace(/-/g, "")}/56" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`
  : `<span class="mini-head"></span>`;

// ================================================================ MOTD colours
const MC_COLORS = { 0: "#000", 1: "#00a", 2: "#0a0", 3: "#0aa", 4: "#a00", 5: "#a0a", 6: "#fa0", 7: "#aaa", 8: "#555", 9: "#55f", a: "#5f5", b: "#5ff", c: "#f55", d: "#f5f", e: "#ff5", f: "#fff" };
function motdHtml(text) {
  if (!text) return "";
  const parts = String(text).split(/§([0-9a-fk-or])/i);
  let out = esc(parts[0]), color = null, bold = false, italic = false;
  for (let i = 1; i < parts.length; i += 2) {
    const code = parts[i].toLowerCase(), chunk = parts[i + 1] || "";
    if (MC_COLORS[code]) { color = MC_COLORS[code]; bold = italic = false; }
    else if (code === "l") bold = true;
    else if (code === "o") italic = true;
    else if (code === "r") { color = null; bold = italic = false; }
    if (chunk) out += `<span style="${color ? `color:${color};` : ""}${bold ? "font-weight:700;" : ""}${italic ? "font-style:italic;" : ""}">${esc(chunk)}</span>`;
  }
  return out;
}

// ================================================================ slots + tooltip
function slotHtml(item, opts = {}) {
  const cls = ["slot"];
  if (opts.selected) cls.push("selected");
  if (!item) {
    const ghost = opts.ghost ? `<img class="ghost" src="${textureUrl(`gui/sprites/container/slot/${opts.ghost}`)}" alt="" onerror="this.remove()">` : "";
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
  h += `<div class="t-dim">${esc(item.id)}</div>`;
  return h;
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
function closeModal() { $("#modal-root").innerHTML = ""; }
function openContainer(item) {
  const isBundle = item.id.includes("bundle");
  const grid = isBundle ? gridHtml(item.contents, Math.max(9, Math.ceil(item.contents.length / 9) * 9), false) : gridHtml(item.contents, 27);
  openModal(`<h2>${esc(item.name || itemName(item))}</h2><div class="mc-panel"><div class="mc-grid">${grid}</div></div>
    <div class="actions"><button class="btn" onclick="closeModal()">Close</button></div>`);
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
  try { state.servers = await api("/api/servers"); } catch (e) { state.servers = state.servers || []; }
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
        <div class="who">${(s.online || []).map((n) => `<img src="https://mc-heads.net/avatar/${encodeURIComponent(n)}/48" alt="${esc(n)}" title="${esc(n)}">`).join("")}</div>
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
  const tabs = [["players", "Players", base], ["activity", "Activity", `${base}/activity`], ["performance", "Performance", `${base}/performance`],
    ...(java ? [["world", "World", `${base}/world`], ["leaderboards", "Leaderboards", `${base}/leaderboards`], ["mods", "Mods", `${base}/mods`]] : []),
    ...(isAdmin() ? [["control", "Control", `${base}/control`]] : [])];
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

// ---------------------------------------------------------------- players tab
function playerCard(p) {
  const href = p.uuid ? `#/s/${encodeURIComponent(curSid)}/p/${p.uuid}` : null;
  const presence = p.online
    ? `<span class="live-tag"><span class="status-dot on"></span>Playing now</span>`
    : `Last seen ${esc(fmtAgo(p.last_seen))}`;
  const where = p.online && p.dimension ? ` · ${esc(dimName(p.dimension))}` : "";
  const h = p.headline || {};
  const inner = `${headHtml(p)}
    <div><div class="pname">${esc(p.name)} ${p.xp_level != null ? `<span class="lvl" title="Level">${p.xp_level}</span>` : ""} ${p.op ? '<span class="op-badge">OP</span>' : ""}</div>
      <div class="meta">${presence}${where}</div>
      <div class="line"><span title="Time played in total">⏱ ${fmtDuration(h.play_time)}</span>${p.today_seconds ? `<span title="Played today">Today ${fmtSeconds(p.today_seconds)}</span>` : ""}<span title="Advancements">★ ${p.advancements ?? 0}</span>${p.health != null ? `<span title="Health">❤ ${p.health}</span>` : ""}</div>
    </div>`;
  return href ? `<a class="player-card ${p.online ? "is-online" : ""}" href="${href}">${inner}</a>` : `<div class="player-card is-online">${inner}</div>`;
}
async function viewPlayers(sid) {
  const s = await serverFrame(sid, "players");
  const draw = (data) => {
    const on = data.players.filter((p) => p.online), off = data.players.filter((p) => !p.online);
    return `${on.length ? `<section class="section"><div class="section-head"><h2>Playing now</h2></div><div class="player-grid">${on.map(playerCard).join("")}</div></section>` : ""}
      <section class="section"><div class="section-head"><h2>${on.length ? "Everyone else" : "Players"}</h2><span class="muted">${data.players.length} ${data.players.length === 1 ? "player has" : "players have"} joined this world</span></div>
      ${off.length ? `<div class="player-grid">${off.map(playerCard).join("")}</div>` : on.length ? "" : `<div class="empty"><h3>Nobody has joined yet</h3><p>Players appear here after their first visit.</p></div>`}</section>`;
  };
  const data = await api(`/api/servers/${sid}/players`);
  setView(serverHeader(s, "players") + `<div id="players-body">${draw(data)}</div>`);
  wireHeader(s);
  every(10000, async () => {
    const d = await api(`/api/servers/${sid}/players`).catch(() => null);
    if (d && $("#players-body")) $("#players-body").innerHTML = draw(d);
  });
}

// ---------------------------------------------------------------- player page
async function viewPlayer(sid, uuid, tab = "inventory") {
  const s = await serverFrame(sid, "players");
  let p;
  try { p = await api(`/api/servers/${sid}/players/${uuid}`); }
  catch (e) { setView(serverHeader(s, "players") + `<div class="empty"><h3>Player not found</h3><p>${esc(e.message)}</p></div>`); wireHeader(s); return; }
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

function playerHero(p) {
  const d = p.data;
  const body = p.uuid ? `<img src="https://mc-heads.net/body/${p.uuid.replace(/-/g, "")}/240" alt="${esc(p.name)}'s skin" onerror="this.outerHTML='<div class=\\'head fallback\\'>${esc(p.name[0])}</div>'">` : "";
  let presence;
  if (p.online) {
    presence = p.source === "live"
      ? `<span class="live-tag"><span class="status-dot on"></span>Playing now · live</span>`
      : `<span class="live-tag"><span class="status-dot on"></span>Playing now</span><span>Inventory from last save, ${esc(fmtAgo(p.as_of))}${p.live_available ? "" : " (turn on RCON for live data)"}</span>`;
  } else presence = `<span>Last seen ${esc(fmtAgo(p.last_seen))}</span>`;
  if (!d) return `<div class="player-hero"><div class="body-render">${body}</div><div><h1>${esc(p.name)}</h1><div class="presence">${presence}</div><p class="muted" style="margin-top:12px">No saved player data yet.</p></div></div>`;
  const pos = d.position;
  const effects = (d.effects || []).map((e) => `<span class="chip"><img src="${textureUrl(`mob_effect/${splitId(e.id)[1]}`)}" alt="" onerror="this.remove()"><b>${esc(effectName(e.id))} ${roman(e.amplifier + 1)}</b> ${e.duration > 0 && e.duration < 1e6 ? fmtDuration(e.duration) : ""}</span>`).join("");
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
  const body = p.uuid ? `<img src="https://mc-heads.net/body/${p.uuid.replace(/-/g, "")}/160" alt="" onerror="this.remove()">` : "";
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
  const cats = Object.keys(byCat).sort((a, b) => (ADV_ORDER.indexOf(a) + 1 || 99) - (ADV_ORDER.indexOf(b) + 1 || 99));
  return `<div class="adv-cats">${cats.map((cat) => {
    const list = treeOrder(byCat[cat]);
    const done = list.filter((d) => mine[d.id]?.done).length;
    return `<section><div class="adv-cat-head"><h2>${esc(ADV_TITLES[cat] || humanize(cat))}</h2><span class="num muted">${done} / ${list.length}</span>
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
const BOARDS = [
  ["play_time", "Time played", fmtDuration], ["xp_level", "Highest level", fmtNum], ["mob_kills", "Mobs defeated", fmtNum],
  ["blocks_mined", "Blocks mined", fmtNum], ["distance_cm", "Distance travelled", fmtDistance], ["items_crafted", "Items crafted", fmtNum],
  ["deaths", "Most deaths", fmtNum], ["jumps", "Jumps", fmtNum], ["fish_caught", "Fish caught", fmtNum],
  ["animals_bred", "Animals bred", fmtNum], ["traded", "Villager trades", fmtNum], ["time_since_death", "Longest alive right now", fmtDuration],
];
async function viewLeaderboards(sid) {
  const s = await serverFrame(sid, "leaderboards");
  const data = await api(`/api/servers/${sid}/leaderboard`);
  const boards = BOARDS.map(([k, title, f]) => {
    const rows = data.players.filter((r) => r[k] > 0).sort((a, b) => b[k] - a[k]).slice(0, 8);
    if (!rows.length) return "";
    const max = rows[0][k];
    return `<div class="board"><h3>${esc(title)}</h3><ol>${rows.map((r, i) => `<li>
      <span class="rank">${i + 1}</span>${miniHead(r)}<a href="#/s/${encodeURIComponent(sid)}/p/${r.uuid}">${esc(r.name)}</a><span class="val">${esc(f(r[k]))}</span>
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
    <div class="world-top">${skyHtml(w)}
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
      ${located.length ? `<div class="where">${located.map((p) => `<a class="where-row" href="#/s/${encodeURIComponent(sid)}/p/${p.uuid}">${miniHead(p)}
        <div><b>${esc(p.name)}</b> ${p.online ? '<span class="live-tag" style="font-size:.85rem"><span class="status-dot on"></span>online</span>' : `<span class="faint" style="font-size:.85rem">${esc(fmtAgo(p.last_seen))}</span>`}
          <div class="coords">${Math.round(p.position.x)}, ${Math.round(p.position.y)}, ${Math.round(p.position.z)}</div></div>
        <span class="dim-tag ${dimClass(p.position.dimension)}">${esc(dimName(p.position.dimension))}</span></a>`).join("")}</div>` : `<div class="empty"><p>No player positions saved yet.</p></div>`}
    </section>
    <section class="section"><div class="section-head"><h2>Explored</h2><span class="muted">Chunks generated in each dimension</span></div>
      <div class="panel dims">${w.dimensions.map((d) => `<div class="dim-bar"><span class="dim-tag ${dimClass(d.id)}" style="justify-self:start">${esc(dimName(d.id))}</span>
        <div class="bar-bg"><span style="width:${(d.chunks / maxChunks) * 100}%"></span></div><span class="num">${fmtNum(d.chunks)}</span></div>`).join("") || '<p class="muted">No region files found.</p>'}</div>
    </section>
    <section class="section"><div class="section-head"><h2>Game rules</h2></div>
      ${Object.keys(w.game_rules).length ? `<div class="rules">${Object.entries(w.game_rules).sort().map(([k, v]) => `<div><span>${esc(humanize(k.replace(/([a-z])([A-Z])/g, "$1_$2")))}</span>${ruleVal(v)}</div>`).join("")}</div>` : '<p class="muted">Using default game rules.</p>'}
    </section>
    ${w.datapacks.enabled.length ? `<section class="section"><div class="section-head"><h2>Data packs</h2></div><div class="chips">${w.datapacks.enabled.map((d) => `<span class="chip">${esc(d.replace(/^file\//, ""))}</span>`).join("")}</div></section>` : ""}`);
  wireHeader(s);
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
      <div class="actions"><button type="button" class="btn" onclick="closeModal()">Cancel</button><button class="btn primary" type="submit">Save settings</button></div>
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
    if (parts[0] === "s" && parts[1]) {
      const sid = parts[1];
      if (parts[2] === "p" && parts[3]) await viewPlayer(sid, parts[3], parts[4] || "inventory");
      else if (parts[2] === "world") await viewWorld(sid);
      else if (parts[2] === "activity") await viewActivity(sid);
      else if (parts[2] === "control") await viewControl(sid);
      else if (parts[2] === "performance") await viewPerformance(sid);
      else if (parts[2] === "leaderboards") await viewLeaderboards(sid);
      else if (parts[2] === "mods") await viewMods(sid);
      else await viewPlayers(sid);
    } else await viewHome();
  } catch (e) {
    setView(`<div class="empty"><h3>Something went wrong loading this page</h3><p>${esc(e.message)}</p><p style="margin-top:12px"><a href="#/">Back to servers</a></p></div>`);
    console.error(e);
  }
}
addEventListener("hashchange", () => { route(); view().focus({ preventScroll: true }); scrollTo(0, 0); });
document.addEventListener("DOMContentLoaded", async () => {
  $("#btn-notify")?.addEventListener("click", openNotifications);
  wireAccountMenu();
  const ch = $("#build-channel");
  if (ch && BUILD_CHANNEL === "beta") { ch.textContent = "Beta build"; ch.hidden = false; }
  try { signedIn((await api("/api/auth/me")).user); }
  catch { showLogin(); }
});
