/* Solstone — Firework editor: design your own fireworks with sliders and a pixel painter,
   watch them in a live preview sky, and save them into the show. Anyone signed in can make
   fireworks; people can change their own, and admins can change anyone's.
   Loaded after app.js and sky.js. */
"use strict";

const FWE_GRID = 25;
const FWE_DEFAULT = {
  name: "", launch: "rocket", pattern: "ball", color_mode: "mix", colors: ["#ffe45c", "#ff5a4f"], picture: [], picture2: [], stages: [],
  sparks: 48, size: 1.2, spread: 0.15, squash: 1, tilt: 0.3, points: 5, arms: 3, spin: 0.5,
  gravity: 1, drag: 0.4, life: 1.4, wind: 0, height: 0.6, rockets: 1, interval: 0.25, fan: 0, spot: 0.3, lean: 0, hang: 0,
  rocket_style: "normal", mirror: false, hold: 0.8, move_x: 0, move_y: 0, turn: 0, swap: 0.4,
  duration: 4, rate: 0.5, power: 0.8, angle: 0.3, wheel_spin: 0.6,
  sparkle: 0, trail: 0, glitter: 0, flash: 0.4, blink: 0, strobe: 0, breathe: 0, piece: 1, grow: 0, wobble: 0, fizzle: 0,
  second: 0, second_delay: 0.5, second_size: 0.6, in_show: true,
  sound_launch: "whoosh", sound_burst: "boom", sound_ground: "hiss", sound_crackle: true, sound_fizzle: false,
};
const FWE_TABS = [["launch", "Launch"], ["shape", "Shape"], ["colours", "Colours"], ["then", "Then…"], ["motion", "Motion"], ["effects", "Effects"], ["sound", "Sound"]];
const FWE_LAUNCHES = [["rocket", "Sky rocket", "🚀"], ["fountain", "Fountain", "⛲"], ["wheel", "Spinning wheel", "🎡"]];
const FWE_STYLES = [["normal", "Normal"], ["sparkly", "Sparkly"], ["corkscrew", "Corkscrew"], ["colored", "Coloured"], ["invisible", "Invisible"]];
const FWE_PATTERNS = [
  ["ball", "Ball", "●"], ["ring", "Ring", "◯"], ["star", "Star", "★"], ["burst", "Burst", "✳"], ["spiral", "Spiral", "🌀"],
  ["palm", "Palm", "🌴"], ["saturn", "Saturn", "🪐"], ["pop", "Pop", "💥"], ["picture", "Picture", "🎨"],
];
const FWE_ACTIONS = [["burst", "Burst again", "a new burst from the middle"], ["pieces", "Every piece bursts", "lots of little bursts"],
  ["shatter", "Shatter", "everything flies outward"], ["implode", "Implode", "pulls back in, then pops"]];
const STAGE_SOUNDS = [["auto", "Auto"], ["boom", "Boom"], ["pop", "Pop"], ["thud", "Thud"], ["crack", "Crack"], ["custom", "🎛 Make your own"], ["none", "Silent"]];
const pct = (v) => `${Math.round(v * 100)}%`;
const off0 = (v) => (v === 0 ? "Off" : pct(v));
const secs = (v) => `${(+v).toFixed(v < 1 ? 2 : 1)} s`;
const side = (v, l, r) => (v === 0 ? "none" : `${v < 0 ? l : r} ${pct(Math.abs(v))}`);
const isRocket = (d) => (d.launch || "rocket") === "rocket";
const onlyPattern = (...p) => (d) => isRocket(d) && p.includes(d.pattern);
// [key, label, min, max, step, format, when]
const FWE_SLIDERS = {
  Launch: [
    ["height", "Rocket height", 0.1, 1, 0.05, pct, isRocket],
    ["rockets", "How many rockets", 1, 12, 1, (v) => (v === 1 ? "1" : `${v} (a volley)`), isRocket],
    ["interval", "Time between rockets", 0.05, 2, 0.05, secs, (d) => isRocket(d) && d.rockets > 1],
    ["spot", "Launch spread", 0, 1, 0.05, (v) => (v === 0 ? "all from one spot" : pct(v)), (d) => isRocket(d) && d.rockets > 1],
    ["fan", "Fan out", 0, 1, 0.05, off0, (d) => isRocket(d) && d.rockets > 1],
    ["lean", "Lean", -1, 1, 0.05, (v) => side(v, "left", "right")],
    ["hang", "Hang time at the top", 0, 3, 0.1, (v) => (v === 0 ? "Off" : secs(v)), isRocket],
    ["duration", "Burn time", 1, 10, 0.5, secs, (d) => !isRocket(d)],
    ["rate", "Sparks", 0.1, 1, 0.05, pct, (d) => !isRocket(d)],
    ["power", "Power", 0.2, 1.5, 0.05, (v) => `×${v.toFixed(2)}`, (d) => !isRocket(d)],
    ["angle", "Spray width", 0, 1, 0.05, pct, (d) => d.launch === "fountain"],
    ["wheel_spin", "Wheel spin", -1, 1, 0.05, (v) => side(v, "left", "right"), (d) => d.launch === "wheel"],
  ],
  Shape: [
    ["sparks", "Pieces", 8, 160, 1, (v) => v, onlyPattern("ball", "ring", "star", "burst", "spiral", "palm", "saturn", "pop")],
    ["size", "Size", 0.3, 3, 0.05, (v) => `×${v.toFixed(2)}`, isRocket],
    ["spread", "Messiness", 0, 1, 0.05, pct, onlyPattern("ball", "ring", "star", "palm", "saturn")],
    ["squash", "Squash and stretch", 0.3, 1.5, 0.05, (v) => (v < 1 ? `flatter ${pct(1 - v)}` : v > 1 ? `taller ${pct(v - 1)}` : "round"), onlyPattern("ball", "ring", "star", "burst", "palm", "pop")],
    ["tilt", "Random tilt", 0, 1, 0.05, pct, onlyPattern("ring", "star", "picture")],
    ["points", "Star points", 3, 10, 1, (v) => v, onlyPattern("star")],
    ["arms", "Spiral arms", 2, 6, 1, (v) => v, onlyPattern("spiral")],
    ["spin", "Spiral spin", -1, 1, 0.05, (v) => side(v, "left", "right"), onlyPattern("spiral")],
  ],
  Picture: [
    ["hold", "Hold the picture", 0, 3, 0.1, secs, onlyPattern("picture")],
    ["move_x", "Fly sideways", -1, 1, 0.05, (v) => side(v, "left", "right"), onlyPattern("picture")],
    ["move_y", "Fly up or down", -1, 1, 0.05, (v) => side(v, "down", "up"), onlyPattern("picture")],
    ["turn", "Spin while holding", -1, 1, 0.05, (v) => side(v, "left", "right"), onlyPattern("picture")],
    ["swap", "Swap frames every", 0.1, 2, 0.05, secs, (d) => onlyPattern("picture")(d) && d.picture2?.length],
  ],
  Motion: [
    ["gravity", "Gravity", 0, 2, 0.05, (v) => (v === 0 ? "floating" : `×${v.toFixed(2)}`)],
    ["drag", "Air resistance", 0, 1, 0.05, pct],
    ["wind", "Wind", -1, 1, 0.05, (v) => side(v, "left", "right")],
    ["life", "Fade time", 0.4, 6, 0.1, secs],
  ],
  Effects: [
    ["piece", "Piece size", 1, 3, 1, (v) => ["", "small", "medium", "big"][v]],
    ["grow", "Grow as they fade", 0, 1, 0.05, off0],
    ["flash", "Flash", 0, 1, 0.05, off0],
    ["sparkle", "Crackle", 0, 1, 0.05, off0],
    ["trail", "Trails", 0, 1, 0.05, off0],
    ["glitter", "Falling glitter", 0, 1, 0.05, off0],
    ["wobble", "Wobble", 0, 1, 0.05, off0],
    ["blink", "Blink", 0, 1, 0.05, (v) => (v === 0 ? "Off" : v < 0.4 ? "slow" : v < 0.75 ? "medium" : "fast")],
    ["strobe", "Strobe", 0, 1, 0.05, off0],
    ["breathe", "Breathe", 0, 1, 0.05, off0],
    ["fizzle", "Fizzle out", 0, 1, 0.05, off0],
    ["second", "Some pieces burst again", 0, 1, 0.05, (v) => (v === 0 ? "Off" : `${pct(v)} of pieces`), isRocket],
    ["second_delay", "…after", 0.2, 1.5, 0.05, secs, (d) => isRocket(d) && d.second > 0],
    ["second_size", "…size", 0.2, 1.5, 0.05, (v) => `×${v.toFixed(2)}`, (d) => isRocket(d) && d.second > 0],
  ],
};
const FWE_STAGE_SLIDERS = [
  ["delay", "After", 0.1, 4, 0.05, secs],
  ["size", "Size", 0.2, 3, 0.05, (v) => `×${v.toFixed(2)}`],
  ["sparks", "Pieces", 8, 120, 1, (v) => v],
];
const FWE_MODES = [["mix", "Mixed"], ["alternate", "Taking turns"], ["change", "Changing"], ["rainbow", "Rainbow"]];

// Stamps for the painter: digits pick colour 1–4, "." is empty.
const dbl = (rows) => rows.flatMap((r) => { const w = [...r].map((c) => c + c).join(""); return [w, w]; });
const tpl = (name, ch = "0") => (FW_TEMPLATES[name] || []).map((r) => r.replace(/#/g, ch));
const FWE_STAMPS = {
  Heart: dbl(tpl("heart")),
  Creeper: dbl(tpl("creeper")),
  Smiley: ["....00000....", "..000000000..", ".00000000000.", ".000.000.000.", "0000.000.0000", "0000000000000",
    "0000000000000", "00.0000000.00", ".00.00000.00.", ".000.....000.", "..000000000..", "....00000...."],
  Star: [".......0.......", "......000......", "......000......", ".....00000.....", "000000000000000", ".0000000000000.",
    "..00000000000..", "...000000000...", "...000000000...", "..00000.00000..", "..0000...0000..", ".0000.....0000.", ".00.........00."],
  Sword: ["...........000", "..........0000", ".........0000.", "........0000..", ".......0000...", "......0000....",
    ".11..0000.....", ".111000.......", "..1100........", "..2111........", ".22..11.......", "22............", "2............."],
  Diamond: ["..111111111..", ".10000000001.", "1000000000001", ".00000000000.", "..000000000..", "...0000000...",
    "....00000....", ".....000.....", "......0......"],
  Block: tpl("cube"),
  Pickaxe: tpl("pickaxe"),
};

const ed = { d: null, id: null, list: [], scene: null, loop: true, debounce: 0, brush: "0", mirror: true, painting: false, frame: 1, grids: {}, tab: "launch", show: "mine", q: "", open: {}, limit: null };

function fweCopy(d) { return JSON.parse(JSON.stringify(d)); }
// The painter works on a full 25×25 grid per frame; the saved picture is trimmed to what's painted.
const picKey = (f) => (f === 2 ? "picture2" : "picture");
function fwePicture(f = ed.frame) {
  const rows = ed.d[picKey(f)]?.length ? ed.d[picKey(f)] : [];
  const grid = Array.from({ length: FWE_GRID }, () => new Array(FWE_GRID).fill("."));
  const h = rows.length, w = Math.max(0, ...rows.map((r) => r.length));
  const oy = Math.floor((FWE_GRID - h) / 2), ox = Math.floor((FWE_GRID - w) / 2);
  rows.forEach((r, y) => [...r].forEach((c, x) => { if (grid[oy + y]?.[ox + x] !== undefined) grid[oy + y][ox + x] = c; }));
  return grid;
}
function fweSetPicture(grid, f = ed.frame) {
  let rows = grid.map((r) => r.join(""));
  const used = (r) => /[0-3]/.test(r);
  while (rows.length && !used(rows[0])) rows.shift();
  while (rows.length && !used(rows[rows.length - 1])) rows.pop();
  const filled = rows.filter(used);
  if (filled.length) {
    const left = Math.min(...filled.map((r) => r.search(/[0-3]/)));
    const right = Math.max(...filled.map((r) => r.length - 1 - [...r].reverse().join("").search(/[0-3]/)));
    rows = rows.map((r) => r.slice(left, right + 1));
  }
  ed.d[picKey(f)] = rows;
  ed.grids[f] = grid;
}

async function viewFireworkEditor(editId) {
  curSid = null;
  document.title = `Firework editor · ${SITE_NAME}`;
  $("#rail-servers").innerHTML = railHtml(null);
  [ed.list, ed.sounds, ed.limit] = await Promise.all([api("/api/fireworks").catch(() => []), api("/api/sounds").catch(() => []), api("/api/fireworks/limit").catch(() => null)]);
  // After a reload (nothing in memory yet), bring back the firework that was being worked on.
  const draft = !ed.d ? fweReadDraft() : null;
  const resume = draft && (!editId || draft.id === editId) ? draft : null;
  const found = editId && ed.list.find((x) => x.id === editId && x.can_edit);
  if (resume) {
    ed.d = { ...fweCopy(FWE_DEFAULT), ...resume.d };
    ed.id = resume.id && ed.list.some((x) => x.id === resume.id && x.can_edit) ? resume.id : null;
    ed.base = resume.id && !ed.id ? fweSnap(fweCopy(FWE_DEFAULT)) : resume.base;
    setTimeout(() => showToast(`Brought back ${ed.id ? "your unsaved changes to" : "the firework you were making,"} “${esc((ed.d.name || "").trim() || "My firework")}”`, 4000), 300);
  } else {
    ed.d = found ? { ...fweCopy(FWE_DEFAULT), ...fweCopy(found) } : ed.d && !editId ? ed.d : fweCopy(FWE_DEFAULT);
    ed.id = found ? found.id : editId ? null : ed.id;
  }
  ed.grids = {}; ed.frame = 1;
  if (!resume && (found || ed.base == null)) fweMarkSaved();
  setView(`<div class="fwe-head"><h1>Fireworks</h1>
      <nav class="tabs" aria-label="Fireworks"><a href="#/fireworks" aria-current="page">Editor</a>${isAdmin() ? '<a href="#/fireworks/settings">Show settings</a>' : ""}</nav>
      <p class="muted">Design a firework, watch it go off, and save it. Fireworks marked <b>In the show</b> join the sky on every page of the site, including the home, sign-in and status pages.</p></div>
    <div class="fwe-mode" id="fwe-mode" aria-live="polite"></div>
    <div class="fwe">
      <div class="fwe-left">
        <div class="fwe-preview glass"><canvas id="fwe-sky" aria-label="Preview sky"></canvas>
          <div class="fwe-bar"><button class="btn primary" id="fwe-launch" type="button">🎆 Launch</button>
            <label class="check fwe-loopck"><input type="checkbox" id="fwe-loop" ${ed.loop ? "checked" : ""}> Keep launching</label>
            <button class="btn" id="fwe-surprise" type="button">🎲 Surprise me</button>
            <button class="btn" id="fwe-sound" type="button" aria-pressed="${FWAudio.isOn("editor")}" title="Sound for this preview only">${FWAudio.isOn("editor") ? "🔊" : "🔇"}</button></div></div>
        <form class="panel fwe-save" id="fwe-save" autocomplete="off">
          <label>Name<input class="input" name="name" maxlength="40" placeholder="My firework" value="${esc(ed.d.name || "")}"></label>
          <label class="check"><input type="checkbox" name="in_show" ${ed.d.in_show !== false ? "checked" : ""}> In the show</label>
          <p class="muted small">Save, save as new or leave from the bar at the top.</p>
        </form>
        <section class="fwe-gallery"><div class="section-head"><h2>Saved fireworks</h2><span class="muted" id="fwe-count"></span></div>
          <div class="fwe-filter" id="fwe-filter"></div><div id="fwe-list"></div></section>
      </div>
      <div class="fwe-controls" id="fwe-controls"></div>
    </div>`);
  ed.scene?.stop();
  // Only the preview makes sound here, so you hear just the firework you're making.
  ed.scene = startSkyScene($("#fwe-sky"), { fit: true, auto: false, sound: (t, i) => FWAudio.play(t, { ...i, solo: true, channel: "editor" }) });
  FWAudio.solo = true;
  document.body.classList.add("on-editor");
  state.cleanups.push(() => { ed.scene?.stop(); ed.scene = null; FWAudio.solo = false; document.body.classList.remove("on-editor"); });
  renderControls();
  renderGallery();
  $("#fwe-launch").addEventListener("click", () => fweLaunch());
  $("#fwe-loop").addEventListener("change", (e) => { ed.loop = e.target.checked; });
  $("#fwe-sound").addEventListener("click", (e) => {
    const on = !FWAudio.isOn("editor");
    FWAudio.setChannel("editor", on); e.currentTarget.textContent = on ? "🔊" : "🔇"; e.currentTarget.setAttribute("aria-pressed", String(on));
    fweLaunch();
  });
  $("#fwe-surprise").addEventListener("click", () => { ed.d = { ...fweSurprise(), name: ed.d.name, in_show: ed.d.in_show }; ed.grids = {}; ed.frame = 1; renderControls(); fweLaunch(); });
  $("#fwe-mode").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-m]");
    if (!b) return;
    const m = b.dataset.m;
    if (m === "save") fweSave(false);
    else if (m === "saveas") fweSave(true);
    else if (m === "exit" || m === "reset") {
      if (fweDirty() && !(await confirmBox(m === "exit" ? "Leave without saving?" : "Start a new firework?", m === "exit" ? "Your changes to this firework will be thrown away, including the copy kept in case of a reload." : "The one you're making hasn't been saved. It will be cleared, including the copy kept in case of a reload. Save it first if you want to keep it.", m === "exit" ? "Leave without saving" : "Clear it and start new"))) return;
      fweNew();
    }
  });
  renderMode();
  every(700, renderMode);
  $("#fwe-save").addEventListener("submit", (e) => { e.preventDefault(); fweSave(false); });
  $("#fwe-save").addEventListener("input", (e) => {
    if (e.target.name === "name") ed.d.name = e.target.value;
    if (e.target.name === "group") ed.d.group = e.target.value;
    if (e.target.name === "in_show") ed.d.in_show = e.target.checked;
  });
  // Keep launching: the next one goes up only once the last has completely finished
  // (stages, fades and all), plus a short pause.
  let idleSince = 0;
  every(250, () => {
    if (!ed.loop || document.hidden || !ed.scene) return;
    if (ed.scene.busy) { idleSince = 0; return; }
    idleSince ||= performance.now();
    if (performance.now() - idleSince > 700) { idleSince = 0; fweLaunch(); }
  });
  setTimeout(() => fweLaunch(), 400);
}

// What's being edited: a new firework, or a saved one (with or without unsaved changes).
const fweSnap = (d) => JSON.stringify(d);
// Unsaved work is kept in this browser as it changes, so a reload or a closed tab doesn't lose it.
const FWE_DRAFT = "solstone-firework-draft";
function fweReadDraft() { try { const x = JSON.parse(localStorage.getItem(FWE_DRAFT) || "null"); return x?.d ? x : null; } catch { return null; } }
function fweClearDraft() { try { localStorage.removeItem(FWE_DRAFT); } catch { /* optional */ } }
function fweKeepDraft() {
  if (!ed.d) return;
  try {
    if (fweDirty()) localStorage.setItem(FWE_DRAFT, JSON.stringify({ d: ed.d, id: ed.id, base: ed.base, at: Date.now() }));
    else fweClearDraft();
  } catch { /* storage full or blocked: nothing kept, nothing lost */ }
}
addEventListener("pagehide", fweKeepDraft);
function fweMarkSaved() { ed.base = fweSnap(ed.d); }
function fweDirty() { return ed.base != null && fweSnap(ed.d) !== ed.base; }
function fweNew() {
  fweClearDraft();
  ed.d = fweCopy(FWE_DEFAULT); ed.id = null; ed.grids = {}; ed.frame = 1; ed.base = null;
  if (location.hash !== "#/fireworks") location.hash = "#/fireworks"; else viewFireworkEditor();
}
function renderMode() {
  const el = $("#fwe-mode");
  if (!el) return;
  fweKeepDraft();
  const dirty = fweDirty(), name = (ed.d.name || "").trim() || "My firework";
  document.querySelector(".fwe")?.classList.toggle("editing", !!ed.id);
  const html = ed.id
    ? `<div class="fwe-mode-bar editing"><span class="fwe-mode-what">✏️ Editing <b>“${esc(name)}”</b>${dirty ? ' <span class="fwe-dirty">● unsaved changes</span> <span class="muted small" title="Kept in this browser until you save or leave without saving">· kept if you reload</span>' : ' <span class="muted">· no changes yet</span>'}</span>
        <span class="fwe-mode-btns"><button class="btn primary" type="button" data-m="save" ${dirty ? "" : "disabled"}>Save changes</button>
        <button class="btn" type="button" data-m="saveas">Save as new</button><button class="btn" type="button" data-m="exit">${dirty ? "Exit without saving" : "Done, make a new one"}</button></span></div>`
    : `<div class="fwe-mode-bar"><span class="fwe-mode-what">✨ <b>New firework</b>${dirty ? ' <span class="fwe-dirty">● not saved yet</span> <span class="muted small" title="Kept in this browser until you save it or start a new one">· kept if you reload</span>' : ""}</span>
        <span class="fwe-mode-btns"><button class="btn primary" type="button" data-m="save">Save</button>${dirty ? `<button class="btn" type="button" data-m="reset">✨ New firework</button>` : ""}</span></div>`;
  if (el._html !== html) { el._html = html; el.innerHTML = html; }
}
// Every preview starts on a clear sky, so previews never pile up and slow things down,
// and only the newest one makes sound.
function fweLaunch(d = ed.d) {
  if (!ed.scene) return;
  FWAudio.silence("sfx-preview");
  ed.scene.clear();
  ed.scene.launchDesign(fweCopy(d));
}
function fweChanged() {
  clearTimeout(ed.debounce);
  ed.debounce = setTimeout(() => fweLaunch(), 450);
}

// ---------------------------------------------------------------- controls
function sliderHtml([k, label, min, max, step, fmt, when], obj, prefix = "") {
  if (when && !when(ed.d)) return "";
  return `<label class="fwe-slider"><span>${esc(label)}</span><b data-out="${prefix}${k}">${esc(String(fmt(+obj[k])))}</b>
    <input type="range" min="${min}" max="${max}" step="${step}" value="${obj[k]}" data-k="${k}" ${prefix ? `data-stage="${prefix.slice(1, -1)}"` : ""}></label>`;
}
function colorsHtml(cols, attr) {
  return `<div class="fwe-colors">${cols.map((c, i) => `<span class="fwe-color"><input type="color" value="${c}" data-${attr}="${i}" aria-label="Colour ${i + 1}">
    ${cols.length > 1 ? `<button type="button" class="chip-x" data-rm-${attr}="${i}" aria-label="Remove colour ${i + 1}">×</button>` : ""}</span>`).join("")}
    ${cols.length < 4 ? `<button type="button" class="btn sm" data-add-${attr}>+ Colour</button>` : ""}</div>`;
}
function stagesHtml(d) {
  const label = Object.fromEntries(FWE_PATTERNS.map(([k, l, ic]) => [k, `${ic} ${l}`]));
  return `${(d.stages || []).map((st, i) => `<div class="fwe-stage" data-si="${i}">
      <div class="fwe-stage-head"><b>Then… (${i + 1})</b><button type="button" class="chip-x" data-rm-stage="${i}" aria-label="Remove stage ${i + 1}">×</button></div>
      <div class="fwe-actions">${FWE_ACTIONS.map(([k, l, hint]) => `<button type="button" data-action="${k}" aria-pressed="${st.action === k}" title="${esc(hint)}">${l}</button>`).join("")}</div>
      ${st.action !== "shatter" ? `<label class="fwe-select">Pattern <select class="input sm" data-stage-pattern>${FWE_PATTERNS.filter(([k]) => k !== "picture").map(([k]) => `<option value="${k}" ${st.pattern === k ? "selected" : ""}>${label[k]}</option>`).join("")}</select></label>` : ""}
      <div class="fwe-sliders">${FWE_STAGE_SLIDERS.filter(([k]) => st.action !== "shatter" || k !== "sparks").map((sl) => sliderHtml(sl, st, `s${i}:`)).join("")}</div>
      <div class="fwe-row fwe-stage-snd"><span>Sound</span><div class="seg" role="group">${STAGE_SOUNDS.map(([k, l]) => `<button type="button" data-stage-snd="${k}" aria-pressed="${(st.sound || "auto") === k}" ${k === "auto" ? 'title="Whatever suits the step"' : ""}>${l}</button>`).join("")}</div></div>
      ${st.sound === "custom" ? sfxPanelHtml(`stage${i}`) : ""}
      <label class="check small"><input type="checkbox" data-stage-owncolors ${st.colors?.length ? "checked" : ""}> Its own colours</label>
      ${st.colors?.length ? colorsHtml(st.colors, `sc${i}`) : ""}
    </div>`).join("")}
    ${(d.stages || []).length < 3 ? `<button type="button" class="btn" id="fwe-addstage">+ Add a “then…” step</button>` : ""}
    <p class="muted small">Steps happen one after another, each after its own delay. They work on everything the firework has made so far.</p>`;
}
function renderControls() {
  const d = ed.d, el = $("#fwe-controls");
  const sec = (title, inner, cls = "") => inner.trim() ? `<section class="panel fwe-sec ${cls}"><h3>${title}</h3>${inner}</section>` : "";
  const sliders = (name) => { const html = FWE_SLIDERS[name].map((sl) => sliderHtml(sl, d)).join(""); return html ? `<div class="fwe-sliders">${html}</div>` : ""; };
  if (!isRocket(d) && (ed.tab === "shape" || ed.tab === "then")) ed.tab = "launch";
  const panels = {
    launch: sec("Launch", `<div class="fwe-patterns fwe-launches">${FWE_LAUNCHES.map(([k, l, ic]) => `<button type="button" data-launch="${k}" aria-pressed="${(d.launch || "rocket") === k}"><span>${ic}</span>${l}</button>`).join("")}</div>
      ${isRocket(d) ? `<div class="seg fwe-styles" role="group" aria-label="Rocket style">${FWE_STYLES.map(([k, l]) => `<button type="button" data-style="${k}" aria-pressed="${(d.rocket_style || "normal") === k}">${l}</button>`).join("")}</div>` : ""}
      <label class="check"><input type="checkbox" id="fwe-mirror-pair" ${d.mirror ? "checked" : ""}> Mirror pair: a matching one from the other side</label>
      ${sliders("Launch")}`),
    shape: isRocket(d) ? sec("Pattern", `<div class="fwe-patterns">${FWE_PATTERNS.map(([k, l, ic]) => `<button type="button" data-pattern="${k}" aria-pressed="${d.pattern === k}"><span>${ic}</span>${l}</button>`).join("")}</div>
      ${d.pattern === "picture" ? painterHtml() : ""}${sliders("Shape")}${d.pattern === "picture" ? sliders("Picture") : ""}`) : "",
    colours: sec("Colours", `${colorsHtml(d.colors, "ci")}
      <div class="fwe-dyes">${FW_COLORS.map((c) => `<button type="button" class="fw-swatch sm" data-dye="${c}" style="--c:${c}" aria-pressed="true" aria-label="Use ${c}"></button>`).join("")}</div>
      <div class="seg fwe-modes" role="group" aria-label="Colour style">${FWE_MODES.map(([k, l]) => `<button type="button" data-mode="${k}" aria-pressed="${d.color_mode === k}">${l}</button>`).join("")}</div>
      <p class="muted small">${{ mix: "Each piece picks one of your colours.", alternate: "Pieces go through your colours in order.", change: "Every piece changes from the first colour to the last as it fades.", rainbow: "Every colour of the rainbow, cycling as it falls." }[d.color_mode]}</p>`),
    then: isRocket(d) ? sec("Then…", stagesHtml(d), "fwe-stages") : "",
    motion: sec("Motion", sliders("Motion")),
    effects: sec("Effects", `${sliders("Effects")}
      ${isRocket(d) && d.second > 0 ? `<label class="fwe-select">…shape <select class="input sm" id="fwe-second-pattern">${FWE_PATTERNS.filter(([k]) => k !== "picture").map(([k, l, ic]) => `<option value="${k}" ${(d.second_pattern || "ball") === k ? "selected" : ""}>${ic} ${l}</option>`).join("")}</select></label>` : ""}`),
    sound: sec("Sound", `${isRocket(d) ? `<div class="fwe-row"><span>Going up</span><div class="seg" role="group">${[["whoosh", "Whoosh"], ["whistle", "Whistle"], ["custom", "🎛 Make your own"], ["none", "Silent"]].map(([k, l]) => `<button type="button" data-snd="sound_launch" data-v="${k}" aria-pressed="${(d.sound_launch || "whoosh") === k}">${l}</button>`).join("")}</div></div>
      ${d.sound_launch === "custom" ? sfxPanelHtml("launch") : ""}
      <div class="fwe-row"><span>The burst</span><div class="seg" role="group">${[["boom", "Boom"], ["pop", "Pop"], ["thud", "Thud"], ["crack", "Crack"], ["custom", "🎛 Make your own"], ["none", "Silent"]].map(([k, l]) => `<button type="button" data-snd="sound_burst" data-v="${k}" aria-pressed="${(d.sound_burst || "boom") === k}">${l}</button>`).join("")}</div></div>
      ${d.sound_burst === "custom" ? sfxPanelHtml("burst") : ""}
      <label class="check"><input type="checkbox" data-sndck="sound_crackle" ${d.sound_crackle !== false ? "checked" : ""}> Crackling (when it has crackle, glitter, strobe or bursts again)</label>
      <label class="check"><input type="checkbox" data-sndck="sound_fizzle" ${d.sound_fizzle ? "checked" : ""}> Fizzle as it fades</label>`
      : `<div class="fwe-row"><span>On the ground</span><div class="seg" role="group">${[["hiss", "Hiss"], ["crackle", "Crackle"], ["custom", "🎛 Make your own"], ["none", "Silent"]].map(([k, l]) => `<button type="button" data-snd="sound_ground" data-v="${k}" aria-pressed="${(d.sound_ground || "hiss") === k}">${l}</button>`).join("")}</div></div>
      ${d.sound_ground === "custom" ? `<p class="muted small">Your sound repeats for as long as the ${d.launch === "wheel" ? "wheel spins" : "fountain runs"}.</p>${sfxPanelHtml("ground")}` : ""}`}
      <p class="muted small">Sounds play for people who turn them on with 🔊 (here, or in the corner of any page). While you're in the editor only this preview makes sound.</p>`),
  };
  const tabs = FWE_TABS.filter(([k]) => panels[k]);
  if (!panels[ed.tab]) ed.tab = tabs[0][0];
  el.innerHTML = `<nav class="fwe-tabs" role="tablist" aria-label="Firework settings">${tabs.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${ed.tab === k}">${l}</button>`).join("")}</nav>
    <div class="fwe-panel" role="tabpanel">${panels[ed.tab]}</div>`;
  el.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { ed.tab = b.dataset.tab; renderControls(); }));
  el.querySelectorAll("[data-snd]").forEach((b) => b.addEventListener("click", () => {
    d[b.dataset.snd] = b.dataset.v;
    if (b.dataset.v === "custom") {                 // start from something that sounds right for the slot
      const slot = b.dataset.snd.replace("sound_", "");
      d[`sfx_${slot}`] ||= SFX_MAKERS[{ launch: "whoosh", burst: "boom", ground: "crackle" }[slot]]();
      renderControls(); fweLaunch(); return;
    }
    renderControls(); if (!FWAudio.isOn("editor")) showToast("Turn on 🔊 under the preview to hear it", 2000); fweLaunch();
  }));
  wireSfx(el);
  el.querySelectorAll("[data-sndck]").forEach((c) => c.addEventListener("change", () => { d[c.dataset.sndck] = c.checked; fweLaunch(); }));
  if (isRocket(d) && d.pattern === "picture") wirePainter();
  const rerender = (launchNow = true) => { renderControls(); if (launchNow) fweLaunch(); };
  el.querySelectorAll("[data-launch]").forEach((b) => b.addEventListener("click", () => { d.launch = b.dataset.launch; rerender(); }));
  el.querySelectorAll("[data-style]").forEach((b) => b.addEventListener("click", () => { d.rocket_style = b.dataset.style; rerender(); }));
  $("#fwe-second-pattern", el)?.addEventListener("change", (e) => { d.second_pattern = e.target.value; fweLaunch(); });
  $("#fwe-mirror-pair", el)?.addEventListener("change", (e) => { d.mirror = e.target.checked; fweLaunch(); });
  el.querySelectorAll("[data-pattern]").forEach((b) => b.addEventListener("click", () => {
    d.pattern = b.dataset.pattern;
    if (d.pattern === "picture" && !d.picture?.length) { ed.frame = 1; stampPicture("Heart"); }
    rerender();
  }));
  el.querySelectorAll("input[type=range][data-k]").forEach((inp) => inp.addEventListener("input", () => {
    const k = inp.dataset.k, si = inp.dataset.stage;
    const def = (si != null ? FWE_STAGE_SLIDERS : Object.values(FWE_SLIDERS).flat()).find((x) => x[0] === k);
    const target = si != null ? d.stages[+si] : d;
    target[k] = +inp.value;
    el.querySelector(`[data-out="${si != null ? `s${si}:` : ""}${k}"]`).textContent = def[5](+inp.value);
    fweChanged();
  }));
  // Some sliders show or hide others (volley settings, "burst again" timing): redraw once
  // the slider is let go, so dragging isn't interrupted.
  el.querySelectorAll('input[data-k="rockets"]:not([data-stage]), input[data-k="second"]:not([data-stage])').forEach((inp) =>
    inp.addEventListener("change", () => rerender(false)));
  // colours (main and per stage)
  el.querySelectorAll("input[type=color]").forEach((inp) => inp.addEventListener("input", () => {
    const st = inp.closest("[data-si]");
    const cols = st ? d.stages[+st.dataset.si].colors : d.colors;
    const idx = +(inp.dataset.ci ?? Object.entries(inp.dataset).find(([k]) => k.startsWith("sc"))?.[1]);
    cols[idx] = inp.value; refreshCells(); fweChanged();
  }));
  el.querySelectorAll("button").forEach((b) => {
    const rm = Object.keys(b.dataset).find((k) => k.startsWith("rmCi") || k.startsWith("rmSc"));
    const add = Object.keys(b.dataset).find((k) => k === "addCi" || k.startsWith("addSc"));
    if (rm) b.addEventListener("click", () => {
      const st = b.closest("[data-si]"); const cols = st ? d.stages[+st.dataset.si].colors : d.colors;
      cols.splice(+b.dataset[rm], 1); rerender(false); fweChanged();
    });
    if (add) b.addEventListener("click", () => {
      const st = b.closest("[data-si]"); const cols = st ? d.stages[+st.dataset.si].colors : d.colors;
      cols.push(pick2(FW_COLORS)); rerender(false); fweChanged();
    });
  });
  el.querySelectorAll("[data-dye]").forEach((b) => b.addEventListener("click", () => {
    if (d.colors.length < 4) d.colors.push(b.dataset.dye); else d.colors[d.colors.length - 1] = b.dataset.dye;
    rerender(false); fweChanged();
  }));
  el.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => { d.color_mode = b.dataset.mode; rerender(); }));
  // stages
  $("#fwe-addstage", el)?.addEventListener("click", () => {
    d.stages = d.stages || [];
    d.stages.push({ action: d.stages.length ? "shatter" : "burst", pattern: "ball", delay: 0.8, size: 0.9, sparks: 30, colors: [] });
    rerender();
  });
  el.querySelectorAll("[data-si]").forEach((card) => {
    const st = d.stages[+card.dataset.si];
    card.querySelector("[data-rm-stage]").addEventListener("click", () => { d.stages.splice(+card.dataset.si, 1); rerender(); });
    card.querySelectorAll("[data-action]").forEach((b) => b.addEventListener("click", () => { st.action = b.dataset.action; rerender(); }));
    card.querySelectorAll("[data-stage-snd]").forEach((b) => b.addEventListener("click", () => {
      st.sound = b.dataset.stageSnd;
      if (st.sound === "custom") st.sfx ||= SFX_MAKERS.boom();
      if (!FWAudio.isOn("editor")) showToast("Turn on 🔊 under the preview to hear it", 2000);
      rerender();
    }));
    card.querySelector("[data-stage-pattern]")?.addEventListener("change", (e) => { st.pattern = e.target.value; fweLaunch(); });
    card.querySelector("[data-stage-owncolors]").addEventListener("change", (e) => {
      st.colors = e.target.checked ? [pick2(FW_COLORS), pick2(FW_COLORS)] : []; rerender();
    });
  });
}
const pick2 = (a) => a[Math.floor(Math.random() * a.length)];

// ---------------------------------------------------------------- pixel painter
function painterHtml() {
  const brushes = ed.d.colors.map((c, i) => `<button type="button" class="fwe-brush" data-brush="${i}" aria-pressed="${ed.brush === String(i)}" style="--c:${c}" aria-label="Paint with colour ${i + 1}"></button>`).join("");
  const has2 = ed.d.picture2?.length;
  return `<div class="fwe-painter">
    <div class="seg fwe-frames" role="group" aria-label="Frame">
      <button type="button" data-frame="1" aria-pressed="${ed.frame === 1}">Frame 1</button>
      <button type="button" data-frame="2" aria-pressed="${ed.frame === 2}">Frame 2${has2 ? "" : " (optional)"}</button></div>
    ${ed.frame === 2 ? `<p class="muted small">Paint a second picture and the firework swaps between the two while it holds, like a flip-book. <button type="button" class="link-btn" id="fwe-copyframe">Start from a copy of frame 1</button></p>` : ""}
    <div class="fwe-tools">${brushes}${ed.d.colors.length < 4 ? `<button type="button" class="fwe-brush add" id="fwe-brush-add" title="Add a colour" aria-label="Add a colour">＋</button>` : ""}
      <button type="button" class="fwe-brush eraser" data-brush="." aria-pressed="${ed.brush === "."}" aria-label="Eraser">⌫</button>
      <label class="fwe-brush-pick ${ed.brush === "." ? "off" : ""}" title="Change the selected colour">🎨<input type="color" id="fwe-brush-color" value="${esc(ed.d.colors[+ed.brush] || ed.d.colors[0])}" aria-label="Change the selected colour" ${ed.brush === "." ? "disabled" : ""}></label>
      <label class="check"><input type="checkbox" id="fwe-mirror" ${ed.mirror ? "checked" : ""}> Mirror</label>
      <button type="button" class="btn sm" id="fwe-clear">Clear</button></div>
    <div class="fwe-grid" id="fwe-grid" style="--n:${FWE_GRID}">${Array.from({ length: FWE_GRID * FWE_GRID }, (_, i) => `<span data-cell="${i}"></span>`).join("")}</div>
    <div class="fwe-stamps"><span class="muted small">Stamps:</span>${Object.keys(FWE_STAMPS).map((k) => `<button type="button" class="btn sm" data-stamp="${k}">${k}</button>`).join("")}
      <select class="input sm" id="fwe-face" aria-label="Use a player's face"><option value="">🙂 Face of…</option>${(ed.players || []).map((p) => `<option value="${esc(p.uuid)}">${esc(p.name)}</option>`).join("")}</select>
      <label class="check small"><input type="checkbox" id="fwe-face-big" ${ed.faceBig !== false ? "checked" : ""}> big</label></div>
    <p class="muted small">Click or drag to paint. Each painted square becomes one spark.</p></div>`;
}
function stampPicture(name) {
  const rows = FWE_STAMPS[name] || [];
  const grid = Array.from({ length: FWE_GRID }, () => new Array(FWE_GRID).fill("."));
  const h = rows.length, w = Math.max(...rows.map((r) => r.length));
  const oy = Math.floor((FWE_GRID - h) / 2), ox = Math.floor((FWE_GRID - w) / 2);
  rows.forEach((r, y) => [...r].forEach((c, x) => {
    if (c !== "." && grid[oy + y]?.[ox + x] !== undefined) grid[oy + y][ox + x] = String(Math.min(+c, ed.d.colors.length - 1));
  }));
  fweSetPicture(grid);
}
function refreshCells() {
  const g = $("#fwe-grid");
  if (!g) return;
  const grid = ed.grids[ed.frame] || fwePicture();
  ed.grids[ed.frame] = grid;
  // Faintly show the other frame underneath, like onion skin, so frames line up.
  const other = ed.frame === 2 ? (ed.grids[1] || fwePicture(1)) : null;
  g.querySelectorAll("[data-cell]").forEach((cell) => {
    const i = +cell.dataset.cell, y = Math.floor(i / FWE_GRID), x = i % FWE_GRID, v = grid[y][x];
    const ghost = other && other[y][x] !== "." && v === ".";
    cell.style.background = v === "." ? "" : ed.d.colors[+v] || ed.d.colors[0];
    cell.classList.toggle("on", v !== ".");
    cell.classList.toggle("ghost", !!ghost);
  });
  $$(".fwe-brush[data-brush]").forEach((b) => { if (b.dataset.brush !== ".") b.style.setProperty("--c", ed.d.colors[+b.dataset.brush] || "#000"); });
}
function wirePainter() {
  ed.grids[ed.frame] ||= fwePicture();
  refreshCells();
  const g = $("#fwe-grid");
  const paintAt = (cell) => {
    if (!cell?.dataset?.cell) return;
    const i = +cell.dataset.cell, y = Math.floor(i / FWE_GRID), x = i % FWE_GRID;
    const v = ed.brush === "." ? "." : String(Math.min(+ed.brush, ed.d.colors.length - 1));
    const grid = ed.grids[ed.frame];
    grid[y][x] = v;
    if (ed.mirror) grid[y][FWE_GRID - 1 - x] = v;
    fweSetPicture(grid);
    refreshCells();
  };
  g.addEventListener("pointerdown", (e) => { ed.painting = true; g.setPointerCapture(e.pointerId); paintAt(e.target.closest("[data-cell]")); e.preventDefault(); });
  g.addEventListener("pointermove", (e) => { if (ed.painting) paintAt(document.elementFromPoint(e.clientX, e.clientY)?.closest?.("[data-cell]")); });
  const stop = () => { if (ed.painting) { ed.painting = false; fweChanged(); } };
  g.addEventListener("pointerup", stop);
  g.addEventListener("pointercancel", stop);
  // Pick a brush; click the picked one again (or 🎨) to change its colour.
  const picker = $("#fwe-brush-color");
  $$(".fwe-brush[data-brush]").forEach((b) => b.addEventListener("click", () => {
    const again = ed.brush === b.dataset.brush;
    ed.brush = b.dataset.brush;
    $$(".fwe-brush[data-brush]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    const erasing = ed.brush === ".";
    picker.disabled = erasing; picker.parentElement.classList.toggle("off", erasing);
    if (!erasing) { picker.value = ed.d.colors[+ed.brush]; if (again) picker.click(); }
  }));
  picker?.addEventListener("input", () => {
    if (ed.brush === ".") return;
    const i = +ed.brush;
    ed.d.colors[i] = picker.value;
    const b = $(`.fwe-brush[data-brush="${i}"]`); if (b) b.style.setProperty("--c", picker.value);
    refreshCells(); fweChanged();
  });
  $("#fwe-brush-add")?.addEventListener("click", () => {
    const unused = FW_COLORS.find((c) => !ed.d.colors.includes(c)) || "#ffffff";
    ed.d.colors.push(unused); ed.brush = String(ed.d.colors.length - 1);
    renderControls(); fweChanged();
  });
  $("#fwe-mirror").addEventListener("change", (e) => { ed.mirror = e.target.checked; });
  $("#fwe-clear").addEventListener("click", () => { fweSetPicture(Array.from({ length: FWE_GRID }, () => new Array(FWE_GRID).fill("."))); refreshCells(); fweChanged(); });
  $$("[data-stamp]").forEach((b) => b.addEventListener("click", () => { stampPicture(b.dataset.stamp); refreshCells(); fweLaunch(); }));
  $$("[data-frame]").forEach((b) => b.addEventListener("click", () => { ed.frame = +b.dataset.frame; renderControls(); }));
  if (!ed.players) api("/api/players/skins").then((list) => { ed.players = list; if ($("#fwe-face")) renderControls(); }).catch(() => { ed.players = []; });
  $("#fwe-face-big")?.addEventListener("change", (e) => { ed.faceBig = e.target.checked; });
  $("#fwe-face")?.addEventListener("change", async (e) => {
    const uuid = e.target.value;
    if (!uuid) return;
    try { await faceStamp(uuid, ed.faceBig !== false); renderControls(); fweLaunch(); }
    catch { showToast("Couldn't get that player's skin", 3000); e.target.value = ""; }
  });
  $("#fwe-copyframe")?.addEventListener("click", () => { fweSetPicture((ed.grids[1] || fwePicture(1)).map((r) => [...r]), 2); renderControls(); fweLaunch(); });
}

// ---------------------------------------------------------------- surprise me
function fweSurprise() {
  const r = (a, b) => a + Math.random() * (b - a), chance = (p) => Math.random() < p, f2 = (v) => +v.toFixed(2);
  const launch = chance(0.82) ? "rocket" : pick2(["fountain", "wheel"]);
  const pattern = pick2(["ball", "ball", "ring", "star", "burst", "spiral", "palm", "saturn", "pop", "picture"]);
  const colors = [...new Set(Array.from({ length: 1 + Math.floor(Math.random() * 3) }, () => pick2(FW_COLORS)))];
  const volley = chance(0.25);
  const d = {
    ...fweCopy(FWE_DEFAULT), launch, pattern, colors, color_mode: pick2(["mix", "mix", "alternate", "change", "rainbow"]),
    sparks: Math.round(r(24, 110)), size: f2(r(0.8, 2.2)), spread: f2(r(0, 0.4)), squash: chance(0.25) ? f2(r(0.5, 1.4)) : 1,
    tilt: f2(r(0, 0.8)), points: Math.round(r(4, 8)), arms: Math.round(r(2, 5)), spin: f2(r(-1, 1)),
    gravity: f2(r(0.3, 1.5)), drag: f2(r(0.1, 0.7)), life: +r(0.9, 3.2).toFixed(1), wind: chance(0.2) ? f2(r(-0.6, 0.6)) : 0,
    height: f2(r(0.4, 0.9)), rockets: volley ? Math.round(r(3, 10)) : 1, interval: f2(r(0.1, 0.5)), spot: volley ? f2(r(0, 0.6)) : 0.3,
    fan: volley ? f2(r(0, 0.8)) : 0, lean: chance(0.2) ? f2(r(-0.5, 0.5)) : 0, hang: chance(0.15) ? +r(0.4, 1.5).toFixed(1) : 0,
    rocket_style: pick2(["normal", "normal", "sparkly", "corkscrew", "colored", "invisible"]), mirror: chance(0.15),
    hold: +r(0.5, 1.6).toFixed(1), move_x: chance(0.3) ? f2(r(-0.8, 0.8)) : 0, move_y: chance(0.2) ? f2(r(-0.5, 0.8)) : 0, turn: chance(0.25) ? f2(r(-0.8, 0.8)) : 0,
    duration: +r(3, 7).toFixed(1), rate: f2(r(0.4, 0.9)), power: f2(r(0.6, 1.2)), angle: f2(r(0.1, 0.6)), wheel_spin: f2(r(0.4, 1) * (chance(0.5) ? -1 : 1)),
    sparkle: chance(0.35) ? f2(r(0.2, 0.8)) : 0, trail: chance(0.35) ? f2(r(0.3, 0.9)) : 0,
    glitter: chance(0.25) ? f2(r(0.3, 0.9)) : 0, flash: f2(r(0, 0.8)), piece: chance(0.2) ? 2 : 1, grow: chance(0.15) ? f2(r(0.3, 1)) : 0,
    wobble: chance(0.15) ? f2(r(0.3, 1)) : 0, fizzle: chance(0.2) ? f2(r(0.4, 1)) : 0,
    blink: chance(0.12) ? f2(r(0.2, 0.9)) : 0, strobe: chance(0.1) ? f2(r(0.2, 0.7)) : 0,
    breathe: chance(0.12) ? f2(r(0.3, 0.9)) : 0, second: chance(0.2) ? f2(r(0.2, 0.7)) : 0,
    second_delay: f2(r(0.3, 0.9)), second_size: f2(r(0.4, 1)), picture: [], picture2: [],
    stages: chance(0.35) ? Array.from({ length: chance(0.3) ? 2 : 1 }, () => ({
      action: pick2(["burst", "pieces", "shatter", "implode"]), pattern: pick2(["ball", "ring", "star", "pop", "burst", "saturn"]),
      delay: f2(r(0.5, 1.5)), size: f2(r(0.6, 1.6)), sparks: Math.round(r(16, 50)), colors: chance(0.5) ? [pick2(FW_COLORS), pick2(FW_COLORS)] : [],
    })) : [],
  };
  if (pattern === "picture" && launch === "rocket") { ed.d = d; ed.grids = {}; ed.frame = 1; stampPicture(pick2(Object.keys(FWE_STAMPS))); return ed.d; }
  return d;
}

// ---------------------------------------------------------------- saving and the gallery
async function fweSave(asNew) {
  const body = { ...ed.d, name: (ed.d.name || "").trim() || "My firework" };
  try {
    const saved = ed.id && !asNew ? await post(`/api/fireworks/${ed.id}`, body, "PUT") : await post("/api/fireworks", body);
    ed.id = saved.id; ed.d = { ...fweCopy(FWE_DEFAULT), ...saved }; fweMarkSaved(); fweClearDraft();
    showToast(`Saved “${esc(saved.name)}”${saved.in_show ? " · it's in the show" : ""}`, 2500);
    await fweRefresh();
    location.hash = `#/fireworks/${saved.id}`;
  } catch (err) { showToast(esc(err.message), 4000); }
}
async function fweRefresh() {
  ed.list = await api("/api/fireworks").catch(() => ed.list);
  renderGallery();
  // Let the sky on this page (and its show) pick up the change straight away.
  fetch("/api/public/fireworks").then((r) => r.json()).then(applyFireworkSettings).catch(() => {});
}
// The saved list: yours first (Mine), or everyone's folded by who made them, or what's in the show; and a search.
// Kept simple on purpose: young players use it too.
function renderGallery() {
  const el = $("#fwe-list");
  if (!el) return;
  const label = Object.fromEntries(FWE_PATTERNS.map(([k, l, ic]) => [k, `${ic} ${l}`]));
  const by = ed.show === "all" ? "maker" : "";
  const lim = ed.limit, mine = ed.list.filter((f) => f.mine).length;
  const count = $("#fwe-count");
  if (count) count.textContent = lim?.limited && lim.per_person ? `${ed.list.length} · ${mine} of ${lim.per_person} yours` : String(ed.list.length);
  const filt = $("#fwe-filter");
  if (filt && !filt._wired) {
    filt._wired = true;
    filt.innerHTML = `<div class="seg" role="group" aria-label="Show">${[["mine", "Mine"], ["all", "Everyone's"], ["show", "In the show"]].map(([k, l]) => `<button type="button" data-show="${k}" aria-pressed="${ed.show === k}">${l}</button>`).join("")}</div>
      <input class="input sm" type="search" id="fwe-q" placeholder="Search names" value="${esc(ed.q)}" aria-label="Search saved fireworks">
      ${isAdmin() ? `<label class="fwe-limit small">Each person can keep <select class="input sm" id="fwe-limit">${[5, 10, 20, 30, 50, 100, 0].map((n) => `<option value="${n}" ${lim?.per_person === n ? "selected" : ""}>${n || "any number"}</option>`).join("")}</select> <span class="muted">(admins: no limit)</span></label>` : ""}`;
    filt.querySelectorAll("[data-show]").forEach((b) => b.addEventListener("click", () => { ed.show = b.dataset.show; filt.querySelectorAll("[data-show]").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); renderGallery(); }));
    $("#fwe-q", filt).addEventListener("input", (e) => { ed.q = e.target.value; renderGallery(); });
    $("#fwe-limit", filt)?.addEventListener("change", async (e) => {
      try { ed.limit = { ...ed.limit, ...(await post("/api/fireworks/limit", { per_person: +e.target.value }, "PUT")) }; showToast("Saved", 1500); renderGallery(); }
      catch (err) { showToast(esc(err.message), 4000); }
    });
  }
  const q = ed.q.trim().toLowerCase();
  const shown = ed.list.slice().reverse().filter((f) => (ed.show !== "mine" || f.mine) && (ed.show !== "show" || f.in_show)
    && (!q || f.name.toLowerCase().includes(q) || (f.author || "").toLowerCase().includes(q)));
  const keyOf = (f) => (by ? f.author || "?" : "");
  const sections = new Map();
  for (const f of shown) { const k = keyOf(f); if (!sections.has(k)) sections.set(k, []); sections.get(k).push(f); }
  const order = [...sections.keys()].sort((a, b) => (b === me.user?.username) - (a === me.user?.username) || a.localeCompare(b));
  const titleOf = (k) => (k === me.user?.username ? `${k} (you)` : k);
  const card = (f) => `<div class="fwe-card ${f.id === ed.id ? "current" : ""}" data-id="${f.id}">
      <div class="fwe-card-main"><b>${esc(f.name)}</b><span class="muted small">${esc(f.launch && f.launch !== "rocket" ? (FWE_LAUNCHES.find(([k]) => k === f.launch) || [])[1] || "" : label[f.pattern] || f.pattern)} · by ${esc(f.author)}</span>
        <span class="fwe-dots">${f.colors.map((c) => `<i style="background:${c}"></i>`).join("")}</span></div>
      <div class="fwe-card-acts">
        <button type="button" class="icon-btn" data-act="play" title="Launch it" aria-label="Launch ${esc(f.name)}">▶</button>
        ${f.can_edit ? `<label class="check small" title="Include in the fireworks show"><input type="checkbox" data-act="show" ${f.in_show ? "checked" : ""}> Show</label>
          <a class="btn sm" href="#/fireworks/${f.id}">Edit</a>` : `<button type="button" class="btn sm" data-act="copy">Copy</button>`}
        ${f.can_edit ? `<button type="button" class="btn sm danger" data-act="del" aria-label="Delete ${esc(f.name)}">Delete</button>` : ""}
      </div></div>`;
  const openOf = (k) => ed.open[`${by}:${k}`] ?? (order.length <= 3 || shown.some((f) => keyOf(f) === k && (f.id === ed.id)) || k === me.user?.username || !!q);
  el.innerHTML = !ed.list.length ? `<p class="muted">Nothing saved yet. Make something and press Save.</p>`
    : !shown.length ? `<p class="muted">${ed.show === "mine" && !q ? "You haven't saved any yet. Make one and press Save, or look at Everyone's." : "Nothing matches."}</p>`
    : !by ? `<div class="fwe-group-list">${shown.map(card).join("")}</div>`
    : order.map((k) => `<details class="fwe-group" data-key="${esc(k)}" ${openOf(k) ? "open" : ""}><summary><b>${esc(titleOf(k))}</b> <span class="muted small">${sections.get(k).length}</span></summary>
        <div class="fwe-group-list">${sections.get(k).map(card).join("")}</div></details>`).join("");
  el.querySelectorAll(".fwe-group").forEach((g) => g.addEventListener("toggle", () => { ed.open[`${by}:${g.dataset.key}`] = g.open; }));
  el.querySelectorAll(".fwe-card").forEach((card) => {
    const f = ed.list.find((x) => x.id === card.dataset.id);
    card.querySelector('[data-act="play"]').addEventListener("click", () => fweLaunch({ ...FWE_DEFAULT, ...f }));
    card.querySelector('a.btn[href^="#/fireworks/"]')?.addEventListener("click", async (e) => {
      if (!fweDirty() || f.id === ed.id) return;
      e.preventDefault();
      if (await confirmBox(`Edit “${f.name}” instead?`, "What you're working on now hasn't been saved and will be thrown away.", "Throw it away")) {
        ed.base = null; location.hash = `#/fireworks/${f.id}`;
      }
    });
    card.querySelector('[data-act="copy"]')?.addEventListener("click", () => {
      ed.d = { ...fweCopy(FWE_DEFAULT), ...fweCopy(f), name: `${f.name} (copy)` }; ed.id = null; ed.grids = {}; ed.frame = 1; ed.base = fweSnap(fweCopy(FWE_DEFAULT));
      location.hash = "#/fireworks"; viewFireworkEditor();
    });
    card.querySelector('[data-act="show"]')?.addEventListener("change", async (e) => {
      try { await post(`/api/fireworks/${f.id}`, { in_show: e.target.checked }, "PUT"); await fweRefresh(); }
      catch (err) { showToast(esc(err.message), 4000); }
    });
    card.querySelector('[data-act="del"]')?.addEventListener("click", async () => {
      if (!(await confirmBox(`Delete “${f.name}”?`, "It will stop appearing in the show.", "Delete"))) return;
      try {
        await api(`/api/fireworks/${f.id}`, { method: "DELETE" });
        if (ed.id === f.id) { ed.id = null; ed.base = fweSnap(fweCopy(FWE_DEFAULT)); }
        await fweRefresh();
      } catch (err) { showToast(esc(err.message), 4000); }
    });
  });
}

// ---------------------------------------------------------------- "Face of…" stamp
// Takes a player's face (with the hat layer) from their skin, boils it down to the
// four colours a picture firework can use, and paints it into the current frame.
async function faceStamp(uuid, big) {
  const img = new Image();
  img.src = `/api/skins/${String(uuid).replace(/-/g, "")}.png`;
  await img.decode();
  const c = document.createElement("canvas"); c.width = 8; c.height = 8;
  const g = c.getContext("2d", { willReadFrequently: true });
  g.imageSmoothingEnabled = false;
  g.drawImage(img, 8, 8, 8, 8, 0, 0, 8, 8);
  g.drawImage(img, 40, 8, 8, 8, 0, 0, 8, 8);        // hat / mask layer on top
  const data = g.getImageData(0, 0, 8, 8).data;
  const px = [];
  for (let i = 0; i < 64; i++) px.push(data[i * 4 + 3] > 40 ? [data[i * 4], data[i * 4 + 1], data[i * 4 + 2]] : null);
  const solid = px.filter(Boolean);
  if (!solid.length) throw new Error("empty");
  const palette = quantize(solid, 4);
  const near = (p) => palette.reduce((best, q, k) => { const dd = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2; return dd < best[1] ? [k, dd] : best; }, [0, Infinity])[0];
  const scale = big ? 2 : 1, size = 8 * scale, off = Math.floor((FWE_GRID - size) / 2);
  const grid = Array.from({ length: FWE_GRID }, () => new Array(FWE_GRID).fill("."));
  px.forEach((p, i) => {
    if (!p) return;
    const v = String(near(p)), x = (i % 8) * scale, y = Math.floor(i / 8) * scale;
    for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++) grid[off + y + dy][off + x + dx] = v;
  });
  // Faces read best as a picture that hangs for a while with solid pieces.
  ed.d.colors = palette.map((q) => `#${q.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`);
  ed.d.color_mode = "mix";
  ed.d.piece = Math.max(ed.d.piece || 1, 2);
  ed.d.hold = Math.max(ed.d.hold || 0.8, 1.5);
  ed.mirror = false;
  fweSetPicture(grid);
}
// k-means on a handful of pixels, started from colours that are far apart.
function quantize(points, k) {
  const uniq = [...new Map(points.map((p) => [p.join(","), p])).values()];
  if (uniq.length <= k) return uniq.map((p) => [...p]);
  const dist = (a, b) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2;
  const centres = [[...uniq[0]]];
  while (centres.length < k) centres.push([...uniq.reduce((best, p) => (Math.min(...centres.map((c) => dist(p, c))) > Math.min(...centres.map((c) => dist(best, c))) ? p : best), uniq[0])]);
  for (let it = 0; it < 10; it++) {
    const sums = centres.map(() => [0, 0, 0, 0]);
    for (const p of points) {
      let bi = 0; centres.forEach((c, i) => { if (dist(p, c) < dist(p, centres[bi])) bi = i; });
      sums[bi][0] += p[0]; sums[bi][1] += p[1]; sums[bi][2] += p[2]; sums[bi][3]++;
    }
    sums.forEach((sm, i) => { if (sm[3]) centres[i] = [sm[0] / sm[3], sm[1] / sm[3], sm[2] / sm[3]]; });
  }
  return centres;
}

// ---------------------------------------------------------------- make your own sound
// bfxr-style: a wave, an envelope, pitch moves, tone and character, with a waveform to see it.
const SFX_MAKER_BTNS = [["boom", "💥 Boom"], ["pop", "🫧 Pop"], ["thud", "🥁 Thud"], ["crackle", "✨ Crackle"], ["whistle", "🎵 Whistle"], ["whoosh", "💨 Whoosh"],
  ["zap", "⚡ Zap"], ["sparkle", "🪙 Sparkle"], ["thunder", "⛈ Thunder"], ["chip", "👾 Chiptune"], ["random", "🎲 Random"]];
const SFX_WAVE_BTNS = [["square", "Square"], ["saw", "Saw"], ["triangle", "Triangle"], ["sine", "Sine"], ["noise", "Noise"]];
const sfxSec = (v) => `${(+v).toFixed(2)} s`, sfxPct = (v) => `${Math.round(v * 100)}%`, sfxSigned = (v) => `${v > 0 ? "+" : ""}${Math.round(v * 100)}`;
const SFX_GROUPS = [
  ["Envelope", [["attack", "Attack", sfxSec], ["sustain", "Sustain", sfxSec], ["punch", "Punch", sfxPct], ["decay", "Decay", sfxSec]]],
  ["Pitch", [["freq", "Start pitch", (v) => `${Math.round(v)} Hz`], ["slide", "Slide", sfxSigned], ["vib", "Vibrato depth", sfxPct], ["vib_speed", "Vibrato speed", (v) => `${(+v).toFixed(1)} Hz`],
    ["jump", "Pitch jump", (v) => `${v > 0 ? "+" : ""}${Math.round(v)} semitones`], ["jump_at", "Jump at", sfxPct]]],
  ["Tone", [["duty", "Square width", sfxPct, (p) => p.wave === "square"], ["lp", "Low-pass", sfxPct], ["lp_sweep", "Low-pass sweep", sfxSigned], ["res", "Resonance", sfxPct], ["hp", "High-pass", sfxPct]]],
  ["Character", [["crunch", "Crunch (bit-crush)", sfxPct], ["drive", "Drive (compression)", sfxPct], ["repeat", "Repeats", (v) => `×${Math.round(v)}`],
    ["repeat_gap", "Repeat gap", sfxSec, (p) => p.repeat > 1], ["echo", "Echo", sfxPct], ["echo_delay", "Echo delay", sfxSec, (p) => p.echo > 0], ["volume", "Volume", sfxPct]]],
];
// Pitch is easier to set on a log scale.
const sfxToSlider = (k, v) => k === "freq" ? Math.round(Math.log(v / 20) / Math.log(250) * 1000) : v;
const sfxFromSlider = (k, v) => k === "freq" ? Math.round(20 * 250 ** (v / 1000)) : v;
// Where a slot's custom sound is kept: on the firework (launch, burst, ground) or on a "then…" step.
const sfxHome = (slot) => (slot.startsWith("stage") ? [ed.d.stages[+slot.slice(5)], "sfx"] : [ed.d, `sfx_${slot}`]);
function sfxPanelHtml(slot) {
  const [home, hk] = sfxHome(slot);
  const p = { ...SFX_DEFAULT, ...home[hk] };
  const slider = ([k, label, fmt, when]) => {
    if (when && !when(p)) return "";
    const [lo, hi, step] = SFX_RANGES[k];
    const attrs = k === "freq" ? `min="0" max="1000" step="1"` : `min="${lo}" max="${hi}" step="${step}"`;
    return `<label class="fwe-slider"><span>${esc(label)}</span><b data-sfx-out="${k}">${esc(fmt(p[k]))}</b>
      <input type="range" ${attrs} value="${sfxToSlider(k, p[k])}" data-sfx="${k}"></label>`;
  };
  return `<div class="sfx" data-slot="${slot}">
    <div class="sfx-top"><canvas class="sfx-wave" aria-label="What the sound looks like"></canvas>
      <div class="sfx-play"><button class="btn primary" type="button" data-sfx-play>▶ Play</button><span class="muted small" data-sfx-len></span></div></div>
    <div class="sfx-lib">
      <select class="input sm" data-sfx-lib aria-label="Saved sounds"><option value="">📂 Saved sounds (${(ed.sounds || []).length})…</option>${(ed.sounds || []).map((x) => `<option value="${esc(x.id)}">${esc(x.name)} · ${esc(x.author)}</option>`).join("")}</select>
      <input class="input sm" data-sfx-name maxlength="32" placeholder="Name this sound" aria-label="Name for this sound">
      <button class="btn sm" type="button" data-sfx-save>💾 Save sound</button>
      <button class="btn sm danger" type="button" data-sfx-del hidden>Delete saved</button></div>
    <div class="sfx-makers" role="group" aria-label="Start from">${SFX_MAKER_BTNS.map(([k, l]) => `<button type="button" class="btn sm" data-sfx-make="${k}">${l}</button>`).join("")}
      <button type="button" class="btn sm" data-sfx-mutate title="Nudge everything a little">🧬 Mutate</button></div>
    <div class="fwe-row"><span>Wave</span><div class="seg" role="group">${SFX_WAVE_BTNS.map(([k, l]) => `<button type="button" data-sfx-wave="${k}" aria-pressed="${p.wave === k}">${l}</button>`).join("")}</div></div>
    <div class="sfx-groups">${SFX_GROUPS.map(([title, list]) => `<fieldset class="sfx-group"><legend>${title}</legend><div class="fwe-sliders">${list.map(slider).join("")}</div></fieldset>`).join("")}</div>
  </div>`;
}
function wireSfx(root) {
  root.querySelectorAll(".sfx").forEach((box) => {
    const slot = box.dataset.slot, [home, key] = sfxHome(slot);
    const p = () => (home[key] = { ...SFX_DEFAULT, ...home[key] });
    const play = () => { ed.scene?.hush(); FWAudio.preview(p()); };      // only this sound, nothing else
    const redraw = () => sfxDraw(box, p());
    // A change starts the preview over, so you hear the new sound in place right away.
    const rebuild = () => { renderControls(); fweLaunch(); };
    box.querySelector("[data-sfx-play]").addEventListener("click", play);
    box.querySelectorAll("[data-sfx-make]").forEach((b) => b.addEventListener("click", () => { home[key] = SFX_MAKERS[b.dataset.sfxMake](); rebuild(); }));
    box.querySelector("[data-sfx-mutate]").addEventListener("click", () => { home[key] = sfxMutate(p()); rebuild(); });
    const lib = box.querySelector("[data-sfx-lib]"), del = box.querySelector("[data-sfx-del]");
    lib.addEventListener("change", () => {
      const x = (ed.sounds || []).find((o) => o.id === lib.value);
      del.hidden = !x?.can_delete;
      if (!x) return;
      home[key] = { ...x.sfx };
      const keep = lib.value; rebuild(); const again = $(`.sfx[data-slot="${slot}"] [data-sfx-lib]`); if (again) { again.value = keep; again.dispatchEvent(new Event("pick")); }
    });
    lib.addEventListener("pick", () => { const x = (ed.sounds || []).find((o) => o.id === lib.value); del.hidden = !x?.can_delete; });
    box.querySelector("[data-sfx-save]").addEventListener("click", async () => {
      const name = box.querySelector("[data-sfx-name]").value.trim();
      if (!name) { showToast("Give the sound a name first", 2500); box.querySelector("[data-sfx-name]").focus(); return; }
      try {
        await post("/api/sounds", { name, sfx: p() });
        ed.sounds = await api("/api/sounds");
        showToast(`Saved “${esc(name)}”. It's in Saved sounds for every firework now.`, 3000);
        renderControls();
      } catch (err) { showToast(esc(err.message), 4000); }
    });
    del.addEventListener("click", async () => {
      const x = (ed.sounds || []).find((o) => o.id === lib.value);
      if (!x || !(await confirmBox(`Delete the sound “${x.name}”?`, "Fireworks already using it keep their own copy.", "Delete"))) return;
      try { await api(`/api/sounds/${x.id}`, { method: "DELETE" }); ed.sounds = await api("/api/sounds"); renderControls(); }
      catch (err) { showToast(esc(err.message), 4000); }
    });
    box.querySelectorAll("[data-sfx-wave]").forEach((b) => b.addEventListener("click", () => { p().wave = b.dataset.sfxWave; rebuild(); }));
    box.querySelectorAll("[data-sfx]").forEach((inp) => {
      const k = inp.dataset.sfx, fmt = SFX_GROUPS.flatMap(([, l]) => l).find((x) => x[0] === k)[2];
      inp.addEventListener("input", () => {
        p()[k] = sfxFromSlider(k, +inp.value);
        box.querySelector(`[data-sfx-out="${k}"]`).textContent = fmt(p()[k]);
        redraw();
      });
      // Hear it when the slider is let go; some sliders show or hide others.
      inp.addEventListener("change", () => { if (["repeat", "echo"].includes(k)) renderControls(); fweLaunch(); });
    });
    redraw();
  });
}
function sfxDraw(box, p) {
  clearTimeout(box._drawT);                       // one timer per panel (launch and burst can both be open)
  box._drawT = setTimeout(async () => {
    const cv = box.querySelector(".sfx-wave"), data = await sfxRender(p).catch(() => null);
    if (!cv?.isConnected || !data) return;
    const w = cv.clientWidth, h = cv.clientHeight, dpr = devicePixelRatio || 1;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    const c = cv.getContext("2d");
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, w, h);
    c.strokeStyle = "rgba(255,255,255,.08)"; c.beginPath(); c.moveTo(0, h / 2 + 0.5); c.lineTo(w, h / 2 + 0.5); c.stroke();
    let peak = 0.0001;
    for (let i = 0; i < data.length; i += 4) peak = Math.max(peak, Math.abs(data[i]));
    const per = data.length / w, g = c.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, "#f2c14e"); g.addColorStop(0.5, "#ffe9a8"); g.addColorStop(1, "#f2c14e");
    c.fillStyle = g;
    for (let x = 0; x < w; x++) {
      let lo = 0, hi = 0;
      for (let i = Math.floor(x * per); i < Math.floor((x + 1) * per); i++) { const v = data[i] / peak; if (v < lo) lo = v; if (v > hi) hi = v; }
      c.fillRect(x, h / 2 - hi * h * 0.45, 1, Math.max(1, (hi - lo) * h * 0.45));
    }
    const len = box.querySelector("[data-sfx-len]");
    if (len) len.textContent = `${(data.length / 11025).toFixed(1)} s`;
  }, 60);
}
