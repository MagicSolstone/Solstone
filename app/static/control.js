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
      <section class="panel"><h3>Message everyone</h3>
        <form id="bc-form" class="bc-form">
          <input class="input" name="message" maxlength="256" placeholder="Dinner in 10 minutes!" autocomplete="off" required>
          <button class="btn primary" type="submit">Send</button>
          <label class="check small"><input type="checkbox" name="on_screen"> Also show it big on everyone's screen</label>
        </form>
      </section>
    </div>
    ${info.can_rcon || info.can_crafty ? "" : `<div class="notice">Turn on RCON for this server (⚙ settings) to send commands.</div>`}
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
          <button class="btn sm" type="button" data-copy-name="${esc(b.player)}">Copy</button><button class="btn sm primary" type="button" data-allow="${esc(b.player)}">Let them in</button><button class="btn sm danger" type="button" data-deny="${esc(b.player)}">Deny</button>
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

// What Solstone keeps about a server that Manage → Servers can clear (db.clear_server, worldmap.clear_tiles).
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
// Manage → Users, Servers & live info, Activity log (one section each).
async function viewAdmin(section = "users") {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = `${{ users: "Users", servers: "Servers & live info", activity: "Activity log" }[section] || "Manage"} · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  const [users, lp, hiddenSrv, siteCfg, playerCfg, ptCfg] = await Promise.all([api("/api/users"), api("/api/settings/status"), api("/api/servers-hidden").catch(() => []), api("/api/posts").then((d) => d.site).catch(() => ({})), api("/api/settings/players").catch(() => ({})), section === "users" ? api("/api/settings/playtime").catch(() => null) : null]);
  const roleOpts = (cur) => ROLE_NAMES.map(([v, l]) => `<option value="${v}" ${cur === v ? "selected" : ""}>${l}</option>`).join("");
  const fmtWhen = (ts) => ts ? fmtAgo(ts) : "never";
  const srvName = (id) => state.servers.find((x) => x.id === id)?.name || id;
  const usersHtml = `<section class="section"><div class="section-head"><h2>Users</h2><span class="muted">Players see the servers, who's on, the leaderboards and their own page. Trusted can see everything (chat, where everyone is, inventories) but can't change anything. Admins can also control servers.</span></div>
      <div class="panel rules-ctl" id="signup-ctl" style="max-width:720px;margin-bottom:12px">
        <label class="switch-row"><span><b>Let players make their own account</b><br><small class="muted">From the sign-in page: they type their Minecraft name while they're playing on a public server, get a code in the game chat, and choose a login. They start as Players. Your whitelist decides who can do this.</small></span><input type="checkbox" role="switch" id="signup-on" ${siteCfg.signup ? "checked" : ""}></label>
        <label class="switch-row"><span><b>Players can see the map</b><br><small class="muted">Gives Players the World tab: the map of the world with where everyone is (and the web map, if the server has one). The world's seed stays hidden.</small></span><input type="checkbox" role="switch" id="players-map-on" ${playerCfg.see_map ? "checked" : ""}></label></div>
      <div class="table-wrap"><table class="data users-table"><thead><tr><th>Username</th><th>Level</th><th>Minecraft player</th><th>Servers</th><th>Last signed in</th><th></th></tr></thead><tbody>
      ${users.map((u) => `<tr data-uid="${u.id}"><td><b>${esc(u.username)}</b>${u.shown && u.shown !== u.username ? ` <span class="muted">shown as ${esc(u.shown)}</span>` : ""}${u.real_name ? `<br><small class="muted" title="Their real name: only admins see it">👤 ${esc(u.real_name)}</small>` : ""}${u.id === me.user.id ? ' <span class="muted">(you)</span>' : ""}</td>
        <td><select class="input sm" data-role ${u.id === me.user.id ? "disabled" : ""} aria-label="Level for ${esc(u.username)}">${roleOpts(u.role)}</select></td>
        <td><button class="btn sm" type="button" data-link title="Link this account to the people they play as (Java and Bedrock)">${(u.players || []).length ? esc(u.players.map((p) => p.name).join(", ")) : "Link…"}</button>${ptCfg && (u.players || []).length ? `<br><a class="small muted" href="#/manage/playtime" title="Bedtime and screen time: Manage → Play time">⏰ ${esc(ptSummary(ptCfg.rows.find((r) => r.key === `u${u.id}`)))}</a>` : ""}</td>
        <td>${u.role === "admin" ? '<span class="muted">All</span>' : `<button class="btn sm" type="button" data-srv title="Which servers they see">${u.servers ? esc(u.servers.length === 1 ? srvName(u.servers[0]) : `${u.servers.length} servers`) : "All"}</button>`}</td>
        <td>${esc(fmtWhen(u.last_login))}</td>
        <td class="row-actions"><button class="btn sm" data-reset>Set password</button>${u.id === me.user.id ? "" : `<button class="btn sm danger" data-del>Remove</button>`}</td></tr>`).join("")}
      </tbody></table></div>
      <form class="panel add-user" id="add-user" autocomplete="off"><h3>Add a user</h3>
        <div class="add-grid"><label>Username<input class="input" name="username" required pattern="[A-Za-z0-9_.\\-]{2,32}" autocapitalize="off"></label>
        <label>Password<input class="input" name="password" type="password" minlength="8" autocomplete="new-password" placeholder="8 or more characters" required></label>
        <label>Level<select class="input" name="role">${roleOpts("trusted")}</select></label>
        <button class="btn primary" type="submit">Add user</button></div></form>
    </section>`;
  const serversHtml = `${hiddenSrv.length ? `<section class="section" id="hidden-servers"><div class="section-head"><h2>Hidden servers</h2><span class="muted">Hidden from Solstone and the home page. Nothing about the server itself changes.</span></div>
      <div class="panel hidden-list">${hiddenSrv.map((x) => `<div class="hidden-row" data-hsid="${esc(x.id)}"><b>${esc(x.name)}</b><span class="muted small">${esc(x.game || "")}</span><button class="btn sm" type="button" data-unhide>Show it again</button></div>`).join("")}</div></section>` : ""}
    <section class="section"><div class="section-head"><h2>Live on the home page</h2><span class="muted">Who's playing right now, for anyone visiting, without signing in</span></div>
      <div class="panel rules-ctl" id="status-page-settings" style="max-width:720px">
        <label class="switch-row"><span><b>Show the servers live on the home page</b><br><small class="muted">Under Help on <a href="/#live" target="_blank" rel="noopener">the home page</a>: who's playing, their health and level, the in-game day, leaderboards and the recap. Never shows chat, and never how long anyone played.</small></span><input type="checkbox" role="switch" data-sp="enabled" ${lp.enabled ? "checked" : ""}></label>
        <label class="switch-row"><span>Show coordinates and the position map<br><small class="muted">Only to people signed in (Trusted and Admins, and Players when “Players can see the map” is on in Users). Visitors who aren't signed in never see where anyone is, or the map.</small></span><input type="checkbox" role="switch" data-sp="show_positions" ${lp.show_positions ? "checked" : ""}></label>
        <label class="switch-row"><span>Show held items and armour</span><input type="checkbox" role="switch" data-sp="show_items" ${lp.show_items ? "checked" : ""}></label>
        <label class="switch-row"><span>Show recent joins, deaths and advancements</span><input type="checkbox" role="switch" data-sp="show_activity" ${lp.show_activity ? "checked" : ""}></label>
        <p class="muted small" style="margin-top:8px">Anyone visiting the home page sees this. Hidden and private servers are never shown.</p>
      </div></section>
    <section class="section"><div class="section-head"><h2>Recap history</h2></div>
      <div class="panel" style="max-width:720px"><p class="muted small">Every day is summarised and kept for good, so “on this day” can look back years. When Solstone first starts it also reads each server's old logs (the <code>logs/*.log.gz</code> files Minecraft keeps) to fill in the days before it was installed. If you've copied older logs in, read them again here.</p>
        <button class="btn" id="ann-backfill" type="button" style="margin-top:8px">Read old logs again</button></div></section>
    <section class="section"><div class="section-head"><h2>Each server</h2></div>
      <div class="panel"><p>A server's own settings (its name, Private, the web map, bedtime) are on its page: open it from <b>Servers</b> and press ⚙.</p></div></section>
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
  setView({ users: usersHtml, servers: serversHtml, activity: activityHtml }[section] || usersHtml);
  if ($("#audit-browse")) mountAuditBrowser($("#audit-browse"));

  $("#status-page-settings")?.addEventListener("change", async () => {
    const body = {};
    $$("[data-sp]").forEach((i) => { body[i.dataset.sp] = i.checked; });
    try { await post("/api/settings/status", body, "PUT"); showToast(body.enabled ? 'Saved. <a href="/#live" target="_blank" rel="noopener">See it on the home page</a>' : "Live info is off the home page", 3500); }
    catch (err) { showError(esc(err.message), 5000); }
  });
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
  $("#hidden-servers")?.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-unhide]");
    if (!b) return;
    const row = b.closest("[data-hsid]");
    try {
      await post(`/api/servers/${encodeURIComponent(row.dataset.hsid)}/settings`, { hidden: false }, "PUT");
      showToast(`${esc(row.querySelector("b").textContent)} is back`, 2500);
      await loadServers(); viewAdmin(section);
    } catch (err) { showError(esc(err.message), 5000); }
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

// Say no to someone who asked to join (Manage → Whitelist and Control): their page tells them it wasn't accepted.
async function denyRequest(player) {
  if (!await confirmBox(`Deny ${player}'s request?`, "It comes off Asked to join, and their page says it wasn't accepted. They aren't added to any whitelist, and can ask again later.", "Deny")) return false;
  try { await post("/api/whitelist/deny", { player }); showToast(`Denied ${esc(player)}'s request`, 2500); return true; }
  catch (err) { showError(esc(err.message), 6000); return false; }
}

// ================================================================ Manage → Whitelist
// Everyone who asked to join (each server they asked for, in or not), everyone the whitelist turned away, and each
// server's list, across all servers. Letting someone in runs the game's own whitelist command on that server.
async function viewWhitelist() {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = `Whitelist · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  const d = await api("/api/whitelist");
  const ago = (ts) => esc(fmtAgo(ts));
  const pill = (sid, name, inOk, player) => inOk
    ? `<span class="wl-in">✅ ${esc(name)}</span>`
    : `<button class="btn sm primary" type="button" data-let="${esc(player)}" data-sid="${esc(sid)}">Let in on ${esc(name)}</button>`;
  const reqHtml = d.requests.length ? d.requests.map((r) => {
    const waiting = r.servers.filter((x) => !x.in);
    return `<li class="wl-req"><div class="wl-who"><code class="ta-name">${esc(r.player)}</code>${r.bedrock ? ' <span class="chip">Bedrock</span>' : ""}
        ${r.name ? `<span>${esc(r.name)}</span>` : ""}<span class="muted small">${ago(r.ts)}</span>
        <button class="btn sm" type="button" data-copy-name="${esc(r.player)}">Copy</button></div>
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
    <section class="section"><div class="section-head"><h2>Asked to join</h2><span class="muted">${d.requests.length || "Nobody"} waiting</span></div>
      ${reqHtml ? `<ul class="wl-list">${reqHtml}</ul>` : `<div class="panel"><p class="muted">No requests waiting. With <i>Ask to join</i> on (Website → Site details), they show here, and you get a notification.</p></div>`}</section>
    ${blockedHtml ? `<section class="section"><div class="section-head"><h2>Tried to join</h2><span class="muted">Turned away in the last two weeks</span></div><ul class="wl-list">${blockedHtml}</ul></section>` : ""}
    <section class="section"><div class="section-head"><h2>Each server's list</h2></div>
      <form class="panel btn-row wl-add" id="wl-add"><input class="input sm" name="name" placeholder="Name (.Name for Bedrock)" pattern="\\.?[A-Za-z0-9_]{1,16}" required>
        ${d.servers.map((s, i) => `<label class="check"><input type="checkbox" name="sid" value="${esc(s.id)}" ${i === 0 ? "checked" : ""}> ${esc(s.name)}</label>`).join("")}
        <button class="btn sm primary" type="submit">Add</button></form>
      <div class="wl-grid">${d.servers.map((s) => `<div class="panel"><h3>${esc(s.name)}${s.private ? ' <span class="chip">Private</span>' : ""}</h3>
        <p class="muted small">The whitelist is <b>${s.enabled ? "on" : "off"}</b>${s.enabled ? "" : ": anyone with the address can join"}.</p>
        <div class="chips">${s.whitelist.length ? s.whitelist.map((n) => `<span class="chip">${esc(n)}<button class="chip-x" type="button" data-unlist="${esc(n)}" data-sid="${esc(s.id)}" aria-label="Remove ${esc(n)}">×</button></span>`).join("") : '<span class="muted">Nobody yet</span>'}</div></div>`).join("")}</div></section>`);
  const letIn = async (name, sid) => {
    try { await post(`/api/servers/${encodeURIComponent(sid)}/control/player/${encodeURIComponent(name)}/whitelist_add`, {}); return true; }
    catch (err) { showError(`${esc(d.servers.find((x) => x.id === sid)?.name || sid)}: ${esc(err.message)}`, 7000); return false; }
  };
  view().addEventListener("click", async (e) => {
    const copy = e.target.closest("[data-copy-name]"), one = e.target.closest("[data-let]"), all = e.target.closest("[data-let-all]"), un = e.target.closest("[data-unlist]");
    const deny = e.target.closest("[data-deny]");
    if (deny) { if (await denyRequest(deny.dataset.deny)) viewWhitelist(); return; }
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
}
