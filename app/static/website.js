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
      <button type="button" role="tab" data-tab="guides" aria-selected="${ws.tab === "guides"}">Rules and guides</button>
      <button type="button" role="tab" data-tab="welcome" aria-selected="${ws.tab === "welcome"}">Welcome in the game</button></nav>
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
  if (ws.tab === "site") wsSite(el); else if (ws.tab === "guides") wsGuides(el); else if (ws.tab === "welcome") wsWelcome(el); else wsPosts(el);
}

// ---------------------------------------------------------------- posts
const wsDate = (ts) => new Date(ts * 1000).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });

const wsSaveLabel = (saved, published) => (published ? (saved ? "Save" : "Publish") : "Save draft");

function wsEditHtml(p) {
  return `<form class="ws-edit panel" id="ws-edit">
    <label>Title<input class="input" name="title" maxlength="120" required value="${esc(p.title || "")}"></label>
    <div class="ws-row"><label>Kind<select class="input" name="category">${WS_CATS.map(([k, l]) => `<option value="${k}" ${p.category === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="check"><input type="checkbox" name="published" ${p.published !== false ? "checked" : ""}> Published <small>Off keeps it a draft only admins see</small></label>
      <label class="check"><input type="checkbox" name="pinned" ${p.pinned ? "checked" : ""}> Pinned <small>Stays at the top</small></label></div>
    <div class="ws-fmt" role="toolbar" aria-label="Formatting">
      <button type="button" class="btn sm" data-wrap="**" title="Bold"><b>B</b></button>
      <button type="button" class="btn sm" data-wrap="*" title="Italic"><i>I</i></button>
      <select class="input sm" data-line aria-label="Heading"><option value="">Heading…</option><option value="# ">Heading</option><option value="## ">Subheading</option><option value="### ">Small heading</option></select>
      <select class="input sm" data-style aria-label="Colour"><option value="">Colour…</option>${POST_COLOURS.map(([k, l]) => `<option value="${k}" class="pf-${k}">${l}</option>`).join("")}</select>
      <select class="input sm" data-style aria-label="Size"><option value="">Size…</option>${POST_SIZES.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
      <button type="button" class="btn sm" data-prefix="- " title="A list with dots">• List</button>
      <button type="button" class="btn sm" data-prefix="1. " title="A numbered list">1. List</button>
      <button type="button" class="btn sm" data-prefix="&gt; " title="A quote">❝ Quote</button>
      <button type="button" class="btn sm" data-rule title="A line across">― Line</button>
      <button type="button" class="btn sm" data-link>🔗 Link</button>
      <label class="btn sm ws-file">🖼 Picture<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" data-pic hidden></label></div>
    <div class="ws-compose">
      <label class="ws-compose-text">Text <small>Select some text, then pick a button. Or type the marks yourself: **bold**, # Heading, {red}colour{/red}.</small>
        <textarea class="input ws-text" name="body" rows="16" maxlength="20000" required>${esc(p.body || "")}</textarea></label>
      <div class="ws-compose-view"><span class="ws-compose-label">How it looks</span><div class="hp-body ws-live" aria-live="off"></div></div></div>
    <small class="muted">Enter starts a new line; a blank line starts a new paragraph. The first picture also shows on the post's card. Pictures under 4 MB each.</small>
    <div class="actions"><button type="button" class="btn" data-preview title="See it as visitors will, before anyone else can">👁 Preview</button>
      <button type="button" class="btn" data-cancel>Cancel</button><button class="btn primary" type="submit" data-save>${wsSaveLabel(p.id, p.published !== false)}</button></div>
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
  form.published.addEventListener("change", () => { form.querySelector("[data-save]").textContent = wsSaveLabel(ws.editing && ws.editing !== "new", form.published.checked); });
  // Preview: what's typed now (saved or not, published or not), on the real post page in a tab of its own. Only this
  // browser has it: it goes through this browser's storage, never the server, so nobody else can see it.
  form.querySelector("[data-preview]").addEventListener("click", () => {
    const f = new FormData(form);
    try {
      localStorage.setItem("solstone-post-preview", JSON.stringify({ title: f.get("title") || "Untitled", category: f.get("category"),
        body: f.get("body") || "", author: me.user?.shown || "", created: Date.now() / 1000 }));
    } catch { showError("This browser won't keep the preview (a private window?)", 5000); return; }
    window.open("/post/__preview__", "solstone-preview");
  });
  // Put text in where the cursor is (on a line of its own for a picture).
  const ta = form.querySelector("textarea[name=body]");
  const insert = (text, ownLine) => {
    const a = ta.selectionStart ?? ta.value.length, b = ta.selectionEnd ?? a, before = ta.value.slice(0, a), after = ta.value.slice(b);
    const pre = ownLine && before && !before.endsWith("\n\n") ? (before.endsWith("\n") ? "\n" : "\n\n") : "";
    const post = ownLine ? "\n\n" : "";
    ta.value = before + pre + text + post + after;
    const at = (before + pre + text).length;
    ta.focus(); ta.setSelectionRange(at, at);
    ta.dispatchEvent(new Event("input"));          // the live view follows
  };
  // The live view beside the text: the same formatting the site uses, as you type.
  const live = form.querySelector(".ws-live");
  let pending = 0;
  const redraw = () => { cancelAnimationFrame(pending); pending = requestAnimationFrame(() => { live.innerHTML = markdown(ta.value) || '<p class="muted">Start typing…</p>'; }); };
  ta.addEventListener("input", redraw);
  redraw();
  const changed = () => { ta.focus(); redraw(); };
  // Marks around the selected text (or a placeholder to type over), e.g. **bold** or {red}…{/red}.
  const wrap = (open, close, placeholder) => {
    const a = ta.selectionStart, b = ta.selectionEnd, sel = ta.value.slice(a, b) || placeholder;
    ta.setRangeText(open + sel + close, a, b, "end");
    ta.setSelectionRange(a + open.length, a + open.length + sel.length);
    changed();
  };
  // Something at the start of each selected line ("## ", "- "); pressing it again takes it off.
  const prefixLines = (mark) => {
    const v = ta.value, a = v.lastIndexOf("\n", ta.selectionStart - 1) + 1;
    let b = v.indexOf("\n", Math.max(ta.selectionEnd - 1, a)); if (b < 0) b = v.length;
    const lines = v.slice(a, b).split("\n");
    const strip = (l) => l.replace(/^(#{1,3} |[-*] |\d+[.)] |> )/, "");
    const all = lines.every((l, i) => (mark === "1. " ? l.startsWith(`${i + 1}. `) : l.startsWith(mark)));
    const out = lines.map((l, i) => (all ? strip(l) : (mark === "1. " ? `${i + 1}. ` : mark) + strip(l))).join("\n");
    ta.setRangeText(out, a, b, "select");
    changed();
  };
  form.querySelectorAll("[data-wrap]").forEach((b) => b.addEventListener("click", () => wrap(b.dataset.wrap, b.dataset.wrap, b.title === "Bold" ? "bold text" : "slanted text")));
  form.querySelectorAll("[data-prefix]").forEach((b) => b.addEventListener("click", () => prefixLines(b.dataset.prefix.replace("&gt;", ">"))));
  form.querySelector("[data-line]").addEventListener("change", (e) => { if (e.target.value) prefixLines(e.target.value); e.target.value = ""; });
  form.querySelectorAll("[data-style]").forEach((s) => s.addEventListener("change", (e) => {
    const k = e.target.value;
    if (k) wrap(`{${k}}`, `{/${k}}`, k === "big" || k === "small" ? "some text" : "coloured text");
    e.target.value = "";
  }));
  form.querySelector("[data-rule]").addEventListener("click", () => insert("---", true));
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
    <label>Tagline <small>One line about the site: on the sign-in page, and under the name if it's shown big on the home page</small><input class="input" name="tagline" maxlength="160" value="${esc(s.tagline)}" placeholder="A Minecraft server for friends"></label>
    <label class="check"><input type="checkbox" name="home_title" ${s.home_title ? "checked" : ""}> Show the name (and tagline) big at the top of the home page <small>Off: just the bar at the top, with the logo and name</small></label>
    <fieldset class="ws-joins"><legend>How to join each server <small class="muted">One card per server on the home page, with how it's doing</small></legend>
      <p class="muted small">Each server gets its own card. Leave Bedrock empty for Java only, or Java empty for Bedrock only; a server with neither isn't shown. Private servers never show. The join guide uses the first server's addresses.</p>
      ${(state.servers || []).filter((x) => !x.private).map((x, i) => `<div class="ws-join" data-sid="${esc(x.id)}">
        <div class="ws-join-head"><b>${esc(x.name)}</b>
          <label class="check"><input type="radio" name="main_server" value="${esc(x.id)}" ${s.main_server === x.id ? "checked" : ""}> Main server <small class="muted">first everywhere</small></label>
          <label class="ws-color" title="The colour of its card's border">Border <input type="color" data-j="join_color" value="#f2c14e"><button type="button" class="link-btn" data-nocolor>none</button></label></div>
        <div class="ws-row"><label>Java<input class="input" data-j="join_address" maxlength="80" placeholder="${i === 0 ? "play.example.net" : "mods.example.net:25566"}"></label>
          <label>Bedrock<input class="input" data-j="join_bedrock_address" maxlength="80"></label>
          <label>Port<input class="input" data-j="join_bedrock_port" inputmode="numeric" placeholder="19132"></label></div>
        <label>About this server <small>Optional, shown on its card: what it is, who it's for. For example: Our survival world for the whole family, or: Modded adventures, needs the modpack.</small><textarea class="input" data-j="join_note" maxlength="300" rows="2"></textarea></label>
        <label class="check"><input type="checkbox" data-j="join_mods"> List the mods players need</label></div>`).join("")}
    </fieldset>
    <label>Discord invite <small>A discord.gg or discord.com link</small><input class="input" name="discord" maxlength="200" value="${esc(s.discord)}" placeholder="https://discord.gg/..."></label>
    <label>About <small>Shown at the bottom of the home page. Same formatting as posts.</small><textarea class="input" name="about" rows="6" maxlength="4000">${esc(s.about)}</textarea></label>
    <label class="check"><input type="checkbox" name="home_live" ${s.home_live ? "checked" : ""}> Show the public servers' status on the home page <small>Running or not and how many are on. Private servers are never shown.</small></label>
    <div class="actions"><a class="btn" href="/" target="_blank" rel="noopener">Open the home page</a><button class="btn primary" type="submit">Save</button></div>
  </form>`;
  // each server's join details come from its settings
  $$(".ws-join").forEach(async (row) => {
    const cur = await api(`/api/servers/${encodeURIComponent(row.dataset.sid)}/settings`).catch(() => ({}));
    $$("[data-j]", row).forEach((i) => {
      if (i.type === "checkbox") i.checked = !!cur[i.dataset.j];
      else if (i.type === "color") { i.value = cur.join_color || "#f2c14e"; i.dataset.set = cur.join_color ? "1" : ""; }
      else i.value = cur[i.dataset.j] ?? "";
    });
    const col = $('[data-j="join_color"]', row);
    col.addEventListener("input", () => { col.dataset.set = "1"; });
    $("[data-nocolor]", row).addEventListener("click", () => { col.dataset.set = ""; col.value = "#f2c14e"; showToast("No border colour for this one", 1500); });
    // From before each server had its own: the old main address belongs to the first server, so it moves there.
    if (row === $(".ws-join") && !cur.join_address && !cur.join_bedrock_address && (s.java_address || s.bedrock_address)) {
      $('[data-j="join_address"]', row).value = s.java_address || "";
      $('[data-j="join_bedrock_address"]', row).value = s.bedrock_address || "";
      $('[data-j="join_bedrock_port"]', row).value = s.bedrock_address ? s.bedrock_port || "" : "";
    }
  });
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
    const body = Object.fromEntries(["name", "tagline", "discord", "about"].map((k) => [k, f.get(k)]));
    body.java_address = ""; body.bedrock_address = "";           // now kept with each server, below
    body.main_server = f.get("main_server") || "";
    body.home_live = !!f.get("home_live");
    body.home_title = !!f.get("home_title");
    try {
      for (const row of $$(".ws-join")) {               // each server's own way in, kept in its settings (first, so
        const v = {};                                   // the old main address is only cleared once it's moved)
        $$("[data-j]", row).forEach((i) => { v[i.dataset.j] = i.type === "checkbox" ? i.checked : i.type === "color" ? (i.dataset.set ? i.value : "") : i.value; });
        await post(`/api/servers/${encodeURIComponent(row.dataset.sid)}/settings`, v, "PUT");
      }
      ws.data.site = await post("/api/settings/site", body, "PUT");
      showToast("Saved", 2000); renderWebsite();
    }
    catch (err) { showError(esc(err.message), 5000); }
  });
}

// ---------------------------------------------------------------- the built-in guides and the rules, in your own words
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
    ${box("join")}${box("account")}${box("rules")}
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

// ---------------------------------------------------------------- a welcome message in the game's chat when someone joins
// Each server's own message (welcome.py sends it): & colour codes, {player} and the like, and web addresses
// that can be clicked on Java. The preview below shows it as the game will.
const WELCOME_COLOURS = [["0", "#000000", "Black"], ["1", "#0000aa", "Dark blue"], ["2", "#00aa00", "Dark green"], ["3", "#00aaaa", "Dark aqua"],
  ["4", "#aa0000", "Dark red"], ["5", "#aa00aa", "Purple"], ["6", "#ffaa00", "Gold"], ["7", "#aaaaaa", "Grey"], ["8", "#555555", "Dark grey"],
  ["9", "#5555ff", "Blue"], ["a", "#55ff55", "Green"], ["b", "#55ffff", "Aqua"], ["c", "#ff5555", "Red"], ["d", "#ff55ff", "Pink"],
  ["e", "#ffff55", "Yellow"], ["f", "#ffffff", "White"]];
const WELCOME_STYLES = [["l", "B", "Bold"], ["o", "I", "Italic"], ["n", "U", "Underline"], ["r", "↺", "Back to plain"]];
const WELCOME_FIELDS = [["player", "Their name"], ["server", "The server's name"], ["rules", "The rules page"], ["site", "The website"]];
const WELCOME_START = "&6&lWelcome to {server}, {player}!&r\n&7Please read the rules: &b{rules}\n&aHave fun, and be kind!";

function welcomePreview(text, sid) {
  const srv = (state.servers || []).find((x) => x.id === sid);
  const base = location.origin;
  const vals = { player: "Steve", server: srv?.name || "the server", site: base, rules: `${base}/guides/rules` };
  const filled = text.replace(/\{(\w+)\}/g, (m, k) => (k.toLowerCase() in vals ? vals[k.toLowerCase()] : m));
  const colour = Object.fromEntries(WELCOME_COLOURS.map(([c, hex]) => [c, hex]));
  return filled.split("\n").map((line) => {
    let st = {}, out = "";
    const span = (t, extra = "") => {
      if (!t) return;
      const css = [st.c ? `color:${st.c}` : "", st.l ? "font-weight:700" : "", st.o ? "font-style:italic" : "",
        st.n || extra ? "text-decoration:underline" : "", st.m ? "text-decoration:line-through" : ""].filter(Boolean).join(";");
      out += `<span style="${css}${extra && !st.c ? ";color:#55ffff" : ""}">${esc(t)}</span>`;
    };
    const re = /&([0-9a-fklmnor])|(https?:\/\/[^\s<>"']+)/gi;
    let pos = 0, m;
    while ((m = re.exec(line))) {
      span(line.slice(pos, m.index));
      pos = re.lastIndex;
      if (m[2]) { span(m[2], "link"); continue; }
      const c = m[1].toLowerCase();
      if (c === "r") st = {}; else if (colour[c]) st = { c: colour[c] }; else st = { ...st, [c]: true };
    }
    span(line.slice(pos));
    return `<div>${out || "&nbsp;"}</div>`;
  }).join("");
}

async function wsWelcome(el) {
  const servers = (state.servers || []).filter((x) => x.type !== "bedrock");
  if (!servers.length) { el.innerHTML = `<p class="muted">No Java servers yet.</p>`; return; }
  el.innerHTML = `<div class="ws-welcome">
    <p class="muted">A message in the game's chat, just for the player who joined: on their first time, or every time. Only they see it. Web addresses can be clicked on Java; Bedrock players see them written out.</p>
    ${servers.map((x) => `<form class="panel ws-wel" data-sid="${esc(x.id)}"><div class="section-head"><h2>${esc(x.name)}</h2>
        <select class="input sm" name="when"><option value="off">Off</option><option value="first">First time they join</option><option value="every">Every time they join</option></select></div>
      <div class="wel-tools" role="toolbar" aria-label="Colours and styles">
        ${WELCOME_COLOURS.map(([c, hex, l]) => `<button type="button" class="wel-col" data-code="&${c}" style="background:${hex}" title="${l}" aria-label="${l}"></button>`).join("")}
        ${WELCOME_STYLES.map(([c, t, l]) => `<button type="button" class="btn sm wel-sty" data-code="&${c}" title="${l}" aria-label="${l}">${t}</button>`).join("")}</div>
      <div class="wel-tools">${WELCOME_FIELDS.map(([k, l]) => `<button type="button" class="btn sm" data-code="{${k}}" title="${l}">{${k}}</button>`).join("")}</div>
      <textarea class="input ws-text" name="text" rows="5" maxlength="800" placeholder="Welcome to the server, {player}!"></textarea>
      <div class="wel-preview" aria-label="How it looks in the game"></div>
      <p class="muted small">Up to 8 lines. Colours carry on until the next one, or <code>&amp;r</code>.</p>
      <div class="btn-row"><button class="btn sm primary" type="submit">Save</button>
        <button class="btn sm" type="button" data-start>Start from an example</button>
        <span class="wel-try"><select class="input sm" name="try"></select><button class="btn sm" type="button" data-try>Send it to them now</button></span></div></form>`).join("")}</div>`;
  for (const form of $$(".ws-wel", el)) {
    const sid = form.dataset.sid, ta = form.text, pv = $(".wel-preview", form);
    const cur = await api(`/api/servers/${encodeURIComponent(sid)}/settings`).catch(() => ({}));
    form.when.value = cur.welcome_when || "off"; ta.value = cur.welcome || "";
    const online = (state.servers.find((x) => x.id === sid)?.online) || [];
    form.try.innerHTML = Array.isArray(online) && online.length ? online.map((n) => `<option>${esc(n)}</option>`).join("") : `<option value="">Nobody's on now</option>`;
    const show = () => { pv.innerHTML = welcomePreview(ta.value, sid) || ""; pv.hidden = !ta.value.trim(); };
    show();
    ta.addEventListener("input", show);
    form.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-code]");
      if (b) {
        const a = ta.selectionStart ?? ta.value.length, z = ta.selectionEnd ?? a;
        ta.setRangeText(b.dataset.code, a, z, "end"); ta.focus(); show(); return;
      }
      if (e.target.closest("[data-start]")) { if (!ta.value.trim() || confirm("Replace what's there with the example?")) { ta.value = WELCOME_START; if (form.when.value === "off") form.when.value = "first"; show(); } return; }
      if (e.target.closest("[data-try]")) {
        if (!form.try.value) { showError("Nobody's on that server right now", 3000); return; }
        try { await post(`/api/servers/${encodeURIComponent(sid)}/welcome/try`, { player: form.try.value, text: ta.value }); showToast(`Sent to ${esc(form.try.value)}`, 2500); }
        catch (err) { showError(esc(err.message), 6000); }
      }
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await post(`/api/servers/${encodeURIComponent(sid)}/settings`, { welcome: ta.value, welcome_when: form.when.value }, "PUT"); showToast("Saved", 2000); }
      catch (err) { showError(esc(err.message), 5000); }
    });
  }
}
