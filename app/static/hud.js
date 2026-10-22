/* Solstone — small drawing helpers shared by the app and the public status page:
   HTML escaping, pixel hearts / hunger / XP bar, and Minecraft MOTD colours. */
"use strict";

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ================================================================ pixel HUD icons
const HEART = [".##.##.", "#######", "#######", ".#####.", "..###..", "...#..."];
const FOOD = [".....##.", "....####", "...#####", "...####.", "..##....", ".##.....", "#.#.....", ".#......"];
function pixelSvg(pattern, fillFn, title = "") {
  const h = pattern.length, w = pattern[0].length;
  const filled = (x, y) => y >= 0 && y < h && x >= 0 && x < w && pattern[y][x] === "#";
  let rects = "";
  for (let y = -1; y <= h; y++) for (let x = -1; x <= w; x++) {
    if (!filled(x, y) && (filled(x - 1, y) || filled(x + 1, y) || filled(x, y - 1) || filled(x, y + 1)))
      rects += `<rect x="${x + 1}" y="${y + 1}" width="1" height="1" fill="#111"/>`;
  }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++)
    if (filled(x, y)) rects += `<rect x="${x + 1}" y="${y + 1}" width="1" height="1" fill="${fillFn(x, y, w, h)}"/>`;
  return `<svg viewBox="0 0 ${w + 2} ${h + 2}" shape-rendering="crispEdges" aria-hidden="true">${title ? `<title>${esc(title)}</title>` : ""}${rects}</svg>`;
}
function heartsHtml(health, max = 20) {
  // Mods can raise max health a lot; past 20 hearts, scale to 20 and show the number.
  const label = `Health ${health} of ${max}`;
  let extra = "";
  if (max > 40) { extra = `<span class="hp-num">${Math.round(health)} / ${Math.round(max)}</span>`; health = (health / max) * 40; max = 40; }
  const n = Math.ceil(max / 2);
  let out = "";
  for (let i = 0; i < n; i++) {
    const v = health - i * 2; // 2 = full, 1 = half
    out += pixelSvg(HEART, (x, y, w) => {
      const red = v >= 2 || (v >= 1 && x < Math.ceil(w / 2));
      if (!red) return "#3a1414";
      return x === 1 && y === 1 ? "#ffb3a8" : "#e0302a";
    });
  }
  return `<div class="hud-row hearts" role="img" aria-label="${label}">${out}${extra}</div>`;
}
function foodHtml(food) {
  let out = "";
  for (let i = 0; i < 10; i++) {
    const v = food - i * 2;
    out += pixelSvg(FOOD, (x, y, w) => {
      const on = v >= 2 || (v >= 1 && x >= 4);
      if (!on) return "#3a2a1a";
      if (x <= 2 && y >= 5) return "#f1e7d0";
      return y <= 1 || (x === 4 && y === 2) ? "#e8a05a" : "#b3602a";
    });
  }
  return `<div class="hud-row food" role="img" aria-label="Hunger ${food} of 20">${out}</div>`;
}
function xpHtml(level, progress) {
  return `<div class="xp" role="img" aria-label="Level ${level}"><span class="lvl-num">${level}</span><div class="xp-bar"><span style="width:${Math.round((progress || 0) * 100)}%"></span></div></div>`;
}

// ================================================================ MOTD colours
const MC_COLORS = { 0: "#000", 1: "#00a", 2: "#0a0", 3: "#0aa", 4: "#a00", 5: "#a0a", 6: "#fa0", 7: "#aaa", 8: "#555", 9: "#55f", a: "#5f5", b: "#5ff", c: "#f55", d: "#f5f", e: "#ff5", f: "#fff" };
function motdHtml(text) {
  if (!text) return "";
  const parts = String(text).split(/§([0-9a-fk-or])/i);
  let out = esc(parts[0]), color = null, bold = false, italic = false;
  for (let i = 1; i < parts.length; i += 2) {
    const code = parts[i].toLowerCase(), chunk = parts[i + 1] || "";
    if (MC_COLORS[code]) { color = MC_COLORS[code]; bold = italic = false; }
    else if (code === "l") bold = true;
    else if (code === "o") italic = true;
    else if (code === "r") { color = null; bold = italic = false; }
    if (chunk) out += `<span style="${color ? `color:${color};` : ""}${bold ? "font-weight:700;" : ""}${italic ? "font-style:italic;" : ""}">${esc(chunk)}</span>`;
  }
  return out;
}


// ================================================================ leaderboard numbers
// One way to show a leaderboard value, used by the app and the status page alike.
function fmtStat(kind, v) {
  v = Number(v) || 0;
  const n = (x, d = 0) => new Intl.NumberFormat([], { maximumFractionDigits: d }).format(x);
  if (kind === "ticks") {
    const s = Math.floor(v / 20), d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : m ? `${m}m` : `${s}s`;
  }
  if (kind === "cm") { const m = v / 100; return m >= 1000 ? `${n(m / 1000, m >= 100000 ? 0 : 1)} km` : `${Math.round(m)} m`; }
  if (kind === "hearts") return `${n(v / 20)} ♥`;
  if (kind === "grams") {                         // a fish's weight, in pounds and ounces
    const oz = v / 28.349523125;
    if (oz < 16) return `${n(oz, oz < 10 ? 1 : 0)} oz`;
    const lb = Math.floor(oz / 16), rest = Math.round(oz - lb * 16);
    return lb >= 100 || !rest || rest === 16 ? `${n(rest === 16 ? lb + 1 : lb)} lb` : `${lb} lb ${rest} oz`;
  }
  return n(v);
}

// ================================================================ player heads
// Heads are cut from the player's skin file: Solstone's own copy straight from Mojang
// first, with mc-heads (looked up by name) underneath as a backup. The face and the hat
// layer are separate layers of the same image; the initial shows if neither loads.
let skinSource = (p) => p.uuid ? `/api/skins/${String(p.uuid).replace(/-/g, "")}.png` : null;
const backupSkin = (p) => `https://mc-heads.net/skin/${p.name ? encodeURIComponent(p.name) : String(p.uuid || "").replace(/-/g, "")}`;
// name (lowercase) -> UUID for players Solstone knows; filled after sign-in so a head drawn
// from just a name still uses the real skin rather than a name lookup (Steve for unknown names).
const knownUuids = {};
function faceHtml(p, size, cls = "") {
  const initial = esc((p.name || "?")[0].toUpperCase());
  if (!p.uuid && p.name && knownUuids[String(p.name).toLowerCase()]) p = { ...p, uuid: knownUuids[String(p.name).toLowerCase()] };
  const main = skinSource(p);
  return `<span class="face ${cls}" style="--s:${size}px;--skin:${main ? `url('${main}')` : "none"};--skin2:url('${backupSkin(p)}')" aria-hidden="true"><span class="face-init">${initial}</span></span>`;
}
