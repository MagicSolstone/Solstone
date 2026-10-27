/* Solstone — the public home page and its posts (News, Guides, FAQ). No sign-in.
   Everything comes from /api/public/site and /api/public/posts; private servers never appear there.
   Post text is a small subset of Markdown, escaped first and then formatted, so it can't carry HTML. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const hp = { site: null };
const SECTIONS = { news: ["News", "news"], guides: ["Guides", "guide"], faq: ["FAQ", "faq"] };

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
    ${site.discord ? `<p class="muted">Questions? <a href="${esc(site.discord)}" target="_blank" rel="noopener">Join us on Discord</a>.</p>` : ""}</section>`;
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
  return `<div class="hp-posts">${posts.map((p) => `<a class="hp-post glass" href="/post/${encodeURIComponent(p.slug)}">
    <span class="hp-post-meta">${esc(CAT_LABEL[p.category] || "")}${p.pinned ? " · 📌" : ""} · ${esc(dateText(p.created))}</span>
    <h3>${esc(p.title)}</h3><p class="muted">${esc(p.excerpt || "")}</p></a>`).join("")}</div>`;
}

function faqList(posts) {
  if (!posts.length) return `<p class="muted">No questions yet.</p>`;
  return `<div class="hp-faq">${posts.map((p) => `<details class="glass"><summary>${esc(p.title)}</summary>
    <div class="hp-body" data-faq="${esc(p.slug)}"><p class="muted">Loading…</p></div></details>`).join("")}</div>`;
}

// ------------------------------------------------------------------ pages
async function home() {
  const s = hp.site;
  const [news, guides] = await Promise.all([getJSON("/api/public/posts?category=news&limit=3"), getJSON("/api/public/posts?category=guide&limit=4")]);
  return `<section class="hp-hero"><h1>${esc(s.name)}</h1>${s.tagline ? `<p class="hp-tagline">${esc(s.tagline)}</p>` : ""}</section>
    ${joinCard(s)}${serversCard(s)}
    <section><div class="hp-head"><h2>News</h2><a href="/news">All news →</a></div>${postCards(news, "No news yet.")}</section>
    ${guides.length ? `<section><div class="hp-head"><h2>Guides</h2><a href="/guides">All guides →</a></div>${postCards(guides, "")}</section>` : ""}
    ${s.about ? `<section class="hp-about glass"><h2>About</h2><div class="hp-body">${markdown(s.about)}</div></section>` : ""}`;
}

async function section(key) {
  const [title, cat] = SECTIONS[key];
  const posts = await getJSON(`/api/public/posts?category=${cat}&limit=100`);
  return `<section><h1>${esc(title)}</h1>${cat === "faq" ? faqList(posts) : postCards(posts, `No ${title.toLowerCase()} yet.`)}</section>`;
}

async function article(slug) {
  let p;
  try { p = await getJSON(`/api/public/posts/${encodeURIComponent(slug)}`); } catch { return `<section><h1>Not found</h1><p class="muted">That post isn't here any more. <a href="/">Back home</a></p></section>`; }
  const back = { news: ["/news", "News"], guide: ["/guides", "Guides"], faq: ["/faq", "FAQ"] }[p.category] || ["/", "Home"];
  document.title = `${p.title} · ${hp.site.name}`;
  return `<article class="hp-article glass"><a class="back" href="${back[0]}">← ${esc(back[1])}</a>
    <h1>${esc(p.title)}</h1><p class="hp-post-meta">${esc(dateText(p.created))}${p.author ? ` · ${esc(p.author)}` : ""}</p>
    <div class="hp-body">${markdown(p.body)}</div></article>`;
}

async function route() {
  const path = location.pathname.replace(/\/+$/, "") || "/";
  const main = $("#hp-main");
  let nav = "home", html;
  try {
    if (path === "/") html = await home();
    else if (path.startsWith("/post/")) { nav = ""; html = await article(decodeURIComponent(path.slice(6))); }
    else if (SECTIONS[path.slice(1)]) { nav = path.slice(1); html = await section(nav); }
    else { nav = ""; html = `<section><h1>Not found</h1><p class="muted"><a href="/">Back home</a></p></section>`; }
  } catch {
    html = `<section><h1>Couldn't load this page</h1><p class="muted">Try again in a moment.</p></section>`;
  }
  if (!path.startsWith("/post/")) document.title = nav && nav !== "home" ? `${SECTIONS[nav][0]} · ${hp.site.name}` : hp.site.name;
  main.innerHTML = html;
  document.querySelectorAll("[data-nav]").forEach((a) => a.toggleAttribute("aria-current", a.dataset.nav === nav));
  window.scrollTo(0, 0);
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
  if (url.pathname === "/" || url.pathname.startsWith("/post/") || SECTIONS[url.pathname.slice(1)]) {
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
  const sky = $("#home-sky");
  if (sky && typeof startSkyScene === "function") hp.scene = startSkyScene(sky, { auto: false, dim: () => 0.35 });
  if (typeof startBoard === "function") startBoard($("#hp-board"), { where: "home", sid: () => "", scene: () => hp.scene, max: innerWidth < 700 ? 1 : 3 });
  route();
});
