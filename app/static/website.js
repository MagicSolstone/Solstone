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
  ws.pub = await api("/api/public/site").catch(() => ({}));       // what {java_address} and the like fill in to
  ws.editing = null;
  if (ws.tab === "guides") ws.tab = "posts";                         // the old tab: guides are posts now
  setView(`<div class="fwe-head"><h1>Website</h1>
      <p class="muted">The public home page at <a href="/" target="_blank" rel="noopener">/</a>: how to join, News, and Help (guides and questions). Anyone can read it without signing in; private servers never show there.</p></div>
    <nav class="fwe-tabs fws-tabs" role="tablist" aria-label="Website">
      <button type="button" role="tab" data-tab="posts" aria-selected="${ws.tab === "posts"}">Posts</button>
      <button type="button" role="tab" data-tab="site" aria-selected="${ws.tab === "site"}">Site details</button>
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
  if (ws.tab === "site") wsSite(el); else if (ws.tab === "welcome") wsWelcome(el); else wsPosts(el);
}

// ---------------------------------------------------------------- posts
const wsDate = (ts) => new Date(ts * 1000).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });

// What a post can stand in for: the built-in pages the site links to (site.ROLES).
const WS_ROLES = { join: "The join guide (Ask to join goes under it)", account: "The guide to making an account", rules: "The server rules" };

const wsDay = (ts) => { const d = ts ? new Date(ts * 1000) : new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const wsSaveLabel = (saved, published) => (published ? (saved ? "Save" : "Publish") : "Save draft");

function wsEditHtml(p) {
  return `<form class="ws-edit panel" id="ws-edit">
    ${p.id ? "" : `<label class="ws-template">Start from <small>Solstone's wording, ready to make your own</small><select class="input" data-template>
      <option value="">A blank post</option>${Object.entries(GUIDES).map(([k, g]) => `<option value="${k}">${esc(g.title)}</option>`).join("")}</select></label>`}
    <label>Title<input class="input" name="title" maxlength="120" required value="${esc(p.title || "")}"></label>
    <label>Card description <small>Optional: a line or two under the title on the post's card (home page, News, Help). Leave it empty to show the start of the post. Fill-ins like {name} work.</small><textarea class="input" name="summary" rows="2" maxlength="240">${esc(p.summary || "")}</textarea></label>
    <div class="ws-card-pic"><label>Card picture <small>The picture on the post's card</small><select class="input sm" data-card-mode>
        <option value="" ${!p.card_image ? "selected" : ""}>The first picture in the post</option>
        <option value="own" ${p.card_image && p.card_image !== "none" ? "selected" : ""}>A picture just for the card</option>
        <option value="none" ${p.card_image === "none" ? "selected" : ""}>No picture</option></select></label>
      <img data-card-img alt="The card's picture" ${p.card_image && p.card_image !== "none" ? `src="/api/public/images/${esc(p.card_image)}"` : "hidden"}>
      <label class="btn sm ws-file" data-card-upload ${p.card_image && p.card_image !== "none" ? "" : "hidden"}>Choose a picture<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" data-card-file hidden></label>
      <input type="hidden" name="card_image" value="${esc(p.card_image || "")}"></div>
    <label class="ws-date">Date <small>Shown on the post. News is listed by it, newest first</small><input class="input sm" type="date" name="date" value="${wsDay(p.created)}" data-was="${wsDay(p.created)}"></label>
    <div class="ws-row"><label>Kind<select class="input" name="category">${WS_CATS.map(([k, l]) => `<option value="${k}" ${p.category === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="check"><input type="checkbox" name="published" ${p.published !== false ? "checked" : ""}> Published <small>Off keeps it a draft only admins see</small></label>
      <label class="check"><input type="checkbox" name="pinned" ${p.pinned ? "checked" : ""}> Pinned <small>Stays at the top</small></label>
      <label>Use as <small>Where the home page, Ask to join and the welcome message link to</small><select class="input" name="role">
        <option value="">Just a post</option>${Object.entries(WS_ROLES).map(([k, l]) => `<option value="${k}" ${p.role === k ? "selected" : ""}>${l}</option>`).join("")}</select></label></div>
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
      <select class="input sm" data-fill aria-label="Fill-in"><option value="">Fill-in…</option>${GUIDE_PLACEHOLDERS.map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join("")}</select>
      <button type="button" class="btn sm" data-link>🔗 Link</button>
      <label class="btn sm ws-file">🖼 Picture<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" data-pic hidden></label>
      <select class="input sm" data-picsize aria-label="Picture size" title="Click on a picture's line in the text, then pick its size"><option value="">Picture size…</option>
        <option value="full">Full width</option><option value="large">Large</option><option value="medium">Medium</option><option value="small">Small</option></select></div>
    <div class="ws-compose">
      <label class="ws-compose-text">Text <small>Select some text, then pick a button. Or type the marks yourself: **bold**, # Heading, {red}colour{/red}.</small>
        <textarea class="input ws-text" name="body" rows="16" maxlength="20000" required>${esc(p.body || "")}</textarea></label>
      <div class="ws-compose-view"><span class="ws-compose-label">How it looks</span><div class="hp-body ws-live" aria-live="off"></div></div></div>
    <small class="muted">Enter starts a new line; a blank line starts a new paragraph. Fill-ins like <code>{java_address}</code> become the main server's details (the first card on the home page), so they stay right when they change. The first picture also shows on the post's card, unless you choose another above. To size a picture, click on its line and pick <b>Picture size</b>. Pictures under 4 MB each.</small>
    <div class="actions"><button type="button" class="btn" data-preview title="See it as visitors will, before anyone else can">👁 Preview</button>
      <button type="button" class="btn" data-cancel>Cancel</button><button class="btn primary" type="submit" data-save>${wsSaveLabel(p.id, p.published !== false)}</button></div>
  </form>`;
}

function wsPosts(el) {
  const posts = ws.data.posts;
  const ordered = (cat) => cat === "guide" || cat === "faq";      // guides and questions: the admin's own order
  const row = (p, i, list) => ws.editing === p.id ? wsEditHtml(p) : `<div class="ws-post" data-id="${p.id}">
      <div><b>${esc(p.title)}</b>${p.pinned ? " 📌" : ""}${p.role ? ` <span class="chip">${esc(WS_ROLES[p.role]?.replace(/ \(.*\)$/, "") || p.role)}</span>` : ""}<div class="muted">${esc(WS_CATS.find(([k]) => k === p.category)?.[1] || "")} · ${esc(wsDate(p.created))}${p.published ? "" : " · <b>Draft</b>"}</div></div>
      <span class="btn-row">${p.published ? `<a class="btn sm" href="/post/${encodeURIComponent(p.slug)}" target="_blank" rel="noopener">View</a>` : ""}
        ${ordered(p.category) ? `<button class="btn sm" type="button" data-move="up" ${i === 0 ? "disabled" : ""} aria-label="Move ${esc(p.title)} up">↑</button><button class="btn sm" type="button" data-move="down" ${i === list.length - 1 ? "disabled" : ""} aria-label="Move ${esc(p.title)} down">↓</button>` : ""}
        <button class="btn sm" type="button" data-edit>Edit</button><button class="btn sm danger" type="button" data-del>Delete</button></span></div>`;
  // one list per kind: news by date (newest first), guides and questions in the order given with ↑ ↓
  const KIND = { news: "News", guide: "Guides", faq: "Questions" };
  const rows = WS_CATS.map(([k, l]) => {
    const label = KIND[k] || l;
    const list = posts.filter((p) => p.category === k);
    return list.length ? `<h3 class="ws-kind">${esc(label)} <small class="muted">${ordered(k) ? "in this order on the Help page and the home page: ↑ ↓ to move" : "newest first, by their date"}</small></h3>${list.map(row).join("")}` : "";
  }).join("");
  el.innerHTML = `<section class="panel"><div class="ws-list">${rows || `<p class="muted">No posts yet. News is for updates and events. On the Help page, guides are for how-tos (the rules, starting out) and questions are for quick answers.</p>`}</div>
    ${ws.editing === "new" ? wsEditHtml({ category: "news", published: true }) : `<button class="btn primary" id="ws-new" style="margin-top:12px">+ New post</button>`}</section>`;
  $("#ws-new")?.addEventListener("click", () => { ws.editing = "new"; renderWebsite(); $("#ws-edit input[name=title]")?.focus(); });
  el.querySelectorAll(".ws-post[data-id]").forEach((row) => {
    const id = +row.dataset.id;
    row.querySelector("[data-edit]").addEventListener("click", () => { ws.editing = id; renderWebsite(); });
    row.querySelectorAll("[data-move]").forEach((b) => b.addEventListener("click", async () => {
      try { await post(`/api/posts/${id}/move`, { up: b.dataset.move === "up" }); ws.data = await api("/api/posts"); renderWebsite(); }
      catch (err) { showError(esc(err.message), 4000); }
    }));
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
        body: f.get("body") || "", author: me.user?.shown || "", created: Date.now() / 1000, role: f.get("role") || null }));
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
  const redraw = () => { cancelAnimationFrame(pending); pending = requestAnimationFrame(() => { live.innerHTML = markdown(fillPostVars(ta.value, ws.pub || {}, form.role.value === "join")) || '<p class="muted">Start typing…</p>'; }); };
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
  form.querySelector("[data-fill]").addEventListener("change", (e) => { if (e.target.value) insert(`{${e.target.value}}`, false); e.target.value = ""; });
  form.role.addEventListener("change", redraw);
  // A template: Solstone's wording for one of the built-in guides, with the fill-ins in place, to make your own.
  form.querySelector("[data-template]")?.addEventListener("change", (e) => {
    const k = e.target.value;
    if (!k) return;
    if (ta.value.trim() && !confirm("Replace the text with Solstone's wording?")) { e.target.value = ""; return; }
    ta.value = guideTemplate(k, { ...(ws.pub || {}), ...ws.data.site });
    if (!form.title.value.trim()) form.title.value = GUIDES[k].title;
    if (!form.summary.value.trim()) form.summary.value = GUIDES[k].excerpt;      // its card says what the built-in one did
    form.category.value = "guide"; form.role.value = k;
    redraw();
  });
  // Picture size: the picture the cursor is on (or the last one before it) gets |small, |medium or |large.
  form.querySelector("[data-picsize]").addEventListener("change", (e) => {
    const size = e.target.value; e.target.value = "";
    if (!size) return;
    const at = ta.selectionStart ?? 0, re = /!\[([^\]|]*)(?:\|\w+)?\]\((\/api\/public\/images\/[^)\s]+)\)/g;
    let hit = null;
    for (const m of ta.value.matchAll(re)) if (m.index <= at) hit = m;
    if (!hit) { showToast("Click on a picture's line in the text first", 2500); return; }
    const md = `![${hit[1]}${size === "full" ? "" : `|${size}`}](${hit[2]})`;
    ta.value = ta.value.slice(0, hit.index) + md + ta.value.slice(hit.index + hit[0].length);
    ta.focus(); ta.setSelectionRange(hit.index + md.length, hit.index + md.length);
    ta.dispatchEvent(new Event("input"));
  });
  // The card's own picture (or the first in the post, or none)
  const cardMode = form.querySelector("[data-card-mode]"), cardImg = form.querySelector("[data-card-img]"), cardVal = form.card_image;
  const cardShow = () => {
    const own = cardMode.value === "own";
    form.querySelector("[data-card-upload]").hidden = !own;
    cardImg.hidden = !own || !cardVal.value || cardVal.value === "none";
    if (!own) cardVal.value = cardMode.value;
  };
  cardMode.addEventListener("change", () => { if (cardMode.value === "own" && cardVal.value === "none") cardVal.value = ""; cardShow(); });
  form.querySelector("[data-card-file]").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try {
      const r = await fetch("/api/posts/images", { method: "POST", credentials: "same-origin", headers: { "X-Solstone": "1", "Content-Type": f.type || "application/octet-stream" }, body: f });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `Upload failed (${r.status})`);
      cardVal.value = d.url.split("/").pop(); cardImg.src = d.url; cardShow();
      showToast("Card picture chosen", 1500);
    } catch (err) { showError(esc(err.message), 5000); }
    e.target.value = "";
  });
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
    const body = { title: f.get("title"), category: f.get("category"), body: f.get("body"), published: !!f.get("published"), pinned: !!f.get("pinned"), role: f.get("role") || "", summary: f.get("summary") || "", card_image: f.get("card_image") || "" };
    if (form.date.value && form.date.value !== form.date.dataset.was) body.date = form.date.value;   // only a date that was changed
    try {
      if (ws.editing === "new") await post("/api/posts", body); else await post(`/api/posts/${ws.editing}`, body, "PUT");
      showToast(body.published ? "Saved — it's on the website" : "Saved as a draft", 2500);
      ws.editing = null; ws.data = await api("/api/posts"); renderWebsite();
    } catch (err) { showError(esc(err.message), 5000); }
  });
}

// ---------------------------------------------------------------- planned maintenance
async function wsMaintenance() {
  const form = $("#ws-maint-form"), status = $("#ws-maint-status"), clearBtn = $("#ws-maint-clear");
  if (!form) return;
  const show = (m, worker) => {
    form.start.value = m?.start || ""; form.end.value = m?.end || ""; form.message.value = m?.message || "";
    clearBtn.hidden = !m;
    const told = worker === "ok" ? " The Cloudflare page knows about it." : worker ? ` ⚠ ${worker}.` : "";
    status.textContent = m ? `Planned: ${new Date(m.start).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })} to ${new Date(m.end).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}.${told}` : worker ? `No maintenance planned.${worker === "ok" ? "" : told}` : "";
  };
  const cur = await api("/api/settings/maintenance").catch(() => null);
  show(cur?.maintenance, null);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { const r = await post("/api/settings/maintenance", { start: form.start.value, end: form.end.value, message: form.message.value }, "PUT"); show(r.maintenance, r.worker); showToast("Maintenance planned", 2500); }
    catch (err) { showError(esc(err.message), 5000); }
  });
  clearBtn.addEventListener("click", async () => {
    try { const r = await post("/api/settings/maintenance", { start: "" }, "PUT"); show(null, r.worker); showToast("Maintenance cancelled", 2500); }
    catch (err) { showError(esc(err.message), 5000); }
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
    <div class="row2"><label>News on the home page <small>The newest (pinned first), then a <b>More news</b> button. 0: none</small><input class="input" type="number" name="home_news" min="0" max="12" value="${s.home_news ?? 3}"></label>
      <label>Guides on the home page <small>Then a <b>More guides</b> button. 0: none</small><input class="input" type="number" name="home_guides" min="0" max="12" value="${s.home_guides ?? 4}"></label></div>
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
    <label>Contact email <small>Where players and parents can reach you: account problems, questions, something stolen or broken. Shown on the Help page and at the bottom of every page, and <code>{contact}</code> puts it in any post.</small><input class="input" type="email" name="contact" maxlength="120" value="${esc(s.contact || "")}" placeholder="contact@example.com"></label>
    <label>Discord invite <small>A discord.gg or discord.com link</small><input class="input" name="discord" maxlength="200" value="${esc(s.discord)}" placeholder="https://discord.gg/..."></label>
    <label>About <small>Shown at the bottom of the home page. Same formatting as posts.</small><textarea class="input" name="about" rows="6" maxlength="4000">${esc(s.about)}</textarea></label>
    <label class="check"><input type="checkbox" name="join_requests" ${s.join_requests ? "checked" : ""}> An <b>Ask to join</b> form on the join guide <small>People send their name in the game (and, if they like, a first name and a note). You get a notification, and they show in Manage → Whitelist.${ws.data.notify_ready === false ? " Set up notifications first (Manage → Notifications)." : ""}</small></label>
    <label class="check"><input type="checkbox" name="home_live" ${s.home_live ? "checked" : ""}> Show the public servers' status on the home page <small>Running or not and how many are on. Private servers are never shown.</small></label>
    <div class="actions"><a class="btn" href="/" target="_blank" rel="noopener">Open the home page</a><button class="btn primary" type="submit">Save</button></div>
  </form>
  <section class="panel ws-offline"><h3>If this website goes down</h3>
    <p class="muted">When this computer is off or Solstone isn't running, visitors can still get a page from Cloudflare: the site's name, your contact email, and whether each Minecraft server is still up (and how many are playing, never who). It's a small Cloudflare Worker, free on Cloudflare's free plan.</p>
    <ol class="ws-steps">
      <li>Save the details above, then <a class="btn sm" href="/api/settings/site/offline-worker" download>⬇ Download the Worker</a></li>
      <li>In Cloudflare: <b>Workers &amp; Pages → Create application → Start with Hello World</b>, name it (like <i>site-offline</i>) and <b>Deploy</b>. Then <b>Edit code</b>, replace everything there with the downloaded file, and <b>Deploy</b> again. (Not <i>Upload</i> or static files: that's for Pages, and won't take it.)</li>
      <li>In the Worker: <b>Settings → Domains &amp; Routes → Add → Route</b> (not <i>Custom domain</i>): <code>${esc(location.host)}/*</code> on your domain's zone. The website's address must be proxied by Cloudflare (orange cloud, or a Cloudflare Tunnel). Its own <i>workers.dev</i> address isn't needed; you can turn it off there.</li>
      <li>For planned maintenance (below), give it somewhere to keep the notice: in Cloudflare, <b>Storage &amp; Databases → KV → Create</b> (name it <i>solstone</i>), then in the Worker <b>Settings → Bindings → Add → KV namespace</b>, variable name <code>SOLSTONE</code>, that namespace, and <b>Deploy</b>.</li>
      <li>To try it, stop Solstone for a moment and open the website.</li>
    </ol>
    <p class="muted small">Changed the name, contact or servers? Download it again and paste it over the old one. The server check uses mcsrvstat.us, a free public status checker.</p>
  </section>
  <section class="panel ws-offline" id="ws-maint"><h3>🛠️ Planned maintenance</h3>
    <p class="muted">Taking the servers and website down on purpose (new hardware, say)? Plan it here: every page shows a banner counting down to it, and while everything's off, the Cloudflare page says <i>Down for maintenance, back around …</i> with your message, instead of just "down". Times are the server's.</p>
    <form id="ws-maint-form" class="ws-row">
      <label>From<input class="input" type="datetime-local" name="start" required></label>
      <label>Until<input class="input" type="datetime-local" name="end" required></label>
      <label class="wide">Message <small>Optional, shown on the banner and the Cloudflare page</small><input class="input" name="message" maxlength="240" placeholder="Swapping in a faster drive. Your builds are safe!"></label>
      <div class="actions"><button type="button" class="btn" id="ws-maint-clear" hidden>Cancel the maintenance</button><button class="btn primary" type="submit">Plan it</button></div>
    </form>
    <p class="muted small" id="ws-maint-status" role="status"></p>
  </section>`;
  wsMaintenance();
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
    const body = Object.fromEntries(["name", "tagline", "contact", "discord", "about"].map((k) => [k, f.get(k)]));
    body.java_address = ""; body.bedrock_address = "";           // now kept with each server, below
    body.main_server = f.get("main_server") || "";
    body.home_live = !!f.get("home_live");
    body.home_title = !!f.get("home_title");
    body.home_news = +f.get("home_news"); body.home_guides = +f.get("home_guides");
    body.join_requests = !!f.get("join_requests");
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

// ---------------------------------------------------------------- a welcome message in the game's chat when someone joins
// Each server's own message (welcome.py sends it): & colour codes, {player} and the like, and web addresses
// that can be clicked on Java. The preview below shows it as the game will.
const WELCOME_COLOURS = [["0", "#000000", "Black"], ["1", "#0000aa", "Dark blue"], ["2", "#00aa00", "Dark green"], ["3", "#00aaaa", "Dark aqua"],
  ["4", "#aa0000", "Dark red"], ["5", "#aa00aa", "Purple"], ["6", "#ffaa00", "Gold"], ["7", "#aaaaaa", "Grey"], ["8", "#555555", "Dark grey"],
  ["9", "#5555ff", "Blue"], ["a", "#55ff55", "Green"], ["b", "#55ffff", "Aqua"], ["c", "#ff5555", "Red"], ["d", "#ff55ff", "Pink"],
  ["e", "#ffff55", "Yellow"], ["f", "#ffffff", "White"]];
const WELCOME_STYLES = [["l", "B", "Bold"], ["o", "I", "Italic"], ["n", "U", "Underline"], ["r", "↺", "Back to plain"]];
const WELCOME_FIELDS = [["player", "Their name"], ["server", "The server's name"], ["rules", "The rules page"], ["site", "The website"], ["contact", "The contact email"]];
const WELCOME_START = "&6&lWelcome to {server}, {player}!&r\n&7Please read the rules: &b{rules}\n&aHave fun, and be kind!";

function welcomePreview(text, sid) {
  const srv = (state.servers || []).find((x) => x.id === sid);
  const base = location.origin;
  const vals = { player: "Steve", server: srv?.name || "the server", site: base, rules: `${base}/guides/rules`, contact: ws.data?.site?.contact || "an admin" };
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
    const re = /&([0-9a-fklmnor])|(https?:\/\/[^\s<>"']+)|(\/trigger [a-z_]+)/gi;
    let pos = 0, m;
    while ((m = re.exec(line))) {
      span(line.slice(pos, m.index));
      pos = re.lastIndex;
      if (m[2]) { span(m[2], "link"); continue; }
      if (m[3]) { const was = st; if (!st.c) st = { ...st, c: "#55ff55" }; span(m[3], "link"); st = was; continue; }
      const c = m[1].toLowerCase();
      if (c === "r") st = {}; else if (colour[c]) st = { c: colour[c] }; else st = { ...st, [c]: true };
    }
    span(line.slice(pos));
    return `<div>${out || "&nbsp;"}</div>`;
  }).join("");
}

async function wsNudge(form, sid) {
  let cfg = await api("/api/settings/nudge");
  const sample = (t) => t.replace(/\{waiting\}/g, "2 new messages and a vote").replace(/\{messages\}/g, "2").replace(/\{votes\}/g, "1");
  const show = () => $$(".wel-preview", form).forEach((pv) => { pv.innerHTML = welcomePreview(sample(form[pv.dataset.for].value), sid) || ""; });
  const fillIn = () => {
    form.join.checked = cfg.join; form.live.checked = cfg.live; form.repeat_minutes.value = cfg.repeat_minutes;
    form.join_text.value = cfg.join_text; form.live_text.value = cfg.live_text; form.signup.value = cfg.signup; form.signup_text.value = cfg.signup_text; show();
  };
  fillIn();
  form.addEventListener("input", show);
  $("[data-nudge-reset]", form).addEventListener("click", () => { for (const k of ["join_text", "live_text", "signup_text"]) form[k].value = cfg.defaults[k]; show(); });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      cfg = await post("/api/settings/nudge", { join: form.join.checked, live: form.live.checked, repeat_minutes: +form.repeat_minutes.value || 0,
        join_text: form.join_text.value, live_text: form.live_text.value, signup: form.signup.value, signup_text: form.signup_text.value }, "PUT");
      fillIn(); showToast("Saved", 2000);
    } catch (err) { showError(esc(err.message), 5000); }
  });
}

async function wsWelcome(el) {
  const servers = (state.servers || []).filter((x) => x.type !== "bedrock");
  if (!servers.length) { el.innerHTML = `<p class="muted">No Java servers yet.</p>`; return; }
  el.innerHTML = `<div class="ws-welcome">
    <p class="muted">A message in the game's chat, just for the player who joined: on their first time, or every time. Only they see it. Web addresses can be clicked on Java; Bedrock players see them written out.</p>
    <form class="panel ws-nudge" id="ws-nudge"><div class="section-head"><h2>✉️ Reminders about the website</h2></div>
      <p class="muted small">So the website isn't forgotten: a line in the game when something's waiting there for a player (new messages, a vote they haven't voted in). Nothing is sent when nothing's waiting.
        Fill-ins: <code>{waiting}</code> (like “2 new messages and a vote”), <code>{messages}</code>, <code>{votes}</code>, <code>{player}</code>, <code>{site}</code>. Colours like the welcome message.</p>
      <label class="check"><input type="checkbox" name="join"> <b>When they join</b>, a few seconds after the welcome message (every time, if something's waiting)</label>
      <textarea class="input ws-text" name="join_text" rows="2" maxlength="400"></textarea>
      <div class="wel-preview" data-for="join_text"></div>
      <label class="check">While they play, if something's still waiting, the same again every
        <input class="input sm" type="number" name="repeat_minutes" min="0" max="1440" step="15" style="width:72px"> minutes <small class="muted">(0: never)</small></label>
      <label class="check"><input type="checkbox" name="live"> <b>When a new message reaches them</b> while they're playing (from an admin, or a notice like a vote's result)</label>
      <textarea class="input ws-text" name="live_text" rows="2" maxlength="400"></textarea>
      <div class="wel-preview" data-for="live_text"></div>
      <label class="check"><b>Players without a website account</b>: an invitation to make one (only while sign-up is open)
        <select class="input sm" name="signup"><option value="off">Off</option><option value="first">The first time they join</option><option value="day">Once a day, when they join</option><option value="every">Every time they join</option></select></label>
      <textarea class="input ws-text" name="signup_text" rows="2" maxlength="400"></textarea>
      <div class="wel-preview" data-for="signup_text"></div>
      <div class="btn-row"><button class="btn sm primary" type="submit">Save</button><button class="btn sm" type="button" data-nudge-reset>Back to Solstone's wording</button></div></form>
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
  wsNudge($("#ws-nudge", el), servers[0].id);
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
