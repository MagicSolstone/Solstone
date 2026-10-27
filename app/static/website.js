/* Solstone — Website (admins): the public site's details (how to join, Discord, about) and its
   posts (news, guides and FAQ). What's saved here shows on the home page at /. Loaded after app.js. */
"use strict";

// News goes on the News page; guides and questions (FAQ) both go on the Help page.
const WS_CATS = [["news", "News"], ["guide", "Help: a guide"], ["faq", "Help: a question"]];
const ws = { data: null, editing: null, tab: "posts" };

async function viewWebsite() {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = `Website · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  ws.data = await api("/api/posts");
  ws.editing = null;
  setView(`<div class="fwe-head"><h1>Website</h1>
      <p class="muted">The public home page at <a href="/" target="_blank" rel="noopener">/</a>: how to join, News, and Help (guides and questions). Anyone can read it without signing in; private servers never show there.</p></div>
    <nav class="fwe-tabs fws-tabs" role="tablist" aria-label="Website">
      <button type="button" role="tab" data-tab="posts" aria-selected="${ws.tab === "posts"}">Posts</button>
      <button type="button" role="tab" data-tab="site" aria-selected="${ws.tab === "site"}">Site details</button>
      <button type="button" role="tab" data-tab="guides" aria-selected="${ws.tab === "guides"}">Join and account guides</button></nav>
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
  if (ws.tab === "site") wsSite(el); else if (ws.tab === "guides") wsGuides(el); else wsPosts(el);
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
    <div class="btn-row ws-insert"><label class="btn sm ws-file">🖼 Add a picture<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" data-pic hidden></label>
      <button type="button" class="btn sm" data-link>🔗 Add a link</button>
      <small class="muted">The first picture also shows on the post's card. Under 4 MB each.</small></div>
    <div class="actions"><button type="button" class="btn" data-cancel>Cancel</button><button class="btn primary" type="submit">${p.id ? "Save" : "Publish"}</button></div>
  </form>`;
}

function wsPosts(el) {
  const posts = ws.data.posts;
  const rows = posts.map((p) => ws.editing === p.id ? wsEditHtml(p) : `<div class="ws-post" data-id="${p.id}">
      <div><b>${esc(p.title)}</b>${p.pinned ? " 📌" : ""}<div class="muted">${esc(WS_CATS.find(([k]) => k === p.category)?.[1] || "")} · ${esc(wsDate(p.created))}${p.published ? "" : " · <b>Draft</b>"}</div></div>
      <span class="btn-row">${p.published ? `<a class="btn sm" href="/post/${encodeURIComponent(p.slug)}" target="_blank" rel="noopener">View</a>` : ""}
        <button class="btn sm" type="button" data-edit>Edit</button><button class="btn sm danger" type="button" data-del>Delete</button></span></div>`).join("");
  el.innerHTML = `<section class="panel"><div class="ws-list">${rows || `<p class="muted">No posts yet. News is for updates and events. On the Help page, guides are for how-tos (the rules, starting out) and questions are for quick answers.</p>`}</div>
    ${ws.editing === "new" ? wsEditHtml({ category: "news", published: true }) : `<button class="btn primary" id="ws-new" style="margin-top:12px">+ New post</button>`}</section>`;
  $("#ws-new")?.addEventListener("click", () => { ws.editing = "new"; renderWebsite(); $("#ws-edit input[name=title]")?.focus(); });
  el.querySelectorAll(".ws-post[data-id]").forEach((row) => {
    const id = +row.dataset.id;
    row.querySelector("[data-edit]").addEventListener("click", () => { ws.editing = id; renderWebsite(); });
    row.querySelector("[data-del]").addEventListener("click", async (e) => {
      const b = e.currentTarget;
      if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Really delete?"; return; }
      try { await api(`/api/posts/${id}`, { method: "DELETE" }); showToast("Deleted", 2000); ws.data = await api("/api/posts"); renderWebsite(); }
      catch (err) { showError(esc(err.message), 5000); }
    });
  });
  const form = $("#ws-edit");
  if (!form) return;
  form.querySelector("[data-cancel]").addEventListener("click", () => { ws.editing = null; renderWebsite(); });
  // Put text in where the cursor is (on a line of its own for a picture).
  const ta = form.querySelector("textarea[name=body]");
  const insert = (text, ownLine) => {
    const a = ta.selectionStart ?? ta.value.length, b = ta.selectionEnd ?? a, before = ta.value.slice(0, a), after = ta.value.slice(b);
    const pre = ownLine && before && !before.endsWith("\n\n") ? (before.endsWith("\n") ? "\n" : "\n\n") : "";
    const post = ownLine ? "\n\n" : "";
    ta.value = before + pre + text + post + after;
    const at = (before + pre + text).length;
    ta.focus(); ta.setSelectionRange(at, at);
  };
  form.querySelector("[data-pic]").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try {
      const r = await fetch("/api/posts/images", { method: "POST", credentials: "same-origin", headers: { "X-Solstone": "1", "Content-Type": f.type || "application/octet-stream" }, body: f });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `Upload failed (${r.status})`);
      insert(`![${f.name.replace(/\.[^.]+$/, "").replace(/[\[\]]/g, "")}](${d.url})`, true);
      showToast("Picture added", 1500);
    } catch (err) { showError(esc(err.message), 5000); }
    e.target.value = "";
  });
  form.querySelector("[data-link]").addEventListener("click", () => {
    const sel = ta.value.slice(ta.selectionStart, ta.selectionEnd) || "the words to click";
    insert(`[${sel}](https://)`, false);
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(form);
    const body = { title: f.get("title"), category: f.get("category"), body: f.get("body"), published: !!f.get("published"), pinned: !!f.get("pinned") };
    try {
      if (ws.editing === "new") await post("/api/posts", body); else await post(`/api/posts/${ws.editing}`, body, "PUT");
      showToast(body.published ? "Saved — it's on the website" : "Saved as a draft", 2500);
      ws.editing = null; ws.data = await api("/api/posts"); renderWebsite();
    } catch (err) { showError(esc(err.message), 5000); }
  });
}

// ---------------------------------------------------------------- site details
function wsSite(el) {
  const s = ws.data.site;
  el.innerHTML = `<form class="panel ws-site" id="ws-site">
    <div class="ws-logo"><img src="${esc(ws.data.logo || SITE_LOGO)}" alt="The site's logo" width="64" height="64" id="ws-logo-img">
      <div><b>Logo</b><small class="muted">A square picture works best (PNG, JPEG, WebP or GIF, under 1 MB). It shows beside the name and in the browser tab.</small>
        <span class="btn-row"><label class="btn sm ws-file">Choose a picture<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" id="ws-logo-file" hidden></label>
          <button type="button" class="btn sm" id="ws-logo-reset">Use Solstone's</button></span></div></div>
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
  $("#ws-logo-file").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try {
      const r = await fetch("/api/settings/site/logo", { method: "POST", credentials: "same-origin", headers: { "X-Solstone": "1", "Content-Type": f.type || "application/octet-stream" }, body: f });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `Upload failed (${r.status})`);
      ws.data.logo = d.logo; $("#ws-logo-img").src = d.logo; showToast("Logo saved. Reload to see it everywhere.", 3000);
    } catch (err) { showError(esc(err.message), 5000); }
  });
  $("#ws-logo-reset").addEventListener("click", async () => {
    try { const d = await post("/api/settings/site/logo", {}, "DELETE"); ws.data.logo = d.logo; $("#ws-logo-img").src = d.logo; showToast("Back to Solstone's logo", 2500); }
    catch (err) { showError(esc(err.message), 5000); }
  });
  $("#ws-site").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = Object.fromEntries(["name", "tagline", "java_address", "bedrock_address", "bedrock_port", "discord", "about"].map((k) => [k, f.get(k)]));
    body.home_live = !!f.get("home_live");
    try { ws.data.site = await post("/api/settings/site", body, "PUT"); showToast("Saved", 2000); renderWebsite(); }
    catch (err) { showError(esc(err.message), 5000); }
  });
}

// ---------------------------------------------------------------- the two built-in guides, in your own words
function wsGuides(el) {
  const s = ws.data.site;
  const box = (key) => `<section class="panel ws-guide" data-guide="${key}"><div class="section-head"><h2>${esc(GUIDES[key].title)}</h2>
      <a class="muted small" href="/guides/${key}" target="_blank" rel="noopener">Open it</a></div>
    <p class="muted small">${s[`guide_${key}`] ? "Your own wording." : "Solstone's wording, which follows Site details by itself. Start from it to make it your own."}</p>
    <textarea class="input ws-text" rows="16" maxlength="8000" data-guide-text placeholder="Empty: Solstone's wording">${esc(s[`guide_${key}`] || "")}</textarea>
    <div class="btn-row"><button type="button" class="btn sm" data-start>Start from Solstone's wording</button>
      <button type="button" class="btn sm" data-clear>Back to Solstone's wording</button></div></section>`;
  el.innerHTML = `<form id="ws-guides" class="ws-guides">
    <section class="panel"><label class="switch-row"><span><b>An “Ask to join” form on the join guide</b><br><small class="muted">Anyone can send their name in the game (and, if they like, their first name and a note). You get a notification, and they show in a server's Control → Whitelist, ready to let in. ${ws.data.notify_ready === false ? "<b>Set up notifications first (Manage → Notifications)</b>, or the messages only show in Control." : ""}</small></span>
      <input type="checkbox" role="switch" name="join_requests" ${s.join_requests ? "checked" : ""}></label></section>
    <p class="muted small">Same formatting as posts. These fill themselves in from Site details: ${GUIDE_PLACEHOLDERS.map(([k, l]) => `<code>{${k}}</code> ${esc(l.toLowerCase())}`).join(", ")}.</p>
    ${box("join")}${box("account")}
    <div class="actions"><button class="btn primary" type="submit">Save guides</button></div></form>`;
  $$(".ws-guide").forEach((sec) => {
    const key = sec.dataset.guide, ta = $("[data-guide-text]", sec);
    $("[data-start]", sec).addEventListener("click", () => { if (!ta.value.trim() || confirm("Replace what's there with Solstone's wording?")) ta.value = guideTemplate(key, { ...s, join_requests: $('[name="join_requests"]').checked }); });
    $("[data-clear]", sec).addEventListener("click", () => { ta.value = ""; });
  });
  $("#ws-guides").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { join_requests: e.target.join_requests.checked };
    $$(".ws-guide").forEach((sec) => { body[`guide_${sec.dataset.guide}`] = $("[data-guide-text]", sec).value; });
    try { ws.data.site = await post("/api/settings/site", body, "PUT"); showToast("Guides saved", 2000); renderWebsite(); }
    catch (err) { showError(esc(err.message), 5000); }
  });
}
