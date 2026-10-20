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
};
const FWE_LAUNCHES = [["rocket", "Sky rocket", "🚀"], ["fountain", "Fountain", "⛲"], ["wheel", "Spinning wheel", "🎡"]];
const FWE_STYLES = [["normal", "Normal"], ["sparkly", "Sparkly"], ["corkscrew", "Corkscrew"], ["colored", "Coloured"], ["invisible", "Invisible"]];
const FWE_PATTERNS = [
  ["ball", "Ball", "●"], ["ring", "Ring", "◯"], ["star", "Star", "★"], ["burst", "Burst", "✳"], ["spiral", "Spiral", "🌀"],
  ["palm", "Palm", "🌴"], ["saturn", "Saturn", "🪐"], ["pop", "Pop", "💥"], ["picture", "Picture", "🎨"],
];
const FWE_ACTIONS = [["burst", "Burst again", "a new burst from the middle"], ["pieces", "Every piece bursts", "lots of little bursts"],
  ["shatter", "Shatter", "everything flies outward"], ["implode", "Implode", "pulls back in, then pops"]];
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

const ed = { d: null, id: null, list: [], scene: null, loop: true, debounce: 0, brush: "0", mirror: true, painting: false, frame: 1, grids: {} };

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
  document.title = "Firework editor · Solstone";
  $("#rail-servers").innerHTML = railHtml(null);
  ed.list = await api("/api/fireworks").catch(() => []);
  const found = editId && ed.list.find((x) => x.id === editId && x.can_edit);
  ed.d = found ? { ...fweCopy(FWE_DEFAULT), ...fweCopy(found) } : ed.d && !editId ? ed.d : fweCopy(FWE_DEFAULT);
  ed.id = found ? found.id : editId ? null : ed.id;
  ed.grids = {}; ed.frame = 1;
  setView(`<div class="fwe-head"><h1>Firework editor</h1>
      <p class="muted">Design a firework, watch it go off, and save it. Fireworks marked <b>In the show</b> join the sky on every page of Solstone, including the sign-in and status pages.</p></div>
    <div class="fwe">
      <div class="fwe-left">
        <div class="fwe-preview glass"><canvas id="fwe-sky" aria-label="Preview sky"></canvas>
          <div class="fwe-bar"><button class="btn primary" id="fwe-launch" type="button">🎆 Launch</button>
            <label class="check fwe-loopck"><input type="checkbox" id="fwe-loop" ${ed.loop ? "checked" : ""}> Keep launching</label>
            <button class="btn" id="fwe-surprise" type="button">🎲 Surprise me</button></div></div>
        <form class="panel fwe-save" id="fwe-save" autocomplete="off">
          <label>Name<input class="input" name="name" maxlength="40" placeholder="My firework" value="${esc(ed.d.name || "")}"></label>
          <label class="check"><input type="checkbox" name="in_show" ${ed.d.in_show !== false ? "checked" : ""}> In the show</label>
          <div class="btn-row"><button class="btn primary" type="submit">${ed.id ? "Save changes" : "Save"}</button>
            ${ed.id ? `<button class="btn" type="button" id="fwe-saveas">Save as new</button>` : ""}
            <button class="btn" type="button" id="fwe-new">Start over</button></div>
          <p class="muted small" id="fwe-editing">${ed.id ? `Editing a saved firework.` : "Not saved yet."}</p>
        </form>
        <section class="fwe-gallery"><div class="section-head"><h2>Saved fireworks</h2><span class="muted">${ed.list.length}</span></div><div id="fwe-list"></div></section>
      </div>
      <div class="fwe-controls" id="fwe-controls"></div>
    </div>`);
  ed.scene?.stop();
  ed.scene = startSkyScene($("#fwe-sky"), { fit: true, auto: false });
  document.body.classList.add("on-editor");
  state.cleanups.push(() => { ed.scene?.stop(); ed.scene = null; document.body.classList.remove("on-editor"); });
  renderControls();
  renderGallery();
  $("#fwe-launch").addEventListener("click", () => fweLaunch());
  $("#fwe-loop").addEventListener("change", (e) => { ed.loop = e.target.checked; });
  $("#fwe-surprise").addEventListener("click", () => { ed.d = { ...fweSurprise(), name: ed.d.name, in_show: ed.d.in_show }; ed.grids = {}; ed.frame = 1; renderControls(); fweLaunch(); });
  $("#fwe-new").addEventListener("click", () => { ed.d = fweCopy(FWE_DEFAULT); ed.id = null; ed.grids = {}; ed.frame = 1; location.hash = "#/fireworks"; viewFireworkEditor(); });
  $("#fwe-saveas")?.addEventListener("click", () => fweSave(true));
  $("#fwe-save").addEventListener("submit", (e) => { e.preventDefault(); fweSave(false); });
  $("#fwe-save").addEventListener("input", (e) => {
    if (e.target.name === "name") ed.d.name = e.target.value;
    if (e.target.name === "in_show") ed.d.in_show = e.target.checked;
  });
  every(2800, () => { if (ed.loop && !document.hidden) fweLaunch(); });
  setTimeout(() => fweLaunch(), 400);
}

function fweLaunch(d = ed.d) { ed.scene?.launchDesign(fweCopy(d)); }
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
  el.innerHTML = `
    ${sec("Launch", `<div class="fwe-patterns fwe-launches">${FWE_LAUNCHES.map(([k, l, ic]) => `<button type="button" data-launch="${k}" aria-pressed="${(d.launch || "rocket") === k}"><span>${ic}</span>${l}</button>`).join("")}</div>
      ${isRocket(d) ? `<div class="seg fwe-styles" role="group" aria-label="Rocket style">${FWE_STYLES.map(([k, l]) => `<button type="button" data-style="${k}" aria-pressed="${(d.rocket_style || "normal") === k}">${l}</button>`).join("")}</div>` : ""}
      <label class="check"><input type="checkbox" id="fwe-mirror-pair" ${d.mirror ? "checked" : ""}> Mirror pair: a matching one from the other side</label>
      ${sliders("Launch")}`)}
    ${isRocket(d) ? sec("Pattern", `<div class="fwe-patterns">${FWE_PATTERNS.map(([k, l, ic]) => `<button type="button" data-pattern="${k}" aria-pressed="${d.pattern === k}"><span>${ic}</span>${l}</button>`).join("")}</div>
      ${d.pattern === "picture" ? painterHtml() : ""}${sliders("Shape")}${d.pattern === "picture" ? sliders("Picture") : ""}`) : ""}
    ${sec("Colours", `${colorsHtml(d.colors, "ci")}
      <div class="fwe-dyes">${FW_COLORS.map((c) => `<button type="button" class="fw-swatch sm" data-dye="${c}" style="--c:${c}" aria-pressed="true" aria-label="Use ${c}"></button>`).join("")}</div>
      <div class="seg fwe-modes" role="group" aria-label="Colour style">${FWE_MODES.map(([k, l]) => `<button type="button" data-mode="${k}" aria-pressed="${d.color_mode === k}">${l}</button>`).join("")}</div>
      <p class="muted small">${{ mix: "Each piece picks one of your colours.", alternate: "Pieces go through your colours in order.", change: "Every piece changes from the first colour to the last as it fades.", rainbow: "Every colour of the rainbow, cycling as it falls." }[d.color_mode]}</p>`)}
    ${isRocket(d) ? sec("Then…", stagesHtml(d), "fwe-stages") : ""}
    ${sec("Motion", sliders("Motion"))}
    ${sec("Effects", sliders("Effects"))}`;
  if (isRocket(d) && d.pattern === "picture") wirePainter();
  const rerender = (launchNow = true) => { renderControls(); if (launchNow) fweLaunch(); };
  el.querySelectorAll("[data-launch]").forEach((b) => b.addEventListener("click", () => { d.launch = b.dataset.launch; rerender(); }));
  el.querySelectorAll("[data-style]").forEach((b) => b.addEventListener("click", () => { d.rocket_style = b.dataset.style; rerender(); }));
  $("#fwe-mirror-pair", el).addEventListener("change", (e) => { d.mirror = e.target.checked; fweLaunch(); });
  el.querySelectorAll("[data-pattern]").forEach((b) => b.addEventListener("click", () => {
    d.pattern = b.dataset.pattern;
    if (d.pattern === "picture" && !d.picture?.length) { ed.frame = 1; stampPicture("Heart"); }
    rerender();
  }));
  el.querySelectorAll("input[type=range]").forEach((inp) => inp.addEventListener("input", () => {
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
    <div class="fwe-tools">${brushes}<button type="button" class="fwe-brush eraser" data-brush="." aria-pressed="${ed.brush === "."}" aria-label="Eraser">⌫</button>
      <label class="check"><input type="checkbox" id="fwe-mirror" ${ed.mirror ? "checked" : ""}> Mirror</label>
      <button type="button" class="btn sm" id="fwe-clear">Clear</button></div>
    <div class="fwe-grid" id="fwe-grid" style="--n:${FWE_GRID}">${Array.from({ length: FWE_GRID * FWE_GRID }, (_, i) => `<span data-cell="${i}"></span>`).join("")}</div>
    <div class="fwe-stamps"><span class="muted small">Stamps:</span>${Object.keys(FWE_STAMPS).map((k) => `<button type="button" class="btn sm" data-stamp="${k}">${k}</button>`).join("")}</div>
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
  $$(".fwe-brush").forEach((b) => b.addEventListener("click", () => { ed.brush = b.dataset.brush; $$(".fwe-brush").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); }));
  $("#fwe-mirror").addEventListener("change", (e) => { ed.mirror = e.target.checked; });
  $("#fwe-clear").addEventListener("click", () => { fweSetPicture(Array.from({ length: FWE_GRID }, () => new Array(FWE_GRID).fill("."))); refreshCells(); fweChanged(); });
  $$("[data-stamp]").forEach((b) => b.addEventListener("click", () => { stampPicture(b.dataset.stamp); refreshCells(); fweLaunch(); }));
  $$("[data-frame]").forEach((b) => b.addEventListener("click", () => { ed.frame = +b.dataset.frame; renderControls(); }));
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
    ed.id = saved.id; ed.d = { ...fweCopy(FWE_DEFAULT), ...saved };
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
function renderGallery() {
  const el = $("#fwe-list");
  if (!el) return;
  const label = Object.fromEntries(FWE_PATTERNS.map(([k, l, ic]) => [k, `${ic} ${l}`]));
  el.innerHTML = ed.list.length ? ed.list.slice().reverse().map((f) => `<div class="fwe-card ${f.id === ed.id ? "current" : ""}" data-id="${f.id}">
      <div class="fwe-card-main"><b>${esc(f.name)}</b><span class="muted small">${esc(f.launch && f.launch !== "rocket" ? (FWE_LAUNCHES.find(([k]) => k === f.launch) || [])[1] || "" : label[f.pattern] || f.pattern)} · by ${esc(f.author)}</span>
        <span class="fwe-dots">${f.colors.map((c) => `<i style="background:${c}"></i>`).join("")}</span></div>
      <div class="fwe-card-acts">
        <button type="button" class="icon-btn" data-act="play" title="Launch it" aria-label="Launch ${esc(f.name)}">▶</button>
        ${f.can_edit ? `<label class="check small" title="Include in the fireworks show"><input type="checkbox" data-act="show" ${f.in_show ? "checked" : ""}> Show</label>
          <a class="btn sm" href="#/fireworks/${f.id}">Edit</a>` : `<button type="button" class="btn sm" data-act="copy">Copy</button>`}
        ${f.can_edit ? `<button type="button" class="btn sm danger" data-act="del" aria-label="Delete ${esc(f.name)}">Delete</button>` : ""}
      </div></div>`).join("")
    : `<p class="muted">Nothing saved yet. Make something and press Save.</p>`;
  el.querySelectorAll(".fwe-card").forEach((card) => {
    const f = ed.list.find((x) => x.id === card.dataset.id);
    card.querySelector('[data-act="play"]').addEventListener("click", () => fweLaunch({ ...FWE_DEFAULT, ...f }));
    card.querySelector('[data-act="copy"]')?.addEventListener("click", () => {
      ed.d = { ...fweCopy(FWE_DEFAULT), ...fweCopy(f), name: `${f.name} (copy)` }; ed.id = null; ed.grids = {}; ed.frame = 1;
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
        if (ed.id === f.id) { ed.id = null; }
        await fweRefresh();
      } catch (err) { showToast(esc(err.message), 4000); }
    });
  });
}
