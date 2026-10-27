/* Solstone — Website (admins): the public site's details (how to join, Discord, about) and its
   posts (news, guides and FAQ). What's saved here shows on the home page at /. Loaded after app.js. */
"use strict";

const WS_CATS = [["news", "News"], ["guide", "Guide"], ["faq", "FAQ"]];
const ws = { data: null, editing: null, tab: "posts" };

async function viewWebsite() {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = `Website · ${SITE_NAME}`;
  $("#rail-servers").innerHTML = railHtml(null);
  ws.data = await api("/api/posts");
  ws.editing = null;
  setView(`<div class="fwe-head"><h1>Website</h1>
      <p class="muted">The public home page at <a href="/" target="_blank" rel="noopener">/</a>: how to join, news, guides and FAQ. Anyone can read it without signing in; private servers never show there.</p></div>
    <nav class="fwe-tabs fws-tabs" role="tablist" aria-label="Website">
      <button type="button" role="tab" data-tab="posts" aria-selected="${ws.tab === "posts"}">Posts</button>
      <button type="button" role="tab" data-tab="site" aria-selected="${ws.tab === "site"}">Site details</button></nav>
    <div id="ws-body"></div>`);
  $$(".fws-tabs [data-tab]").forEach((b) => b.addEventListener("click", () => {
    ws.tab = b.dataset.tab; ws.editing = null;
    $$(".fws-tabs [data-tab]").forEach((x) => x.setAttribute("aria-selected", String(x === b))); renderWebsite();
  }));
  renderWebsite();
}

function renderWebsite() {
  const el = $("#ws-body");
  if (!el) return;
  if (ws.tab === "site") wsSite(el); else wsPosts(el);
}

// ---------------------------------------------------------------- posts
const wsDate = (ts) => new Date(ts * 1000).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });

function wsEditHtml(p) {
  return `<form class="ws-edit panel" id="ws-edit">
    <label>Title<input class="input" name="title" maxlength="120" required value="${esc(p.title || "")}"></label>
    <div class="ws-row"><label>Kind<select class="input" name="category">${WS_CATS.map(([k, l]) => `<option value="${k}" ${p.category === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="check"><input type="checkbox" name="published" ${p.published !== false ? "checked" : ""}> Published <small>Off keeps it a draft only admins see</small></label>
      <label class="check"><input type="checkbox" name="pinned" ${p.pinned ? "checked" : ""}> Pinned <small>Stays at the top</small></label></div>
    <label>Text <small>Plain text with a little formatting: # Heading, **bold**, *italic*, - lists, [a link](https://...), &gt; a quote. A blank line starts a new paragraph.</small>
      <textarea class="input ws-text" name="body" rows="14" maxlength="20000" required>${esc(p.body || "")}</textarea></label>
    <div class="actions"><button type="button" class="btn" data-cancel>Cancel</button><button class="btn primary" type="submit">${p.id ? "Save" : "Publish"}</button></div>
  </form>`;
}

function wsPosts(el) {
  const posts = ws.data.posts;
  const rows = posts.map((p) => ws.editing === p.id ? wsEditHtml(p) : `<div class="ws-post" data-id="${p.id}">
      <div><b>${esc(p.title)}</b>${p.pinned ? " 📌" : ""}<div class="muted">${esc(WS_CATS.find(([k]) => k === p.category)?.[1] || "")} · ${esc(wsDate(p.created))}${p.published ? "" : " · <b>Draft</b>"}</div></div>
      <span class="btn-row">${p.published ? `<a class="btn sm" href="/post/${encodeURIComponent(p.slug)}" target="_blank" rel="noopener">View</a>` : ""}
        <button class="btn sm" type="button" data-edit>Edit</button><button class="btn sm danger" type="button" data-del>Delete</button></span></div>`).join("");
  el.innerHTML = `<section class="panel"><div class="ws-list">${rows || `<p class="muted">No posts yet. News is good for updates and events; guides for how-tos (joining on Bedrock, the rules, starting out); FAQ for quick questions.</p>`}</div>
    ${ws.editing === "new" ? wsEditHtml({ category: "news", published: true }) : `<button class="btn primary" id="ws-new" style="margin-top:12px">+ New post</button>`}</section>`;
  $("#ws-new")?.addEventListener("click", () => { ws.editing = "new"; renderWebsite(); $("#ws-edit input[name=title]")?.focus(); });
  el.querySelectorAll(".ws-post[data-id]").forEach((row) => {
    const id = +row.dataset.id;
    row.querySelector("[data-edit]").addEventListener("click", () => { ws.editing = id; renderWebsite(); });
    row.querySelector("[data-del]").addEventListener("click", async (e) => {
      const b = e.currentTarget;
      if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Really delete?"; return; }
      try { await api(`/api/posts/${id}`, { method: "DELETE" }); showToast("Deleted", 2000); ws.data = await api("/api/posts"); renderWebsite(); }
      catch (err) { showToast(esc(err.message), 5000); }
    });
  });
  const form = $("#ws-edit");
  if (!form) return;
  form.querySelector("[data-cancel]").addEventListener("click", () => { ws.editing = null; renderWebsite(); });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(form);
    const body = { title: f.get("title"), category: f.get("category"), body: f.get("body"), published: !!f.get("published"), pinned: !!f.get("pinned") };
    try {
      if (ws.editing === "new") await post("/api/posts", body); else await post(`/api/posts/${ws.editing}`, body, "PUT");
      showToast(body.published ? "Saved — it's on the website" : "Saved as a draft", 2500);
      ws.editing = null; ws.data = await api("/api/posts"); renderWebsite();
    } catch (err) { showToast(esc(err.message), 5000); }
  });
}

// ---------------------------------------------------------------- site details
function wsSite(el) {
  const s = ws.data.site;
  el.innerHTML = `<form class="panel ws-site" id="ws-site">
    <label>Site name<input class="input" name="name" maxlength="80" value="${esc(s.name)}"></label>
    <label>Tagline <small>One line under the name</small><input class="input" name="tagline" maxlength="160" value="${esc(s.tagline)}" placeholder="A family Minecraft server"></label>
    <div class="ws-row"><label>Java address<input class="input" name="java_address" maxlength="80" value="${esc(s.java_address)}" placeholder="play.example.net"></label>
      <label>Bedrock address<input class="input" name="bedrock_address" maxlength="80" value="${esc(s.bedrock_address)}" placeholder="play.example.net"></label>
      <label>Bedrock port<input class="input" name="bedrock_port" inputmode="numeric" value="${esc(s.bedrock_port)}"></label></div>
    <label>Discord invite <small>A discord.gg or discord.com link</small><input class="input" name="discord" maxlength="200" value="${esc(s.discord)}" placeholder="https://discord.gg/..."></label>
    <label>About <small>Shown at the bottom of the home page. Same formatting as posts.</small><textarea class="input" name="about" rows="6" maxlength="4000">${esc(s.about)}</textarea></label>
    <label class="check"><input type="checkbox" name="home_live" ${s.home_live ? "checked" : ""}> Show the public servers' status on the home page <small>Running or not and how many are on. Private servers are never shown.</small></label>
    <div class="actions"><a class="btn" href="/" target="_blank" rel="noopener">Open the home page</a><button class="btn primary" type="submit">Save</button></div>
  </form>`;
  $("#ws-site").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = Object.fromEntries(["name", "tagline", "java_address", "bedrock_address", "bedrock_port", "discord", "about"].map((k) => [k, f.get(k)]));
    body.home_live = !!f.get("home_live");
    try { ws.data.site = await post("/api/settings/site", body, "PUT"); showToast("Saved", 2000); renderWebsite(); }
    catch (err) { showToast(esc(err.message), 5000); }
  });
}
