/* Solstone — admin Control tab (console, quick actions, players, bedtime) and Users & activity page.
   Loaded after app.js and history.js and uses their helpers. */
"use strict";

const DANGEROUS = /^\/?(stop|op|deop|ban|ban-ip|pardon|kill|clear|reload|save-off|whitelist\s+(off|remove)|kick\s+@|fill|clone|forceload|difficulty\s+hard)\b/i;
const QUICK_COMMANDS = ["list", "save-all", "tick query", "time query daytime", "seed", "whitelist list", "help"];
const ACTION_LABELS = {
  command: "Ran a command", broadcast: "Messaged everyone", gamerule: "Changed a game rule", settings: "Changed server settings",
  "quick:time": "Set the time", "quick:weather": "Set the weather", "quick:difficulty": "Set difficulty", "quick:save": "Saved the world",
  "player:message": "Messaged a player", "player:tp_to_player": "Teleported", "player:bring": "Teleported", "player:tp_spawn": "Sent to spawn",
  "player:tp_bed": "Sent to their bed", "player:heal": "Healed", "player:gamemode": "Changed game mode", "player:give": "Gave items",
  "player:kick": "Kicked", "player:whitelist_add": "Added to whitelist", "player:whitelist_remove": "Removed from whitelist",
  "player:op": "Made operator", "player:deop": "Removed operator", "power:start_server": "Started the server",
  "power:stop_server": "Stopped the server", "power:restart_server": "Restarted the server", "power:backup_server": "Started a backup",
  kick: "Disconnected", add_user: "Added a user", edit_user: "Changed a user", delete_user: "Removed a user",
  change_password: "Changed their password", login_page_settings: "Changed the sign-in page", login_failed: "Failed sign-in", login: "Signed in", main_player: "Picked their main Minecraft account", notification_settings: "Changed notifications",
};
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Cleanups run when leaving a page (e.g. closing the console stream).
state.cleanups = state.cleanups || [];
const _clearTimers = clearTimers;
clearTimers = function () { _clearTimers(); state.cleanups.splice(0).forEach((fn) => { try { fn(); } catch {} }); }; // eslint-disable-line no-func-assign

function confirmBox(title, text, okLabel, danger = true) {
  return new Promise((resolve) => {
    openModal(`<h2>${esc(title)}</h2><p class="muted" style="margin-bottom:16px">${text}</p>
      <div class="actions"><button type="button" class="btn" id="cf-no">Cancel</button>
      <button type="button" class="btn ${danger ? "danger" : "primary"}" id="cf-yes">${esc(okLabel)}</button></div>`, (m) => {
      $("#cf-no", m).addEventListener("click", () => { closeModal(); resolve(false); });
      $("#cf-yes", m).addEventListener("click", () => { closeModal(); resolve(true); });
      $("#cf-yes", m).focus();
    });
  });
}

// Ask for a line of text that may be left empty. Resolves to the text ("" when emptied), or null if cancelled.
function promptBox(title, text, value = "", max = 160) {
  return new Promise((resolve) => {
    openModal(`<h2>${esc(title)}</h2><form id="pb-form"><p class="muted" style="margin-bottom:10px">${esc(text)}</p>
      <input class="input" id="pb-in" maxlength="${max}" value="${esc(value)}" autocomplete="off">
      <div class="actions" style="margin-top:14px"><button type="button" class="btn" id="pb-no">Cancel</button><button type="submit" class="btn primary">Save</button></div></form>`, (m) => {
      $("#pb-no", m).addEventListener("click", () => { closeModal(); resolve(null); });
      $("#pb-form", m).addEventListener("submit", (e) => { e.preventDefault(); const v = $("#pb-in", m).value.trim(); closeModal(); resolve(v); });
      $("#pb-in", m).focus();
    });
  });
}

// Ask for a short line of text. Resolves to the text, or "" if cancelled.
function textBox(title, text, value = "", max = 40) {
  return new Promise((resolve) => {
    openModal(`<h2>${esc(title)}</h2><form id="tb-form"><p class="muted" style="margin-bottom:10px">${esc(text)}</p>
      <input class="input" id="tb-in" maxlength="${max}" value="${esc(value)}" autocomplete="off">
      <div class="actions" style="margin-top:14px"><button type="button" class="btn" id="tb-no">Cancel</button><button type="submit" class="btn primary">OK</button></div></form>`, (m) => {
      $("#tb-no", m).addEventListener("click", () => { closeModal(); resolve(""); });
      $("#tb-form", m).addEventListener("submit", (e) => { e.preventDefault(); const v = $("#tb-in", m).value.trim(); closeModal(); resolve(v); });
      $("#tb-in", m).focus();
    });
  });
}

function auditHtml(rows, showServer = false) {
  if (!rows.length) return `<p class="muted">Nothing yet.</p>`;
  const serverName = (id) => state.servers.find((s) => s.id === id)?.name || "";
  return `<ul class="audit">${rows.map((a) => {
    const when = new Date(a.ts * 1000);
    const label = ACTION_LABELS[a.action] || humanize(a.action);
    const failed = (a.result || "").startsWith("failed") || a.result === "denied";
    return `<li class="${failed ? "failed" : ""}"><span class="a-time" title="${esc(when.toLocaleString())}">${esc(dayLabel(a.ts))}, ${esc(hm(a.ts))}</span>
      <span class="a-who">${esc(a.username || "Someone")}</span>
      <span class="a-what">${esc(label)}${a.detail ? ` <code>${esc(a.detail)}</code>` : ""}${showServer && a.server_id ? ` <span class="muted">on ${esc(serverName(a.server_id))}</span>` : ""}
      ${a.result && a.result !== "ok" ? `<span class="a-result">${esc(a.result)}</span>` : ""}</span></li>`;
  }).join("")}</ul>`;
}

// Manage → Activity: the admin activity log, filtered and a page at a time.
const AUDIT_PAGE = 50;
async function mountAuditBrowser(el) {
  let facets = await api("/api/audit/facets");
  const f = { server: "", action: "", who: "", q: "", from: "", to: "", failed: false, oldest: false, offset: 0 };
  const label = (a) => ACTION_LABELS[a] || humanize(a);
  // actions like "player:bring" and "player:message" are offered one by one, and as one group ("Player: all")
  const kinds = () => {
    const groups = [...new Set(facets.actions.filter((a) => a.includes(":")).map((a) => a.split(":")[0]))];
    return [...facets.actions.map((a) => [a, label(a)]), ...groups.map((g) => [g, `${humanize(g)}: all`])].sort((x, y) => x[1].localeCompare(y[1]));
  };
  const keepText = (d) => (d ? (d % 365 === 0 ? `${d / 365} year${d > 365 ? "s" : ""}` : `${d} days`) : "Forever");
  const dayStart = (v) => (v ? new Date(`${v}T00:00`).getTime() / 1000 : 0);
  el.innerHTML = `<form class="audit-filters" id="audit-filters" autocomplete="off">
      <input class="input sm" type="search" name="q" placeholder="Search (a command, a player's name…)" aria-label="Search">
      <select class="input sm" name="action" aria-label="Kind"><option value="">Everything</option>${kinds().map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("")}</select>
      <select class="input sm" name="who" aria-label="Who"><option value="">Anyone</option>${facets.people.map((p) => `<option>${esc(p)}</option>`).join("")}</select>
      <select class="input sm" name="server" aria-label="Server"><option value="">All servers</option>${(state.servers || []).map((x) => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("")}</select>
      <label class="audit-date">From <input class="input sm" type="date" name="from"></label>
      <label class="audit-date">To <input class="input sm" type="date" name="to"></label>
      <label class="check"><input type="checkbox" name="failed"> Only failures</label>
      <select class="input sm" name="oldest" aria-label="Order"><option value="">Newest first</option><option value="1">Oldest first</option></select>
      <button class="btn sm" type="reset">Clear filters</button>
    </form>
    <p class="muted small audit-count" id="audit-count"></p>
    <div id="audit-rows"></div>
    <div class="btn-row audit-pager" id="audit-pager"></div>
    <div class="audit-keep">
      <label>Keep the log for <select class="input sm" id="audit-keep">${facets.keep_choices.map((d) => `<option value="${d}" ${d === facets.keep_days ? "selected" : ""}>${keepText(d)}</option>`).join("")}</select></label>
      <span class="muted small" id="audit-since"></span></div>`;
  const since = () => { $("#audit-since", el).textContent = facets.count ? `${facets.count.toLocaleString()} entries, the first from ${new Date(facets.first * 1000).toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" })}.` : ""; };
  since();
  const load = async () => {
    const qs = new URLSearchParams({ offset: f.offset, limit: AUDIT_PAGE });
    for (const k of ["server", "action", "who", "q"]) if (f[k]) qs.set(k, f[k]);
    if (f.from) qs.set("since", dayStart(f.from));
    if (f.to) qs.set("until", dayStart(f.to) + 86400);
    if (f.failed) qs.set("failed", "true");
    if (f.oldest) qs.set("oldest", "true");
    const d = await api(`/api/audit/search?${qs}`);
    $("#audit-rows", el).innerHTML = auditHtml(d.rows, true);
    const end = Math.min(d.total, d.offset + d.rows.length);
    $("#audit-count", el).textContent = d.total ? `${d.offset + 1}–${end} of ${d.total.toLocaleString()}` : "";
    const page = Math.floor(d.offset / AUDIT_PAGE) + 1, pages = Math.max(1, Math.ceil(d.total / AUDIT_PAGE));
    $("#audit-pager", el).innerHTML = pages > 1 ? `<button class="btn sm" type="button" data-page="0" ${page === 1 ? "disabled" : ""}>« First</button>
      <button class="btn sm" type="button" data-page="${(page - 2) * AUDIT_PAGE}" ${page === 1 ? "disabled" : ""}>‹ ${f.oldest ? "Older" : "Newer"}</button>
      <span class="muted small">Page ${page} of ${pages}</span>
      <button class="btn sm" type="button" data-page="${page * AUDIT_PAGE}" ${page === pages ? "disabled" : ""}>${f.oldest ? "Newer" : "Older"} ›</button>
      <button class="btn sm" type="button" data-page="${(pages - 1) * AUDIT_PAGE}" ${page === pages ? "disabled" : ""}>Last »</button>` : "";
  };
  const form = $("#audit-filters", el);
  const read = () => { const v = new FormData(form); for (const k of ["server", "action", "who", "q", "from", "to"]) f[k] = (v.get(k) || "").trim(); f.failed = !!v.get("failed"); f.oldest = !!v.get("oldest"); f.offset = 0; };
  let typing;
  form.addEventListener("input", (e) => { clearTimeout(typing); typing = setTimeout(() => { read(); load(); }, e.target.name === "q" ? 300 : 0); });
  form.addEventListener("reset", () => setTimeout(() => { read(); load(); }, 0));
  form.addEventListener("submit", (e) => e.preventDefault());
  $("#audit-pager", el).addEventListener("click", (e) => { const b = e.target.closest("[data-page]"); if (!b) return; f.offset = +b.dataset.page; load(); el.scrollIntoView({ block: "start", behavior: "smooth" }); });
  $("#audit-keep", el).addEventListener("change", async (e) => {
    const days = +e.target.value;
    if (days && !(await confirmBox(`Keep the log for ${keepText(days)}?`, `Entries older than that are deleted now, and from then on.`, "Keep it that long"))) { e.target.value = facets.keep_days; return; }
    try { facets = await post("/api/audit/keep", { days }, "PUT"); since(); showToast(days ? `Kept for ${keepText(days)}` : "Kept forever", 2500); await load(); }
    catch (err) { showError(esc(err.message), 4000); e.target.value = facets.keep_days; }
  });
  await load();
}

// ================================================================ Control tab
async function viewControl(sid) {
  if (!isAdmin()) { location.replace(`#/s/${encodeURIComponent(sid)}`); return; }
  const s = await serverFrame(sid, "control");
  const base = `/api/servers/${encodeURIComponent(sid)}`;
  let info = await api(`${base}/control`);

  setView(serverHeader(s, "control") + `
    <div class="ctl-top">
      <section class="panel"><h3>Server</h3>
        <p class="muted ctl-state">${s.running === false ? "The server is offline." : `Running${s.started ? ` since ${esc(new Date(s.started.replace(" ", "T")).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }))}` : ""}.`}</p>
        <div class="btn-row">
          ${s.running === false ? `<button class="btn primary" data-power="start_server">Start</button>` : `<button class="btn" data-power="restart_server">Restart</button><button class="btn danger" data-power="stop_server">Stop</button>`}
          <button class="btn" data-power="backup_server">Back up now</button>
          <button class="btn" data-quick="save" data-value="">Save world</button>
        </div>
        ${info.can_crafty ? "" : `<p class="muted small">Start, stop and backups need Crafty connected.</p>`}
      </section>
      ${info.xbox ? `<section class="panel ctl-xbox"><h3>🎮 Xbox friend joining</h3>
        ${xboxStateHtml(info.xbox, "ctl-xbox-st")}
        <p class="muted small">${info.xbox_gamertag ? `Gamertag <b>${esc(info.xbox_gamertag)}</b> · ` : ""}MCXboxBroadcast${info.xbox.since && info.xbox.state !== "off" ? ` · ${info.xbox.state === "ok" ? "working" : "like this"} since ${esc(fmtAgo(info.xbox.since))}` : ""}</p>
        ${info.xbox.drops_24h != null ? `<p class="muted small">${info.xbox.drops_24h ? `Reconnected ${info.xbox.drops_24h} time${info.xbox.drops_24h === 1 ? "" : "s"} in the last day (Microsoft drops its connection now and then; a second or two each time is normal).` : "No dropped connections in the last day."}</p>` : ""}
        ${info.xbox.problem ? `<details class="small"><summary>Last problem it logged · ${esc(fmtAgo(info.xbox.problem_at))}</summary><code class="ctl-xbox-err">${esc(info.xbox.problem)}</code></details>` : ""}
        <p class="muted small">Not reconnected within ${Math.round((info.xbox.grace || 120) / 60)} minutes counts as down: you get a notification, and another when it's back.</p>
      </section>` : ""}
      <section class="panel"><h3>Message everyone</h3>
        <form id="bc-form" class="bc-form">
          <input class="input" name="message" maxlength="256" placeholder="Dinner in 10 minutes!" autocomplete="off" required>
          <button class="btn primary" type="submit">Send</button>
          <label class="check small"><input type="checkbox" name="on_screen"> Also show it big on everyone's screen</label>
        </form>
      </section>
    </div>
    ${info.can_rcon || info.can_crafty ? "" : `<div class="notice">Turn on RCON for this server (<a href="#/manage/setup">Manage → Server setup</a>) to send commands.</div>`}
    <div class="ctl-main">
      <section class="console-wrap"><div class="section-head"><h2>Console</h2><span class="muted small" id="console-state">Connecting…</span></div>
        <div class="console" id="console" role="log" aria-live="off"></div>
        <form id="cmd-form" class="cmd-form" autocomplete="off">
          <span aria-hidden="true">/</span><input id="cmd-input" name="command" placeholder="Type a command, like time set day" spellcheck="false" aria-label="Command">
          <button class="btn primary" type="submit">Run</button>
        </form>
        <div class="chips">${QUICK_COMMANDS.map((c) => `<button class="chip chip-btn" type="button" data-cmd="${esc(c)}">${esc(c)}</button>`).join("")}</div>
      </section>
      <aside class="ctl-side">${info.is_java ? `
        <section class="panel"><h3>World</h3>
          <div class="ctl-row"><span>Time</span><div class="seg">${["day", "noon", "night", "midnight"].map((v) => `<button data-quick="time" data-value="${v}">${humanize(v)}</button>`).join("")}</div></div>
          <div class="ctl-row"><span>Weather</span><div class="seg">${["clear", "rain", "thunder"].map((v) => `<button data-quick="weather" data-value="${v}">${humanize(v)}</button>`).join("")}</div></div>
          <div class="ctl-row"><span>Difficulty</span><div class="seg">${["peaceful", "easy", "normal", "hard"].map((v) => `<button data-quick="difficulty" data-value="${v}">${humanize(v)}</button>`).join("")}</div></div>
        </section>
        <section class="panel"><h3>Game rules</h3><div id="rules">${rulesHtml(info.game_rules, info.can_rcon)}</div></section>` : `<section class="panel"><p class="muted">Quick world controls are for Minecraft Java servers. Use the console for this server.</p></section>`}
      </aside>
    </div>
    ${info.is_java ? `<section class="section"><div class="section-head"><h2>Players</h2><span class="muted" id="online-count"></span></div><div id="ctl-players"></div></section>
    <section class="section"><div class="section-head"><h2>Whitelist and operators</h2></div><div class="panel" id="ctl-lists"></div></section>
    <section class="section"><div class="section-head"><h2>Bedtime</h2><span class="muted" id="bed-status"></span></div><div class="panel" id="ctl-bedtime"></div></section>` : ""}
    <section class="section"><div class="section-head"><h2>Recent admin actions</h2></div><div class="panel" id="ctl-audit">${auditHtml(info.audit)}</div></section>`);
  wireHeader(s);

  // ---- helpers
  const refreshInfo = async () => {
    info = await api(`${base}/control`).catch(() => info);
    if ($("#ctl-audit")) $("#ctl-audit").innerHTML = auditHtml(info.audit);
    if (info.is_java && $("#ctl-players")) { renderPlayers(); renderLists(); $("#rules").innerHTML = rulesHtml(info.game_rules, info.can_rcon); }
  };
  const report = (res, okMsg) => {
    const outs = (res.results || []).map((r) => (r.output || r.note || "").trim()).filter(Boolean);
    const bad = (res.results || []).some((r) => r.ok === false);
    showToast(esc(outs.join(" · ") || okMsg), bad ? 6000 : 3000);
    outs.forEach((o) => appendConsole([o], "reply"));
  };
  const act = async (path, body, okMsg) => {
    try { const r = await post(`${base}/control/${path}`, body); report(r, okMsg); refreshInfo(); return r; }
    catch (err) { showError(esc(err.message), 6000); }
  };

  // ---- power + quick + broadcast
  $$("[data-power]").forEach((b) => b.addEventListener("click", async () => {
    const a = b.dataset.power;
    const words = { start_server: ["Start the server?", "Start"], restart_server: ["Restart the server?", "Restart"],
      stop_server: ["Stop the server?", "Stop"], backup_server: ["Back up the server now?", "Back up"] }[a];
    const online = info.online.length ? `${info.online.length} player${info.online.length === 1 ? " is" : "s are"} online and will be disconnected.` : "Nobody is online.";
    if (a !== "backup_server" && a !== "start_server" && !(await confirmBox(words[0], esc(online), words[1], a === "stop_server"))) return;
    try { await post(`${base}/control/power/${a}`); showToast(`${words[1]} requested. Crafty is on it.`, 4000); setTimeout(() => route(), 4000); }
    catch (err) { showError(esc(err.message), 6000); }
  }));
  $$("[data-quick]").forEach((q) => q.addEventListener("click", () => act("quick", { action: q.dataset.quick, value: q.dataset.value }, "Done")));
  $("#bc-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const r = await act("broadcast", { message: f.get("message"), on_screen: !!f.get("on_screen") }, "Message sent");
    if (r) e.target.reset();
  });

  // ---- console
  const con = $("#console");
  let stick = true;
  con.addEventListener("scroll", () => { stick = con.scrollHeight - con.scrollTop - con.clientHeight < 30; });
  function lineClass(l) {
    if (/\/(WARN|WARNING)\]|\bWARN\]/.test(l)) return "warn";
    if (/\/(ERROR|FATAL)\]|\bERROR\]/.test(l)) return "err";
    if (/\]: (\[Not Secure\] )?<[^>]+>/.test(l)) return "chat";
    if (/ (joined|left) the game$/.test(l)) return "join";
    return "";
  }
  function appendConsole(lines, kind = "") {
    if (!con) return;
    const frag = document.createDocumentFragment();
    for (const l of lines) {
      const div = document.createElement("div");
      div.className = `ln ${kind || lineClass(l)}`;
      div.textContent = l;
      frag.append(div);
    }
    con.append(frag);
    while (con.childElementCount > 1500) con.firstElementChild.remove();
    if (stick) con.scrollTop = con.scrollHeight;
  }
  const es = new EventSource(`${base}/console/stream`);
  state.cleanups.push(() => es.close());
  es.onopen = () => { $("#console-state").textContent = "Live"; };
  es.onerror = () => { $("#console-state").textContent = "Reconnecting…"; };
  es.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    if (d.error) { appendConsole([d.error], "err"); $("#console-state").textContent = "Log unavailable"; es.close(); return; }
    if (d.reset) con.innerHTML = "";
    appendConsole(d.lines || [], d.rotated ? "sys" : "");
    $("#console-state").textContent = "Live";
  };

  let history = [];
  try { history = JSON.parse(localStorage.getItem("solstone-cmd-history") || "[]"); } catch {}
  let hIdx = history.length;
  const input = $("#cmd-input");
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowUp" && hIdx > 0) { hIdx -= 1; input.value = history[hIdx]; e.preventDefault(); }
    if (e.key === "ArrowDown") { hIdx = Math.min(history.length, hIdx + 1); input.value = history[hIdx] || ""; e.preventDefault(); }
  });
  const runCommand = async (cmd) => {
    cmd = cmd.trim().replace(/^\//, "");
    if (!cmd) return;
    if (DANGEROUS.test(cmd) && !(await confirmBox("Run this command?", `<code>/${esc(cmd)}</code> can't easily be undone.`, "Run it"))) return;
    history = [...history.filter((h) => h !== cmd), cmd].slice(-50); hIdx = history.length;
    try { localStorage.setItem("solstone-cmd-history", JSON.stringify(history)); } catch {}
    appendConsole([`> /${cmd}`], "cmd");
    try {
      const r = await post(`${base}/control/command`, { command: cmd });
      for (const res of r.results) appendConsole([(res.output || res.note || "(no reply)").trim()], res.ok === false ? "err" : "reply");
      refreshInfo();
    } catch (err) { appendConsole([err.message], "err"); }
  };
  $("#cmd-form").addEventListener("submit", (e) => { e.preventDefault(); const v = input.value; input.value = ""; runCommand(v); input.focus(); });
  $$("[data-cmd]").forEach((b) => b.addEventListener("click", () => runCommand(b.dataset.cmd)));

  // ---- game rules
  $("#rules")?.addEventListener("change", async (e) => {
    const el = e.target.closest("[data-rule]");
    if (!el) return;
    const value = el.type === "checkbox" ? el.checked : Number(el.value);
    await act("gamerule", { key: el.dataset.rule, value }, "Game rule changed");
  });

  // ---- players
  function renderPlayers() {
    const el = $("#ctl-players");
    if (!el) return;
    $("#online-count").textContent = info.online.length ? `${info.online.length} online` : "";
    if (!info.can_rcon) { el.innerHTML = `<div class="empty"><p>Player actions need RCON on this server.</p></div>`; return; }
    if (!info.online.length) { el.innerHTML = `<div class="empty"><p>Nobody is online right now. Player actions appear here when someone joins.</p></div>`; return; }
    const others = (n) => info.online.filter((o) => o !== n);
    el.innerHTML = `<div class="ctl-players">${info.online.map((n) => `
      <div class="ctl-player panel" data-player="${esc(n)}">
        <div class="cp-head">${faceHtml({ name: n }, 32)}<b>${esc(n)}</b></div>
        <div class="btn-row">
          <button class="btn sm" data-pa="heal">Heal &amp; feed</button>
          <button class="btn sm" data-pa="tp_spawn">Send to spawn</button>
          <button class="btn sm" data-pa="tp_bed">Send to bed</button>
          <select class="input sm" data-pa="gamemode" aria-label="Game mode for ${esc(n)}"><option value="">Game mode…</option>${["survival", "creative", "adventure", "spectator"].map((m) => `<option value="${m}">${humanize(m)}</option>`).join("")}</select>
        </div>
        ${others(n).length ? `<div class="btn-row"><select class="input sm" data-target aria-label="Other player">${others(n).map((o) => `<option>${esc(o)}</option>`).join("")}</select>
          <button class="btn sm" data-pa="tp_to_player">Send ${esc(n)} to them</button><button class="btn sm" data-pa="bring">Bring them here</button></div>` : ""}
        <form class="btn-row" data-form="message"><input class="input sm grow" name="message" placeholder="Private message" maxlength="256" required><button class="btn sm">Send</button></form>
        <div class="btn-row"><button class="btn sm" data-give>🎁 Give items</button><button class="btn sm danger" data-pa="kick">Kick</button></div>
      </div>`).join("")}</div>`;
  }
  $("#ctl-players")?.addEventListener("click", async (e) => {
    const g = e.target.closest("button[data-give]");
    if (g) return openGiveItem(sid, g.closest("[data-player]").dataset.player);
    const b = e.target.closest("button[data-pa]");
    if (!b) return;
    const card = b.closest("[data-player]"), p = card.dataset.player, a = b.dataset.pa;
    const target = card.querySelector("[data-target]")?.value;
    if (a === "kick") {
      if (!(await confirmBox(`Kick ${p}?`, "They can join again right away unless bedtime or a screen-time limit is on.", "Kick"))) return;
      return act(`player/${encodeURIComponent(p)}/kick`, { reason: "Kicked by an admin" }, `Kicked ${p}`);
    }
    act(`player/${encodeURIComponent(p)}/${a}`, { target }, "Done");
  });
  $("#ctl-players")?.addEventListener("change", (e) => {
    const sel = e.target.closest('select[data-pa="gamemode"]');
    if (!sel || !sel.value) return;
    const p = sel.closest("[data-player]").dataset.player;
    act(`player/${encodeURIComponent(p)}/gamemode`, { mode: sel.value }, `${p} is now in ${sel.value}`);
    sel.value = "";
  });
  $("#ctl-players")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target, p = form.closest("[data-player]").dataset.player, f = new FormData(form);
    if (form.dataset.form === "message") { if (await act(`player/${encodeURIComponent(p)}/message`, { message: f.get("message") }, "Message sent")) form.reset(); }
  });

  // ---- whitelist / ops
  function renderLists() {
    const el = $("#ctl-lists");
    if (!el || !info.lists) return;
    const L = info.lists;
    const chips = (names, action, label) => names.length
      ? names.map((n) => `<span class="chip">${esc(n)}<button class="chip-x" type="button" data-list="${action}" data-name="${esc(n)}" aria-label="${label} ${esc(n)}">×</button></span>`).join("")
      : `<span class="muted">None</span>`;
    el.innerHTML = `<p class="muted small" style="margin-bottom:10px">The whitelist is <b>${L.enabled ? "on" : "off"}</b>${L.enabled ? ": only these players can join." : ". Anyone with the address can join. Turn it on in server.properties (white-list=true) or with /whitelist on."}</p>
      <div class="lists"><div><h3>Whitelist</h3><div class="chips">${chips(L.whitelist, "whitelist_remove", "Remove")}</div></div>
      <div><h3>Operators</h3><div class="chips">${chips(L.ops, "deop", "Remove operator")}</div></div></div>
      ${(info.asked || []).length ? `<div class="turned-away asked"><h3>Asked to join <small class="muted">from the website's join guide</small></h3>
        <ul>${info.asked.map((b) => `<li><code class="ta-name">${esc(b.player)}</code>${b.player.startsWith(".") ? ' <span class="chip">Bedrock</span>' : ""}${b.name ? ` <span>${esc(b.name)}</span>` : ""}<span class="muted small">${esc(fmtAgo(b.ts))}</span>
          <button class="btn sm" type="button" data-copy-name="${esc(b.player)}">Copy</button><button class="btn sm" type="button" data-fix-name="${esc(b.player)}">✏️ Fix name</button><button class="btn sm primary" type="button" data-allow="${esc(b.player)}">Let them in</button><button class="btn sm danger" type="button" data-deny="${esc(b.player)}">Deny</button>
          ${b.note ? `<p class="ta-note">“${esc(b.note)}”</p>` : ""}</li>`).join("")}</ul></div>` : ""}
      ${(info.blocked || []).length ? `<div class="turned-away"><h3>Tried to join <small class="muted">turned away by the whitelist in the last two weeks</small></h3>
        <ul>${info.blocked.map((b) => `<li><code class="ta-name">${esc(b.name)}</code>${b.bedrock ? ' <span class="chip">Bedrock</span>' : ""}<span class="muted small">${esc(fmtAgo(b.ts))}</span>
          <button class="btn sm" type="button" data-copy-name="${esc(b.name)}">Copy</button><button class="btn sm primary" type="button" data-allow="${esc(b.name)}">Let them in</button></li>`).join("")}</ul></div>` : ""}
      <form class="btn-row" id="list-form" style="margin-top:12px"><input class="input sm" name="name" placeholder="Name (.Name for Bedrock)" pattern="\.?[A-Za-z0-9_]{1,16}" required>
        <button class="btn sm" name="do" value="whitelist_add">Add to whitelist</button><button class="btn sm" name="do" value="op">Make operator</button></form>`;
  }
  $("#ctl-lists")?.addEventListener("click", async (e) => {
    const copy = e.target.closest("[data-copy-name]"), allow = e.target.closest("[data-allow]");
    if (copy) { navigator.clipboard?.writeText(copy.dataset.copyName).then(() => showToast("Copied", 1500), () => showToast(esc(copy.dataset.copyName), 4000)); return; }
    const deny = e.target.closest("[data-deny]");
    if (deny) { if (await denyRequest(deny.dataset.deny)) { info.asked = (info.asked || []).filter((b) => b.player !== deny.dataset.deny); renderLists(); } return; }
    const fix = e.target.closest("[data-fix-name]");
    if (fix) { const to = await fixRequestName(fix.dataset.fixName); const b = (info.asked || []).find((x) => x.player === fix.dataset.fixName);
      if (to && b) { b.player = to; renderLists(); } return; }
    if (allow) {
      const n = allow.dataset.allow;
      if (await confirmBox(`Let ${n} in?`, "They're added to the whitelist and can join straight away.", "Let them in", false)) {
        if (await act(`player/${encodeURIComponent(n)}/whitelist_add`, {}, `${esc(n)} can join now`)) { info.blocked = (info.blocked || []).filter((b) => b.name !== n); info.asked = (info.asked || []).filter((b) => b.player !== n); renderLists(); }
      }
      return;
    }
    const x = e.target.closest("[data-list]");
    if (!x) return;
    const what = x.dataset.list === "deop" ? `Remove ${x.dataset.name} as an operator?` : `Remove ${x.dataset.name} from the whitelist?`;
    if (await confirmBox(what, "", "Remove")) act(`player/${encodeURIComponent(x.dataset.name)}/${x.dataset.list}`, {}, "Done");
  });
  $("#ctl-lists")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = new FormData(e.target).get("name"), action = e.submitter?.value || "whitelist_add";
    if (action === "op" && !(await confirmBox(`Make ${name} an operator?`, "Operators can use every command, including stopping the server.", "Make operator"))) return;
    if (await act(`player/${encodeURIComponent(name)}/${action}`, {}, "Done")) e.target.reset();
  });

  // ---- bedtime
  function renderBedtime() {
    const el = $("#ctl-bedtime");
    if (!el) return;
    const rules = info.bedtime || [];
    const dayList = (days) => days.length === 7 ? "every night" : days.map((d) => DAY_NAMES[d].slice(0, 3)).join(", ");
    $("#bed-status").textContent = rules.length ? "On" : "Off";
    el.innerHTML = `${rules.length ? `<ul class="pt-covers">${rules.map((r) => `<li><b>${esc(r.name)}</b>: ${esc(dayList(r.days))}, ${esc(fmtClock(r.start))} to ${esc(fmtClock(r.end))}</li>`).join("")}</ul>`
      : '<p class="muted">No bedtime for this server.</p>'}${info.can_rcon ? "" : '<p class="muted small"><b>Bedtime needs RCON.</b></p>'}
      <p><a class="btn sm" href="#/manage/playtime">⏰ Bedtimes and screen time: Manage → Play time</a></p>`;
  }

  if (info.is_java) { renderPlayers(); renderLists(); renderBedtime(); }
  if (!state.lang[sid] || Object.keys(state.lang[sid]).length < 50) await ensureServerAssets(sid);
  every(10000, async () => {
    const before = JSON.stringify([info.online, info.lists]);
    info = await api(`${base}/control`).catch(() => info);
    if (JSON.stringify([info.online, info.lists]) !== before && !document.activeElement?.closest("#ctl-players, #ctl-lists")) { renderPlayers(); renderLists(); }
    if ($("#ctl-audit")) $("#ctl-audit").innerHTML = auditHtml(info.audit);
  });
}

function fmtClock(hhmm) {
  const [h, m] = String(hhmm).split(":").map(Number);
  return new Date(2000, 0, 1, h, m).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function rulesHtml(rules, canRcon) {
  if (!canRcon) return `<p class="muted small">Game rules need RCON on this server.</p>`;
  if (!rules.length) return `<p class="muted small">Couldn't read game rules from this server.</p>`;
  return `<div class="rules-ctl">${rules.map((r) => r.kind === "bool"
    ? `<label class="switch-row"><span>${esc(r.label)}</span><input type="checkbox" role="switch" data-rule="${esc(r.key)}" ${r.value ? "checked" : ""}></label>`
    : `<label class="switch-row"><span>${esc(r.label)}</span><input class="input sm num-in" type="number" min="0" max="100" data-rule="${esc(r.key)}" value="${esc(r.value)}"></label>`).join("")}</div>`;
}

// What Solstone keeps about a server that Manage → Solstone can clear (db.clear_server, worldmap.clear_tiles).
const CLEAR_KINDS = [
  ["chat", "Chat", "Everything said in the game's chat and from the website."],
  ["activity", "Activity", "Joins, leaves, deaths, advancements, contests and the like: recent activity and players' timelines."],
  ["recaps", "Daily recaps", "The summary of each day, and “on this day”."],
  ["play", "Play history", "Who played when (days played, last seen, play time), where they went, and Adventures. Their first-time welcome message comes again."],
  ["performance", "Performance graphs", "CPU, memory, players and how smoothly it ran."],
  ["fishing", "Fishing journal", "Every fish caught, and the records."],
  ["map", "Map pictures", "The top-down map of the world. It's drawn again from the new world as people look at it."],
];

// ================================================================ Users & activity
// Manage → Players, Servers & live info, Activity log (one section each).
async function viewAdmin(section = "users") {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = `${{ users: "Players", setup: "Server setup", servers: "History & data", activity: "Activity log" }[section] || "Manage"} · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  const [users, lp, hiddenSrv, siteCfg, playerCfg, ptCfg] = await Promise.all([api("/api/users"), Promise.resolve(null), Promise.resolve([]), api("/api/posts").then((d) => d.site).catch(() => ({})), api("/api/settings/players").catch(() => ({})), section === "users" ? api("/api/settings/playtime").catch(() => null) : null]);
  const roleOpts = (cur) => ROLE_NAMES.map(([v, l]) => `<option value="${v}" ${cur === v ? "selected" : ""}>${l}</option>`).join("");
  const fmtWhen = (ts) => ts ? fmtAgo(ts) : "never";
  const srvName = (id) => state.servers.find((x) => x.id === id)?.name || id;
  const usersHtml = `<section class="section"><div class="section-head"><h2>Users</h2><span class="muted">Players see the servers, who's on, the leaderboards and their own page. Trusted can see everything (chat, where everyone is, inventories) but can't change anything. Admins can also control servers.</span></div>
      <div class="panel rules-ctl" id="signup-ctl" style="max-width:720px;margin-bottom:12px">
        <p class="muted small">Players making their own account (and the Ask to join form) are switched on in <a href="#/manage/website">Website → Site details</a>, under <b>Getting started</b>.</p>
        <label class="switch-row"><span><b>Players can see the map</b><br><small class="muted">Gives Players the World tab: the map of the world with where everyone is (and the web map, if the server has one). The world's seed stays hidden.</small></span><input type="checkbox" role="switch" id="players-map-on" ${playerCfg.see_map ? "checked" : ""}></label></div>
      <div class="table-wrap"><table class="data users-table"><thead><tr><th>Username</th><th>Level</th><th>Minecraft player</th><th>Servers</th><th>Last signed in</th><th></th></tr></thead><tbody>
      ${users.map((u) => `<tr data-uid="${u.id}"><td><b>${esc(u.username)}</b>${u.shown && u.shown !== u.username ? ` <span class="muted">shown as ${esc(u.shown)}</span>` : ""}${u.real_name ? `<br><small class="muted" title="Their real name: only admins see it">👤 ${esc(u.real_name)}</small>` : ""}${u.id === me.user.id ? ' <span class="muted">(you)</span>' : ""}</td>
        <td><select class="input sm" data-role ${u.id === me.user.id ? "disabled" : ""} aria-label="Level for ${esc(u.username)}">${roleOpts(u.role)}</select></td>
        <td><button class="btn sm" type="button" data-link title="Link this account to the people they play as (Java and Bedrock)">${(u.players || []).length ? esc(u.players.map((p) => p.name).join(", ")) : "Link…"}</button>${ptCfg && (u.players || []).length ? `<br><a class="small muted" href="#/manage/playtime" title="Bedtime and screen time: Manage → Play time">⏰ ${esc(ptSummary(ptCfg.rows.find((r) => r.key === `u${u.id}`)))}</a>` : ""}</td>
        <td>${u.role === "admin" ? '<span class="muted">All</span>' : `<button class="btn sm" type="button" data-srv title="Which servers they see">${u.servers ? esc(u.servers.length === 1 ? srvName(u.servers[0]) : `${u.servers.length} servers`) : "All"}</button>`}</td>
        <td>${esc(fmtWhen(u.last_login))}</td>
        <td class="row-actions">${u.two_step ? `<span class="chip" title="Two-step sign-in is on">🔐</span>${u.id === me.user.id ? "" : '<button class="btn sm" data-ts-off title="Lost their phone and backup codes? Turn it off so they can sign in with just the password">Two-step off</button>'}` : ""}<button class="btn sm" data-reset>Set password</button>${u.id === me.user.id ? "" : `<button class="btn sm danger" data-del>Remove</button>`}</td></tr>`).join("")}
      </tbody></table></div>
      <form class="panel add-user" id="add-user" autocomplete="off"><h3>Add a user</h3>
        <div class="add-grid"><label>Username<input class="input" name="username" required pattern="[A-Za-z0-9_.\\-]{2,32}" autocapitalize="off"></label>
        <label>Password<input class="input" name="password" type="password" minlength="8" autocomplete="new-password" placeholder="8 or more characters" required></label>
        <label>Level<select class="input" name="role">${roleOpts("trusted")}</select></label>
        <button class="btn primary" type="submit">Add user</button></div></form>
    </section>`;
  const setupHtml = `<section class="section" id="srv-manage"><div class="section-head"><h2>Your servers</h2><span class="muted">Each one's name, how Solstone reaches it, and who sees it</span></div>
      <div class="srv-list"><p class="muted">Loading…</p></div></section>
    <section class="section" id="conn-manage"><div class="section-head"><h2>Connections</h2><span class="muted">What starts and stops your servers and says how they're doing</span></div>
      <div class="conn-list"><p class="muted">Loading…</p></div></section>`;
  const serversHtml = `<section class="section"><div class="section-head"><h2>Recap history</h2></div>
      <div class="panel" style="max-width:720px"><p class="muted small">Every day is summarised and kept for good, so “on this day” can look back years. When Solstone first starts it also reads each server's old logs (the <code>logs/*.log.gz</code> files Minecraft keeps) to fill in the days before it was installed. If you've copied older logs in, read them again here.</p>
        <button class="btn" id="ann-backfill" type="button" style="margin-top:8px">Read old logs again</button></div></section>
    <section class="section"><div class="section-head"><h2>🌐 Website traffic</h2><span class="muted">What Solstone answered, who asked, and how quickly</span></div>
      <div class="panel" id="traffic" style="max-width:860px"><p class="muted">Loading…</p></div></section>
    <section class="section"><div class="section-head"><h2>📖 What people read</h2><span class="muted">Each page of the website: how many looked, and read it to the end</span></div>
      <div class="panel" id="reading" style="max-width:860px"><p class="muted">Loading…</p></div></section>
    <section class="section"><div class="section-head"><h2>💾 Storage</h2><span class="muted">How much room Solstone takes, and what grows</span></div>
      <div class="panel" id="storage" style="max-width:720px"><p class="muted">Loading…</p></div></section>
    <section class="section"><div class="section-head"><h2>Solstone's own backups</h2><span class="muted">Accounts, settings, posts and history</span></div>
      <div class="panel" id="self-backups" style="max-width:720px"><p class="muted">Loading…</p></div></section>
    <section class="section"><div class="section-head"><h2>Clear saved history</h2><span class="muted">For a new world, or a fresh start</span></div>
      <form class="panel clear-form" id="clear-form" style="max-width:720px">
        <p class="muted small">Only what Solstone kept. The game server isn't touched: the world, everyone's items, the whitelist and the server's own log files all stay.</p>
        <label>Server <select class="input" name="sid">${(state.servers || []).map((x) => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("")}</select></label>
        ${CLEAR_KINDS.map(([k, t, d]) => `<label class="check"><input type="checkbox" name="what" value="${k}"> <span><b>${t}</b><br><small class="muted">${d}</small></span></label>`).join("")}
        <div class="btn-row"><button class="btn sm" type="button" data-new-world>Tick what a new world needs</button><button class="btn danger" type="submit">Clear</button></div></form></section>`;
  const activityHtml = `<section class="section"><div class="section-head"><h2>Admin activity</h2><span class="muted">Commands, changes and sign-in failures across all servers</span></div>
      <div class="panel" id="audit-browse"><p class="muted">Loading…</p></div></section>`;
  setView({ users: usersHtml, setup: setupHtml, servers: serversHtml, activity: activityHtml }[section] || usersHtml);
  if ($("#srv-manage")) { manageServers(); manageConnections(); }
  if ($("#audit-browse")) mountAuditBrowser($("#audit-browse"));

  const selfBackups = async () => {
    const box = $("#self-backups");
    if (!box) return;
    const d = await api("/api/solstone-backups").catch(() => null);
    if (!d) { box.innerHTML = `<p class="muted">Couldn't load the backups.</p>`; return; }
    const size = (n) => n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
    box.innerHTML = `<p class="muted small">One a day (every ${d.every_hours} h), the newest ${d.keep} kept, in <code>${esc(d.folder)}</code>. Point your off-site backup (Duplicacy, Kopia, rclone…) at that folder. The world itself is in Crafty's backups. A backup holds every account and the RCON passwords, so keep copies somewhere private and encrypted. To restore: stop Solstone, unzip one into its data folder, start it again.</p>
      ${d.backups.length ? `<ul class="sb-list">${d.backups.slice(0, 5).map((b) => `<li><span>${esc(fmtAgo(b.ts))}</span><span class="muted small">${esc(size(b.size))}</span><a class="btn sm" href="/api/solstone-backups/${encodeURIComponent(b.name)}" download>Download</a></li>`).join("")}</ul>`
        : `<p><b>No backups yet.</b> The first one is made within the hour.</p>`}
      <button class="btn sm" type="button" data-backup-now>Back up now</button>`;
  };
  selfBackups();
  // website traffic: who asked (you, other admins, players, visitors), by hour, how quick, and the container's network
  let trDays = 1, trWho = "all";
  const traffic = async () => {
    const box = $("#traffic");
    if (!box) return;
    const d = await api(`/api/traffic?days=${trDays}`).catch(() => null);
    if (!d) { box.innerHTML = `<p class="muted">Couldn't load it.</p>`; return; }
    const sz = (n) => (n >= 1073741824 ? `${(n / 1073741824).toFixed(2)} GB` : n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`);
    const WHO = [["you", "You"], ["admins", "Other admins"], ["players", "Signed-in players"], ["visitors", "Visitors (not signed in)"]];
    const COL = { you: "#f2c14e", admins: "#b18cff", players: "#5fd08a", visitors: "#6aa9ff" };
    const tiles = WHO.map(([k, l]) => { const g = d.groups[k] || { requests: 0, bytes: 0 }; return `<button type="button" class="st-tile tr-tile ${trWho === k ? "on" : ""}" data-trwho="${k}" aria-pressed="${trWho === k}" style="--c:${COL[k]}">
        <span class="st-tile-label"><i class="tr-key" aria-hidden="true"></i>${l}</span><b>${g.requests.toLocaleString()}</b><small class="muted">requests · ${sz(g.bytes)} sent${k === "visitors" && d.visitors ? ` · about ${d.visitors} ${d.visitors === 1 ? "visitor" : "different visitors"}` : ""}</small></button>`; }).join("");
    // Hours grouped so the bars stay readable: each hour for a day, 6 hours for a week, each day for a month.
    const per = trDays === 1 ? 1 : trDays === 7 ? 6 : 24;
    const buckets = [];
    for (let i = 0; i < d.hours.length; i += per) {
      const part = d.hours.slice(i, i + per), b = { hour: part[0].hour, end: part[part.length - 1].hour + 3600 };
      for (const [k] of WHO) b[k] = part.reduce((n, h) => n + (h[k] || 0), 0);
      buckets.push(b);
    }
    const shown = WHO.map(([k]) => k).filter((k) => trWho === "all" || trWho === k);
    const tot = (b) => shown.reduce((n, k) => n + b[k], 0);
    const when = (b) => {
      const a = new Date(b.hour * 1000), z = new Date(b.end * 1000);
      if (per === 24) return a.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
      const t = (x) => x.toLocaleTimeString([], { hour: "numeric" });
      return `${per > 1 ? `${a.toLocaleDateString([], { weekday: "short" })} ` : ""}${t(a)}–${t(z)}`;
    };
    const tick = (b) => (per === 24 ? new Date(b.hour * 1000).toLocaleDateString([], { month: "short", day: "numeric" })
      : per === 6 ? new Date(b.hour * 1000).toLocaleDateString([], { weekday: "short" }) : new Date(b.hour * 1000).toLocaleTimeString([], { hour: "numeric" }));
    const sp = d.speed, quick = sp.requests ? Math.round((sp.buckets[0] / sp.requests) * 100) : null;
    const slow = sp.buckets[3];
    const kinds = Object.entries(d.kinds).sort((a, b2) => b2[1] - a[1]).map(([k, n]) => `${({ pages: "pages", api: "data", map: "the map", files: "pictures and files" })[k] || k} ${n.toLocaleString()}`).join(" · ");
    const unit = per === 24 ? "day" : per === 6 ? "6 hours" : "hour";
    box.innerHTML = `<div class="st-filters"><div class="seg" role="group" aria-label="How long">${[[1, "Last 24 hours"], [7, "7 days"], [30, "30 days"]].map(([n, l]) => `<button type="button" data-trdays="${n}" aria-pressed="${trDays === n}">${l}</button>`).join("")}</div>
        ${trWho !== "all" ? `<button type="button" class="btn sm" data-trwho="all">Show everyone</button>` : ""}</div>
      <div class="st-tiles tr-tiles">${tiles}</div>
      <p class="muted small tr-explain">Each bar is one ${unit}: how many things the website answered then, coloured by who asked. Point at (or tap) a bar for the details; tap a box above to see just them.</p>
      <div class="tr-chart" role="img" aria-label="Requests each ${unit}, by who asked"><div class="tr-plot"></div><div class="tr-tip" hidden></div></div>
      <p class="tr-speed">${sp.requests ? `<b>${quick}%</b> answered in under 0.1 s · on average <b>${sp.avg_ms} ms</b> · ${slow ? `<b class="wl-no">${slow} took over a second</b>` : "none took over a second"}` : "Nothing answered yet in this time."}</p>
      ${kinds ? `<p class="muted small">What was asked for: ${esc(kinds)}</p>` : ""}
      ${(d.slow || []).length ? `<details class="tr-slow"><summary>🐢 The slowest lately (${d.slow.length}, since Solstone last started)</summary>
        <ul>${d.slow.map((x) => `<li><span class="muted">${esc(new Date(x.at * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }))}</span>
          <b>${x.secs.toFixed(1)} s</b> <code>${esc(x.what)}</code>${x.status >= 400 ? ` <span class="wl-no">${x.status}</span>` : ""}</li>`).join("")}</ul></details>` : ""}
      ${d.net.available ? `<p class="muted small">This container's whole network (the website, plus talking to the game, Crafty, Modrinth): <b>${sz(d.net.tx)}</b> sent, <b>${sz(d.net.rx)}</b> received.</p>` : ""}
      <p class="muted small">No addresses are kept: visitors are counted with a scramble that changes every day. Cloudflare's dashboard shows what never reaches here (bots it blocks, countries, attacks).</p>`;
    box.querySelectorAll("[data-trdays]").forEach((b) => b.addEventListener("click", () => { trDays = +b.dataset.trdays; traffic(); }));
    box.querySelectorAll("[data-trwho]").forEach((b) => b.addEventListener("click", () => { trWho = trWho === b.dataset.trwho ? "all" : b.dataset.trwho; traffic(); }));
    // Drawn at the chart's real size (nothing stretched), with a scale on the left.
    const chart = box.querySelector(".tr-chart"), plot = chart.querySelector(".tr-plot"), tip = chart.querySelector(".tr-tip");
    const W = Math.max(280, plot.clientWidth), H = 170, L = 40, B = 20, T = 8, pw = W - L, ph = H - B - T;
    const top = Math.max(...buckets.map(tot), 1);
    const nice = (() => { const st = Math.max(1, 10 ** Math.floor(Math.log10(top)) / 2); return Math.ceil(top / st) * st; })();   // 2,360 → 2,500
    const y = (v) => T + ph - (v / nice) * ph, step = pw / buckets.length, bw = Math.max(2, Math.min(28, step * 0.72));
    const grid = [0, 0.5, 1].map((f) => `<line x1="${L}" x2="${W}" y1="${y(nice * f)}" y2="${y(nice * f)}" class="tr-grid"/><text x="${L - 6}" y="${y(nice * f) + 4}" text-anchor="end" class="tr-axis">${(nice * f).toLocaleString([], { maximumFractionDigits: 1 })}</text>`).join("");
    const labelEvery = Math.ceil(buckets.length / Math.max(3, Math.floor(pw / 70)));
    const bars = buckets.map((b, i) => {
      const x = L + i * step + (step - bw) / 2;
      let acc = 0;
      const segs = shown.map((k) => { if (!b[k]) return ""; const y0 = y(acc), y1 = y(acc + b[k]); acc += b[k]; return `<rect x="${x}" y="${y1}" width="${bw}" height="${Math.max(1, y0 - y1)}" fill="${COL[k]}"/>`; }).join("");
      const lab = i % labelEvery === 0 ? `<text x="${L + i * step + step / 2}" y="${H - 4}" text-anchor="middle" class="tr-axis">${esc(tick(b))}</text>` : "";
      return `<g data-i="${i}"><rect class="tr-hit" x="${L + i * step}" y="${T}" width="${step}" height="${ph}"/>${segs}</g>${lab}`;
    }).join("");
    plot.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${grid}${bars}</svg>`;
    const show = (e) => {
      const g = e.target.closest("[data-i]");
      plot.querySelectorAll("g.on").forEach((x) => x.classList.remove("on"));
      if (!g) { tip.hidden = true; return; }
      g.classList.add("on");
      const b = buckets[+g.dataset.i];
      tip.innerHTML = `<b>${esc(when(b))}</b>${shown.map((k) => `<span><i class="tr-key" style="--c:${COL[k]}"></i>${WHO.find(([w]) => w === k)[1]}: <b>${b[k].toLocaleString()}</b></span>`).join("")}${shown.length > 1 ? `<span class="muted">Together: ${tot(b).toLocaleString()}</span>` : ""}`;
      tip.hidden = false;
      const r = chart.getBoundingClientRect();
      tip.style.left = `${Math.min(Math.max(4, e.clientX - r.left - tip.offsetWidth / 2), r.width - tip.offsetWidth - 4)}px`;
    };
    plot.addEventListener("pointermove", show);
    plot.addEventListener("pointerdown", show);
    chart.addEventListener("pointerleave", () => { tip.hidden = true; plot.querySelectorAll("g.on").forEach((x) => x.classList.remove("on")); });
  };
  traffic();
  // what people read: each page's views, people, read to the end and time on it (admins' own visits not counted)
  let rdDays = 30, rdPage = null;
  const readingView = async () => {
    const box = $("#reading");
    if (!box) return;
    const d = await api(`/api/reading?days=${rdDays}`).catch(() => null);
    if (!d) { box.innerHTML = `<p class="muted">Couldn't load it.</p>`; return; }
    const secs = (n) => (n == null ? "–" : n < 60 ? `${n} s` : `${Math.floor(n / 60)} min${n % 60 ? ` ${n % 60} s` : ""}`);
    const name = (p) => (p.page === "/" ? "🏠 Home page" : p.page === "/help" ? "📰 News & Help" : p.page === "/events" ? "📅 Events" : esc(p.title));
    const rows = d.pages.map((p) => `<tr><td><a href="${esc(p.page)}" target="_blank" rel="noopener">${name(p)}</a>${p.page.startsWith("/guides/") ? ' <span class="chip">Guide</span>' : ""}</td>
        <td class="num">${p.views.toLocaleString()}</td>
        <td class="num" title="${p.visitors} not signed in, ${p.players} signed-in players">${p.people.toLocaleString()}<small class="muted rd-split">${p.visitors} · ${p.players}</small></td>
        <td class="num">${p.article ? `${p.reads.toLocaleString()}${p.views ? ` <small class="muted">${Math.round(Math.min(1, p.reads / p.views) * 100)}%</small>` : ""}` : '<span class="muted">–</span>'}</td>
        <td class="num">${secs(p.avg_secs)}</td></tr>`).join("");
    const total = d.daily.reduce((n, x) => n + x.views, 0);
    box.innerHTML = `<div class="st-filters"><div class="seg" role="group" aria-label="How long">${[[1, "Today"], [7, "7 days"], [30, "30 days"], [365, "A year"]].map(([n, l]) => `<button type="button" data-rddays="${n}" aria-pressed="${rdDays === n}">${l}</button>`).join("")}</div>
        ${rdPage ? `<button type="button" class="btn sm" data-rdall>Show every page</button>` : ""}</div>
      ${rows ? `<div class="tr-chart rd-chart" role="img" aria-label="Page views over time"><div class="tr-plot"></div><div class="tr-tip" hidden></div></div>
      <div class="rd-keys"></div>
      <p class="muted small">${total.toLocaleString()} page view${total === 1 ? "" : "s"} in all. Each bar is ${({ 3600: "an hour", 21600: "6 hours", 86400: "a day", 604800: "a week" })[d.slot_secs] || "a stretch"}; point at one to see which pages. Tap a page in the list to see just that one.</p>
      <div class="rd-wrap"><table class="rd-table"><thead><tr><th>Page</th><th class="num">Views</th><th class="num" title="Different people (not signed in · signed-in players)">People</th><th class="num" title="Reached the end and had it open ${d.read_secs} seconds or more">Read it</th><th class="num">Time on it</th></tr></thead>
        <tbody>${rows}</tbody></table></div>` : `<p class="muted">Nobody's looked yet in this time (your own visits don't count).</p>`}
      <p class="muted small"><b>People</b> counts each person once a day (not signed in · signed-in players). <b>Read it</b>: news posts and guides opened, scrolled to the end, and kept open ${d.read_secs} seconds or more. <b>Time on it</b>: the average while it was on their screen. Admins' visits aren't counted, and nobody's named: these are counts per page.</p>`;
    box.querySelectorAll("[data-rddays]").forEach((b) => b.addEventListener("click", () => { rdDays = +b.dataset.rddays; readingView(); }));
    box.querySelector("[data-rdall]")?.addEventListener("click", () => { rdPage = null; readingView(); });
    box.querySelectorAll(".rd-table tbody tr").forEach((tr, i) => {
      tr.classList.toggle("on", d.pages[i].page === rdPage);
      tr.addEventListener("click", (e) => { if (e.target.closest("a")) return; rdPage = rdPage === d.pages[i].page ? null : d.pages[i].page; readingView(); });
    });
    if (rows) drawReading(box, d, name);
  };
  // The timeline: views in each bar, coloured by page (the five most viewed, the rest together as "Other pages").
  const RD_COL = ["#6aa9ff", "#5fd08a", "#f2c14e", "#b18cff", "#ff8f6b"];
  const drawReading = (box, d, name) => {
    const top = (rdPage ? [d.pages.find((p) => p.page === rdPage)].filter(Boolean) : d.pages.slice(0, RD_COL.length));
    const keys = top.map((p, i) => ({ page: p.page, label: name(p), col: RD_COL[i] }));
    const other = !rdPage && d.pages.length > top.length;
    if (other) keys.push({ page: null, label: "Other pages", col: "#8a93a6" });
    const val = (s, k) => (k.page ? s.pages[k.page] || 0 : Object.entries(s.pages).filter(([p]) => !top.some((t) => t.page === p)).reduce((n, [, v]) => n + v, 0));
    box.querySelector(".rd-keys").innerHTML = keys.map((k) => `<span><i class="tr-key" style="--c:${k.col}"></i>${k.label}</span>`).join("");
    const chart = box.querySelector(".rd-chart"), plot = chart.querySelector(".tr-plot"), tip = chart.querySelector(".tr-tip");
    const W = Math.max(280, plot.clientWidth), H = 150, L = 34, B = 20, T = 8, pw = W - L, ph = H - B - T;
    const slots = d.slots, tot = (s) => keys.reduce((n, k) => n + val(s, k), 0);
    const nice = Math.max(4, Math.ceil(Math.max(1, ...slots.map(tot)) / 4) * 4);
    const y = (v) => T + ph - (v / nice) * ph, step = pw / slots.length, bw = Math.max(2, Math.min(26, step * 0.72));
    const when = (s) => {
      const a = new Date(s.t * 1000);
      if (d.slot_secs >= 604800) return `Week of ${a.toLocaleDateString([], { month: "short", day: "numeric" })}`;
      if (d.slot_secs >= 86400) return a.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
      const z = new Date((s.t + d.slot_secs) * 1000), t = (x) => x.toLocaleTimeString([], { hour: "numeric" });
      return `${d.slot_secs > 3600 ? `${a.toLocaleDateString([], { weekday: "short" })} ` : ""}${t(a)}–${t(z)}`;
    };
    const tick = (s) => (d.slot_secs >= 86400 ? new Date(s.t * 1000).toLocaleDateString([], { month: "short", day: "numeric" })
      : d.slot_secs > 3600 ? new Date(s.t * 1000).toLocaleDateString([], { weekday: "short" }) : new Date(s.t * 1000).toLocaleTimeString([], { hour: "numeric" }));
    const every = Math.ceil(slots.length / Math.max(3, Math.floor(pw / 70)));
    const grid = [0, 0.5, 1].map((f) => `<line x1="${L}" x2="${W}" y1="${y(nice * f)}" y2="${y(nice * f)}" class="tr-grid"/><text x="${L - 6}" y="${y(nice * f) + 4}" text-anchor="end" class="tr-axis">${Math.round(nice * f)}</text>`).join("");
    const bars = slots.map((s, i) => {
      const x = L + i * step + (step - bw) / 2;
      let acc = 0;
      const segs = keys.map((k) => { const v = val(s, k); if (!v) return ""; const y0 = y(acc), y1 = y(acc + v); acc += v; return `<rect x="${x}" y="${y1}" width="${bw}" height="${Math.max(1, y0 - y1)}" fill="${k.col}"/>`; }).join("");
      const lab = i % every === 0 ? `<text x="${L + i * step + step / 2}" y="${H - 4}" text-anchor="middle" class="tr-axis">${esc(tick(s))}</text>` : "";
      return `<g data-i="${i}"><rect class="tr-hit" x="${L + i * step}" y="${T}" width="${step}" height="${ph}"/>${segs}</g>${lab}`;
    }).join("");
    plot.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${grid}${bars}</svg>`;
    const show = (e) => {
      const g = e.target.closest("[data-i]");
      plot.querySelectorAll("g.on").forEach((x) => x.classList.remove("on"));
      if (!g) { tip.hidden = true; return; }
      g.classList.add("on");
      const s = slots[+g.dataset.i];
      const all = Object.entries(s.pages).sort((a, b) => b[1] - a[1]);
      const label = (p) => { const x = d.pages.find((q) => q.page === p); return x ? name(x) : esc(p); };
      tip.innerHTML = `<b>${esc(when(s))}</b>${all.length ? all.slice(0, 8).map(([p, v]) => `<span>${label(p)}: <b>${v}</b></span>`).join("") + (all.length > 8 ? `<span class="muted">and ${all.length - 8} more</span>` : "") : '<span class="muted">Nobody</span>'}`;
      tip.hidden = false;
      const r = chart.getBoundingClientRect();
      tip.style.left = `${Math.min(Math.max(4, e.clientX - r.left - tip.offsetWidth / 2), r.width - tip.offsetWidth - 4)}px`;
    };
    plot.addEventListener("pointermove", show);
    plot.addEventListener("pointerdown", show);
    chart.addEventListener("pointerleave", () => { tip.hidden = true; plot.querySelectorAll("g.on").forEach((x) => x.classList.remove("on")); });
  };
  readingView();
  (async () => {
    const box = $("#storage");
    if (!box) return;
    const d = await api("/api/solstone-storage").catch(() => null);
    if (!d) { box.innerHTML = `<p class="muted">Couldn't work it out.</p>`; return; }
    const sz = (n) => (n >= 1073741824 ? `${(n / 1073741824).toFixed(1)} GB` : n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
    const PART = { "solstone.db": "The database (history, accounts, posts)", backups: "Solstone's own backups", site: "Pictures in posts and the logo",
      skins: "Players' skins (fetched again if deleted)", assets: "Item pictures, one set per Minecraft version (old versions' can be deleted)",
      mrpack: "The modpack download", maptiles: "The world map's pictures (one per 512 × 512 blocks explored)", "tide-guide": "The tackle guide", "settings.json": "Settings" };
    const top = Math.max(1, ...d.parts.map((p) => p.bytes));
    box.innerHTML = `<p><b>${esc(sz(d.total))}</b> in <code>${esc(d.folder)}</code> · <span class="muted">${esc(sz(d.disk.free))} free on that disk${d.measured ? ` · measured ${esc(fmtAgo(d.measured))} (again every 10 minutes)` : ""}</span></p>
      <ul class="st-list">${d.parts.filter((p) => p.bytes > 0).map((p) => `<li><span>${esc(PART[p.name] || p.name)}</span><span class="st-bar"><i style="width:${(p.bytes / top) * 100}%"></i></span><b>${esc(sz(p.bytes))}</b></li>`).join("")}</ul>
      <details><summary>Inside the database</summary><table class="data st-table"><thead><tr><th>What</th><th>Rows</th><th>Size</th><th>Kept</th></tr></thead><tbody>
        ${d.tables.map((t) => `<tr><td>${esc(t.what || t.name)}</td><td>${fmtNum(t.rows)}</td><td>${t.bytes ? esc(sz(t.bytes)) : "–"}</td><td class="muted">${esc(t.kept || "")}</td></tr>`).join("")}</tbody></table>
        <p class="muted small">The world map's pictures grow with the world, not with time: one picture for each 512 × 512 blocks someone has explored (plus smaller zoomed-out ones), redrawn in place when that part changes. Clearing a server's map history (below) deletes them; they're drawn again when the map is looked at.</p>
        <p class="muted small">Adventures trails are the part that grows: a row every few seconds for each player while anyone plays. Old ones are cleared each day, so it levels off. The database file doesn't shrink when rows are cleared; it reuses the room.</p></details>`;
  })();
  $("#self-backups")?.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-backup-now]");
    if (!b) return;
    b.disabled = true; b.textContent = "Backing up…";
    try { await post("/api/solstone-backups"); showToast("Backed up", 2000); } catch (err) { showError(esc(err.message), 6000); }
    selfBackups();
  });
  $("#clear-form")?.addEventListener("click", (e) => {
    if (!e.target.closest("[data-new-world]")) return;
    $$('#clear-form [name="what"]').forEach((i) => { i.checked = ["play", "map", "activity"].includes(i.value); });
  });
  $("#clear-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target), what = f.getAll("what"), name = state.servers.find((x) => x.id === f.get("sid"))?.name || f.get("sid");
    if (!what.length) { showError("Tick what to clear first", 3000); return; }
    const list = CLEAR_KINDS.filter(([k]) => what.includes(k)).map(([, t]) => t.toLowerCase()).join(", ");
    if (!await confirmBox(`Clear ${name}'s ${list}?`, "This can't be undone. The game server and its world aren't changed.", "Clear")) return;
    try {
      await post(`/api/servers/${encodeURIComponent(f.get("sid"))}/clear`, { what });
      showToast(`Cleared ${esc(name)}'s ${esc(list)}`, 3500); e.target.reset();
    } catch (err) { showError(esc(err.message), 6000); }
  });
  $("#ann-backfill")?.addEventListener("click", async (e) => {
    e.target.disabled = true; e.target.textContent = "Reading…";
    try { const r = await post("/api/recap/backfill"); showToast(r.days ? `Filled in ${r.days} days` : "Nothing new in the old logs", 3500); }
    catch (err) { showError(esc(err.message), 5000); }
    e.target.disabled = false; e.target.textContent = "Read old logs again";
  });
  $("#add-user")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try { await post("/api/users", { username: f.get("username"), password: f.get("password"), role: f.get("role") }); showToast(`Added ${esc(f.get("username"))}`, 2500); viewAdmin(section); }
    catch (err) { showError(esc(err.message), 5000); }
  });
  $("#players-map-on")?.addEventListener("change", async (e) => {
    try { await post("/api/settings/players", { see_map: e.target.checked }, "PUT"); showToast(e.target.checked ? "Players can see the map (World tab)" : "The map is for Trusted and Admins only", 2500); }
    catch (err) { showError(esc(err.message), 5000); e.target.checked = !e.target.checked; }
  });
  $("#signup-on")?.addEventListener("change", async (e) => {
    try { await post("/api/settings/site", { signup: e.target.checked }, "PUT"); showToast(e.target.checked ? "Players can make their own account" : "Sign-up turned off", 2500); }
    catch (err) { showError(esc(err.message), 5000); }
  });
  $$("[data-link]").forEach((b) => b.addEventListener("click", async () => {
    const tr = b.closest("tr"), uid = tr.dataset.uid, name = tr.querySelector("b").textContent;
    let u = users.find((x) => String(x.id) === uid) || {};
    const known = await api("/api/users/players").catch(() => []);
    const linked = () => (u.players || []).length
      ? `<ul class="my-players">${u.players.map((p) => `<li><b>${esc(p.name)}</b>${p.name.startsWith(".") ? ' <span class="chip">Bedrock</span>' : ""}<button class="btn sm" type="button" data-unlink="${esc(p.uuid)}">Unlink</button></li>`).join("")}</ul>`
      : `<p class="muted small">Not linked to anyone who plays yet.</p>`;
    const pills = () => `<div class="chips link-pills">${known.filter((p) => !p.linked_to).map((p) => `<button type="button" class="chip-btn" data-pick="${esc(p.name)}">${esc(p.name)}</button>`).join("") || '<span class="muted small">Everyone who has played is linked already.</span>'}</div>`;
    openModal(`<h2>${esc(name)}: players and name</h2>
      <div id="link-list">${linked()}</div>
      <form id="link-add" class="btn-row"><input class="input sm" name="player" placeholder="Minecraft name" autocapitalize="off" list="link-known" required>
        <datalist id="link-known">${known.map((p) => `<option value="${esc(p.name)}">`).join("")}</datalist><button class="btn sm primary" type="submit">Link</button></form>
      <p class="muted small">Not linked yet, on a whitelist or have played:</p><div id="link-pills">${pills()}</div>
      <form id="link-form"><label>Real name <small>Optional. Only admins see it.</small><input class="input" name="real_name" maxlength="40" value="${esc(u.real_name || "")}"></label>
      <div class="actions"><button type="button" class="btn" data-close-modal>Close</button><button class="btn primary" type="submit">Save name</button></div></form>`, (m) => {
      const change = async (body) => {
        try {
          u = await post(`/api/users/${uid}`, body, "PATCH");
          const k = known.find((p) => body.add_player && p.name.toLowerCase() === body.add_player.toLowerCase()); if (k) k.linked_to = u.username;
          if (body.remove_player) known.forEach((p) => { if (p.uuid === body.remove_player) p.linked_to = null; });
          $("#link-list", m).innerHTML = linked(); $("#link-pills", m).innerHTML = pills();
          tr.querySelector("[data-link]").textContent = (u.players || []).length ? u.players.map((p) => p.name).join(", ") : "Link…";
        } catch (err) { showError(esc(err.message), 5000); }
      };
      m.addEventListener("click", (e) => {
        const pick = e.target.closest("[data-pick]"), un = e.target.closest("[data-unlink]");
        if (pick) change({ add_player: pick.dataset.pick });
        if (un) change({ remove_player: un.dataset.unlink });
      });
      $("#link-add", m).addEventListener("submit", (e) => { e.preventDefault(); change({ add_player: e.target.player.value }); e.target.reset(); });
      $("#link-form", m).addEventListener("submit", async (e) => {
        e.preventDefault();
        try { await post(`/api/users/${uid}`, { real_name: new FormData(e.target).get("real_name") || "" }, "PATCH"); closeModal(); showToast("Saved", 2000); viewAdmin(section); }
        catch (err) { showError(esc(err.message), 5000); }
      });
    });
  }));
  $$("[data-role]").forEach((sel) => sel.addEventListener("change", async () => {
    const uid = sel.closest("tr").dataset.uid;
    try { await post(`/api/users/${uid}`, { role: sel.value }, "PATCH"); showToast("Level changed", 2500); }
    catch (err) { showError(esc(err.message), 5000); viewAdmin(section); }
  }));
  // which servers a login sees (admins always see all)
  $$("[data-srv]").forEach((b) => b.addEventListener("click", () => {
    const tr = b.closest("tr"), u = users.find((x) => String(x.id) === tr.dataset.uid), cur = u.servers;
    openModal(`<h2>Servers ${esc(u.username)} sees</h2><form id="srv-form">
      <label class="check"><input type="checkbox" name="all" ${cur ? "" : "checked"}> Every server <small class="muted">(and any added later)</small></label>
      <fieldset class="checks" id="srv-list" ${cur ? "" : "disabled"}>${state.servers.map((x) => `<label class="check"><input type="checkbox" name="sid" value="${esc(x.id)}" ${!cur || cur.includes(x.id) ? "checked" : ""}> ${esc(x.name)}</label>`).join("")}</fieldset>
      <p class="muted small">They don't see the others anywhere: not in the server list, the announcements or Events.</p>
      <div class="actions"><button type="button" class="btn" data-close-modal>Cancel</button><button class="btn primary" type="submit">Save</button></div></form>`, (m) => {
      const f = $("#srv-form", m);
      f.all.addEventListener("change", () => { $("#srv-list", m).disabled = f.all.checked; });
      f.addEventListener("submit", async (e) => {
        e.preventDefault();
        const picked = [...f.querySelectorAll('[name="sid"]:checked')].map((x) => x.value);
        if (!f.all.checked && !picked.length) { showToast("Pick at least one server", 3000); return; }
        try { await post(`/api/users/${u.id}`, { servers: f.all.checked ? null : picked }, "PATCH"); closeModal(); showToast("Saved", 2000); viewAdmin(section); }
        catch (err) { showError(esc(err.message), 5000); }
      });
    });
  }));
  $$("[data-ts-off]").forEach((b) => b.addEventListener("click", async () => {
    const tr = b.closest("tr"), name = tr.querySelector("b").textContent;
    if (!(await confirmBox(`Turn off two-step sign-in for ${name}?`, "They'll sign in with just their password (and can turn it on again). They're signed out everywhere now.", "Turn off"))) return;
    try { await post(`/api/users/${tr.dataset.uid}/two-step-off`, {}); showToast(`Two-step sign-in is off for ${esc(name)}`, 2500); viewAdmin("users"); }
    catch (err) { showError(esc(err.message), 4000); }
  }));
  $$("[data-reset]").forEach((b) => b.addEventListener("click", () => {
    const tr = b.closest("tr"), name = tr.querySelector("b").textContent;
    openModal(`<h2>Set a new password for ${esc(name)}</h2><form id="reset-form">
      <label>New password <small>8+ characters. They'll be signed out everywhere.</small><input class="input" type="password" name="password" minlength="8" autocomplete="new-password" required></label>
      <div class="actions"><button type="button" class="btn" data-close-modal>Cancel</button><button class="btn primary" type="submit">Set password</button></div></form>`, (m) => {
      $("#reset-form", m).addEventListener("submit", async (e) => {
        e.preventDefault();
        try { await post(`/api/users/${tr.dataset.uid}`, { password: new FormData(e.target).get("password") }, "PATCH"); closeModal(); showToast("Password set", 2500); }
        catch (err) { showError(esc(err.message), 5000); }
      });
    });
  }));
  $$("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    const tr = b.closest("tr"), name = tr.querySelector("b").textContent;
    if (!(await confirmBox(`Remove ${name}?`, "They'll be signed out and won't be able to sign in again.", "Remove"))) return;
    try { await api(`/api/users/${tr.dataset.uid}`, { method: "DELETE" }); showToast(`Removed ${esc(name)}`, 2500); viewAdmin(section); }
    catch (err) { showError(esc(err.message), 5000); }
  }));
}

// ---------------------------------------------------------------- fireworks settings
const FW_LABELS = [
  ["ball", "Small ball"], ["large", "Large ball"], ["star", "Star"], ["burst", "Burst"], ["ring", "Ring"],
  ["crossette", "Crossette", "bursts twice"], ["spiral", "Spiral"], ["willow", "Willow", "falling glitter"],
  ["saturn", "Saturn", "ball with a ring"], ["pair", "Mirror pair", "one from each side"],
  ["candle", "Roman candle", "a row of shots"], ["cake", "Barrage", "a fast fan of shots"],
  ["fountain", "Fountain", "on the hill"], ["wheel", "Spinning wheel", "on the hill"],
  ["sparkler", "Sparkler", "the watcher waves one"], ["shootingstar", "Shooting star"],
  ["cube", "Block"], ["pickaxe", "Pickaxe"], ["axe", "Axe"], ["creeper", "Creeper"], ["heart", "Heart"],
  ["dragon", "Ender dragon", "show-piece"], ["bow", "Bow and arrow", "show-piece"], ["tree", "Tree", "show-piece"],
];
function fireworksSettingsHtml(fw) {
  const seg = (name, opts, cur) => `<div class="seg" role="group" data-fw-seg="${name}">${opts.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${v === cur}">${l}</button>`).join("")}</div>`;
  const weights = fw.weights || Object.fromEntries(Object.entries(fw.kinds || {}).map(([k, v]) => [k, v ? 1 : 0]));
  return `<h3 class="fw-sub">Built-in fireworks <span class="muted small">how often each one comes up</span></h3>
    <div class="fw-kinds">${FW_LABELS.map(([k, l, note]) => `<div class="fw-kind ${weights[k] ? "" : "off"}">
      <span class="fw-kname">${esc(l)}${note ? ` <small class="muted">${esc(note)}</small>` : ""}</span>
      ${freqSeg(`data-fw-weight="${k}"`, weights[k] ?? 1)}
      <button type="button" class="icon-btn fw-try" data-try="${k}" title="Launch one now" aria-label="Try ${esc(l)}">▶</button></div>`).join("")}</div>
    <p class="muted small" style="margin:-4px 0 14px">Dragon, bow and arrow, and tree are show-pieces: their frequencies are compared with each other, and “Show-pieces” below sets how often any of them appears.</p>
    <div class="fw-row"><span>Colours</span><div class="fw-colors">${FW_COLORS.map((c) => `<button type="button" class="fw-swatch" data-color="${c}" aria-pressed="${fw.colors.includes(c)}" style="--c:${c}" aria-label="Colour ${c}"></button>`).join("")}</div></div>
    <div class="fw-row"><span>How often</span>${seg("pace", [["calm", "Calm"], ["normal", "Normal"], ["lively", "Lively"]], fw.pace)}</div>
    <p class="muted small">Everyone's usual. Each person can pick their own in the 🎆 Launch list (Show pace), just for their device.</p>
    <div class="fw-row"><span>Show-pieces</span>${seg("showpieces", [["rare", "Rare"], ["sometimes", "Sometimes"], ["often", "Often"]], fw.showpieces)}</div>
    <p class="muted small">Creeper, heart and tree keep their own colours, and willows are often classic gold. The ▶ buttons are easiest to watch with the Show switch (bottom right) turned off.</p>`;
}
// Off · Rare · Normal · Often · Lots, used for kinds, designs and people.
const FREQS = [[0, "Off"], [0.5, "Rare"], [1, "Normal"], [2, "Often"], [4, "Lots"]];
function freqSeg(attr, cur) {
  return `<div class="seg freq" role="group" ${attr}>${FREQS.map(([v, l]) => `<button type="button" data-freq="${v}" aria-pressed="${+cur === v}">${l}</button>`).join("")}</div>`;
}
function wireFireworksSettings(el, fw) {
  const save = async (body) => {
    try {
      const cfg = await post("/api/settings/fireworks", body, "PUT");
      applyFireworkSettings(cfg); Object.assign(fw, cfg);
      showToast("Fireworks updated", 1800);
    } catch (err) { showError(esc(err.message), 4000); el.innerHTML = fireworksSettingsHtml(fw); wireFireworksSettings(el, fw); }
  };
  el.addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    const wseg = t.closest("[data-fw-weight]");
    if (wseg) {
      const k = wseg.dataset.fwWeight, v = +t.dataset.freq;
      const others = Object.entries(fw.weights || {}).some(([x, w]) => x !== k && w > 0);
      if (v === 0 && !others) { showToast("Leave at least one kind of firework on", 2500); return; }
      wseg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === t)));
      wseg.closest(".fw-kind").classList.toggle("off", v === 0);
      save({ weights: { [k]: v } });
      return;
    }
    if (t.dataset.try) { const label = FW_LABELS.find(([k]) => k === t.dataset.try)?.[1] || t.dataset.try; openFwPreview({ title: label, run: (sc) => sc.launch(t.dataset.try) }); return; }
    if (t.dataset.color) {
      const on = t.getAttribute("aria-pressed") !== "true";
      const colors = $$(".fw-swatch", el).filter((b) => (b === t ? on : b.getAttribute("aria-pressed") === "true")).map((b) => b.dataset.color);
      if (!colors.length) { showToast("Keep at least one colour", 2500); return; }
      t.setAttribute("aria-pressed", String(on));
      save({ colors });
      return;
    }
    const seg = t.closest("[data-fw-seg]");
    if (seg) {
      seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === t)));
      save({ [seg.dataset.fwSeg]: t.dataset.v });
    }
  });
}

// Fix the name on a request to join (typed wrong). Their page still hears they're in: it goes by their request.
async function fixRequestName(player) {
  const bedrockHint = player.startsWith(".")
    ? " Bedrock: a dot, then the gamertag with spaces as _ and its number joined on. Xbox's \"mama bear#7349\" is .mama_bear7349." : "";
  const to = await promptBox(`Fix ${player}'s name`, `The name as it is in the game.${bedrockHint}`, player, 17);
  if (!to || to === player) return "";
  try { await post("/api/whitelist/rename", { player, to }); showToast(`Now ${esc(to)}: let them in when ready`, 3000); return to; }
  catch (err) { showError(esc(err.message), 6000); return ""; }
}
// Who a name on a whitelist really is: its id there, who Xbox or Mojang says owns that id, and whether they've played.
async function whoisBox(sid, name) {
  openModal(`<h2>Who is ${esc(name)}?</h2><p class="muted">Checking…</p>`, () => {});
  let w;
  try { w = await api(`/api/whitelist/whois?sid=${encodeURIComponent(sid)}&name=${encodeURIComponent(name)}`); }
  catch (err) { closeModal(); showError(esc(err.message), 5000); return; }
  const owner = w.bedrock ? w.gamertag : w.java_name;
  const match = owner && (w.bedrock ? `.${owner.replace(/ /g, "_")}`.toLowerCase() === name.toLowerCase() : owner.toLowerCase() === name.toLowerCase());
  openModal(`<h2>Who is ${esc(name)}?</h2>
    <dl class="wl-whois-list">
      <dt>On the whitelist as</dt><dd><code>${esc(w.name)}</code> ${w.bedrock ? '<span class="chip">Bedrock</span>' : '<span class="chip">Java</span>'}</dd>
      <dt>Their id</dt><dd><code>${esc(w.uuid)}</code></dd>
      ${w.bedrock ? `<dt>Xbox account number (XUID)</dt><dd><code>${esc(w.xuid || "?")}</code></dd>` : ""}
      <dt>${w.bedrock ? "Xbox says that's" : "Mojang says that's"}</dt><dd>${owner ? `<b>${esc(owner)}</b> ${match ? '<span class="wl-in">✅ matches</span>' : '<span class="wl-no">⚠️ a different name: they may have changed it</span>'}` : `<span class="muted">${esc(w.error || "Couldn't find out")}</span>`}</dd>
      <dt>Played here</dt><dd>${w.played ? `✅ Yes${w.played_as && w.played_as !== w.name ? `, as <b>${esc(w.played_as)}</b>` : ""}` : '<span class="muted">Not yet: once they join, their id here is theirs for sure</span>'}</dd>
    </dl>
    <p class="muted small">The id is what the server really goes by. ${w.bedrock ? "For Bedrock it's built from the Xbox account number, so it's the same account whatever the gamertag looks like." : "For Java it's their Mojang account."}</p>
    <div class="actions"><button class="btn" type="button" data-close>Close</button></div>`, (m) => $("[data-close]", m).addEventListener("click", closeModal));
}

// Say no to someone who asked to join (Manage → Players → Whitelist and Control): their page tells them it wasn't accepted.
// Saying no, with a reason they'll see where they asked ("Ask again with your real name in the note").
function denyRequest(player) {
  return new Promise((done) => {
    openModal(`<h2>Deny ${esc(player)}'s request?</h2>
      <p class="muted">It comes off Asked to join. They aren't added to any whitelist, and can ask again.</p>
      <form id="deny-form" class="deny-form"><label>A message for them <small>Optional. They see it on the home page, where they asked.</small>
        <textarea class="input" name="reason" rows="3" maxlength="300" placeholder="Can you ask again with your real name, or a note saying who you know here?"></textarea></label>
        <div class="actions"><button type="button" class="btn" data-close-modal>Cancel</button><button class="btn danger" type="submit">Deny</button></div></form>`, (m) => {
      $("#deny-form textarea", m).focus();
      $("[data-close-modal]", m).addEventListener("click", () => done(false));
      $("#deny-form", m).addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await post("/api/whitelist/deny", { player, reason: new FormData(e.target).get("reason") || "" });
          closeModal(); showToast(`Denied ${esc(player)}'s request`, 2500); done(true);
        } catch (err) { showError(esc(err.message), 6000); }
      });
    });
  });
}

// ================================================================ Manage → Players → Whitelist
// Everyone who asked to join (each server they asked for, in or not), everyone the whitelist turned away, and each
// server's list, across all servers. Letting someone in runs the game's own whitelist command on that server.
async function viewWhitelist() {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = `Whitelist · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  const d = await api("/api/whitelist");
  cmRefreshUnread();                                   // the number on your name: asks still waiting
  const ago = (ts) => esc(fmtAgo(ts));
  const pill = (sid, name, inOk, player) => inOk
    ? `<span class="wl-in">✅ ${esc(name)}</span>`
    : `<button class="btn sm primary" type="button" data-let="${esc(player)}" data-sid="${esc(sid)}">Let in on ${esc(name)}</button>`;
  const unseen = (d.answered || []).filter((a) => !a.seen).length;
  const reqHtml = d.requests.length ? d.requests.map((r) => {
    const waiting = r.servers.filter((x) => !x.in);
    return `<li class="wl-req"><div class="wl-who"><code class="ta-name">${esc(r.player)}</code>${r.bedrock ? ' <span class="chip">Bedrock</span>' : ""}
        ${r.name ? `<span>${esc(r.name)}</span>` : ""}<span class="muted small">${ago(r.ts)}</span>
        <button class="btn sm" type="button" data-copy-name="${esc(r.player)}">Copy</button>
        <button class="btn sm" type="button" data-fix-name="${esc(r.player)}" title="Typed it wrong? Fix it, then let them in: they still hear they're in">✏️ Fix name</button></div>
      ${r.asked_as && r.asked_as !== r.player ? `<p class="muted small">Asked as <code>${esc(r.asked_as)}</code></p>` : ""}
      ${r.note ? `<p class="ta-note">“${esc(r.note)}”</p>` : ""}
      <div class="wl-servers">${r.servers.map((x) => pill(x.id, x.name, x.in, r.player)).join("")}
        ${waiting.length > 1 ? `<button class="btn sm" type="button" data-let-all="${esc(r.player)}" data-sids="${esc(waiting.map((x) => x.id).join(","))}">Let in on all ${waiting.length}</button>` : ""}
        <button class="btn sm danger" type="button" data-deny="${esc(r.player)}">Deny</button></div></li>`;
  }).join("") : "";
  const blockedHtml = d.blocked.length ? d.blocked.map((b) => `<li class="wl-req"><div class="wl-who"><code class="ta-name">${esc(b.name)}</code>${b.bedrock ? ' <span class="chip">Bedrock</span>' : ""}
      <span class="muted small">turned away ${ago(b.ts)}</span><button class="btn sm" type="button" data-copy-name="${esc(b.name)}">Copy</button></div>
      <div class="wl-servers">${b.servers.map((x) => pill(x.id, x.name, false, b.name)).join("")}</div></li>`).join("") : "";
  setView(`<div class="fwe-head"><h1>Whitelist</h1>
      <p class="muted">Who's asked to join, who the whitelist turned away, and who's on each server's list. A player's account gets every server they're on the whitelist of.</p></div>
    <section class="section"><div class="section-head"><h2>Asked to join</h2><span class="muted">${d.requests.length || "Nobody"} waiting</span>
      ${(d.answered || []).length ? `<button type="button" class="btn sm wl-answered-btn" id="wl-answered">👀 Answered lately${unseen ? ` · <b>${unseen} not seen yet</b>` : ""}</button>` : ""}</div>
      ${reqHtml ? `<ul class="wl-list">${reqHtml}</ul>` : `<div class="panel"><p class="muted">No requests waiting. With <i>Ask to join</i> on (Website → Site details), they show here, and you get a notification.</p></div>`}</section>
    ${blockedHtml ? `<section class="section"><div class="section-head"><h2>Tried to join</h2><span class="muted">Turned away in the last two weeks</span></div><ul class="wl-list">${blockedHtml}</ul></section>` : ""}
    <section class="section"><div class="section-head"><h2>Each server's list</h2></div>
      <form class="panel btn-row wl-add" id="wl-add"><input class="input sm" name="name" placeholder="Name (.Name for Bedrock)" pattern="\\.?[A-Za-z0-9_]{1,16}" required>
        ${d.servers.map((s, i) => `<label class="check"><input type="checkbox" name="sid" value="${esc(s.id)}" ${i === 0 ? "checked" : ""}> ${esc(s.name)}</label>`).join("")}
        <button class="btn sm primary" type="submit">Add</button></form>
      <div class="wl-grid">${d.servers.map((s) => `<div class="panel"><h3>${esc(s.name)}${s.private ? ' <span class="chip">Private</span>' : ""}</h3>
        <p class="muted small">The whitelist is <b>${s.enabled ? "on" : "off"}</b>${s.enabled ? "" : ": anyone with the address can join"}.</p>
        <div class="chips">${s.whitelist.length ? s.whitelist.map((n) => `<span class="chip"><button type="button" class="link-btn wl-whois" data-whois="${esc(n)}" data-sid="${esc(s.id)}" title="Who is this?">${esc(n)}</button><button class="chip-x" type="button" data-unlist="${esc(n)}" data-sid="${esc(s.id)}" aria-label="Remove ${esc(n)}">×</button></span>`).join("") : '<span class="muted">Nobody yet</span>'}</div></div>`).join("")}</div></section>`);
  const letIn = async (name, sid) => {
    try { await post(`/api/servers/${encodeURIComponent(sid)}/control/player/${encodeURIComponent(name)}/whitelist_add`, {}); return true; }
    catch (err) { showError(`${esc(d.servers.find((x) => x.id === sid)?.name || sid)}: ${esc(err.message)}`, 7000); return false; }
  };
  // answered lately: in a popup, so it doesn't take up the page
  $("#wl-answered")?.addEventListener("click", () => openModal(`<h2>👀 Answered lately</h2>
      <p class="muted small">Requests let in or not accepted in the last two weeks, and whether they've seen the answer on the website. You get a notification when they do.</p>
      <ul class="wl-list wl-answered-list">${d.answered.map((a) => `<li class="wl-req wl-answered"><div class="wl-who"><code class="ta-name">${esc(a.player)}</code>${a.player.startsWith(".") ? ' <span class="chip">Bedrock</span>' : ""}
        ${a.name ? `<span>${esc(a.name)}</span>` : ""}</div>
        <div class="wl-ans-line"><span class="${a.denied ? "wl-no" : "wl-in"}">${a.denied ? "❌ Not accepted" : "✅ Let in"} ${ago(a.ts_in)}</span>
        ${a.seen ? `<span class="wl-seen">👀 Saw it ${ago(a.seen)}</span>` : '<span class="muted small">Hasn\'t seen it on the website yet</span>'}
        <button type="button" class="icon-btn wl-ans-x" data-clear-ans="${esc(a.player)}" aria-label="Take ${esc(a.player)} off this list" title="Take off this list">✕</button></div></li>`).join("")}</ul>
      <p class="muted small">✕ only takes them off this list. Their own page still shows their answer.</p>
      <div class="actions"><button class="btn danger" type="button" data-clear-all>Clear all</button><button class="btn" type="button" data-close>Close</button></div>`, (m) => {
    $("[data-close]", m).addEventListener("click", closeModal);
    const clear = async (player) => {
      try { await post("/api/whitelist/answered/clear", player ? { player } : {}); } catch (err) { showError(esc(err.message), 4000); return; }
      closeModal();
      await viewWhitelist();
      if (player) $("#wl-answered")?.click();               // back to the list, one shorter
    };
    m.querySelectorAll("[data-clear-ans]").forEach((b) => b.addEventListener("click", () => clear(b.dataset.clearAns)));
    $("[data-clear-all]", m).addEventListener("click", () => clear(null));
  }));
  view().addEventListener("click", async (e) => {
    const copy = e.target.closest("[data-copy-name]"), one = e.target.closest("[data-let]"), all = e.target.closest("[data-let-all]"), un = e.target.closest("[data-unlist]");
    const deny = e.target.closest("[data-deny]");
    if (deny) { if (await denyRequest(deny.dataset.deny)) viewWhitelist(); return; }
    const fix = e.target.closest("[data-fix-name]");
    if (fix) { if (await fixRequestName(fix.dataset.fixName)) viewWhitelist(); return; }
    const who = e.target.closest("[data-whois]");
    if (who) { whoisBox(who.dataset.sid, who.dataset.whois); return; }
    if (copy) { navigator.clipboard?.writeText(copy.dataset.copyName).then(() => showToast("Copied", 1500), () => showToast(esc(copy.dataset.copyName), 4000)); return; }
    if (one) { one.disabled = true; if (await letIn(one.dataset.let, one.dataset.sid)) { showToast(`${esc(one.dataset.let)} can join now`, 2500); viewWhitelist(); } else one.disabled = false; return; }
    if (all) {
      all.disabled = true;
      let ok = 0;
      for (const sid of all.dataset.sids.split(",")) ok += await letIn(all.dataset.letAll, sid) ? 1 : 0;
      if (ok) showToast(`${esc(all.dataset.letAll)} let in on ${ok} server${ok === 1 ? "" : "s"}`, 3000);
      viewWhitelist(); return;
    }
    if (un && await confirmBox(`Take ${un.dataset.unlist} off the whitelist?`, "They won't be able to join that server.", "Remove")) {
      try { await post(`/api/servers/${encodeURIComponent(un.dataset.sid)}/control/player/${encodeURIComponent(un.dataset.unlist)}/whitelist_remove`, {}); showToast("Removed", 2000); }
      catch (err) { showError(esc(err.message), 6000); }
      viewWhitelist();
    }
  });
  $("#wl-add").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target), name = f.get("name"), sids = f.getAll("sid");
    if (!sids.length) { showError("Pick at least one server", 3000); return; }
    let ok = 0;
    for (const sid of sids) ok += await letIn(name, sid) ? 1 : 0;
    if (ok) showToast(`${esc(name)} added to ${ok} server${ok === 1 ? "" : "s"}`, 3000);
    viewWhitelist();
  });
  const rm = document.createElement("section");
  rm.className = "section";
  rm.innerHTML = removePlayerHtml();
  view().append(rm);
  wireForgetPlayer(rm);
}

// ---------------------------------------------------------------- removing a player for good
// A guide for the game side (done by hand: the server's files, land claims, the whitelist), and forgetting
// them in Solstone, guarded so it can't happen by accident: what goes is shown first, their name typed again,
// a server backup confirmed, nobody online under that name, and a Solstone backup made just before.
const FORGET_KINDS = [["sessions", "times they played (days played, play time, leaderboards)"], ["events", "lines in the activity feed and chat"],
  ["positions", "points of their Adventures trail"], ["fish", "fish in the fishing journal"], ["recaps", "daily recaps that name them (their name comes out)"],
  ["challenges", "contests, races and games they were in (results kept, as “a former player”)"], ["playtime", "bedtime and play-time rules"],
  ["join_firework", "join firework"], ["prizes_owed", "prizes still waiting for them"], ["join_requests", "asks to join"], ["votes", "votes from the game"]];

function removePlayerHtml() {
  return `<div class="section-head"><h2>🚪 Removing a player for good</h2><span class="muted">When someone has left and shouldn't come back</span></div>
    <div class="panel rm-guide">
      <p class="muted">Do these in order. The game and its mods keep things about each player by their <b>ID</b> (a long code; the check below shows it), so their files are named by it.</p>
      <ol>
        <li><b>Take a server backup</b> (in Crafty) before anything else. It's the only way to undo.</li>
        <li><b>Their land claims (Flan):</b> in the server console run <code>/flan help</code> to find the admin delete command for your Flan version, then delete all of their claims (it's usually <code>/flan adminDelete all &lt;name&gt;</code>). Their claimed land becomes free to build on.</li>
        <li><b>Off the whitelist</b>, above, on every server (or <code>/whitelist remove &lt;name&gt;</code> in the console). If they were an operator, <code>/deop &lt;name&gt;</code> too. If they must never come back, <code>/ban &lt;name&gt;</code>.</li>
        <li><b>Their files</b>, while they're offline (stopping the server is safest), in the world folder:
          <ul><li><code>playerdata/&lt;ID&gt;.dat</code> and <code>playerdata/&lt;ID&gt;.dat_old</code>: their inventory, ender chest and where they were</li>
            <li><code>stats/&lt;ID&gt;.json</code>: their statistics (Solstone's leaderboards read these)</li>
            <li><code>advancements/&lt;ID&gt;.json</code>: their advancements</li></ul>
          With the server stopped, you can also delete their line from <code>usercache.json</code> in the server folder (the game's list of names it has seen).</li>
        <li><b>Other mods</b> may keep their own files by the same ID (a search of the world's <code>data</code> folder for the ID finds them). Distant Horizons and BlueMap don't keep anything per player.</li>
        <li><b>Their website account</b>, if they made one: Manage → Players → delete. Their fireworks and messages go with it.</li>
        <li><b>Forget them in Solstone</b>, below. It can be done before or after the steps above. If they ever join again, Solstone starts a fresh history for them.</li>
      </ol>
    </div>
    <form class="panel rm-forget" id="rm-forget" autocomplete="off">
      <h3>🧹 Forget a player in Solstone</h3>
      <p class="muted small">Takes them off Solstone's pages on every server: history, play time, leaderboards, the activity feed, Adventures, the fishing journal and recaps. Nothing in the game is changed.</p>
      <div class="btn-row"><input class="input sm" name="name" placeholder="Minecraft name (.Name for Bedrock)" pattern="\\.?[A-Za-z0-9_]{1,16}" required>
        <button class="btn sm" type="submit">Check what would go</button></div>
      <div id="rm-plan"></div>
    </form>`;
}

function wireForgetPlayer(el) {
  const form = $("#rm-forget", el), out = $("#rm-plan", el);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = form.name.value.trim();
    let p;
    try { p = await api(`/api/players/forget?name=${encodeURIComponent(name)}`); } catch (err) { showError(esc(err.message), 4000); return; }
    const rows = FORGET_KINDS.filter(([k]) => p.counts[k]).map(([k, label]) => `<li><b>${p.counts[k].toLocaleString()}</b> ${esc(label)}</li>`).join("");
    out.innerHTML = `<div class="rm-plan">
      <p><b>${esc(p.name)}</b>${p.uuid ? ` · ID <code>${esc(p.uuid)}</code>` : " · not seen on any server"}${p.names.length > 1 ? ` · also played as ${esc(p.names.filter((n) => n !== p.name.toLowerCase()).join(", "))}` : ""}</p>
      ${p.total ? `<ul class="rm-counts">${rows}</ul>` : `<p class="muted">Solstone has nothing kept about them.</p>`}
      ${p.account ? `<p class="notice small">They have a website account (<b>${esc(p.account)}</b>). That isn't removed here: delete it in Manage → Players.</p>` : ""}
      ${p.online.length ? `<p class="notice small">They're playing on ${esc(p.online.join(", "))} right now. Wait until they've left.</p>` : ""}
      ${p.total && !p.online.length ? `<div class="rm-confirm">
        <label class="check"><input type="checkbox" name="backed_up"> I've taken a server backup (Solstone makes its own backup just before, too)</label>
        <label>To be sure, type <b>${esc(p.name)}</b> again<input class="input sm" name="confirm" autocomplete="off" spellcheck="false"></label>
        <button class="btn danger" type="button" data-forget disabled>Forget ${esc(p.name)} in Solstone</button>
        <p class="muted small">This can't be undone here. To get it back, restore the Solstone backup made just before (see Solstone's backups in Manage → Solstone).</p></div>` : ""}
    </div>`;
    const go = out.querySelector("[data-forget]");
    if (!go) return;
    const ready = () => { go.disabled = !(form.backed_up.checked && form.confirm.value.trim() === p.name); };
    form.backed_up.addEventListener("change", ready);
    form.confirm.addEventListener("input", ready);
    go.addEventListener("click", async () => {
      if (!(await confirmBox(`Forget ${p.name}?`, `${p.total.toLocaleString()} things about them come off Solstone's pages, on every server.`, "Forget them"))) return;
      try {
        const r = await post("/api/players/forget", { name: p.name, confirm: p.name, backed_up: true });
        out.innerHTML = `<p class="notice small">Done: ${r.total.toLocaleString()} things about ${esc(r.name)} are gone from Solstone. A backup was made just before.</p>`;
        form.reset();
      } catch (err) { showError(esc(err.message), 5000); }
    });
  });
}

// Manage → Server setup: every server Solstone has found, shown or hidden, each with its settings a click away.
async function manageServers() {
  const box = $("#srv-manage .srv-list");
  if (!box) return;
  const list = await api("/api/manage/servers").catch(() => null);
  if (!list) { box.innerHTML = `<p class="notice">Couldn't load the servers just now.</p>`; return; }
  if (!list.length) {
    box.innerHTML = `<p class="muted">No servers found yet. Solstone finds them in Crafty and in its servers folder, or add one that's somewhere else.</p>
      <div class="btn-row"><button class="btn primary" type="button" data-add-remote>🌐 Add a server somewhere else</button></div>`;
  }
  const wireAdd = () => box.querySelectorAll("[data-add-remote]").forEach((b) => b.addEventListener("click", () => openServerSetup(null, manageServers)));
  if (!list.length) { wireAdd(); return; }
  const chip = (cls, text, title = "") => `<span class="srv-chip ${cls}" ${title ? `title="${esc(title)}"` : ""}>${text}</span>`;
  box.innerHTML = list.map((x) => `<div class="panel srv-row ${x.hidden ? "is-hidden" : ""}" data-msid="${esc(x.id)}">
      <div class="srv-main"><b>${esc(x.name)}</b>${x.name !== x.found_as ? ` <span class="muted small">(${esc(x.found_as)})</span>` : ""}
        <div class="srv-chips">${x.new ? chip("new", "New", "Found by itself, so it starts hidden: show it when you're ready") : ""}
          ${chip(x.hidden ? "off" : "on", x.hidden ? "Hidden" : "Shown")}${x.private ? chip("warn", "Private", "Only admins see it") : ""}
          ${x.java ? chip(x.rcon && !x.rcon_error ? "on" : "warn", x.rcon ? (x.rcon_error ? "RCON not answering" : "RCON ✓") : "RCON off", x.rcon_error || "") : chip("", esc(x.game || "Bedrock"))}
          ${x.remote ? chip(x.files?.ok === false ? "warn" : x.files?.ok ? "on" : "", x.files?.ok === false ? "Files: not updating" : `🌐 ${esc(x.where)}`, x.files?.error || (x.files?.synced ? `Files updated ${fmtAgo(x.files.synced)}` : "Somewhere else, over SFTP"))
            + (x.panel ? chip(x.panel_error ? "warn" : "on", x.panel_error ? "Panel: not answering" : "Panel ✓", x.panel_error || "Start, stop, CPU and memory through the host's panel") : "")
            : chip("", x.crafty ? "Crafty" : "Folder", x.crafty ? "Started and stopped through Crafty" : `The ${x.folder} folder`)}${x.version ? chip("", esc(x.version)) : ""}${x.remote && x.map ? chip("", "🗺 Map", "Copies the parts of the world players go to, for the map") : ""}${backupChip(x.backup, chip)}</div></div>
      <div class="btn-row">${x.hidden ? `<button class="btn sm primary" type="button" data-show>Show it</button>` : `<a class="btn sm" href="#/s/${encodeURIComponent(x.id)}">Open</a>`}
        <button class="btn sm" type="button" data-edit>⚙ Settings</button></div></div>`).join("")
    + `<p class="muted small">A server Solstone finds for the first time starts <b>hidden</b>, so nothing new turns up on the website until you show it.</p>
    <div class="btn-row"><button class="btn" type="button" data-add-remote>🌐 Add a server somewhere else</button>
      <span class="muted small">A game host, a rented server, another computer: Solstone reaches its files over SFTP.</span></div>`;
  wireAdd();
  box.querySelectorAll("[data-msid]").forEach((row) => {
    const x = list.find((y) => y.id === row.dataset.msid);
    row.querySelector("[data-edit]").addEventListener("click", () => openServerSetup(x.id, manageServers));
    row.querySelector("[data-show]")?.addEventListener("click", async () => {
      try { await post(`/api/servers/${encodeURIComponent(x.id)}/settings`, { hidden: "" }, "PUT"); showToast(`${esc(x.name)} is shown`, 2500); await loadServers(); manageServers(); }
      catch (e) { showError(esc(e.message), 4000); }
    });
  });
}

// The full copy of a server elsewhere: running now, or how the last one went, and when the next is.
function fmtBytes(n) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"], i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i > 1 ? 1 : 0)} ${u[i]}`;
}
function backupChip(b, chip) {
  if (!b || !(b.on || b.last?.finished || b.running)) return "";
  const l = b.last || {}, stale = b.on && (!l.finished || Date.now() / 1000 - l.finished > 36 * 3600);
  if (b.running) return chip("", "💾 Copying…", b.progress?.phase || "");
  if (l.finished && !l.ok) return chip("warn", "💾 Full copy failed", l.error || "");
  return chip(stale || l.warning ? "warn" : "on", l.finished ? `💾 Copied ${fmtAgo(l.finished)}` : "💾 No full copy yet", l.warning || (stale ? "No full copy in the last day and a half" : `Next: ${b.next ? new Date(b.next * 1000).toLocaleString() : "when asked"}`));
}
function backupLine(b) {
  if (!b) return "";
  const p = b.progress || {}, l = b.last || {};
  const lines = [];
  if (b.running) lines.push(`<p class="muted small"><span class="spin" aria-hidden="true"></span> ${esc(p.phase || "Copying")}${p.files ? ` · ${p.fetched || 0} files (${fmtBytes(p.fetched_bytes)}) fetched of ${fmtBytes(p.to_fetch_bytes)} that changed · ${p.files} files, ${fmtBytes(p.total_bytes)} in all` : ""}</p>`);
  if (l.finished) {
    const when = `${esc(fmtAgo(l.finished))}${l.started ? `, took ${Math.max(1, Math.round((l.finished - l.started) / 60))} min` : ""}`;
    lines.push(l.ok ? `<p class="ok small">✓ Last full copy ${when}: ${l.files} files, ${fmtBytes(l.total_bytes)}; ${l.fetched} changed (${fmtBytes(l.fetched_bytes)} fetched)${l.removed ? `, ${l.removed} the server no longer has removed` : ""}. Checked: every file matches the server's.${l.paused_secs != null ? ` Saving paused ${Math.round(l.paused_secs)} s.` : ""}</p>`
      : `<p class="notice small">The last full copy (${when}) didn't finish: ${esc(l.error || "")}</p>`);
    if (l.ok && l.warning) lines.push(`<p class="notice small">${esc(l.warning)}</p>`);
  } else if (!b.running) lines.push(`<p class="muted small">No full copy yet.</p>`);
  if (b.on && b.next) lines.push(`<p class="muted small">Next: ${esc(new Date(b.next * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }))}.</p>`);
  if (b.folder) lines.push(`<p class="muted small">Kept in <code>${esc(b.folder)}</code> (inside Solstone's container: the folder you mapped to its data folder, then <code>remote/…</code>). Already have a copy? Put its files there before the first one, and only what differs is fetched (for region files, just the chunks that differ).</p>`);
  return lines.join("");
}

// One server's settings, the same window for every server (Manage → Server setup → Your servers):
//   1. General: its name, the web map, who sees it        3. RCON: commands, who's online, games
//   2. Its files: on this machine, or over SFTP            4. Start, stop and stats: Crafty, a host's panel, or none
// Here or somewhere else only changes where its files come from (2) and what can run it (4). sid null: adding one
// somewhere else (its files over SFTP).
async function openServerSetup(sid, then) {
  const [rows, conns] = await Promise.all([api("/api/manage/servers").catch(() => []), api("/api/manage/connections").catch(() => [])]);
  const row = sid ? rows.find((x) => x.id === sid) : null;
  if (sid && !row) { showError("Couldn't load its settings", 3000); return; }
  const remote = !sid || row.remote;
  const [cur, rc] = await Promise.all([sid ? api(`/api/servers/${encodeURIComponent(sid)}/settings`).catch(() => ({})) : {},
    remote && sid ? api(`/api/manage/remote/${encodeURIComponent(sid)}`).catch(() => null) : null]);
  const c = rc || { port: 22, path: "/", files_secs: 30 };
  const panels = conns.filter((x) => x.type === "panel" || x.type === "serverprism");
  const saved = (set) => (set ? "Saved. Type a new one to replace it." : "");
  let tested = null;
  const title = sid ? (cur.display_name || row.found_as) : "Add a server somewhere else";
  const filesHere = row && !remote ? `<p>📁 <b>On this machine</b>: the <code>${esc(row.folder)}</code> folder${row.crafty ? `, found through ${esc(row.crafty_name || "Crafty")}` : ""}.</p>
      <p class="muted small">Solstone reads its files where they are. (For a server at a game host or on another computer, use <b>Add a server somewhere else</b>.)</p>` : "";
  const filesThere = `<p class="muted small">🌐 <b>Somewhere else, over SFTP</b>: a game host, a rented server, another computer. Solstone keeps a copy of the few files it reads (the log, players' stats, the world's info) up to date, and reads that. In your host's panel, look for <b>SFTP details</b>: an address, a port and a username (the password is usually your panel password).</p>
      <div class="remote-grid">
        <label class="wide">Address<input class="input" name="host" required value="${esc(c.host || "")}" placeholder="sftp.examplehost.com" autocapitalize="off" spellcheck="false"></label>
        <label>Port<input class="input" name="port" inputmode="numeric" value="${esc(c.port || 22)}" style="width:90px"></label>
        <label class="wide">Username<input class="input" name="user" required value="${esc(c.user || "")}" placeholder="steve.1a2b3c4d" autocapitalize="off" spellcheck="false"></label>
        <label class="wide">Password <small class="muted">${saved(c.password_set)}</small><input class="input" type="password" name="password" autocomplete="new-password" ${c.password_set ? "" : "required"}></label>
        <label class="wide">Folder <small class="muted">where server.properties is; usually just /</small><input class="input" name="path" value="${esc(c.path || "/")}" autocapitalize="off" spellcheck="false"></label>
        <label class="wide">Look for new stats and player files every <select class="input sm" name="files_secs">${[[15, "15 seconds"], [30, "30 seconds"], [60, "minute"], [120, "2 minutes"], [300, "5 minutes"]].map(([v, l]) => `<option value="${v}" ${+c.files_secs === v ? "selected" : ""}>${l}</option>`).join("")}</select>
          <small class="muted">The log (who joined, chat, deaths) is followed every few seconds either way, fetching only its new lines.</small></label>
      </div>
      <label class="check"><input type="checkbox" name="map" ${c.map !== false ? "checked" : ""}> Draw the map where players have been <small class="muted">copies just those parts of the world (about 1-10 MB for each 512 × 512 blocks), and again when they change while someone's there; never the whole world</small></label>
      <h4 class="set-h">💾 A full copy here <small class="muted">a backup on this machine</small></h4>
      <label class="check"><input type="checkbox" name="backup" ${c.backup ? "checked" : ""}> Copy the whole server here each night <small class="muted">every file of the server (but logs and what the game downloads again by itself), updated with only what changed. The game's saving is paused for the last moments (save-off, save-all), so the copy is of one moment, not a file caught halfway. Point Kopia (or any backup) at its folder.</small></label>
      <div class="remote-grid">
        <label>At <input class="input" type="time" name="backup_at" value="${esc(c.backup_at || "04:00")}" style="width:120px"></label>
        <label class="check wide"><input type="checkbox" name="backup_dh" ${c.backup_dh !== false ? "checked" : ""}> With Distant Horizons' data <small class="muted">large, and fetched whole again on nights it changed; it can be rebuilt from the world</small></label>
      </div>
      <div id="backup-status">${sid ? backupLine(row?.backup) : ""}</div>
      <div class="btn-row"><button class="btn" type="button" data-test>🔌 Test the connection</button>
        ${sid ? `<button class="btn" type="button" data-backup-now>💾 Copy now</button>` : ""}
        ${sid && c.host_key ? `<button class="btn sm" type="button" data-forget-key title="Only if your host moved your server to another machine">Forget its identity</button>` : ""}</div>
      <div class="remote-result" id="remote-result">${c.host_key ? `<p class="muted small">Its identity: <code>${esc(c.host_key)}</code> (remembered the first time; Solstone won't connect if it changes)</p>` : ""}
        ${row?.files?.error ? `<p class="notice small">Its files aren't updating: ${esc(row.files.error)}</p>` : row?.files?.synced ? `<p class="muted small">Files last updated ${esc(fmtAgo(row.files.synced))}.</p>` : ""}
        ${row?.files?.["error_the map"] ? `<p class="notice small">The map isn't updating (everything else is): ${esc(row.files["error_the map"])}</p>` : ""}
        ${row?.files?.map ? `<p class="muted small">🗺 Map: <b>${row.files.map.visited}</b> area${row.files.map.visited === 1 ? "" : "s"} to copy (spawn, and where players are or were: ${row.files.map.now} around someone now) · <b>${row.files.map.copied}</b> copied · ${row.files.map.queued} waiting · looked ${esc(fmtAgo(row.files.map.looked))}${row.files.map.no_folder?.length ? ` · <span class="notice">no world folder found on the server for ${esc(row.files.map.no_folder.join(", "))}${row.files.map.world_has?.length ? ` (its world folder has: ${esc(row.files.map.world_has.join(", "))})` : ""}</span>` : ""}</p>` : ""}</div>`;
  const runner = !remote ? (row.crafty ? `<p>🧰 <b>${esc(row.crafty_name || "Crafty")}</b> starts and stops it, and says how it's doing. <span class="muted small">(Under <b>Connections</b> on this page.)</span></p>`
      : `<p class="muted">Nothing: Solstone found it as a folder, so it can't start or stop it. Add Crafty under <b>Connections</b> if Crafty runs it.</p>`)
    : panels.length ? `<p class="muted small">Which of your host connections it's on (Pterodactyl, Pelican or ServerPrism), then which server it is there.</p>
      <div class="remote-grid">
        <label class="wide">Panel<select class="input" name="conn"><option value="">None</option>${panels.map((p) => `<option value="${esc(p.id)}" ${c.conn === p.id ? "selected" : ""}>${esc(p.name)} (${esc(p.url.replace(/^https?:\/\//, ""))})</option>`).join("")}</select></label>
        <label class="wide">Server there<select class="input" name="panel_id">${c.panel_id ? `<option value="${esc(c.panel_id)}">${esc(c.panel_id)}</option>` : `<option value="">Pick the panel first</option>`}</select></label>
      </div>` : `<p class="muted small">Optional, for hosts on <b>Pterodactyl</b>, <b>Pelican</b> or <b>ServerPrism</b>: add it under <b>Connections</b> on this page first (once for every server there), then pick it here.</p>`;
  const html = `<h2>⚙ ${esc(title)}</h2>
    <form id="settings-form" class="remote-form" autocomplete="off">
      <h3 class="set-h">1. General</h3>
      <div class="remote-grid">
        <label class="wide">Name${remote && !sid ? "" : ` <small class="muted">blank: ${esc(row.found_as)}</small>`}<input class="input" name="display_name" maxlength="60" ${remote && !sid ? "required" : ""} value="${esc(remote && !sid ? "" : cur.display_name || "")}" placeholder="${esc(row?.found_as || "Family Survival")}"></label>
      </div>
      <label class="check"><input type="checkbox" name="private" ${cur.private ? "checked" : ""}> Private <small class="muted">only admins see it: never on the public pages, and signed-in players don't see it</small></label>
      ${sid ? `<label class="check"><input type="checkbox" name="hidden" ${cur.hidden ? "checked" : ""}> Hidden <small class="muted">Solstone leaves it alone: not on the website or any page, no history kept</small></label>` : ""}
      <p class="muted small">How to join it (addresses, a note, the mods) is in Manage → Website → Site details.</p>
      <h3 class="set-h">2. Its files</h3>
      ${remote ? filesThere : filesHere}
      <h3 class="set-h">3. RCON <small class="muted">commands, who's online, live inventories, games</small></h3>
      <p class="muted small">Read from the server's own server.properties (<code>enable-rcon</code>, <code>rcon.port</code>, <code>rcon.password</code>): leave these blank unless it's different.${remote ? " A game host has to let that port through: often an extra port (an <i>allocation</i>) you add in its panel and set as rcon.port." : ""}</p>
      <div class="remote-grid">
        <label class="wide">Address <small class="muted">blank: ${remote ? "the same as SFTP" : "this machine's usual one"}</small><input class="input" name="rcon_host" value="${esc(cur.rcon_host || "")}" autocapitalize="off" spellcheck="false"></label>
        <label>Port<input class="input" name="rcon_port" inputmode="numeric" value="${esc(cur.rcon_port || "")}" placeholder="auto" style="width:110px"></label>
        <label class="wide">Password <small class="muted">${cur.rcon_password_set ? "Saved. Type a new one to replace it." : "blank: from server.properties"}</small><input class="input" type="password" name="rcon_password" autocomplete="off"></label>
      </div>
      ${row?.java === false ? "" : row?.rcon_error ? `<p class="notice small">RCON isn't answering right now: ${esc(row.rcon_error)}</p>` : ""}
      <h3 class="set-h">4. Start, stop and stats <small class="muted">running or not, CPU and memory</small></h3>
      ${runner}
      <div class="actions">${remote && sid ? `<button type="button" class="btn danger" data-remove>Stop looking after it</button>` : ""}<span class="spacer"></span>
        <button type="button" class="btn" data-close-modal>Cancel</button><button class="btn primary" type="submit">${sid ? "Save" : "Add it"}</button></div>
    </form>`;
  const remoteBody = (form) => {
    const f = new FormData(form), out = { name: (f.get("display_name") || "").trim() || rc?.name || row?.found_as || "" };
    for (const k of ["host", "port", "user", "password", "path", "conn", "panel_id", "files_secs"]) out[k] = (f.get(k) || "").trim();
    out.map = !!f.get("map");
    out.backup = !!f.get("backup"); out.backup_dh = !!f.get("backup_dh"); out.backup_at = f.get("backup_at") || "04:00";
    if (sid) out.id = sid;
    return out;
  };
  openModal(html, (m) => {
    const form = $("#settings-form", m), result = $("#remote-result", m);
    // a panel's servers, to pick from (its API key lists the ones it can see)
    const loadPanelServers = async () => {
      const sel = form.panel_id, cid = form.conn?.value;
      if (!sel) return;
      if (!cid) { sel.innerHTML = `<option value="">Pick the panel first</option>`; return; }
      sel.innerHTML = `<option value="">Looking…</option>`;
      try {
        const list = await api(`/api/manage/connections/${encodeURIComponent(cid)}/servers`);
        sel.innerHTML = list.length ? list.map((x) => `<option value="${esc(x.id)}" ${c.panel_id === x.id ? "selected" : ""}>${esc(x.name)}${x.node ? ` · ${esc(x.node)}` : ""} (${esc(x.id)})</option>`).join("")
          : `<option value="">That key can't see any servers</option>`;
      } catch (err) { sel.innerHTML = `<option value="">${esc(err.message)}</option>`; }
    };
    form.conn?.addEventListener("change", loadPanelServers);
    if (c.conn) loadPanelServers();
    m.querySelector("[data-test]")?.addEventListener("click", async (e) => {
      if (!form.host.value || !form.user.value) { showToast("Fill in the address and username first", 3000); return; }
      e.target.disabled = true; result.innerHTML = `<p class="muted"><span class="spin" aria-hidden="true"></span> Connecting…</p>`;
      try {
        const r = await post("/api/manage/remote/test", remoteBody(form));
        tested = r;
        const f = r.files || {};
        const lines = [f.ok ? `<p class="ok">✓ Connected and found the server${f.motd ? `: <b>${esc(f.motd)}</b>` : ""}.</p>` : `<p class="notice">${esc(f.error || "Couldn't connect")}</p>`];
        if (f.host_key) lines.push(`<p class="muted small">Its identity: <code>${esc(f.host_key)}</code>. Solstone remembers it and won't connect if it ever changes.</p>`);
        if (f.ok) lines.push(f.rcon ? `<p class="muted small">RCON is on in server.properties (port ${esc(f.rcon_port || "25575")}). Make sure your host lets that port through.</p>`
          : `<p class="notice small">RCON is off in server.properties. Set <code>enable-rcon=true</code>, an <code>rcon.password</code> and an <code>rcon.port</code> your host lets through, then restart the server. Without it Solstone can show things but not run commands or games.</p>`);
        if (f.ok && f.files?.length) lines.push(`<details class="small"><summary>What's in the folder</summary><p class="muted">${f.files.map(esc).join(" · ")}</p></details>`);
        if (r.panel) lines.push(r.panel.ok ? `<p class="ok">✓ The panel answered: <b>${esc(r.panel.name)}</b>${r.panel.state ? ` (${esc(r.panel.state)})` : ""}${r.panel.node ? ` on ${esc(r.panel.node)}` : ""}.</p>` : `<p class="notice">Panel: ${esc(r.panel.error)}</p>`);
        result.innerHTML = lines.join("");
      } catch (err) { result.innerHTML = `<p class="notice">${esc(err.message)}</p>`; }
      e.target.disabled = false;
    });
    // the full copy, now: its progress shown while it runs
    m.querySelector("[data-backup-now]")?.addEventListener("click", async (e) => {
      const box = $("#backup-status", m);
      try { box.innerHTML = backupLine(await post(`/api/manage/remote/${encodeURIComponent(sid)}/backup`, {})); }
      catch (err) { showError(esc(err.message), 4000); return; }
      e.target.disabled = true;
      const poll = setInterval(async () => {
        if (!document.body.contains(box)) { clearInterval(poll); return; }
        const st = await api(`/api/manage/remote/${encodeURIComponent(sid)}/backup`).catch(() => null);
        if (!st) return;
        box.innerHTML = backupLine(st);
        if (!st.running) { clearInterval(poll); e.target.disabled = false; }
      }, 2000);
    });
    m.querySelector("[data-forget-key]")?.addEventListener("click", async () => {
      if (!(await confirmBox("Forget its identity?", "Only if your host moved your server to another machine (they'd tell you). Solstone then learns the new one now.", "Forget and reconnect"))) return;
      try { const r = await post(`/api/manage/remote/${encodeURIComponent(sid)}/forget-key`, {}); showToast(r.ok ? "Learned its new identity" : esc(r.error || "Couldn't connect"), 4000); closeModal(); openServerSetup(sid, then); }
      catch (err) { showError(esc(err.message), 4000); }
    });
    m.querySelector("[data-remove]")?.addEventListener("click", async () => {
      if (!(await confirmBox(`Stop looking after ${esc(title)}?`, "Solstone forgets how to reach it and deletes its copy of the files. Its history in Solstone (activity, stats, leaderboards) stays. Nothing on the server itself changes.", "Stop looking after it"))) return;
      try { await api(`/api/manage/remote/${encodeURIComponent(sid)}`, { method: "DELETE" }); closeModal(); showToast("Done", 2500); await loadServers(); if (then) await then(); }
      catch (err) { showError(esc(err.message), 4000); }
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(form);
      if (remote && !sid && !tested?.files?.ok && !(await confirmBox("Add it without a working connection?", "The test didn't find the server yet. You can add it now and fix the details later; Solstone keeps trying.", "Add it anyway"))) return;
      try {
        let id = sid;
        if (remote) {                                       // where its files are (and its panel), first: a new one gets its id here
          const r = await post(sid ? `/api/manage/remote/${encodeURIComponent(sid)}` : "/api/manage/remote", remoteBody(form), "PUT");
          id = r.id;
        }
        const body = { display_name: remote && !sid ? "" : f.get("display_name"), rcon_host: f.get("rcon_host"),
          rcon_port: f.get("rcon_port") ? Number(f.get("rcon_port")) : "", private: f.get("private") ? true : "" };
        if (sid) body.hidden = f.get("hidden") ? true : "";
        if (f.get("rcon_password")) body.rcon_password = f.get("rcon_password");
        await post(`/api/servers/${encodeURIComponent(id)}/settings`, body, "PUT");
        closeModal(); showToast(sid ? "Saved" : `${esc(f.get("display_name"))} is added. Its files arrive in a few seconds.`, 4000);
        await loadServers();
        if (then) await then(); else route();
      } catch (err) { showError(esc(err.message), 5000); }
    });
  });
}

// Manage → Server setup → Connections: Crafty, and the hosts' panels (Pterodactyl, Pelican).
async function manageConnections() {
  const box = $("#conn-manage .conn-list");
  if (!box) return;
  const list = await api("/api/manage/connections").catch(() => null);
  if (!list) { box.innerHTML = `<p class="notice">Couldn't load the connections just now.</p>`; return; }
  const chip = (cls, text, title = "") => `<span class="srv-chip ${cls}" ${title ? `title="${esc(title)}"` : ""}>${text}</span>`;
  box.innerHTML = (list.length ? list.map((x) => `<div class="panel srv-row" data-cid="${esc(x.id)}">
      <div class="srv-main"><b>${{ crafty: "🧰", serverprism: "🔷" }[x.type] || "🛰️"} ${esc(x.name)}</b> <span class="muted small">${esc(x.type_name)} · ${esc(x.url)}</span>
        <div class="srv-chips">${x.error || x.unreachable ? chip("warn", "Not answering", x.error || "") : chip("on", "Answering")}
          ${chip("", x.servers.length ? `${x.servers.length} server${x.servers.length === 1 ? "" : "s"}` : "No servers yet", x.servers.join(", "))}
          ${x.from_env ? chip("new", "From the container's settings", "Brought in from CRAFTY_URL and CRAFTY_TOKEN once. It's set here now: you can remove those from the container") : ""}</div></div>
      <div class="btn-row"><button class="btn sm" type="button" data-edit-conn>Edit</button></div></div>`).join("")
    : `<p class="muted">None yet. Crafty, if you use it, goes here; so does a game host's panel.</p>`)
    + `<div class="btn-row"><button class="btn" type="button" data-add-conn>＋ Add a connection</button>
      <span class="muted small">Crafty 4 on this machine, a game host's Pterodactyl or Pelican panel, or ServerPrism.</span></div>`;
  box.querySelector("[data-add-conn]").addEventListener("click", () => openConnection(null));
  box.querySelectorAll("[data-cid]").forEach((row) => row.querySelector("[data-edit-conn]").addEventListener("click", () => openConnection(list.find((x) => x.id === row.dataset.cid))));
}

function openConnection(cur) {
  let kind = cur?.type || "crafty";
  const html = () => `<h2>${cur ? `${esc(cur.name)}` : "Add a connection"}</h2>
    <form id="conn-form" class="remote-form" autocomplete="off">
      ${cur ? "" : `<div class="seg" role="group" aria-label="What kind">${[["crafty", "🧰 Crafty 4"], ["panel", "🛰️ Pterodactyl or Pelican"], ["serverprism", "🔷 ServerPrism"]].map(([v, l]) => `<button type="button" data-kind="${v}" aria-pressed="${kind === v}">${l}</button>`).join("")}</div>`}
      ${kind === "serverprism" ? `<p class="muted small">ServerPrism's own API. At <b>serverprism.com → Account → API Credentials</b>, create a token with <b>servers:read</b> and <b>servers:control</b> (and <b>backups:create</b> for Back up), and copy it: it's only shown once. One connection covers every server on your account. It gives Solstone whether each is running, CPU and memory, start, stop and restart, and backups. RCON still does the game (its commands send back the game's answer).</p>`
        : kind === "crafty" ? `<p class="muted small">Crafty Controller on this machine (or one Solstone can reach). Solstone lists its servers and reads their files from the servers folder it can see. In Crafty: click your name → <b>API Keys</b> → add one with access to the servers, and copy the token.</p>`
        : `<p class="muted small">A game host's panel (most run Pterodactyl or Pelican; it says so at the bottom of the panel's pages). In the panel: <b>Account → API Credentials → Create</b>, and copy the key. One connection covers every server on that account; add each server under <b>Your servers</b> (its files come over SFTP).</p>`}
      <div class="remote-grid">
        <label class="wide">Name<input class="input" name="name" maxlength="40" value="${esc(cur?.name || (kind === "crafty" ? "Crafty" : "Host's panel"))}"></label>
        ${kind === "serverprism" ? "" : `<label class="wide">Address<input class="input" name="url" required value="${esc(cur?.url || "")}" placeholder="${kind === "crafty" ? "https://192.168.1.10:8443" : "https://panel.examplehost.com"}" autocapitalize="off" spellcheck="false"></label>`}
        ${kind === "crafty" ? `<label class="wide">API token <small class="muted">${cur?.token_set ? "Saved. Type a new one to replace it." : ""}</small><input class="input" type="password" name="token" autocomplete="off"></label>`
          : `<label class="wide">API ${kind === "serverprism" ? "token" : "key"} <small class="muted">${cur?.key_set ? "Saved. Type a new one to replace it." : ""}</small><input class="input" type="password" name="key" autocomplete="off" placeholder="${kind === "serverprism" ? "" : "ptlc_…"}"></label>`}
        ${kind === "serverprism" ? "" : `<label class="check wide"><input type="checkbox" name="verify_ssl" ${(cur ? cur.verify_ssl : kind === "panel") ? "checked" : ""}> Check its certificate <small class="muted">${kind === "crafty" ? "leave off for Crafty: it makes its own" : "leave on for a host's panel"}</small></label>`}
      </div>
      <div class="btn-row"><button class="btn" type="button" data-test-conn>🔌 Test it</button></div>
      <div class="remote-result" id="conn-result"></div>
      <div class="actions">${cur ? `<button type="button" class="btn danger" data-remove-conn>Remove</button>` : ""}<span class="spacer"></span>
        <button type="button" class="btn" data-close-modal>Cancel</button><button class="btn primary" type="submit">${cur ? "Save" : "Add it"}</button></div>
    </form>`;
  const body = (form) => {
    const f = new FormData(form), out = { type: kind, verify_ssl: !!f.get("verify_ssl") };
    for (const k of ["name", "url", "token", "key"]) if (f.get(k) !== null) out[k] = (f.get(k) || "").trim();
    if (cur) out.id = cur.id;
    return out;
  };
  const show = () => openModal(html(), (m) => {
    const form = $("#conn-form", m), result = $("#conn-result", m);
    m.querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => { kind = b.dataset.kind; show(); }));
    m.querySelector("[data-test-conn]").addEventListener("click", async (e) => {
      e.target.disabled = true; result.innerHTML = `<p class="muted"><span class="spin" aria-hidden="true"></span> Asking…</p>`;
      try {
        const r = await post("/api/manage/connections/test", body(form));
        result.innerHTML = r.ok ? `<p class="ok">✓ It answered${r.servers.length ? `: ${r.servers.length} server${r.servers.length === 1 ? "" : "s"}` : ", but has no servers yet"}.</p>${r.servers.length ? `<p class="muted small">${r.servers.map((x) => esc(x.name)).join(" · ")}</p>` : ""}`
          : `<p class="notice">${esc(r.error)}</p>`;
      } catch (err) { result.innerHTML = `<p class="notice">${esc(err.message)}</p>`; }
      e.target.disabled = false;
    });
    m.querySelector("[data-remove-conn]")?.addEventListener("click", async () => {
      const what = cur.type === "crafty" ? "Its servers leave the list (their history in Solstone stays, and they come back if you add it again)." : "Servers on it keep working over SFTP, just without start, stop, CPU and memory.";
      if (!(await confirmBox(`Remove ${esc(cur.name)}?`, what, "Remove it"))) return;
      try { await api(`/api/manage/connections/${encodeURIComponent(cur.id)}`, { method: "DELETE" }); closeModal(); showToast("Removed", 2500); await loadServers(); manageConnections(); manageServers(); }
      catch (err) { showError(esc(err.message), 4000); }
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await post(cur ? `/api/manage/connections/${encodeURIComponent(cur.id)}` : "/api/manage/connections", body(form), "PUT");
        closeModal(); showToast(cur ? "Saved" : "Added", 2500); await loadServers(); manageConnections(); manageServers();
      } catch (err) { showError(esc(err.message), 5000); }
    });
  });
  show();
}
