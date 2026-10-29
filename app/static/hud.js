/* Solstone — small drawing helpers shared by the app and the public status page:
   HTML escaping, pixel hearts / hunger / XP bar, and Minecraft MOTD colours. */
"use strict";

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

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
  // Mods can raise max health a lot; past 20 hearts, scale to 20 and show the number.
  const label = `Health ${health} of ${max}`;
  let extra = "";
  if (max > 40) { extra = `<span class="hp-num">${Math.round(health)} / ${Math.round(max)}</span>`; health = (health / max) * 40; max = 40; }
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
  return `<div class="hud-row hearts" role="img" aria-label="${label}">${out}${extra}</div>`;
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


// ================================================================ leaderboard numbers
// One way to show a leaderboard value, used by the app and the status page alike.
function fmtStat(kind, v) {
  v = Number(v) || 0;
  const n = (x, d = 0) => new Intl.NumberFormat([], { maximumFractionDigits: d }).format(x);
  if (kind === "ticks") {
    const s = Math.floor(v / 20), d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : m ? `${m}m` : `${s}s`;
  }
  if (kind === "cm") { const m = v / 100; return m >= 1000 ? `${n(m / 1000, m >= 100000 ? 0 : 1)} km` : `${Math.round(m)} m`; }
  if (kind === "hearts") return `${n(v / 20)} ♥`;
  if (kind === "grams") {                         // a fish's weight: "0.16 oz", "5.3 oz", "3.4 lb", "1,298 lb" (as Tide+ shows it)
    const lb = v / 453.59237, oz = lb * 16;
    if (lb < 1) return oz < 1 ? `${Math.max(oz, 0.01).toFixed(2)} oz` : `${oz.toFixed(1)} oz`;
    return lb < 100 ? `${lb.toFixed(1)} lb` : `${n(lb)} lb`;
  }
  return n(v);
}

// ================================================================ player heads
// Heads are cut from the player's skin file: Solstone's own copy straight from Mojang
// first, with mc-heads (looked up by name) underneath as a backup. The face and the hat
// layer are separate layers of the same image; the initial shows if neither loads.
let skinSource = (p) => p.uuid ? `/api/skins/${String(p.uuid).replace(/-/g, "")}.png` : null;
const backupSkin = (p) => `https://mc-heads.net/skin/${p.name ? encodeURIComponent(p.name) : String(p.uuid || "").replace(/-/g, "")}`;
// name (lowercase) -> UUID for players Solstone knows; filled after sign-in so a head drawn
// from just a name still uses the real skin rather than a name lookup (Steve for unknown names).
const knownUuids = {};
function faceHtml(p, size, cls = "") {
  const initial = esc((String(p.name || "?").replace(/^\./, "") || "?")[0].toUpperCase());
  if (!p.uuid && p.name && knownUuids[String(p.name).toLowerCase()]) p = { ...p, uuid: knownUuids[String(p.name).toLowerCase()] };
  const main = skinSource(p);
  // Solstone's own copy when it has a UUID (no backup underneath: a by-name lookup often shows Steve first and
  // then flips to the real skin); the by-name service only for someone Solstone doesn't know.
  return `<span class="face ${cls}" style="--s:${size}px;--skin:${main ? `url('${main}')` : `url('${backupSkin(p)}')`};--skin2:none" aria-hidden="true"><span class="face-init">${initial}</span></span>`;
}

// An address on a home network (192.168.x.x, 10.x, localhost, *.local...): fine from the same Wi-Fi, but a public page
// that loads one makes the browser ask for access to the visitor's local network, and it can't reach it anyway.
function isHomeNetwork(url) {
  let h = "";
  try { h = new URL(url, location.href).hostname.toLowerCase(); } catch { return false; }
  return h === "localhost" || h.endsWith(".local") || h.endsWith(".lan") || h.endsWith(".home.arpa") || /^(127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h)
    || h === "[::1]" || /^\[f[cd]/.test(h);
}

// ================================================================ the top bar
// The same bar on every page: Home, News, Help, then (signed in) Events and Servers, and Manage for admins.
// Servers drops down a list of the servers you can see; with only one, it goes straight there.
function serversMenuHtml(servers, activeSid) {
  const icon = (s) => `<span class="server-icon">${s.has_icon ? `<img src="/api/servers/${encodeURIComponent(s.id)}/icon.png" alt="">` : esc((s.name || "?")[0])}<span class="status-dot ${s.crashed ? "crash" : s.running ? "on" : ""}"></span></span>`;
  return `<a class="rail-item rail-all" href="/app#/" ${activeSid === "" ? 'aria-current="page"' : ""}><span class="server-icon">▦</span><div><div class="name">All servers</div></div></a>` + servers.map((s) => {
    const sub = s.running === false ? "Offline" : s.online ? `${s.online.length} playing` : "";
    return `<a class="rail-item" href="/app#/s/${encodeURIComponent(s.id)}" ${s.id === activeSid ? 'aria-current="page"' : ""}>
      ${icon(s)}<div><div class="name">${esc(s.name)}</div><div class="sub">${esc(sub)}</div></div></a>`;
  }).join("");
}
function fillServersMenu(servers, activeSid = null) {
  const btn = document.getElementById("btn-servers"), panel = document.getElementById("rail-servers");
  if (!btn || !panel) return;
  btn._servers = servers;
  panel.innerHTML = servers.length > 1 ? serversMenuHtml(servers, activeSid) : "";
  btn.querySelector(".caret")?.toggleAttribute("hidden", servers.length < 2);
  btn.setAttribute("aria-haspopup", servers.length > 1 ? "true" : "false");
}
function wireServersMenu() {
  const btn = document.getElementById("btn-servers"), panel = document.getElementById("rail-servers");
  if (!btn || btn._wired) return;
  btn._wired = true;
  const set = (open) => { panel.hidden = !open; btn.setAttribute("aria-expanded", String(open)); };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const list = btn._servers || [];
    if (list.length === 1) { set(false); location.href = `/app#/s/${encodeURIComponent(list[0].id)}`; return; }
    set(panel.hidden);
  });
  document.addEventListener("click", (e) => { if (!panel.hidden && (!panel.contains(e.target) || e.target.closest("a[href]"))) set(false); });
  addEventListener("keydown", (e) => { if (e.key === "Escape") set(false); });
  addEventListener("hashchange", () => set(false));
}
// A menu that drops down under a button (the account menu).
function wireDropMenu(btn, menu) {
  document.body.append(menu);         // lives on <body>, placed under the button whenever it opens
  const place = () => {
    const r = btn.getBoundingClientRect(), mh = menu.offsetHeight, mw = menu.offsetWidth;
    const below = innerHeight - r.bottom, above = r.top;
    menu.style.left = `${Math.max(8, Math.min(r.right - mw, innerWidth - mw - 8))}px`;
    menu.style.top = below >= mh + 12 || below >= above ? `${r.bottom + 6}px` : `${Math.max(8, r.top - mh - 6)}px`;
  };
  const close = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  const open = () => { menu.hidden = false; place(); btn.setAttribute("aria-expanded", "true"); menu.querySelector("a, button")?.focus(); };
  btn.addEventListener("click", (e) => { e.stopPropagation(); menu.hidden ? open() : close(); });
  document.addEventListener("click", (e) => { if (!menu.contains(e.target) || e.target.closest("a[href]")) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { close(); btn.focus(); } });
  addEventListener("resize", close);
  addEventListener("scroll", close, { passive: true });
  return close;
}
// Signed in, the links for signed-in people (and admins) appear.
function showNavFor(user) {
  document.querySelectorAll("[data-signed-in]").forEach((el) => { el.hidden = !user; });
  document.querySelectorAll("[data-signed-out]").forEach((el) => { el.hidden = !!user; });
  document.querySelectorAll("[data-admin]").forEach((el) => { el.hidden = user?.role !== "admin"; });
  wireServersMenu();
}

// The website's pages when someone is signed in: the same bar as inside the app, and their name (with a
// menu: Fireworks, Sign out) where "Sign in" was, so the website and the servers feel like one site.
function showSignedIn() {
  fetch("/api/auth/me", { credentials: "same-origin" }).then((r) => (r.ok ? r.json() : null)).then((d) => {
    if (!d?.user) return;
    showNavFor(d.user);
    fetch("/api/servers", { credentials: "same-origin" }).then((r) => (r.ok ? r.json() : [])).then((list) => fillServersMenu(list)).catch(() => {});
    const b = document.getElementById("hp-signin");
    if (!b) return;
    const wrap = document.createElement("div");
    wrap.className = "account";
    wrap.innerHTML = `<button class="btn sm" id="hp-account" type="button" aria-haspopup="menu" aria-expanded="false">👤 ${esc(d.user.shown || d.user.username)}</button>
      <div class="account-menu" id="hp-account-menu" role="menu" hidden>
        <a role="menuitem" href="/app#/fireworks">🎆 Fireworks</a>
        <button type="button" role="menuitem" id="hp-logout">Sign out</button></div>`;
    b.replaceWith(wrap);
    const close = wireDropMenu(wrap.querySelector("#hp-account"), wrap.querySelector("#hp-account-menu"));
    document.getElementById("hp-logout").addEventListener("click", async () => {
      close();
      await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin", headers: { "X-Solstone": "1", "Content-Type": "application/json" }, body: "{}" }).catch(() => {});
      location.href = "/";
    });
  }).catch(() => {});
}
