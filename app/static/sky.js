/* Solstone — the pixel night sky shared by every page: twinkling stars, a dark blocky
   hill with a small figure and their dog watching, and Minecraft-style fireworks. */
"use strict";

// Minecraft dye colours, brightened the way firework stars look in-game.
const FW_COLORS = ["#ff5a4f", "#ffa13d", "#ffe45c", "#9be34a", "#4fd7e6", "#5d8bff", "#c46cf0", "#ff8fc0", "#ffffff", "#3fd1b0"];
const FW_SHAPES = ["ball", "ball", "large", "star", "burst", "ring", "cube", "pickaxe", "axe", "creeper", "heart",
  "crossette", "crossette", "spiral", "spiral", "willow", "willow"];
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
  FW.colors = c.colors?.length ? c.colors : FW_COLORS;
  FW.pace = FW_PACE[c.pace] ? c.pace : "normal";
  FW.showpieces = FW_SPECIAL_CHANCE[c.showpieces] != null ? c.showpieces : "sometimes";
  FW.custom = Array.isArray(c.custom) ? c.custom : [];
}
const fwOn = (k) => !FW.kinds || FW.kinds[k] !== false;
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
  let stars = [], land = null, groundY = 0, cardBox = null, hill = [];
  const rockets = [], sparks = [], figures = [], trees = [];

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
    heights.forEach((h, i) => {
      g.fillStyle = "#0d1014"; g.fillRect(i * B, H - h, B, h);
      g.fillStyle = "#15211a"; g.fillRect(i * B, H - h, B, 1);    // a hint of grass on top
    });
    // Sitting figure and dog on the left hilltop, facing the sky. Pixel maps: # = filled.
    const top = H - heights[Math.floor(sitX / B)];
    // Standing, head tipped back to watch the sky.
    const person = ["....##.", "...##..", "...##..", "..####.", ".#.##.#", ".#.##.#", "...##..", "...#.#.", "...#.#.", "...#.#."];
    const dog = ["##.....", "###....", ".#...#.", ".#####.", ".#####.", ".#.#.#."];
    g.fillStyle = "#0d1014";
    const draw = (map, ox, oy) => map.forEach((row, y) => [...row].forEach((c, x) => { if (c === "#") g.fillRect(ox + x, oy + y, 1, 1); }));
    draw(person, sitX - 5, top - person.length);
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

  // ---- fireworks
  function launch(shape, at) {
    // Favour the open sky beside the sign-in card so most bursts are visible.
    let x;
    const sides = cardBox ? [[W * 0.06, cardBox.l - 10], [cardBox.r + 10, W * 0.94]].filter(([a, b]) => b - a > 20) : [];
    if (at) x = at.x;
    else if (sides.length && Math.random() < 0.8) { const [a, b] = pick(sides); x = rand(a, b); } else x = rand(W * 0.1, W * 0.9);
    if (!shape) {
      const busy = figures.length || trees.length || rockets.some((r) => FW_SPECIALS.includes(r.shape));
      const regular = [...FW_SHAPES.filter(fwOn), ...FW.custom.map((d) => d)], special = FW_SPECIALS.filter(fwOn);
      const wantSpecial = special.length && !busy && (Math.random() < FW_SPECIAL_CHANCE[FW.showpieces] || !regular.length);
      if (wantSpecial) shape = pick(special);
      else if (regular.length) shape = pick(regular);
      else return null;                            // only show-pieces are on, and one is already up
    }
    if (shape && typeof shape === "object") return launchDesign(shape, at?.x);
    if (FW_SPECIALS.includes(shape)) x = Math.max(W * 0.18, Math.min(W * 0.82, x));
    // A tree bursts low, just above the hill, and grows upwards from there.
    // A tree's rocket comes up out of the hill itself and bursts right at the surface.
    const surface = hill.length ? H - hill[Math.max(0, Math.min(hill.length - 1, Math.floor(x / 3)))] : groundY;
    const apex = at ? at.y : shape === "tree" ? surface - 2 : rand(H * 0.1, Math.min(H * 0.45, groundY - 40));
    const startY = shape === "tree" ? H + 2 : groundY + 4;
    const vy = -Math.sqrt(2 * G * Math.max(1, startY - apex));
    const colors = [pick(FW.colors)];
    if (Math.random() < 0.45 || shape === "crossette") colors.push(pick(FW.colors));
    if (shape === "willow" && Math.random() < 0.6) colors[0] = pick(["#ffcf5a", "#ffe9a8", "#ffb347"]);   // classic gold
    const r = { x, y: startY, vx: at ? 0 : rand(-0.12, 0.12), vy, shape, colors, target: at?.target || null,
      fade: Math.random() < 0.35 ? pick(FW.colors) : null, trail: Math.random() < 0.4, twinkle: Math.random() < 0.35 };
    if (shape === "creeper") r.colors = ["#7dff5c", "#5fe04a"];
    if (shape === "heart") r.colors = [pick(["#ff5a7a", "#ff8fc0", "#ff4f4f"])];
    rockets.push(r);
    return r;
  }

  // ---- custom fireworks from the Firework editor
  // A design is a bag of numbers (see app/fireworks.py); each rocket carries it to the burst.
  function launchDesign(d, atX) {
    const n = Math.max(1, Math.min(5, d.rockets || 1));
    const x0 = atX ?? rand(W * 0.2, W * 0.8);
    const first = rocketFor(d, x0 - ((n - 1) / 2) * 28);
    for (let k = 1; k < n; k++) setTimeout(() => { if (!stopped) { rocketFor(d, x0 + (k - (n - 1) / 2) * 28 + rand(-6, 6)); wake(); } }, k * rand(160, 320));
    return first;
  }
  function rocketFor(d, x) {
    x = Math.max(8, Math.min(W - 8, x));
    const top = H * 0.06, apex = groundY - (groundY - top) * Math.max(0.1, Math.min(1, d.height ?? 0.6)) + rand(-6, 6);
    const r = { x, y: groundY + 4, vx: rand(-0.06, 0.06), vy: -Math.sqrt(2 * G * Math.max(4, groundY + 4 - apex)), shape: "custom", design: d, colors: d.colors };
    rockets.push(r);
    return r;
  }
  function explodeCustom(r) {
    const d = r.design, S = d.size || 1.2, cols = d.colors?.length ? d.colors : ["#ffe45c"];
    const rt = { d, drag: 0.995 - (d.drag ?? 0.4) * 0.07, born: frame, hue: rand(0, 360) };
    const life = () => (d.life || 1.4) * 60 * rand(0.85, 1.15);
    const rot = rand(-1, 1) * (d.tilt || 0) * 1.2, cos = Math.cos(rot), sin = Math.sin(rot);
    const out = [];
    const colorFor = (i, n) => d.color_mode === "alternate" ? cols[i % cols.length] : d.color_mode === "mix" ? pick(cols) : cols[0];
    const spark = (vx, vy, i, n, extra = {}) => {
      const sq = d.pattern === "picture" || d.pattern === "spiral" ? 1 : d.squash ?? 1;
      const rx = vx * cos - vy * sin, ry = (vx * sin + vy * cos) * sq;
      out.push({ cd: rt, x: r.x, y: r.y, px: r.x, py: r.y, vx: rx, vy: ry, life: 0, max: life(), color: colorFor(i, n), hueOff: (i / n) * 360, ...extra });
    };
    const n = Math.max(8, Math.min(160, d.sparks || 48));
    const jitter = () => 1 - (d.spread || 0) * Math.random();
    if (d.flash > 0) {                               // the bright pop at the moment of the burst
      const m = Math.round(8 + d.flash * 26);
      for (let i = 0; i < m; i++) {
        const a = (i / m) * Math.PI * 2;
        sparks.push({ x: r.x, y: r.y, px: r.x, py: r.y, vx: Math.cos(a) * (0.6 + d.flash), vy: Math.sin(a) * (0.6 + d.flash), life: 0, max: rand(8, 14), color: "#ffffff" });
      }
    }
    if (d.pattern === "picture" && d.picture?.length) {
      const rows = d.picture.length, w = Math.max(...d.picture.map((row) => row.length)), k = 0.15 * S;
      const hold = 45 + (d.hold ?? 0.8) * 60;
      let i = 0;
      d.picture.forEach((row, y) => [...row].forEach((c, x) => {
        if (c === ".") return;
        const ox = x - (w - 1) / 2, oy = y - (rows - 1) / 2;
        spark(ox * k, oy * k, i++, 1, { hold, max: hold + life(), color: cols[+c] || cols[0] });
      }));
    } else if (d.pattern === "spiral") {
      const arms = Math.max(2, Math.min(6, d.arms || 3)), per = Math.max(4, Math.round(n / arms)), spin = (d.spin ?? 0.5) * 0.08 || 0.01, off = rand(0, Math.PI * 2);
      for (let a = 0; a < arms; a++) for (let j = 0; j < per; j++) {
        spark(0, 0, a * per + j, n, { orbit: { cx: r.x, cy: r.y, a: off + (a / arms) * Math.PI * 2 - j * 0.15 * Math.sign(spin), r: 0, dr: S * (0.3 + j * (1.2 / per)), da: spin } });
      }
    } else if (d.pattern === "palm") {
      const arms = Math.max(5, Math.min(12, Math.round(n / 6)));
      for (let i = 0; i < arms; i++) {
        const a = (i / arms) * Math.PI * 2 - Math.PI / 2 + rand(-0.1, 0.1);
        spark(Math.cos(a) * S * 1.15 * jitter(), Math.sin(a) * S * 1.15 * jitter() - 0.25, i, arms, { palm: true, max: life() * 1.2 });
      }
    } else {
      for (let i = 0; i < n; i++) {
        let a = (i / n) * Math.PI * 2, sp = S * jitter();
        if (d.pattern === "burst") { a = rand(0, Math.PI * 2); sp = S * rand(0.15, 1); }
        else if (d.pattern === "ring") { sp = S * (1 - (d.spread || 0) * 0.2 * Math.random()); }
        else if (d.pattern === "star") {
          const pts = Math.max(3, Math.min(10, d.points || 5)), k = ((a / (Math.PI * 2)) * pts) % 1;
          sp = S * (0.45 + 0.75 * (1 - Math.abs(k - 0.5) * 2)) * jitter();
          a -= Math.PI / 2;
        } else a += rand(-0.06, 0.06);
        spark(Math.cos(a) * sp, Math.sin(a) * sp * (d.pattern === "ring" ? 0.5 : 1), i, n);
      }
    }
    // Some pieces burst again a moment later.
    if (d.second > 0) for (const p of out) if (Math.random() < d.second) p.fuse = Math.round((d.second_delay || 0.5) * 60 * rand(0.85, 1.15));
    sparks.push(...out);
  }
  function customColor(p, t) {
    const d = p.cd.d, cols = d.colors?.length ? d.colors : ["#ffe45c"];
    if (d.color_mode === "rainbow") return `hsl(${(p.cd.hue + p.hueOff + p.life * 5) % 360} 100% 66%)`;
    if (d.color_mode === "change") {
      const list = cols.length > 1 ? cols : [cols[0], "#ffffff"];
      const f = Math.min(0.999, t) * (list.length - 1), k = Math.floor(f);
      return mix(list[k], list[k + 1], f - k);
    }
    return p.color;
  }
  // Returns false when the spark is used up (and has been removed).
  function stepCustom(p, i) {
    const rt = p.cd, d = rt.d;
    if (p.fuse && p.life >= p.fuse) {
      sparks.splice(i, 1);
      const cols = d.colors?.length ? d.colors : ["#ffe45c"], m = 14, sp = (d.size || 1.2) * (d.second_size || 0.6) * 0.55;
      const next = cols[(cols.indexOf(p.color) + 1) % cols.length] || cols[0];
      for (let k = 0; k < m; k++) {
        const a = (k / m) * Math.PI * 2 + rand(-0.1, 0.1);
        sparks.push({ cd: rt, x: p.x, y: p.y, px: p.x, py: p.y, vx: Math.cos(a) * sp + p.vx * 0.3, vy: Math.sin(a) * sp + p.vy * 0.3,
          life: 0, max: (d.life || 1.4) * 40 * rand(0.8, 1.1), color: next, hueOff: (k / m) * 360 });
      }
      return false;
    }
    if (p.orbit) {
      const o = p.orbit;
      o.a += o.da; o.r += o.dr; o.dr *= 0.962; o.cy += (0.03 + p.life * 0.001) * (d.gravity ?? 1);
      p.x = o.cx + Math.cos(o.a) * o.r; p.y = o.cy + Math.sin(o.a) * o.r * 0.9;
    } else {
      if (p.hold && p.life < p.hold) { p.vx *= 0.95; p.vy = p.vy * 0.95 + G * 0.04; }     // pictures hang in shape
      else { p.vx *= rt.drag; p.vy = p.vy * rt.drag + G * 0.55 * (d.gravity ?? 1); }
      p.x += p.vx; p.y += p.vy;
    }
    const t = p.life / p.max;
    const color = customColor(p, t);
    if ((d.trail > 0 || p.palm) && p.life % 2 === 0 && t < 0.85 && Math.random() < (p.palm ? 0.9 : d.trail)) {
      sparks.push({ x: p.x, y: p.y, px: p.x, py: p.y, vx: rand(-0.03, 0.03), vy: 0.05, life: 0, max: p.palm ? 22 : 14, color, ember: true });
    }
    if (d.glitter > 0 && t < 0.85 && Math.random() < d.glitter * 0.45) {
      sparks.push({ x: p.x, y: p.y, px: p.x, py: p.y, vx: rand(-0.03, 0.03), vy: rand(0.02, 0.09), life: 0, max: rand(40, 75),
        color: Math.random() < 0.45 ? "#fff3c4" : color, glitter: true, twinkle: true });
    }
    if (d.sparkle > 0 && t > 0.25 && Math.random() < d.sparkle * 0.6) return true;      // crackle
    let alpha = Math.min(1, 1.25 * (1 - t * t));
    const age = frame - rt.born;
    if (d.blink > 0 && Math.floor(age / Math.round(36 - d.blink * 30)) % 2) alpha *= 0.06;
    if (d.breathe > 0) alpha *= 1 - d.breathe * 0.75 * (0.5 + 0.5 * Math.sin(age * (0.06 + d.breathe * 0.1)));
    let fill = color;
    if (d.strobe > 0) {
      const roll = Math.random();
      if (roll < d.strobe * 0.3) { fill = "#ffffff"; alpha = 1; } else if (roll < d.strobe * 0.55) return true;
    }
    ctx.globalAlpha = alpha; ctx.fillStyle = fill;
    line(p.px, p.py, p.x, p.y);
    return true;
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
        add(Math.cos(a) * 1.15, Math.sin(a) * 1.15 - 0.2, 0, { sub: true, fuse: rand(24, 34), max: 60, trail: true, twinkle: false, fade: null, color2: r.colors[1] || pick(FW.colors) });
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
    ctx.clearRect(0, 0, W, H);
    for (const s of stars) {                         // slow twinkle
      ctx.globalAlpha = s.a * (0.65 + 0.35 * Math.sin(s.p + frame * 0.02));
      ctx.fillStyle = "#dfe6f5"; ctx.fillRect(s.x, s.y, 1, 1);
    }
    ctx.globalAlpha = 1;

    for (let i = rockets.length - 1; i >= 0; i--) {
      const r = rockets[i];
      r.x += r.vx; r.y += r.vy; r.vy += G;
      ctx.fillStyle = "#fff1c2"; ctx.fillRect(Math.round(r.x), Math.round(r.y), 1, 2);
      if (frame % 2 === 0) sparks.push({ x: r.x, y: r.y + 2, px: r.x, py: r.y + 2, vx: rand(-0.08, 0.08), vy: rand(0.1, 0.4), life: 0, max: rand(10, 20), color: "#ffb35c", ember: true });
      if (r.vy >= -0.15) { rockets.splice(i, 1); explode(r); }
    }

    for (let i = sparks.length - 1; i >= 0; i--) {
      const p = sparks[i];
      p.life++;
      if (p.life > p.max) { sparks.splice(i, 1); continue; }
      p.px = p.x; p.py = p.y;
      if (p.cd) { stepCustom(p, i); continue; }
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
        if (p.life < p.max * 0.85 && Math.random() < 0.42) {      // glitter left hanging behind: the drooping strands
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
      if (p.trail && !p.ember && p.life % (p.sub ? 2 : 3) === 0 && t < 0.8) {
        sparks.push({ x: p.x, y: p.y, px: p.x, py: p.y, vx: 0, vy: 0.05, life: 0, max: 14, color: p.fade || p.color, ember: true });
      }
    }
    ctx.globalAlpha = 1;
    updateTrees();
    updateFigures();
    ctx.drawImage(land, 0, 0);                        // hill and watchers in front of everything
  }

  // The loop only runs while something is moving: the automatic show is on, or rockets
  // and sparks are still in the air. Otherwise one quiet frame is drawn and it sleeps, so
  // the frosted panels on top don't have to re-blur every frame.
  let auto = opts.auto !== false;
  function loop() {
    if (!running) return;
    step();
    if (!auto && !rockets.length && !sparks.length && !figures.length && !trees.length) { running = false; frame = 0; step(); return; }
    raf = requestAnimationFrame(loop);
  }
  function wake() {
    if (running || stopped || document.hidden) return;
    running = true; loop();
  }
  function schedule() {
    clearTimeout(timer);
    if (!auto) return;
    timer = setTimeout(() => {
      if (!document.hidden && rockets.length < 6 && sparks.length < 1400) {
        launch();
        if (Math.random() < 0.25) setTimeout(launch, rand(150, 400));      // the occasional salvo
        if (Math.random() < 0.1) setTimeout(launch, rand(450, 700));
        wake();
      }
      schedule();
    }, rand(every()[0], every()[1]));
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
    rockets.length = 0; sparks.length = 0; figures.length = 0; trees.length = 0;
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
      stopped = true; running = false; ro?.disconnect(); cancelAnimationFrame(raf); clearTimeout(timer);
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

// A small floating control: launch a firework, and turn the automatic show on or off.
// The choice is remembered per page in this browser.
function skyControls(scene, key, defaultOn) {
  let on = defaultOn && !matchMedia("(prefers-reduced-motion: reduce)").matches;
  try { const v = localStorage.getItem(key); if (v != null) on = v === "1"; } catch { /* storage is optional */ }
  scene.setAuto(on);
  const box = document.createElement("div");
  box.className = "sky-ctl glass";
  box.innerHTML = `<button type="button" class="sky-launch" title="Launch a firework" aria-label="Launch a firework">🎆</button>
    <button type="button" class="sky-auto" aria-pressed="${on}" title="Keep launching fireworks"><span class="sky-sw"></span><span>Show</span></button>`;
  document.body.append(box);
  const autoBtn = box.querySelector(".sky-auto");
  box.querySelector(".sky-launch").addEventListener("click", () => scene.launch());
  autoBtn.addEventListener("click", () => {
    on = !on; scene.setAuto(on); autoBtn.setAttribute("aria-pressed", String(on));
    try { localStorage.setItem(key, on ? "1" : "0"); } catch { /* storage is optional */ }
  });
  return box;
}
