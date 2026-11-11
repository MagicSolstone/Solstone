/* Solstone — the public home page and its posts (News, Guides, FAQ). No sign-in.
   Everything comes from /api/public/site and /api/public/posts; private servers never appear there.
   Post text is a small subset of Markdown, escaped first and then formatted, so it can't carry HTML. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const hp = { site: null };
// Two kinds of page: News (what's happening) and Help (guides, then questions and answers).
const SECTIONS = { news: ["News", "news"], help: ["News & Help", "help"], events: ["Events", "events"] };

// Old bookmarks into the app (/#/s/...) still work: the app lives at /app now.
if (location.hash.startsWith("#/")) location.replace(`/app${location.hash}`);

async function getJSON(url) {
  const r = await fetch(url, { credentials: "same-origin", cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

function toast(text, html = false) {
  const t = $("#hp-toast");
  if (html) t.innerHTML = text; else t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, html ? 6000 : 2500);
}

// Post text is turned into HTML by postfmt.js (shared with the post editor's live preview).

// ------------------------------------------------------------------ pieces
const dateText = (ts) => new Date(ts * 1000).toLocaleDateString([], { year: "numeric", month: "long", day: "numeric" });
const CAT_LABEL = { news: "News", guide: "Guide", faq: "FAQ" };

// The mods a player's own Minecraft needs for a modded server, folded away until wanted.
function modsHtml(m) {
  if (!m || !m.list?.length) return "";
  const head = `${m.list.length} ${m.list.length === 1 ? "mod" : "mods"} for ${esc([m.loader, m.mc && `Minecraft ${m.mc}`].filter(Boolean).join(" · "))}`;
  const dl = m.download ? `<div class="hp-pack"><a class="btn primary sm" href="${esc(m.download)}" download>⬇ Download the modpack</a>
      <details><summary>How to install it</summary><ol>
        <li>Get <a href="https://prismlauncher.org" target="_blank" rel="noopener">Prism Launcher</a> (free, for Windows, Mac and Linux) and sign in with your Microsoft account.</li>
        <li>Download the modpack (the button above). It's one <b>.mrpack</b> file.</li>
        <li>In Prism, choose <b>Add Instance</b>, then <b>Import</b>, pick the file, and choose <b>OK</b>. Prism sets up the right Minecraft, Fabric and every mod.</li>
        <li>Launch it, then join the server from <b>Multiplayer</b>.</li></ol>
        <p class="muted small">The Modrinth App and CurseForge can import the file too. When the mods change, download it again and import the new one.</p></details></div>` : "";
  return `${dl}<details class="hp-mods"><summary>🧩 ${head}</summary>
    <ul>${m.list.map((x) => `<li>${x.link ? `<a href="${esc(x.link)}" target="_blank" rel="noopener">${esc(x.name)}</a>` : esc(x.name)}${x.version ? ` <span class="muted small">${esc(x.version)}</span>` : ""}${x.kind && x.kind !== "mod" ? ` <span class="chip">${esc(x.kind === "resourcepack" ? "Resource pack" : x.kind === "shader" ? "Shader" : x.kind)}</span>` : ""}</li>`).join("")}</ul></details>`;
}

// How long since a time ("2 d 4 h"), for "up for".
function sinceText(started) {
  const since = typeof started === "number" ? started : started ? new Date(String(started).replace(" ", "T")).getTime() : NaN;
  if (!Number.isFinite(since)) return "";
  const m = Math.max(0, Math.floor((Date.now() - since) / 60000)), d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m % 60} min` : `${m} min`;
}

// The servers' status at the top of the home page: up or down, how many are playing (never who), how smoothly it
// runs, its version, how long it's been up, and what it's using. The same for everyone; refreshed while it's open.
// Today on the server, added up (never who): a line of small counts, so the page feels alive.
const TODAY_BITS = [["players", "👥", (n) => (n === 1 ? "player" : "players")], ["mobs", "⚔️", () => "mobs defeated"],
  ["mined", "⛏️", () => "blocks dug"], ["logs", "🪓", () => "logs chopped"], ["crops", "🌾", () => "crops harvested"],
  ["placed", "🧱", () => "blocks placed"], ["fish", "🎣", () => "fish caught"], ["advancements", "🏅", (n) => (n === 1 ? "advancement" : "advancements")],
  ["travelled", "🧭", () => "travelled"]];
function todayHtml(t) {
  const num = (k, n) => (k === "travelled" ? fmtDist(n) : n.toLocaleString());       // km or miles, as the site's set
  const bits = TODAY_BITS.filter(([k]) => t?.[k]).map(([k, icon, say]) => `<span class="hp-today-bit">${icon} <b>${esc(num(k, t[k]))}</b> ${esc(say(t[k]))}</span>`);
  return bits.length > 1 ? `<p class="hp-today"><span class="hp-today-label">Today</span>${bits.join("")}</p>` : "";
}

// A little line graph of the last few hours (gaps where the server was off), for a status tile.
function sparkline(values, lo, hi, label) {
  const v = values || [];
  if (v.filter((x) => x != null).length < 2) return "";
  const W = 120, H = 28, n = v.length, top = Math.max(hi, ...v.filter((x) => x != null)), span = top - lo || 1;
  const pts = v.map((x, i) => (x == null ? null : [(i / (n - 1)) * W, H - 2 - ((x - lo) / span) * (H - 4)]));
  const runs = [];
  let cur = [];
  for (const p of pts) { if (p) cur.push(p); else if (cur.length) { runs.push(cur); cur = []; } }
  if (cur.length) runs.push(cur);
  const path = runs.map((r) => (r.length === 1 ? `M${r[0][0].toFixed(1)} ${r[0][1].toFixed(1)}h1` : `M${r.map((p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("L")}`)).join("");
  const last = pts.filter(Boolean).pop();
  return `<svg class="hp-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(label)}"><path d="${path}"/>${last ? `<circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.2"/>` : ""}</svg>`;
}

// In the world right now: the time of day and the weather (the clock ticks on by itself between refreshes).
function worldStrip(w) {
  if (!w) return "";
  const t = mcNow(w), phase = mcPhase(t);
  return `<div class="hp-world hp-world-${phase.toLowerCase()} ${w.thunder ? "storm" : w.rain ? "rain" : ""}" data-world='${esc(JSON.stringify(w))}'>
    <span class="hp-world-emoji" aria-hidden="true">${mcEmoji(t, w)}</span>
    <span class="hp-world-text"><small>In the world right now</small><b class="hp-world-clock">${esc(mcClock(t))}</b><span>${esc(phase)} · ${esc(mcWeather(w))}</span>
      ${w.ticking ? "" : `<span class="hp-world-paused">⏸ Time's paused while nobody's playing</span>`}</span></div>`;
}
setInterval(() => {                          // a game minute is under a second: keep the clocks moving
  document.querySelectorAll(".hp-world[data-world]").forEach((el) => {
    try { const w = JSON.parse(el.dataset.world); if (w.ticking) el.outerHTML = worldStrip(w); } catch { /* next time */ }
  });
}, 2500);
function statusPanel(site) {
  if (!site.servers?.length) return "";
  const card = (s) => {
    // each card opens its story further back (tap or click); Minecraft's version has none
    const tile = (label, value, hint = "", spark = "", what = "") => {
      const inner = `<span class="hp-stat-label">${esc(label)}</span><b>${value}</b>${hint ? `<small class="muted">${esc(hint)}</small>` : ""}${spark}`;
      return what ? `<button type="button" class="hp-stat hp-stat-btn" data-hist="${esc(what)}" data-sid="${esc(s.id)}" data-name="${esc(s.name)}" title="More about ${esc(label.toLowerCase())}">${inner}</button>`
        : `<div class="hp-stat">${inner}</div>`;
    };
    if (!s.running) return `<article class="hp-status-card off"><header><span class="hp-dot"></span><h3>${esc(s.name)}</h3><span class="hp-status-word">Offline</span></header>
      <p class="muted small">It's not running right now.${s.uptime_7d != null ? ` Up ${Math.round(s.uptime_7d * 1000) / 10}% of the last 7 days.` : ""}
        <button type="button" class="link-btn" data-hist="uptime" data-sid="${esc(s.id)}" data-name="${esc(s.name)}">See its uptime</button></p></article>`;
    const tps = s.tps == null ? null : Number(s.tps);
    const smooth = tps == null ? "" : tps >= 19.5 ? "Smooth" : tps >= 15 ? "A little laggy" : "Laggy";
    const tr = s.trend || {}, hrs = `the last ${tr.hours || 6} hours`;
    const tiles = [
      tile("Playing now", `${s.online}${s.max ? ` <small>/ ${s.max}</small>` : ""}`, "", sparkline(tr.players, 0, 4, `Players over ${hrs}`)
        + (s.online ? `<span class="hp-eds">${s.online - (s.on_bedrock || 0) ? `<span>${edIcon("java", 12)} ${s.online - (s.on_bedrock || 0)} on Java</span>` : ""}${s.on_bedrock ? `<span>${edIcon("bedrock", 12)} ${s.on_bedrock} on Bedrock</span>` : ""}</span>` : ""), "players"),
      tps != null ? tile("TPS", tps.toFixed(1), `${smooth}${s.mspt != null ? ` · ${Number(s.mspt).toFixed(0)} ms a tick` : ""}`, sparkline(tr.tps, 0, 20, `TPS over ${hrs}`), "tps") : "",
      s.version ? tile("Minecraft", esc(s.version), s.loader ? s.loader.charAt(0).toUpperCase() + s.loader.slice(1) : "") : "",
      s.up_since ? tile("Up for", esc(sinceText(s.up_since * 1000)), s.uptime_7d != null ? `${Math.round(s.uptime_7d * 1000) / 10}% of the last 7 days` : "", "", "uptime") : "",
      s.cpu != null ? tile("CPU", `${Math.round(Number(s.cpu))}%`, s.cpu_cores ? `of its ${+s.cpu_cores} core${+s.cpu_cores === 1 ? "" : "s"}` : "", sparkline(tr.cpu, 0, 100, `CPU over ${hrs}`), "cpu") : "",
      s.mem ? tile("Memory", esc(s.mem), s.mem_percent != null ? `${Math.round(Number(s.mem_percent))}% of the computer's RAM` : "",
        sparkline(tr.mem_mb, 0, Math.max(0, ...(tr.mem_mb || []).filter((x) => x != null)) * 1.15, `Memory over ${hrs}`), "mem_mb") : "",
    ].join("");
    return `<article class="hp-status-card"><header><span class="hp-dot on"></span><h3>${esc(s.name)}</h3><span class="hp-status-word">Online</span></header>
      ${worldStrip(s.world)}<div class="hp-stats">${tiles}</div>${todayHtml(s.today)}${tr.players ? `<p class="hp-spark-note muted small">Graphs: ${esc(hrs)}</p>` : ""}</article>`;
  };
  return `<section class="hp-status" id="hp-status" aria-label="Server status"><div class="hp-status-cards ${site.servers.length > 1 ? "many" : ""}">${site.servers.map(card).join("")}</div></section>`;
}

function joinCard(site) {
  // One card per server: what it is, how it's doing, and how to get on it.
  // Each way in by edition: Java on PC or Mac (the address), Bedrock everywhere else. On Bedrock the friend's
  // gamertag comes first when there is one (it works on every device, consoles too); the address is the other way.
  const copyBtn = (v, what) => `<button class="btn sm" type="button" data-copy="${esc(v)}" aria-label="Copy the ${what}">Copy</button>`;
  const javaBlock = (j) => `<div class="hp-ed-block java">
      <div class="hp-ed-head">${edIcon("java", 20)}<b>Java Edition</b><span class="muted">PC or Mac</span>${j.version ? `<span class="chip hp-ver" title="Launch this version">${esc(j.version)}</span>` : ""}</div>
      <div class="hp-join-row"><code class="hp-addr">${esc(j.java)}</code>${copyBtn(j.java, "address")}</div>
      <p class="hp-how muted small">Multiplayer → Add Server → paste the address.</p></div>`;
  const consoleSlug = site.guide_posts?.consoles;
  const consoleHelp = (down) => (consoleSlug ? `<p class="hp-how small ${down ? "hp-console-down" : "muted"}">🎮 On a console${down ? " while the friend is down" : ""}? <a href="/post/${encodeURIComponent(consoleSlug)}">Here's another way in</a></p>` : "");
  const bedrockBlock = (j) => {
    const server = j.bedrock ? `<div class="hp-join-row"><code class="hp-addr">${esc(j.bedrock)}</code><span class="hp-port">Port <b>${esc(String(j.bedrock_port))}</b></span>${copyBtn(j.bedrock, "address")}</div>` : "";
    return `<div class="hp-ed-block bedrock">
      <div class="hp-ed-head">${edIcon("bedrock", 20)}<b>Bedrock Edition</b><span class="muted">phones, tablets, consoles, Windows</span></div>
      ${j.xbox ? `<div class="hp-friend">${edIcon("friend", 22)}<span class="hp-friend-label">Add as a friend</span><span class="hp-gt-tag">Gamertag:</span><code class="hp-gamertag">${esc(j.xbox)}</code>${copyBtn(j.xbox, "gamertag")}</div>
        ${xboxStateHtml(j.xbox_status)}
        <p class="hp-how muted small">Then Play → Friends, and join the server from there. Works on every device, consoles too.</p>
        ${server ? `<details class="hp-alt" ${j.xbox_status?.state === "down" ? "open" : ""}><summary>Or add it as a server <span class="hp-devices">phones, tablets and Windows</span></summary>${server}<p class="hp-how muted small">Play → Servers → Add Server. Consoles can't add servers: on Xbox, PlayStation or Switch, join through the friend above.</p></details>` : ""}
        ${consoleHelp(j.xbox_status?.state === "down")}`
      : `${server}<p class="hp-how muted small">Phones, tablets and Windows: Play → Servers → Add Server, with the address and port. Consoles can't add servers.</p>${consoleHelp(false)}`}</div>`;
  };
  const cards = (site.joins || []).map((j) => {
    const icon = j.status?.has_icon ? `<img class="px" src="/api/public/icon/${encodeURIComponent(j.id)}.png" alt="" width="40" height="40">` : "";
    return `<article class="hp-join-card ${j.main ? "main" : ""}" ${j.color ? `style="--accent:${esc(j.color)}"` : ""}>
      <header>${icon}<div><h3>${esc(j.name)}</h3></div></header>
      <div class="hp-ed-blocks">${j.java ? javaBlock(j) : ""}${j.xbox || j.bedrock ? bedrockBlock(j) : ""}</div>
      ${j.note ? `<p class="hp-join-note">${esc(j.note)}</p>` : ""}${modsHtml(j.mods)}
</article>`;
  });
  if (!cards.length) return "";
  const servers = `<div class="hp-join-cards ${cards.length > 1 ? "many" : ""}">${cards.join("")}</div>`;
  const discord = site.discord ? `<p class="muted">Questions? <a href="${esc(site.discord)}" target="_blank" rel="noopener">Join us on Discord</a></p>` : "";
  // Signed in already (or nothing to ask for): just how to get on.
  if (hp.me || (!site.join_requests && !site.signup)) return `<section class="hp-join glass"><h2>Join the server${cards.length > 1 ? "s" : ""}</h2>${servers}${discord}</section>`;
  // New here: the steps, one after another, each a button on this page.
  const steps = [];
  if (site.join_requests) steps.push(`<li class="hp-step" id="step-ask"><span class="hp-step-dot">1</span><div class="hp-step-body">
      <h3>Ask to join</h3><div class="muted" data-step-text>The server only lets in people on its list. Send your name, and an admin will add you.</div>
      <button class="btn primary hp-ask-btn glow" type="button" data-open-ask>🙋 Ask to join</button></div></li>`);
  steps.push(`<li class="hp-step" id="step-play"><span class="hp-step-dot">${steps.length + 1}</span><div class="hp-step-body">
      <h3 data-step-title>Get in the game</h3><p class="muted" data-step-text>${site.join_requests ? "Once you're let in, join with the address for your Minecraft:" : "Join with the address for your Minecraft:"}</p>
      ${servers}</div></li>`);
  if (site.signup) steps.push(`<li class="hp-step" id="step-account"><span class="hp-step-dot">${steps.length + 1}</span><div class="hp-step-body">
      <h3>Make your website account</h3><p class="muted">While you're playing, we send a code to your game chat. Then pick a password, and you're in here too.</p>
      <button class="btn hp-step-btn" type="button" data-open-signup>🌐 Make a website account</button>
      <p class="muted small">Have one already? <a href="/app">Sign in</a></p></div></li>`);
  return `<section class="hp-join glass"><h2>Get started</h2><ol class="hp-steps">${steps.join("")}</ol>${discord}</section>`;
}

// The step-by-step on the home page follows a request that's out: waiting, then let in.
function stepState(list) {
  const ask = $("#step-ask"), play = $("#step-play");
  if (!ask || !play) return;
  const all = (Array.isArray(list) ? list : list ? [list] : []).filter(Boolean);
  const has = (st) => all.some((d) => d.state === st);
  const anyIn = has("in") || has("partly");
  ask.classList.toggle("done", anyIn && !has("waiting"));
  ask.classList.toggle("waiting", has("waiting"));
  ask.classList.toggle("denied", all.length > 0 && all.every((d) => d.state === "denied"));
  play.classList.toggle("now", anyIn);
  const btn = $(".hp-ask-btn", ask), text = $("[data-step-text]", ask);
  btn.hidden = all.length > 0;                        // (the list below has its own "ask for someone else")
  const row = (d) => {
    const x = `<button type="button" class="link-btn" data-ask-forget="${esc(d.token)}">Clear</button>`;
    const cancel = `<button type="button" class="link-btn" data-ask-cancel="${esc(d.token)}" data-player="${esc(d.player)}">Cancel</button>`;
    return `<li class="hp-ask-row ${esc(d.state)}">${d.state === "waiting" ? `<span class="spin" aria-hidden="true"></span> <b>${esc(d.player)}</b>: waiting for an admin ${cancel}`
      : d.state === "in" ? `✅ <b>${esc(d.player)}</b> is on the list. Join the game below! ${x}`
      : d.state === "partly" ? `✅ <b>${esc(d.player)}</b> is in on some servers, and waiting on the rest. ${cancel}`
      : `<span class="hp-denied">✋ <b>${esc(d.player)}</b> wasn't accepted this time.</span>${d.reason ? ` <span class="hp-admin-says"><small>The admins said:</small> ${esc(d.reason)}</span>` : ""} ${x}`}</li>`;
  };
  text.innerHTML = all.length
    ? `<ul class="hp-ask-list">${all.map(row).join("")}</ul>
       ${has("waiting") ? '<span class="muted small">You can leave this page: we\'ll show it here when you come back.</span>' : ""}
       <span class="hp-step-acts"><button type="button" class="btn sm" data-open-ask>🙋 Ask for someone else${all.length ? " (or another account)" : ""}</button></span>`
    : "The server only lets in people on its list. Send your name, and an admin will add you.";
  $("[data-step-title]", play).textContent = has("waiting") && !anyIn ? "Then get in the game" : anyIn ? "You're in! Join the game" : "Get in the game";
}

// A status card's story further back: a bigger line over a day, a week or a month, or (uptime) every day's share
// and each time it went down, like a status page. Counts and times only: nothing about who.
const HIST = {
  players: { title: "Players", fmt: (v) => `${Math.round(v)}`, lo: 0, note: "The most playing at once, in each stretch." },
  tps: { title: "TPS", fmt: (v) => v.toFixed(1), lo: 0, hi: 20, note: "20 is perfectly smooth. Below 15 you'd notice lag." },
  cpu: { title: "CPU", fmt: (v) => `${Math.round(v)}%`, lo: 0, hi: 100, note: "How hard the server's working. At a game host, 100% is everything its plan gives it (all its cores); on a computer of your own, 100% is one whole core." },
  mem_mb: { title: "Memory", fmt: (v) => (v >= 1024 ? `${(v / 1024).toFixed(2)} GB` : `${Math.round(v)} MB`), lo: 0, note: "Java grabs memory and gives it back slowly, so a high flat line is normal." },
  uptime: { title: "Uptime" },
};
const HIST_SPANS = [[1, "24 hours"], [7, "7 days"], [30, "30 days"]];
function bigChart(d, h) {
  const v = d.values || [], have = v.filter((x) => x != null);
  if (have.length < 2) return `<p class="muted">Not enough to draw yet: Solstone checks every 30 seconds while the server's running.</p>`;
  const W = 520, H = 160, P = 4, n = v.length, lo = h.lo ?? Math.min(...have), top = Math.max(h.hi ?? 0, ...have) * (h.hi ? 1 : 1.12), span = top - lo || 1;
  const xy = (x, i) => [P + (i / (n - 1)) * (W - 2 * P), H - P - ((x - lo) / span) * (H - 2 * P)];
  const runs = [];
  let cur = [];
  v.forEach((x, i) => { if (x == null) { if (cur.length) runs.push(cur); cur = []; } else cur.push(xy(x, i)); });
  if (cur.length) runs.push(cur);
  const line = runs.map((r) => (r.length === 1 ? `M${r[0][0].toFixed(1)} ${r[0][1].toFixed(1)}h2` : `M${r.map((p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("L")}`)).join("");
  const area = runs.filter((r) => r.length > 1).map((r) => `M${r[0][0].toFixed(1)} ${H - P}L${r.map((p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("L")}L${r[r.length - 1][0].toFixed(1)} ${H - P}Z`).join("");
  const when = (t) => new Date(t * 1000).toLocaleString([], d.days === 1 ? { hour: "numeric", minute: "2-digit" } : { month: "short", day: "numeric" });
  return `<figure class="hist-chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(h.title)} over the last ${esc(HIST_SPANS.find((x) => x[0] === d.days)[1])}">
      <line x1="0" x2="${W}" y1="${H - P}" y2="${H - P}" class="hist-base"/><path class="hist-area" d="${area}"/><path class="hist-line" d="${line}"/></svg>
    <figcaption><span>${esc(when(d.start))}</span><span>${d.days === 1 ? "now" : "today"}</span></figcaption></figure>
    <div class="hist-nums"><span><small>Lowest</small><b>${esc(h.fmt(d.low))}</b></span><span><small>Average</small><b>${esc(h.fmt(d.average))}</b></span><span><small>Highest</small><b>${esc(h.fmt(d.high))}</b></span></div>
    <p class="muted small">${esc(h.note)} Gaps are when it wasn't running.</p>`;
}
const pct = (x) => (x == null ? "–" : `${(Math.floor(x * 1000) / 10).toFixed(x >= 0.9995 ? 0 : 1)}%`);
function longFor(secs) {
  const m = Math.round(secs / 60);
  if (m < 1) return "under a minute";
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60), r = m % 60;
  if (h < 48) return `${h} h${r ? ` ${r} min` : ""}`;
  return `${Math.floor(h / 24)} days ${h % 24} h`;
}
function uptimeView(d) {
  const day = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  // green: up all day (quick restarts don't count); yellow: down under 30 minutes; red: down 30 minutes or more
  const tone = (b) => (b.up == null ? "none" : !b.down_secs ? "good" : b.down_secs < 1800 ? "ok" : "bad");
  const bars = d.bars.map((b) => `<span class="ut-bar ${tone(b)}" title="${esc(day(b.day))}: ${b.up == null ? "not watched" : b.down_secs ? `down ${longFor(b.down_secs)} (up ${pct(b.up)})` : `up all day (${pct(b.up)})`}"></span>`).join("");
  const at = (t) => new Date(t * 1000).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const kinds = { down: ["🔴", "Down"], restart: ["🔁", "Restarted"], unwatched: ["⚪", "Not watched"] };
  const rows = d.outages.map((o) => {
    const [icon, word] = kinds[o.kind] || kinds.down;
    return `<li class="ut-out ${esc(o.kind)}"><span aria-hidden="true">${icon}</span><span><b>${word}</b> ${o.to ? `for ${esc(longFor(o.secs))}` : `<b class="ut-now">now</b>, for ${esc(longFor(o.secs))} so far`}
      <small class="muted">${esc(at(o.from))}${o.to ? ` → back ${esc(at(o.to))}` : ""}</small></span></li>`;
  }).join("");
  return `<div class="hist-nums"><span><small>24 hours</small><b>${pct(d.percent["24h"])}</b></span><span><small>7 days</small><b>${pct(d.percent["7d"])}</b></span><span><small>30 days</small><b>${pct(d.percent["30d"])}</b></span></div>
    <div class="ut-bars" style="--n:${d.bars.length}" role="img" aria-label="Each day's uptime">${bars}</div>
    <div class="ut-legend muted small"><span><i class="ut-bar good"></i> All day</span><span><i class="ut-bar ok"></i> Down under 30 min</span><span><i class="ut-bar bad"></i> Down 30 min or more</span><span><i class="ut-bar none"></i> Not watched</span></div>
    <h3 class="hist-h">Times it went down</h3>
    ${rows ? `<ul class="ut-outs">${rows}</ul>` : `<p class="muted">✅ Not once in the last ${esc(HIST_SPANS.find((x) => x[0] === d.days)[1])}.</p>`}
    <p class="muted small">🔁 A restart is back within 5 minutes (like the nightly one). ⚪ Not watched: Solstone itself was off or updating while the server kept going, so it doesn't count against the server. If the whole machine restarted (the server started again meanwhile), that's counted as down.</p>`;
}
let histAsk = 0;                                   // (only the last one asked for is shown)
async function openHistory(sid, what, name, days = what === "uptime" ? 30 : 1) {
  const h = HIST[what];
  if (!h) return;
  const tabs = HIST_SPANS.map(([n, label]) => `<button type="button" class="chip-btn ${n === days ? "on" : ""}" data-hist-days="${n}" aria-pressed="${n === days}">${label}</button>`).join("");
  const frame = (body) => `<h2>${esc(h.title)} <small class="muted">· ${esc(name)}</small></h2><div class="hist-tabs" role="group" aria-label="How far back">${tabs}</div><div class="hist-body">${body}</div>`;
  const wire = (box) => box.addEventListener("click", (e) => {
    const b = e.target.closest("[data-hist-days]");
    if (b) openHistory(sid, what, name, Number(b.dataset.histDays));
  });
  if (!$("#hp-pop")?.open) openPop(frame(`<p class="muted"><span class="spin" aria-hidden="true"></span> Looking back…</p>`), wire);
  else { const box = $("#hp-pop .hp-pop-body"); box.innerHTML = frame(`<p class="muted"><span class="spin" aria-hidden="true"></span> Looking back…</p>`); }
  const ask = ++histAsk;
  let d;
  try {
    const r = await fetch(`/api/public/site/history?sid=${encodeURIComponent(sid)}&what=${encodeURIComponent(what)}&days=${days}`);
    if (!r.ok) throw new Error();
    d = await r.json();
  } catch { $("#hp-pop .hist-body").innerHTML = `<p class="muted">Couldn't look that up just now. Try again in a moment.</p>`; return; }
  const body = $("#hp-pop .hist-body");
  if (body && ask === histAsk) body.innerHTML = what === "uptime" ? uptimeView(d) : bigChart(d, h);
}
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-hist]");
  if (t) openHistory(t.dataset.sid, t.dataset.hist, t.dataset.name);
});

// Pop-ups on the home page (Ask to join, Make an account): a <dialog>, closed with ×, Esc or a click outside.
function openPop(html, wire) {
  let d = $("#hp-pop");
  if (!d) {
    d = document.createElement("dialog"); d.id = "hp-pop"; d.className = "hp-pop glass";
    d.addEventListener("click", (e) => { if (e.target === d || e.target.closest("[data-pop-close]")) d.close(); });
    document.body.append(d);
  }
  d.innerHTML = `<button type="button" class="hp-pop-x" data-pop-close aria-label="Close">×</button><div class="hp-pop-body">${html}</div>`;
  d.showModal();
  wire?.($(".hp-pop-body", d));
  $("input:not([type=radio]):not([type=checkbox])", d)?.focus();
}
const closePop = () => $("#hp-pop")?.close();

async function postJSON(url, body) {
  const r = await fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Solstone": "1" }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "That didn't work. Try again in a moment.");
  return d;
}

// Making a website account: their name (they must be in the game), a code sent to their game chat, then a password.
function openSignup() {
  let player = "";
  const step1 = (note = "") => `<h2>Make a website account</h2>
    <p class="muted">Join the server first and stay in the game. We'll send a code to your game chat, so only you can see it.</p>
    <form id="su-start" autocomplete="off"><label>Your name in the game <small>Exactly as it shows. Bedrock names may start with a dot, like .Steve</small>
      <input class="input" name="player" required maxlength="18" autocapitalize="off" value="${esc(player)}"></label>
      <p class="login-error" role="alert">${note}</p>
      <div class="actions"><button type="button" class="btn" data-pop-close>Cancel</button><button class="btn primary" type="submit">Send me a code</button></div></form>`;
  const step2 = (msg) => `<h2>Check the game chat</h2><p class="hp-pop-ok">📨 ${esc(msg)}</p>
    <form id="su-finish" autocomplete="off"><label>The six-digit code<input class="input" name="code" inputmode="numeric" maxlength="7" required autocomplete="one-time-code"></label>
      <p class="su-login">You'll sign in with your Minecraft name, <b>${esc(player)}</b>, and the password you pick now.</p>
      <label>Pick a password <small>8 or more characters. Not the one for your Microsoft account.</small><input class="input" type="password" name="password" minlength="8" required autocomplete="new-password"></label>
      <label>Your first name <small>Optional. Only the admins see it, so they know who you are.</small><input class="input" name="real_name" maxlength="40" autocomplete="given-name"></label>
      <p class="login-error" role="alert"></p>
      <div class="actions"><button type="button" class="btn" data-su-back>Send a new code</button><button class="btn primary" type="submit">Make my account</button></div></form>`;
  openPop(step1(), (box) => {
    const wire1 = () => $("#su-start", box).addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = $("button[type=submit]", e.target), err = $(".login-error", e.target);
      player = new FormData(e.target).get("player").trim();
      btn.disabled = true; err.textContent = "";
      try {
        const r = await postJSON("/api/public/signup/start", { player });
        if (r.state === "offline") { err.textContent = r.message; btn.disabled = false; return; }
        if (r.player) player = r.player;
        render2(r.message);
      } catch (x) { err.textContent = x.message; btn.disabled = false; }
    });
    const render2 = (msg) => {
      box.innerHTML = step2(msg);
      $("[data-su-back]", box).addEventListener("click", () => { box.innerHTML = step1(); wire1(); $("input", box).focus(); });
      $("#su-finish", box).addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = new FormData(e.target);
        try {
          await postJSON("/api/public/signup/finish", { player, code: f.get("code"), password: f.get("password"), real_name: f.get("real_name") || "" });
          box.innerHTML = `<h2>🎉 Welcome, ${esc(player)}!</h2><p>Your account is ready, and you're signed in.</p>
            <div class="actions"><a class="btn primary" href="/app">Go to the servers</a><button type="button" class="btn" data-pop-close>Stay here</button></div>`;
          $("#hp-pop").addEventListener("close", () => location.reload(), { once: true });
        } catch (x) { $(".login-error", e.target).textContent = x.message; }
      });
      $("#su-finish input", box).focus();
    };
    wire1();
  });
}

function postCards(posts, empty) {
  if (!posts.length) return `<p class="muted">${esc(empty)}</p>`;
  return `<div class="hp-posts">${posts.map((p) => `<a class="hp-post glass ${p.image ? "has-pic" : ""}" href="${p.builtin ? `/guides/${p.slug}` : `/post/${encodeURIComponent(p.slug)}`}">
    ${p.image ? `<img class="hp-post-pic" src="${esc(p.image)}" alt="" loading="lazy">` : ""}
    <span class="hp-post-meta">${p.builtin ? "Guide · Start here" : `${esc(CAT_LABEL[p.category] || "")}${p.pinned ? " · 📌" : ""} · ${esc(dateText(p.created))}`}</span>
    <h3>${esc(p.title)}</h3><p class="muted">${esc(fillPostVars(p.excerpt || "", hp.site))}</p></a>`).join("")}</div>`;
}

function faqList(posts) {
  if (!posts.length) return `<p class="muted">No questions yet.</p>`;
  return `<div class="hp-faq">${posts.map((p) => `<details class="glass"><summary>${esc(p.title)}</summary>
    <div class="hp-body" data-faq="${esc(p.slug)}"><p class="muted">Loading…</p></div></details>`).join("")}</div>`;
}

// ------------------------------------------------------------------ built-in guides
// Their wording is in guides.js (admins can rewrite them in Website → Guides).
const BUILTIN = GUIDES;

// Solstone's own guides, except where a post stands in for one (it's listed with the other posts instead).
function builtinCards() {
  return Object.entries(BUILTIN).filter(([k]) => !hp.site.guide_posts?.[k] && guideOn(hp.site, k))
    .map(([k, g]) => ({ slug: k, title: g.title, excerpt: g.excerpt, builtin: true }));
}

// ------------------------------------------------------------------ pages
async function home() {
  const s = hp.site;
  // a few of each (Site details says how many), and a button to the rest when there are more
  const nNews = s.home_news ?? 3, nGuides = s.home_guides ?? 4;
  hp.me = await getJSON("/api/auth/me").then((d) => d.user || null, () => null);
  const [news, guides] = await Promise.all([nNews ? getJSON(`/api/public/posts?category=news&limit=${nNews + 1}`) : [],
    nGuides ? getJSON(`/api/public/posts?category=guide&limit=${nGuides + 1}`) : []]);
  const help = [...builtinCards(), ...guides];
  const more = (list, n, href, label) => (list.length > n ? `<div class="hp-more"><a class="btn" href="${href}">${label} →</a></div>` : "");
  return `${s.home_title ? `<section class="hp-hero"><h1>${esc(s.name)}</h1>${s.tagline ? `<p class="hp-tagline">${esc(s.tagline)}</p>` : ""}</section>` : ""}
    <p class="hp-ask-status" id="ask-status" hidden></p>
    ${statusPanel(s)}
    ${joinCard(s)}
    ${nNews ? `<section><div class="hp-head"><h2>News</h2><a href="/help#news">All news →</a></div>${postCards(news.slice(0, nNews), "No news yet.")}${more(news, nNews, "/help#news", "More news")}</section>` : ""}
    ${nGuides ? `<section><div class="hp-head"><h2>Help</h2><a href="/help">All guides and questions →</a></div>${postCards(help.slice(0, nGuides), "")}${more(help, nGuides, "/help", "More guides and questions")}</section>` : ""}
    ${s.about ? `<section class="hp-about glass"><h2>About</h2><div class="hp-body">${markdown(s.about)}</div></section>` : ""}`;
}

// What's planned, for everyone (no names: nobody's sign-up). Signed in, the app's Events page has more.
async function eventsPage() {
  const d = await getJSON("/api/public/upcoming");
  const row = (it) => (it.kind === "event" ? upEventHtml(it) : `<li class="up-item ${it.live ? "live" : ""} ${it.then ? "up-then" : ""}${upLook(it).cls}"${upLook(it).style}><span class="up-emoji" aria-hidden="true">${esc(it.emoji || "•")}</span>
    <div class="up-main"><b>${upTitle(it)}</b>${it.then ? "" : `<span class="muted small">${esc([it.server, it.detail, it.days > 1 ? `${it.days} days` : ""].filter(Boolean).join(" · "))}</span>`}
      ${it.about ? `<span class="up-about">${esc(it.about).split("\n").map(inline).join("<br>")}</span>` : ""}${rewardLineHtml(it.reward)}</div>
    <span class="up-when">${it.live ? "On now" : it.time ? esc(it.time) : ""}</span></li>`);
  return `<section><h1>Events</h1><p class="muted">Contests, races, games and holidays coming up. <a href="/app#/events">Sign in</a> to say you're coming and see who else is.</p></section>
    ${d.items.length ? `<section>${upTimeline(d.items, row, "glass")}</section>`
      : '<section class="glass hp-empty"><p class="muted">Nothing planned yet. Check back soon!</p></section>'}
    ${upPastHtml(d.past, "glass")}`;
}

async function section(key) {
  if (key === "events") return eventsPage();
  if (key === "help") {
    // News and Help together: what's new, then the guides, then questions (only when there are some)
    const [news, guides, faq] = await Promise.all([getJSON("/api/public/posts?category=news&limit=100"),
      getJSON("/api/public/posts?category=guide&limit=100"), getJSON("/api/public/posts?category=faq&limit=100")]);
    const help = [...builtinCards(), ...guides];
    return `<section><h1>News &amp; Help</h1><p class="muted">What's new on the server, how to join, and how things work here.</p></section>
      <section id="news"><h2>News</h2>${postCards(news, "No news yet.")}</section>
      ${help.length ? `<section id="guides"><h2>Guides</h2>${postCards(help, "")}</section>` : ""}
      ${faq.length ? `<section id="faq"><h2>Questions</h2>${faqList(faq)}</section>` : ""}
      ${hp.site.contact ? `<section id="contact" class="hp-contact glass"><h2>Contact</h2><p>A problem with your account, a question (parents too), or something stolen or broken in the game? Email <a href="mailto:${esc(hp.site.contact)}">${esc(hp.site.contact)}</a>.</p></section>` : ""}`;
  }
  const [title, cat] = SECTIONS[key];
  const posts = await getJSON(`/api/public/posts?category=${cat}&limit=100`);
  return `<section><h1>${esc(title)}</h1>${postCards(posts, `No ${title.toLowerCase()} yet.`)}</section>`;
}

async function article(slug) {
  let p;
  if (slug === "__preview__") return previewArticle();
  try { p = await getJSON(`/api/public/posts/${encodeURIComponent(slug)}`); } catch { return `<section><h1>Not found</h1><p class="muted">That post isn't here any more. <a href="/">Back home</a></p></section>`; }
  const back = { news: ["/help", "News & Help"], guide: ["/help", "News & Help"], faq: ["/help", "News & Help"] }[p.category] || ["/", "Home"];
  document.title = `${p.title} · ${hp.site.name}`;
  return `<article class="hp-article glass"><a class="back" href="${back[0]}">← ${esc(back[1])}</a>
    <h1>${esc(p.title)}</h1><p class="hp-post-meta">${esc(dateText(p.created))}${p.author ? ` · ${esc(p.author)}` : ""}</p>
    <div class="hp-body">${markdown(fillPostVars(p.body, hp.site))}</div></article>`;
}

// A post being written (Website → Posts → 👁 Preview): from this browser's storage, shown as visitors will see it.
function previewArticle() {
  let p = null;
  try { p = JSON.parse(localStorage.getItem("solstone-post-preview") || "null"); } catch { /* nothing kept */ }
  if (!p) return `<section><h1>Nothing to preview</h1><p class="muted">Press 👁 Preview in the post editor (Website → Posts).</p></section>`;
  document.title = `Preview: ${p.title} · ${hp.site.name}`;
  return `<p class="hp-preview-note glass">👁 <b>Preview.</b> Only you can see this. Nobody else sees the post until it's published and saved. Press Preview again after changes, or reload this tab.</p>
    <article class="hp-article glass"><a class="back" href="/help">← News &amp; Help</a>
    <h1>${esc(p.title)}</h1><p class="hp-post-meta">${esc(dateText(p.created))}${p.author ? ` · ${esc(p.author)}` : ""}</p>
    <div class="hp-body">${markdown(fillPostVars(p.body, hp.site))}</div></article>`;
}

async function builtinArticle(key) {
  const slug = hp.site.guide_posts?.[key];
  if (slug) return article(slug);             // a post stands in for this guide
  const g = BUILTIN[key];
  document.title = `${g.title} · ${hp.site.name}`;
  return `<article class="hp-article glass"><a class="back" href="/help">← News &amp; Help</a>
    <h1>${esc(g.title)}</h1><div class="hp-body">${markdown(guideText(key, hp.site))}</div></article>`;
}

// Asked already? This browser keeps a private ticket for each request, so it can show when each is let in, without
// anyone else being able to see who's on the list. Several at once: a family on one computer, or someone with a Java
// and a Bedrock account. (An older single ticket is moved over.)
function askTickets() {
  let list = [];
  try { list = JSON.parse(localStorage.getItem("solstone-asks") || "[]"); } catch { list = []; }
  try {
    const old = JSON.parse(localStorage.getItem("solstone-ask") || "null");
    if (old?.token && !list.some((t) => t.token === old.token)) list.push(old);
    localStorage.removeItem("solstone-ask");
    if (old) localStorage.setItem("solstone-asks", JSON.stringify(list));
  } catch { /* private window */ }
  return Array.isArray(list) ? list.filter((t) => t?.token) : [];
}
function saveTickets(list) { try { localStorage.setItem("solstone-asks", JSON.stringify(list)); } catch { /* private window */ } }
const askTicket = () => askTickets()[0] || null;        // (any request at all)
// A small badge in the corner while requests are out: sent, waiting (it can take a while), then "you're in".
// It checks every 15 seconds while the page is open (a minute when it's in the background), and never gets stuck: × hides it, a ticket the server no longer knows is dropped,
// and after a week of waiting the badge stops (the requests still show on the join guide).
const ASK_BADGE_DAYS = 7;
let askTimer = 0;
async function showAskStatus() {
  clearTimeout(askTimer);
  let tickets = askTickets();
  if (!tickets.length) { renderAskBadge(null); stepState(null); return; }
  const look = async (t) => {
    const r = await fetch("/api/public/join-request/status", { method: "POST", headers: { "Content-Type": "application/json", "X-Solstone": "1" }, body: JSON.stringify({ token: t.token }) });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);       // Solstone restarting: try again shortly; the request is safe
    return { ...(await r.json()), token: t.token, at: t.at, hidden: t.hidden };
  };
  let all;
  try { all = await Promise.all(tickets.map(look)); } catch { askTimer = setTimeout(showAskStatus, 20000); return; }
  const gone = all.filter((d) => d.state === "unknown").map((d) => d.token);   // only when Solstone itself doesn't know it
  if (gone.length) { tickets = tickets.filter((t) => !gone.includes(t.token)); saveTickets(tickets); all = all.filter((d) => !gone.includes(d.token)); }
  stepState(all);
  const box = $("#step-ask") ? null : $("#ask-status");
  if (box) {
    box.hidden = !all.length;
    box.className = "hp-ask-status";
    box.innerHTML = all.map((d) => {
      const each = (d.servers || []).length > 1 ? ` <span class="ask-each">${d.servers.map((x) => `<span class="${x.in ? "in" : ""}">${x.in ? "✅" : "⏳"} ${esc(x.name)}</span>`).join("")}</span>` : "";
      return `<span class="hp-ask-line ${esc(d.state)}">${d.state === "denied"
        ? `Sorry, <b>${esc(d.player)}</b>, your request wasn't accepted this time.${d.reason ? ` The admins said: <i>${esc(d.reason)}</i>` : ""} <button type="button" class="link-btn" data-ask-forget="${esc(d.token)}">Clear</button>`
        : d.state === "in" ? `🎉 <b>${esc(d.player)}</b>, you're in! Join the server now.${each} <button type="button" class="link-btn" data-ask-forget="${esc(d.token)}">Hide this</button>`
        : d.state === "partly" ? `<span class="spin" aria-hidden="true"></span> <b>${esc(d.player)}</b>, you're in on some already, and waiting for an admin on the rest.${each}`
        : `<span class="spin" aria-hidden="true"></span> The request for <b>${esc(d.player)}</b> is waiting for an admin.${each}`}</span>`;
    }).join("");
  }
  // the corner badge (other pages): the news first (someone's in, or not accepted), else what's still waiting
  const fresh = all.filter((d) => !(Date.now() - (d.at || Date.now()) > ASK_BADGE_DAYS * 86400000) && !d.hidden);
  const pick = all.find((d) => d.state === "in") || all.find((d) => d.state === "denied") || fresh.find((d) => d.state === "partly") || fresh[0] || null;
  renderAskBadge(!$("#step-ask") && pick ? { ...pick, more: all.length - 1 } : null);
  if (all.some((d) => d.state !== "in" && d.state !== "denied")) askTimer = setTimeout(showAskStatus, document.hidden ? 60000 : 15000);
}
function renderAskBadge(d) {
  let b = $("#ask-badge");
  if (!d) { b?.remove(); return; }
  if (!b) { b = document.createElement("div"); b.id = "ask-badge"; b.setAttribute("role", "status"); document.body.append(b); }
  b.className = `ask-badge glass ${d.state}`;
  const more = d.more ? ` (and ${d.more} more request${d.more > 1 ? "s" : ""}: <a href="/">see the home page</a>)` : "";
  b.innerHTML = d.state === "denied"
    ? `<span aria-hidden="true">✋</span><span><b>Request for ${esc(d.player)} not accepted</b><small>${d.reason ? "The admins left a message: " : ""}<a href="/">see the home page</a></small></span><button type="button" class="ask-x" data-ask-forget="${esc(d.token)}" aria-label="Close">×</button>`
    : d.state === "in"
    ? `<span aria-hidden="true">🎉</span><span><b>You're in, ${esc(d.player)}!</b><small>Join the server now${more}</small></span><button type="button" class="ask-x" data-ask-forget="${esc(d.token)}" aria-label="Close">×</button>`
    : `<span class="spin" aria-hidden="true"></span><span><b>${d.state === "partly" ? "You're in on some" : "Request sent"}</b><small>${d.state === "partly"
      ? `In on ${esc(d.servers.filter((x) => x.in).map((x) => x.name).join(", "))}. Waiting on ${esc(d.servers.filter((x) => !x.in).map((x) => x.name).join(", "))}`
      : `Waiting for an admin to let ${esc(d.player)} in`}${more}</small></span><button type="button" class="ask-x" data-ask-hide aria-label="Hide">×</button>`;
}
// Take a request back altogether (asked by mistake, or a typo to send again): off the admins' list too.
async function cancelAsk(token, player) {
  if (!confirm(`Cancel the request for ${player}? The admins won't see it any more. You can always ask again.`)) return;
  try {
    const r = await fetch("/api/public/join-request/withdraw", { method: "POST", headers: { "Content-Type": "application/json", "X-Solstone": "1" }, body: JSON.stringify({ token }) });
    if (!r.ok) throw new Error();
  } catch { toast("That didn't go through. Try again in a moment."); return; }
  toast("Request cancelled");
  forgetAsk(token);
}
// One request off this browser's list (or all of them)
function forgetAsk(token) {
  saveTickets(token ? askTickets().filter((t) => t.token !== token) : []);
  clearTimeout(askTimer);
  showAskStatus();
}
document.addEventListener("click", (e) => {
  const f = e.target.closest("[data-ask-forget]");
  if (f) { forgetAsk(f.dataset.askForget || null); return; }
  const c = e.target.closest("[data-ask-cancel]");
  if (c) { cancelAsk(c.dataset.askCancel, c.dataset.player); return; }
  if (e.target.closest("[data-open-ask]")) { openPop(askFormHtml(true)); return; }
  if (e.target.closest("[data-ask-again]")) { openPop(askFormHtml(true)); return; }
  if (e.target.closest("[data-open-signup]")) { openSignup(); return; }
  if (e.target.closest("[data-ask-hide]")) {          // hide the badge only: the requests are still waiting
    saveTickets(askTickets().map((t) => ({ ...t, hidden: true })));
    renderAskBadge(null);
  }
});
document.addEventListener("visibilitychange", () => { if (!document.hidden && askTicket()) showAskStatus(); });

// Ask to join: their name goes to the admins' notifications, ready to let in from Control.
function askFormHtml(pop = false) {
  return `<section class="hp-ask ${pop ? "" : "glass"}" id="ask"><h2>Ask to join</h2>
    ${pop ? "" : '<p class="hp-ask-status" id="ask-status" hidden></p>'}
    <p class="muted">The admins get a message with your name and can let you in. Then you can join the game.</p>
    <form id="ask-form" autocomplete="off">
      <fieldset class="hp-ask-ed"><legend>I play on</legend>
        <label class="check"><input type="radio" name="edition" value="java" checked> Java (PC or Mac)</label>
        <label class="check"><input type="radio" name="edition" value="bedrock"> Bedrock (phone, tablet, console, Windows)</label></fieldset>
      ${(hp.site.ask_servers || []).length > 1 ? `<fieldset class="hp-ask-ed"><legend>Which servers? <small class="muted">Pick one or more</small></legend>
        ${hp.site.ask_servers.map((x, i) => `<label class="check"><input type="checkbox" name="servers" value="${esc(x.id)}" ${i === 0 ? "checked" : ""}> ${esc(x.name)}</label>`).join("")}</fieldset>` : ""}
      <label>Your name in the game <small>Exactly as it shows. On Bedrock that's your Xbox gamertag.</small><input class="input" name="player" required maxlength="20" autocapitalize="off"></label>
      <label>Your first name <small>Optional, so the admins know who you are</small><input class="input" name="name" maxlength="40"></label>
      <label>A note <small>Optional: who you know here, for example</small><textarea class="input" name="note" rows="3" maxlength="300"></textarea></label>
      <label class="check hp-ask-rules"><input type="checkbox" name="rules" required> ${guideOn(hp.site, "rules") ? `I've read <a href="/guides/rules" target="_blank" rel="noopener">the rules</a> and I'll follow them` : "I'll be kind and follow the server's rules"}</label>
      <p class="login-error" role="alert"></p>
      <button class="btn primary" type="submit">Send</button></form></section>`;
}
document.addEventListener("submit", async (e) => {
  if (e.target.id !== "ask-form") return;
  e.preventDefault();
  const f = new FormData(e.target), err = $(".login-error", e.target);
  try {
    const r = await fetch("/api/public/join-request", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Solstone": "1" },
      body: JSON.stringify({ edition: f.get("edition"), player: f.get("player"), name: f.get("name"), note: f.get("note"), servers: f.getAll("servers"), rules: !!f.get("rules") }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "That didn't send. Try again in a moment.");
    saveTickets([...askTickets().filter((t) => (t.player || "").toLowerCase() !== (d.player || "").toLowerCase()), { token: d.token, player: d.player, at: Date.now() }]);
    if (e.target.closest("#hp-pop")) { closePop(); toast("✅ Request sent"); } else e.target.outerHTML = `<p class="hp-ask-done">✅ ${esc(d.message)}</p>`;
    showAskStatus();
  } catch (x) { err.textContent = x.message; }
});

async function route() {
  hp.path = location.pathname;
  const path = location.pathname.replace(/\/+$/, "") || "/";
  const main = $("#hp-main");
  let nav = "home", html;
  try {
    if (path === "/") {                              // back to Home from another page: today's status, not the first one
      if (Date.now() - (hp.siteAt || 0) > 15000) { hp.site = await getJSON("/api/public/site").catch(() => hp.site); hp.siteAt = Date.now(); }
      html = await home();
    }
    else if (path.startsWith("/post/")) { nav = ""; html = await article(decodeURIComponent(path.slice(6))); }
    else if (path === "/guides/join" && location.hash === "#ask") { history.replaceState(null, "", "/#ask"); route(); return; }   // (the form's old place)
    else if (path === "/guides" || path === "/faq" || path === "/news") { history.replaceState(null, "", { "/faq": "/help#faq", "/news": "/help#news" }[path] || "/help"); route(); return; }   // the old pages
    else if (path.startsWith("/guides/") && BUILTIN[path.slice(8)] && guideOn(hp.site, path.slice(8))) { nav = "help"; html = await builtinArticle(path.slice(8)); }
    else if (path.startsWith("/guides/")) { history.replaceState(null, "", "/help"); route(); return; }       // a guide that's been taken off
    else if (SECTIONS[path.slice(1)]) { nav = path.slice(1); html = await section(nav); }
    else { nav = ""; html = `<section><h1>Not found</h1><p class="muted"><a href="/">Back home</a></p></section>`; }
  } catch (e) {
    console.error("Solstone: couldn't load this page:", e);
    html = `<section><h1>Couldn't load this page</h1><p class="muted">Try again in a moment.</p></section>`;
  }
  if (!path.startsWith("/post/") && !path.startsWith("/guides/")) document.title = nav && nav !== "home" ? `${SECTIONS[nav][0]} · ${hp.site.name}` : hp.site.name;
  main.innerHTML = html;
  if (!/<h1>(Not found|Couldn't load this page)<\/h1>/.test(html) && !path.includes("__preview__")) readStart(path);
  document.querySelectorAll("[data-nav]").forEach((a) => a.toggleAttribute("aria-current", a.dataset.nav === nav));
  showAskStatus();
  if (path === "/" && location.hash === "#ask" && hp.site.join_requests) { history.replaceState(null, "", "/"); openPop(askFormHtml(true)); }
  else if (path === "/" && location.hash === "#account" && hp.site.signup) { history.replaceState(null, "", "/"); openSignup(); }
  else if (["#faq", "#ask", "#contact", "#news", "#guides"].includes(location.hash)) $(location.hash)?.scrollIntoView(); else window.scrollTo(0, 0);
}

// What people read, for the admins (Manage → Solstone → What people read): a view when a page opens, "read" once
// they've reached the end and had it open 15 seconds, and how long it was on screen. Admins' own visits don't count,
// and nobody's named: it's counts per page.
const readT = { id: "", page: "", seen: 0, since: 0, end: false, read: false, sent: 0, article: false };
function readSend(event, extra = {}) {
  if (!readT.page) return;
  try {
    fetch("/api/public/read", { method: "POST", keepalive: true, headers: { "Content-Type": "application/json", "X-Solstone": "1" },
      body: JSON.stringify({ id: readT.id, page: readT.page, title: document.title.split(" · ")[0], event, ...extra }) }).catch(() => {});
  } catch { /* never in the way */ }
}
const readTime = () => readT.seen + (readT.since ? Date.now() - readT.since : 0);
function readLeave() {
  const s = Math.round(readTime() / 1000);
  if (readT.page && s > 0 && s !== readT.sent) { readT.sent = s; readSend("time", { secs: s }); }
}
function readCheck() {
  if (!readT.page || readT.read || !readT.article) return;
  const body = $(".hp-article .hp-body");
  if (body && body.getBoundingClientRect().bottom <= innerHeight + 40) readT.end = true;
  if (readT.end && readTime() >= 15000) { readT.read = true; readSend("read"); }
}
function readStart(path) {
  if (path === readT.page) return;
  readLeave();
  const id = window.crypto?.randomUUID?.() || `${Date.now()}${Math.random()}`.replace(".", "");
  Object.assign(readT, { id, page: path, seen: 0, since: document.hidden ? 0 : Date.now(), end: false, read: false, sent: 0,
    article: path.startsWith("/post/") || path.startsWith("/guides/") });
  readSend("view");
  readCheck();
}
addEventListener("scroll", readCheck, { passive: true });
setInterval(readCheck, 3000);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { readT.seen = readTime(); readT.since = 0; readLeave(); } else readT.since = Date.now();
});
addEventListener("pagehide", readLeave);

// The status panel keeps itself current while the home page is open (the server is only asked every 15 s), and
// straight away when the tab comes back into view (a tab left in the background skips its updates meanwhile).
async function refreshStatus() {
  const el = document.getElementById("hp-status");
  if (!el || document.hidden) return;
  try { hp.site = await getJSON("/api/public/site"); hp.siteAt = Date.now(); const fresh = statusPanel(hp.site); if (fresh) el.outerHTML = fresh; } catch { /* next time */ }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshStatus(); });
addEventListener("pageshow", (e) => { if (e.persisted) refreshStatus(); });     // back to a page the browser kept
setInterval(async () => {
  const el = document.getElementById("hp-status");
  if (!el || document.hidden) return;
  try { hp.site = await getJSON("/api/public/site"); const fresh = statusPanel(hp.site); if (fresh) el.outerHTML = fresh; } catch { /* next time */ }
}, 30000);

// Links inside the site change the page without a reload; everything else is a normal link.
document.addEventListener("click", (e) => {
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    navigator.clipboard?.writeText(copy.dataset.copy).then(() => toast("Copied"), () => toast(copy.dataset.copy));
    return;
  }
  const a = e.target.closest("a[href]");
  if (!a || e.defaultPrevented || a.target || e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;
  const url = new URL(a.href, location.href);
  if (url.origin !== location.origin) return;
  if (url.hash === "#ask" && url.pathname !== "/" && (url.pathname === location.pathname || url.pathname.startsWith("/guides/join"))) {
    e.preventDefault();                                  // Ask to join: on the home page, in its pop-up
    if (location.pathname === "/") { if (hp.site.join_requests) openPop(askFormHtml(true)); return; }
    history.pushState(null, "", "/#ask");
    route();
    return;
  }
  if (url.pathname === "/" && (url.hash === "#ask" || url.hash === "#account") && location.pathname === "/") {     // the pop-ups, right here
    e.preventDefault();
    if (url.hash === "#ask" && hp.site.join_requests) openPop(askFormHtml(true)); else if (url.hash === "#account" && hp.site.signup) openSignup();
    return;
  }
  if (url.pathname === location.pathname && url.hash) return;          // a spot on this page: the browser scrolls to it
  if (url.pathname === "/" || url.pathname.startsWith("/post/") || url.pathname.startsWith("/guides") || url.pathname === "/faq" || SECTIONS[url.pathname.slice(1)]) {
    e.preventDefault();
    if (url.pathname !== location.pathname) history.pushState(null, "", url.pathname + url.hash);
    route();
  }
});
window.addEventListener("popstate", () => { if (location.pathname !== hp.path) route(); });     // not for a jump to a spot on the page

// FAQ answers load when opened.
document.addEventListener("toggle", async (e) => {
  const box = e.target.querySelector?.("[data-faq]");
  if (!e.target.open || !box || box.dataset.loaded) return;
  box.dataset.loaded = "1";
  try { box.innerHTML = markdown(fillPostVars((await getJSON(`/api/public/posts/${encodeURIComponent(box.dataset.faq)}`)).body, hp.site)); }
  catch { box.innerHTML = `<p class="muted">Couldn't load the answer.</p>`; }
}, true);

document.addEventListener("DOMContentLoaded", async () => {
  try { hp.site = await getJSON("/api/public/site"); hp.siteAt = Date.now(); } catch { hp.site = { name: "Solstone", servers: [], live: false }; }
  $("#hp-name").textContent = $("#hp-foot-name").textContent = hp.site.name;
  if (hp.site.contact) {                                // the footer's Contact: an email link, on every page
    const a = $("#hp-foot-contact a"); a.href = `mailto:${hp.site.contact}`; a.title = hp.site.contact; $("#hp-foot-contact").hidden = false;
  }
  showSignedIn();
  const sky = $("#home-sky");
  if (sky && typeof startSkyScene === "function") {
    hp.scene = startSkyScene(sky, { auto: false, sound: (t, i) => FWAudio.play(t, i), dim: () => (document.body.classList.contains("ui-hidden") ? 0 : 0.35) });
    // The show runs behind the page from the start, without sound (sound stays off until someone turns it on);
    // a visitor who switches the show off is remembered, and "reduce motion" keeps it off.
    if (typeof startShowBar === "function") hp.bar = startShowBar(hp.scene, { key: "solstone-sky-home", defaultOn: true, hide: true });
  }
  if (typeof startBoard === "function") startBoard($("#hp-board"), { where: "home", sid: () => "", scene: () => hp.scene, max: innerWidth < 700 ? 1 : 3 });
  route();
});
