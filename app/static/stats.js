/* Solstone — a server's stats over time (Leaderboards → Server stats): what everyone did, day by day, kept for good.
   Server-wide only, no names. Totals for a range, one chart at a time (pick what to chart), when people play,
   and a few records. Loaded after app.js. */
"use strict";

// what's charted: [key, label, icon, how a number reads, how it adds up over a week or month]
const ST_KEYS = [
  ["play_hours", "Hours played", "⏱️", (v) => `${stNum(v, v < 10 ? 1 : 0)} h`, "sum"],
  ["mobs", "Monsters defeated", "⚔️", (v) => stNum(v), "sum"],
  ["travelled", "Distance travelled", "🧭", (v) => (v >= 1000 ? `${stNum(v / 1000, 1)} km` : `${stNum(v)} blocks`), "sum"],
  ["mined", "Blocks dug", "⛏️", (v) => stNum(v), "sum"],
  ["placed", "Blocks placed", "🧱", (v) => stNum(v), "sum"],
  ["logs", "Logs chopped", "🪓", (v) => stNum(v), "sum"],
  ["crops", "Crops harvested", "🌾", (v) => stNum(v), "sum"],
  ["fish", "Fish caught", "🎣", (v) => stNum(v), "sum"],
  ["deaths", "Deaths", "💀", (v) => stNum(v), "sum"],
  ["advancements", "Advancements", "🏆", (v) => stNum(v), "sum"],
  ["chat", "Chat messages", "💬", (v) => stNum(v), "sum"],
  ["trades", "Villager trades", "💰", (v) => stNum(v), "sum"],
  ["bred", "Animals bred", "🐄", (v) => stNum(v), "sum"],
  ["events", "Contests, races and games", "🎉", (v) => stNum(v), "sum"],
  ["new_players", "New players", "🌱", (v) => stNum(v), "sum"],
  ["players", "Players in a day", "👥", (v) => stNum(v), "max"],
  ["peak", "Most on at once", "📈", (v) => stNum(v), "max"],
];
const ST_TILES = ["play_hours", "mobs", "travelled", "mined", "logs", "fish", "deaths", "advancements"];
// a fun way to picture a total
const ST_FUN = {
  travelled: (v) => (v >= 42195 ? `≈ ${stNum(v / 42195, 1)} marathons` : v >= 1000 ? `≈ ${stNum(v / 400, 0)} laps of a running track` : ""),
  mined: (v) => (v >= 2500 ? `≈ ${stNum(v / 2500, 1)} Olympic pools of blocks` : ""),
  logs: (v) => (v >= 20 ? `about ${stNum(v / 5)} trees` : ""),
  play_hours: (v) => (v >= 24 ? `${stNum(v / 24, 1)} days of non-stop play` : ""),
  mobs: (v) => (v >= 64 ? `${stNum(v / 64, 1)} stacks of 64` : ""),
  deaths: (v) => (v ? `${v === 1 ? "one respawn" : `${stNum(v)} respawns`}` : "nobody's died"),
};
const ST_RANGES = [["30", "30 days"], ["90", "90 days"], ["365", "Year"], ["all", "All time"]];
const ST_GROUPS = [["day", "By day"], ["week", "By week"], ["month", "By month"]];
const stv = { range: "90", group: "day", key: "play_hours", running: false, data: null, heatFor: null };

function stNum(v, dp = 0) {
  return Number(v || 0).toLocaleString([], { maximumFractionDigits: dp, minimumFractionDigits: 0 });
}
const stKey = (k) => ST_KEYS.find((x) => x[0] === k) || ST_KEYS[0];
const stDate = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
const stIso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function stInRange(days) {
  if (stv.range === "all") return days;
  const from = new Date(); from.setHours(0, 0, 0, 0); from.setDate(from.getDate() - (+stv.range - 1));
  const lo = stIso(from);
  return days.filter((d) => d.day >= lo);
}
// days into buckets (a day, the week starting Monday, or the month), each with the chosen key added up (or its best)
function stBuckets(days, key, group, how) {
  const out = [];
  for (const d of days) {
    const dt = stDate(d.day);
    let label = d.day;
    if (group === "week") { const m = new Date(dt); m.setDate(dt.getDate() - ((dt.getDay() + 6) % 7)); label = stIso(m); }
    if (group === "month") label = d.day.slice(0, 7);
    let b = out[out.length - 1];
    if (!b || b.label !== label) { b = { label, v: 0, from: d.day, to: d.day }; out.push(b); }
    const v = Number(d[key] || 0);
    b.v = how === "max" ? Math.max(b.v, v) : b.v + v;
    b.to = d.day;
  }
  return out;
}
const stLabel = (b, group, long = false) => {
  const d = stDate(group === "month" ? `${b.label}-01` : b.label);
  if (group === "month") return d.toLocaleDateString([], { month: long ? "long" : "short", year: "numeric" });
  const day = d.toLocaleDateString([], { month: "short", day: "numeric" });
  return group === "week" ? (long ? `Week of ${day}` : day) : (long ? d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", year: "numeric" }) : day);
};
// a round top for the axis: 1, 2 or 5 times a power of ten
function stNice(max) {
  if (max <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(max)), f = max / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

function stChartHtml(buckets, k) {
  const [key, label, , fmt, how] = k;
  const running = stv.running && how === "sum";
  let acc = 0;
  const vals = buckets.map((b) => (running ? (acc += b.v) : b.v));
  const W = 760, H = 240, L = 46, R = 8, T = 10, B = 26, n = Math.max(1, vals.length);
  const top = stNice(Math.max(...vals, 0)), x0 = L, iw = W - L - R, ih = H - T - B;
  const y = (v) => T + ih - (v / top) * ih;
  const grid = [0, 0.5, 1].map((f) => `<line x1="${L}" x2="${W - R}" y1="${y(top * f)}" y2="${y(top * f)}" class="st-grid"/>
      <text x="${L - 6}" y="${y(top * f) + 4}" class="st-axis" text-anchor="end">${esc(fmt(top * f))}</text>`).join("");
  const step = iw / n, bw = Math.max(2, Math.min(28, step - 2));
  const every = Math.max(1, Math.ceil(n / 7));
  const xl = buckets.map((b, i) => (i % every === 0 || i === n - 1 ? `<text x="${x0 + step * i + step / 2}" y="${H - 8}" class="st-axis" text-anchor="middle">${esc(stLabel(b, stv.group))}</text>` : "")).join("");
  const tip = (b, i) => `${stLabel(b, stv.group, true)}: ${fmt(vals[i])}${running ? " in all" : ""}`;
  const hits = buckets.map((b, i) => `<rect class="st-hit" x="${x0 + step * i}" y="${T}" width="${step}" height="${ih}" data-tip="${esc(tip(b, i))}" data-i="${i}"/>`).join("");
  let marks;
  if (running) {
    const pts = vals.map((v, i) => `${x0 + step * i + step / 2},${y(v)}`).join(" ");
    marks = `<polyline class="st-line" points="${pts}"/>${vals.length < 60 ? vals.map((v, i) => `<circle class="st-dot" cx="${x0 + step * i + step / 2}" cy="${y(v)}" r="3"/>`).join("") : ""}`;
  } else {
    marks = vals.map((v, i) => {
      const h = Math.max(0, (v / top) * ih), r = Math.min(4, bw / 2, h);
      const bx = x0 + step * i + (step - bw) / 2, by = T + ih - h;
      return v > 0 ? `<path class="st-bar" data-b="${i}" d="M${bx},${T + ih} V${by + r} Q${bx},${by} ${bx + r},${by} H${bx + bw - r} Q${bx + bw},${by} ${bx + bw},${by + r} V${T + ih} Z"/>` : "";
    }).join("");
  }
  const total = how === "max" ? Math.max(...buckets.map((b) => b.v), 0) : buckets.reduce((t, b) => t + b.v, 0);
  return `<div class="st-chart-head"><h3>${esc(label)}</h3><span class="muted">${how === "max" ? "Best" : "In all"}: <b>${esc(fmt(total))}</b></span></div>
    <div class="st-chart" role="img" aria-label="${esc(label)}, ${esc(ST_GROUPS.find(([g]) => g === stv.group)[1].toLowerCase())}">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}${marks}${xl}${hits}</svg><div class="st-tip" hidden></div></div>`;
}

function stHeatHtml(heat) {
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const max = Math.max(...heat.flat(), 0);
  if (!max) return `<p class="muted">Nobody's played in this time yet.</p>`;
  const hour = (h) => new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" });
  const cells = heat.map((row, d) => `<div class="st-hrow"><span class="st-hday">${days[d]}</span>${row.map((v, h) => {
    const f = v / max;
    return `<span class="st-cell" style="--f:${f ? (0.12 + 0.88 * f).toFixed(2) : 0}" data-tip="${esc(`${days[d]} ${hour(h)}: ${stNum(v, 1)} h played`)}"></span>`;
  }).join("")}</div>`).join("");
  let best = [0, 0];
  heat.forEach((row, d) => row.forEach((v, h) => { if (v > heat[best[0]][best[1]]) best = [d, h]; }));
  const byDay = heat.map((row) => row.reduce((a, b) => a + b, 0)), topDay = byDay.indexOf(Math.max(...byDay));
  const fullDays = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"];
  return `<p class="st-heat-note">Busiest on <b>${fullDays[topDay]}</b>; the busiest hour is around <b>${hour(best[1])}</b> on ${fullDays[best[0]]}.</p>
    <div class="st-heat">${cells}<div class="st-hrow st-hours"><span class="st-hday"></span>${Array.from({ length: 24 }, (_, h) => `<span>${h % 6 === 0 ? esc(hour(h)) : ""}</span>`).join("")}</div></div>
    <p class="muted small">Brighter: more hours played then.</p>`;
}

function stRecords(days, rec) {
  const best = (key) => days.reduce((b, d) => ((d[key] || 0) > (b?.[key] || 0) ? d : b), null);
  const longDay = (d) => stDate(d.day).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  const rows = [
    ["players", "👥", "Busiest day", (d) => `${stNum(d.players)} players`],
    ["peak", "📈", "Most on at once", (d) => `${stNum(d.peak)} players`],
    ["play_hours", "⏱️", "Most hours played in a day", (d) => `${stNum(d.play_hours, 1)} h`],
    ["mobs", "⚔️", "Biggest monster-fighting day", (d) => `${stNum(d.mobs)} defeated`],
    ["mined", "⛏️", "Biggest digging day", (d) => `${stNum(d.mined)} blocks`],
    ["travelled", "🧭", "Farthest travelled in a day", (d) => stKey("travelled")[3](d.travelled)],
  ].map(([k, icon, what, say]) => { const d = best(k); return d ? `<li><span aria-hidden="true">${icon}</span><span>${what}</span><b>${esc(say(d))}</b><span class="muted small">${esc(longDay(d))}</span></li>` : ""; }).join("");
  const longest = rec?.longest_session_hours ? `<li><span aria-hidden="true">🛌</span><span>Longest time on in one go</span><b>${stNum(rec.longest_session_hours, 1)} h</b><span class="muted small">all time</span></li>` : "";
  return rows || longest ? `<ul class="st-records">${rows}${longest}</ul>` : `<p class="muted">Records show up once people have played.</p>`;
}

async function viewStats(sid) {
  const s = await serverFrame(sid, "stats");
  const since = () => (stv.range === "all" ? 0 : Date.now() / 1000 - +stv.range * 86400);
  const load = async () => {
    stv.data = await api(`/api/servers/${encodeURIComponent(sid)}/stats/history?since=${Math.floor(since())}`);
    stv.heatFor = stv.range;
  };
  if (!stv.data || stv.sid !== sid || stv.heatFor !== stv.range) { await load(); stv.sid = sid; }
  const draw = () => {
    const all = stv.data.days, days = stInRange(all);
    const seg = (name, opts, cur) => `<div class="seg" role="group" aria-label="${name}">${opts.map(([v, l]) => `<button type="button" data-${name}="${v}" aria-pressed="${v === cur}">${l}</button>`).join("")}</div>`;
    const sum = (key) => days.reduce((t, d) => t + Number(d[key] || 0), 0), allSum = (key) => all.reduce((t, d) => t + Number(d[key] || 0), 0);
    const tiles = ST_TILES.map((key) => {
      const [, label, icon, fmt] = stKey(key), v = sum(key), fun = ST_FUN[key]?.(v) || "";
      return `<button type="button" class="st-tile ${stv.key === key ? "on" : ""}" data-key="${key}" aria-pressed="${stv.key === key}">
        <span class="st-tile-label"><span aria-hidden="true">${icon}</span> ${esc(label)}</span><b>${esc(fmt(v))}</b>
        <small class="muted">${esc(fun)}${stv.range !== "all" ? `${fun ? " · " : ""}${esc(fmt(allSum(key)))} all time` : ""}</small></button>`;
    }).join("");
    const k = stKey(stv.key);
    const empty = !all.length;
    const first = all[0]?.day;
    setView(serverHeader(s, "stats") + (empty ? `<div class="empty"><h3>No stats yet</h3><p>They build up as people play: what everyone does each day is kept here for good.</p></div>` : `
      <div class="st-filters">${seg("range", ST_RANGES, stv.range)}${seg("group", ST_GROUPS, stv.group)}
        <span class="muted small">Since ${esc(stDate(first).toLocaleDateString([], { month: "long", day: "numeric", year: "numeric" }))}. The whole server, no names.</span></div>
      <div class="st-tiles">${tiles}</div>
      <section class="panel st-panel">
        <div class="st-pick"><label class="small">Chart <select class="input sm" id="st-key">${ST_KEYS.map(([kk, l, ic]) => `<option value="${kk}" ${kk === stv.key ? "selected" : ""}>${ic} ${esc(l)}</option>`).join("")}</select></label>
          ${k[4] === "sum" ? `<label class="check small"><input type="checkbox" id="st-running" ${stv.running ? "checked" : ""}> Running total</label>` : ""}</div>
        ${stChartHtml(stBuckets(days, k[0], stv.group, k[4]), k)}
      </section>
      <div class="st-two">
        <section class="panel st-panel"><h3>When people play</h3>${stHeatHtml(stv.data.heat)}</section>
        <section class="panel st-panel"><h3>Records</h3>${stRecords(all, stv.data.records)}<p class="muted small">All time, best days.</p></section>
      </div>`));
    const v = view();
    v.querySelectorAll("[data-range]").forEach((b) => b.addEventListener("click", async () => { stv.range = b.dataset.range; await load(); draw(); }));
    v.querySelectorAll("[data-group]").forEach((b) => b.addEventListener("click", () => { stv.group = b.dataset.group; draw(); }));
    v.querySelectorAll("[data-key]").forEach((b) => b.addEventListener("click", () => { stv.key = b.dataset.key; draw(); }));
    $("#st-key")?.addEventListener("change", (e) => { stv.key = e.target.value; draw(); });
    $("#st-running")?.addEventListener("change", (e) => { stv.running = e.target.checked; draw(); });
    // hover: the exact number for a bar, a point or an hour
    v.querySelectorAll(".st-chart, .st-heat").forEach((box) => {
      const tipEl = box.querySelector(".st-tip") || box.appendChild(Object.assign(document.createElement("div"), { className: "st-tip", hidden: true }));
      const show = (e) => {
        const t = e.target.closest("[data-tip]");
        if (!t) { tipEl.hidden = true; box.querySelectorAll(".st-hover").forEach((x) => x.classList.remove("st-hover")); return; }
        tipEl.textContent = t.dataset.tip; tipEl.hidden = false;
        const r = box.getBoundingClientRect(), x = (e.clientX ?? r.left) - r.left;
        tipEl.style.left = `${Math.min(Math.max(8, x - tipEl.offsetWidth / 2), r.width - tipEl.offsetWidth - 8)}px`;
        box.querySelectorAll(".st-hover").forEach((x2) => x2.classList.remove("st-hover"));
        t.classList.add("st-hover");
        if (t.dataset.i != null) box.querySelector(`.st-bar[data-b="${t.dataset.i}"]`)?.classList.add("st-hover");
      };
      box.addEventListener("pointermove", show);
      box.addEventListener("pointerdown", show);
      box.addEventListener("pointerleave", () => { tipEl.hidden = true; });
    });
  };
  draw();
}
