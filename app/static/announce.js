/* Solstone — Announcements (admins): banners with countdowns, birthdays, the bedtime
   countdown, and TV mode for the status page. Loaded after app.js. */
"use strict";

const ANN_TABS = [["banners", "Banners"], ["birthdays", "Birthdays"], ["bedtime", "Bedtime"], ["tv", "TV mode"]];
const ANN_STYLES = [["info", "Info"], ["party", "Celebration"], ["heads", "Heads-up"]];
const ANN_WHERE = [["status", "Status page & TV"], ["app", "Solstone (signed in)"], ["login", "Sign-in page"]];
const ANN_EMOJI = ["📣", "🎉", "🏗️", "🏆", "⚠️", "🎂", "🌙", "🎃", "🎄", "⛏️", "🐉", "🎬"];
const ANN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const ann = { tab: "banners", data: null, editing: null, tv: null };

async function viewAnnouncements() {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = "Announcements · Solstone";
  $("#rail-servers").innerHTML = railHtml(null);
  [ann.data, ann.tv] = await Promise.all([api("/api/board"), api("/api/settings/tv")]);
  ann.editing = null;
  setView(`<div class="fwe-head"><h1>Announcements</h1>
      <p class="muted">Banners across the top of the status page, Solstone and the sign-in page. Add a countdown and it ticks down live, then can set off a show and post in the game.</p></div>
    <nav class="fwe-tabs fws-tabs" role="tablist" aria-label="Announcements">${ANN_TABS.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${ann.tab === k}">${l}</button>`).join("")}</nav>
    <div id="ann-body"></div>`);
  $$(".fws-tabs [data-tab]").forEach((b) => b.addEventListener("click", () => {
    ann.tab = b.dataset.tab; ann.editing = null;
    $$(".fws-tabs [data-tab]").forEach((x) => x.setAttribute("aria-selected", String(x === b))); renderAnn();
  }));
  renderAnn();
}
function renderAnn() {
  const el = $("#ann-body");
  if (!el) return;
  ({ banners: annBanners, birthdays: annBirthdays, bedtime: annBedtime, tv: annTv })[ann.tab](el);
}
async function annSave(part, msg = "Saved") {
  try { ann.data = await post("/api/board", part, "PUT"); showToast(msg, 2000); appSky.board?.refresh(); return true; }
  catch (e) { showToast(esc(e.message), 5000); return false; }
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
      it.where.length < 3 && it.where.map((w) => ANN_WHERE.find(([k]) => k === w)?.[1]).join(", "),
    ].filter(Boolean);
    return ann.editing === i ? annEditHtml(it) : `<div class="ann-row ${cls}" data-i="${i}">
      ${annBannerHtml(it, true)}
      <div class="ann-meta"><span class="ann-state ${cls}">${esc(label)}</span>${facts.map((f) => `<span>${esc(f)}</span>`).join("")}
        <span class="ann-btns"><label class="switch-row ann-on"><span class="sr-only">On</span><input type="checkbox" role="switch" data-on ${it.enabled ? "checked" : ""} aria-label="Show this banner"></label>
        <button class="btn sm" data-edit>Edit</button><button class="btn sm danger" data-del>Delete</button></span></div></div>`;
  }).join("");
  el.innerHTML = `<section class="panel"><div class="ann-list">${rows || `<p class="muted">No announcements yet. They're good for build contests, server restarts, movie night, or "dinner in 10 minutes".</p>`}</div>
    ${ann.editing === "new" ? annEditHtml({ text: "", detail: "", emoji: "📣", style: "info", where: ["status", "app", "login"], server: "", start: "", end: "", countdown: "", done_text: "", show: "", say: false, enabled: true }) : `<button class="btn primary" id="ann-new" style="margin-top:12px">+ New announcement</button>`}</section>`;
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

// ---------------------------------------------------------------- birthdays
function annDaysUntil(b) {
  const t = new Date(); t.setHours(0, 0, 0, 0);
  const at = (y) => { const d = new Date(y, b.month - 1, b.day); return d.getMonth() === b.month - 1 ? d : new Date(y, 1, 28); };
  let d = at(t.getFullYear());
  if (d < t) d = at(t.getFullYear() + 1);
  return Math.round((d - t) / 864e5);
}
function annBirthdays(el) {
  const d = ann.data;
  const list = [...d.birthdays].sort((a, b) => annDaysUntil(a) - annDaysUntil(b));
  const row = (b) => `<div class="ann-bday" data-player="${esc(b.player)}">
      <span class="ann-bd-face">${faceHtml({ name: b.player }, 28)}</span>
      <input class="input sm" name="player" value="${esc(b.player)}" list="ann-players" maxlength="16" aria-label="Player" placeholder="Player">
      <select class="input sm" name="month" aria-label="Month">${ANN_MONTHS.map((m, i) => `<option value="${i + 1}" ${i + 1 === b.month ? "selected" : ""}>${m}</option>`).join("")}</select>
      <input class="input sm" name="day" type="number" min="1" max="31" value="${b.day}" aria-label="Day" style="width:70px">
      <select class="input sm" name="show" aria-label="Show"><option value="">A few fireworks</option>${d.shows.map((s) => `<option value="${esc(s.id)}" ${s.id === b.show ? "selected" : ""}>🎬 ${esc(s.name)}</option>`).join("")}</select>
      <label class="check small"><input type="checkbox" name="say" ${b.say ? "checked" : ""}> Wish them in the game</label>
      <span class="muted small">${b.player ? (annDaysUntil(b) === 0 ? "🎂 Today!" : `in ${annDaysUntil(b)} days`) : ""}</span>
      <button class="btn sm" type="button" data-del aria-label="Remove">×</button></div>`;
  el.innerHTML = `<section class="panel"><p class="muted" style="margin-bottom:12px">On someone's birthday a banner wishes them a happy birthday everywhere, their show plays once on each screen, and (if you like) the game wishes them happy birthday when they join. Before that, a smaller banner counts the days.</p>
    <datalist id="ann-players">${d.players.map((p) => `<option value="${esc(p)}">`).join("")}</datalist>
    <div class="ann-bdays" id="ann-bdays">${list.map(row).join("") || ""}</div>
    <button class="btn" id="ann-bd-add" type="button" style="margin-top:10px">+ Add a birthday</button>
    <div class="fw-row" style="margin-top:14px"><span>Banner ahead</span><span><input class="input sm" type="number" min="0" max="31" id="ann-soon" value="${d.birthday_soon}" style="width:70px"> days before (0 for none)</span></div>
    <div class="actions" style="justify-content:flex-start;margin-top:12px"><button class="btn primary" id="ann-bd-save" type="button">Save birthdays</button></div></section>`;
  $("#ann-bd-add").addEventListener("click", () => {
    const now = new Date();
    $("#ann-bdays").insertAdjacentHTML("beforeend", row({ player: "", month: now.getMonth() + 1, day: now.getDate(), show: "", say: true }));
    $("#ann-bdays").lastElementChild.querySelector("[name=player]").focus();
  });
  $("#ann-bdays").addEventListener("click", (e) => { if (e.target.closest("[data-del]")) e.target.closest(".ann-bday").remove(); });
  $("#ann-bd-save").addEventListener("click", async () => {
    const birthdays = $$(".ann-bday").map((r) => ({ player: r.querySelector("[name=player]").value.trim(), month: +r.querySelector("[name=month]").value,
      day: +r.querySelector("[name=day]").value, show: r.querySelector("[name=show]").value, say: r.querySelector("[name=say]").checked })).filter((b) => b.player);
    const bad = birthdays.find((b) => !/^[A-Za-z0-9_]{1,16}$/.test(b.player));
    if (bad) { showToast(`“${esc(bad.player)}” isn't a Minecraft name`, 4000); return; }
    if (await annSave({ birthdays, birthday_soon: +$("#ann-soon").value || 0 }, "Birthdays saved")) renderAnn();
  });
}

// ---------------------------------------------------------------- bedtime
function annBedtime(el) {
  const d = ann.data, b = d.bedtime;
  el.innerHTML = `<section class="panel" style="max-width:720px">
    <label class="switch-row"><span><b>Count down to bedtime</b><br><small class="muted">A banner on the status page and in Solstone before a server's bedtime, then “asleep until…” overnight.</small></span><input type="checkbox" role="switch" id="ann-bt-on" ${b.show ? "checked" : ""}></label>
    <div class="fw-row" style="margin-top:10px"><span>Starts</span><span><input class="input sm" type="number" min="5" max="180" id="ann-bt-min" value="${b.minutes}" style="width:76px"> minutes before bedtime</span></div>
    <h3 class="fws-sub" style="margin-top:16px">Servers</h3>
    <ul class="ann-bt-list">${d.servers.map((s) => `<li><b>${esc(s.name)}</b> <span class="muted">${s.bedtime ? "Bedtime is on" : "No bedtime set"}</span> <a href="#/s/${encodeURIComponent(s.id)}/control">Set it in Control</a></li>`).join("")}</ul>
    <div class="actions" style="justify-content:flex-start;margin-top:12px"><button class="btn primary" id="ann-bt-save" type="button">Save</button></div></section>`;
  $("#ann-bt-save").addEventListener("click", () => annSave({ bedtime: { show: $("#ann-bt-on").checked, minutes: +$("#ann-bt-min").value || 30 } }));
}

// ---------------------------------------------------------------- TV mode
const ANN_SLIDES = [["now", "Who's playing", "Server, players, health and gear"], ["map", "Where everyone is", "The position map (when coordinates are shown)"],
  ["leaders", "Leaderboards", "Time played, levels, mobs, blocks mined…"], ["recap", "Recap and on this day", "Today, yesterday, and this date in past years"],
  ["feed", "Recent activity", "Joins, deaths and advancements"], ["news", "Announcements", "Big, when there are any"]];
function annTv(el) {
  const t = ann.tv;
  el.innerHTML = `<section class="panel" style="max-width:760px">
    <p class="muted" style="margin-bottom:10px">TV mode turns the status page into a slideshow for a screen on the wall: one thing at a time, big enough to read across the room, with banners and fireworks on top. Open it with the 📺 button on the status page, or go straight to <a href="/status?tv=1" target="_blank" rel="noopener">${esc(location.origin)}/status?tv=1</a>.</p>
    ${ann.data.status_enabled ? "" : `<div class="notice">The public status page is off. Turn it on under <a href="#/admin">Users &amp; activity</a> first.</div>`}
    <h3 class="fws-sub">Slides</h3>
    ${ANN_SLIDES.map(([k, l, h]) => `<label class="switch-row"><span><b>${l}</b><br><small class="muted">${h}</small></span><input type="checkbox" role="switch" data-slide="${k}" ${t.slides[k] ? "checked" : ""}></label>`).join("")}
    <div class="fw-row" style="margin-top:12px"><span>Each slide</span><span><input class="input sm" type="number" min="6" max="120" id="ann-tv-secs" value="${t.seconds}" style="width:76px"> seconds</span></div>
    <label class="switch-row"><span>Go through every server in turn<br><small class="muted">Otherwise it stays on the one that's picked</small></span><input type="checkbox" role="switch" id="ann-tv-rotate" ${t.rotate ? "checked" : ""}></label>
    <div class="actions" style="justify-content:flex-start;margin-top:12px"><button class="btn primary" id="ann-tv-save" type="button">Save</button></div></section>
    <section class="panel" style="max-width:760px;margin-top:16px"><h3 class="fws-sub">Recap history</h3>
      <p class="muted small">Every day is summarised and kept for good, so “on this day” can look back years. When Solstone first starts it also reads each server's old logs (the <code>logs/*.log.gz</code> files Minecraft keeps) to fill in the days before it was installed. If you've copied older logs in, read them again here.</p>
      <button class="btn" id="ann-backfill" type="button" style="margin-top:8px">Read old logs again</button></section>`;
  $("#ann-tv-save").addEventListener("click", async () => {
    const slides = {};
    $$("[data-slide]").forEach((i) => { slides[i.dataset.slide] = i.checked; });
    try { ann.tv = await post("/api/settings/tv", { slides, seconds: +$("#ann-tv-secs").value || 15, rotate: $("#ann-tv-rotate").checked }, "PUT"); showToast("TV mode saved", 2000); }
    catch (e) { showToast(esc(e.message), 5000); }
  });
  $("#ann-backfill").addEventListener("click", async (e) => {
    e.target.disabled = true; e.target.textContent = "Reading…";
    try { const r = await post("/api/recap/backfill"); showToast(r.days ? `Filled in ${r.days} days` : "Nothing new in the old logs", 3500); }
    catch (err) { showToast(esc(err.message), 5000); }
    e.target.disabled = false; e.target.textContent = "Read old logs again";
  });
}
