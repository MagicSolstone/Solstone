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

// ------------------------------------------------------------------ Markdown (a safe subset)
function inline(s) {
  return s
    // pictures uploaded in Website (only those: nothing loaded from elsewhere)
    .replace(/!\[([^\]]*)\]\((\/api\/public\/images\/[0-9a-f]{16}\.(?:png|jpg|gif|webp))\)/g, '<img class="post-img" src="$2" alt="$1" loading="lazy">')
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])[*_]([^*_]+)[*_](?=[\s).,!?:;]|$)/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\(((?:https?:\/\/|\/(?!\/)|#[\w-]+(?=\)))[^\s)]*)\)/g, (_, t, href) =>
      `<a href="${href}"${href.startsWith("/") || href.startsWith("#") ? "" : ' target="_blank" rel="noopener"'}>${t}</a>`);
}

function markdown(src) {
  const lines = esc(src).replace(/\r/g, "").split("\n");
  const out = [];
  let list = null, para = [];
  const flush = () => {
    if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; }
    if (list) { out.push(`</${list}>`); list = null; }
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    let m;
    if (!line.trim()) { flush(); continue; }
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) { flush(); const n = Math.min(4, m[1].length + 1); out.push(`<h${n}>${inline(m[2])}</h${n}>`); continue; }
    if ((m = line.match(/^&gt;\s?(.*)$/))) { flush(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if ((m = line.match(/^\s*[-*]\s+(.*)$/)) || (m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      const kind = /^\s*\d/.test(line) ? "ol" : "ul";
      if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; }
      if (list !== kind) { if (list) out.push(`</${list}>`); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline(m[1])}</li>`);
      continue;
    }
    if (list) { out.push(`</${list}>`); list = null; }
    para.push(line.trim());
  }
  flush();
  return out.join("");
}

// ------------------------------------------------------------------ pieces
const dateText = (ts) => new Date(ts * 1000).toLocaleDateString([], { year: "numeric", month: "long", day: "numeric" });
const CAT_LABEL = { news: "News", guide: "Guide", faq: "FAQ" };

function joinCard(site) {
  const rows = [];
  if (site.java_address) rows.push(["Java Edition", site.java_address, ""]);
  if (site.bedrock_address) rows.push(["Bedrock Edition", site.bedrock_address, `Port ${site.bedrock_port}`]);
  if (!rows.length) return "";
  return `<section class="hp-join glass"><h2>Join the server</h2>
    <div class="hp-join-rows">${rows.map(([ed, addr, extra]) => `<div class="hp-join-row">
      <span class="hp-ed">${esc(ed)}</span><code class="hp-addr">${esc(addr)}</code>${extra ? `<span class="muted">${esc(extra)}</span>` : ""}
      <button class="btn sm" type="button" data-copy="${esc(addr)}">Copy</button></div>`).join("")}</div>
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
  return `<section class="hp-hero"><h1>${esc(s.name)}</h1>${s.tagline ? `<p class="hp-tagline">${esc(s.tagline)}</p>` : ""}</section>
    <p class="hp-ask-status" id="ask-status" hidden></p>
    ${joinCard(s)}${serversCard(s)}
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
  try { p = await getJSON(`/api/public/posts/${encodeURIComponent(slug)}`); } catch { return `<section><h1>Not found</h1><p class="muted">That post isn't here any more. <a href="/">Back home</a></p></section>`; }
  const back = { news: ["/news", "News"], guide: ["/help", "Help"], faq: ["/help", "Help"] }[p.category] || ["/", "Home"];
  document.title = `${p.title} · ${hp.site.name}`;
  return `<article class="hp-article glass"><a class="back" href="${back[0]}">← ${esc(back[1])}</a>
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
async function showAskStatus() {
  const box = $("#ask-status"), t = askTicket();
  if (!box || !t?.token) return;
  let d = null;
  try {
    const r = await fetch("/api/public/join-request/status", { method: "POST", headers: { "Content-Type": "application/json", "X-Solstone": "1" }, body: JSON.stringify({ token: t.token }) });
    d = r.ok ? await r.json() : null;
  } catch { return; }
  if (!d || d.state === "unknown") { try { localStorage.removeItem("solstone-ask"); } catch { /* fine */ } return; }
  box.hidden = false;
  box.className = `hp-ask-status ${d.state}`;
  box.innerHTML = d.state === "in"
    ? `🎉 <b>${esc(d.player)}</b>, you're in! Join the server now. <button type="button" class="link-btn" data-ask-forget>Hide this</button>`
    : `⏳ Your request for <b>${esc(d.player)}</b> is waiting for an admin. Check back here later.`;
}
document.addEventListener("click", (e) => {
  if (!e.target.closest("[data-ask-forget]")) return;
  try { localStorage.removeItem("solstone-ask"); } catch { /* fine */ }
  $("#ask-status").hidden = true;
});

// Ask to join: their name goes to the admins' notifications, ready to let in from Control.
function askFormHtml() {
  return `<section class="hp-ask glass" id="ask"><h2>Ask to join</h2>
    <p class="hp-ask-status" id="ask-status" hidden></p>
    <p class="muted">The admins get a message with your name and can let you in. Then try joining again.</p>
    <form id="ask-form" autocomplete="off">
      <fieldset class="hp-ask-ed"><legend>I play on</legend>
        <label class="check"><input type="radio" name="edition" value="java" checked> Java (PC or Mac)</label>
        <label class="check"><input type="radio" name="edition" value="bedrock"> Bedrock (phone, tablet, console, Windows)</label></fieldset>
      <label>Your name in the game <small>Exactly as it shows. On Bedrock that's your Xbox gamertag.</small><input class="input" name="player" required maxlength="20" autocapitalize="off"></label>
      <label>Your first name <small>Optional, so the admins know who you are</small><input class="input" name="name" maxlength="40"></label>
      <label>A note <small>Optional: who you know here, for example</small><textarea class="input" name="note" rows="3" maxlength="300"></textarea></label>
      <p class="login-error" role="alert"></p>
      <button class="btn primary" type="submit">Send</button></form></section>`;
}
document.addEventListener("submit", async (e) => {
  if (e.target.id !== "ask-form") return;
  e.preventDefault();
  const f = new FormData(e.target), err = $(".login-error", e.target);
  try {
    const r = await fetch("/api/public/join-request", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Solstone": "1" },
      body: JSON.stringify({ edition: f.get("edition"), player: f.get("player"), name: f.get("name"), note: f.get("note") }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "That didn't send. Try again in a moment.");
    try { localStorage.setItem("solstone-ask", JSON.stringify({ token: d.token, player: d.player })); } catch { /* private window */ }
    e.target.outerHTML = `<p class="hp-ask-done">✅ ${esc(d.message)}</p>`;
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
