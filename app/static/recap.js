/* Solstone — daily recap cards ("Today on the server", "On this day"), shared by the
   app's Overview tab and the status page / TV mode. */
"use strict";

function recapSpan(sec) {
  sec = Math.round(sec || 0);
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  return h ? `${h} h${m ? ` ${m} min` : ""}` : `${Math.max(1, m)} min`;
}
function recapDate(iso, withYear = true) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long", ...(withYear ? { year: "numeric" } : {}) });
}
const recapNames = (list) => list.length <= 2 ? list.join(" and ") : `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`;

// The day's best moments, most special first.
function recapHighlights(r, max = 6) {
  const out = [];
  const by = (kind) => r.advancements.filter((a) => a.kind === kind);
  for (const a of by("challenge")) out.push({ icon: "🏆", html: `<b>${esc(a.player)}</b> completed the challenge <span class="adv-name">${esc(a.title)}</span>` });
  for (const n of r.newcomers || []) out.push({ icon: "👋", html: `<b>${esc(n)}</b> joined for the very first time` });
  for (const a of by("goal")) out.push({ icon: "🎯", html: `<b>${esc(a.player)}</b> reached the goal <span class="adv-name">${esc(a.title)}</span>` });
  const adv = by("advancement");
  if (adv.length === 1) out.push({ icon: "★", html: `<b>${esc(adv[0].player)}</b> made the advancement <span class="adv-name">${esc(adv[0].title)}</span>` });
  else if (adv.length) {
    const per = {};
    adv.forEach((a) => { per[a.player] = (per[a.player] || 0) + 1; });
    const top = Object.entries(per).sort((a, b) => b[1] - a[1])[0];
    out.push({ icon: "★", html: `${adv.length} advancements${Object.keys(per).length > 1 ? `, most by <b>${esc(top[0])}</b> (${top[1]})` : ` by <b>${esc(top[0])}</b>`}` });
  }
  if (r.players.length > 1 && r.peak > 1) out.push({ icon: "👥", html: `${r.peak === r.players.length ? "Everyone" : `${r.peak} people`} played together at once` });
  if (r.players[0] && r.players[0].seconds >= 600) out.push({ icon: "⏱", html: `<b>${esc(r.players[0].name)}</b> played the longest: ${esc(recapSpan(r.players[0].seconds))}` });
  for (const l of (r.levels || []).slice(0, 2)) out.push({ icon: "⬆", html: esc(l.message) });
  if (r.deaths.length) {
    const per = {};
    r.deaths.forEach((d) => { per[d.player] = (per[d.player] || 0) + 1; });
    out.push({ icon: "☠", html: r.deaths.length === 1 ? esc(r.deaths[0].message) : `${r.deaths.length} deaths (${Object.entries(per).map(([n, c]) => `${esc(n)} ${c}`).join(", ")})` });
  }
  return out.slice(0, max);
}

// title: "Today so far" etc. o.big for the TV; o.max lines.
function recapCardHtml(r, title, o = {}) {
  if (!r || (!r.players.length && !r.advancements.length && !r.deaths.length)) {
    return `<div class="rc-card ${o.big ? "big" : ""}"><div class="rc-head"><h3>${esc(title)}</h3></div><p class="muted">Nobody played${title.startsWith("Today") ? " yet today" : ""}.</p></div>`;
  }
  const lines = recapHighlights(r, o.max || 6);
  const who = r.players.map((p) => `<span class="rc-who" title="${esc(p.name)} · ${esc(recapSpan(p.seconds))}">${faceHtml(p, o.big ? 44 : 30)}<span><b>${esc(p.name)}</b><small>${esc(recapSpan(p.seconds))}</small></span></span>`).join("");
  return `<div class="rc-card ${o.big ? "big" : ""}">
    <div class="rc-head"><h3>${esc(title)}</h3><span class="muted">${r.players.length} ${r.players.length === 1 ? "player" : "players"} · ${esc(recapSpan(r.total_seconds))} played${r.source === "logs" ? ' · <span title="Read from the server\'s old logs">from the logs</span>' : ""}</span></div>
    ${who ? `<div class="rc-players">${who}</div>` : ""}
    ${lines.length ? `<ul class="rc-lines">${lines.map((l) => `<li><span class="rc-ic" aria-hidden="true">${l.icon}</span><span>${l.html}</span></li>`).join("")}</ul>` : ""}
  </div>`;
}

function onThisDayHtml(list, o = {}) {
  if (!list?.length) return "";
  return `<div class="rc-otd ${o.big ? "big" : ""}"><h3>📅 On this day</h3>${list.map((r) => {
    const top = recapHighlights(r, 1)[0];
    return `<div class="rc-otd-row"><div class="rc-otd-when"><b>${esc(r.label)}</b><small>${esc(recapDate(r.day))}</small></div>
      <div class="rc-otd-what"><span class="rc-faces">${r.players.slice(0, 6).map((p) => faceHtml(p, o.big ? 34 : 24)).join("")}</span>
      <span>${esc(recapNames(r.players.map((p) => p.name).slice(0, 4)))}${r.players.length > 4 ? ` and ${r.players.length - 4} more` : ""} played ${esc(recapSpan(r.total_seconds))}${top ? `. ${top.icon} ${top.html}` : ""}</span></div></div>`;
  }).join("")}</div>`;
}
