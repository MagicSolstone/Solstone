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
// The server's own name (Website → Site details); Solstone itself only says so in small print.
const SITE_NAME = document.querySelector('meta[name="site-name"]')?.content || "Solstone";
const SITE_LOGO = document.querySelector('link[rel="icon"]')?.getAttribute("href") || "/static/solstone.svg";
const isAdmin = () => me.user?.role === "admin";
// Players (often signed up from the game) see the servers, who's on, leaderboards and their own page.
const isPlayer = () => me.user?.role === "player";
const isMine = (uuid) => !isPlayer() || (!!uuid && (me.user?.players || []).some((p) => String(uuid).replace(/-/g, "") === p.uuid.replace(/-/g, "")));
const ROLE_NAMES = [["player", "Player"], ["trusted", "Trusted"], ["admin", "Admin"]];
const PLAYER_HIDDEN = new Set(["world", "chat", "control", "check", "challenges"]);

function showLogin(message = "") {
  clearTimers?.();
  me.user = null;
  document.body.classList.add("logged-out");
  if (appSky.scene) { appSky.scene.stop(); appSky.bar?.remove(); appSky.scene = appSky.bar = null; }
  appSky.board?.remove(); appSky.board = null;
  const root = $("#login-root");
  root.hidden = false;
  root.innerHTML = `<canvas id="login-sky" aria-hidden="true"></canvas>
    <div class="login-wrap"><div id="login-board" class="board-stack" hidden></div><form class="login-card" id="login-form" autocomplete="on">
      <img src="${esc(SITE_LOGO)}" alt="" width="56" height="56">
      <div class="login-title"><h1>${esc(SITE_NAME)}</h1><p class="tagline" id="login-tagline">Sign in to see the servers</p></div>
      <label>Minecraft name or username<input class="input" name="username" autocomplete="username" autocapitalize="off" required></label>
      <label>Password<input class="input" type="password" name="password" autocomplete="current-password" required></label>
      <p class="login-error" role="alert">${esc(message)}</p>
      <button class="btn primary" type="submit">Sign in</button>
      <p class="login-alt"><span id="login-signup" hidden>New here? <button type="button" class="link-btn" id="btn-signup">Make an account</button> · </span><a href="/guides/join">How to join the server</a> · <a href="/">Home</a></p>
      <p class="login-made">Made with Solstone</p>
    </form><a class="login-status glass" id="login-status-link" href="/#live" hidden></a></div>`;
  const form = $("#login-form");
  form.querySelector("input").focus();
  fetch("/api/public/site").then((r) => r.json()).then((site) => {
    if (site.tagline) $("#login-tagline").textContent = site.tagline;
    $("#login-signup").hidden = !site.signup;
  }).catch(() => {});
  $("#btn-signup").addEventListener("click", openSignup);
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

// Making an account from the game: their Minecraft name, a code whispered to them in the game, then a login.
function openSignup() {
  let player = "";
  const step1 = () => `<h2>Make an account</h2>
    <p class="muted">You need to be playing on the server right now: we'll send a code to you in the game chat, so only you can see it.</p>
    <form id="su-start"><label>Your Minecraft name <small>As it shows in the game. On Bedrock (phone, tablet, console) it may start with a dot, like .Steve</small>
      <input class="input" name="player" required maxlength="18" autocapitalize="off" autocomplete="off" value="${esc(player)}"></label>
      <p class="login-error" role="alert"></p>
      <div class="actions"><button type="button" class="btn" data-close-modal>Cancel</button><button class="btn primary" type="submit">Send me a code</button></div></form>
    <p class="muted small" style="margin-top:12px">Not on the server yet? <a href="/guides/join">How to join</a></p>`;
  const step2 = (msg) => `<h2>Check the game chat</h2><p class="muted">${esc(msg)}</p>
    <form id="su-finish" autocomplete="off"><label>The six-digit code<input class="input" name="code" inputmode="numeric" maxlength="7" required autocomplete="one-time-code"></label>
      <p class="su-login">You'll sign in here with your Minecraft name, <b>${esc(player)}</b>, and the password you pick now.</p>
      <label>Pick a password <small>8 or more characters. Not the one for your Microsoft account.</small><input class="input" type="password" name="password" minlength="8" required autocomplete="new-password"></label>
      <label>Your first name <small>Optional. Only the admins see it, so they know who you are.</small><input class="input" name="real_name" maxlength="40" autocomplete="given-name"></label>
      <div class="su-bday"><span>Your birthday <small>Optional. You get a birthday banner and fireworks on the day.</small></span>
        <span class="su-bday-row"><select class="input sm" name="bmonth" aria-label="Birthday month"><option value="">Month</option>${["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"].map((m, i) => `<option value="${i + 1}">${m}</option>`).join("")}</select>
          <select class="input sm" name="bday" aria-label="Birthday day"><option value="">Day</option>${Array.from({ length: 31 }, (_, i) => `<option>${i + 1}</option>`).join("")}</select></span></div>
      <p class="login-error" role="alert"></p>
      <div class="actions"><button type="button" class="btn" id="su-back">Send a new code</button><button class="btn primary" type="submit">Make my account</button></div></form>`;
  openModal(step1(), (m) => {
    const wire1 = () => $("#su-start", m).addEventListener("submit", async (e) => {
      e.preventDefault();
      player = new FormData(e.target).get("player").trim();
      try { const r = await post("/api/public/signup/start", { player }); render2(r.message); }
      catch (err) { $(".login-error", e.target).textContent = err.message; }
    });
    const container = m;
    const render2 = (msg) => {
      container.innerHTML = step2(msg);
      $("#su-back", m).addEventListener("click", () => { container.innerHTML = step1(); wire1(); });
      $("#su-finish", m).addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = new FormData(e.target);
        try {
          const birthday = f.get("bmonth") && f.get("bday") ? { month: +f.get("bmonth"), day: +f.get("bday") } : null;
          const r = await post("/api/public/signup/finish", { player, code: f.get("code"), password: f.get("password"),
            real_name: f.get("real_name") || "", birthday });
          closeModal(); signedIn(r.user); showToast(`Welcome, ${esc(r.user.shown)}!`, 3000);
        } catch (err) { $(".login-error", e.target).textContent = err.message; }
      });
      $("#su-finish input", m).focus();
    };
    wire1();
  });
}

async function signedIn(user) {
  me.user = user;
  document.body.classList.remove("logged-out");
  document.body.classList.toggle("is-admin", user.role === "admin");
  showNavFor(user);
  stopLoginScene();
  clearInterval(state.loginRefresh);
  if (!appSky.scene && $("#app-sky")) {
    // A bright in-game day is dimmed behind the panels (but not when the page is hidden to watch).
    appSky.scene = startSkyScene($("#app-sky"), { auto: false, sound: (t, i) => FWAudio.play(t, i),
      dim: () => (document.body.classList.contains("ui-hidden") ? 0 : 0.5) });
    appSky.bar = startShowBar(appSky.scene, { key: "solstone-sky-app", defaultOn: true, hide: true, skyServer: () => curSid || "",
      onEvent: (item) => { if (item.text) showToast(`🎆 ${esc(item.text)}${item.server && item.server !== "Test" ? ` <span class="muted">· ${esc(item.server)}</span>` : ""}`, 4000); } });
  }
  const root = $("#login-root"); root.hidden = true; root.innerHTML = "";
  if (!appSky.board) appSky.board = startBoard($("#app-board"), { where: "app", sid: () => curSid || "", scene: () => appSky.scene, dismiss: true, max: innerWidth < 700 ? 1 : 2 });
  $("#account-name").textContent = user.shown || user.username;
  showAccountPlayers(user);
  fetch("/api/public/status").then((r) => r.json()).then((d) => { appBuild = d.build; }).catch(() => {});
  // Left open for a while? Say when Solstone has been updated (a reload loads it).
  clearInterval(state.buildCheck);
  state.buildCheck = setInterval(async () => {
    try { const d = await (await fetch("/api/public/status")).json(); if (appBuild && d.build && d.build !== appBuild) { showToast('Solstone has been updated. <a href="" data-reload>Reload to get the new version</a>', 0); clearInterval(state.buildCheck); } } catch { /* offline for a moment */ }
  }, 5 * 60 * 1000);
  // Pages that don't need the server list (Events, Fireworks, Manage) show without waiting for it.
  loadServers();
  route();
}

// The top bar (built in hud.js): which page you're on.
function wireMobileMenu() {
  wireServersMenu();
  addEventListener("hashchange", markNav);
  markNav();
}
function setManageNav(tab) {
  const nav = $("#manage-nav");
  if (!nav) return;
  nav.hidden = !tab || !isAdmin();
  nav.querySelectorAll("[data-m]").forEach((a) => a.toggleAttribute("aria-current", a.dataset.m === tab));
}
function markNav() {
  const h = location.hash || "#/";
  const on = h === "#/" || h.startsWith("#/s/") ? "servers" : h.startsWith("#/events") ? "events" : h.startsWith("#/manage") ? "manage" : "";
  document.querySelectorAll(".app-nav [data-nav]").forEach((el) => el.toggleAttribute("aria-current", el.dataset.nav === on));
}

function wireAccountMenu() {
  const close = wireDropMenu($("#btn-account"), $("#account-menu"));
  $("#btn-logout").addEventListener("click", async () => { close(); await post("/api/auth/logout").catch(() => {}); location.href = "/"; });   // signed out: back to the home page
  $("#btn-password").addEventListener("click", () => { close(); openPasswordChange(); });
  $("#btn-display-name").addEventListener("click", () => { close(); openDisplayName(); });
  $("#btn-my-players").addEventListener("click", () => { close(); openMyPlayers(); });
}

function showAccountPlayers(user) {
  const names = (user.players || []).map((p) => p.name).join(", ");
  $("#btn-account").title = [user.real_name, names && `In the game: ${names}`].filter(Boolean).join(" · ");
  $("#account-role").textContent = `${(ROLE_NAMES.find(([v]) => v === user.role) || [, "Signed in"])[1]} · signed in as ${user.username}`;
  $("#account-name").textContent = user.shown;
  // players are shown by their Minecraft name (picked in My Minecraft accounts), so no display name of their own
  const dn = $("#btn-display-name"); if (dn) dn.hidden = user.role === "player";
}

// Your Minecraft accounts: a Java one and a Bedrock one can both be yours, and you sign in with either name (one
// password). Linking one sends a code to that player in the game (only whoever is playing as them sees it), the
// same way as making an account. Players are shown on the site by the one marked main.
function openMyPlayers() {
  const list = () => {
    const ps = me.user.players || [];
    if (!ps.length) return `<p class="muted">No Minecraft account linked yet.</p>`;
    const main = (ps.find((p) => p.main) || ps[0]).uuid;
    return `<ul class="my-players">${ps.map((p) => `<li>${faceHtml({ name: p.name, uuid: p.uuid }, 24)} <b>${esc(p.name)}</b>${p.name.startsWith(".") ? ' <span class="chip">Bedrock</span>' : ' <span class="chip">Java</span>'}
        ${ps.length > 1 ? (p.uuid === main ? ' <span class="chip mp-main">⭐ Main</span>' : `<button class="btn sm" type="button" data-main="${esc(p.uuid)}">Make main</button>`) : ""}
        ${isPlayer() && ps.length <= 1 ? "" : `<button class="btn sm" type="button" data-unlink="${esc(p.uuid)}">Unlink</button>`}</li>`).join("")}</ul>
      <p class="muted small">You can sign in with ${ps.length > 1 ? "any of these names" : "this name"} and your one password.${isPlayer() && ps.length > 1 ? " On the website you're shown as your ⭐ main one." : ""}</p>`;
  };
  openModal(`<h2>My Minecraft accounts</h2>
    <div id="mp-list">${list()}</div>
    <form id="mp-form" class="mp-form"><h3>Link another</h3>
      <p class="muted small">Play on Java and Bedrock with different names? Link both, so your page and the servers you're on include each. Be in the game as that player, type the name here (Bedrock names start with a dot), and a code appears in your game chat.</p>
      <label>Name in the game<input class="input" name="player" maxlength="18" autocapitalize="off" required></label>
      <label id="mp-code-row" hidden>Code from the game chat<input class="input" name="code" inputmode="numeric" maxlength="7" autocomplete="one-time-code"></label>
      <p class="muted small" id="mp-msg" role="status"></p>
      <div class="actions"><button type="button" class="btn" data-close-modal>Close</button><button class="btn primary" type="submit" id="mp-go">Send me a code</button></div></form>`, (m) => {
    let sent = false;
    $("#mp-list", m).addEventListener("click", async (e) => {
      const mb = e.target.closest("[data-main]");
      if (mb) {
        try { const r = await post(`/api/auth/players/${encodeURIComponent(mb.dataset.main)}/main`, {}); me.user = r.user; showAccountPlayers(me.user); $("#mp-list", m).innerHTML = list(); showToast(`You're shown as ${esc(r.user.shown)}`, 2500); }
        catch (err) { showError(esc(err.message), 5000); }
        return;
      }
      const b = e.target.closest("[data-unlink]");
      if (!b) return;
      try { const r = await api(`/api/auth/players/${encodeURIComponent(b.dataset.unlink)}`, { method: "DELETE" }); me.user = r.user; showAccountPlayers(me.user); $("#mp-list", m).innerHTML = list(); }
      catch (err) { showError(esc(err.message), 5000); }
    });
    $("#mp-form", m).addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      try {
        if (!sent) {
          const r = await post("/api/auth/players/start", { player: f.get("player") });
          sent = true; $("#mp-code-row", m).hidden = false; $("#mp-go", m).textContent = "Link"; $("#mp-msg", m).textContent = r.message;
          e.target.code.required = true; e.target.code.focus();
        } else {
          const r = await post("/api/auth/players/finish", { player: f.get("player"), code: f.get("code") });
          me.user = r.user; showAccountPlayers(me.user); $("#mp-list", m).innerHTML = list();
          e.target.reset(); sent = false; $("#mp-code-row", m).hidden = true; $("#mp-go", m).textContent = "Send me a code"; $("#mp-msg", m).textContent = "";
          showToast("Linked", 2500); loadServers();
        }
      } catch (err) { showError(esc(err.message), 5000); }
    });
  });
}

// The name other people see in chat and the activity feed; the login name stays the same.
function openDisplayName() {
  const cur = me.user || {};
  openModal(`<h2>Display name</h2><form id="dn-form">
      <label>Name shown in chat and on the site <small>Your login stays <b>${esc(cur.username || "")}</b>. Leave empty to use it.</small>
        <input class="input" name="display_name" maxlength="24" value="${esc(cur.display_name || "")}" placeholder="${esc(cur.username || "")}" autocomplete="nickname"></label>
      <div class="actions"><button type="button" class="btn" data-close-modal>Cancel</button><button class="btn primary" type="submit">Save</button></div>
    </form>`, (m) => {
    $("#dn-form", m).addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const r = await post("/api/auth/profile", { display_name: new FormData(e.target).get("display_name") });
        me.user = r.user; $("#account-name").textContent = r.user.shown;
        closeModal(); showToast(`You're now shown as ${esc(r.user.shown)}`, 2500);
      } catch (err) { showError(esc(err.message), 4000); }
    });
  });
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
      catch (err) { showError(esc(err.message), 4000); }
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
// What an item does: its in-game tooltip when the server can tell us, otherwise the language files' description.
async function describeItem(sid, id) {
  state.itemDesc ||= {};
  const key = `${sid}|${id}`;
  if (state.itemDesc[key]) return state.itemDesc[key];
  const d = await api(`/api/servers/${encodeURIComponent(sid)}/assets/describe?item=${encodeURIComponent(id)}`).catch(() => ({ lines: [], source: "none" }));
  const srv = (state.servers || []).find((s) => s.id === sid);
  d.offline = d.source !== "game" && srv?.running === false;
  if (d.offline) d.why = "";
  if (d.source === "game") state.itemDesc[key] = d;      // keep live answers for the session
  return d;
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
      pk.innerHTML = `${itemIcon({ id: x.id })}<div class="gv-pick-text"><b>${esc(x.name)}</b><div class="muted small">${esc(x.id)}</div><div class="gv-desc" aria-live="polite"></div></div>`;
      describeItem(sid, x.id).then((d) => {
        if (pick?.id !== x.id) return;                       // picked something else meanwhile
        const box = $(".gv-desc", pk);
        box.innerHTML = d.lines.length
          ? `<div class="mc-tip">${d.lines.map((l) => `<div style="color:${esc(l.color)}">${esc(l.text)}</div>`).join("")}</div>`
          : `<div class="muted small">${d.offline ? "Start the server to see what this does." : "No description for this item."}</div>`;
        if (d.why) box.insertAdjacentHTML("beforeend", `<div class="muted small gv-why">${esc(d.why)}</div>`);
      });
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
      } catch (err) { showError(esc(err.message), 6000); }
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
// A message at the top of the page. kind "warn" (something went wrong, or needs attention) stands out in orange
// and stays up a little longer; the others are the everyday "Saved" kind.
function showToast(msg, ms = 0, kind = "") {
  const t = $("#toast"); t.innerHTML = msg; t.hidden = false;
  t.classList.toggle("warn", kind === "warn");
  t.classList.remove("pop"); void t.offsetWidth; t.classList.add("pop");     // a little bounce each time, so it's noticed
  clearTimeout(toastTimer); if (ms) toastTimer = setTimeout(hideToast, ms);
}
function showError(msg, ms = 6000) { showToast(`⚠️ ${msg}`, Math.max(ms, 5000), "warn"); }
function hideToast() { $("#toast").hidden = true; }

// ================================================================ rail
function serverIconHtml(s, withDot = true) {
  const dot = withDot ? `<span class="status-dot ${s.crashed ? "crash" : s.running ? "on" : ""}"></span>` : "";
  const inner = s.has_icon ? `<img src="/api/servers/${encodeURIComponent(s.id)}/icon.png" alt="">` : esc((s.name || "?")[0]);
  return `<span class="server-icon">${inner}${dot}</span>`;
}
// One request at a time: callers at the same moment share it.
function loadServers() {
  return (state.serversLoading ||= fetchServers().finally(() => { state.serversLoading = null; }));
}
async function fetchServers() {
  const uuids = api("/api/players/uuids").then((m) => Object.assign(knownUuids, m)).catch(() => null);
  try { state.servers = await api("/api/servers"); } catch (e) { state.servers = state.servers || []; }
  await uuids;
  fillServersMenu(state.servers, curSid);
  setRailTitle();
}
function setRailTitle() {
  const t = $("#rail-title");
  if (t) t.textContent = state.servers.find((x) => x.id === curSid)?.name || SITE_NAME;
}

// ================================================================ views
const view = () => $("#view");
function setView(html) { state.items.clear(); hideTip(); view().innerHTML = html; }

async function viewHome() {
  curSid = null;
  document.title = SITE_NAME;
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
  // Sections in groups: the everyday ones on their own, the extras under Play, the running of it under Server.
  // The group you're in shows its own row of tabs underneath.
  const groups = [
    ["overview", "Overview", [["overview", "Overview", base]]],
    ...(java ? [...(isPlayer() && !s.player_map ? [] : [["world", "World", [["world", "World", `${base}/world`]]]]),
      ["leaderboards", "Leaderboards", [["leaderboards", "Leaderboards", `${base}/leaderboards`]]],
      ["play", "Play", [...(s.fishing ? [["fishing", "Fishing", `${base}/fishing`]] : []), ["adventures", "Adventures", `${base}/adventures`],
        ...(isAdmin() ? [["challenges", "Challenges", `${base}/challenges`]] : [])]]] : []),
    ["server", "Server", [["performance", "Performance", `${base}/performance`], ...(java ? [["mods", "Mods", `${base}/mods`], ...(isPlayer() ? [] : [["chat", "Chat", `${base}/chat`]])] : []),
      ...(isAdmin() ? [["control", "Control", `${base}/control`]] : []), ...(isAdmin() && java ? [["check", "Check", `${base}/check`]] : [])]],
  ].filter(([, , items]) => items.length);
  const inGroup = groups.find(([, , items]) => items.some(([k]) => k === tab));
  if (inGroup && inGroup[2].length > 1) { try { localStorage.setItem(`solstone-tab-${inGroup[0]}`, tab); } catch { /* private window */ } }
  const groupHref = ([g, , items]) => {
    let last = null;
    try { last = localStorage.getItem(`solstone-tab-${g}`); } catch { /* private window */ }
    return (items.find(([k]) => k === last) || items[0])[2];
  };
  const tabsHtml = `<nav class="tabs" aria-label="Server sections">${groups.map((gr) => `<a href="${groupHref(gr)}" ${gr === inGroup ? 'aria-current="page"' : ""}>${gr[1]}${gr[2].length > 1 ? ' <span class="tab-more" aria-hidden="true">▾</span>' : ""}</a>`).join("")}</nav>
    ${inGroup && inGroup[2].length > 1 ? `<nav class="subtabs" aria-label="${esc(inGroup[1])}">${inGroup[2].map(([k, label, href]) => `<a href="${href}" ${k === tab ? 'aria-current="page"' : ""}>${label}</a>`).join("")}</nav>` : ""}`;
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
    ${tabsHtml}`;
}

async function serverFrame(sid, tab) {
  curSid = sid;
  if (!state.servers.find((s) => s.id === sid)) await loadServers();
  else fillServersMenu(state.servers, sid);
  setRailTitle();
  const s = await api(`/api/servers/${encodeURIComponent(sid)}`);
  const idx = state.servers.findIndex((x) => x.id === sid);
  if (idx >= 0) state.servers[idx] = s;
  document.title = `${s.name} · ${SITE_NAME}`;
  if (!s.game || s.game === "minecraft-java") ensureServerAssets(sid);
  if (!state.lang[sid]) await api(`/api/servers/${sid}/assets/lang`).then((l) => (state.lang[sid] = l)).catch(() => {});
  return s;
}
function wireHeader(s) {
  // phones: the section tabs scroll sideways; keep the one you're on in view
  const cur = document.querySelector(".server-head ~ .tabs a[aria-current], .tabs a[aria-current]");
  if (cur && innerWidth < 900) cur.scrollIntoView({ inline: "center", block: "nearest" });
  $("#btn-settings")?.addEventListener("click", () => openSettings(s));
}

// ---------------------------------------------------------------- overview tab
// Players down the side, play time and the activity timeline in the main column.
function playerRow(p) {
  const href = p.uuid && isMine(p.uuid) ? `#/s/${encodeURIComponent(curSid)}/p/${p.uuid}` : null;
  const h = p.headline || {};
  const sub = p.online
    ? `<span class="live-tag"><span class="status-dot on"></span>Playing</span>${p.dimension ? `<span>${esc(dimName(p.dimension))}</span>` : ""}`
    : `<span>Last seen ${esc(fmtAgo(p.last_seen))}</span>${p.removed ? '<span class="chip" title="Not on the whitelist any more">Removed</span>' : ""}`;
  const vitals = p.online && p.health != null
    ? `<span title="Health">❤ ${p.health}</span>${p.food != null ? `<span title="Hunger">🍗 ${p.food}</span>` : ""}`
    : "";
  const inner = `${headHtml(p, 40)}
    <div class="pr-main"><div class="pr-name">${esc(p.name)}${p.xp_level != null ? `<span class="lvl" title="Level">${p.xp_level}</span>` : ""}${p.op ? '<span class="op-badge">OP</span>' : ""}</div>
      <div class="pr-sub">${sub}${vitals}</div></div>`;
  const cls = `pl-row ${p.online ? "is-online" : ""}`;
  return href ? `<a class="${cls}" href="${href}">${inner}</a>` : `<div class="${cls}">${inner}</div>`;
}
function playersListHtml(data) {
  const on = data.players.filter((p) => p.online), off = data.players.filter((p) => !p.online);
  if (!data.players.length) return `<div class="empty"><h3>Nobody has joined yet</h3><p>Players appear here after their first visit.</p></div>`;
  return `${on.length ? `<div class="pl-group"><div class="pl-label">Playing now · ${on.length}</div>${on.map(playerRow).join("")}</div>` : `<p class="muted pl-none">Nobody is playing right now.</p>`}
    ${off.length ? `<div class="pl-group"><div class="pl-label">${on.length ? "Everyone else" : "Players"}</div>${off.map(playerRow).join("")}</div>` : ""}`;
}
// Players taken off the whitelist are left out; admins can show them again for a look (?removed=1).
let showRemoved = false;
const removedNote = (d) => d.removed_count ? `<p class="muted small pl-removed">${d.removed_count} no longer on the whitelist (left out of lists and leaderboards).
  <button type="button" class="link-btn" data-show-removed>${showRemoved ? "Hide them" : "Show them"}</button></p>` : "";
async function viewOverview(sid) {
  const s = await serverFrame(sid, "overview");
  const playersUrl = () => `/api/servers/${sid}/players${showRemoved ? "?removed=1" : ""}`;
  const data = await api(playersUrl());
  setView(serverHeader(s, "overview") + `<div class="overview">
      <aside class="ov-side" aria-label="Players"><div class="section-head"><h2>Players</h2><span class="muted">${data.players.length} joined</span></div>
        <div id="players-body">${playersListHtml(data)}${removedNote(data)}</div></aside>
      <div class="ov-main">${isPlayer() ? '<div id="ov-glance"></div>' : ""}<section class="rc-wrap" id="ov-recap" aria-label="Daily recap"></section><div id="ov-activity"></div></div></div>`);
  wireHeader(s);
  const refreshRecap = mountRecap($("#ov-recap"), sid);
  // Players get the server at a glance (now, the world, coming up, themselves) and who played which days;
  // everyone else the full activity.
  const refreshActivity = isPlayer() ? mountPlayerGlance($("#ov-glance"), $("#ov-activity"), s, data) : mountActivity($("#ov-activity"), sid, data.players.map((p) => p.name));
  const repaint = async () => {
    const d = await api(playersUrl()).catch(() => null);
    if (d && $("#players-body")) $("#players-body").innerHTML = playersListHtml(d) + removedNote(d);
  };
  $("#players-body").addEventListener("click", (e) => { if (e.target.closest("[data-show-removed]")) { showRemoved = !showRemoved; repaint(); } });
  every(10000, repaint);
  every(30000, refreshActivity);
  every(120000, refreshRecap);
}

// The overview for a Player account: a few cards about the server right now, then who played which days.
function mountPlayerGlance(el, daysEl, s, data) {
  const sid = s.id;
  const mine = data.players.find((p) => isMine(p.uuid));
  const phase = (t) => (t < 6000 ? "Morning" : t < 12000 ? "Afternoon" : t < 13000 ? "Sunset" : t < 23000 ? "Night" : "Sunrise");
  const tps = s.perf?.tps;
  const load = async () => {
    const [sky, up] = await Promise.all([fetch(`/api/public/sky?sid=${encodeURIComponent(sid)}`).then((r) => r.json()).catch(() => null),
      api("/api/upcoming").catch(() => ({ items: [] }))]);
    if (!el.isConnected) return;
    const world = sky?.mode === "game" && sky.server === sid
      ? `<b>Day ${esc(sky.day)}</b><span>${esc(phase(sky.time_of_day))} · ${sky.thundering ? "Thunderstorm" : sky.raining ? "Raining" : "Clear"}</span>` : `<b>—</b><span>The world's time shows while it's running</span>`;
    const next = (up.items || []).filter((x) => !x.server || x.server === s.name).slice(0, 3);
    el.innerHTML = `<div class="glance">
      <div class="glance-card"><small>Server</small><b>${s.running === false ? "Offline" : `${s.online?.length || 0} of ${s.max_players ?? "?"} playing`}</b>
        <span>${esc([s.version && `Minecraft ${s.version}`, s.loader].filter(Boolean).join(" · "))}</span>
        ${tps != null && s.running ? `<span>${tps >= 19 ? "🟢 Running smoothly" : tps >= 15 ? "🟡 A little slow" : "🔴 Lagging"} (${esc(tps.toFixed(1))} TPS)</span>` : ""}</div>
      <div class="glance-card"><small>In the world</small>${world}</div>
      ${mine ? `<a class="glance-card glance-me" href="#/s/${encodeURIComponent(sid)}/p/${mine.uuid}"><small>You</small>
        <b>${headHtml(mine, 28)} ${esc(mine.name)}${mine.xp_level != null ? ` <span class="lvl">${mine.xp_level}</span>` : ""}</b>
        <span>${mine.online ? "Playing now" : `Last seen ${esc(fmtAgo(mine.last_seen))}`} · your inventory${s.fishing ? ", stats and fishing" : " and stats"} →</span></a>` : ""}
      <div class="glance-card"><small>Events</small>${next.length ? next.map((x) => `<span>${esc(x.emoji || "")} <b>${esc(x.title)}</b> ${x.live ? "· on now" : `· ${esc(new Date(x.at * 1000).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }))}${x.time ? ` ${esc(x.time)}` : ""}`}</span>`).join("")
        : "<span>Nothing planned yet</span>"}<a class="glance-more" href="#/events">All of it →</a></div>
    </div>`;
  };
  const loadDays = async () => {
    const a = await api(`/api/servers/${encodeURIComponent(sid)}/activity?days=14`).catch(() => null);
    if (!a || !daysEl.isConnected) return;
    const names = [...new Set(a.daily.flatMap((d) => Object.keys(d.players)))].sort((x, y) => x.localeCompare(y));
    daysEl.innerHTML = `<section class="section"><div class="section-head"><h2>Who played</h2><span class="muted">The last two weeks</span></div>
      <div class="panel"><div class="chart" id="days-chart"></div></div></section>`;
    renderDaysPlayed($("#days-chart", daysEl), a.daily, names);
  };
  load(); loadDays();
  return () => { load(); loadDays(); };
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
  const tabs = [["inventory", "Inventory"], ["history", "Play history"], ["stats", "Statistics"], ["advancements", "Advancements"],
    ...(s.fishing ? [["fishing", "Fishing"]] : [])];
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
    else if (tab === "fishing") renderPlayerFishing(el, sid, p);
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
    } catch (err) { showError(esc(err.message), 5000); }
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
  const body = p.uuid ? `<img src="/api/skins/${p.uuid.replace(/-/g, "")}/body.png?size=256" alt="${esc(p.name)}'s skin" data-fail="letter" data-letter="${esc(p.name[0])}">` : "";
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
        ${fishingChip(p)}
        ${effects}
      </div>
      ${giveBtn(p)}
    </div></div>`;
}

// The Tide fishing mod: level and title, a link to their fishing journal, more on hover.
function fishingChip(p) {
  const f = p.fishing;
  if (!f) return "";
  const tip = `${f.xp.toLocaleString()} fishing XP · ${f.species}/${f.species_total} kinds of fish · ${f.caught.toLocaleString()} caught${f.biggest ? ` · biggest: ${f.biggest.name}, ${fmtStat("grams", f.biggest.weight_g)}` : ""}`;
  return `<a class="chip chip-link" href="#/s/${encodeURIComponent(curSid)}/fishing/${encodeURIComponent(p.name)}" title="${esc(tip)}">🎣 Fishing <b>Lv ${f.level}</b> ${esc(f.title)}</a>`;
}

function statStrip(p) {
  const h = p.headline || {};
  const cells = [
    ...(typeof h.play_time === "number" ? [[fmtDuration(h.play_time), "Time played"]] : []),     // admins only
    [fmtNum(h.mob_kills), "Mobs defeated"], [fmtNum(h.deaths), "Deaths"],
    [fmtNum(h.blocks_mined), "Blocks mined"], [fmtDistance(h.distance_cm), "Distance travelled"], [fmtNum(h.items_crafted), "Items crafted"],
  ];
  return `<div class="stat-strip">${cells.map(([v, k]) => `<div><div class="v">${esc(v)}</div><div class="k">${esc(k)}</div></div>`).join("")}</div>`;
}

function inventoryHtml(p) {
  const d = p.data;
  if (!d) return `<div class="empty"><h3>No inventory saved yet</h3><p>Minecraft writes player data when the world saves or the player logs out.</p></div>`;
  const inv = d.inventory;
  const body = p.uuid ? `<img src="/api/skins/${p.uuid.replace(/-/g, "")}/body.png?size=160" alt="" data-fail="remove">` : "";
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
  // Boards nobody has scored on yet are left out. Medals: 1st, 2nd and 3rd on each board (equal scores share a place).
  const medals = {};
  let showEmpty = true;
  try { showEmpty = localStorage.getItem("solstone-lb-empty") !== "0"; } catch { /* private window */ }
  const TIDE_ONLY = new Set(["fishing_level", "heaviest_fish"]);          // meaningless without the fishing mod
  const boardHtml = ({ key: k, title, kind, medals: counts }) => {
    const rows = data.players.filter((r) => r[k] > 0).sort((a, b) => b[k] - a[k]);
    if (!rows.length) return showEmpty && (s.fishing || !TIDE_ONLY.has(k)) ? `<div class="board empty-board"><h3>${esc(title)}</h3><p class="muted small">Nobody yet. Be the first!</p></div>` : "";
    if (counts !== false) {
      const values = [...new Set(rows.map((r) => r[k]))];
      rows.forEach((r) => { const place = values.indexOf(r[k]); if (place < 3) { const m = (medals[r.uuid] ||= { r, n: [0, 0, 0] }); m.n[place] += 1; } });
    }
    const top = rows.slice(0, 8), max = top[0][k];
    return `<div class="board"><h3>${esc(title)}</h3><ol>${top.map((r, i) => `<li>
      <span class="rank">${i + 1}</span>${miniHead(r)}<a href="#/s/${encodeURIComponent(sid)}/p/${r.uuid}">${esc(r.name)}</a><span class="val">${esc(fmtStat(kind, r[k]))}</span>
      <span></span><span></span><div class="bar-bg"><span style="width:${(r[k] / max) * 100}%"></span></div></li>`).join("")}</ol></div>`;
  };
  const groups = (data.groups || ["More"]).map((g) => {
    const html = (data.boards || []).filter((b) => (b.group || "More") === g).map(boardHtml).join("");
    return html ? `<section class="board-group" id="lb-${esc(g.replace(/\W+/g, "-").toLowerCase())}"><h2>${esc(g)}</h2><div class="boards">${html}</div></section>` : "";
  }).filter(Boolean);
  const ranked = Object.values(medals).sort((a, b) => b.n[0] - a.n[0] || b.n[1] - a.n[1] || b.n[2] - a.n[2] || a.r.name.localeCompare(b.r.name));
  const medalRow = (m, i) => `<li><span class="rank">${i + 1}</span>${miniHead(m.r)}<a href="#/s/${encodeURIComponent(sid)}/p/${m.r.uuid}">${esc(m.r.name)}</a>
      <span class="medals">${m.n[0] ? `<span title="1st places">🥇 ${m.n[0]}</span>` : ""}${m.n[1] ? `<span title="2nd places">🥈 ${m.n[1]}</span>` : ""}${m.n[2] ? `<span title="3rd places">🥉 ${m.n[2]}</span>` : ""}</span></li>`;
  const medalHtml = ranked.length > 1 ? `<section class="board-group medal-table"><h2>Most medals</h2><p class="muted small">1st, 2nd and 3rd places across every leaderboard below.</p>
      <ol class="medal-list">${ranked.slice(0, 5).map(medalRow).join("")}</ol>
      ${ranked.length > 5 ? `<details><summary>Everyone (${ranked.length})</summary><ol class="medal-list" start="6">${ranked.slice(5).map((m, i) => medalRow(m, i + 5)).join("")}</ol></details>` : ""}</section>` : "";
  const jump = groups.length > 1 ? `<nav class="chips board-jump" aria-label="Jump to">${(data.groups || []).filter((g) => groups.some((h) => h.includes(`<h2>${esc(g)}</h2>`))).map((g) => `<a class="chip" href="#" data-jump="lb-${esc(g.replace(/\W+/g, "-").toLowerCase())}">${esc(g)}</a>`).join("")}</nav>` : "";
  const toggle = `<label class="check lb-empty-toggle"><input type="checkbox" id="lb-empty" ${showEmpty ? "checked" : ""}> Show boards nobody has scored on yet</label>`;
  setView(serverHeader(s, "leaderboards") + (groups.length ? `${medalHtml}${jump}${toggle}${groups.join("")}` : `<div class="empty"><h3>No scores yet</h3><p>Leaderboards appear once players have some statistics.</p></div>`));
  wireHeader(s);
  $("#lb-empty")?.addEventListener("change", (e) => { try { localStorage.setItem("solstone-lb-empty", e.target.checked ? "1" : "0"); } catch { /* fine */ } viewLeaderboards(sid); });
  $$("[data-jump]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); document.getElementById(a.dataset.jump)?.scrollIntoView({ behavior: "smooth" }); }));
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
  let located = pl.players.filter((p) => p.position);
  // Two maps: Solstone's own (drawn from the world files, with everyone's last spot) and a web map (BlueMap...) if set
  // The web map's frame goes in only when it's picked (a hidden frame still loads, and one at a home-network
  // address makes the browser ask for local network access); from outside the home, a home address can't load at all.
  // Through Solstone (map_proxy): a sandboxed frame with a pass in its address (webmap.py), from anywhere.
  const hasWeb = !!(s.map_url || s.map_proxy);
  const webMap = () => s.map_proxy ? '<div id="wm-proxy"><p class="muted">Opening the map…</p></div>'
    : s.map_url
    ? isHomeNetwork(s.map_url) && !isHomeNetwork(location.href)
      ? `<div class="empty"><p>This map is at a home-network address (<code>${esc(s.map_url)}</code>), so it only opens on the same Wi-Fi as the server. <a href="${esc(s.map_url)}" target="_blank" rel="noopener">Open it</a></p>${isAdmin() ? `<p class="muted small">To show it to everyone, give it a public address (a Cloudflare tunnel to it, for example) in this server's ⚙ settings.</p>` : ""}</div>`
      : `<iframe class="map-frame" src="${esc(s.map_url)}" title="World map" loading="lazy"></iframe><p class="muted" style="margin-top:8px;font-size:.9rem"><a href="${esc(s.map_url)}" target="_blank" rel="noopener">Open the map full screen</a></p>`
    : isPlayer() ? "" : `<div class="empty"><h3>Add a 3D web map too</h3><p>Install the <b>BlueMap</b> or <b>squaremap</b> Fabric mod on this server, then paste its web address (for example <code>http://your-server:8100</code>) in server settings. It shows here beside the top-down map.</p><p style="margin-top:12px"><button class="btn primary" id="btn-map">Add map address</button></p></div>`;
  const DIM_ORDER = ["minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"];
  const mapDims = w.dimensions.filter((d) => d.chunks > 0).map((d) => d.id)
    .sort((a, b) => ((DIM_ORDER.indexOf(a) + 1 || 9) - (DIM_ORDER.indexOf(b) + 1 || 9)));
  let pick = "own";
  try { if (localStorage.getItem("solstone-world-map") === "web" && hasWeb) pick = "web"; } catch { /* private window */ }
  const map = `<div class="world-map-pick">${isPlayer() && !hasWeb ? "" : `<span class="seg" role="group" aria-label="Which map"><button type="button" data-wm="own" aria-pressed="${pick === "own"}">🗺️ Top-down map</button><button type="button" data-wm="web" aria-pressed="${pick === "web"}">${hasWeb ? "🧊 Web map" : "＋ Web map"}</button></span>`}
      ${mapDims.length > 1 ? `<select class="input sm" id="wm-dim" aria-label="Dimension">${mapDims.map((d) => `<option value="${esc(d)}">${esc(dimName(d))}</option>`).join("")}</select>` : ""}</div>
    <div id="wm-own" class="world-own-map" ${pick === "own" ? "" : "hidden"}></div><div id="wm-web" ${pick === "web" ? "" : "hidden"}>${pick === "web" ? webMap() : ""}</div>`;
  setView(serverHeader(s, "world") + `
    <div class="world-top"><div id="world-sky" class="world-sky">${skyHtml(w)}</div>
      <div class="panel"><dl class="kv">
        <dt>World</dt><dd>${esc(w.level_name)}</dd>
        ${isPlayer() ? "" : `<dt>Seed</dt><dd>${w.seed ? `<span class="num">${esc(w.seed)}</span><button class="copy" data-copy="${esc(w.seed)}">Copy</button>` : "Unknown"}</dd>`}
        <dt>Difficulty</dt><dd>${esc(humanize(w.difficulty || "?"))}${w.hardcore ? " · Hardcore" : ""}</dd>
        <dt>Game mode</dt><dd>${esc(humanize(w.default_gamemode))}</dd>
        <dt>World spawn</dt><dd>${w.spawn ? `<span class="num">${w.spawn.x}, ${w.spawn.y}, ${w.spawn.z}</span>` : "Unknown"}</dd>
        <dt>Total ticks</dt><dd>${fmtDuration(w.game_time)} of world time</dd>
      </dl></div></div>
    <section class="section"><div class="section-head"><h2>Map</h2></div>${map}</section>
    <section class="section"><div class="section-head"><h2>Where everyone is</h2><span class="muted">Live for players online with RCON, otherwise from their last save</span></div>
      ${located.length ? `<div class="where">${located.map((p) => `<a class="where-row" ${!isPlayer() || isMine(p.uuid) ? `href="#/s/${encodeURIComponent(sid)}/p/${p.uuid}"` : ""}>${miniHead(p, 32)}
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
  // Solstone's own map, centred on whoever's around, with everyone's (last) spot
  let ownMap = null;
  // Each player's face (with the hat layer), cut from their skin, drawn where they are.
  const heads = {};
  const headOf = (p) => {
    if (heads[p.name]) return heads[p.name];
    const img = new Image();
    img.onload = () => ownMap?.draw();
    img.onerror = () => { if (img.src !== backupSkin(p)) img.src = backupSkin(p); };
    img.src = skinSource(p) || backupSkin(p);
    return (heads[p.name] = img);
  };
  const mountOwn = (dim) => {
    const hereNow = () => located.filter((p) => (p.position.dimension || "minecraft:overworld") === dim);
    const here = hereNow();
    const c = here[0]?.position || (dim === "minecraft:overworld" && w.spawn) || { x: 0, z: 0 };
    ownMap = worldMapCanvas($("#wm-own"), sid, { dim, center: { x: c.x, z: c.z }, scale: 1,
      overlay: (ctx, toScreen) => {
        if (dim === "minecraft:overworld" && w.spawn) {
          const [x, y] = toScreen(w.spawn.x, w.spawn.z);
          ctx.fillStyle = "#f2c14e"; ctx.save(); ctx.translate(x, y); ctx.rotate(Math.PI / 4); ctx.fillRect(-5, -5, 10, 10); ctx.restore();
        }
        for (const p of hereNow()) {
          const [x, y] = toScreen(p.position.x, p.position.z), sz = 22, img = headOf(p);
          ctx.globalAlpha = p.online ? 1 : 0.6;                  // not on now: a faded head where they left
          ctx.fillStyle = p.online ? "#fff" : "rgba(200,210,230,.8)"; ctx.fillRect(x - sz / 2 - 2, y - sz / 2 - 2, sz + 4, sz + 4);
          if (img.complete && img.naturalWidth >= 64) {
            ctx.imageSmoothingEnabled = false;
            ctx.drawImage(img, 8, 8, 8, 8, x - sz / 2, y - sz / 2, sz, sz);
            ctx.drawImage(img, 40, 8, 8, 8, x - sz / 2, y - sz / 2, sz, sz);
          } else { ctx.fillStyle = "#4d74d6"; ctx.fillRect(x - sz / 2, y - sz / 2, sz, sz); }
          ctx.globalAlpha = 1;
          ctx.font = "bold 12px system-ui"; ctx.lineWidth = 3; ctx.strokeStyle = "rgba(0,0,0,.8)"; ctx.fillStyle = "#fff";
          const label = p.online ? p.name : `${p.name} · ${fmtAgo(p.last_seen)}`;
          ctx.strokeText(label, x + sz / 2 + 6, y + 4); ctx.fillText(label, x + sz / 2 + 6, y + 4);
        }
      } });
    if (here.length > 1) ownMap.fit(here.map((p) => ({ x: p.position.x, z: p.position.z })));
  };
  if (pick === "own") mountOwn(mapDims[0] || "minecraft:overworld");
  const openProxied = async () => {
    const box = $("#wm-proxy");
    if (!box) return;
    try {
      const { url } = await api(`/api/servers/${encodeURIComponent(sid)}/webmap`);
      box.innerHTML = `<iframe class="map-frame" src="${esc(url)}" title="World map" sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox allow-downloads" referrerpolicy="no-referrer"></iframe>
        <p class="muted" style="margin-top:8px;font-size:.9rem"><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open the map full screen</a></p>`;
    } catch (err) { box.innerHTML = `<div class="empty"><p>The web map couldn't be opened: ${esc(err.message)}</p></div>`; }
  };
  if (pick === "web") openProxied();
  $("#wm-dim")?.addEventListener("change", (e) => mountOwn(e.target.value));
  document.querySelectorAll("[data-wm]").forEach((b) => b.addEventListener("click", () => {
    const which = b.dataset.wm;
    try { localStorage.setItem("solstone-world-map", which); } catch { /* private window */ }
    document.querySelectorAll("[data-wm]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    $("#wm-own").hidden = which !== "own"; $("#wm-web").hidden = which !== "web";
    if (which === "web" && !$("#wm-web").innerHTML) { $("#wm-web").innerHTML = webMap(); $("#btn-map")?.addEventListener("click", () => openSettings(s)); openProxied(); }
    if (which === "own" && !ownMap) mountOwn($("#wm-dim")?.value || mapDims[0] || "minecraft:overworld");
  }));
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
  // Where everyone is, live: every few seconds while the page is open (the map keeps where you've moved it to).
  every(5000, async () => {
    if (document.hidden) return;
    const np = await api(`/api/servers/${sid}/players`).catch(() => null);
    if (!np) return;
    located = np.players.filter((p) => p.position);
    ownMap?.draw();
  });
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
  const listHtml = `<div class="section-head"><h2>${data.mods.length} ${data.mods.length === 1 ? "mod" : "mods"}</h2><span class="muted">${esc(data.loader)}</span></div>` +
    (data.mods.length ? `${isAdmin() ? `<div class="mod-updates" id="mod-updates"><span class="muted small">Checking Modrinth for updates…</span></div>` : ""}<div class="mods">${data.mods.map((m) => `<div class="mod" data-file="${esc(m.file)}"><div class="mn"><span>${esc(m.name)}</span><span class="mv">${esc(m.version || "")}</span></div>${m.description ? `<p>${esc(m.description)}</p>` : ""}</div>`).join("")}</div>`
      : `<div class="empty"><h3>No mods installed</h3><p>This server runs ${esc(data.loader)} without a mods folder.</p></div>`);
  if (!isAdmin() || !data.mods.length) { setView(serverHeader(s, "mods") + listHtml); wireHeader(s); return; }
  let pack = await api(`/api/servers/${encodeURIComponent(sid)}/modpack`).catch(() => null);
  const base = `/api/servers/${encodeURIComponent(sid)}/modpack`;
  const KIND = { mod: "Mod", resourcepack: "Resource pack", shader: "Shader" };
  let hits = [], kind = "mod", note = "";
  const packHtml = () => {
    if (!pack) return "";
    const setup = pack.enabled ? `<ol class="pk-steps">
        <li>In Prism, right-click the instance → <b>Folder</b>, and open the <code>minecraft</code> folder inside it. Put <a href="${esc(pack.bootstrap)}" download>packwiz-installer-bootstrap.jar</a> there. Move any mods the pack provides out of its <code>mods</code> folder (the pack puts them back; two copies of a mod won't start).</li>
        <li>Right-click the instance → <b>Edit</b> → <b>Settings</b> → <b>Custom commands</b>, tick it, and paste this as the <b>Pre-launch command</b>:
          <div class="pk-copy"><code id="pk-cmd">${esc(pack.command)}</code><button class="btn sm" type="button" data-copy="pk-cmd">Copy</button></div></li>
        <li>Launch. A small window checks the pack and downloads what changed, every time it starts.</li></ol>
        <p class="muted small">Pack address: <code>${esc(pack.url)}</code> · Anyone with this address can download the pack's mods. <button class="linkish" type="button" data-newtoken>Make a new address</button></p>` : "";
    const sm = pack.server_mods.filter((m) => !m.server_only);
    return `<section class="section panel pk">
      <div class="section-head"><h2>📦 Modpack</h2></div>
      <p class="muted">The mods players need, for Minecraft ${esc(pack.mc || "?")}${pack.loader ? ` with Fabric Loader ${esc(pack.loader)}` : ""}: this server's own jars (so they always match it) plus the client mods, resource packs and shaders below. Two ways to hand it out:</p>
      <div class="pk-ways">
        <div class="pk-way"><h3>⬇ One file to import</h3>
          <p class="muted small">A <b>.mrpack</b> file. In Prism: <b>Add Instance → Import</b>, pick the file, and it sets up Minecraft, Fabric and every mod (the Modrinth App and CurseForge import it too). It doesn't update by itself: when you change the pack, they import the new file.</p>
          <div class="btn-row"><button class="btn sm primary" type="button" data-mrpack>Download the .mrpack</button></div>
          <label class="check"><input type="checkbox" data-mp-public ${pack.public_download ? "checked" : ""}> <span>Offer it on the website<br><small class="muted">A download, with how to install it, on this server's card on the home page</small></span></label></div>
        <div class="pk-way"><h3>🔄 Keeps itself up to date (packwiz)</h3>
          <p class="muted small">For Prism on PCs you set up yourself: a small installer runs before each launch and downloads whatever changed.</p>
          <label class="check"><input type="checkbox" data-mp-on ${pack.enabled ? "checked" : ""}> Keep Prism instances up to date from here</label>
          ${setup}</div></div>
      <h3>From this server</h3>
      <div class="pk-list">${sm.map((m) => `<label class="check pk-item"><input type="checkbox" data-sm="${esc(m.id)}" ${m.included ? "checked" : ""}> <b>${esc(m.name)}</b> <span class="muted small">${esc(m.version || "")}${m.environment === "client" ? " · client mod" : ""}</span></label>`).join("")}</div>
      <h3>From Modrinth <span class="muted small">${pack.extra.length}</span></h3>
      ${pack.extra.length ? `<div class="pk-list">${pack.extra.map((e) => `<div class="pk-item">${e.icon ? `<img src="${esc(e.icon)}" alt="" width="20" height="20" loading="lazy" data-fail="remove">` : ""}<span class="pk-t"><b>${esc(e.title)}</b><small class="muted">${e.kind === "mod" ? "" : `${esc(KIND[e.kind])} · `}${esc(e.version)}</small></span><button class="icon-btn" type="button" data-rm="${esc(e.slug)}" aria-label="Remove ${esc(e.title)}">✕</button></div>`).join("")}</div>
        <div class="btn-row"><button class="btn sm" type="button" data-check>Check for updates</button><span id="pk-upd" class="muted small"></span></div>` : `<p class="muted small">Nothing yet.</p>`}
      <form class="pk-search" id="pk-search"><select class="input sm" name="kind">${Object.entries(KIND).map(([k, l]) => `<option value="${k}" ${k === kind ? "selected" : ""}>${l}</option>`).join("")}</select>
        <input class="input" name="q" placeholder="Search Modrinth (Sodium, Iris, Fresh Animations…)" autocomplete="off"><button class="btn" type="submit">Search</button></form>
      ${hits.length ? `<div class="pk-hits">${hits.map((h) => `<button type="button" class="pk-hit" data-add="${esc(h.slug)}" data-kind="${esc(h.kind)}">${h.icon ? `<img src="${esc(h.icon)}" alt="" width="28" height="28" loading="lazy" data-fail="remove">` : ""}<span><b>${esc(h.title)}</b><small class="muted">${esc(h.description)}</small></span><span class="btn sm">Add</span></button>`).join("")}</div>` : ""}
      <details class="pk-paste"><summary>Add a whole list at once</summary>
        <form id="pk-names"><textarea class="input" name="names" rows="6" placeholder="One per line, for example:&#10;Sodium&#10;Iris&#10;LambDynamicLights&#10;resourcepack: Fresh Animations&#10;shader: Complementary Reimagined"></textarea>
        <button class="btn" type="submit">Add them</button></form></details>
      ${note ? `<p class="notice small">${note}</p>` : ""}
    </section>`;
  };
  const render = () => { setView(serverHeader(s, "mods") + listHtml + packHtml()); wireHeader(s); wire(); paintUpdates(); };
  // Updates from Modrinth (by each jar's fingerprint, for this server's Minecraft version): a badge on each mod, and
  // Geyser and Floodgate called out at the top, since Bedrock players can't join when they fall behind.
  let upd = null;
  const paintUpdates = () => {
    const box = $("#mod-updates");
    if (!box || !upd) return;
    if (upd.error) { box.innerHTML = `<span class="muted small">⚠️ ${esc(upd.error)}</span> <button class="btn sm" type="button" data-recheck>Try again</button>`; }
    else {
      const rows = Object.values(upd.mods), news = rows.filter((r) => r.status === "update"), bedrock = news.filter((r) => r.important);
      box.innerHTML = `${bedrock.length ? `<p class="mod-bedrock">⚠️ <b>Update ${esc(bedrock.map((r) => r.name).join(" and "))}</b>: Bedrock players may not be able to join until ${bedrock.length > 1 ? "they're" : "it's"} up to date.</p>` : ""}
        <span class="${news.length ? "" : "muted"} small">${news.length ? `⬆ ${news.length} ${news.length === 1 ? "mod has" : "mods have"} a newer build for Minecraft ${esc(upd.mc || "")}` : "✓ Everything on Modrinth is up to date"}
        · checked ${esc(fmtAgo(upd.checked))}</span> <button class="btn sm" type="button" data-recheck>Check again</button>`;
      $$(".mod[data-file]").forEach((el) => {
        const r = upd.mods[el.dataset.file];
        el.querySelector(".mod-badge")?.remove();
        if (!r) return;
        const b = document.createElement("span");
        b.className = `mod-badge ${r.status}${r.important ? " key" : ""}`;
        b.innerHTML = r.status === "update" ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">⬆ ${esc(r.latest)} available</a>`
          : r.status === "ok" ? "✓ Up to date" : "Not on Modrinth";
        el.querySelector(".mn")?.append(b);
      });
    }
    box.querySelector("[data-recheck]")?.addEventListener("click", () => loadUpdates(true));
  };
  const loadUpdates = async (force) => {
    const box = $("#mod-updates");
    if (box && force) box.innerHTML = `<span class="muted small">Checking Modrinth…</span>`;
    upd = await api(`/api/servers/${encodeURIComponent(sid)}/mods/updates${force ? "?force=1" : ""}`).catch((err) => ({ error: err.message }));
    paintUpdates();
  };
  const busy = (el, on) => { if (el) { el.disabled = on; el.classList.toggle("busy", on); } };
  const wire = () => {
    $("[data-mp-on]")?.addEventListener("change", async (e) => { pack = await post(base, { enabled: e.target.checked }, "PUT"); render(); });
    $("[data-mp-public]")?.addEventListener("change", async (e) => { pack = await post(base, { public_download: e.target.checked }, "PUT"); showToast(e.target.checked ? "On the website now" : "Off the website", 2000); render(); });
    $("[data-mrpack]")?.addEventListener("click", async (e) => {
      const b = e.currentTarget; b.disabled = true; b.textContent = "Making it…";
      try {
        const r = await fetch(pack.mrpack, { credentials: "same-origin" });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "That didn't work");
        const name = (r.headers.get("content-disposition") || "").match(/filename="?([^";]+)/)?.[1] || "modpack.mrpack";
        const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(await r.blob()), download: name });
        a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      } catch (err) { showError(esc(err.message), 7000); }
      b.disabled = false; b.textContent = "Download the .mrpack";
    });
    $("[data-newtoken]")?.addEventListener("click", async () => { if (!confirm("Make a new pack address? Every PC's pre-launch command will need the new one.")) return; pack = await post(base, { new_token: true }, "PUT"); render(); });
    $$("[data-sm]").forEach((b) => b.addEventListener("change", async () => {
      pack = await post(base, { server_mods: $$("[data-sm]").filter((x) => x.checked).map((x) => x.dataset.sm) }, "PUT"); render();
    }));
    $$("[data-rm]").forEach((b) => b.addEventListener("click", async () => { pack = await api(`${base}/extra/${encodeURIComponent(b.dataset.rm)}`, { method: "DELETE" }); render(); }));
    $$("[data-copy]").forEach((b) => b.addEventListener("click", () => { navigator.clipboard?.writeText($("#" + b.dataset.copy).textContent); showToast("Copied", 1500); }));
    $("#pk-search")?.addEventListener("submit", async (e) => {
      e.preventDefault(); const f = new FormData(e.target); kind = f.get("kind");
      busy(e.target.querySelector("button"), true);
      try { hits = (await api(`${base}/search?q=${encodeURIComponent(f.get("q"))}&kind=${kind}`)).hits; note = hits.length ? "" : `Nothing on Modrinth for that on ${esc(pack.mc)}.`; }
      catch (err) { note = esc(err.message); }
      render(); $("#pk-search input[name=q]").value = f.get("q");
    });
    $$("[data-add]").forEach((b) => b.addEventListener("click", async () => {
      busy(b, true);
      try { const r = await post(`${base}/add`, { slug: b.dataset.add, kind: b.dataset.kind }); pack = r.pack; hits = []; note = r.added.length ? `Added ${r.added.map((a) => esc(a.title)).join(", ")}.` : "Already in the pack."; }
      catch (err) { note = esc(err.message); }
      render();
    }));
    $("#pk-names")?.addEventListener("submit", async (e) => {
      e.preventDefault(); busy(e.target.querySelector("button"), true);
      try {
        const r = await post(`${base}/add`, { names: new FormData(e.target).get("names") }); pack = r.pack;
        note = `${r.added.length ? `Added: ${r.added.map((a) => esc(a.title) + (a.already ? " (already in)" : "")).join(", ")}.` : ""}${r.missing.length ? ` Not found for ${esc(pack.mc)}: ${r.missing.map(esc).join(", ")}.` : ""}`;
      } catch (err) { note = esc(err.message); }
      render();
    });
    $("[data-check]")?.addEventListener("click", async (e) => {
      busy(e.target, true);
      const r = await post(`${base}/check`).catch((err) => ({ error: err.message }));
      const el = $("#pk-upd");
      if (r.error) { el.textContent = r.error; busy(e.target, false); return; }
      if (!r.updates.length) { el.textContent = "Everything is up to date."; busy(e.target, false); return; }
      el.innerHTML = `${r.updates.map((u) => `${esc(u.title)} ${esc(u.current)} → ${esc(u.latest)}`).join(" · ")} <button class="btn sm primary" type="button" data-updall>Update all</button>`;
      busy(e.target, false);
      $("[data-updall]").addEventListener("click", async () => { const u = await post(`${base}/update-all`); pack = u.pack; note = `Updated ${u.changed.length}. Each PC picks it up next launch.`; render(); });
    });
  };
  render();
  loadUpdates(false);
}

// ---------------------------------------------------------------- settings
async function openSettings(s) {
  const cur = await api(`/api/servers/${encodeURIComponent(s.id)}/settings`).catch(() => ({}));
  openModal(`<h2>Server settings</h2>
    <form id="settings-form">
      <label>Display name<input class="input" name="display_name" value="${esc(cur.display_name || "")}" placeholder="${esc(s.name)}"></label>
      <label>Map address <small>BlueMap, squaremap or Dynmap web address shown on the World tab</small><input class="input" name="map_url" value="${esc(cur.map_url || "")}" placeholder="http://192.168.1.10:8100"></label>
      <label class="check"><input type="checkbox" name="map_proxy" ${cur.map_proxy ? "checked" : ""}> Show the map through Solstone <small>It then opens from anywhere, not just at home, and only for people signed in who may see the map (Players only with <i>Players can see the map</i> on). The map itself stays off the internet: use its home-network address above.</small></label>
      <p class="muted small">How to join this server (its addresses, a note, the mods) is set in Manage → Website → Site details.</p>
      <label>RCON host <small>Used for live inventories. Leave blank to use ${esc(s.rcon?.host || "the Crafty host")}.</small><input class="input" name="rcon_host" value="${esc(cur.rcon_host || "")}"></label>
      <label>RCON port <small>Leave blank to use rcon.port from server.properties</small><input class="input" name="rcon_port" inputmode="numeric" value="${esc(cur.rcon_port || "")}"></label>
      <label>RCON password <small>${cur.rcon_password_set ? "Saved. Type a new one to replace it." : "Leave blank to use rcon.password from server.properties"}</small><input class="input" type="password" name="rcon_password" autocomplete="off"></label>
      <label class="check"><input type="checkbox" name="private" ${cur.private ? "checked" : ""}> Private <small>Only admins see it. It never shows on the public pages, and signed-in players don't see it.</small></label>
      <label class="check"><input type="checkbox" name="hidden" ${cur.hidden ? "checked" : ""}> Hide this server from Solstone</label>
      <div class="actions"><button type="button" class="btn" data-close-modal>Cancel</button><button class="btn primary" type="submit">Save settings</button></div>
    </form>`, (m) => {
    $("#settings-form", m).addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const body = { display_name: f.get("display_name"), map_url: f.get("map_url"), rcon_host: f.get("rcon_host"),
        rcon_port: f.get("rcon_port") ? Number(f.get("rcon_port")) : "", hidden: f.get("hidden") ? true : "", private: f.get("private") ? true : "",
        map_proxy: f.get("map_proxy") ? true : "" };
      if (f.get("rcon_password")) body.rcon_password = f.get("rcon_password");
      try {
        await post(`/api/servers/${encodeURIComponent(s.id)}/settings`, body, "PUT");
        closeModal(); showToast("Settings saved", 2500);
        await loadServers(); route();
      } catch (err) { showError(`Couldn't save settings: ${esc(err.message)}`, 5000); }
    });
  });
}

// ================================================================ router
async function route() {
  clearTimers();
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent).filter(Boolean);
  try {
    if (!me.user) return;
    // Manage: the old addresses lead to their tab
    const OLD = { admin: "users", announcements: "announcements", website: "website" };
    if (OLD[parts[0]]) { location.replace(`#/manage/${OLD[parts[0]]}`); return; }
    if ((parts[0] === "fireworks" && parts[1] === "settings") || (parts[0] === "manage" && parts[1] === "fireworks")) { location.replace("#/fireworks/show"); return; }
    setManageNav(parts[0] === "manage" ? parts[1] || "announcements" : null);
    if (parts[0] === "manage") {
      const tab = parts[1] || "announcements";
      if (tab === "announcements") await viewAnnouncements();
      else if (tab === "website") await viewWebsite();
      else if (tab === "whitelist") await viewWhitelist();
      else if (tab === "notifications") await viewNotifications();
      else if (tab === "holidays") await viewHolidays();
      else await viewAdmin(tab);
      return;
    }
    if (parts[0] === "coming-up") { location.replace("#/events"); return; }      // its old name
    if (parts[0] === "events") { await viewUpcoming(); return; }
    if (parts[0] === "fireworks" && parts[1] === "show") { await viewFireworkSettings(); return; }
    if (parts[0] === "fireworks") { await viewFireworkEditor(parts[1]); return; }
    if (parts[0] === "s" && parts[1]) {
      const sid = parts[1];
      if (isPlayer() && parts[2] === "world" && !state.servers?.length) await loadServers();
      const mapOk = parts[2] === "world" && state.servers?.find((x) => x.id === sid)?.player_map;
      if (isPlayer() && PLAYER_HIDDEN.has(parts[2]) && !mapOk) { location.replace(`#/s/${encodeURIComponent(sid)}`); return; }
      if (parts[2] === "p" && parts[3]) await viewPlayer(sid, parts[3], parts[4] || "inventory");
      else if (parts[2] === "world") await viewWorld(sid);
      else if (parts[2] === "activity") location.replace(`#/s/${encodeURIComponent(sid)}`);
      else if (parts[2] === "control") await viewControl(sid);
      else if (parts[2] === "check") await viewCheck(sid);
      else if (parts[2] === "fishing") await viewFishingJournal(sid, parts[3]);
      else if (parts[2] === "chat") await viewChat(sid);
      else if (parts[2] === "adventures") await viewAdventures(sid, parts[3]);
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
  wireAccountMenu(); wireMobileMenu();
  const ch = $("#build-channel");
  if (ch && BUILD_CHANNEL === "beta") { ch.textContent = "Beta build"; ch.hidden = false; }
  try { signedIn((await api("/api/auth/me")).user); }
  catch { showLogin(); }
});
