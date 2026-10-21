/* Solstone — the pixel night sky shared by every page: twinkling stars, a dark blocky
   hill with a small figure and their dog watching, and Minecraft-style fireworks. */
"use strict";

// Minecraft dye colours, brightened the way firework stars look in-game.
const FW_COLORS = ["#ff5a4f", "#ffa13d", "#ffe45c", "#9be34a", "#4fd7e6", "#5d8bff", "#c46cf0", "#ff8fc0", "#ffffff", "#3fd1b0"];
const FW_SHAPES = ["ball", "ball", "large", "star", "burst", "ring", "cube", "pickaxe", "axe", "creeper", "heart",
  "crossette", "crossette", "spiral", "spiral", "willow", "willow", "saturn", "pair", "candle", "cake", "fountain", "wheel",
  "sparkler", "shootingstar"];
// Show-pieces: rarer, and only one on screen at a time so the sky never gets cluttered.
const FW_SPECIALS = ["dragon", "bow", "tree"];
const FW_PACE = { calm: [2600, 6500], normal: [700, 1900], lively: [350, 1000] };
const FW_SPECIAL_CHANCE = { rare: 0.05, sometimes: 0.1, often: 0.22 };
// Admin settings (Users & activity → Fireworks), shared by every page. Defaults until loaded.
const FW = { kinds: null, colors: FW_COLORS, pace: "normal", showpieces: "sometimes", custom: [] };
let fwLoaded = null;
function loadFireworkSettings() {
  fwLoaded ||= fetch("/api/public/fireworks").then((r) => r.ok ? r.json() : null).then((c) => { if (c) applyFireworkSettings(c); }).catch(() => {});
  return fwLoaded;
}
function applyFireworkSettings(c) {
  FW.kinds = c.kinds || null;
  FW.weights = c.weights || null;
  FW.colors = c.colors?.length ? c.colors : FW_COLORS;
  FW.pace = FW_PACE[c.pace] ? c.pace : "normal";
  FW.showpieces = FW_SPECIAL_CHANCE[c.showpieces] != null ? c.showpieces : "sometimes";
  FW.custom = Array.isArray(c.custom) ? c.custom : [];
  FW.theme = c.theme || null;
  FW.finales = Array.isArray(c.finales) ? c.finales : [];
  FW.music = !!c.music;
  FW.base_shows = c.base_shows || null;
  FW.sky = c.sky || { mode: "game", daytime: "smoke" };
}
// How often each kind comes up (admin settings): 0 off, 0.5 rare, 1 normal, 2 often, 4 lots.
const fwWeight = (k) => FW.weights ? (FW.weights[k] ?? 1) : FW.kinds && FW.kinds[k] === false ? 0 : 1;
const fwOn = (k) => fwWeight(k) > 0;
function pickWeighted(list) {
  const total = list.reduce((a, [, w]) => a + w, 0);
  let r = Math.random() * total;
  for (const [item, w] of list) { r -= w; if (r <= 0) return item; }
  return list.length ? list[list.length - 1][0] : null;
}
// On a holiday the calendar's colours replace the usual ones and its favourite kinds come up more.
const fwPalette = () => (FW.theme?.colors?.length ? FW.theme.colors : FW.colors);
// Pixel templates for shaped bursts: each "#" becomes a spark that flies out to its spot.
const FW_TEMPLATES = {
  cube: [
    "......#......",
    "....##.##....",
    "..##.....##..",
    "##.........##",
    "#.##.....##.#",
    "#...##.##...#",
    "#.....#.....#",
    "#.....#.....#",
    "#.....#.....#",
    "##....#....##",
    "..##..#..##..",
    "....##.##....",
    "......#......",
  ],
  pickaxe: [
    "...#######...",
    ".##...#...##.",
    "#.....#.....#",
    "......#......",
    "......#......",
    "......#......",
    "......#......",
    "......#......",
    "......#......",
    "......#......",
  ],
  creeper: [
    "########",
    "########",
    "#..##..#",
    "#..##..#",
    "###..###",
    "##....##",
    "##....##",
    "##.##.##",
  ],
  heart: [
    ".##...##.",
    "####.####",
    "#########",
    "#########",
    ".#######.",
    "..#####..",
    "...###...",
    "....#....",
  ],
  axe: [
    "....##.",
    "..####.",
    ".######",
    "#######",
    "#######",
    ".######",
    "..####.",
    "....##.",
    ".....#.",
    ".....#.",
    ".....#.",
    ".....#.",
    ".....#.",
  ],
};

// Pixel figures that appear, move as one piece, then shatter into sparks. Letters pick
// the colour from the figure's palette; "." is empty. Frames alternate (wing flaps).
const FW_FIGURES = {
  dragon: {
    palette: { b: "#c46cf0", w: "#8f5ae0", e: "#ff9cf7" },
    frames: [[
      "..........w.....w.........",
      ".........ww....ww.........",
      "........www...www.........",
      ".......www...www......bb..",
      "......wwww..www.....bbbbbe",
      "b....bbbbbbbbbbbb...bbbbbb",
      ".bb.bbbbbbbbbbbbbbbbbb....",
      "...bb...b.....b...........",
      "........b.....b...........",
      "..........................",
      "..........................",
    ], [
      "..........................",
      "..........................",
      "..........................",
      ".....................bb...",
      "....................bbbbbe",
      "b....bbbbbbbbbbbb...bbbbbb",
      ".bb.bbbbbbbbbbbbbbbbbb....",
      "...bb..wwww..wwww.........",
      "........www...www.........",
      ".........ww....ww.........",
      "..........w.....w.........",
    ]],
  },
  bow: {
    palette: { s: "#f4f1e8", b: "#f0b35a" },
    frames: [[
      "sb.....", "s.b....", "s..b...", "s...b..", "s....b.", "s....b.", "s....b.",
      "s....b.", "s....b.", "s...b..", "s..b...", "s.b....", "sb.....",
    ]],
  },
  arrow: {
    palette: { f: "#ffffff", s: "#ffe45c", h: "#9fe8ff" },
    frames: [[
      "ff..........h..",
      ".fsssssssssshhh",
      "ff..........h..",
    ]],
  },
};

function startSkyScene(cv, opts = {}) {
  // opts.avoid: element to launch beside; opts.every: [min, max] ms between launches;
  // opts.auto: false starts with the automatic show off (launch() and setAuto() still work).
  const card = opts.avoid || null;
  const every = () => opts.every || FW_PACE[FW.pace];
  loadFireworkSettings();
  const ctx = cv.getContext("2d");
  const SCALE = 3;                                  // low-res canvas scaled up = crisp pixels
  const G = 0.03;                                   // gravity, low-res px per frame²
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  const rand = (a, b) => a + Math.random() * (b - a);
  let W = 0, H = 0, raf = 0, timer = 0, running = false, frame = 0, stopped = false;
  let stars = [], land = null, groundY = 0, cardBox = null, hill = [], watcher = { x: 0, y: 0 };
  const rockets = [], sparks = [], figures = [], trees = [];
  const SPARK_SOFT = 2200, SPARK_HARD = 3600;        // effects thin out past these
  // Sound: the page passes opts.sound(type, info); pan is -1 (left) to 1 (right).
  const snd = (type, info = {}) => { try { opts.sound?.(type, { ...info, pan: info.x != null && W ? Math.max(-1, Math.min(1, (info.x / W) * 2 - 1)) : 0 }); } catch { /* sound is optional */ } };
  let boostUntil = 0;                                // a scheduled show or event: lively for a while
  const boosting = () => performance.now() < boostUntil;

  // ---- static layer: blocky hill with two small silhouettes
  function buildLand() {
    land = document.createElement("canvas");
    land.width = W; land.height = H;
    const g = land.getContext("2d");
    const B = 3;                                    // block size in low-res px
    const sitX = Math.round(W * (W > 500 ? 0.16 : 0.2));
    const heights = [];
    for (let x = 0; x < W; x += B) {
      const t = x / W;
      const bump = Math.exp(-(((t - sitX / W) / 0.17) ** 2)) * 0.11 + Math.exp(-(((t - 0.86) / 0.12) ** 2)) * 0.07;
      const ripple = Math.sin(x * 0.09) * 0.006 + Math.sin(x * 0.031 + 1.3) * 0.01;
      heights.push(Math.round((H * (0.075 + bump + ripple)) / B) * B);
    }
    groundY = H - Math.max(...heights);
    hill = heights;
    const lc = landColors();
    heights.forEach((h, i) => {
      g.fillStyle = lc.ground; g.fillRect(i * B, H - h, B, h);
      g.fillStyle = lc.grass; g.fillRect(i * B, H - h, B, 1);    // a hint of grass on top
    });
    // Sitting figure and dog on the left hilltop, facing the sky. Pixel maps: # = filled.
    const top = H - heights[Math.floor(sitX / B)];
    // Standing, head tipped back to watch the sky.
    const person = ["....##.", "...##..", "...##..", "..####.", ".#.##.#", ".#.##.#", "...##..", "...#.#.", "...#.#.", "...#.#."];
    const dog = ["##.....", "###....", ".#...#.", ".#####.", ".#####.", ".#.#.#."];
    g.fillStyle = lc.figure;
    const draw = (map, ox, oy) => map.forEach((row, y) => [...row].forEach((c, x) => { if (c === "#") g.fillRect(ox + x, oy + y, 1, 1); }));
    draw(person, sitX - 5, top - person.length);
    watcher = { x: sitX - 5 + 7, y: top - person.length + 3 };      // just past the raised hand
    draw(dog, sitX + 5, top - dog.length);
  }

  function resize() {
    W = Math.ceil((opts.fit ? cv.clientWidth : innerWidth) / SCALE); H = Math.ceil((opts.fit ? cv.clientHeight : innerHeight) / SCALE);
    cv.width = W; cv.height = H;
    stars = Array.from({ length: Math.round((W * H) / 700) }, () => ({ x: Math.floor(Math.random() * W), y: Math.floor(Math.random() * H * 0.7), p: Math.random() * 6.28, a: rand(0.15, 0.55) }));
    buildLand();
    const r = card ? card.getBoundingClientRect() : null;
    cardBox = r ? { l: r.left / SCALE, r: r.right / SCALE, t: r.top / SCALE } : null;
  }

  // ---- the sky itself: always night, or following a Minecraft server's time and weather
  let gsky = null;               // {tod, ref, ticking, moon, raining, thundering}
  let landKey = "", flashA = 0, ambient = 0;
  const hexRgb = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const lerpC = (a, b, t) => { const x = hexRgb(a), y = hexRgb(b); return `#${x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("")}`; };
  function tod() {
    if (!gsky) return 18000;                          // midnight
    const secs = gsky.ticking ? (performance.now() - gsky.ref) / 1000 : 0;
    return (gsky.tod + secs * 20) % 24000;
  }
  // 0 = night, 1 = full day, with dawn and dusk in between (Minecraft's 0 is 6 am).
  function daylight(t = tod()) {
    if (t < 1000) return 0.55 + 0.45 * (t / 1000);
    if (t < 11500) return 1;
    if (t < 13000) return 1 - (t - 11500) / 1500;
    if (t < 22500) return 0;
    return 0.55 * ((t - 22500) / 1500);
  }
  function glow(t = tod()) {                         // warm sunrise/sunset colour
    const near = (c, w) => Math.max(0, 1 - Math.abs(t - c) / w);
    return Math.max(near(12500, 900), near(23700, 900), near(-300, 900));
  }
  const isDay = () => !!gsky && daylight() > 0.45;
  const rainAmt = () => (gsky?.raining ? (gsky.thundering ? 1 : 0.75) : 0);
  function landColors() {
    const d = gsky ? daylight() : 0, r = rainAmt();
    const ground = lerpC("#0d1014", "#26341f", d * (1 - r * 0.4)), grass = lerpC("#15211a", "#4f7a33", d * (1 - r * 0.4));
    return { ground, grass, figure: lerpC("#0d1014", "#1a2316", d) };
  }
  function skyColors() {
    const d = daylight(), g = glow(), r = rainAmt();
    let top = lerpC("#0a0e1c", "#4a7fe0", d), bottom = lerpC("#1d2233", "#a9ccf2", d);
    top = lerpC(top, "#2f3a78", g * 0.55); bottom = lerpC(bottom, "#f0905e", g * 0.75);
    if (r) { top = lerpC(top, d > 0.3 ? "#57606f" : "#121620", r * 0.7); bottom = lerpC(bottom, d > 0.3 ? "#8b95a3" : "#1c212c", r * 0.7); }
    return [top, bottom];
  }
  const CLOUDS = Array.from({ length: 9 }, (_, i) => ({ x: Math.random(), y: 0.06 + Math.random() * 0.24, w: 14 + Math.floor(Math.random() * 22), h: 3 + Math.floor(Math.random() * 3), sp: 0.6 + Math.random() * 0.8, seed: i }));
  function drawBackdrop() {
    if (!gsky) { ctx.clearRect(0, 0, W, H); return; }
    const [top, bottom] = skyColors();
    const grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, top); grad.addColorStop(1, bottom);
    ctx.fillStyle = grad; ctx.fillRect(0, 0, W, H);
    const t = tod(), d = daylight(), horizon = groundY + 6, arc = horizon - H * 0.08;
    // Sun by day, the moon (with Minecraft's eight phases) by night.
    if (t < 12600 || t > 23400) {
      const s = ((t + 600) % 24000) / 13200, x = W * (0.06 + 0.88 * s), y = horizon - Math.sin(Math.max(0, Math.min(1, s)) * Math.PI) * arc;
      ctx.globalAlpha = 0.35 * (1 - rainAmt() * 0.8); ctx.fillStyle = "#fff3b0"; ctx.fillRect(Math.round(x) - 6, Math.round(y) - 6, 12, 12);
      ctx.globalAlpha = 1 - rainAmt() * 0.7; ctx.fillStyle = "#fff7c8"; ctx.fillRect(Math.round(x) - 4, Math.round(y) - 4, 8, 8);
      ctx.fillStyle = "#ffffff"; ctx.fillRect(Math.round(x) - 2, Math.round(y) - 2, 4, 4);
    }
    if (t > 11800 && t < 24000) {
      const s = (t - 11800) / 12200, x = W * (0.06 + 0.88 * s), y = horizon - Math.sin(s * Math.PI) * arc;
      const phase = gsky.moon || 0, lit = [7, 5, 4, 2, 0, 2, 4, 5][phase], fromLeft = phase > 0 && phase < 4;
      ctx.globalAlpha = (1 - d) * (1 - rainAmt() * 0.7);
      for (let cx = 0; cx < 7; cx++) {
        const on = fromLeft ? cx < lit : cx >= 7 - lit;
        ctx.fillStyle = on ? "#e8edf7" : "#3a4256";
        ctx.fillRect(Math.round(x) - 3 + cx, Math.round(y) - 3, 1, 7);
      }
      if (lit > 3) { ctx.fillStyle = "#c3cbdd"; ctx.fillRect(Math.round(x) - 1 + (fromLeft ? -1 : 1), Math.round(y) - 1, 2, 2); }
      ctx.globalAlpha = 1;
    }
    // Blocky clouds drift with real time (so they keep moving even when nothing else does).
    const now = performance.now() / 1000, r = rainAmt();
    const n = r ? CLOUDS.length : Math.round(4 + 3 * d);
    for (let i = 0; i < n; i++) {
      const c = CLOUDS[i], cx = ((c.x * (W + 80) + now * c.sp) % (W + 80)) - 40, cy = Math.round(c.y * H);
      ctx.globalAlpha = (0.15 + 0.7 * d) * (r ? 0.9 : 0.75);
      ctx.fillStyle = r ? lerpC("#3a414d", "#c9ced6", d * 0.6) : lerpC("#2a3142", "#ffffff", d);
      ctx.fillRect(Math.round(cx), cy, c.w, c.h);
      ctx.fillRect(Math.round(cx) + 3, cy - 2, c.w - 8, 2);
    }
    ctx.globalAlpha = 1;
  }
  function drawWeather() {
    const r = rainAmt();
    if (!r) return;
    const now = performance.now() / 1000, n = Math.round((W * H) / 900 * r);
    ctx.fillStyle = "rgba(175, 195, 235, 0.55)";
    for (let i = 0; i < n; i++) {
      const hx = (Math.sin(i * 91.7) * 43758.5) % 1, hy = (Math.sin(i * 12.9) * 78233.1) % 1;
      const y = ((Math.abs(hy) * (H + 20) + now * (140 + (i % 5) * 18)) % (H + 20)) - 10;
      const x = (Math.abs(hx) * (W + 40) - y * 0.18 + now * 4) % (W + 40);
      ctx.fillRect(Math.round(x), Math.round(y), 1, 3);
    }
    if (gsky.thundering && Math.random() < 0.0025) { flashA = 0.55; snd("thunder", { x: Math.random() * W }); }
    if (flashA > 0) { ctx.fillStyle = `rgba(230, 236, 255, ${flashA})`; ctx.fillRect(0, 0, W, H); flashA -= 0.04; }
  }
  function refreshLand() {
    const key = gsky ? `${Math.round(daylight() * 8)}-${rainAmt()}` : "night";
    if (key !== landKey) { landKey = key; buildLand(); }
  }
  // Ambient motion (clouds, rain) when the firework loop is asleep: a gentle redraw.
  function ambientTick() {
    clearTimeout(ambient);
    if (stopped) return;
    if (gsky && !running && !document.hidden) step();
    ambient = setTimeout(ambientTick, rainAmt() ? 50 : gsky ? 400 : 2000);
  }

  // ---- daytime fireworks: coloured smoke, the way real daytime fireworks look
  function smoke(x, y, colors, size = 1) {
    if (!isDay() || FW.sky?.daytime !== "smoke" || sparks.length > SPARK_SOFT) return;
    const n = Math.round(10 + size * 6);
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2, sp = rand(0.25, 0.7) * size;
      sparks.push({ x, y, px: x, py: y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 0, max: rand(160, 260), puff: true,
        color: lerpC(pick(colors || ["#ffffff"]), "#9aa3b2", 0.35), r0: rand(1.5, 3) });
    }
  }

  // ---- fireworks
  function launch(shape, at) {
    // Favour the open sky beside the sign-in card so most bursts are visible.
    let x;
    const sides = cardBox ? [[W * 0.06, cardBox.l - 10], [cardBox.r + 10, W * 0.94]].filter(([a, b]) => b - a > 20) : [];
    if (at) x = at.x;
    else if (sides.length && Math.random() < 0.8) { const [a, b] = pick(sides); x = rand(a, b); } else x = rand(W * 0.1, W * 0.9);
    if (!shape) {
      const busy = figures.length || trees.length || rockets.some((r) => FW_SPECIALS.includes(r.shape));
      // Holiday favourites count extra; editor fireworks carry their own weight.
      const themed = (FW.theme?.kinds || []).flatMap((k) => k.startsWith("custom:") ? FW.custom.filter((d) => `custom:${d.id}` === k).map((d) => [d, 2]) : [[k, 2]]);
      const regular = [...[...new Set(FW_SHAPES)].map((k) => [k, fwWeight(k)]), ...FW.custom.map((d) => [d, d.weight ?? 1]),
        ...themed.filter(([k]) => typeof k !== "string" || !FW_SPECIALS.includes(k))].filter(([, w]) => w > 0);
      const special = [...FW_SPECIALS.map((k) => [k, fwWeight(k)]), ...themed.filter(([k]) => FW_SPECIALS.includes(k))].filter(([, w]) => w > 0);
      const wantSpecial = special.length && !busy && (Math.random() < FW_SPECIAL_CHANCE[FW.showpieces] || !regular.length);
      if (wantSpecial) shape = pickWeighted(special);
      else if (regular.length) shape = pickWeighted(regular);
      else return null;                            // only show-pieces are on, and one is already up
    }
    if (shape && typeof shape === "object") return launchDesign(shape, at?.x);
    if (shape === "sparkler") {
      if (emitters.some((e) => e.kind === "sparkler")) shape = "ball";
      else return addEmitter("sparkler", { duration: rand(5, 8) }, watcher.x);
    }
    if (shape === "shootingstar") {
      const left = Math.random() < 0.5;
      return addEmitter("comet", { duration: 4 }, left ? rand(-10, W * 0.3) : rand(W * 0.7, W + 10), { y: rand(2, H * 0.25), vx: (left ? 1 : -1) * rand(2.2, 3.4), vy: rand(0.5, 1.1) });
    }
    if (shape === "pair") {                         // the same firework from both sides at once
      const base = pick(["ball", "large", "star", "ring", "crossette", "willow", "spiral", "heart"]);
      const px = rand(W * 0.1, W * 0.35), apex = rand(H * 0.12, Math.min(H * 0.4, groundY - 40));
      const a1 = launch(base, { x: px, y: apex }), a2 = launch(base, { x: W - px, y: apex });
      if (a1 && a2) { a2.colors = a1.colors; a2.fade = a1.fade; a2.trail = a1.trail; a2.twinkle = a1.twinkle; }
      return a1;
    }
    const preset = builtinDesign(shape);
    if (preset) return launchDesign(preset, preset.launch ? undefined : x);
    if (FW_SPECIALS.includes(shape) && !(at?.x != null && at.y == null && at.keepX)) x = Math.max(W * 0.18, Math.min(W * 0.82, x));
    // A tree bursts low, just above the hill, and grows upwards from there.
    // A tree's rocket comes up out of the hill itself and bursts right at the surface.
    const surface = hill.length ? H - hill[Math.max(0, Math.min(hill.length - 1, Math.floor(x / 3)))] : groundY;
    const apex = at?.y != null ? at.y : shape === "tree" ? surface - 2 : rand(H * 0.1, Math.min(H * 0.45, groundY - 40));
    const startY = shape === "tree" ? H + 2 : groundY + 4;
    const vy = -Math.sqrt(2 * G * Math.max(1, startY - apex));
    const colors = [pick(fwPalette())];
    if (Math.random() < 0.45 || shape === "crossette") colors.push(pick(fwPalette()));
    if (shape === "willow" && Math.random() < 0.6) colors[0] = pick(["#ffcf5a", "#ffe9a8", "#ffb347"]);   // classic gold
    const r = { x, y: startY, vx: at?.y != null ? 0 : rand(-0.12, 0.12), vy, shape, colors, target: at?.target || null,
      fade: Math.random() < 0.35 ? pick(fwPalette()) : null, trail: Math.random() < 0.4, twinkle: Math.random() < 0.35 };
    if (shape === "dud") { r.vy *= 0.55; r.dud = true; r.colors = ["#8a8f98"]; }
    if (shape === "creeper") r.colors = ["#7dff5c", "#5fe04a"];
    if (!at?.quiet) snd("launch", { x, style: shape === "dud" ? "whoosh" : Math.random() < 0.18 ? "whistle" : "whoosh" });
    if (shape === "heart") r.colors = [pick(["#ff5a7a", "#ff8fc0", "#ff4f4f"])];
    rockets.push(r);
    return r;
  }

  // ---- custom fireworks from the Firework editor (and the built-in kinds made the same way)
  // A design is a bag of numbers (see app/fireworks.py). Rockets carry it to the burst;
  // fountains and wheels burn it on the hill. Everything one design makes shares a group,
  // so pictures can move as one and "then…" stages can act on all the pieces together.
  const emitters = [], groups = [], events = [];
  const later = (frames, fn) => events.push({ at: frame + Math.max(1, Math.round(frames)), fn });
  const surfaceAt = (x) => hill.length ? H - hill[Math.max(0, Math.min(hill.length - 1, Math.floor(x / 3)))] : groundY;
  const dv = (d, k, def) => (d[k] ?? def);

  function launchDesign(d, atX) {
    if (d.launch === "fountain" || d.launch === "wheel") {
      const x = atX ?? rand(W * 0.15, W * 0.85);
      addEmitter(d.launch, d, x);
      if (d.mirror && Math.abs(W - x - x) > 12) addEmitter(d.launch, d, W - x);
      return true;
    }
    const n = Math.max(1, Math.min(12, d.rockets || 1)), spread = dv(d, "spot", 0.3);
    const x0 = atX ?? (n > 1 && spread > 0.6 ? W / 2 : rand(W * 0.2, W * 0.8));
    const gap = dv(d, "interval", 0.25) * 60;
    for (let k = 0; k < n; k++) {
      const off = n > 1 ? k / (n - 1) - 0.5 : 0;
      const fire = () => {
        const x = Math.max(8, Math.min(W - 8, x0 + off * spread * W * 0.7 + rand(-3, 3) * spread));
        const fan = off * dv(d, "fan", 0) * 1.1;
        rocketFor(d, x, fan);
        if (d.mirror) rocketFor(d, W - x, -fan, true);
      };
      if (k === 0) fire(); else later(k * gap, fire);
    }
    return true;
  }
  function rocketFor(d, x, fan = 0, mirrored = false) {
    const lean = (mirrored ? -1 : 1) * dv(d, "lean", 0) * 0.55 + fan;
    const top = H * 0.06, apex = groundY - (groundY - top) * Math.max(0.1, Math.min(1, dv(d, "height", 0.6))) + rand(-6, 6);
    const v = Math.sqrt(2 * G * Math.max(4, groundY + 4 - apex));
    const r = { x, y: groundY + 4, vx: Math.sin(lean) * v, vy: -Math.cos(lean) * v, shape: "custom", design: d, colors: d.colors,
      style: d.rocket_style || "normal", hang: Math.round(dv(d, "hang", 0) * 60), t: 0, mirrored };
    rockets.push(r);
    if (d.sound_launch !== "none") snd("launch", { x, style: d.sound_launch || "whoosh" });
    return r;
  }

  // ---- bursts
  function newGroup(d, x, y) {
    const g = { d, born: frame, bx: x, by: y, cx: x, cy: y, rot: 0, released: true, hue: rand(0, 360) };
    groups.push(g);
    return g;
  }
  const colorsOf = (d, own) => (own?.length ? own : d.colors?.length ? d.colors : ["#ffe45c"]);
  function explodeCustom(r) {
    const d = r.design, g = newGroup(d, r.x, r.y);
    if (d.flash > 0) flashBurst(r.x, r.y, d.flash);
    smoke(r.x, r.y, d.colors, Math.min(2, d.size || 1.2));
    if ((d.sound_burst || "boom") !== "none") snd("burst", { x: r.x, kind: d.sound_burst || "boom", size: d.size || 1.2 });
    if (d.sound_crackle !== false && (d.sparkle > 0 || d.strobe > 0 || d.glitter > 0 || d.second > 0)) snd("crackle", { x: r.x, delay: d.second > 0 ? dv(d, "second_delay", 0.5) : 0.5, dur: Math.min(3, (d.life || 1.4) * 0.8) });
    if (d.sound_fizzle) snd("fizzle", { x: r.x, delay: (d.life || 1.4) * 0.75 });
    burst(g, r.x, r.y, { pattern: d.pattern, size: d.size || 1.2, sparks: d.sparks || 48, colors: colorsOf(d), mirrored: r.mirrored });
    let t = 0;
    for (const st of d.stages || []) { t += st.delay * 60; later(t, () => runStage(g, st)); }
  }
  function flashBurst(x, y, power) {
    const m = Math.round(8 + power * 26);
    for (let i = 0; i < m; i++) {
      const a = (i / m) * Math.PI * 2;
      sparks.push({ x, y, px: x, py: y, vx: Math.cos(a) * (0.6 + power), vy: Math.sin(a) * (0.6 + power), life: 0, max: rand(8, 14), color: "#ffffff" });
    }
  }
  function customSpark(g, x, y, vx, vy, color, i, n, extra = {}) {
    const d = g.d;
    return { cd: g, x, y, px: x, py: y, vx, vy, life: 0, max: (d.life || 1.4) * 60 * rand(0.85, 1.15), color, hueOff: (i / Math.max(1, n)) * 360, seed: rand(0, 6.28), ...extra };
  }
  // One burst of a pattern at (x, y), added to the group's pieces.
  function burst(g, x, y, o) {
    // When the sky is already very full, new bursts get fewer pieces so nothing bogs down.
    const room = sparks.length > SPARK_HARD ? 0.25 : sparks.length > SPARK_SOFT ? 0.5 : 1;
    const d = g.d, S = o.size, cols = o.colors, n = Math.max(6, Math.min(160, Math.round(o.sparks * room)));
    const rot = rand(-1, 1) * dv(d, "tilt", 0) * 1.2, cos = Math.cos(rot), sin = Math.sin(rot);
    const jitter = () => 1 - dv(d, "spread", 0) * Math.random();
    const colorFor = (i) => d.color_mode === "alternate" ? cols[i % cols.length] : d.color_mode === "mix" ? pick(cols) : cols[0];
    const add = (vx, vy, i, extra = {}, squash = true) => {
      const sq = squash ? dv(d, "squash", 1) : 1;
      sparks.push(customSpark(g, x, y, vx * cos - vy * sin, (vx * sin + vy * cos) * sq, colorFor(i), i, n, extra));
    };
    const pattern = o.pattern;
    if (pattern === "picture" && d.picture?.length) return pictureBurst(g, x, y, S, cols, o.mirrored);
    if (pattern === "spiral") {
      const arms = Math.max(2, Math.min(6, d.arms || 3)), per = Math.max(4, Math.round(n / arms)), spin = dv(d, "spin", 0.5) * 0.08 || 0.01, off = rand(0, Math.PI * 2);
      for (let a = 0; a < arms; a++) for (let j = 0; j < per; j++) {
        sparks.push(customSpark(g, x, y, 0, 0, colorFor(a * per + j), a * per + j, n,
          { orbit: { cx: x, cy: y, a: off + (a / arms) * Math.PI * 2 - j * 0.15 * Math.sign(spin), r: 0, dr: S * (0.3 + j * (1.2 / per)), da: spin } }));
      }
      return;
    }
    if (pattern === "palm") {
      const arms = Math.max(5, Math.min(12, Math.round(n / 6)));
      for (let i = 0; i < arms; i++) {
        const a = (i / arms) * Math.PI * 2 - Math.PI / 2 + rand(-0.1, 0.1);
        add(Math.cos(a) * S * 1.15 * jitter(), Math.sin(a) * S * 1.15 * jitter() - 0.25, i, { palm: true, max: (d.life || 1.4) * 72 });
      }
      return;
    }
    if (pattern === "pop") {
      const m = Math.min(n, 14);
      for (let i = 0; i < m; i++) { const a = rand(0, Math.PI * 2), sp = S * rand(0.2, 0.55); add(Math.cos(a) * sp, Math.sin(a) * sp, i, { max: (d.life || 1.4) * 40 }); }
      return;
    }
    if (pattern === "saturn") {                    // a ball with a tilted ring around it
      const core = Math.round(n * 0.55), ring = n - core, tilt = rand(-0.5, 0.5), tc = Math.cos(tilt), ts = Math.sin(tilt);
      for (let i = 0; i < core; i++) { const a = (i / core) * Math.PI * 2; const sp = S * 0.55 * jitter(); add(Math.cos(a) * sp, Math.sin(a) * sp, i, {}, false); }
      for (let i = 0; i < ring; i++) {
        const a = (i / ring) * Math.PI * 2, rx = Math.cos(a) * S * 1.25, ry = Math.sin(a) * S * 0.3;
        sparks.push(customSpark(g, x, y, rx * tc - ry * ts, rx * ts + ry * tc, cols[(i + 1) % cols.length], i, ring));
      }
      return;
    }
    for (let i = 0; i < n; i++) {
      let a = (i / n) * Math.PI * 2, sp = S * jitter();
      if (pattern === "burst") { a = rand(0, Math.PI * 2); sp = S * rand(0.15, 1); }
      else if (pattern === "ring") { sp = S * (1 - dv(d, "spread", 0) * 0.2 * Math.random()); }
      else if (pattern === "star") {
        const pts = Math.max(3, Math.min(10, d.points || 5)), k = ((a / (Math.PI * 2)) * pts) % 1;
        sp = S * (0.45 + 0.75 * (1 - Math.abs(k - 0.5) * 2)) * jitter();
        a -= Math.PI / 2;
      } else a += rand(-0.06, 0.06);
      add(Math.cos(a) * sp, Math.sin(a) * sp * (pattern === "ring" ? 0.5 : 1), i);
    }
    if (dv(d, "second", 0) > 0) {
      for (const p of sparks.slice(-n)) if (p.cd === g && Math.random() < d.second) p.fuse = Math.round(dv(d, "second_delay", 0.5) * 60 * rand(0.85, 1.15));
    }
  }

  // Pictures: pieces fly into place, then the whole picture can drift, spin and swap between
  // two painted frames while it holds, before falling (or whatever the next stage says).
  function pictureLayout(rows, k) {
    if (!rows?.length) return [];
    const h = rows.length, w = Math.max(...rows.map((r) => r.length)), out = [];
    rows.forEach((row, y) => [...row].forEach((c, x) => { if (c !== ".") out.push({ x: (x - (w - 1) / 2) * k, y: (y - (h - 1) / 2) * k, c: +c }); }));
    return out;
  }
  function pictureBurst(g, x, y, S, cols, mirrored) {
    // Spacing between painted squares: firework-like dots at small sizes, solid pixel art
    // when the piece size fills the gaps.
    const d = g.d, k = 1.2 + S * 1.6;
    const flip = (pts) => mirrored ? pts.map((p) => ({ ...p, x: -p.x })) : pts;
    const f1 = flip(pictureLayout(d.picture, k)), f2 = flip(pictureLayout(d.picture2, k));
    const n = Math.max(f1.length, f2.length);
    Object.assign(g, {
      released: false, form: 42, hold: Math.round(dv(d, "hold", 0.8) * 60), swap: f2.length ? Math.round(dv(d, "swap", 0.4) * 60) : 0,
      vx: dv(d, "move_x", 0) * 0.7 * (mirrored ? -1 : 1), vy: -dv(d, "move_y", 0) * 0.5, turn: dv(d, "turn", 0) * 0.05 * (mirrored ? -1 : 1),
      rot: rand(-1, 1) * dv(d, "tilt", 0) * 0.6,
    });
    for (let i = 0; i < n; i++) {
      const a = f1[i] || null, b = f2.length ? f2[i] || null : a;
      sparks.push(customSpark(g, x, y, 0, 0, cols[(a || b).c] || cols[0], i, n, {
        pin: true, t1: a, t2: b, c1: a ? cols[a.c] || cols[0] : null, c2: b ? cols[b.c] || cols[0] : null, max: 1e9,
      }));
    }
  }
  function release(g, kick = 0.2) {
    if (g.released) return;
    g.released = true;
    for (const p of sparks) {
      if (p.cd !== g || !p.pin) continue;
      p.pin = false;
      if (p.hidden) { p.max = 0; continue; }
      p.vx = rand(-kick, kick) + (g.vx || 0); p.vy = rand(-kick * 1.4, kick * 0.4) + (g.vy || 0);
      p.max = p.life + (g.d.life || 1.4) * 60 * rand(0.85, 1.15);
    }
  }
  function updateGroups() {
    for (let i = groups.length - 1; i >= 0; i--) {
      const g = groups[i], age = frame - g.born;
      if (!g.released && age > g.form) {
        g.cx += g.vx; g.cy += g.vy; g.rot += g.turn;
        if (age >= g.form + g.hold) release(g);
      }
      if (age > 60 * 40) groups.splice(i, 1);
    }
  }

  // ---- "then…" stages, acting on everything the firework has made so far
  function piecesOf(g) { return sparks.filter((p) => p.cd === g && !p.hidden && p.life < p.max); }
  function centreOf(g, list) {
    if (!g.released) return { x: g.cx, y: g.cy };
    if (!list.length) return { x: g.cx, y: g.cy };
    return { x: list.reduce((a, p) => a + p.x, 0) / list.length, y: list.reduce((a, p) => a + p.y, 0) / list.length };
  }
  function runStage(g, st) {
    if (stopped) return;
    const d = g.d, cols = colorsOf(d, st.colors);
    const list = piecesOf(g);
    const c = centreOf(g, list);
    if (d.sound_burst !== "none") snd("burst", { x: c.x, kind: st.action === "pieces" ? "crack" : st.action === "shatter" ? "pop" : d.sound_burst || "boom", size: st.size });
    if (st.action === "burst") {
      if (d.flash > 0) flashBurst(c.x, c.y, d.flash * 0.7);
      release(g);
      burst(g, c.x, c.y, { pattern: st.pattern, size: st.size, sparks: st.sparks, colors: cols });
    } else if (st.action === "pieces") {
      release(g, 0);
      const step = Math.max(1, Math.floor(list.length / 14));
      for (let i = 0; i < list.length; i += step) {
        const p = list[i];
        p.max = 0;
        burst(g, p.x, p.y, { pattern: st.pattern, size: st.size * 0.5, sparks: Math.min(st.sparks, 16), colors: cols });
      }
    } else if (st.action === "shatter") {
      release(g, 0);
      for (const p of list) {
        const dx = p.x - c.x, dy = p.y - c.y, len = Math.hypot(dx, dy) || 1, sp = st.size * rand(0.6, 1.25);
        p.vx = (dx / len) * sp; p.vy = (dy / len) * sp; p.orbit = null; p.fuse = 0;
        p.max = p.life + (d.life || 1.4) * 60 * rand(0.85, 1.15);
        if (st.colors?.length) { p.color = pick(st.colors); p.c1 = p.c2 = null; }
      }
    } else if (st.action === "implode") {
      release(g, 0);
      for (const p of list) { p.implode = { x: c.x, y: c.y }; p.orbit = null; p.fuse = 0; p.max = p.life + 40; }
      later(30, () => {
        flashBurst(c.x, c.y, 0.8);
        burst(g, c.x, c.y, { pattern: st.pattern, size: st.size, sparks: st.sparks, colors: cols });
      });
    }
    wake();
  }

  // ---- fountains, spinning wheels, the sparkler and shooting stars
  function addEmitter(kind, d, x, extra = {}) {
    const y = kind === "comet" ? 0 : surfaceAt(x);
    const e = { kind, d, x, y, t: 0, dur: Math.round(dv(d, "duration", 4) * 60), acc: 0, ang: 0, g: newGroup(d, x, y), ...extra };
    emitters.push(e);
    if (kind !== "comet") snd("hiss", { x: kind === "sparkler" ? watcher.x : x, dur: e.dur / 60, soft: kind === "sparkler" });
    return e;
  }
  function updateEmitters() {
    for (let i = emitters.length - 1; i >= 0; i--) {
      const e = emitters[i], d = e.d, g = e.g;
      e.t++;
      if (e.t > e.dur) { emitters.splice(i, 1); continue; }
      const cols = colorsOf(d), fade = Math.min(1, (e.dur - e.t) / 40, e.t / 15);
      const colorFor = (k) => d.color_mode === "alternate" ? cols[k % cols.length] : d.color_mode === "mix" ? pick(cols) : cols[0];
      if (e.kind === "fountain") {
        ctx.fillStyle = "#3a3f4a"; ctx.fillRect(Math.round(e.x) - 1, e.y - 3, 3, 3);
        ctx.fillStyle = "#fff3c4"; ctx.fillRect(Math.round(e.x), e.y - 4, 1, 1);
        e.acc += dv(d, "rate", 0.5) * 3.2 * fade;
        for (; e.acc >= 1; e.acc--) {
          const a = -Math.PI / 2 + rand(-1, 1) * dv(d, "angle", 0.3) * 0.7 + dv(d, "lean", 0) * 0.35;
          const sp = dv(d, "power", 0.8) * rand(1.4, 2.3);
          sparks.push(customSpark(g, e.x, e.y - 4, Math.cos(a) * sp, Math.sin(a) * sp, colorFor(e.t), e.t, 60));
        }
      } else if (e.kind === "wheel") {
        const hx = Math.round(e.x), hy = e.y - 16;
        ctx.fillStyle = "#2a2e36"; ctx.fillRect(hx, hy, 1, 16);
        e.ang += dv(d, "wheel_spin", 0.6) * 0.16;
        const spokes = 4;
        for (let k = 0; k < spokes; k++) {
          const a = e.ang + (k / spokes) * Math.PI * 2, rx = hx + Math.cos(a) * 4, ry = hy + Math.sin(a) * 4;
          ctx.fillStyle = cols[k % cols.length]; ctx.fillRect(Math.round(rx), Math.round(ry), 1, 1);
          if (Math.random() < dv(d, "rate", 0.5) * 1.6 * fade) {
            const dir = Math.sign(dv(d, "wheel_spin", 0.6)) || 1, ta = a + (dir * Math.PI) / 2, sp = dv(d, "power", 0.8) * rand(0.8, 1.4);
            sparks.push(customSpark(g, rx, ry, Math.cos(ta) * sp, Math.sin(ta) * sp, colorFor(k), k, spokes, { max: (d.life || 1.4) * 60 * rand(0.5, 0.9) }));
          }
        }
        ctx.fillStyle = "#fff6d8"; ctx.fillRect(hx, hy, 1, 1);
      } else if (e.kind === "sparkler") {
        const hx = watcher.x + Math.cos(e.t * 0.12) * 2.5, hy = watcher.y + Math.sin(e.t * 0.12) * 2;
        ctx.fillStyle = "#fffbe6"; ctx.fillRect(Math.round(hx), Math.round(hy), 1, 1);
        for (let k = 0; k < 3; k++) {
          const a = rand(0, Math.PI * 2), sp = rand(0.3, 0.9);
          sparks.push({ x: hx, y: hy, px: hx, py: hy, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 0, max: rand(6, 16), color: pick(["#fff3c4", "#ffffff", "#ffcf5a"]), twinkle: true });
        }
      } else if (e.kind === "comet") {
        e.x += e.vx; e.y += e.vy;
        ctx.fillStyle = "#ffffff"; ctx.fillRect(Math.round(e.x), Math.round(e.y), 1, 1);
        sparks.push({ x: e.x, y: e.y, px: e.x - e.vx, py: e.y - e.vy, vx: 0, vy: 0, life: 0, max: rand(14, 24), color: pick(["#dfe9ff", "#ffffff", "#9fd8ff"]), still: true, ember: true });
        if (e.x < -10 || e.x > W + 10 || e.y > groundY) e.t = e.dur + 1;
      }
    }
  }

  function customColor(p, t) {
    const g = p.cd, d = g.d, cols = colorsOf(d);
    if (d.color_mode === "rainbow") return `hsl(${(g.hue + p.hueOff + p.life * 5) % 360} 100% 66%)`;
    if (d.color_mode === "change") {
      const list = cols.length > 1 ? cols : [cols[0], "#ffffff"];
      const f = Math.min(0.999, t) * (list.length - 1), k = Math.floor(f);
      return mix(list[k], list[k + 1], f - k);
    }
    return p.color;
  }
  // Moves and draws one custom piece. Removes it (and returns) when it's used up.
  function stepCustom(p, i) {
    const g = p.cd, d = g.d, age = frame - g.born;
    if (p.fuse && p.life >= p.fuse) {               // "burst again"
      sparks.splice(i, 1);
      const cols = colorsOf(d), next = cols[(cols.indexOf(p.color) + 1) % cols.length] || cols[0];
      burst(g, p.x, p.y, { pattern: "ball", size: (d.size || 1.2) * dv(d, "second_size", 0.6) * 0.45, sparks: 14, colors: [next] });
      for (const q of sparks.slice(-14)) { q.fuse = 0; q.vx += p.vx * 0.3; q.vy += p.vy * 0.3; q.max *= 0.7; }
      return;
    }
    let colorOverride = null;
    if (p.pin) {
      const f = g.swap && age > g.form ? Math.floor((age - g.form) / g.swap) % 2 : 0;
      const tg = f ? p.t2 : p.t1;
      p.hidden = !tg;
      if (tg) {
        const cos = Math.cos(g.rot), sin = Math.sin(g.rot);
        const tx = g.cx + tg.x * cos - tg.y * sin, ty = g.cy + tg.x * sin + tg.y * cos;
        if (age < g.form) { const e = 1 - (1 - age / g.form) ** 3; p.x = g.bx + (tx - g.bx) * e; p.y = g.by + (ty - g.by) * e; }
        else { p.x = tx; p.y = ty; }
        colorOverride = f ? p.c2 : p.c1;
      }
    } else if (p.implode) {
      p.x += (p.implode.x - p.x) * 0.13; p.y += (p.implode.y - p.y) * 0.13;
    } else if (p.orbit) {
      const o = p.orbit;
      o.a += o.da; o.r += o.dr; o.dr *= 0.962; o.cy += (0.03 + p.life * 0.001) * dv(d, "gravity", 1);
      p.x = o.cx + Math.cos(o.a) * o.r; p.y = o.cy + Math.sin(o.a) * o.r * 0.9;
    } else {
      const drag = 0.995 - dv(d, "drag", 0.4) * 0.07;
      p.vx = p.vx * drag + dv(d, "wind", 0) * 0.012;
      p.vy = p.vy * drag + G * 0.55 * dv(d, "gravity", 1);
      if (d.wobble > 0) p.vx += Math.sin(p.life * 0.3 + p.seed) * 0.05 * d.wobble;
      p.x += p.vx; p.y += p.vy;
    }
    if (p.hidden) { p.px = p.x; p.py = p.y; return; }
    const t = p.pin ? Math.min(0.2, age / 600) : p.life / p.max;
    const color = colorOverride && d.color_mode !== "rainbow" && d.color_mode !== "change" ? colorOverride : customColor(p, t);
    const crowded = sparks.length > SPARK_SOFT;
    if (!crowded && !p.pin && (d.trail > 0 || p.palm) && p.life % 2 === 0 && t < 0.85 && Math.random() < (p.palm ? 0.9 : d.trail)) {
      sparks.push({ x: p.x, y: p.y, px: p.x, py: p.y, vx: rand(-0.03, 0.03), vy: 0.05, life: 0, max: p.palm ? 22 : 14, color, ember: true });
    }
    if (!crowded && !p.pin && d.glitter > 0 && t < 0.85 && Math.random() < d.glitter * 0.45) {
      sparks.push({ x: p.x, y: p.y, px: p.x, py: p.y, vx: rand(-0.03, 0.03), vy: rand(0.02, 0.09), life: 0, max: rand(40, 75),
        color: Math.random() < 0.45 ? "#fff3c4" : color, glitter: true, twinkle: true });
    }
    if (d.sparkle > 0 && t > 0.25 && Math.random() < d.sparkle * 0.6) return;            // crackle
    if (d.fizzle > 0 && t > 0.7 && Math.random() < d.fizzle * (t - 0.7) * 3) return;      // flickering out
    let alpha = Math.min(1, 1.25 * (1 - t * t));
    const pulse = frame - g.born;
    if (d.blink > 0 && Math.floor(pulse / Math.round(36 - d.blink * 30)) % 2) alpha *= 0.06;
    if (d.breathe > 0) alpha *= 1 - d.breathe * 0.75 * (0.5 + 0.5 * Math.sin(pulse * (0.06 + d.breathe * 0.1)));
    let fill = color;
    if (d.strobe > 0) {
      const roll = Math.random();
      if (roll < d.strobe * 0.3) { fill = "#ffffff"; alpha = 1; } else if (roll < d.strobe * 0.55) return;
    }
    if (d.fizzle > 0 && t > 0.7 && Math.random() < d.fizzle * 0.3) fill = "#ffffff";
    ctx.globalAlpha = alpha; ctx.fillStyle = fill;
    const size = Math.min(4, dv(d, "piece", 1) + Math.floor(t * dv(d, "grow", 0) * 3));
    if (size <= 1 && !p.pin) line(p.px, p.py, p.x, p.y);
    else ctx.fillRect(Math.round(p.x - (size - 1) / 2), Math.round(p.y - (size - 1) / 2), Math.max(1, size), Math.max(1, size));
  }

  // Built-in kinds made from designs, so they share all the machinery above.
  function builtinDesign(kind) {
    const two = () => [pick(fwPalette()), pick(fwPalette())];
    const base = { colors: two(), color_mode: "mix", size: 1.2, sparks: 48, life: 1.4, gravity: 1, drag: 0.4, flash: 0.3 };
    switch (kind) {
      case "candle": return { ...base, rockets: Math.round(rand(5, 8)), interval: rand(0.35, 0.55), spot: 0, fan: rand(0.1, 0.3), lean: rand(-0.35, 0.35),
        pattern: "pop", size: 0.7, sparks: 12, height: rand(0.45, 0.7), rocket_style: "colored", life: 0.9, flash: 0, trail: 0.4, color_mode: "alternate" };
      case "cake": return { ...base, rockets: Math.round(rand(10, 15)), interval: rand(0.09, 0.15), spot: 0, fan: rand(0.6, 1), pattern: pick(["ball", "pop", "star"]),
        size: 0.55, sparks: 20, height: rand(0.35, 0.55), rocket_style: "sparkly", life: 0.9, sparkle: 0.4, flash: 0.15 };
      case "fountain": return { ...base, launch: "fountain", duration: rand(4, 6.5), rate: rand(0.55, 0.85), power: rand(0.6, 1), angle: rand(0.15, 0.35),
        colors: Math.random() < 0.5 ? ["#ffcf5a", "#fff3c4"] : two(), life: 1.1, glitter: 0.15, sparkle: 0.3 };
      case "wheel": return { ...base, launch: "wheel", duration: rand(4, 6), rate: 0.8, power: rand(0.6, 1), wheel_spin: pick([-0.8, 0.8]), life: 0.8, sparkle: 0.2 };
      case "saturn": return { ...base, pattern: "saturn", sparks: 64, size: 1.3, color_mode: "alternate" };
      default: return null;
    }
  }

  // ---- figures (dragon, bow, arrow)
  function addFigure(kind, x, y, extra = {}) {
    const def = FW_FIGURES[kind];
    const h = def.frames[0].length, w = def.frames[0][0].length;
    const f = { kind, def, x, y, w, h, sc: 2, vx: 0, vy: 0, t: 0, life: 200, dir: 1, form: 26, flapEvery: 9, ...extra };
    f.delay = def.frames[0].flatMap((row) => [...row].map(() => rand(0, f.form)));
    figures.push(f);
    return f;
  }
  function figurePixels(f) {
    const rows = f.def.frames[Math.floor(f.t / f.flapEvery) % f.def.frames.length];
    const out = [];
    rows.forEach((row, cy) => [...row].forEach((c, cx) => {
      if (c === ".") return;
      const px = f.dir > 0 ? cx : f.w - 1 - cx;
      out.push({ x: Math.round(f.x + (px - f.w / 2) * f.sc), y: Math.round(f.y + (cy - f.h / 2) * f.sc), color: f.def.palette[c], i: cy * f.w + cx });
    }));
    return out;
  }
  function shatter(f, power = 1) {
    for (const p of figurePixels(f)) {
      sparks.push({ x: p.x, y: p.y, px: p.x, py: p.y, vx: rand(-0.7, 0.7) * power + f.vx * 0.3, vy: rand(-0.9, 0.3) * power,
        life: 0, max: rand(45, 80), color: p.color, twinkle: Math.random() < 0.5 });
    }
  }
  function flash(x, y, color, n = 14) {
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      sparks.push({ x, y, px: x, py: y, vx: Math.cos(a) * 0.9, vy: Math.sin(a) * 0.9, life: 0, max: rand(14, 22), color });
    }
  }
  // ---- tree: grows up from a low burst, holds, then its leaves drift down and the wood fades
  const LEAVES = [["#5fe04a", "#3fbf5a", "#9be34a", "#7dff5c"], ["#ffb7d5", "#ff8fc0", "#ffe0ee", "#ffffff"], ["#ffa13d", "#ff5a4f", "#ffe45c", "#ffcf5a"]];
  function growTree(x0, y0) {
    const px = [], leafSet = pick(LEAVES), wood = "#a0693a";
    let done = 0;
    function leaves(cx, cy, t) {
      const r = rand(6, 8.5);
      for (let i = 0; i < r * r * 1.5; i++) {
        const a = rand(0, Math.PI * 2), d = Math.sqrt(Math.random()) * r;
        const at = t + rand(3, 24);
        px.push({ x: Math.round(cx + Math.cos(a) * d), y: Math.round(cy + Math.sin(a) * d * 0.85), c: pick(leafSet), at, leaf: true });
        done = Math.max(done, at);
      }
    }
    function branch(x, y, ang, len, width, depth, t) {
      for (let i = 0; i < Math.round(len); i++) {
        x += Math.cos(ang); y += Math.sin(ang); ang += rand(-0.07, 0.07); t += 1.2;
        for (let w = 0; w < width; w++) px.push({ x: Math.round(x + w - (width - 1) / 2), y: Math.round(y), c: wood, at: t });
      }
      if (depth >= 3) { leaves(x, y, t); return; }
      if (depth >= 1) leaves(x, y, t + 6);
      const kids = depth === 0 ? 3 : 2;
      for (let k = 0; k < kids; k++) {
        const spread = (k - (kids - 1) / 2) * (depth === 0 ? 0.6 : 0.7);
        branch(x, y, ang + spread + rand(-0.25, 0.25), len * rand(0.55, 0.7), Math.max(1, width - 1), depth + 1, t);
      }
    }
    branch(x0, y0, -Math.PI / 2 + rand(-0.06, 0.06), rand(30, 40), 3, 0, 0);
    trees.push({ px, t: 0, full: done, hold: 110 });
  }
  function updateTrees() {
    for (let i = trees.length - 1; i >= 0; i--) {
      const tr = trees[i];
      tr.t += 1;
      if (tr.t > tr.full + tr.hold) {
        trees.splice(i, 1);
        for (const p of tr.px) {
          if (p.leaf) { if (Math.random() < 0.55) sparks.push({ x: p.x, y: p.y, px: p.x, py: p.y, vx: 0, vy: 0, life: 0, max: rand(170, 280), color: p.c, leaf: true, seed: rand(0, 6.28), fall: rand(0.18, 0.34) }); }
          else sparks.push({ x: p.x, y: p.y, px: p.x, py: p.y, vx: 0, vy: 0, life: 0, max: rand(30, 60), color: p.c, still: true, ember: true });
        }
        continue;
      }
      for (const p of tr.px) {
        if (p.at > tr.t) continue;
        const fresh = tr.t - p.at < 3;              // the growing tip sparkles
        ctx.globalAlpha = fresh ? 1 : p.leaf ? 0.92 : 0.85;
        ctx.fillStyle = fresh ? "#fffbe6" : p.c;
        ctx.fillRect(p.x, p.y, 1, 1);
      }
      ctx.globalAlpha = 1;
    }
  }

  function updateFigures() {
    for (let i = figures.length - 1; i >= 0; i--) {
      const f = figures[i];
      f.t++;
      if (f.kind === "dragon") {
        f.vy = Math.sin(f.t * 0.07) * 0.22 - 0.02;
        if (f.t > f.form) { f.x += f.vx; f.y += f.vy; }
        if (f.t % 3 === 0 && f.t > f.form) {      // embers off the tail
          const tx = f.x - f.dir * (f.w / 2) * f.sc, ty = f.y + f.sc;
          sparks.push({ x: tx, y: ty, px: tx, py: ty, vx: -f.vx * 0.3 + rand(-0.1, 0.1), vy: rand(0, 0.25), life: 0, max: rand(16, 26), color: pick(["#c46cf0", "#ff9cf7", "#5d8bff"]), ember: true });
        }
      } else if (f.kind === "bow") {
        // Lingers until a moment after the arrow is loosed (or gives up if it never comes).
        if ((f.shotAt && f.t - f.shotAt > 55) || (!f.shotAt && f.t > 420)) f.done = true;
        f.y += 0.02;
      } else if (f.kind === "arrow") {
        if (!f.flying && f.t > f.form + 28) {
          f.flying = true; f.vx = f.dir * 2.6; f.vy = -0.18;
          if (f.bow) f.bow.shotAt = f.bow.t;
        }
        if (f.flying) {
          f.vy += 0.006; f.x += f.vx; f.y += f.vy;
          const tx = f.x - f.dir * (f.w / 2) * f.sc;
          sparks.push({ x: tx, y: f.y, px: tx, py: f.y, vx: -f.vx * 0.15, vy: rand(-0.05, 0.1), life: 0, max: rand(12, 20), color: pick(["#ffe45c", "#ffffff"]), ember: true });
          if (f.t > f.form + 28 + 110) f.done = true;
        }
      }
      const offscreen = f.x < -f.w * f.sc || f.x > W + f.w * f.sc;
      if (f.kind === "dragon" && f.t >= f.life) f.done = true;
      if (f.done || offscreen) {
        figures.splice(i, 1);
        if (!offscreen) {
          shatter(f, f.kind === "arrow" ? 1.3 : 1);
          if (f.kind === "arrow") flash(f.x + f.dir * (f.w / 2) * f.sc, f.y, "#ffe45c", 18);
        }
        continue;
      }
      const fade = f.kind === "dragon" ? Math.min(1, (f.life - f.t) / 25) : 1;
      for (const p of figurePixels(f)) {
        if (f.t < f.delay[p.i]) continue;          // pixels sparkle in one by one
        ctx.globalAlpha = (f.t < f.form && Math.random() < 0.3 ? 0.5 : 1) * Math.max(0.35, fade);
        ctx.fillStyle = p.color; ctx.fillRect(p.x, p.y, f.sc, f.sc);
      }
      ctx.globalAlpha = 1;
    }
  }

  function explode(r) {
    if (r.design) { explodeCustom(r); return; }
    if (r.dud) {                                     // a sad little fizzle (someone died)
      for (let i = 0; i < 7; i++) sparks.push({ x: r.x, y: r.y, px: r.x, py: r.y, vx: rand(-0.25, 0.25), vy: rand(-0.3, 0.1), life: 0, max: rand(30, 60), color: pick(["#8a8f98", "#5f646d", "#b0703a"]), twinkle: true });
      snd("fizzle", { x: r.x });
      return;
    }
    smoke(r.x, r.y, r.colors, r.shape === "large" ? 1.5 : 1);
    snd("burst", { x: r.x, kind: ["large", "saturn", "dragon", "tree", "willow"].includes(r.shape) ? "boom" : r.shape === "pop" ? "pop" : Math.random() < 0.5 ? "boom" : "pop",
      size: r.shape === "large" ? 1.6 : 1 });
    if (r.twinkle || r.shape === "crossette" || r.shape === "willow") snd("crackle", { x: r.x, delay: r.shape === "crossette" ? 0.45 : 0.6, dur: r.shape === "willow" ? 2.4 : 1.2 });
    const add = (vx, vy, i, extra = {}) => sparks.push({ x: r.x, y: r.y, px: r.x, py: r.y, vx, vy, life: 0, max: rand(55, 85) * (r.shape === "large" ? 1.3 : 1),
      color: r.colors[i % r.colors.length], fade: r.fade, trail: r.trail, twinkle: r.twinkle, ...extra });
    if (r.shape === "dragon") {
      const dir = r.x < W / 2 ? 1 : -1;
      flash(r.x, r.y, "#ff9cf7", 18);
      addFigure("dragon", r.x, r.y, { dir, vx: dir * 0.55, life: 240 });
      return;
    }
    if (r.shape === "bow") {
      const dir = r.x < W / 2 ? 1 : -1;
      flash(r.x, r.y, "#f0b35a");
      const bow = addFigure("bow", r.x, r.y, { dir, form: 20 });
      // A second rocket comes up to the bow and becomes the arrow.
      setTimeout(() => { if (!stopped) { launch("arrow", { x: r.x - dir * 2, y: r.y, target: bow }); wake(); } }, 350);
      return;
    }
    if (r.shape === "arrow") {
      const bow = r.target && figures.includes(r.target) ? r.target : null;
      const dir = bow ? bow.dir : (r.x < W / 2 ? 1 : -1);
      const aw = FW_FIGURES.arrow.frames[0][0].length;
      const x = bow ? bow.x - dir * (bow.w / 2) * bow.sc + dir * (aw / 2) * 2 : r.x;
      flash(r.x, r.y, "#ffffff", 10);
      addFigure("arrow", x, bow ? bow.y : r.y, { dir, bow, form: 12 });
      return;
    }
    if (r.shape === "willow") {
      // Falls slowly in long glittering strands, fading well after a normal burst.
      const n = 26;
      for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2 + rand(-0.06, 0.06), sp = rand(1.3, 1.6);
        add(Math.cos(a) * sp, Math.sin(a) * sp - 0.2, i, { willow: true, max: rand(190, 250), twinkle: false, trail: false, fade: r.fade || "#b0703a" });
      }
      return;
    }
    if (r.shape === "tree") {
      flash(r.x, r.y, "#9be34a", 16);
      growTree(r.x, r.y);
      return;
    }
    if (r.shape === "crossette") {
      // Splits into a handful of smaller rockets that each burst again in a second colour.
      const n = Math.round(rand(5, 7)), off = rand(0, Math.PI);
      for (let i = 0; i < n; i++) {
        const a = off + (i / n) * Math.PI * 2;
        add(Math.cos(a) * 1.15, Math.sin(a) * 1.15 - 0.2, 0, { sub: true, fuse: rand(24, 34), max: 60, trail: true, twinkle: false, fade: null, color2: r.colors[1] || pick(fwPalette()) });
      }
      return;
    }
    if (r.shape === "spiral") {
      // A pinwheel: arms of sparks that swirl outwards while they drift down.
      const arms = Math.random() < 0.5 ? 3 : 4, spin = (Math.random() < 0.5 ? 1 : -1) * 0.045, off = rand(0, Math.PI * 2);
      for (let a = 0; a < arms; a++) for (let j = 0; j < 16; j++) {
        add(0, 0, a, { orbit: { cx: r.x, cy: r.y, a: off + (a / arms) * Math.PI * 2 - j * 0.15 * Math.sign(spin), r: 0, dr: 0.35 + j * 0.075, da: spin }, max: rand(90, 110), trail: j % 4 === 0 });
      }
      return;
    }
    const tpl = FW_TEMPLATES[r.shape];
    if (tpl) {
      // Sparks fly out to their place in the shape, hang there, then droop and fade.
      const rows = tpl.length, cols = tpl[0].length, rot = rand(-0.35, 0.35), flip = Math.random() < 0.5 ? -1 : 1;
      const k = rand(0.17, 0.21), cos = Math.cos(rot), sin = Math.sin(rot);
      let i = 0;
      tpl.forEach((row, y) => [...row].forEach((c, x) => {
        if (c !== "#") return;
        const ox = (x - (cols - 1) / 2) * flip, oy = y - (rows - 1) / 2;
        add((ox * cos - oy * sin) * k, (ox * sin + oy * cos) * k, i++, { shaped: true, max: rand(95, 115) });
      }));
      return;
    }
    const n = { ball: 34, large: 64, star: 50, burst: 46, ring: 40 }[r.shape];
    for (let i = 0; i < n; i++) {
      let a = (i / n) * Math.PI * 2, sp;
      if (r.shape === "ball") { sp = rand(0.9, 1.3); a += rand(-0.08, 0.08); }
      else if (r.shape === "large") { sp = rand(1.6, 2.2); a += rand(-0.05, 0.05); }
      else if (r.shape === "ring") { sp = 1.5; }
      else if (r.shape === "burst") { sp = rand(0.3, 1.9); a = rand(0, Math.PI * 2); }
      else { // star: speed follows a 5-point star outline
        const k = ((a / (Math.PI * 2)) * 5) % 1;
        sp = 0.85 + 0.9 * (1 - Math.abs(k - 0.5) * 2);
        a -= Math.PI / 2;
      }
      add(Math.cos(a) * sp, Math.sin(a) * sp * (r.shape === "ring" ? 0.55 : 1), i);
    }
  }

  function mix(c1, c2, t) {
    const p = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
    const a = p(c1), b = p(c2);
    return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",")})`;
  }

  function line(x0, y0, x1, y1) {
    x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx + dy;
    for (let i = 0; i < 16; i++) {
      ctx.fillRect(x0, y0, 1, 1);
      if (x0 === x1 && y0 === y1) break;
      const e2 = 2 * err;
      if (e2 >= dy) { err += dy; x0 += sx; }
      if (e2 <= dx) { err += dx; y0 += sy; }
    }
  }

  function step() {
    frame++;
    refreshLand();
    drawBackdrop();
    runShow();
    const starVis = gsky ? (1 - daylight()) * (1 - rainAmt() * 0.85) : 1;
    for (const s of stars) {                         // slow twinkle
      if (starVis <= 0.02) break;
      ctx.globalAlpha = starVis * s.a * (0.65 + 0.35 * Math.sin(s.p + frame * 0.02));
      ctx.fillStyle = "#dfe6f5"; ctx.fillRect(s.x, s.y, 1, 1);
    }
    ctx.globalAlpha = 1;

    for (let i = rockets.length - 1; i >= 0; i--) {
      const r = rockets[i];
      r.t = (r.t || 0) + 1;
      if (r.hanging > 0) {                           // hang time: hiss at the top, then burst
        r.hanging--;
        if (Math.random() < 0.6) sparks.push({ x: r.x, y: r.y, px: r.x, py: r.y, vx: rand(-0.3, 0.3), vy: rand(-0.2, 0.3), life: 0, max: rand(6, 12), color: "#fff1c2", ember: true });
        ctx.fillStyle = r.t % 6 < 3 ? "#ffffff" : "#ffcf5a"; ctx.fillRect(Math.round(r.x), Math.round(r.y), 1, 1);
        if (r.hanging <= 0) { rockets.splice(i, 1); explode(r); }
        continue;
      }
      r.x += r.vx; r.y += r.vy; r.vy += G;
      const wig = r.style === "corkscrew" ? Math.sin(r.t * 0.35) * 2.5 : 0, rx = Math.round(r.x + wig), ry = Math.round(r.y);
      if (r.style !== "invisible") {
        const head = r.style === "colored" ? r.colors[0] : "#fff1c2";
        ctx.fillStyle = head; ctx.fillRect(rx, ry, 1, 2);
        if (frame % 2 === 0) sparks.push({ x: rx, y: ry + 2, px: rx, py: ry + 2, vx: rand(-0.08, 0.08), vy: rand(0.1, 0.4), life: 0, max: rand(10, 20), color: r.style === "colored" ? head : "#ffb35c", ember: true });
        if (r.style === "sparkly" && Math.random() < 0.8) sparks.push({ x: rx, y: ry + 1, px: rx, py: ry + 1, vx: rand(-0.3, 0.3), vy: rand(0, 0.3), life: 0, max: rand(10, 22), color: pick(["#ffffff", "#fff3c4", "#ffcf5a"]), twinkle: true });
      }
      if (r.vy >= -0.15) {
        r.x += wig;
        if (r.hang > 0 && !r.hung) { r.hung = true; r.hanging = r.hang; r.vx = 0; continue; }
        rockets.splice(i, 1); explode(r);
      }
    }

    if (sparks.length > SPARK_HARD * 1.4) {           // way too many: let the faintest go
      const keep = sparks.filter((p) => !p.ember && !p.glitter);
      sparks.length = 0; sparks.push(...keep.slice(-SPARK_HARD));
    }
    for (let i = sparks.length - 1; i >= 0; i--) {
      const p = sparks[i];
      p.life++;
      if (p.life > p.max) { sparks.splice(i, 1); continue; }
      p.px = p.x; p.py = p.y;
      if (p.cd) { stepCustom(p, i); continue; }
      if (p.puff) {                                  // daytime smoke: drifts, spreads, fades
        p.vx *= 0.97; p.vy = p.vy * 0.97 - 0.004; p.x += p.vx + 0.02; p.y += p.vy;
        const tt = p.life / p.max, rr = Math.round(p.r0 + tt * 5);
        ctx.globalAlpha = 0.32 * (1 - tt); ctx.fillStyle = p.color;
        ctx.fillRect(Math.round(p.x - rr / 2), Math.round(p.y - rr / 2), rr, rr);
        continue;
      }
      if (p.sub && p.life >= p.fuse) {               // crossette: the small rocket bursts
        sparks.splice(i, 1);
        const n = 16;
        for (let k = 0; k < n; k++) {
          const a = (k / n) * Math.PI * 2 + rand(-0.1, 0.1), sp = rand(0.45, 0.75);
          sparks.push({ x: p.x, y: p.y, px: p.x, py: p.y, vx: Math.cos(a) * sp + p.vx * 0.3, vy: Math.sin(a) * sp + p.vy * 0.3, life: 0, max: rand(35, 55), color: p.color2, twinkle: Math.random() < 0.5 });
        }
        continue;
      }
      if (p.willow) {
        p.vx *= 0.965; p.vy = p.vy * 0.965 + G * 0.45;
        if (sparks.length < SPARK_SOFT && p.life < p.max * 0.85 && Math.random() < 0.42) {      // glitter left hanging behind: the drooping strands
          sparks.push({ x: p.x, y: p.y, px: p.x, py: p.y, vx: rand(-0.03, 0.03), vy: rand(0.02, 0.09), life: 0, max: rand(45, 85),
            color: Math.random() < 0.45 ? "#fff3c4" : p.color, glitter: true, twinkle: true });
        }
      } else if (p.glitter) {
        p.vy = Math.min(p.vy + 0.002, 0.18);
      } else if (p.leaf) {
        p.vx = Math.sin(p.life * 0.05 + p.seed) * 0.3; p.vy = p.fall + Math.sin(p.life * 0.09 + p.seed) * 0.06;
      } else if (p.still) {
        p.vx = 0; p.vy = 0;
      } else if (p.orbit) {
        const o = p.orbit;
        o.a += o.da; o.r += o.dr; o.dr *= 0.962; o.cy += 0.05 + p.life * 0.0012;
        p.x = o.cx + Math.cos(o.a) * o.r; p.y = o.cy + Math.sin(o.a) * o.r * 0.9;
      } else if (p.shaped) { p.vx *= 0.95; p.vy = p.vy * 0.95 + G * (p.life > 45 ? 0.35 : 0.04); }   // hold the shape, then fall
      else { p.vx *= 0.975; p.vy = p.vy * 0.975 + G * (p.ember ? 0.3 : 0.55); }
      if (!p.orbit) { p.x += p.vx; p.y += p.vy; }
      const t = p.life / p.max;
      if (p.twinkle && t > 0.35 && Math.random() < 0.45) continue;      // crackle
      ctx.globalAlpha = p.ember ? 0.7 * (1 - t) : p.glitter ? 0.9 * (1 - t) : p.willow || p.leaf ? Math.min(1, 1.6 * (1 - t)) : Math.min(1, 1.25 * (1 - t * t));
      ctx.fillStyle = p.fade && t > 0.4 ? mix(p.color, p.fade, Math.min(1, (t - 0.4) / 0.4)) : p.color;
      line(p.px, p.py, p.x, p.y);
      if (p.sub) { ctx.fillStyle = "#fff6d8"; ctx.fillRect(Math.round(p.x), Math.round(p.y), 1, 1); }
      if (p.trail && !p.ember && sparks.length < SPARK_SOFT && p.life % (p.sub ? 2 : 3) === 0 && t < 0.8) {
        sparks.push({ x: p.x, y: p.y, px: p.x, py: p.y, vx: 0, vy: 0.05, life: 0, max: 14, color: p.fade || p.color, ember: true });
      }
    }
    ctx.globalAlpha = 1;
    for (let k = events.length - 1; k >= 0; k--) if (events[k].at <= frame) { const ev = events.splice(k, 1)[0]; ev.fn(); }
    updateGroups();
    updateEmitters();
    ctx.globalAlpha = 1;
    updateTrees();
    updateFigures();
    drawWeather();
    ctx.drawImage(land, 0, 0);
    // A bright sky behind the app's panels is dimmed a little so the page stays readable.
    const dim = gsky && opts.dim ? opts.dim() * daylight() : 0;
    if (dim > 0) { ctx.fillStyle = `rgba(8, 12, 24, ${dim})`; ctx.fillRect(0, 0, W, H); }                        // hill and watchers in front of everything
  }

  // The loop only runs while something is moving: the automatic show is on, or rockets
  // and sparks are still in the air. Otherwise one quiet frame is drawn and it sleeps, so
  // the frosted panels on top don't have to re-blur every frame.
  let auto = opts.auto !== false;
  // Everything moves in fixed 1/60 s steps, so fireworks run at the same speed on a
  // 60 Hz phone and a 144 Hz monitor. A slow frame catches up (up to a few steps); a long
  // gap (tab hidden, computer asleep) doesn't fast-forward.
  const STEP_MS = 1000 / 60;
  let lastT = 0, acc = 0;
  function loop(now = performance.now()) {
    if (!running) return;
    if (!lastT || now - lastT > 250) { lastT = now - STEP_MS; acc = 0; }
    acc += now - lastT; lastT = now;
    let n = 0;
    while (acc >= STEP_MS && n < 4) { step(); acc -= STEP_MS; n++; }
    if (n === 4) acc = 0;
    if (!auto && !boosting() && !runner && !rockets.length && !sparks.length && !figures.length && !trees.length && !emitters.length && !events.length) { running = false; frame = 0; step(); return; }
    raf = requestAnimationFrame(loop);
  }
  function wake() {
    if (running || stopped || document.hidden) return;
    running = true; lastT = 0; loop();
  }
  // ---- shows: timed lists of launches made in Show settings
  let runner = null;             // {show, t0, idx, loop, base}
  function playShow(show, o = {}) {
    if (!show?.steps?.length) return;
    runner = { show, t0: frame, idx: 0, loop: !!o.loop, base: !!o.base, until: o.until || 0 };
    wake();
  }
  function fireStep(stp) {
    const n = Math.max(1, Math.min(12, stp.count || 1));
    for (let k = 0; k < n; k++) {
      const off = n > 1 ? k / (n - 1) : 0.5;
      const x = stp.where === "left" ? W * rand(0.12, 0.3) : stp.where === "right" ? W * rand(0.7, 0.88) : stp.where === "center" ? W * rand(0.42, 0.58)
        : stp.where === "spread" ? W * (0.12 + 0.76 * off) : stp.where === "sides" ? (k % 2 ? W * rand(0.72, 0.88) : W * rand(0.12, 0.28)) : W * rand(0.1, 0.9);
      const go = () => {
        if (stp.design) launchDesign(stp.design, x);
        else if (stp.what === "random") launch(undefined, { x });
        else if (stp.what === "showpiece") { const sp = FW_SPECIALS.map((q) => [q, fwWeight(q)]).filter(([, w]) => w > 0); launch(sp.length ? pickWeighted(sp) : "large", { x, keepX: true }); }
        else if (stp.what.startsWith("custom:")) { const d = FW.custom.find((q) => `custom:${q.id}` === stp.what); d ? launchDesign(d, x) : launch(undefined, { x }); }
        else launch(stp.what, { x, keepX: true });
      };
      if (k === 0) go(); else later(k * rand(5, 12), go);
    }
  }
  function runShow() {
    if (!runner) return;
    const steps = runner.show.steps, t = (frame - runner.t0) / 60;
    while (runner.idx < steps.length && steps[runner.idx].at <= t) fireStep(steps[runner.idx++]);
    if (runner.idx >= steps.length) {
      const gap = (runner.show.loop_gap ?? 2) * 60;
      const last = steps[steps.length - 1].at * 60;
      if (frame - runner.t0 >= last + gap) {
        const keep = runner.loop && (runner.base ? auto : runner.until > performance.now());
        if (keep) { runner.t0 = frame; runner.idx = 0; } else runner = null;
      }
    }
  }
  const isNightNow = () => (gsky ? daylight() < 0.45 : (() => { const h = new Date().getHours(); return h >= 19 || h < 7; })());
  // While the Show switch is on, a base show (day or night) replaces the random mix.
  function baseShow() {
    const b = FW.base_shows;
    return b ? (isNightNow() ? b.night : b.day) : null;
  }
  function daytimePaused() { return isDay() && FW.sky?.daytime === "pause" && !boosting(); }

  function schedule() {
    clearTimeout(timer);
    if (!auto && !boosting()) return;
    const bs = !boosting() && auto ? baseShow() : null;
    if (bs && !daytimePaused()) {
      if (!runner || !runner.base || runner.show.id !== bs.id) playShow(bs, { loop: true, base: true });
      timer = setTimeout(schedule, 2000);           // check again for day/night changes
      return;
    }
    if (runner?.base) runner = null;
    timer = setTimeout(() => {
      if (!document.hidden && !daytimePaused() && rockets.length < 6 && sparks.length < 1400) {
        launch();
        if (Math.random() < 0.25) setTimeout(launch, rand(150, 400));      // the occasional salvo
        if (Math.random() < 0.1) setTimeout(launch, rand(450, 700));
        wake();
      }
      schedule();
    }, boosting() ? rand(FW_PACE.lively[0], FW_PACE.lively[1])
      : isDay() && FW.sky?.daytime === "smoke" ? rand(FW_PACE.calm[0], FW_PACE.calm[1]) : rand(every()[0], every()[1]));
  }
  const onVis = () => {
    if (document.hidden) { running = false; cancelAnimationFrame(raf); }
    else if (auto && !reduced) wake();
  };
  const onResize = () => { resize(); if (!running) { if (reduced && auto) still(); else { frame = 0; step(); } } };
  function still() {
    // One quiet frame: two bursts frozen mid-air, no motion.
    rockets.length = 0; sparks.length = 0;
    for (let k = 0; k < 2; k++) { launch(pick(["ball", "large", "star", "heart"])); const r = rockets.pop(); r.y = rand(H * 0.15, H * 0.35); explode(r); }
    for (let i = 0; i < 18; i++) step();
    rockets.length = 0; sparks.length = 0; figures.length = 0; trees.length = 0; emitters.length = 0; events.length = 0;
  }

  resize();
  addEventListener("resize", onResize);
  let ro = null;
  if (opts.fit && "ResizeObserver" in window) { ro = new ResizeObserver(() => onResize()); ro.observe(cv); }
  document.addEventListener("visibilitychange", onVis);
  if (reduced) { if (auto) still(); else step(); auto = false; }
  else if (auto) { launch(); setTimeout(launch, 500); wake(); schedule(); }
  else step();
  return {
    stop() {
      stopped = true; running = false; ro?.disconnect(); clearTimeout(ambient); cancelAnimationFrame(raf); clearTimeout(timer);
      removeEventListener("resize", onResize); document.removeEventListener("visibilitychange", onVis);
    },
    // A salvo, e.g. when someone joins. Skipped for reduced motion and hidden tabs.
    celebrate(n = 3) {
      if (reduced || document.hidden) return;
      for (let i = 0; i < n; i++) setTimeout(() => { launch(); wake(); }, i * rand(180, 420));
    },
    // One rocket on request (the launch button). Works even with reduced motion,
    // because someone asked for it.
    launch(shape) { if (rockets.length < 12) { launch(shape); wake(); } },
    // A lively show for a while (scheduled finales, the "show" event), even with Show off.
    boost(seconds, show) {
      if (reduced) return;
      boostUntil = Math.max(boostUntil, performance.now() + seconds * 1000);
      if (show?.steps?.length) playShow(show, { loop: true, until: boostUntil });
      else launch();
      wake(); schedule();
    },
    // Play a show once (game events, previews in Show settings).
    playShow(show, o = {}) { playShow(show, o); },
    stopShow() { runner = null; },
    // In-game time and weather: {time_of_day, moon, raining, thundering, ticking} or null for night.
    setGameSky(info) {
      gsky = info && info.time_of_day != null ? { tod: info.time_of_day, ref: performance.now(), ticking: !!info.ticking, moon: info.moon || 0,
        raining: !!info.raining, thundering: !!info.thundering } : null;
      if (!running) step();
      ambientTick();
    },
    get daylight() { return gsky ? daylight() : 0; },
    get boosting() { return boosting(); },
    // One of the big show-pieces (dragon, bow, tree), for challenge advancements.
    showpiece() { const k = FW_SPECIALS.map((x) => [x, fwWeight(x)]).filter(([, w]) => w > 0); launch(k.length ? pickWeighted(k) : "large"); wake(); },
    // Is anything still in the air (including stages and fountains still to come)?
    get busy() { return !!(rockets.length || sparks.length || figures.length || trees.length || emitters.length || events.length); },
    // Empty the sky at once (the editor uses this so previews never pile up).
    clear() {
      rockets.length = 0; sparks.length = 0; figures.length = 0; trees.length = 0; emitters.length = 0; events.length = 0; groups.length = 0; runner = null;
      if (!running) { frame = 0; step(); }
    },
    // Launch a design straight from the Firework editor.
    launchDesign(d) { launchDesign(d); wake(); },
    get auto() { return auto; },
    setAuto(on) {
      auto = !!on;
      if (auto) { launch(); wake(); }
      schedule();
    },
  };
}
