/* Solstone — the pixel night sky shared by every page: twinkling stars, a dark blocky
   hill with a small figure and their dog watching, and Minecraft-style fireworks. */
"use strict";

// Minecraft dye colours, brightened the way firework stars look in-game.
const FW_COLORS = ["#ff5a4f", "#ffa13d", "#ffe45c", "#9be34a", "#4fd7e6", "#5d8bff", "#c46cf0", "#ff8fc0", "#ffffff", "#3fd1b0"];
const FW_SHAPES = ["ball", "ball", "large", "star", "burst", "ring", "cube", "pickaxe", "axe"];
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

function startSkyScene(cv, opts = {}) {
  // opts.avoid: element to launch beside; opts.every: [min, max] ms between launches;
  // opts.still: draw one quiet frame (stars and hill only) and never animate.
  const card = opts.avoid || null;
  const every = opts.every || [700, 1900];
  const ctx = cv.getContext("2d");
  const SCALE = 3;                                  // low-res canvas scaled up = crisp pixels
  const G = 0.03;                                   // gravity, low-res px per frame²
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  const rand = (a, b) => a + Math.random() * (b - a);
  let W = 0, H = 0, raf = 0, timer = 0, running = true, frame = 0;
  let stars = [], land = null, groundY = 0, cardBox = null;
  const rockets = [], sparks = [];

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
    W = Math.ceil(innerWidth / SCALE); H = Math.ceil(innerHeight / SCALE);
    cv.width = W; cv.height = H;
    stars = Array.from({ length: Math.round((W * H) / 700) }, () => ({ x: Math.floor(Math.random() * W), y: Math.floor(Math.random() * H * 0.7), p: Math.random() * 6.28, a: rand(0.15, 0.55) }));
    buildLand();
    const r = card ? card.getBoundingClientRect() : null;
    cardBox = r ? { l: r.left / SCALE, r: r.right / SCALE, t: r.top / SCALE } : null;
  }

  // ---- fireworks
  function launch() {
    // Favour the open sky beside the sign-in card so most bursts are visible.
    let x;
    const sides = cardBox ? [[W * 0.06, cardBox.l - 10], [cardBox.r + 10, W * 0.94]].filter(([a, b]) => b - a > 20) : [];
    if (sides.length && Math.random() < 0.8) { const [a, b] = pick(sides); x = rand(a, b); } else x = rand(W * 0.1, W * 0.9);
    const apex = rand(H * 0.1, Math.min(H * 0.45, groundY - 40));
    const vy = -Math.sqrt(2 * G * (groundY + 4 - apex));
    const colors = [pick(FW_COLORS)];
    if (Math.random() < 0.45) colors.push(pick(FW_COLORS));
    rockets.push({ x, y: groundY + 4, vx: rand(-0.12, 0.12), vy, shape: pick(FW_SHAPES), colors,
      fade: Math.random() < 0.35 ? pick(FW_COLORS) : null, trail: Math.random() < 0.4, twinkle: Math.random() < 0.35 });
  }

  function explode(r) {
    const add = (vx, vy, i, extra = {}) => sparks.push({ x: r.x, y: r.y, px: r.x, py: r.y, vx, vy, life: 0, max: rand(55, 85) * (r.shape === "large" ? 1.3 : 1),
      color: r.colors[i % r.colors.length], fade: r.fade, trail: r.trail, twinkle: r.twinkle, ...extra });
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
      if (p.shaped) { p.vx *= 0.95; p.vy = p.vy * 0.95 + G * (p.life > 45 ? 0.35 : 0.04); }   // hold the shape, then fall
      else { p.vx *= 0.975; p.vy = p.vy * 0.975 + G * (p.ember ? 0.3 : 0.55); }
      p.x += p.vx; p.y += p.vy;
      const t = p.life / p.max;
      if (p.twinkle && t > 0.35 && Math.random() < 0.45) continue;      // crackle
      ctx.globalAlpha = p.ember ? 0.7 * (1 - t) : Math.min(1, 1.25 * (1 - t * t));
      ctx.fillStyle = p.fade && t > 0.4 ? mix(p.color, p.fade, Math.min(1, (t - 0.4) / 0.4)) : p.color;
      line(p.px, p.py, p.x, p.y);
      if (p.trail && !p.ember && p.life % 3 === 0 && t < 0.8) {
        sparks.push({ x: p.x, y: p.y, px: p.x, py: p.y, vx: 0, vy: 0.05, life: 0, max: 14, color: p.fade || p.color, ember: true });
      }
    }
    ctx.globalAlpha = 1;
    ctx.drawImage(land, 0, 0);                        // hill and watchers in front of everything
  }

  function loop() {
    if (!running) return;
    step();
    raf = requestAnimationFrame(loop);
  }
  function schedule() {
    timer = setTimeout(() => {
      if (!document.hidden && rockets.length < 6 && sparks.length < 1400) {
        launch();
        if (Math.random() < 0.25) setTimeout(launch, rand(150, 400));      // the occasional salvo
        if (Math.random() < 0.1) setTimeout(launch, rand(450, 700));
      }
      schedule();
    }, rand(every[0], every[1]));
  }
  const onVis = () => {
    if (document.hidden) { running = false; cancelAnimationFrame(raf); }
    else if (!reduced && !running) { running = true; loop(); }
  };
  const onResize = () => { resize(); if (reduced) still(); };
  function still() {
    // One quiet frame: two bursts frozen mid-air, no motion.
    rockets.length = 0; sparks.length = 0;
    for (let k = 0; k < 2; k++) { launch(); const r = rockets.pop(); r.y = rand(H * 0.15, H * 0.35); explode(r); }
    for (let i = 0; i < 18; i++) step();
  }

  const quiet = () => { ctx.clearRect(0, 0, W, H); rockets.length = 0; sparks.length = 0; frame = 0; step(); };
  resize();
  if (opts.still) {
    const onStill = () => { resize(); quiet(); };
    quiet();
    addEventListener("resize", onStill);
    return { stop: () => removeEventListener("resize", onStill), celebrate() {} };
  }
  addEventListener("resize", onResize);
  document.addEventListener("visibilitychange", onVis);
  if (reduced) { running = false; still(); }
  else { launch(); setTimeout(launch, 500); loop(); schedule(); }
  return {
    stop() {
      running = false; cancelAnimationFrame(raf); clearTimeout(timer);
      removeEventListener("resize", onResize); document.removeEventListener("visibilitychange", onVis);
    },
    // A salvo, e.g. when someone joins. Skipped for reduced motion and hidden tabs.
    celebrate(n = 3) {
      if (reduced || document.hidden) return;
      for (let i = 0; i < n; i++) setTimeout(launch, i * rand(180, 420));
    },
  };
}

