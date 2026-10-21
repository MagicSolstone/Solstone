/* Solstone — Firework settings (admins): what the show launches, fireworks for things
   happening in the game, each player's join firework, the calendar of holidays and
   scheduled shows, and the music playlist. Loaded after app.js, control.js and editor.js. */
"use strict";

const FWS_TABS = [["show", "The show"], ["shows", "Shows"], ["events", "Game events"], ["join", "Join fireworks"], ["calendar", "Calendar"], ["music", "Music"]];
const FWS_EVENTS = [
  ["join", "Someone joins", "Their join firework if they have one (Join fireworks tab), otherwise what you pick."],
  ["advancement", "Advancement", "Any normal advancement."],
  ["goal", "Goal reached", "Goal advancements, like “Cover Me in Debris”."],
  ["challenge", "Challenge completed", "The purple challenge advancements. Goes big: three at once."],
  ["death", "Someone dies", "A sad little dud fizzles out."],
  ["level", "Level milestone", "When someone passes every so many levels."],
  ["night", "Night falls", "In the game, while someone's playing."],
  ["start", "Server starts", ""],
];
const FWS_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const FWS_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const fws = { tab: "show", data: null, designs: [], editing: null };

function fwsKindOptions(cur, extra = []) {
  const kinds = FW_LABELS.map(([k, l]) => [k, l]);
  const custom = fws.designs.map((d) => [`custom:${d.id}`, `🎨 ${d.name}`]);
  const opt = ([v, l]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`;
  const showOpts = (fws.data?.shows || []).map((x) => [`show:${x.id}`, `🎬 ${x.name}`]);
  return `${extra.map(opt).join("")}${showOpts.length && extra.length ? `<optgroup label="Shows">${showOpts.map(opt).join("")}</optgroup>` : ""}<optgroup label="Built-in">${kinds.map(opt).join("")}</optgroup>${custom.length ? `<optgroup label="Made in the editor">${custom.map(opt).join("")}</optgroup>` : ""}`;
}
function fwsDateText(e) {
  const d = e.date, ord = (n) => (n === -1 ? "last" : ["", "1st", "2nd", "3rd", "4th"][n]);
  const base = d.type === "fixed" ? `${FWS_MONTHS[d.month - 1]} ${d.day}` : d.type === "easter" ? "Easter Sunday"
    : d.type === "nth" ? `${ord(d.n)} ${FWS_WEEKDAYS[d.weekday]} of ${FWS_MONTHS[d.month - 1]}` : d.type === "weekly" ? `every ${FWS_WEEKDAYS[d.weekday]}` : d.iso;
  return `${base}${e.days > 1 ? ` (${e.days} days)` : ""}`;
}
const fwsTime = (t) => { const [h, m] = t.split(":").map(Number); return new Date(2000, 0, 1, h, m).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); };

async function viewFireworkSettings() {
  if (!isAdmin()) { location.replace("#/fireworks"); return; }
  curSid = null;
  document.title = "Firework settings · Solstone";
  $("#rail-servers").innerHTML = railHtml(null);
  const [data, fw, designs] = await Promise.all([api("/api/fireworks/show"), api("/api/public/fireworks"), api("/api/fireworks").catch(() => [])]);
  fws.data = data; fws.fw = fw; fws.designs = designs;
  setView(`<div class="fwe-head"><h1>Fireworks</h1>
      <nav class="tabs" aria-label="Fireworks"><a href="#/fireworks">Editor</a><a href="#/fireworks/settings" aria-current="page">Show settings</a></nav>
      <p class="muted" id="fws-today"></p></div>
    <nav class="fwe-tabs fws-tabs" role="tablist" aria-label="Show settings">${FWS_TABS.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${fws.tab === k}">${l}</button>`).join("")}</nav>
    <div id="fws-body"></div>`);
  $$(".fws-tabs [data-tab]").forEach((b) => b.addEventListener("click", () => {
    fws.tab = b.dataset.tab; $$(".fws-tabs [data-tab]").forEach((x) => x.setAttribute("aria-selected", String(x === b))); renderFws();
  }));
  renderToday();
  renderFws();
}
function renderToday() {
  const t = fws.data.today, bits = [];
  if (t.theme) bits.push(`Today: <b>${esc(t.theme.emoji)} ${esc(t.theme.name)}</b>`);
  const next = t.finales.find((f) => f.end * 1000 > Date.now());
  if (next) bits.push(`Next scheduled show: <b>${esc(next.emoji)} ${esc(next.name)}</b> at ${new Date(next.start * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}`);
  $("#fws-today").innerHTML = bits.join(" · ") || "No holiday today, and no scheduled show in the next day.";
}
async function fwsSave(body, msg = "Saved") {
  try {
    fws.data = await post("/api/fireworks/show", body, "PUT");
    fwLoaded = null; loadFireworkSettings();     // the sky on this page picks it up
    renderToday(); showToast(msg, 1800);
  } catch (err) { showToast(esc(err.message), 4000); }
}

function renderFws() {
  const el = $("#fws-body");
  if (fws.tab === "show") {
    el.innerHTML = `<section class="panel fws-sky" id="fws-sky"></section>
      <section class="panel fw-settings" id="fw-settings">${fireworksSettingsHtml(fws.fw)}</section>
      <section class="panel fws-community" id="fws-community"></section>`;
    renderSky($("#fws-sky"));
    wireFireworksSettings($("#fw-settings"), fws.fw);
    renderCommunity($("#fws-community"));
  } else if (fws.tab === "shows") renderShows(el);
  else if (fws.tab === "events") renderEvents(el);
  else if (fws.tab === "join") renderJoin(el);
  else if (fws.tab === "calendar") renderCalendar(el);
  else renderMusic(el);
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
    catch (err) { showToast(esc(err.message), 3000); }
    fws.data = await api("/api/fireworks/show"); renderCommunity(el);
  };
  el.querySelectorAll("[data-design-weight] button").forEach((b) => b.addEventListener("click", () => updateDesign(b.closest("[data-id]").dataset.id, { weight: +b.dataset.freq })));
  el.querySelectorAll("[data-inshow]").forEach((c) => c.addEventListener("change", () => updateDesign(c.closest("[data-id]").dataset.id, { in_show: c.checked })));
  el.querySelectorAll("[data-play]").forEach((b) => b.addEventListener("click", () => {
    const d = fws.designs.find((x) => x.id === b.closest("[data-id]").dataset.id);
    if (d) appSky.scene?.launch({ ...d });
  }));
}

// ---------------------------------------------------------------- game events
function renderEvents(el) {
  const ev = fws.data.events;
  const extras = { join: [["signature", "Their join firework"]], challenge: [["showpiece", "A show-piece (dragon, bow, tree)"]], death: [["dud", "A dud that fizzles"]], night: [["show", "A short show"]] };
  el.innerHTML = `<section class="panel fws-events">${FWS_EVENTS.map(([k, label, hint]) => {
    const e = ev[k];
    const choices = [...(extras[k] || []), ["random", "Something random"], ["showpiece", "A show-piece"], ["none", "Nothing"]]
      .filter((c, i, a) => a.findIndex((x) => x[0] === c[0]) === i);
    return `<div class="fws-event" data-ev="${k}">
      <label class="switch-row fws-ev-head"><span><b>${esc(label)}</b>${hint ? `<br><small class="muted">${esc(hint)}</small>` : ""}</span><input type="checkbox" role="switch" data-on ${e.on ? "checked" : ""}></label>
      <div class="fws-ev-opts"><label>Launch <select class="input sm" data-fw>${fwsKindOptions(e.firework, choices)}</select></label>
        ${k === "level" ? `<label>every <input class="input sm num-in" type="number" min="1" max="100" value="${e.every}" data-every> levels</label>` : ""}
        ${k === "night" ? `<label>for <input class="input sm num-in" type="number" min="1" max="30" value="${e.minutes}" data-minutes> minutes</label>` : ""}
        <button type="button" class="btn sm" data-test>Try it</button></div></div>`;
  }).join("")}
    <p class="muted small">These go off on every Solstone page that's open, including the status page and the sign-in page. Try it shows you here.</p></section>`;
  el.querySelectorAll("[data-ev]").forEach((row) => {
    const k = row.dataset.ev;
    const save = () => fwsSave({ events: { [k]: {
      on: row.querySelector("[data-on]").checked, firework: row.querySelector("[data-fw]").value,
      ...(row.querySelector("[data-every]") ? { every: +row.querySelector("[data-every]").value } : {}),
      ...(row.querySelector("[data-minutes]") ? { minutes: +row.querySelector("[data-minutes]").value } : {}),
    } } });
    row.querySelectorAll("input, select").forEach((i) => i.addEventListener("change", save));
    row.querySelector("[data-test]").addEventListener("click", async () => {
      const player = k === "join" ? fws.data.players[0] : null;
      try { await post("/api/fireworks/test-event", { event: k, player }); showToast("Watch the sky…", 1500); }
      catch (err) { showToast(esc(err.message), 3000); }
    });
  });
}

// ---------------------------------------------------------------- join fireworks
function renderJoin(el) {
  const sig = fws.data.signatures, players = fws.data.players;
  el.innerHTML = `<section class="panel"><p class="muted" style="margin-bottom:12px">Pick a firework for each player. It goes off whenever they join, so everyone knows who just arrived. Make one in the <a href="#/fireworks">editor</a> first.</p>
    ${players.length ? `<div class="fws-join">${players.map((n) => `<div class="fws-join-row">${faceHtml({ name: n }, 28)}<b>${esc(n)}</b>
      <select class="input sm" data-player="${esc(n)}"><option value="">Random firework</option>${fws.designs.map((d) => `<option value="${d.id}" ${sig[n.toLowerCase()] === d.id ? "selected" : ""}>🎨 ${esc(d.name)} · by ${esc(d.author)}</option>`).join("")}</select>
      <button type="button" class="icon-btn" data-try="${esc(n)}" title="Try it" aria-label="Try ${esc(n)}'s firework">▶</button></div>`).join("")}</div>`
    : `<p class="muted">Nobody has joined a server yet.</p>`}</section>`;
  el.querySelectorAll("[data-player]").forEach((s) => s.addEventListener("change", () => {
    const next = { ...fws.data.signatures };
    if (s.value) next[s.dataset.player.toLowerCase()] = s.value; else delete next[s.dataset.player.toLowerCase()];
    fwsSave({ signatures: next }, `Join firework set for ${s.dataset.player}`);
  }));
  el.querySelectorAll("[data-try]").forEach((b) => b.addEventListener("click", () => post("/api/fireworks/test-event", { event: "join", player: b.dataset.try }).catch(() => {})));
}

// ---------------------------------------------------------------- calendar
function renderCalendar(el) {
  const cal = fws.data.calendar;
  el.innerHTML = `<section class="panel"><p class="muted" style="margin-bottom:12px">On these days the fireworks take on the day's colours and favourite kinds, and a message shows on every page. A <b>scheduled show</b> fills the sky at a set time on every open page; the New Year one counts down from 10.</p>
    <div class="fws-cal">${cal.map((e, i) => fws.editing === i ? calEditHtml(e, i) : `<div class="fws-cal-row ${e.enabled ? "" : "off"}" data-i="${i}">
      <span class="fws-emoji">${esc(e.emoji)}</span>
      <div><b>${esc(e.name)}</b><div class="muted small">${esc(fwsDateText(e))}${e.finale.on ? ` · show at ${esc(fwsTime(e.finale.time))} for ${e.finale.minutes} min${e.finale.countdown ? " with a countdown" : ""}` : ""}</div>
        <div class="fwe-dots">${e.colors.map((c) => `<i style="background:${c}"></i>`).join("")}</div></div>
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
  $("#fws-add").addEventListener("click", async () => {
    const next = [...fweCopy(cal), { name: "Birthday", emoji: "🎂", date: { type: "fixed", month: new Date().getMonth() + 1, day: new Date().getDate() }, days: 1,
      colors: ["#ff8fc0", "#ffe45c", "#4fd7e6"], kinds: ["heart", "star", "crossette"], message: "Happy birthday!", enabled: true,
      finale: { on: true, day: 0, time: "19:00", minutes: 5, countdown: false } }];
    await fwsSave({ calendar: next }, "Added");
    fws.editing = fws.data.calendar.length - 1; renderCalendar(el);
  });
  $("#fws-reset").addEventListener("click", async () => {
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
  return `<form class="fws-cal-edit" data-i="${i}">
    <div class="fws-grid">
      <label>Name<input class="input" name="name" maxlength="40" value="${esc(e.name)}"></label>
      <label>Emoji<input class="input" name="emoji" maxlength="4" value="${esc(e.emoji)}" style="width:70px"></label>
      <label>When${sel("dtype", [["fixed", "Same date every year"], ["nth", "A weekday in a month"], ["easter", "Easter"], ["weekly", "Every week"], ["once", "Just once"]], d.type)}</label>
      <label class="fws-when">${d.type === "fixed" ? `${sel("month", FWS_MONTHS.map((m, k) => [k + 1, m]), d.month)} ${num("day", d.day, 1, 31)}`
        : d.type === "nth" ? `${sel("n", [[1, "1st"], [2, "2nd"], [3, "3rd"], [4, "4th"], [-1, "Last"]], d.n)} ${sel("weekday", FWS_WEEKDAYS.map((w, k) => [k, w]), d.weekday)} of ${sel("month", FWS_MONTHS.map((m, k) => [k + 1, m]), d.month)}`
        : d.type === "weekly" ? sel("weekday", FWS_WEEKDAYS.map((w, k) => [k, w]), d.weekday)
        : d.type === "once" ? `<input class="input sm" type="date" name="iso" value="${esc(d.iso || "")}">` : `<span class="muted small">Worked out each year</span>`}</label>
      <label class="inl">Lasts ${num("days", e.days, 1, 14)} day(s)</label>
      <label class="wide">Message<input class="input" name="message" maxlength="80" value="${esc(e.message)}" placeholder="Shown on every page that day"></label>
    </div>
    <div class="fws-sub">Colours <span class="muted small">(leave none for the usual colours)</span></div>
    <div class="fwe-colors" data-cal-colors>${e.colors.map((c, k) => `<span class="fwe-color"><input type="color" value="${c}" data-cc="${k}"><button type="button" class="chip-x" data-rmcc="${k}" aria-label="Remove">×</button></span>`).join("")}
      ${e.colors.length < 6 ? `<button type="button" class="btn sm" data-addcc>+ Colour</button>` : ""}</div>
    <div class="fws-sub">Favourite kinds <span class="muted small">(go off more often that day)</span></div>
    <div class="fws-kinds">${[...FW_LABELS.map(([k, l]) => [k, l]), ...fws.designs.map((x) => [`custom:${x.id}`, `🎨 ${x.name}`])].map(([k, l]) =>
      `<label class="chip ${kinds.has(k) ? "on" : ""}"><input type="checkbox" value="${esc(k)}" data-kind ${kinds.has(k) ? "checked" : ""}> ${esc(l)}</label>`).join("")}</div>
    <div class="fws-sub">Scheduled show</div>
    <div class="fws-grid">
      <label class="check"><input type="checkbox" name="fon" ${e.finale.on ? "checked" : ""}> Put on a show</label>
      ${e.days > 1 ? `<label class="inl">on day ${num("fday", e.finale.day + 1, 1, e.days)}</label>` : ""}
      <label class="inl">at <input class="input sm" type="time" name="ftime" value="${esc(e.finale.time)}"></label>
      <label class="inl">for ${num("fmin", e.finale.minutes, 1, 30)} minutes</label>
      <label class="check"><input type="checkbox" name="fcount" ${e.finale.countdown ? "checked" : ""}> Count down from 10</label>
      <label class="inl">playing <select class="input sm" name="fshow"><option value="">a lively random mix</option>${(fws.data.shows || []).map((x) => `<option value="${esc(x.id)}" ${e.finale.show === x.id ? "selected" : ""}>🎬 ${esc(x.name)}</option>`).join("")}</select></label>
    </div>
    <div class="btn-row"><button class="btn primary" type="submit">Save</button><button type="button" class="btn" data-cancel>Cancel</button>
      <button type="button" class="btn" data-preview>Preview</button><button type="button" class="btn danger" data-del>Delete</button></div>
  </form>`;
}
function wireCalEdit(el, i) {
  const form = el.querySelector(".fws-cal-edit");
  const draft = fweCopy(fws.data.calendar[i]);
  const read = () => {
    const f = new FormData(form), dtype = f.get("dtype");
    draft.name = f.get("name"); draft.emoji = f.get("emoji"); draft.message = f.get("message"); draft.days = +f.get("days") || 1;
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
    draft.finale = { on: !!f.get("fon"), day: Math.max(0, (+f.get("fday") || 1) - 1), time: f.get("ftime") || "20:00", minutes: +f.get("fmin") || 5, countdown: !!f.get("fcount"), show: f.get("fshow") || "" };
  };
  const redraw = () => { read(); fws.data.calendar[i] = draft; renderCalendar(el); };
  form.querySelector('[name="dtype"]').addEventListener("change", redraw);
  form.querySelector('[name="days"]').addEventListener("change", redraw);
  form.querySelectorAll("[data-kind]").forEach((c) => c.addEventListener("change", () => c.closest(".chip").classList.toggle("on", c.checked)));
  form.querySelectorAll("[data-cc]").forEach((c) => c.addEventListener("input", () => { draft.colors[+c.dataset.cc] = c.value; }));
  form.querySelectorAll("[data-rmcc]").forEach((b) => b.addEventListener("click", () => { draft.colors.splice(+b.dataset.rmcc, 1); redraw(); }));
  form.querySelector("[data-addcc]")?.addEventListener("click", () => { draft.colors.push(pick2(FW_COLORS)); redraw(); });
  form.querySelector("[data-cancel]").addEventListener("click", async () => { fws.editing = null; fws.data = await api("/api/fireworks/show"); renderCalendar(el); });
  form.querySelector("[data-del]").addEventListener("click", async () => {
    if (!(await confirmBox(`Delete ${draft.name}?`, "It won't change the fireworks on that day any more.", "Delete"))) return;
    const next = fweCopy(fws.data.calendar); next.splice(i, 1);
    fws.editing = null; await fwsSave({ calendar: next }, "Deleted"); renderCalendar(el);
  });
  form.querySelector("[data-preview]").addEventListener("click", () => {
    read();
    const scene = appSky.scene;
    if (!scene) return;
    const before = FW.theme;
    FW.theme = { colors: draft.colors, kinds: draft.kinds, name: draft.name, emoji: draft.emoji, message: draft.message };
    showToast(`${esc(draft.emoji)} ${esc(draft.message || draft.name)}`, 4000);
    scene.boost(15);
    setTimeout(() => { FW.theme = before; }, 16000);
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); read();
    const next = fweCopy(fws.data.calendar); next[i] = draft;
    fws.editing = null; await fwsSave({ calendar: next }); renderCalendar(el);
  });
}

// ---------------------------------------------------------------- music
function renderMusic(el) {
  const m = fws.data.music;
  const mb = (n) => `${(n / 1024 / 1024).toFixed(1)} MB`;
  el.innerHTML = `<section class="panel">
    <p class="muted" style="margin-bottom:12px">Background music for the fireworks. Anyone signed in can play it with 🎵 in the corner; it plays in order (or shuffled) and moves on by itself. MP3, OGG, M4A, WAV, FLAC or Opus, up to 60 MB each.</p>
    <label class="switch-row" style="max-width:640px"><span>Also play music on the public status page</span><input type="checkbox" role="switch" id="fws-music-public" ${m.public ? "checked" : ""}></label>
    <div class="fws-upload"><label class="btn primary">Add music…<input type="file" accept="audio/*" multiple hidden id="fws-file"></label><span class="muted small" id="fws-up"></span></div>
    ${m.tracks.length ? `<ol class="fws-tracks">${m.tracks.map((t, i) => `<li data-id="${t.id}"><span class="num muted">${i + 1}</span>
        <input class="input sm" value="${esc(t.title)}" data-title aria-label="Title"><span class="muted small">${t.ext.toUpperCase()} · ${mb(t.size)}</span>
        <span class="row-actions"><button type="button" class="icon-btn" data-play title="Play">▶</button><button type="button" class="icon-btn" data-up ${i === 0 ? "disabled" : ""} title="Move up">▲</button>
        <button type="button" class="icon-btn" data-down ${i === m.tracks.length - 1 ? "disabled" : ""} title="Move down">▼</button><button type="button" class="btn sm danger" data-del>Delete</button></span></li>`).join("")}</ol>`
      : `<p class="muted" style="margin-top:12px">No music yet.</p>`}</section>`;
  const reload = async () => { fws.data = await api("/api/fireworks/show"); FWMusic.loaded = false; await FWMusic.load(); $(".sky-music") && ($(".sky-music").hidden = false); renderMusic(el); };
  $("#fws-music-public").addEventListener("change", async (e) => { await post("/api/music", { public: e.target.checked }, "PUT").catch((err) => showToast(esc(err.message), 3000)); showToast("Saved", 1500); });
  $("#fws-file").addEventListener("change", async (e) => {
    const files = [...e.target.files];
    for (const [k, f] of files.entries()) {
      $("#fws-up").textContent = `Uploading ${k + 1} of ${files.length}: ${f.name}…`;
      try {
        const r = await fetch(`/api/music?filename=${encodeURIComponent(f.name)}`, { method: "POST", body: f, credentials: "same-origin",
          headers: { "X-Solstone": "1", "Content-Type": f.type || "application/octet-stream" } });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
      } catch (err) { showToast(`${esc(f.name)}: ${esc(err.message)}`, 5000); }
    }
    $("#fws-up").textContent = "";
    reload();
  });
  el.querySelectorAll(".fws-tracks li").forEach((li) => {
    const id = li.dataset.id, ids = m.tracks.map((t) => t.id), i = ids.indexOf(id);
    li.querySelector("[data-title]").addEventListener("change", (e) => post("/api/music", { titles: { [id]: e.target.value } }, "PUT").then(reload));
    li.querySelector("[data-play]").addEventListener("click", () => { if (!FWMusic.loaded) FWMusic.load().then(() => FWMusic.play(i)); else FWMusic.play(i); });
    const move = (to) => { const o = [...ids]; o.splice(i, 1); o.splice(to, 0, id); post("/api/music", { order: o }, "PUT").then(reload); };
    li.querySelector("[data-up]").addEventListener("click", () => move(i - 1));
    li.querySelector("[data-down]").addEventListener("click", () => move(i + 1));
    li.querySelector("[data-del]").addEventListener("click", async () => {
      if (!(await confirmBox("Delete this track?", esc(m.tracks[i].title), "Delete"))) return;
      await api(`/api/music/${id}`, { method: "DELETE" }).catch((err) => showToast(esc(err.message), 3000));
      reload();
    });
  });
}

// ---------------------------------------------------------------- the sky
function renderSky(el) {
  const sky = fws.fw.sky || { mode: "game", server: "auto", daytime: "smoke" };
  const seg = (name, opts, cur) => `<div class="seg" role="group" data-sky="${name}">${opts.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${v === cur}">${l}</button>`).join("")}</div>`;
  el.innerHTML = `<h3 class="fw-sub">The sky <span class="muted small">behind every page</span></h3>
    <div class="fw-row"><span>Sky</span>${seg("mode", [["game", "Follow the game"], ["night", "Always night"]], sky.mode)}</div>
    ${sky.mode === "game" ? `<div class="fw-row"><span>From</span><select class="input sm" data-sky-server><option value="auto">The server people are playing on</option>
        ${(fws.data.servers || []).map((x) => `<option value="${esc(x.id)}" ${sky.server === x.id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></div>
      <div class="fw-row"><span>In the daytime</span>${seg("daytime", [["smoke", "Coloured smoke"], ["normal", "Same as night"], ["pause", "Wait for night"]], sky.daytime)}</div>
      <p class="muted small">The sun, moon (with its phases), clouds, rain and thunder follow the game. On a server's page the sky shows that server. Daytime fireworks leave coloured smoke and go up less often, like real ones; game events and scheduled shows still go off either way.</p>` : ""}`;
  const save = async (patch) => {
    try {
      const cfg = await post("/api/settings/fireworks", { sky: patch }, "PUT");
      fws.fw = { ...fws.fw, ...cfg };
      fwLoaded = null; await loadFireworkSettings(); appSky.bar?.skyChanged(true);
      showToast("Saved", 1200);
    } catch (err) { showToast(esc(err.message), 3000); }
    renderSky(el);
  };
  el.querySelectorAll("[data-sky] button").forEach((b) => b.addEventListener("click", () => save({ [b.closest("[data-sky]").dataset.sky]: b.dataset.v })));
  el.querySelector("[data-sky-server]")?.addEventListener("change", (e) => save({ server: e.target.value }));
}

// ---------------------------------------------------------------- show builder
const SHOW_WHERE = [["random", "Anywhere"], ["left", "Left"], ["center", "Middle"], ["right", "Right"], ["spread", "Spread out"], ["sides", "Both sides"]];
function showLength(sh) { return sh.steps.length ? Math.max(...sh.steps.map((x) => x.at)) : 0; }
function renderShows(el) {
  const shows = fws.data.shows || [], base = fws.data.base_shows || { day: "", night: "" };
  const pickShow = (k) => `<select class="input sm" data-base="${k}"><option value="">The usual random mix</option>${shows.map((x) => `<option value="${esc(x.id)}" ${base[k] === x.id ? "selected" : ""}>🎬 ${esc(x.name)}</option>`).join("")}</select>`;
  el.innerHTML = `<section class="panel"><h3 class="fw-sub">Base shows <span class="muted small">what plays while the Show switch is on</span></h3>
      <div class="fw-row"><span>☀️ Daytime</span>${pickShow("day")}</div><div class="fw-row"><span>🌙 Night</span>${pickShow("night")}</div>
      <p class="muted small">Day and night follow the game when the sky does (otherwise 7 pm to 7 am). A base show loops; game events and holiday shows still play on top.</p></section>
    <section class="panel" style="margin-top:16px"><h3 class="fw-sub">Shows <span class="muted small">timed lists of fireworks, for base shows, the calendar and game events</span></h3>
      <div class="fws-shows">${shows.map((sh, i) => fws.editingShow === i ? showEditHtml(sh, i) : `<div class="fws-show-row" data-i="${i}">
        <b>🎬 ${esc(sh.name)}</b><span class="muted small">${sh.steps.length} steps · ${Math.round(showLength(sh))} s${base.day === sh.id ? " · daytime base" : ""}${base.night === sh.id ? " · night base" : ""}</span>
        <span class="row-actions"><button type="button" class="icon-btn" data-play title="Watch it" aria-label="Watch ${esc(sh.name)}">▶</button>
          <button type="button" class="btn sm" data-edit>Edit</button><button type="button" class="btn sm" data-copy>Copy</button></span>
        ${timelineHtml(sh)}</div>`).join("")}</div>
      <button type="button" class="btn" id="fws-newshow" style="margin-top:12px">+ New show</button></section>`;
  el.querySelectorAll("[data-base]").forEach((sel) => sel.addEventListener("change", async () => {
    await fwsSave({ base_shows: { [sel.dataset.base]: sel.value } }, "Base show set");
  }));
  el.querySelectorAll(".fws-show-row").forEach((row) => {
    const i = +row.dataset.i, sh = shows[i];
    row.querySelector("[data-play]").addEventListener("click", () => previewShow(sh));
    row.querySelector("[data-edit]").addEventListener("click", () => { fws.editingShow = i; renderShows(el); });
    row.querySelector("[data-copy]").addEventListener("click", async () => {
      await fwsSave({ shows: [...fweCopy(shows), { ...fweCopy(sh), id: "", name: `${sh.name} (copy)` }] }, "Copied"); renderShows(el);
    });
  });
  $("#fws-newshow").addEventListener("click", async () => {
    await fwsSave({ shows: [...fweCopy(shows), { name: "New show", loop_gap: 2, steps: [{ at: 0, what: "random", count: 1, where: "random" }, { at: 2, what: "random", count: 2, where: "spread" }] }] }, "Added");
    fws.editingShow = fws.data.shows.length - 1; renderShows(el);
  });
  if (fws.editingShow != null && shows[fws.editingShow]) wireShowEdit(el, fws.editingShow);
}
function stepLabel(what) {
  if (what === "random") return "🎲 Random";
  if (what === "showpiece") return "⭐ Show-piece";
  if (what.startsWith("custom:")) { const d = fws.designs.find((x) => `custom:${x.id}` === what); return d ? `🎨 ${d.name}` : "🎨 (deleted)"; }
  return (FW_LABELS.find(([k]) => k === what) || [what, what])[1];
}
function timelineHtml(sh) {
  const len = Math.max(1, showLength(sh));
  return `<div class="fws-timeline" aria-hidden="true">${sh.steps.map((x) => `<i style="left:${(x.at / len) * 100}%" title="${esc(`${x.at}s: ${stepLabel(x.what)} ×${x.count}`)}" class="${x.what === "showpiece" ? "big" : x.what.startsWith("custom:") ? "mine" : ""}"></i>`).join("")}</div>`;
}
function previewShow(sh) {
  const scene = appSky.scene;
  if (!scene) return;
  scene.clear();
  const steps = sh.steps.map((x) => (x.what.startsWith("custom:") ? { ...x, design: fws.designs.find((d) => `custom:${d.id}` === x.what) } : x));
  scene.playShow({ ...sh, steps });
  showToast(`🎬 ${esc(sh.name)}`, 2000);
}
function showEditHtml(sh, i) {
  const opts = (cur) => `<option value="random" ${cur === "random" ? "selected" : ""}>🎲 Random</option><option value="showpiece" ${cur === "showpiece" ? "selected" : ""}>⭐ Show-piece</option>
    <optgroup label="Built-in">${FW_LABELS.map(([k, l]) => `<option value="${k}" ${cur === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</optgroup>
    ${fws.designs.length ? `<optgroup label="Made in the editor">${fws.designs.map((d) => `<option value="custom:${d.id}" ${cur === `custom:${d.id}` ? "selected" : ""}>🎨 ${esc(d.name)}</option>`).join("")}</optgroup>` : ""}`;
  return `<form class="fws-show-edit" data-i="${i}">
    <div class="fws-grid"><label>Name<input class="input" name="name" maxlength="40" value="${esc(sh.name)}"></label>
      <label class="inl">Pause before it repeats <input class="input sm num-in" type="number" name="gap" min="0" max="30" step="0.5" value="${sh.loop_gap ?? 2}"> s</label></div>
    ${timelineHtml(sh)}
    <div class="fws-steps"><div class="fws-step fws-head muted small"><span>At (s)</span><span>Launch</span><span>How many</span><span>Where</span><span></span></div>
      ${sh.steps.map((x, k) => `<div class="fws-step" data-k="${k}">
        <input class="input sm" type="number" min="0" max="600" step="0.25" value="${x.at}" data-f="at" aria-label="Seconds">
        <select class="input sm" data-f="what">${opts(x.what)}</select>
        <input class="input sm" type="number" min="1" max="12" value="${x.count}" data-f="count" aria-label="How many">
        <select class="input sm" data-f="where">${SHOW_WHERE.map(([v, l]) => `<option value="${v}" ${x.where === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        <button type="button" class="chip-x" data-rm aria-label="Remove step">×</button></div>`).join("")}</div>
    <div class="btn-row"><button type="button" class="btn sm" data-add>+ Add a step</button><button type="button" class="btn sm" data-add-pause>+ Step after a 3 s pause</button></div>
    <div class="btn-row"><button class="btn primary" type="submit">Save</button><button type="button" class="btn" data-cancel>Cancel</button>
      <button type="button" class="btn" data-preview>▶ Watch it</button><button type="button" class="btn danger" data-del>Delete</button></div>
  </form>`;
}
function wireShowEdit(el, i) {
  const form = el.querySelector(".fws-show-edit");
  const draft = fweCopy(fws.data.shows[i]);
  const read = () => {
    draft.name = form.querySelector('[name="name"]').value; draft.loop_gap = +form.querySelector('[name="gap"]').value || 0;
    draft.steps = [...form.querySelectorAll(".fws-step[data-k]")].map((row) => ({
      at: +row.querySelector('[data-f="at"]').value || 0, what: row.querySelector('[data-f="what"]').value,
      count: Math.max(1, Math.min(12, +row.querySelector('[data-f="count"]').value || 1)), where: row.querySelector('[data-f="where"]').value }));
  };
  const redraw = () => { read(); draft.steps.sort((a, b) => a.at - b.at); fws.data.shows[i] = draft; renderShows(el); };
  form.querySelectorAll('[data-f="at"]').forEach((inp) => inp.addEventListener("change", redraw));
  form.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => { read(); draft.steps.splice(+b.closest("[data-k]").dataset.k, 1); fws.data.shows[i] = draft; renderShows(el); }));
  const add = (gap) => { read(); const last = draft.steps.length ? Math.max(...draft.steps.map((x) => x.at)) : 0; draft.steps.push({ at: draft.steps.length ? last + gap : 0, what: "random", count: 1, where: "random" }); fws.data.shows[i] = draft; renderShows(el); };
  form.querySelector("[data-add]").addEventListener("click", () => add(1));
  form.querySelector("[data-add-pause]").addEventListener("click", () => add(3));
  form.querySelector("[data-preview]").addEventListener("click", () => { read(); previewShow(draft); });
  form.querySelector("[data-cancel]").addEventListener("click", async () => { fws.editingShow = null; fws.data = await api("/api/fireworks/show"); renderShows(el); });
  form.querySelector("[data-del]").addEventListener("click", async () => {
    if (!(await confirmBox(`Delete ${draft.name}?`, "Base shows, calendar dates and events using it go back to random fireworks.", "Delete"))) return;
    const next = fweCopy(fws.data.shows); next.splice(i, 1);
    fws.editingShow = null; await fwsSave({ shows: next }, "Deleted"); renderShows(el);
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); read();
    const next = fweCopy(fws.data.shows); next[i] = draft;
    fws.editingShow = null; await fwsSave({ shows: next }); renderShows(el);
  });
}
