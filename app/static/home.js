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

function toast(text) {
  const t = $("#hp-toast");
  t.textContent = text; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, 2500);
}

// ------------------------------------------------------------------ Markdown (a safe subset)
function inline(s) {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])[*_]([^*_]+)[*_](?=[\s).,!?:;]|$)/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\(((?:https?:\/\/|\/(?!\/))[^\s)]*)\)/g, (_, t, href) =>
      `<a href="${href}"${href.startsWith("/") ? "" : ' target="_blank" rel="noopener"'}>${t}</a>`);
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

function serversCard(site) {
  if (!site.servers.length) return "";
  return `<section class="hp-servers"><h2>Servers</h2><div class="hp-server-list">${site.servers.map((s) => `
    <a class="hp-server glass" href="${site.status_page ? `/status/${encodeURIComponent(s.id)}` : "#"}" ${site.status_page ? "" : 'aria-disabled="true"'}>
      ${s.has_icon ? `<img class="px" src="/api/public/icon/${encodeURIComponent(s.id)}.png" alt="" width="40" height="40">` : ""}
      <span class="hp-server-name">${esc(s.name)}</span>
      <span class="hp-dot ${s.running ? "on" : ""}" aria-hidden="true"></span>
      <span class="muted">${s.running ? `${s.online} / ${s.max} online` : "Offline"}${s.version ? ` · ${esc(s.version)}` : ""}</span>
    </a>`).join("")}</div></section>`;
}

function postCards(posts, empty) {
  if (!posts.length) return `<p class="muted">${esc(empty)}</p>`;
  return `<div class="hp-posts">${posts.map((p) => `<a class="hp-post glass" href="${p.builtin ? `/guides/${p.slug}` : `/post/${encodeURIComponent(p.slug)}`}">
    <span class="hp-post-meta">${p.builtin ? "Guide · Start here" : `${esc(CAT_LABEL[p.category] || "")}${p.pinned ? " · 📌" : ""} · ${esc(dateText(p.created))}`}</span>
    <h3>${esc(p.title)}</h3><p class="muted">${esc(p.excerpt || "")}</p></a>`).join("")}</div>`;
}

function faqList(posts) {
  if (!posts.length) return `<p class="muted">No questions yet.</p>`;
  return `<div class="hp-faq">${posts.map((p) => `<details class="glass"><summary>${esc(p.title)}</summary>
    <div class="hp-body" data-faq="${esc(p.slug)}"><p class="muted">Loading…</p></div></details>`).join("")}</div>`;
}

// ------------------------------------------------------------------ built-in guides
// Always there, written from Site details, so the two questions every new player asks are answered.
const BUILTIN = {
  join: {
    title: "How to join the server",
    excerpt: "Step by step on Java (PC) and Bedrock (phone, tablet, Windows, console).",
    body: (s) => {
      const java = s.java_address || "the address an admin gives you";
      const bed = s.bedrock_address || s.java_address || "the address an admin gives you";
      const ask = s.discord ? ` (ask on [Discord](${s.discord}))` : "";
      return `${s.name} is a Minecraft server you can join from Java Edition or Bedrock Edition. They play together in the same world.

## First: get on the list
The server only lets in people on its whitelist. Send your exact in-game name to an admin${ask}. On Bedrock that's your Xbox gamertag.

## Java Edition (Windows, Mac, Linux)
1. Open Minecraft: Java Edition and choose **Multiplayer**.
2. Choose **Add Server**. Give it any name, and type **${java}** as the Server Address.
3. Choose **Done**, then pick the server and **Join Server**.

## Bedrock Edition (phone, tablet, Windows, Xbox, PlayStation, Switch)
1. Open Minecraft and choose **Play**, then the **Servers** tab.
2. Scroll down and choose **Add Server**.
3. Give it any name. Server Address: **${bed}**. Port: **${s.bedrock_port}**.
4. Choose **Save**, then join it. You sign in with your Microsoft (Xbox) account as usual.

Good to know on Bedrock:
- Your name on the server starts with a dot, like *.Steve*. That's how the server tells Bedrock players apart, and it's the name to use on this website.
- Xbox, PlayStation and Switch don't have **Add Server** for outside servers. A common way round it is *BedrockConnect*: search for it to find the steps for your console. Or join from a phone, tablet or Windows PC instead.
- A few things added by mods on the server can look different, or be missing, on Bedrock.

## It won't let me in
- **"You are not white-listed"**: you're not on the list yet. Send an admin your exact name.
- **Can't connect / timed out**: check the address${s.bedrock_address ? " and port" : ""} for typos, and that the server is running${s.status_page ? " ([live status](/status))" : ""}.
- **Outdated client or server**: update Minecraft to the newest version.`;
    },
  },
  account: {
    title: "Making an account on this website",
    excerpt: "See the servers, leaderboards and your own stats. Takes a minute, from inside the game.",
    body: (s) => s.signup ? `Your account here shows the servers, who's on, the leaderboards, fishing, and your own page: your inventory, stats and play time.

## Make one
1. Join the server and stay in the game (see [How to join](/guides/join)).
2. Go to [Sign in](/app) and choose **Make an account**.
3. Type your Minecraft name as it shows in the game. On Bedrock it starts with a dot, like *.Steve*.
4. A six-digit code appears in your game chat. Only you can see it, and it works for 10 minutes.
5. Type the code, then pick a username and password for this website. **Don't use your Microsoft password.**

## Good to know
- Each Minecraft player can have one account.
- Forgot your password? Ask an admin to set a new one.
- Never share your code or password. Admins will never ask for them.` : `Accounts on this website are made by an admin. Ask one for a login${s.discord ? ` on [Discord](${s.discord})` : ""}.`,
  },
};

function builtinCards() {
  return Object.entries(BUILTIN).map(([k, g]) => ({ slug: k, title: g.title, excerpt: g.excerpt, builtin: true }));
}

// ------------------------------------------------------------------ pages
async function home() {
  const s = hp.site;
  const [news, guides] = await Promise.all([getJSON("/api/public/posts?category=news&limit=3"), getJSON("/api/public/posts?category=guide&limit=4")]);
  return `<section class="hp-hero"><h1>${esc(s.name)}</h1>${s.tagline ? `<p class="hp-tagline">${esc(s.tagline)}</p>` : ""}</section>
    ${joinCard(s)}${serversCard(s)}
    <section><div class="hp-head"><h2>News</h2><a href="/news">All news →</a></div>${postCards(news, "No news yet.")}</section>
    <section><div class="hp-head"><h2>Help</h2><a href="/help">All guides and questions →</a></div>${postCards([...builtinCards(), ...guides].slice(0, 4), "")}</section>
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
    <h1>${esc(g.title)}</h1><div class="hp-body">${markdown(g.body(hp.site))}</div></article>`;
}

async function route() {
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
  if (location.hash === "#faq") $("#faq")?.scrollIntoView(); else window.scrollTo(0, 0);
}

// Links inside the site change the page without a reload; everything else is a normal link.
document.addEventListener("click", (e) => {
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    navigator.clipboard?.writeText(copy.dataset.copy).then(() => toast("Copied"), () => toast(copy.dataset.copy));
    return;
  }
  const a = e.target.closest("a[href]");
  if (!a || a.target || e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;
  const url = new URL(a.href, location.href);
  if (url.origin !== location.origin) return;
  if (url.pathname === "/" || url.pathname.startsWith("/post/") || url.pathname.startsWith("/guides") || url.pathname === "/faq" || SECTIONS[url.pathname.slice(1)]) {
    e.preventDefault();
    if (url.pathname !== location.pathname) history.pushState(null, "", url.pathname);
    route();
  }
});
window.addEventListener("popstate", route);

// FAQ answers load when opened.
document.addEventListener("toggle", async (e) => {
  const box = e.target.querySelector?.("[data-faq]");
  if (!e.target.open || !box || box.dataset.loaded) return;
  box.dataset.loaded = "1";
  try { box.innerHTML = markdown((await getJSON(`/api/public/posts/${encodeURIComponent(box.dataset.faq)}`)).body); }
  catch { box.innerHTML = `<p class="muted">Couldn't load the answer.</p>`; }
}, true);

document.addEventListener("DOMContentLoaded", async () => {
  try { hp.site = await getJSON("/api/public/site"); } catch { hp.site = { name: "Solstone", servers: [], status_page: false }; }
  $("#hp-name").textContent = $("#hp-foot-name").textContent = hp.site.name;
  $("#hp-status-link").hidden = !hp.site.status_page;
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
