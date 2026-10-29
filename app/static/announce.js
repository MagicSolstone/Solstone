/* Solstone — Announcements (admins): banners with countdowns (the bedtime countdown is in
   Manage → Play time). Loaded after app.js. */
"use strict";

const ANN_STYLES = [["info", "Info"], ["party", "Celebration"], ["heads", "Heads-up"]];
const ANN_WHERE = [["home", "Home page"], ["app", "Signed-in pages"], ["login", "Sign-in page"]];
const ANN_EMOJI = ["📣", "🎉", "🏗️", "🏆", "⚠️", "🎂", "🌙", "🎃", "🎄", "⛏️", "🐉", "🎬"];
const ann = { data: null, editing: null };

async function viewAnnouncements() {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = `Announcements · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  ann.data = await api("/api/board");
  ann.editing = null;
  setView(`<div class="fwe-head"><h1>Announcements</h1>
      <p class="muted">Banners across the top of the home page, the signed-in pages and the sign-in page. Add a countdown and it ticks down live, then can set off a show and post in the game.</p></div>
    <div id="ann-body"></div>`);
  renderAnn();
}
function renderAnn() {
  const el = $("#ann-body");
  if (!el) return;
  annBanners(el);
}
async function annSave(part, msg = "Saved") {
  try { ann.data = await post("/api/board", part, "PUT"); showToast(msg, 2000); appSky.board?.refresh(); return true; }
  catch (e) { showError(esc(e.message), 5000); return false; }
}

// ---------------------------------------------------------------- banners
const annLocal = (iso) => iso ? new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "";
function annState(it) {
  if (!it.enabled) return ["off", "Off"];
  const now = Date.now(), s = it.start ? new Date(it.start).getTime() : null, cd = it.countdown ? new Date(it.countdown).getTime() : null;
  let e = it.end ? new Date(it.end).getTime() : null;
  if (cd && !e) e = cd + 3600e3;
  if (e && now >= e) return ["ended", "Ended"];
  if (s && now < s) return ["later", `Starts ${annLocal(it.start)}`];
  return ["live", "Showing now"];
}
function annBannerHtml(it, preview = false) {
  const cd = it.countdown ? (preview ? new Date(it.countdown).getTime() / 1000 : null) : null;
  return `<div class="bn bn-${esc(it.style)}">${it.emoji ? `<span class="bn-emoji">${esc(it.emoji)}</span>` : ""}
    <div class="bn-text"><b>${esc(it.text || "Your announcement")}</b>${it.detail ? `<small>${esc(it.detail)}</small>` : ""}</div>
    ${cd ? `<span class="bn-cd">${esc(cd > Date.now() / 1000 ? fmtCountdown(cd - Date.now() / 1000) : it.done_text || "It's here!")}</span>` : ""}</div>`;
}
function annBanners(el) {
  const d = ann.data;
  const showName = (id) => d.shows.find((s) => s.id === id)?.name || id;
  const rows = d.items.map((it, i) => {
    const [cls, label] = annState(it);
    const facts = [
      it.countdown && `⏳ Counts down to ${annLocal(it.countdown)}`,
      it.end && !it.countdown && `Until ${annLocal(it.end)}`,
      it.show && `🎆 ${showName(it.show)} at zero`, it.say && "💬 Posts in the game",
      it.server && `Only ${d.servers.find((s) => s.id === it.server)?.name || it.server}`,
      it.where.length < ANN_WHERE.length && it.where.map((w) => ANN_WHERE.find(([k]) => k === w)?.[1]).join(", "),
    ].filter(Boolean);
    return ann.editing === i ? annEditHtml(it) : `<div class="ann-row ${cls}" data-i="${i}">
      ${annBannerHtml(it, true)}
      <div class="ann-meta"><span class="ann-state ${cls}">${esc(label)}</span>${facts.map((f) => `<span>${esc(f)}</span>`).join("")}
        <span class="ann-btns"><label class="switch-row ann-on"><span class="sr-only">On</span><input type="checkbox" role="switch" data-on ${it.enabled ? "checked" : ""} aria-label="Show this banner"></label>
        <button class="btn sm" data-edit>Edit</button><button class="btn sm danger" data-del>Delete</button></span></div></div>`;
  }).join("");
  el.innerHTML = `<section class="panel"><div class="ann-list">${rows || `<p class="muted">No announcements yet. They're good for build contests, server restarts, movie night, or "dinner in 10 minutes".</p>`}</div>
    ${ann.editing === "new" ? annEditHtml({ text: "", detail: "", emoji: "📣", style: "info", where: ["home", "app", "login"], server: "", start: "", end: "", countdown: "", done_text: "", show: "", say: false, enabled: true }) : `<button class="btn primary" id="ann-new" style="margin-top:12px">+ New announcement</button>`}</section>`;
  $("#ann-new")?.addEventListener("click", () => { ann.editing = "new"; renderAnn(); $(".ann-edit input[name=text]")?.focus(); });
  el.querySelectorAll(".ann-row[data-i]").forEach((row) => {
    const i = +row.dataset.i;
    row.querySelector("[data-edit]").addEventListener("click", () => { ann.editing = i; renderAnn(); });
    row.querySelector("[data-del]").addEventListener("click", async () => {
      const items = d.items.filter((_, j) => j !== i);
      if (await annSave({ items }, "Deleted")) renderAnn();
    });
    row.querySelector("[data-on]").addEventListener("change", async (e) => {
      const items = d.items.map((x, j) => (j === i ? { ...x, enabled: e.target.checked } : x));
      if (await annSave({ items }, e.target.checked ? "Banner on" : "Banner off")) renderAnn();
    });
  });
  if (ann.editing != null) annWireEdit(el.querySelector(".ann-edit"));
}
function annEditHtml(it) {
  const d = ann.data;
  const seg = (name, opts, cur) => `<div class="seg" role="group" data-seg="${name}">${opts.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${v === cur}">${l}</button>`).join("")}</div>`;
  return `<form class="ann-edit fws-cal-edit" autocomplete="off">
    <div class="ann-preview" aria-label="Preview">${annBannerHtml(it, true)}</div>
    <div class="fws-grid">
      <label>Emoji<span class="ann-emoji"><input class="input sm" name="emoji" value="${esc(it.emoji)}" maxlength="8" style="width:64px"></span></label>
      <label class="wide">Message<input class="input" name="text" value="${esc(it.text)}" maxlength="120" required placeholder="Build contest: castles!"></label>
    </div>
    <div class="ann-picks">${ANN_EMOJI.map((e) => `<button type="button" class="btn sm" data-emoji="${e}">${e}</button>`).join("")}</div>
    <label class="ann-full">Smaller line <span class="muted small">optional</span><input class="input" name="detail" value="${esc(it.detail)}" maxlength="240" placeholder="Meet at spawn. Best build wins a diamond pickaxe."></label>
    <div class="fw-row"><span>Look</span>${seg("style", ANN_STYLES, it.style)}</div>
    <div class="fw-row"><span>Show on</span><div class="ann-checks">${ANN_WHERE.map(([k, l]) => `<label class="check"><input type="checkbox" name="where" value="${k}" ${it.where.includes(k) ? "checked" : ""}> ${l}</label>`).join("")}</div></div>
    ${d.servers.length > 1 ? `<div class="fw-row"><span>Server</span><select class="input sm" name="server"><option value="">All servers</option>${d.servers.map((s) => `<option value="${esc(s.id)}" ${s.id === it.server ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></div>` : ""}
    <h3 class="fws-sub">When</h3>
    <div class="fws-grid">
      <label>Starts <span class="muted small">blank = now</span><input class="input sm" type="datetime-local" name="start" value="${esc(it.start)}"></label>
      <label>Ends <span class="muted small">blank = when you delete it</span><input class="input sm" type="datetime-local" name="end" value="${esc(it.end)}"></label>
    </div>
    <h3 class="fws-sub">Countdown <span class="muted small">optional; the banner counts down to this, and stays up an hour after</span></h3>
    <div class="fws-grid">
      <label>Counts down to<input class="input sm" type="datetime-local" name="countdown" value="${esc(it.countdown)}"></label>
      <label class="wide">At zero, the banner says<input class="input sm" name="done_text" value="${esc(it.done_text)}" maxlength="80" placeholder="It's here!"></label>
      <label>At zero, play<select class="input sm" name="show"><option value="">A few fireworks (celebration look) or nothing</option>${d.shows.map((s) => `<option value="${esc(s.id)}" ${s.id === it.show ? "selected" : ""}>🎬 ${esc(s.name)}</option>`).join("")}</select></label>
    </div>
    <label class="check"><input type="checkbox" name="say" ${it.say ? "checked" : ""}> Post it in the game chat (with a title on screen) when it starts, or at zero if it has a countdown</label>
    <p class="muted small">Times are in the server's time zone. The last ten seconds of a countdown with a show or the celebration look fill the screen.</p>
    <div class="actions" style="justify-content:flex-start"><button class="btn primary" type="submit">Save</button><button class="btn" type="button" data-cancel>Cancel</button></div>
  </form>`;
}
function annFormItem(form) {
  const f = new FormData(form);
  const base = typeof ann.editing === "number" ? ann.data.items[ann.editing] : { enabled: true };
  return { ...base, text: f.get("text").trim(), detail: f.get("detail").trim(), emoji: f.get("emoji").trim(),
    style: form.querySelector('[data-seg="style"] [aria-pressed="true"]')?.dataset.v || "info",
    where: f.getAll("where"), server: f.get("server") || "", start: f.get("start"), end: f.get("end"),
    countdown: f.get("countdown"), done_text: f.get("done_text").trim(), show: f.get("show"), say: !!f.get("say") };
}
function annWireEdit(form) {
  if (!form) return;
  const preview = () => { form.querySelector(".ann-preview").innerHTML = annBannerHtml(annFormItem(form), true); };
  form.addEventListener("input", preview);
  form.addEventListener("change", preview);
  form.querySelectorAll("[data-seg] button").forEach((b) => b.addEventListener("click", () => {
    b.parentElement.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); preview();
  }));
  form.querySelectorAll("[data-emoji]").forEach((b) => b.addEventListener("click", () => { form.emoji.value = b.dataset.emoji; preview(); }));
  form.querySelector("[data-cancel]").addEventListener("click", () => { ann.editing = null; renderAnn(); });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const it = annFormItem(form);
    if (!it.where.length) { showToast("Pick at least one place to show it", 3000); return; }
    if (it.start && it.end && it.end <= it.start) { showToast("It ends before it starts", 3000); return; }
    const items = [...ann.data.items];
    if (typeof ann.editing === "number") items[ann.editing] = it; else items.push(it);
    if (await annSave({ items })) { ann.editing = null; renderAnn(); }
  });
}



// ================================================================ events
// Everything with a date ahead, in one list: contests, races, games, holidays and
// their shows, announcements counting down.
const UP_SIGNUP = new Set(["contest", "race", "game", "show"]);      // things people can say they're coming to
const UP_KIND = { contest: "Contest", race: "Race", game: "Game", holiday: "Holiday", show: "Fireworks", note: "Announcement" };
async function viewUpcoming() {
  curSid = null;
  document.title = `Events · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  const d = await api("/api/upcoming");
  const zone = new Date();
  const dayKey = (iso) => {
    const [y, m, dd] = iso.split("-").map(Number), day = new Date(y, m - 1, dd);
    const today = new Date(zone.getFullYear(), zone.getMonth(), zone.getDate());
    const diff = Math.round((day - today) / 86400000);
    const name = day.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
    return diff === 0 ? `Today · ${name}` : diff === 1 ? `Tomorrow · ${name}` : diff < 7 ? name : diff < 14 ? `Next week · ${name}` : name;
  };
  const row = (it) => `<li class="up-item ${it.live ? "live" : ""} up-${esc(it.kind)} ${it.then ? "up-then" : ""}">
      <span class="up-emoji" aria-hidden="true">${esc(it.emoji || "•")}</span>
      <div class="up-main"><b>${it.link ? `<a href="${esc(it.link)}">${esc(it.title)}</a>` : esc(it.title)}</b>
        ${it.then ? "" : `<span class="muted small">${esc([UP_KIND[it.kind], it.server, it.detail, it.days > 1 ? `${it.days} days` : ""].filter(Boolean).join(" · "))}</span>`}
        ${it.who?.length ? `<span class="small up-who">🙋 ${esc(it.who.join(", "))}</span>` : ""}</div>
      <span class="up-when">${it.live ? '<span class="state-pill live"><span class="status-dot on"></span>On now</span>' : it.time ? esc(it.time) : '<span class="muted small">All day</span>'}
        ${UP_SIGNUP.has(it.kind) ? `<button type="button" class="btn sm up-coming ${it.me ? "on" : ""}" data-coming="${esc(it.key)}" aria-pressed="${it.me}"
>${it.me ? "✅ I'm coming" : "🙋 I'm coming!"}${it.coming ? ` · ${it.coming}` : ""}</button>` : ""}</span></li>`;
  const live = d.items.filter((x) => x.live), ahead = d.items.filter((x) => !x.live);
  const groups = [];
  for (const it of ahead) { const g = groups[groups.length - 1]; if (g && g.date === it.date) g.items.push(it); else groups.push({ date: it.date, items: [it] }); }
  setView(`<div class="fwe-head"><h1>Events</h1>
      <p class="muted">Everything planned for the next ${d.days} days: contests, races and games, holidays and their fireworks shows, and announcements counting down.${isAdmin() ? ` Add things from a server's <b>Contests</b> page, <a href="#/manage/holidays">Holidays</a> or <a href="#/manage/announcements">Announcements</a>.` : ""}</p></div>
    ${live.length ? `<section class="section"><div class="section-head"><h2>Happening now</h2></div><ul class="up-list panel">${live.map(row).join("")}</ul></section>` : ""}
    ${groups.length ? groups.map((g) => `<section class="section up-day"><div class="section-head"><h2>${esc(dayKey(g.date))}</h2></div><ul class="up-list panel">${g.items.map(row).join("")}</ul></section>`).join("")
      : live.length ? "" : `<div class="panel up-empty"><span class="up-empty-emoji" aria-hidden="true">🗓️</span><h2>No events scheduled</h2>
          <p class="muted">Nothing's planned for the next ${Math.round(d.days / 30)} months yet. Contests, races and holidays show up here when they're added.</p>
          ${isAdmin() ? `<p class="muted small">Add a contest from a server's <b>Contests</b> page, a holiday on <a href="#/manage/holidays">Holidays</a>, or a countdown in <a href="#/manage/announcements">Announcements</a>.</p>` : ""}</div>`}`);
  $$("[data-coming]", view()).forEach((b) => b.addEventListener("click", async () => {
    const it = d.items.find((x) => x.key === b.dataset.coming);
    try {
      await post("/api/community/signup", { event: it.key, coming: !it.me });
      const y = scrollY;
      await viewUpcoming(); scrollTo(0, y);                // the names under it change too
    } catch (err) { showError(esc(err.message), 4000); }
  }));
}
