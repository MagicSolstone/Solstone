/* Solstone — Firework settings (admins): what the show launches, each player's join firework,
   and the calendar of holidays (their colours, banners and rewards). Loaded after app.js,
   control.js and editor.js. */
"use strict";

const FWS_TABS = [["show", "The show"], ["join", "Join fireworks"]];
const FWS_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const FWS_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const fws = { tab: "show", data: null, designs: [], editing: null };

function fwsDateText(e) {
  const d = e.date, ord = (n) => (n === -1 ? "last" : ["", "1st", "2nd", "3rd", "4th"][n]);
  const base = d.type === "fixed" ? `${FWS_MONTHS[d.month - 1]} ${d.day}` : d.type === "easter" ? "Easter Sunday"
    : d.type === "nth" ? `${ord(d.n)} ${FWS_WEEKDAYS[d.weekday]} of ${FWS_MONTHS[d.month - 1]}` : d.type === "weekly" ? `every ${FWS_WEEKDAYS[d.weekday]}` : d.iso;
  return `${base}${e.days > 1 ? ` (${e.days} days)` : ""}`;
}

async function viewFireworkSettings() {
  if (!isAdmin()) { location.replace("#/fireworks"); return; }
  curSid = null;
  document.title = `Firework settings · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  const [data, fw, designs] = await Promise.all([api("/api/fireworks/show"), api("/api/public/fireworks"), api("/api/fireworks").catch(() => [])]);
  fws.data = data; fws.fw = fw; fws.designs = designs;
  setView(`<div class="fwe-head"><h1>Fireworks</h1>
      ${fireworksTabs("show")}
      <p class="muted" id="fws-today"></p>
      <p class="muted small">Holidays and their colours: <a href="#/manage/holidays">Manage → Announcements → Holidays</a></p></div>
    <nav class="fwe-tabs fws-tabs" role="tablist" aria-label="Show settings">${FWS_TABS.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${fws.tab === k}">${l}</button>`).join("")}</nav>
    <div id="fws-body"></div>`);
  $$(".fws-tabs [data-tab]").forEach((b) => b.addEventListener("click", () => {
    fws.tab = b.dataset.tab; $$(".fws-tabs [data-tab]").forEach((x) => x.setAttribute("aria-selected", String(x === b))); renderFws();
  }));
  renderToday();
  renderFws();
}
function renderToday() {
  if (!$("#fws-today")) return;                     // Manage → Announcements → Holidays has no "today" line
  const t = fws.data.today, bits = [];
  if (t.theme) bits.push(`Today: <b>${esc(t.theme.emoji)} ${esc(t.theme.name)}</b>`);
  $("#fws-today").innerHTML = bits.join(" · ") || "No holiday today.";
}
async function fwsSave(body, msg = "Saved") {
  try {
    fws.data = await post("/api/fireworks/show", body, "PUT");
    fwLoaded = null; loadFireworkSettings();     // the sky on this page picks it up
    renderToday(); showToast(msg, 1800);
  } catch (err) { showError(esc(err.message), 4000); }
}

function renderFws() {
  const el = $("#fws-body");
  if (fws.tab === "show") {
    el.innerHTML = `<p class="muted small fws-sky-moved">🌌 The sky behind every page (follow the game or always night, and fireworks in the daytime) is in <a href="#/manage/website">Website → Site details</a>.</p>
      <section class="panel fw-settings" id="fw-settings">${fireworksSettingsHtml(fws.fw)}</section>
      <section class="panel fws-community" id="fws-community"></section>`;
    wireFireworksSettings($("#fw-settings"), fws.fw);
    renderCommunity($("#fws-community"));
  } else if (fws.tab === "join") renderJoin(el);
}

// ---------------------------------------------------------------- fireworks people made
// Each maker has a frequency (Off leaves out everything they made), and each of their
// fireworks has its own, on top of whether its maker put it in the show.
function renderCommunity(el) {
  const creators = fws.data.creators || [];
  if (!creators.length) { el.innerHTML = `<h3 class="fw-sub">From the editor</h3><p class="muted">Nobody has saved a firework yet. Make one in the <a href="#/fireworks">editor</a>.</p>`; return; }
  const open = fws.openCreators ||= new Set();
  el.innerHTML = `<h3 class="fw-sub">From the editor <span class="muted small">how often each person's fireworks come up, and each firework</span></h3>
    <div class="fws-creators">${creators.map((c) => {
      const mine = fws.designs.filter((d) => d.author === c.name);
      const inShow = mine.filter((d) => d.in_show).length;
      return `<div class="fws-creator ${c.weight ? "" : "off"}" data-creator="${esc(c.name)}">
        <div class="fws-creator-head"><button type="button" class="link-btn" data-toggle aria-expanded="${open.has(c.name)}">${open.has(c.name) ? "▾" : "▸"} <b>${esc(c.name)}</b></button>
          <span class="muted small">${mine.length} made · ${inShow} in the show</span>${freqSeg(`data-creator-weight="${esc(c.name)}"`, c.weight)}</div>
        ${open.has(c.name) ? `<div class="fws-designs">${mine.map((d) => `<div class="fws-design ${d.in_show && d.weight ? "" : "off"}" data-id="${d.id}">
            <span class="fwe-dots">${d.colors.map((x) => `<i style="background:${x}"></i>`).join("")}</span><span class="fws-dname">${esc(d.name)}</span>
            <label class="check small"><input type="checkbox" data-inshow ${d.in_show ? "checked" : ""}> In the show</label>
            ${freqSeg(`data-design-weight="${d.id}"`, d.weight ?? 1)}
            <button type="button" class="icon-btn" data-play title="Launch it" aria-label="Launch ${esc(d.name)}">▶</button></div>`).join("")}</div>` : ""}
      </div>`;
    }).join("")}</div>`;
  el.querySelectorAll("[data-toggle]").forEach((b) => b.addEventListener("click", () => {
    const n = b.closest("[data-creator]").dataset.creator;
    open.has(n) ? open.delete(n) : open.add(n);
    renderCommunity(el);
  }));
  el.querySelectorAll("[data-creator-weight] button").forEach((b) => b.addEventListener("click", async () => {
    const n = b.closest("[data-creator]").dataset.creator;
    await fwsSave({ creators: { [n]: +b.dataset.freq } }, +b.dataset.freq ? `${n}'s fireworks: ${FREQS.find(([v]) => v === +b.dataset.freq)[1]}` : `${n}'s fireworks are out of the show`);
    renderCommunity(el);
  }));
  const updateDesign = async (id, body) => {
    try { await post(`/api/fireworks/${id}`, body, "PUT"); fws.designs = await api("/api/fireworks"); fwLoaded = null; loadFireworkSettings(); showToast("Saved", 1200); }
    catch (err) { showError(esc(err.message), 3000); }
    fws.data = await api("/api/fireworks/show"); renderCommunity(el);
  };
  el.querySelectorAll("[data-design-weight] button").forEach((b) => b.addEventListener("click", () => updateDesign(b.closest("[data-id]").dataset.id, { weight: +b.dataset.freq })));
  el.querySelectorAll("[data-inshow]").forEach((c) => c.addEventListener("change", () => updateDesign(c.closest("[data-id]").dataset.id, { in_show: c.checked })));
  el.querySelectorAll("[data-play]").forEach((b) => b.addEventListener("click", () => {
    const d = fws.designs.find((x) => x.id === b.closest("[data-id]").dataset.id);
    if (d) openFwPreview({ title: d.name, sub: `by ${d.author || "someone"}`, run: (sc) => sc.launch({ ...d }) });
  }));
}

// ---------------------------------------------------------------- join fireworks
function renderJoin(el) {
  const sig = fws.data.signatures, players = fws.data.players, on = fws.data.join?.on !== false;
  el.innerHTML = `<section class="panel"><label class="switch-row" style="margin-bottom:10px"><span><b>A firework when someone joins</b><br><small class="muted">On every Solstone page that's open: their own join firework, or a random one if they haven't picked</small></span>
      <input type="checkbox" role="switch" data-join-on ${on ? "checked" : ""}></label>
    <p class="muted" style="margin-bottom:12px">Pick a firework for each player (players can pick their own too, from their account menu). It goes off whenever they join, so everyone knows who just arrived. Make one in the <a href="#/fireworks">editor</a> first.</p>
    ${players.length ? `<div class="fws-join">${players.map((n) => `<div class="fws-join-row">${faceHtml({ name: n }, 28)}<b>${esc(n)}</b>
      <select class="input sm" data-player="${esc(n)}"><option value="">Random firework</option>${fws.designs.map((d) => `<option value="${d.id}" ${sig[n.toLowerCase()] === d.id ? "selected" : ""}>🎨 ${esc(d.name)} · by ${esc(d.author)}</option>`).join("")}</select>
      <button type="button" class="icon-btn" data-try="${esc(n)}" title="Try it" aria-label="Try ${esc(n)}'s firework">▶</button></div>`).join("")}</div>`
    : `<p class="muted">Nobody has joined a server yet.</p>`}</section>`;
  el.querySelector("[data-join-on]").addEventListener("change", (e) => fwsSave({ join: { on: e.target.checked } }, e.target.checked ? "Join fireworks on" : "Join fireworks off"));
  el.querySelectorAll("[data-player]").forEach((s) => s.addEventListener("change", () => {
    const next = { ...fws.data.signatures };
    if (s.value) next[s.dataset.player.toLowerCase()] = s.value; else delete next[s.dataset.player.toLowerCase()];
    fwsSave({ signatures: next }, `Join firework set for ${s.dataset.player}`);
  }));
  el.querySelectorAll("[data-try]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const r = await post("/api/fireworks/test-join", { player: b.dataset.try });
      openFwPreview({ title: `${b.dataset.try} joins`, sub: "Their join firework", run: (sc, ui) => pvRunShow(sc, r.show, ui) });
    } catch (err) { showError(esc(err.message), 3000); }
  }));
}

// ---------------------------------------------------------------- calendar (Manage → Announcements → Holidays)
// Holidays and special days: the ones switched on show on the Events page, put their message on every page
// that day and give the fireworks their colours. Kept in the fireworks settings (fw_calendar), edited here.
async function viewHolidays() {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = `Holidays · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  const [data, designs] = await Promise.all([api("/api/fireworks/show"), api("/api/fireworks").catch(() => [])]);
  fws.data = data; fws.designs = designs; fws.editing = null;
  setView(`<div class="fwe-head"><h1>Holidays</h1>
      <p class="muted">Holidays and special days. The ones switched <b>On</b> show on the <a href="#/events">Events</a> page, put their message on every page that day and colour the fireworks. Switch off the ones you don't celebrate, or add your own.</p></div>
    <div id="hol-body"></div>`);
  renderCalendar($("#hol-body"));
}
// A small note when a day shares dates with another one; it's allowed, this just says which one wins.
const fwsDay = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d).toLocaleDateString([], { day: "numeric", month: "short" }); };
function fwsOverlapNote(id) {
  const list = fws.data?.overlaps?.[id] || [];
  if (!list.length) return "";
  const when = (o) => (o.count === 1 ? fwsDay(o.dates[0]) : `${o.count} days`);
  const text = (o) => o.wins ? `shares ${when(o)} with ${o.with} (this one's colours show)` : `${o.with} takes over on ${when(o)}`;
  const shown = list.slice(0, 2).map(text), more = list.length - shown.length;
  const all = list.map((o) => `${text(o)}${o.count > 1 ? ` (${o.dates.map(fwsDay).join(", ")}${o.count > 3 ? "…" : ""})` : ""}`).join("\n");
  return `<div class="fws-overlap" title="${esc(all)}">⚠ ${esc(shown.join(" · "))}${more > 0 ? ` · +${more} more` : ""}</div>`;
}

function renderCalendar(el) {
  const cal = fws.data.calendar;
  el.innerHTML = `<section class="panel"><p class="muted" style="margin-bottom:12px">On these days the fireworks take on the day's colours and favourite kinds.</p>
    <div class="fws-cal">${cal.map((e, i) => fws.editing === i ? calEditHtml(e, i) : `<div class="fws-cal-row ${e.enabled ? "" : "off"}" data-i="${i}">
      <span class="fws-emoji">${esc(e.emoji)}</span>
      <div><b>${annFmt(e.name_fmt || e.name)}</b><div class="muted small">${esc(fwsDateText(e))}${e.banner_days ? ` · banner ${e.banner_days} day${e.banner_days === 1 ? "" : "s"} before` : ""}${e.reward?.items?.length ? " · 🎁 reward" : ""}${e.colors_before || e.colors_after ? ` · colours ${e.colors_before} day${e.colors_before === 1 ? "" : "s"} before to ${e.colors_after} after` : ""}</div>
        ${fwsOverlapNote(e.id)}<div class="fwe-dots">${e.colors.map((c) => `<i style="background:${c}"></i>`).join("")}</div></div>
      <label class="check small"><input type="checkbox" data-en ${e.enabled ? "checked" : ""}> On</label>
      <button type="button" class="btn sm" data-edit>Edit</button></div>`).join("")}</div>
    <div class="btn-row" style="margin-top:12px"><button type="button" class="btn" id="fws-add">+ Add a date</button>
      <button type="button" class="btn" id="fws-reset">Restore the standard holidays</button></div></section>`;
  el.querySelectorAll(".fws-cal-row").forEach((row) => {
    const i = +row.dataset.i;
    row.querySelector("[data-en]").addEventListener("change", (ev) => { const next = fweCopy(cal); next[i].enabled = ev.target.checked; fwsSave({ calendar: next }).then(() => renderCalendar(el)); });
    row.querySelector("[data-edit]").addEventListener("click", () => { fws.editing = i; renderCalendar(el); });
  });
  if (fws.editing != null && cal[fws.editing]) wireCalEdit(el, fws.editing);
  $("#fws-add")?.addEventListener("click", async () => {
    const next = [...fweCopy(cal), { name: "New holiday", emoji: "🎉", date: { type: "fixed", month: new Date().getMonth() + 1, day: new Date().getDate() }, days: 1,
      colors: ["#ff8fc0", "#ffe45c", "#4fd7e6"], kinds: ["heart", "star", "crossette"], message: "", enabled: true }];
    await fwsSave({ calendar: next }, "Added");
    fws.editing = fws.data.calendar.length - 1; renderCalendar(el);
  });
  $("#fws-reset")?.addEventListener("click", async () => {
    if (!(await confirmBox("Restore the standard holidays?", "Your own dates are kept; the standard ones go back to how they started.", "Restore", false))) return;
    const custom = cal.filter((e) => !["newyear", "valentine", "stpatrick", "easter", "july4", "halloween", "thanksgiving", "christmas", "friday"].includes(e.id));
    await fwsSave({ calendar: [...fwsDefaults(), ...custom] }, "Restored");
    fws.editing = null; renderCalendar(el);
  });
}
function fwsDefaults() { return fweCopy(fws.data.calendar_defaults || []); }
function calEditHtml(e, i) {
  const d = e.date, kinds = new Set(e.kinds);
  const num = (name, v, min, max, w = 64) => `<input class="input sm" type="number" name="${name}" min="${min}" max="${max}" value="${v}" style="width:${w}px">`;
  const sel = (name, opts, cur) => `<select class="input sm" name="${name}">${opts.map(([v, l]) => `<option value="${v}" ${String(v) === String(cur) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  const bn = e.banner || { show: true, style: "party", colors: [] }, rw = e.reward || {};
  const webFmt = `<span class="ann-fmt" role="toolbar" aria-label="Formatting"><button type="button" class="btn sm" data-wrap="**|**" title="Bold"><b>B</b></button><button type="button" class="btn sm" data-wrap="*|*" title="Italic"><i>I</i></button><button type="button" class="btn sm" data-wrap="__|__" title="Underline"><u>U</u></button>
        <button type="button" class="btn sm" data-link title="A link">🔗 Link</button>
        ${POST_COLOURS.map(([k, l]) => `<button type="button" class="ann-col pf-swatch-${k}" data-wrap="{${k}}|{/${k}}" title="${l}" aria-label="${l}"></button>`).join("")}
        <span class="muted small">Select words in the box you were last in, then pick.</span></span>`;
  return `<form class="fws-cal-edit hol-edit" data-i="${i}">${fwsOverlapNote(e.id)}
    <div class="hol-preview-wrap"><div class="hol-phases seg" role="group" aria-label="Preview the banner"></div><div class="hol-preview" aria-label="Preview"></div>
      <p class="hol-timeline muted small"></p></div>

    <fieldset class="hol-sec"><legend>📅 The holiday</legend>
      ${webFmt}
      <div class="fws-grid">
        <label class="wide">Name<input class="input" name="name" maxlength="120" value="${esc(e.name_fmt || e.name)}"></label>
        <label>Emoji<input class="input" name="emoji" maxlength="4" value="${esc(e.emoji)}" style="width:70px"></label>
      </div>
      <div class="fws-grid">
        <label>When${sel("dtype", [["fixed", "Same date every year"], ["nth", "A weekday in a month"], ["easter", "Easter Sunday (worked out each year)"], ["weekly", "Every week"], ["once", "Just once"]], d.type)}</label>
        <label class="fws-when">${d.type === "fixed" ? `${sel("month", FWS_MONTHS.map((m, k) => [k + 1, m]), d.month)} ${num("day", d.day, 1, 31)}`
          : d.type === "nth" ? `${sel("n", [[1, "1st"], [2, "2nd"], [3, "3rd"], [4, "4th"], [-1, "Last"]], d.n)} ${sel("weekday", FWS_WEEKDAYS.map((w, k) => [k, w]), d.weekday)} of ${sel("month", FWS_MONTHS.map((m, k) => [k + 1, m]), d.month)}`
          : d.type === "weekly" ? sel("weekday", FWS_WEEKDAYS.map((w, k) => [k, w]), d.weekday)
          : d.type === "once" ? `<input class="input sm" type="date" name="iso" value="${esc(d.iso || "")}">` : `<span class="muted small">Worked out each year</span>`}</label>
        <label class="inl">Lasts ${num("days", e.days, 1, 14)} day(s)</label>
      </div>
      <label class="fws-detail">Description on the Events page <span class="muted small">optional, under its name</span>
        <textarea class="input" name="detail" rows="4" maxlength="600" placeholder="Log in any time this week for a present!">${esc(e.detail || "")}</textarea></label>
    </fieldset>

    <fieldset class="hol-sec"><legend>📣 Its banner <span class="muted small">one banner on every page, from the countdown to the last day of its reward</span></legend>
      <label class="check"><input type="checkbox" name="bshow" ${bn.show !== false ? "checked" : ""}> Show a banner</label>
      <div class="hol-bn-opts" ${bn.show !== false ? "" : "hidden"}>
        <label class="wide">Message on the day <span class="muted small">(blank: its name)</span><input class="input" name="message" maxlength="240" value="${esc(e.message_fmt ?? e.message)}" placeholder="Merry Christmas!"></label>
        ${d.type === "weekly" ? "" : `<label class="inl">Counting down from ${num("banner_days", e.banner_days || 0, 0, 30)} days before <span class="muted small">(0: no countdown, just the day)</span></label>`}
        <div class="fw-row ann-looks"><span>Look</span><div class="seg" role="group" data-seg="bstyle">${ANN_STYLES.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${v === bn.style}">${l}</button>`).join("")}</div></div>
        <div class="fw-row ann-colors" ${bn.style === "custom" ? "" : "hidden"}><span>Colours</span>
          ${[0, 1, 2].map((k) => `<label class="ann-color"><input type="color" name="bcolor${k}" value="${esc((bn.colors || [])[k] || ["#2f6fd0", "#8a3ad0", "#d0435f"][k])}" aria-label="Colour ${k + 1}">${k === 2 ? `<input type="checkbox" name="buse3" ${(bn.colors || []).length > 2 ? "checked" : ""} aria-label="Use a third colour"> <small class="muted">a third</small>` : ""}</label>`).join("")}
          <small class="muted">Left to right. Darker colours keep the words easy to read.</small></div>
      </div>
    </fieldset>

    <fieldset class="hol-sec fws-reward"><legend>🎁 Reward <span class="muted small">everyone who plays during it gets this once (each server, each year); no items: no reward</span></legend>
      <div class="fws-reward-items">${(rw.items || []).map((it, k) => `<span class="fws-reward-item">${itemIcon({ id: it.item })}<b>${esc(it.count)} × ${esc(it.name || itemName({ id: it.item }))}</b>
        <button type="button" class="chip-x" data-rm-reward="${k}" aria-label="Remove ${esc(it.name || it.item)}">×</button></span>`).join("")}
        ${(rw.items || []).length < 9 ? `<button type="button" class="btn sm" data-add-reward>＋ Add an item</button>` : ""}</div>
      <div class="hol-rw-opts" ${(rw.items || []).length ? "" : "hidden"}>
        <label class="inl">Given from ${num("rbefore", rw.before || 0, 0, 30)} days before to ${num("rafter", rw.after || 0, 0, 30)} days after
          <span class="muted small">(0 and 0: just ${e.days > 1 ? "its days" : "the day"}; Thursday's Thanksgiving through Sunday: 0 and 3)</span></label>
        <label class="check"><input type="checkbox" name="rbanner" ${rw.banner ? "checked" : ""}> Keep the banner up on those extra days <span class="muted small">(the reward shows on it the whole time)</span></label>
        <label class="wide hol-after" ${rw.banner && rw.after ? "" : "hidden"}>The banner after the holiday says <span class="muted small">(blank: “${esc(e.name)} is over, but there's still time for its reward!”)</span>
          <input class="input" name="rafter_text" maxlength="160" value="${esc(rw.after_text || "")}" placeholder="Merry Christmas! Rewards still available through the end of the week"></label>
        <label class="wide">Description <span class="muted small">on the Events page and the banner</span>${webFmt}
          <input class="input" name="rnote" maxlength="300" value="${esc(rw.note || "")}" placeholder="Reward for playing ${esc(e.name)}${rw.after ? " weekend" : ""}!"></label>
        <label class="wide">Message in the game when they get it <span class="muted small">the game's own colours; then what they got</span>
          <span class="wel-tools hol-game-fmt">${WELCOME_COLOURS.map(([c, hex, l]) => `<button type="button" class="wel-col" data-code="&${c}" style="background:${hex}" title="${l}" aria-label="${l}"></button>`).join("")}
            ${WELCOME_STYLES.map(([c, t, l]) => `<button type="button" class="btn sm wel-sty" data-code="&${c}" title="${l}" aria-label="${l}">${t}</button>`).join("")}
            <button type="button" class="btn sm" data-code="{player}" title="Their name">{player}</button></span>
          <textarea class="input" name="rmessage" rows="3" maxlength="600" placeholder="&6&l${esc(e.name)}!&r &eA present for being here">${esc(rw.message || "")}</textarea>
          <span class="muted small">Each line is its own line in the chat (up to 5).</span></label>
        <div class="wel-preview hol-game-preview"></div>
        <p class="muted small">No room in their inventory? It waits (nothing's dropped on the ground): they're told to make room, and it arrives by itself when they do.</p>
      </div>
    </fieldset>
    <details class="fws-more" ${fws.moreOpen ? "open" : ""}><summary>Fireworks <span class="muted small">colours (for the day or the whole week) and favourite kinds</span></summary>
    <div class="fws-sub">Colours <span class="muted small">(leave none for the usual colours)</span></div>
    <div class="fwe-colors" data-cal-colors>${e.colors.map((c, k) => `<span class="fwe-color"><input type="color" value="${c}" data-cc="${k}"><button type="button" class="chip-x" data-rmcc="${k}" aria-label="Remove">×</button></span>`).join("")}
      ${e.colors.length < 6 ? `<button type="button" class="btn sm" data-addcc>+ Colour</button>` : ""}</div>
    <div class="fws-grid">
      <label class="inl">These colours from ${num("cbefore", e.colors_before || 0, 0, 30)} days before to ${num("cafter", e.colors_after || 0, 0, 30)} days after
        <span class="muted small">(a red, green and white week for Christmas: 3 and 3)</span></label>
      <label class="check"><input type="checkbox" name="recolor" ${e.recolor !== false ? "checked" : ""}> Players' own fireworks take these colours too <span class="muted small">(when they go off by themselves; one launched by hand keeps its own)</span></label>
    </div>
    <div class="fws-sub">Favourite kinds <span class="muted small">(go off more often then)</span></div>
    <div class="fws-kinds">${[...FW_LABELS.map(([k, l]) => [k, l]), ...fws.designs.map((x) => [`custom:${x.id}`, `🎨 ${x.name}`])].map(([k, l]) =>
      `<label class="chip ${kinds.has(k) ? "on" : ""}"><input type="checkbox" value="${esc(k)}" data-kind ${kinds.has(k) ? "checked" : ""}> ${esc(l)}</label>`).join("")}</div>
    </details>
    <div class="btn-row"><button class="btn primary" type="submit">Save</button><button type="button" class="btn" data-cancel>Cancel</button>
      <button type="button" class="btn" data-preview>Preview</button><button type="button" class="btn danger" data-del>Delete</button></div>
  </form>`;
}
// The holiday's one banner at each point: counting down, on the day, and (if its reward runs on) after it.
function holPhases(e) {
  const rw = e.reward || {}, items = (rw.items || []).length, stay = items && rw.banner;
  return [((e.banner_days || 0) > 0 || (stay && rw.before > 0)) && e.date.type !== "weekly" && ["soon", "Before"], ["day", "On the day"],
    stay && rw.after > 0 && ["after", "After"]].filter(Boolean);
}
// The last day of a holiday's reward, as the banner says it ("Now until Sat 27 Dec"), from the next time it comes round.
function holUntil(e) {
  const rw = e.reward || {};
  if (!e.next) return rw.after ? `Now until ${rw.after} day${rw.after === 1 ? "" : "s"} after` : "";
  const [y, m, d] = e.next.split("-").map(Number);
  const last = new Date(y, m - 1, d + (e.days || 1) - 1 + (rw.after || 0));
  return (e.days || 1) === 1 && !rw.after && !rw.before ? "Today only" : `Now until ${last.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}`;
}
function holBannerHtml(e, phase) {
  const rw = e.reward || {}, items = (rw.items || []).map((x) => ({ ...x, name: x.name || itemName({ id: x.item }) }));
  const name = e.name_fmt || e.name, days = Math.max(1, e.banner_days || 1);
  const text = phase === "soon" ? `${name} is ${days === 1 ? "tomorrow" : `in ${days} days`}` : phase === "after" ? (rw.after_text || `${name} is over, but there's still time for its reward!`) : (e.message_fmt || name);
  const giving = items.length && (phase === "day" || phase === "after" || (rw.before || 0) >= days);
  const it = { style: e.banner.style, colors: e.banner.style === "custom" ? e.banner.colors : [], items, reward_note: rw.note, reward_until: holUntil(e) };
  return `<div class="bn bn-${esc(it.style)}"${annLook(it)}><span class="bn-emoji">${esc(e.emoji || "🎉")}</span>
    <div class="bn-text"><b>${annFmt(text)}</b>${giving ? bnRewardHtml(it) : ""}</div>${phase === "soon" ? `<span class="bn-cd">${days} d 0 h</span>` : ""}</div>`;
}
function holTimeline(e) {
  if (!e.banner.show) return "";
  const rw = e.reward || {}, items = (rw.items || []).length, stay = items && rw.banner;
  const before = Math.max(e.date.type === "weekly" ? 0 : e.banner_days || 0, stay ? rw.before || 0 : 0), after = stay ? rw.after || 0 : 0;
  const bits = [before ? `from ${before} day${before === 1 ? "" : "s"} before${e.banner_days ? ", counting down" : ""}` : "",
    `on ${e.days > 1 ? `its ${e.days} days` : "the day"}`, after ? `and ${after} day${after === 1 ? "" : "s"} after, while the reward's still being given` : ""];
  return `The banner shows ${bits.filter(Boolean).join(", ")}. It's one banner the whole way through: it just changes what it says.`;
}
function wireCalEdit(el, i) {
  const form = el.querySelector(".fws-cal-edit");
  const draft = fweCopy(fws.data.calendar[i]);
  const read = () => {
    const f = new FormData(form), dtype = f.get("dtype");
    draft.name_fmt = draft.name = f.get("name"); draft.emoji = f.get("emoji"); draft.days = +f.get("days") || 1;
    draft.message_fmt = draft.message = f.get("message") ?? draft.message_fmt ?? "";
    if (f.get("banner_days") != null) draft.banner_days = Math.max(0, Math.min(30, +f.get("banner_days") || 0));
    draft.detail = f.get("detail") || "";
    draft.banner = { show: !!f.get("bshow"), style: form.querySelector('[data-seg="bstyle"] [aria-pressed="true"]')?.dataset.v || "party",
      colors: [f.get("bcolor0"), f.get("bcolor1"), ...(f.get("buse3") ? [f.get("bcolor2")] : [])] };
    draft.reward = { items: draft.reward?.items || [], message: f.get("rmessage") || "", note: f.get("rnote") || "", banner: !!f.get("rbanner"),      // items: picked below
      after_text: f.get("rafter_text") || "",
      before: Math.max(0, Math.min(30, +f.get("rbefore") || 0)), after: Math.max(0, Math.min(30, +f.get("rafter") || 0)) };
    draft.colors_before = Math.max(0, Math.min(30, +f.get("cbefore") || 0));
    draft.colors_after = Math.max(0, Math.min(30, +f.get("cafter") || 0));
    draft.recolor = !!f.get("recolor");
    const d = { type: dtype };
    if (dtype === draft.date.type) {
      if (f.get("month")) d.month = +f.get("month");
      if (f.get("day")) d.day = +f.get("day");
      if (f.get("weekday") != null) d.weekday = +f.get("weekday");
      if (f.get("n")) d.n = +f.get("n");
      if (f.get("iso")) d.iso = f.get("iso");
    } else Object.assign(d, { month: draft.date.month || 1, day: draft.date.day || 1, weekday: 4, n: 1, iso: new Date().toISOString().slice(0, 10) });
    draft.date = d;
    draft.kinds = [...form.querySelectorAll("[data-kind]:checked")].map((c) => c.value);
  };
  const redraw = () => { read(); fws.moreOpen = !!form.querySelector(".fws-more")?.open; fws.data.calendar[i] = draft; renderCalendar(el); };
  // the formatting buttons wrap what's selected in the box last typed in (the name, the banner's message,
  // the description, or the reward's description)
  const fmtBoxes = ["name", "message", "detail", "rnote"].map((n) => form.querySelector(`[name="${n}"]`)).filter(Boolean);
  let det = fmtBoxes[0];
  fmtBoxes.forEach((x) => x.addEventListener("focus", () => { det = x; }));
  const wrap = (a, z, fill = "words") => { const s0 = det.selectionStart ?? det.value.length, s1 = det.selectionEnd ?? s0; det.setRangeText(a + (det.value.slice(s0, s1) || fill) + z, s0, s1, "end"); det.focus(); holShow(); };
  form.querySelectorAll("[data-wrap], [data-link]").forEach((b) => b.addEventListener("mousedown", (ev) => ev.preventDefault()));
  form.querySelectorAll("[data-wrap]").forEach((b) => b.addEventListener("click", () => { const [a, z] = b.dataset.wrap.split("|"); wrap(a, z); }));
  form.querySelectorAll("[data-link]").forEach((b) => b.addEventListener("click", () => {
    const url = prompt("The link's address (https://…, or a page here like /help)");
    if (url && /^(https?:\/\/|\/)/.test(url.trim())) wrap("[", `](${url.trim()})`, "this link");
  }));
  // the game's own colours for the reward's message
  const gm = form.querySelector('[name="rmessage"]');
  form.querySelectorAll(".hol-game-fmt [data-code]").forEach((b) => {
    b.addEventListener("mousedown", (ev) => ev.preventDefault());
    b.addEventListener("click", () => { const a = gm.selectionStart ?? gm.value.length, z = gm.selectionEnd ?? a; gm.setRangeText(b.dataset.code, a, z, "end"); gm.focus(); holShow(); });
  });
  // the banner's look
  form.querySelectorAll('[data-seg="bstyle"] button').forEach((b) => b.addEventListener("click", () => {
    b.parentElement.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    form.querySelector(".ann-colors").hidden = b.dataset.v !== "custom";
    holShow();
  }));
  form.querySelector('[name="bshow"]').addEventListener("change", (ev) => { form.querySelector(".hol-bn-opts").hidden = !ev.target.checked; holShow(); });
  const afterBox = () => { form.querySelector(".hol-after").hidden = !(form.querySelector('[name="rbanner"]').checked && +form.querySelector('[name="rafter"]').value > 0); };
  form.querySelector('[name="rbanner"]')?.addEventListener("change", afterBox);
  form.querySelector('[name="rafter"]')?.addEventListener("input", afterBox);
  // the preview: the banner as it'll look before, on and after the day, and when it shows
  let phase = "day";
  const holShow = () => {
    read();
    const phases = holPhases(draft);
    if (!phases.some(([k]) => k === phase)) phase = phases[0]?.[0] || "day";
    form.querySelector(".hol-phases").innerHTML = phases.length > 1 ? phases.map(([k, l]) => `<button type="button" data-ph="${k}" aria-pressed="${k === phase}">${l}</button>`).join("") : "";
    form.querySelector(".hol-preview").innerHTML = draft.banner.show ? holBannerHtml(draft, phase) : `<p class="muted small">No banner for this one.</p>`;
    form.querySelector(".hol-timeline").textContent = holTimeline(draft);
    const pv = form.querySelector(".hol-game-preview");
    if (pv) pv.innerHTML = typeof welcomePreview === "function" && draft.reward.message ? welcomePreview(draft.reward.message, curSid) : "";
  };
  form.querySelector(".hol-phases").addEventListener("click", (ev) => { const b = ev.target.closest("[data-ph]"); if (b) { phase = b.dataset.ph; holShow(); } });
  form.addEventListener("input", holShow);
  form.addEventListener("change", holShow);
  holShow();
  // the reward: picked from the server's own items (with their pictures), like a contest's prize
  form.querySelector("[data-add-reward]")?.addEventListener("click", () => {
    const sid = (state.servers || []).find((x) => !x.game || x.game === "minecraft-java")?.id;
    if (!sid) { showError("Add a Java server first: the items come from it", 4000); return; }
    read();
    openGiveItem(sid, "", { title: `A reward for ${draft.name}`, pick: (item, count) => {
      draft.reward = { ...(draft.reward || {}), items: [...(draft.reward?.items || []), { item: item.id, count, name: item.name }].slice(0, 9) };
      fws.data.calendar[i] = draft; fws.moreOpen = !!form.querySelector(".fws-more")?.open; renderCalendar(el);
    } });
  });
  form.querySelectorAll("[data-rm-reward]").forEach((b) => b.addEventListener("click", () => {
    read();
    draft.reward.items = draft.reward.items.filter((_, k) => k !== +b.dataset.rmReward);
    fws.data.calendar[i] = draft; renderCalendar(el);
  }));
  form.querySelector('[name="dtype"]').addEventListener("change", redraw);
  form.querySelector('[name="days"]').addEventListener("change", redraw);
  form.querySelectorAll("[data-kind]").forEach((c) => c.addEventListener("change", () => c.closest(".chip").classList.toggle("on", c.checked)));
  form.querySelectorAll("[data-cc]").forEach((c) => c.addEventListener("input", () => { draft.colors[+c.dataset.cc] = c.value; }));
  form.querySelectorAll("[data-rmcc]").forEach((b) => b.addEventListener("click", () => { draft.colors.splice(+b.dataset.rmcc, 1); redraw(); }));
  form.querySelector("[data-addcc]")?.addEventListener("click", () => { draft.colors.push(pick2(FW_COLORS)); redraw(); });
  form.querySelector("[data-cancel]").addEventListener("click", async () => { fws.editing = null; fws.data = await api("/api/fireworks/show"); renderCalendar(el); });
  form.querySelector("[data-del]").addEventListener("click", async () => {
    if (!(await confirmBox(`Delete ${draft.name}?`, "It won't show on Events or change the fireworks any more.", "Delete"))) return;
    const next = fweCopy(fws.data.calendar); next.splice(i, 1);
    fws.editing = null; await fwsSave({ calendar: next }, "Deleted"); renderCalendar(el);
  });
  form.querySelector("[data-preview]").addEventListener("click", () => {
    read();
    const theme = { colors: draft.colors, kinds: draft.kinds, name: draft.name, emoji: draft.emoji, message: draft.message };
    openFwPreview({ title: `${draft.emoji} ${draft.name}`, theme, sub: "The day's colours and favourite kinds",
      run: (sc, ui) => {
        if (draft.message) ui.message(`${draft.emoji} ${annPlain(draft.message)}`, 3500);
        sc.boost(8);                                       // a taste of the day: its colours and kinds
      } });
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); read();
    const next = fweCopy(fws.data.calendar); next[i] = draft;
    fws.editing = null; await fwsSave({ calendar: next }); renderCalendar(el);
  });
}


// ---------------------------------------------------------------- the sky (shown in Website → Site details)
async function wsSky(el) {
  const box = document.createElement("section");
  box.className = "panel fws-sky ws-sky";
  el.append(box);
  try { fws.fw = await api("/api/public/fireworks"); } catch { box.remove(); return; }
  fws.data = { ...(fws.data || {}), servers: (state.servers || []).filter((x) => x.type !== "bedrock").map((x) => ({ id: x.id, name: x.name })) };
  renderSky(box);
}
function renderSky(el) {
  const sky = fws.fw.sky || { mode: "game", server: "auto", daytime: "smoke" };
  const seg = (name, opts, cur) => `<div class="seg" role="group" data-sky="${name}">${opts.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${v === cur}">${l}</button>`).join("")}</div>`;
  el.innerHTML = `<h3 class="fw-sub">The sky <span class="muted small">behind every page</span></h3>
    <div class="fw-row"><span>Sky</span>${seg("mode", [["game", "Follow the game"], ["night", "Always night"]], sky.mode)}</div>
    ${sky.mode === "game" ? `<div class="fw-row"><span>From</span><select class="input sm" data-sky-server><option value="auto">The server people are playing on</option>
        ${(fws.data.servers || []).map((x) => `<option value="${esc(x.id)}" ${sky.server === x.id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></div>
      <div class="fw-row"><span>In the daytime</span>${seg("daytime", [["smoke", "Coloured smoke"], ["normal", "Same as night"], ["pause", "Wait for night"]], sky.daytime)}</div>
      <p class="muted small">The sun, moon (with its phases), clouds, rain and thunder follow the game. On a server's page the sky shows that server. Daytime fireworks leave coloured smoke and go up less often, like real ones; join fireworks still go off either way.</p>` : ""}`;
  const save = async (patch) => {
    try {
      const cfg = await post("/api/settings/fireworks", { sky: patch }, "PUT");
      fws.fw = { ...fws.fw, ...cfg };
      fwLoaded = null; await loadFireworkSettings(); appSky.bar?.skyChanged(true);
      showToast("Saved", 1200);
    } catch (err) { showError(esc(err.message), 3000); }
    renderSky(el);
  };
  el.querySelectorAll("[data-sky] button").forEach((b) => b.addEventListener("click", () => save({ [b.closest("[data-sky]").dataset.sky]: b.dataset.v })));
  el.querySelector("[data-sky-server]")?.addEventListener("change", (e) => save({ server: e.target.value }));
}

// ---------------------------------------------------------------- preview window
// Previews play in their own sky in front of everything. The background sky pauses and goes
// quiet meanwhile, so you see and hear only what you're trying out.
function openFwPreview({ title, sub = "", run, theme = null, again = true }) {
  closeFwPreview();
  const box = document.createElement("div");
  box.className = "pv"; box.setAttribute("role", "dialog"); box.setAttribute("aria-modal", "true"); box.setAttribute("aria-label", `Preview: ${title}`);
  box.innerHTML = `<div class="pv-box">
      <div class="pv-head"><div><h2>${esc(title)}</h2>${sub ? `<p class="muted small">${esc(sub)}</p>` : ""}</div>
        <button class="icon-btn pv-x" type="button" data-pv-close aria-label="Close preview">×</button></div>
      <div class="pv-stage"><canvas aria-label="Preview sky"></canvas><div class="pv-msg" hidden></div><div class="pv-count" hidden></div></div>
      <div class="pv-foot">${again ? `<button class="btn primary" type="button" data-pv-again>↻ Play again</button>` : ""}
        <button class="btn" type="button" data-pv-sound aria-pressed="${FWAudio.isOn("preview")}">${FWAudio.isOn("preview") ? "🔊 Sound on" : "🔇 Sound off"}</button>
        <span class="muted small">The fireworks behind are paused while you watch.</span>
        <button class="btn" type="button" data-pv-close>Close</button></div></div>`;
  document.body.append(box);
  const bg = appSky.scene, wasAuto = bg?.auto, wasSolo = FWAudio.solo, wasTheme = FW.theme;
  bg?.setAuto(false); bg?.clear();
  FWAudio.solo = true;
  if (theme) FW.theme = theme;
  const scene = startSkyScene(box.querySelector("canvas"), { fit: true, auto: false, sound: (t, i) => FWAudio.play(t, { ...i, solo: true, channel: "preview" }) });
  const timers = [];
  const ui = {
    later: (ms, fn) => timers.push(setTimeout(fn, ms)),
    message(text, ms = 4000) { const m = box.querySelector(".pv-msg"); m.textContent = text; m.hidden = !text; if (text) ui.later(ms, () => { m.hidden = true; }); },
    count(n) { const c = box.querySelector(".pv-count"); c.hidden = n == null; c.textContent = n ?? ""; },
  };
  const go = () => { timers.splice(0).forEach(clearTimeout); scene.clear(); ui.count(null); ui.message(""); run(scene, ui); };
  const close = () => {
    timers.forEach(clearTimeout); scene.stop(); box.remove();
    FWAudio.solo = wasSolo; FW.theme = wasTheme;
    if (bg && wasAuto) bg.setAuto(true);
    document.removeEventListener("keydown", onKey);
    fwPreviewClose = null;
  };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  box.addEventListener("click", (e) => {
    if (e.target === box || e.target.closest("[data-pv-close]")) close();
    else if (e.target.closest("[data-pv-again]")) go();
    else if (e.target.closest("[data-pv-sound]")) {
      const on = !FWAudio.isOn("preview");
      FWAudio.setChannel("preview", on);              // only previews; the 🔊 in the corner is separate
      const b = e.target.closest("[data-pv-sound]"); b.textContent = on ? "🔊 Sound on" : "🔇 Sound off"; b.setAttribute("aria-pressed", String(on));
    }
  });
  fwPreviewClose = close;
  box.querySelector("[data-pv-again], [data-pv-close]").focus();
  setTimeout(go, 250);                     // let the canvas size itself first
  return close;
}
let fwPreviewClose = null;
function closeFwPreview() { fwPreviewClose?.(); }
// What someone joining would launch, played in a preview sky.
function pvRunShow(scene, show, ui) {
  if (!show) { ui.message("Nothing: join fireworks are switched off"); return; }
  const n = Math.max(1, Math.min(5, show.count || 1));
  for (let i = 0; i < n; i++) ui.later(i * 450, () => {
    if (show.design) scene.launch(show.design);
    else if (show.kind === "showpiece") scene.showpiece();
    else if (show.kind === "random" || !show.kind) scene.launch();
    else scene.launch(show.kind);
  });
}
