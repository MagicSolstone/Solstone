/* Solstone — Firework editor: design your own fireworks with sliders and a pixel painter,
   watch them in a live preview sky, and save them into the show. Anyone signed in can make
   fireworks; people can change their own, and admins can change anyone's.
   Loaded after app.js and sky.js. */
"use strict";

const FWE_GRID = 25;
const FWE_DEFAULT = {
  name: "", pattern: "ball", color_mode: "mix", colors: ["#ffe45c", "#ff5a4f"], picture: [],
  sparks: 48, size: 1.2, spread: 0.15, squash: 1, tilt: 0.3, points: 5, arms: 3, spin: 0.5,
  gravity: 1, drag: 0.4, life: 1.4, height: 0.6, rockets: 1, hold: 0.8,
  sparkle: 0, trail: 0, glitter: 0, flash: 0.4, blink: 0, strobe: 0, breathe: 0,
  second: 0, second_delay: 0.5, second_size: 0.6, in_show: true,
};
const FWE_PATTERNS = [
  ["ball", "Ball", "●"], ["ring", "Ring", "◯"], ["star", "Star", "★"], ["burst", "Burst", "✳"],
  ["spiral", "Spiral", "🌀"], ["palm", "Palm", "🌴"], ["picture", "Picture", "🎨"],
];
const pct = (v) => `${Math.round(v * 100)}%`;
const off0 = (v) => (v === 0 ? "Off" : pct(v));
// [key, label, min, max, step, format, only for these patterns]
const FWE_SLIDERS = {
  Shape: [
    ["sparks", "Pieces", 8, 160, 1, (v) => v, ["ball", "ring", "star", "burst", "spiral", "palm"]],
    ["size", "Size", 0.3, 3, 0.05, (v) => `×${v.toFixed(2)}`],
    ["spread", "Messiness", 0, 1, 0.05, pct, ["ball", "ring", "star", "palm"]],
    ["squash", "Squash and stretch", 0.3, 1.5, 0.05, (v) => (v < 1 ? `flatter ${pct(1 - v)}` : v > 1 ? `taller ${pct(v - 1)}` : "round"), ["ball", "ring", "star", "burst", "palm"]],
    ["tilt", "Random tilt", 0, 1, 0.05, pct, ["ring", "star", "picture"]],
    ["points", "Star points", 3, 10, 1, (v) => v, ["star"]],
    ["arms", "Spiral arms", 2, 6, 1, (v) => v, ["spiral"]],
    ["spin", "Spin", -1, 1, 0.05, (v) => (v === 0 ? "none" : `${v < 0 ? "left" : "right"} ${pct(Math.abs(v))}`), ["spiral"]],
    ["hold", "Hold the picture", 0, 3, 0.1, (v) => `${v.toFixed(1)} s`, ["picture"]],
  ],
  Motion: [
    ["height", "Rocket height", 0.1, 1, 0.05, pct],
    ["rockets", "Rockets at once", 1, 5, 1, (v) => v],
    ["gravity", "Gravity", 0, 2, 0.05, (v) => (v === 0 ? "floating" : `×${v.toFixed(2)}`)],
    ["drag", "Air resistance", 0, 1, 0.05, pct],
    ["life", "Fade time", 0.4, 6, 0.1, (v) => `${v.toFixed(1)} s`],
  ],
  Effects: [
    ["flash", "Flash", 0, 1, 0.05, off0],
    ["sparkle", "Crackle", 0, 1, 0.05, off0],
    ["trail", "Trails", 0, 1, 0.05, off0],
    ["glitter", "Falling glitter", 0, 1, 0.05, off0],
    ["blink", "Blink", 0, 1, 0.05, (v) => (v === 0 ? "Off" : v < 0.4 ? "slow" : v < 0.75 ? "medium" : "fast")],
    ["strobe", "Strobe", 0, 1, 0.05, off0],
    ["breathe", "Breathe", 0, 1, 0.05, off0],
    ["second", "Burst again", 0, 1, 0.05, (v) => (v === 0 ? "Off" : `${pct(v)} of pieces`)],
    ["second_delay", "…after", 0.2, 1.5, 0.05, (v) => `${v.toFixed(2)} s`],
    ["second_size", "…size", 0.2, 1.5, 0.05, (v) => `×${v.toFixed(2)}`],
  ],
};
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

const ed = { d: null, id: null, list: [], scene: null, loop: true, debounce: 0, brush: "0", mirror: true, painting: false };

function fweCopy(d) { return JSON.parse(JSON.stringify(d)); }
// The painter works on a full 25×25 grid; the saved picture is trimmed to what's painted.
function fwePicture() {
  const rows = ed.d.picture?.length ? ed.d.picture : [];
  const grid = Array.from({ length: FWE_GRID }, () => new Array(FWE_GRID).fill("."));
  const h = rows.length, w = Math.max(0, ...rows.map((r) => r.length));
  const oy = Math.floor((FWE_GRID - h) / 2), ox = Math.floor((FWE_GRID - w) / 2);
  rows.forEach((r, y) => [...r].forEach((c, x) => { if (grid[oy + y]?.[ox + x] !== undefined) grid[oy + y][ox + x] = c; }));
  return grid;
}
function fweSetPicture(grid) {
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
  ed.d.picture = rows;
  ed.grid = grid;
}

async function viewFireworkEditor(editId) {
  curSid = null;
  document.title = "Firework editor · Solstone";
  $("#rail-servers").innerHTML = railHtml(null);
  ed.list = await api("/api/fireworks").catch(() => []);
  const found = editId && ed.list.find((x) => x.id === editId && x.can_edit);
  ed.d = found ? { ...fweCopy(FWE_DEFAULT), ...fweCopy(found) } : ed.d && !editId ? ed.d : fweCopy(FWE_DEFAULT);
  ed.id = found ? found.id : editId ? null : ed.id;
  ed.grid = null;
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
  $("#fwe-surprise").addEventListener("click", () => { ed.d = { ...fweSurprise(), name: ed.d.name, in_show: ed.d.in_show }; ed.grid = null; renderControls(); fweLaunch(); });
  $("#fwe-new").addEventListener("click", () => { ed.d = fweCopy(FWE_DEFAULT); ed.id = null; ed.grid = null; location.hash = "#/fireworks"; viewFireworkEditor(); });
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
function renderControls() {
  const d = ed.d, el = $("#fwe-controls");
  const slider = ([k, label, min, max, step, fmt, only]) => only && !only.includes(d.pattern) ? "" : `
    <label class="fwe-slider"><span>${esc(label)}</span><b data-out="${k}">${esc(String(fmt(+d[k])))}</b>
      <input type="range" min="${min}" max="${max}" step="${step}" value="${d[k]}" data-k="${k}"></label>`;
  el.innerHTML = `
    <section class="panel fwe-sec"><h3>Pattern</h3>
      <div class="fwe-patterns">${FWE_PATTERNS.map(([k, l, ic]) => `<button type="button" data-pattern="${k}" aria-pressed="${d.pattern === k}"><span>${ic}</span>${l}</button>`).join("")}</div>
      ${d.pattern === "picture" ? painterHtml() : ""}
    </section>
    <section class="panel fwe-sec"><h3>Colours</h3>
      <div class="fwe-colors">${d.colors.map((c, i) => `<span class="fwe-color"><input type="color" value="${c}" data-ci="${i}" aria-label="Colour ${i + 1}">
        ${d.colors.length > 1 ? `<button type="button" class="chip-x" data-rmc="${i}" aria-label="Remove colour ${i + 1}">×</button>` : ""}</span>`).join("")}
        ${d.colors.length < 4 ? `<button type="button" class="btn sm" id="fwe-addc">+ Colour</button>` : ""}</div>
      <div class="fwe-dyes">${FW_COLORS.map((c) => `<button type="button" class="fw-swatch sm" data-dye="${c}" style="--c:${c}" aria-pressed="true" aria-label="Use ${c}"></button>`).join("")}</div>
      <div class="seg fwe-modes" role="group" aria-label="Colour style">${FWE_MODES.map(([k, l]) => `<button type="button" data-mode="${k}" aria-pressed="${d.color_mode === k}">${l}</button>`).join("")}</div>
      <p class="muted small">${{ mix: "Each piece picks one of your colours.", alternate: "Pieces go through your colours in order.", change: "Every piece changes from the first colour to the last as it fades.", rainbow: "Every colour of the rainbow, cycling as it falls." }[d.color_mode]}</p>
    </section>
    ${Object.entries(FWE_SLIDERS).map(([title, list]) => `<section class="panel fwe-sec"><h3>${title}</h3><div class="fwe-sliders">${list.map(slider).join("")}</div></section>`).join("")}`;
  if (d.pattern === "picture") wirePainter();
  el.querySelectorAll("[data-pattern]").forEach((b) => b.addEventListener("click", () => {
    d.pattern = b.dataset.pattern;
    if (d.pattern === "picture" && !d.picture?.length) { stampPicture("Heart"); }
    renderControls(); fweLaunch();
  }));
  el.querySelectorAll("input[type=range]").forEach((inp) => inp.addEventListener("input", () => {
    const k = inp.dataset.k, def = Object.values(FWE_SLIDERS).flat().find((s) => s[0] === k);
    d[k] = +inp.value;
    el.querySelector(`[data-out="${k}"]`).textContent = def[5](+inp.value);
    fweChanged();
  }));
  el.querySelectorAll("input[type=color]").forEach((inp) => inp.addEventListener("input", () => { d.colors[+inp.dataset.ci] = inp.value; refreshCells(); fweChanged(); }));
  el.querySelectorAll("[data-rmc]").forEach((b) => b.addEventListener("click", () => { d.colors.splice(+b.dataset.rmc, 1); renderControls(); fweChanged(); }));
  $("#fwe-addc", el)?.addEventListener("click", () => { d.colors.push(pick2(FW_COLORS)); renderControls(); fweChanged(); });
  el.querySelectorAll("[data-dye]").forEach((b) => b.addEventListener("click", () => {
    if (d.colors.length < 4) d.colors.push(b.dataset.dye); else d.colors[d.colors.length - 1] = b.dataset.dye;
    renderControls(); fweChanged();
  }));
  el.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => { d.color_mode = b.dataset.mode; renderControls(); fweLaunch(); }));
}
const pick2 = (a) => a[Math.floor(Math.random() * a.length)];

// ---------------------------------------------------------------- pixel painter
function painterHtml() {
  const brushes = ed.d.colors.map((c, i) => `<button type="button" class="fwe-brush" data-brush="${i}" aria-pressed="${ed.brush === String(i)}" style="--c:${c}" aria-label="Paint with colour ${i + 1}"></button>`).join("");
  return `<div class="fwe-painter">
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
  const grid = ed.grid || fwePicture();
  ed.grid = grid;
  g.querySelectorAll("[data-cell]").forEach((cell) => {
    const i = +cell.dataset.cell, v = grid[Math.floor(i / FWE_GRID)][i % FWE_GRID];
    cell.style.background = v === "." ? "" : ed.d.colors[+v] || ed.d.colors[0];
    cell.classList.toggle("on", v !== ".");
  });
  $$(".fwe-brush[data-brush]").forEach((b) => { if (b.dataset.brush !== ".") b.style.setProperty("--c", ed.d.colors[+b.dataset.brush] || "#000"); });
}
function wirePainter() {
  ed.grid ||= fwePicture();
  refreshCells();
  const g = $("#fwe-grid");
  const paintAt = (cell) => {
    if (!cell?.dataset?.cell) return;
    const i = +cell.dataset.cell, y = Math.floor(i / FWE_GRID), x = i % FWE_GRID;
    const v = ed.brush === "." ? "." : String(Math.min(+ed.brush, ed.d.colors.length - 1));
    ed.grid[y][x] = v;
    if (ed.mirror) ed.grid[y][FWE_GRID - 1 - x] = v;
    fweSetPicture(ed.grid);
    refreshCells();
  };
  g.addEventListener("pointerdown", (e) => { ed.painting = true; g.setPointerCapture(e.pointerId); paintAt(e.target.closest("[data-cell]")); e.preventDefault(); });
  g.addEventListener("pointermove", (e) => { if (ed.painting) paintAt(document.elementFromPoint(e.clientX, e.clientY)?.closest?.("[data-cell]")); });
  const stop = () => { if (ed.painting) { ed.painting = false; fweChanged(); } };
  g.addEventListener("pointerup", stop);
  g.addEventListener("pointercancel", stop);
  $$(".fwe-brush").forEach((b) => b.addEventListener("click", () => { ed.brush = b.dataset.brush; $$(".fwe-brush").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); }));
  $("#fwe-mirror").addEventListener("change", (e) => { ed.mirror = e.target.checked; });
  $("#fwe-clear").addEventListener("click", () => { fweSetPicture(Array.from({ length: FWE_GRID }, () => new Array(FWE_GRID).fill("."))); refreshCells(); });
  $$("[data-stamp]").forEach((b) => b.addEventListener("click", () => { stampPicture(b.dataset.stamp); refreshCells(); fweLaunch(); }));
}

// ---------------------------------------------------------------- surprise me
function fweSurprise() {
  const r = (a, b) => a + Math.random() * (b - a), chance = (p) => Math.random() < p;
  const pattern = pick2(["ball", "ball", "ring", "star", "burst", "spiral", "palm", "picture"]);
  const colors = [...new Set(Array.from({ length: 1 + Math.floor(Math.random() * 3) }, () => pick2(FW_COLORS)))];
  const d = {
    ...fweCopy(FWE_DEFAULT), pattern, colors, color_mode: pick2(["mix", "mix", "alternate", "change", "rainbow"]),
    sparks: Math.round(r(24, 110)), size: +r(0.8, 2.2).toFixed(2), spread: +r(0, 0.4).toFixed(2), squash: chance(0.25) ? +r(0.5, 1.4).toFixed(2) : 1,
    tilt: +r(0, 0.8).toFixed(2), points: Math.round(r(4, 8)), arms: Math.round(r(2, 5)), spin: +r(-1, 1).toFixed(2),
    gravity: +r(0.3, 1.5).toFixed(2), drag: +r(0.1, 0.7).toFixed(2), life: +r(0.9, 3.2).toFixed(1), height: +r(0.4, 0.9).toFixed(2),
    rockets: chance(0.2) ? Math.round(r(2, 4)) : 1, hold: +r(0.5, 1.6).toFixed(1),
    sparkle: chance(0.35) ? +r(0.2, 0.8).toFixed(2) : 0, trail: chance(0.35) ? +r(0.3, 0.9).toFixed(2) : 0,
    glitter: chance(0.25) ? +r(0.3, 0.9).toFixed(2) : 0, flash: +r(0, 0.8).toFixed(2),
    blink: chance(0.15) ? +r(0.2, 0.9).toFixed(2) : 0, strobe: chance(0.12) ? +r(0.2, 0.7).toFixed(2) : 0,
    breathe: chance(0.15) ? +r(0.3, 0.9).toFixed(2) : 0, second: chance(0.25) ? +r(0.2, 0.7).toFixed(2) : 0,
    second_delay: +r(0.3, 0.9).toFixed(2), second_size: +r(0.4, 1).toFixed(2),
  };
  if (pattern === "picture") { ed.d = d; stampPicture(pick2(Object.keys(FWE_STAMPS))); return ed.d; }
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
      <div class="fwe-card-main"><b>${esc(f.name)}</b><span class="muted small">${esc(label[f.pattern] || f.pattern)} · by ${esc(f.author)}</span>
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
      ed.d = { ...fweCopy(FWE_DEFAULT), ...fweCopy(f), name: `${f.name} (copy)` }; ed.id = null; ed.grid = null;
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
