/* Solstone — the public home page and its posts (News, Guides, FAQ). No sign-in.
   Everything comes from /api/public/site and /api/public/posts; private servers never appear there.
   Post text is a small subset of Markdown, escaped first and then formatted, so it can't carry HTML. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const hp = { site: null };
// Two kinds of page: News (what's happening) and Help (guides, then questions and answers).
const SECTIONS = { news: ["News", "news"], help: ["Help", "help"] };

// Old bookmarks into the app (/#/s/...) still work: the app lives at /app now.
if (location.hash.startsWith("#/")) location.replace(`/app${location.hash}`);

async function getJSON(url) {
  const r = await fetch(url, { credentials: "same-origin", cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

function toast(text, html = false) {
  const t = $("#hp-toast");
  if (html) t.innerHTML = text; else t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, html ? 6000 : 2500);
}

// Post text is turned into HTML by postfmt.js (shared with the post editor's live preview).

// ------------------------------------------------------------------ pieces
const dateText = (ts) => new Date(ts * 1000).toLocaleDateString([], { year: "numeric", month: "long", day: "numeric" });
const CAT_LABEL = { news: "News", guide: "Guide", faq: "FAQ" };

// The mods a player's own Minecraft needs for a modded server, folded away until wanted.
function modsHtml(m) {
  if (!m || !m.list?.length) return "";
  const head = `${m.list.length} ${m.list.length === 1 ? "mod" : "mods"} for ${esc([m.loader, m.mc && `Minecraft ${m.mc}`].filter(Boolean).join(" · "))}`;
  const dl = m.download ? `<div class="hp-pack"><a class="btn primary sm" href="${esc(m.download)}" download>⬇ Download the modpack</a>
      <details><summary>How to install it</summary><ol>
        <li>Get <a href="https://prismlauncher.org" target="_blank" rel="noopener">Prism Launcher</a> (free, for Windows, Mac and Linux) and sign in with your Microsoft account.</li>
        <li>Download the modpack (the button above). It's one <b>.mrpack</b> file.</li>
        <li>In Prism, choose <b>Add Instance</b>, then <b>Import</b>, pick the file, and choose <b>OK</b>. Prism sets up the right Minecraft, Fabric and every mod.</li>
        <li>Launch it, then join the server from <b>Multiplayer</b>.</li></ol>
        <p class="muted small">The Modrinth App and CurseForge can import the file too. When the mods change, download it again and import the new one.</p></details></div>` : "";
  return `${dl}<details class="hp-mods"><summary>🧩 ${head}</summary>
    <ul>${m.list.map((x) => `<li>${x.link ? `<a href="${esc(x.link)}" target="_blank" rel="noopener">${esc(x.name)}</a>` : esc(x.name)}${x.version ? ` <span class="muted small">${esc(x.version)}</span>` : ""}${x.kind && x.kind !== "mod" ? ` <span class="chip">${esc(x.kind === "resourcepack" ? "Resource pack" : x.kind === "shader" ? "Shader" : x.kind)}</span>` : ""}</li>`).join("")}</ul></details>`;
}

// A server's state in a few words, beside where to join it: online or not, how many on, up how long, how smooth.
function statusLine(s) {
  if (!s) return "";
  if (!s.running) return `<p class="hp-join-state"><span class="hp-dot"></span>Offline right now</p>`;
  const since = s.started ? new Date(String(s.started).replace(" ", "T")).getTime() : NaN;
  const up = Number.isFinite(since) ? (() => { const m = Math.max(0, Math.floor((Date.now() - since) / 60000)), d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60);
    return d ? `${d} d ${h} h` : h ? `${h} h ${m % 60} min` : `${m} min`; })() : "";
  const tps = s.tps == null ? "" : s.tps >= 19.5 ? "running smoothly" : s.tps >= 15 ? "a little laggy" : "very laggy";
  return `<p class="hp-join-state"><span class="hp-dot on"></span><b>Online</b> · ${s.online} / ${s.max ?? "?"} playing${up ? ` · up ${up}` : ""}${tps ? ` · ${tps}${s.tps != null ? ` (${Number(s.tps).toFixed(1)} TPS)` : ""}` : ""}</p>`;
}

function joinCard(site) {
  const rowsHtml = (rows) => `<div class="hp-join-rows">${rows.map(([ed, addr, extra]) => `<div class="hp-join-row">
      <span class="hp-ed">${esc(ed)}</span><code class="hp-addr">${esc(addr)}</code>${extra ? `<span class="muted">${esc(extra)}</span>` : ""}
      <button class="btn sm" type="button" data-copy="${esc(addr)}">Copy</button></div>`).join("")}</div>`;
  // One card per server: what it is, how it's doing, and how to get on it.
  const cards = (site.joins || []).map((j) => {
    const r = [];
    if (j.java) r.push(["Java", j.java, j.version ? `Minecraft ${j.version}` : ""]);
    if (j.bedrock) r.push(["Bedrock", j.bedrock, `Port ${j.bedrock_port} · newest version`]);
    const kind = j.java && j.bedrock ? "Java and Bedrock" : j.java ? "Java only" : "Bedrock only";
    const icon = site.live && j.status?.has_icon ? `<img class="px" src="/api/public/icon/${encodeURIComponent(j.id)}.png" alt="" width="40" height="40">` : "";
    return `<article class="hp-join-card ${j.main ? "main" : ""}" ${j.color ? `style="--accent:${esc(j.color)}"` : ""}>
      <header>${icon}<div><h3>${esc(j.name)}</h3><span class="chip">${kind}</span></div></header>
      ${statusLine(j.status)}${rowsHtml(r)}${j.note ? `<p class="hp-join-note">${esc(j.note)}</p>` : ""}${modsHtml(j.mods)}
      ${site.live ? `<a class="hp-join-live" href="#live" data-live-sid="${esc(j.id)}">📊 Go to live stats →</a>` : ""}</article>`;
  });
  if (!cards.length) return "";
  return `<section class="hp-join glass"><h2>Join the server${cards.length > 1 ? "s" : ""}</h2>
    <div class="hp-join-cards ${cards.length > 1 ? "many" : ""}">${cards.join("")}</div>
    ${site.join_requests ? `<div class="hp-ask-cta"><a class="btn primary hp-ask-btn" href="/guides/join#ask">🙋 Ask to join</a>
      <span class="muted">New here? The server only lets in people on its list. Ask, and an admin will add you.</span></div>` : ""}
    <p class="muted"><a href="/guides/join">Step-by-step guide</a>${site.signup ? ' · <a href="/guides/account">Make an account on this website</a>' : ""}${site.discord ? ` · Questions? <a href="${esc(site.discord)}" target="_blank" rel="noopener">Join us on Discord</a>` : ""}</p></section>`;
}

// With live info on, a server's card shows it live further down the page.
function serversCard(site) {
  if (!site.servers.length) return "";
  return `<section class="hp-servers"><h2>Servers</h2><div class="hp-server-list">${site.servers.map((s) => `
    <a class="hp-server glass" href="${site.live ? "#live" : "#"}" ${site.live ? `data-live-sid="${esc(s.id)}"` : 'aria-disabled="true"'}>
      ${s.has_icon ? `<img class="px" src="/api/public/icon/${encodeURIComponent(s.id)}.png" alt="" width="40" height="40">` : ""}
      <span class="hp-server-name">${esc(s.name)}</span>
      <span class="hp-dot ${s.running ? "on" : ""}" aria-hidden="true"></span>
      <span class="muted">${s.running ? `${s.online} / ${s.max} online` : "Offline"}${s.version ? ` · ${esc(s.version)}` : ""}</span>
    </a>`).join("")}</div></section>`;
}

function postCards(posts, empty) {
  if (!posts.length) return `<p class="muted">${esc(empty)}</p>`;
  return `<div class="hp-posts">${posts.map((p) => `<a class="hp-post glass ${p.image ? "has-pic" : ""}" href="${p.builtin ? `/guides/${p.slug}` : `/post/${encodeURIComponent(p.slug)}`}">
    ${p.image ? `<img class="hp-post-pic" src="${esc(p.image)}" alt="" loading="lazy">` : ""}
    <span class="hp-post-meta">${p.builtin ? "Guide · Start here" : `${esc(CAT_LABEL[p.category] || "")}${p.pinned ? " · 📌" : ""} · ${esc(dateText(p.created))}`}</span>
    <h3>${esc(p.title)}</h3><p class="muted">${esc(p.excerpt || "")}</p></a>`).join("")}</div>`;
}

function faqList(posts) {
  if (!posts.length) return `<p class="muted">No questions yet.</p>`;
  return `<div class="hp-faq">${posts.map((p) => `<details class="glass"><summary>${esc(p.title)}</summary>
    <div class="hp-body" data-faq="${esc(p.slug)}"><p class="muted">Loading…</p></div></details>`).join("")}</div>`;
}

// Live: who's playing right now, the world, leaderboards and the recap (live.js fills it in).
function liveSection() {
  return `<section class="hp-live" id="live" hidden><div class="hp-head"><h2>Live on the servers</h2><span class="sp-updated" id="sp-updated" aria-live="polite"></span></div>
    <nav class="sp-servers" id="sp-servers" aria-label="Servers"></nav>
    <div id="sp-main" class="sp-main"><p class="muted sp-loading">Loading…</p></div></section>`;
}

// ------------------------------------------------------------------ built-in guides
// Their wording is in guides.js (admins can rewrite them in Website → Guides).
const BUILTIN = GUIDES;

function builtinCards() {
  return Object.entries(BUILTIN).map(([k, g]) => ({ slug: k, title: g.title, excerpt: g.excerpt, builtin: true }));
}

// ------------------------------------------------------------------ pages
async function home() {
  const s = hp.site;
  const [news, guides] = await Promise.all([getJSON("/api/public/posts?category=news&limit=3"), getJSON("/api/public/posts?category=guide&limit=4")]);
  return `${s.home_title ? `<section class="hp-hero"><h1>${esc(s.name)}</h1>${s.tagline ? `<p class="hp-tagline">${esc(s.tagline)}</p>` : ""}</section>` : ""}
    <p class="hp-ask-status" id="ask-status" hidden></p>
    ${joinCard(s) || serversCard(s)}
    <section><div class="hp-head"><h2>News</h2><a href="/news">All news →</a></div>${postCards(news, "No news yet.")}</section>
    <section><div class="hp-head"><h2>Help</h2><a href="/help">All guides and questions →</a></div>${postCards([...builtinCards(), ...guides].slice(0, 4), "")}</section>
    ${s.live ? liveSection() : ""}
    ${s.about ? `<section class="hp-about glass"><h2>About</h2><div class="hp-body">${markdown(s.about)}</div></section>` : ""}`;
}

async function section(key) {
  if (key === "help") {
    const [guides, faq] = await Promise.all([getJSON("/api/public/posts?category=guide&limit=100"), getJSON("/api/public/posts?category=faq&limit=100")]);
    return `<section><h1>Help</h1><p class="muted">How to join, how things work here, and answers to common questions.</p></section>
      <section><h2>Guides</h2>${postCards([...builtinCards(), ...guides], "")}</section>
      <section id="faq"><h2>Questions</h2>${faqList(faq)}</section>`;
  }
  const [title, cat] = SECTIONS[key];
  const posts = await getJSON(`/api/public/posts?category=${cat}&limit=100`);
  return `<section><h1>${esc(title)}</h1>${postCards(posts, `No ${title.toLowerCase()} yet.`)}</section>`;
}

async function article(slug) {
  let p;
  if (slug === "__preview__") return previewArticle();
  try { p = await getJSON(`/api/public/posts/${encodeURIComponent(slug)}`); } catch { return `<section><h1>Not found</h1><p class="muted">That post isn't here any more. <a href="/">Back home</a></p></section>`; }
  const back = { news: ["/news", "News"], guide: ["/help", "Help"], faq: ["/help", "Help"] }[p.category] || ["/", "Home"];
  document.title = `${p.title} · ${hp.site.name}`;
  return `<article class="hp-article glass"><a class="back" href="${back[0]}">← ${esc(back[1])}</a>
    <h1>${esc(p.title)}</h1><p class="hp-post-meta">${esc(dateText(p.created))}${p.author ? ` · ${esc(p.author)}` : ""}</p>
    <div class="hp-body">${markdown(p.body)}</div></article>`;
}

// A post being written (Website → Posts → 👁 Preview): from this browser's storage, shown as visitors will see it.
function previewArticle() {
  let p = null;
  try { p = JSON.parse(localStorage.getItem("solstone-post-preview") || "null"); } catch { /* nothing kept */ }
  if (!p) return `<section><h1>Nothing to preview</h1><p class="muted">Press 👁 Preview in the post editor (Website → Posts).</p></section>`;
  document.title = `Preview: ${p.title} · ${hp.site.name}`;
  return `<p class="hp-preview-note glass">👁 <b>Preview.</b> Only you can see this. Nobody else sees the post until it's published and saved. Press Preview again after changes, or reload this tab.</p>
    <article class="hp-article glass"><a class="back" href="${p.category === "news" ? "/news" : "/help"}">← ${p.category === "news" ? "News" : "Help"}</a>
    <h1>${esc(p.title)}</h1><p class="hp-post-meta">${esc(dateText(p.created))}${p.author ? ` · ${esc(p.author)}` : ""}</p>
    <div class="hp-body">${markdown(p.body)}</div></article>`;
}

function builtinArticle(key) {
  const g = BUILTIN[key];
  document.title = `${g.title} · ${hp.site.name}`;
  return `<article class="hp-article glass"><a class="back" href="/help">← Help</a>
    <h1>${esc(g.title)}</h1><div class="hp-body">${markdown(guideText(key, hp.site))}</div></article>
    ${key === "join" && hp.site.join_requests ? askFormHtml() : ""}`;
}

// Asked already? This browser keeps a private ticket for it, so it can show them when they're let in, without
// anyone else being able to see who's on the list.
function askTicket() { try { return JSON.parse(localStorage.getItem("solstone-ask") || "null"); } catch { return null; } }
// A small badge in the corner while a request is out: sent, waiting (it can take a while), then "you're in".
// It checks once a minute, and never gets stuck: × hides it, a ticket the server no longer knows is dropped,
// and after a week of waiting the badge stops (the request still shows on the join guide).
const ASK_BADGE_DAYS = 7;
let askTimer = 0;
async function showAskStatus() {
  clearTimeout(askTimer);
  const t = askTicket();
  if (!t?.token) { renderAskBadge(null); return; }
  let d = null;
  try {
    const r = await fetch("/api/public/join-request/status", { method: "POST", headers: { "Content-Type": "application/json", "X-Solstone": "1" }, body: JSON.stringify({ token: t.token }) });
    d = r.ok ? await r.json() : null;
  } catch { askTimer = setTimeout(showAskStatus, 60000); return; }
  if (!d || d.state === "unknown") { forgetAsk(); return; }
  const box = $("#ask-status");
  if (box) {
    box.hidden = false;
    box.className = `hp-ask-status ${d.state}`;
    const each = (d.servers || []).length > 1 ? ` <span class="ask-each">${d.servers.map((x) => `<span class="${x.in ? "in" : ""}">${x.in ? "✅" : "⏳"} ${esc(x.name)}</span>`).join("")}</span>` : "";
    box.innerHTML = d.state === "denied"
      ? `Sorry, <b>${esc(d.player)}</b>, your request wasn't accepted this time. If you think that's a mistake, ask an admin you know. <button type="button" class="link-btn" data-ask-forget>Hide this</button>`
      : d.state === "in"
      ? `🎉 <b>${esc(d.player)}</b>, you're in! Join the server now.${each} <button type="button" class="link-btn" data-ask-forget>Hide this</button>`
      : d.state === "partly"
        ? `<span class="spin" aria-hidden="true"></span> <b>${esc(d.player)}</b>, you're in on some already, and waiting for an admin on the rest.${each}`
        : `<span class="spin" aria-hidden="true"></span> Your request for <b>${esc(d.player)}</b> is waiting for an admin. It may not be right away, but they'll get to it as soon as they can.${each}`;
  }
  const old = Date.now() - (t.at || Date.now()) > ASK_BADGE_DAYS * 86400000;
  renderAskBadge(d.state === "in" || d.state === "denied" || (!old && !t.hidden) ? d : null);
  if (d.state !== "in" && d.state !== "denied") askTimer = setTimeout(showAskStatus, document.hidden ? 180000 : 60000);
}
function renderAskBadge(d) {
  let b = $("#ask-badge");
  if (!d) { b?.remove(); return; }
  if (!b) { b = document.createElement("div"); b.id = "ask-badge"; b.setAttribute("role", "status"); document.body.append(b); }
  b.className = `ask-badge glass ${d.state}`;
  b.innerHTML = d.state === "denied"
    ? `<span aria-hidden="true">✋</span><span><b>Request not accepted</b><small>Your request for ${esc(d.player)} wasn't accepted this time</small></span><button type="button" class="ask-x" data-ask-forget aria-label="Close">×</button>`
    : d.state === "in"
    ? `<span aria-hidden="true">🎉</span><span><b>You're in, ${esc(d.player)}!</b><small>Join the server now</small></span><button type="button" class="ask-x" data-ask-forget aria-label="Close">×</button>`
    : `<span class="spin" aria-hidden="true"></span><span><b>${d.state === "partly" ? "You're in on some" : "Request sent"}</b><small>${d.state === "partly"
      ? `In on ${esc(d.servers.filter((x) => x.in).map((x) => x.name).join(", "))}. Waiting on ${esc(d.servers.filter((x) => !x.in).map((x) => x.name).join(", "))}`
      : `Waiting for an admin to let ${esc(d.player)} in`}</small></span><button type="button" class="ask-x" data-ask-hide aria-label="Hide">×</button>`;
}
function forgetAsk() {
  try { localStorage.removeItem("solstone-ask"); } catch { /* fine */ }
  clearTimeout(askTimer);
  renderAskBadge(null);
  const box = $("#ask-status");
  if (box) box.hidden = true;
}
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-ask-forget]")) { forgetAsk(); return; }
  if (e.target.closest("[data-ask-hide]")) {          // hide the badge only: the request is still waiting
    const t = askTicket();
    if (t) { try { localStorage.setItem("solstone-ask", JSON.stringify({ ...t, hidden: true })); } catch { /* fine */ } }
    renderAskBadge(null);
  }
});
document.addEventListener("visibilitychange", () => { if (!document.hidden && askTicket()) showAskStatus(); });

// Ask to join: their name goes to the admins' notifications, ready to let in from Control.
function askFormHtml() {
  return `<section class="hp-ask glass" id="ask"><h2>Ask to join</h2>
    <p class="hp-ask-status" id="ask-status" hidden></p>
    <p class="muted">The admins get a message with your name and can let you in. Then try joining again.</p>
    <form id="ask-form" autocomplete="off">
      <fieldset class="hp-ask-ed"><legend>I play on</legend>
        <label class="check"><input type="radio" name="edition" value="java" checked> Java (PC or Mac)</label>
        <label class="check"><input type="radio" name="edition" value="bedrock"> Bedrock (phone, tablet, console, Windows)</label></fieldset>
      ${(hp.site.ask_servers || []).length > 1 ? `<fieldset class="hp-ask-ed"><legend>Which servers? <small class="muted">Pick one or more</small></legend>
        ${hp.site.ask_servers.map((x, i) => `<label class="check"><input type="checkbox" name="servers" value="${esc(x.id)}" ${i === 0 ? "checked" : ""}> ${esc(x.name)}</label>`).join("")}</fieldset>` : ""}
      <label>Your name in the game <small>Exactly as it shows. On Bedrock that's your Xbox gamertag.</small><input class="input" name="player" required maxlength="20" autocapitalize="off"></label>
      <label>Your first name <small>Optional, so the admins know who you are</small><input class="input" name="name" maxlength="40"></label>
      <label>A note <small>Optional: who you know here, for example</small><textarea class="input" name="note" rows="3" maxlength="300"></textarea></label>
      <label class="check hp-ask-rules"><input type="checkbox" name="rules" required> I've read <a href="/guides/rules" target="_blank" rel="noopener">the rules</a> and I'll follow them</label>
      <p class="login-error" role="alert"></p>
      <button class="btn primary" type="submit">Send</button></form></section>`;
}
document.addEventListener("submit", async (e) => {
  if (e.target.id !== "ask-form") return;
  e.preventDefault();
  const f = new FormData(e.target), err = $(".login-error", e.target);
  try {
    const r = await fetch("/api/public/join-request", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Solstone": "1" },
      body: JSON.stringify({ edition: f.get("edition"), player: f.get("player"), name: f.get("name"), note: f.get("note"), servers: f.getAll("servers"), rules: !!f.get("rules") }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "That didn't send. Try again in a moment.");
    try { localStorage.setItem("solstone-ask", JSON.stringify({ token: d.token, player: d.player, at: Date.now() })); } catch { /* private window */ }
    e.target.outerHTML = `<p class="hp-ask-done">✅ ${esc(d.message)}</p>`;
    showAskStatus();
  } catch (x) { err.textContent = x.message; }
});

async function route() {
  hp.path = location.pathname;
  const path = location.pathname.replace(/\/+$/, "") || "/";
  const main = $("#hp-main");
  let nav = "home", html;
  try {
    if (path === "/") html = await home();
    else if (path.startsWith("/post/")) { nav = ""; html = await article(decodeURIComponent(path.slice(6))); }
    else if (path === "/guides" || path === "/faq") { history.replaceState(null, "", path === "/faq" ? "/help#faq" : "/help"); route(); return; }   // the old pages
    else if (path.startsWith("/guides/") && BUILTIN[path.slice(8)]) { nav = "help"; html = builtinArticle(path.slice(8)); }
    else if (SECTIONS[path.slice(1)]) { nav = path.slice(1); html = await section(nav); }
    else { nav = ""; html = `<section><h1>Not found</h1><p class="muted"><a href="/">Back home</a></p></section>`; }
  } catch {
    html = `<section><h1>Couldn't load this page</h1><p class="muted">Try again in a moment.</p></section>`;
  }
  if (!path.startsWith("/post/") && !path.startsWith("/guides/")) document.title = nav && nav !== "home" ? `${SECTIONS[nav][0]} · ${hp.site.name}` : hp.site.name;
  main.innerHTML = html;
  document.querySelectorAll("[data-nav]").forEach((a) => a.toggleAttribute("aria-current", a.dataset.nav === nav));
  showAskStatus();
  if (location.hash === "#faq" || location.hash === "#ask") $(location.hash)?.scrollIntoView(); else if (location.hash !== "#live") window.scrollTo(0, 0);
  if ($("#live") && typeof startLive === "function") {
    await startLive({ scene: hp.scene, toast: (h) => toast(h, true) });
    if (location.hash === "#live") $("#live")?.scrollIntoView();
  }
}

// Links inside the site change the page without a reload; everything else is a normal link.
document.addEventListener("click", (e) => {
  const card = e.target.closest("[data-live-sid]");
  if (card) { e.preventDefault(); window.showLiveServer?.(card.dataset.liveSid); return; }
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    navigator.clipboard?.writeText(copy.dataset.copy).then(() => toast("Copied"), () => toast(copy.dataset.copy));
    return;
  }
  const a = e.target.closest("a[href]");
  if (!a || e.defaultPrevented || a.target || e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;
  const url = new URL(a.href, location.href);
  if (url.origin !== location.origin) return;
  if (url.pathname === location.pathname && url.hash) return;          // a spot on this page: the browser scrolls to it
  if (url.pathname === "/" || url.pathname.startsWith("/post/") || url.pathname.startsWith("/guides") || url.pathname === "/faq" || SECTIONS[url.pathname.slice(1)]) {
    e.preventDefault();
    if (url.pathname !== location.pathname) history.pushState(null, "", url.pathname + url.hash);
    route();
  }
});
window.addEventListener("popstate", () => { if (location.pathname !== hp.path) route(); });     // not for a jump to a spot on the page

// FAQ answers load when opened.
document.addEventListener("toggle", async (e) => {
  const box = e.target.querySelector?.("[data-faq]");
  if (!e.target.open || !box || box.dataset.loaded) return;
  box.dataset.loaded = "1";
  try { box.innerHTML = markdown((await getJSON(`/api/public/posts/${encodeURIComponent(box.dataset.faq)}`)).body); }
  catch { box.innerHTML = `<p class="muted">Couldn't load the answer.</p>`; }
}, true);

document.addEventListener("DOMContentLoaded", async () => {
  try { hp.site = await getJSON("/api/public/site"); } catch { hp.site = { name: "Solstone", servers: [], live: false }; }
  $("#hp-name").textContent = $("#hp-foot-name").textContent = hp.site.name;
  showSignedIn();
  const sky = $("#home-sky");
  if (sky && typeof startSkyScene === "function") {
    hp.scene = startSkyScene(sky, { auto: false, sound: (t, i) => FWAudio.play(t, i), dim: () => (document.body.classList.contains("ui-hidden") ? 0 : 0.35) });
    // Fireworks are there for whoever wants them: off until a visitor turns the show on (it's remembered).
    if (typeof startShowBar === "function") hp.bar = startShowBar(hp.scene, { key: "solstone-sky-home", defaultOn: false, hide: true });
  }
  if (typeof startBoard === "function") startBoard($("#hp-board"), { where: "home", sid: () => "", scene: () => hp.scene, max: innerWidth < 700 ? 1 : 3 });
  route();
});
