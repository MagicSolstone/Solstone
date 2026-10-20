/* Lodestone — sign-in page: public server status and the "lodestone" background.
   Pings appear at random spots; each sends four pixel lines out along the compass
   directions, which bend back and converge on the lodestone glow behind the card. */
"use strict";

const loginScene = { stop: null };

function startLoginScene() {
  stopLoginScene();
  const cv = document.getElementById("login-sky");
  const glow = document.getElementById("login-glow");
  const card = document.querySelector(".login-card");
  if (!cv || !card) return;
  const ctx = cv.getContext("2d");
  const SCALE = 3;                               // draw at 1/3 resolution, scale up crisp = pixel look
  const COLORS = ["#4d74d6", "#4d74d6", "#6f93ea", "#5fb59a", "#f2c14e"];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let W = 0, H = 0, T = { x: 0, y: 0 }, raf = 0, timer = 0, running = true;
  const parts = [], pings = [];

  function resize() {
    W = Math.ceil(innerWidth / SCALE); H = Math.ceil(innerHeight / SCALE);
    cv.width = W; cv.height = H;
    const r = card.getBoundingClientRect();
    T = { x: (r.left + r.width / 2) / SCALE, y: (r.top + Math.min(r.height, 360) / 2) / SCALE };
    if (glow) { glow.style.left = `${T.x * SCALE}px`; glow.style.top = `${T.y * SCALE}px`; }
  }

  function spawn() {
    if (parts.length > 64) return;
    const minD = Math.min(W, H) * 0.3;
    let x, y, tries = 0;
    do { x = 8 + Math.random() * (W - 16); y = 8 + Math.random() * (H - 16); tries++; }
    while (Math.hypot(x - T.x, y - T.y) < minD && tries < 25);
    const color = COLORS[Math.floor(Math.random() * COLORS.length)];
    const speed = 1.1 + Math.random() * 0.5;
    pings.push({ x: Math.round(x), y: Math.round(y), age: 0, color });
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      parts.push({ x, y, vx: dx * speed, vy: dy * speed, age: 0, color, trail: [[Math.round(x), Math.round(y)]], done: false });
    }
  }

  function plotLine(x0, y0, x1, y1) {          // Bresenham: unbroken pixel lines
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx + dy;
    for (let i = 0; i < 64; i++) {
      ctx.fillRect(x0, y0, 1, 1);
      if (x0 === x1 && y0 === y1) break;
      const e2 = 2 * err;
      if (e2 >= dy) { err += dy; x0 += sx; }
      if (e2 <= dx) { err += dx; y0 += sy; }
    }
  }

  const TRAIL = 34;
  function step() {
    ctx.clearRect(0, 0, W, H);

    for (let i = pings.length - 1; i >= 0; i--) {   // square ripple where a ping starts
      const p = pings[i]; p.age++;
      const r = Math.floor(p.age / 4);
      if (r > 6) { pings.splice(i, 1); continue; }
      ctx.globalAlpha = 0.9 * (1 - r / 7); ctx.strokeStyle = p.color; ctx.lineWidth = 1;
      ctx.strokeRect(p.x - r + 0.5, p.y - r + 0.5, r * 2, r * 2);
    }
    ctx.globalAlpha = 1;

    let arrived = 0;
    for (let i = parts.length - 1; i >= 0; i--) {
      const p = parts[i];
      if (!p.done) {
        p.age++;
        const dx = T.x - p.x, dy = T.y - p.y, dist = Math.hypot(dx, dy) || 1;
        // Out along the compass direction first, then steer toward home with growing
        // strength. Steering toward a desired velocity (not adding force) avoids orbits.
        const k = p.age < 20 ? 0 : Math.min(0.09, (p.age - 20) * 0.0016);
        const max = 2.2, want = Math.min(max, dist * 0.08 + 0.6);
        p.vx += ((dx / dist) * want - p.vx) * k;
        p.vy += ((dy / dist) * want - p.vy) * k;
        p.x += p.vx; p.y += p.vy;
        const last = p.trail[p.trail.length - 1], nx = Math.round(p.x), ny = Math.round(p.y);
        if (nx !== last[0] || ny !== last[1]) p.trail.push([nx, ny]);
        if (dist < 2.5 || p.age > 600) { p.done = true; if (dist < 2.5) arrived++; }
      }
      if (p.trail.length > TRAIL || (p.done && p.trail.length)) p.trail.shift();
      if (p.done && p.trail.length < 2) { parts.splice(i, 1); continue; }
      // Draw the trail, fading toward its tail.
      ctx.fillStyle = p.color;
      const n = p.trail.length;
      for (let t = 1; t < n; t++) {
        ctx.globalAlpha = (t / n) * 0.95;
        plotLine(p.trail[t - 1][0], p.trail[t - 1][1], p.trail[t][0], p.trail[t][1]);
      }
      ctx.globalAlpha = 1;
    }
    if (arrived && glow) { glow.classList.remove("pulse"); void glow.offsetWidth; glow.classList.add("pulse"); }
  }

  function loop() {
    if (!running) return;
    step();
    raf = requestAnimationFrame(loop);
  }
  function schedule() {
    timer = setTimeout(() => { if (!document.hidden) spawn(); schedule(); }, 650 + Math.random() * 700);
  }
  const onVis = () => {
    if (document.hidden) { running = false; cancelAnimationFrame(raf); }
    else if (!reduced && !running) { running = true; loop(); }
  };

  resize();
  addEventListener("resize", resize);
  document.addEventListener("visibilitychange", onVis);
  if (reduced) {
    // A single still frame: a few paths mid-flight, no motion.
    for (let k = 0; k < 4; k++) spawn();
    for (let i = 0; i < 70; i++) step();
    running = false;
  } else {
    for (let k = 0; k < 3; k++) spawn();
    loop(); schedule();
  }
  loginScene.stop = () => {
    running = false; cancelAnimationFrame(raf); clearTimeout(timer);
    removeEventListener("resize", resize); document.removeEventListener("visibilitychange", onVis);
  };
}

function stopLoginScene() { if (loginScene.stop) { loginScene.stop(); loginScene.stop = null; } }

async function loadPublicStatus() {
  const box = document.getElementById("login-servers");
  if (!box) return;
  let data;
  try { data = await (await fetch("/api/public/status")).json(); } catch { return; }
  if (!data.show_servers || !data.servers?.length) { box.hidden = true; return; }
  box.hidden = false;
  box.innerHTML = `<h2>Servers</h2><ul>${data.servers.map((s) => {
    const on = s.running !== false;
    const status = !on ? (s.crashed ? "Crashed" : "Offline") : s.online ? `${s.online}${s.max ? ` of ${s.max}` : ""} playing` : "Online · nobody playing";
    const w = s.world;
    const world = w ? `Day ${w.day.toLocaleString()} · ${w.phase}${w.weather ? ` · ${w.weather}` : ""}${w.paused ? " (paused)" : ""}` : "";
    const meta = [s.game && s.game !== "Minecraft Java" ? s.game : s.version ? `Minecraft ${s.version}` : "", world].filter(Boolean).join(" · ");
    const icon = s.has_icon ? `<img src="/api/public/icon/${encodeURIComponent(s.id)}.png" alt="">` : esc((s.name || "?")[0]);
    return `<li><span class="server-icon">${icon}<span class="status-dot ${s.crashed ? "crash" : on ? "on" : ""}"></span></span>
      <div><div class="ls-name">${esc(s.name)}</div><div class="ls-status ${on && s.online ? "live" : ""}">${esc(status)}</div>
      ${meta ? `<div class="ls-meta">${esc(meta)}</div>` : ""}
      ${s.names?.length ? `<div class="ls-names">${s.names.map((n) => `<span><img src="https://mc-heads.net/avatar/${encodeURIComponent(n)}/32" alt="" onerror="this.remove()">${esc(n)}</span>`).join("")}</div>` : ""}</div></li>`;
  }).join("")}</ul>`;
}
