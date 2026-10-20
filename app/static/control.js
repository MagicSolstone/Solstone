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
  change_password: "Changed their password", login_page_settings: "Changed the sign-in page", login_failed: "Failed sign-in", notification_settings: "Changed notifications",
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
    catch (err) { showToast(esc(err.message), 6000); }
  };

  // ---- power + quick + broadcast
  $$("[data-power]").forEach((b) => b.addEventListener("click", async () => {
    const a = b.dataset.power;
    const words = { start_server: ["Start the server?", "Start"], restart_server: ["Restart the server?", "Restart"],
      stop_server: ["Stop the server?", "Stop"], backup_server: ["Back up the server now?", "Back up"] }[a];
    const online = info.online.length ? `${info.online.length} player${info.online.length === 1 ? " is" : "s are"} online and will be disconnected.` : "Nobody is online.";
    if (a !== "backup_server" && a !== "start_server" && !(await confirmBox(words[0], esc(online), words[1], a === "stop_server"))) return;
    try { await post(`${base}/control/power/${a}`); showToast(`${words[1]} requested. Crafty is on it.`, 4000); setTimeout(() => route(), 4000); }
    catch (err) { showToast(esc(err.message), 6000); }
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
  try { history = JSON.parse(localStorage.getItem("solstone-cmd-history") || localStorage.getItem("lodestone-cmd-history") || "[]"); } catch {}
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
  function itemOptions() {
    const lang = state.lang[sid] || {};
    return Object.keys(lang).filter((k) => /^(item|block)\.minecraft\.[a-z0-9_]+$/.test(k))
      .map((k) => `<option value="minecraft:${k.split(".")[2]}">${esc(lang[k])}</option>`).join("");
  }
  function renderPlayers() {
    const el = $("#ctl-players");
    if (!el) return;
    $("#online-count").textContent = info.online.length ? `${info.online.length} online` : "";
    if (!info.can_rcon) { el.innerHTML = `<div class="empty"><p>Player actions need RCON on this server.</p></div>`; return; }
    if (!info.online.length) { el.innerHTML = `<div class="empty"><p>Nobody is online right now. Player actions appear here when someone joins.</p></div>`; return; }
    const others = (n) => info.online.filter((o) => o !== n);
    el.innerHTML = `<div class="ctl-players">${info.online.map((n) => `
      <div class="ctl-player panel" data-player="${esc(n)}">
        <div class="cp-head"><img src="https://mc-heads.net/avatar/${encodeURIComponent(n)}/64" alt="" onerror="this.style.visibility='hidden'"><b>${esc(n)}</b></div>
        <div class="btn-row">
          <button class="btn sm" data-pa="heal">Heal &amp; feed</button>
          <button class="btn sm" data-pa="tp_spawn">Send to spawn</button>
          <button class="btn sm" data-pa="tp_bed">Send to bed</button>
          <select class="input sm" data-pa="gamemode" aria-label="Game mode for ${esc(n)}"><option value="">Game mode…</option>${["survival", "creative", "adventure", "spectator"].map((m) => `<option value="${m}">${humanize(m)}</option>`).join("")}</select>
        </div>
        ${others(n).length ? `<div class="btn-row"><select class="input sm" data-target aria-label="Other player">${others(n).map((o) => `<option>${esc(o)}</option>`).join("")}</select>
          <button class="btn sm" data-pa="tp_to_player">Send ${esc(n)} to them</button><button class="btn sm" data-pa="bring">Bring them here</button></div>` : ""}
        <form class="btn-row" data-form="message"><input class="input sm grow" name="message" placeholder="Private message" maxlength="256" required><button class="btn sm">Send</button></form>
        <form class="btn-row" data-form="give"><input class="input sm grow" name="item" list="item-list" placeholder="Item, like diamond" required><input class="input sm num-in" name="count" type="number" min="1" max="6400" value="1" aria-label="How many"><button class="btn sm">Give</button></form>
        <div class="btn-row"><button class="btn sm danger" data-pa="kick">Kick</button></div>
      </div>`).join("")}</div><datalist id="item-list">${itemOptions()}</datalist>`;
  }
  $("#ctl-players")?.addEventListener("click", async (e) => {
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
    if (form.dataset.form === "give") await act(`player/${encodeURIComponent(p)}/give`, { item: f.get("item"), count: Number(f.get("count")) }, "Given");
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
      <form class="btn-row" id="list-form" style="margin-top:12px"><input class="input sm" name="name" placeholder="Minecraft username" pattern="[A-Za-z0-9_]{1,16}" required>
        <button class="btn sm" name="do" value="whitelist_add">Add to whitelist</button><button class="btn sm" name="do" value="op">Make operator</button></form>`;
  }
  $("#ctl-lists")?.addEventListener("click", async (e) => {
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
    const b = info.bedtime;
    const players = [...new Set([...info.known_players, ...b.exempt])].sort((x, y) => x.localeCompare(y));
    $("#bed-status").textContent = b.enabled ? `On · ${fmtClock(b.start)} to ${fmtClock(b.end)}` : "Off";
    el.innerHTML = `<form id="bed-form" class="bed-form">
      <label class="check"><input type="checkbox" name="enabled" ${b.enabled ? "checked" : ""}> Turn on bedtime for this server</label>
      <p class="muted small">Players get in-game warnings, then the world is saved and everyone is disconnected. Anyone who joins before wake-up time is disconnected again.${info.can_rcon ? "" : " <b>Needs RCON.</b>"}</p>
      <div class="row2"><label>Bedtime<input class="input" type="time" name="start" value="${esc(b.start)}" required></label>
        <label>Wake-up<input class="input" type="time" name="end" value="${esc(b.end)}" required></label></div>
      <fieldset class="checks"><legend>On these nights</legend><div class="day-checks">${DAY_NAMES.map((d, i) => `<label class="check"><input type="checkbox" name="day" value="${i}" ${b.days.includes(i) ? "checked" : ""}> ${d}</label>`).join("")}</div></fieldset>
      <label>Warn players this many minutes before <small>Separate with commas</small><input class="input" name="warn" value="${esc(b.warn_minutes.join(", "))}"></label>
      <label>Disconnect message <small>Optional</small><input class="input" name="message" maxlength="120" value="${esc(b.message)}" placeholder="Bedtime! The server opens again at ${esc(fmtClock(b.end))}."></label>
      ${players.length ? `<fieldset class="checks"><legend>Can stay on after bedtime</legend><div class="day-checks">${players.map((n) => `<label class="check"><input type="checkbox" name="exempt" value="${esc(n)}" ${b.exempt.includes(n) ? "checked" : ""}> ${esc(n)}</label>`).join("")}</div></fieldset>` : ""}
      <div class="actions"><button class="btn primary" type="submit">Save bedtime</button></div></form>`;
    $("#bed-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const bedtime = { enabled: !!f.get("enabled"), start: f.get("start"), end: f.get("end"), days: f.getAll("day").map(Number),
        warn_minutes: String(f.get("warn")).split(/[,\s]+/).filter(Boolean).map(Number).filter((n) => n > 0), exempt: f.getAll("exempt"), message: f.get("message") };
      try { const r = await post(`${base}/settings`, { bedtime }, "PUT"); info.bedtime = r.bedtime; renderBedtime(); showToast("Bedtime saved", 2500); refreshInfo(); }
      catch (err) { showToast(esc(err.message), 5000); }
    });
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

// ================================================================ Users & activity
async function viewAdmin() {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = "Users & activity · Solstone";
  $("#rail-servers").innerHTML = railHtml(null);
  const [users, audit, lp] = await Promise.all([api("/api/users"), api("/api/audit?limit=200"), api("/api/settings/status")]);
  const fmtWhen = (ts) => ts ? fmtAgo(ts) : "never";
  setView(`<h1 style="margin-bottom:20px">Users &amp; activity</h1>
    <section class="section"><div class="section-head"><h2>Users</h2><span class="muted">Viewers can see everything but can't change anything. Admins can also control servers.</span></div>
      <div class="table-wrap"><table class="data users-table"><thead><tr><th>Username</th><th>Role</th><th>Last signed in</th><th></th></tr></thead><tbody>
      ${users.map((u) => `<tr data-uid="${u.id}"><td><b>${esc(u.username)}</b>${u.id === me.user.id ? ' <span class="muted">(you)</span>' : ""}</td>
        <td><select class="input sm" data-role ${u.id === me.user.id ? "disabled" : ""} aria-label="Role for ${esc(u.username)}"><option value="viewer" ${u.role === "viewer" ? "selected" : ""}>Viewer</option><option value="admin" ${u.role === "admin" ? "selected" : ""}>Admin</option></select></td>
        <td>${esc(fmtWhen(u.last_login))}</td>
        <td class="row-actions"><button class="btn sm" data-reset>Set password</button>${u.id === me.user.id ? "" : `<button class="btn sm danger" data-del>Remove</button>`}</td></tr>`).join("")}
      </tbody></table></div>
      <form class="panel add-user" id="add-user" autocomplete="off"><h3>Add a user</h3>
        <div class="add-grid"><label>Username<input class="input" name="username" required pattern="[A-Za-z0-9_.\\-]{2,32}" autocapitalize="off"></label>
        <label>Password<input class="input" name="password" type="password" minlength="8" autocomplete="new-password" placeholder="8 or more characters" required></label>
        <label>Role<select class="input" name="role"><option value="viewer">Viewer (read-only)</option><option value="admin">Admin</option></select></label>
        <button class="btn primary" type="submit">Add user</button></div></form>
    </section>
    <section class="section"><div class="section-head"><h2>Public status page</h2><span class="muted">A live, read-only big-screen view anyone can open without signing in</span></div>
      <div class="panel rules-ctl" id="status-page-settings" style="max-width:720px">
        <label class="switch-row"><span><b>Turn on the status page</b><br><small class="muted">At <a href="/status" target="_blank" rel="noopener">${esc(location.origin)}/status</a>, linked from the sign-in page. Shows who's playing, their health, level and the in-game day. Never shows chat.</small></span><input type="checkbox" role="switch" data-sp="enabled" ${lp.enabled ? "checked" : ""}></label>
        <label class="switch-row"><span>Show coordinates and the position map</span><input type="checkbox" role="switch" data-sp="show_positions" ${lp.show_positions ? "checked" : ""}></label>
        <label class="switch-row"><span>Show held items and armour</span><input type="checkbox" role="switch" data-sp="show_items" ${lp.show_items ? "checked" : ""}></label>
        <label class="switch-row"><span>Show recent joins, deaths and advancements</span><input type="checkbox" role="switch" data-sp="show_activity" ${lp.show_activity ? "checked" : ""}></label>
        <label class="switch-row"><span>Embed the web map (BlueMap, squaremap) <br><small class="muted">Only works if visitors can reach the map's address too. A plain http:// map won't load on an https:// page.</small></span><input type="checkbox" role="switch" data-sp="show_web_map" ${lp.show_web_map ? "checked" : ""}></label>
        <p class="muted small" style="margin-top:8px">Anyone with the address can see this page. Hidden servers are never shown.</p>
      </div></section>
    <section class="section"><div class="section-head"><h2>Admin activity</h2><span class="muted">Commands, changes and sign-in failures across all servers</span></div>
      <div class="panel">${auditHtml(audit, true)}</div></section>`);

  $("#status-page-settings").addEventListener("change", async () => {
    const body = {};
    $$("[data-sp]").forEach((i) => { body[i.dataset.sp] = i.checked; });
    try { await post("/api/settings/status", body, "PUT"); showToast(body.enabled ? 'Status page updated. <a href="/status" target="_blank" rel="noopener">Open it</a>' : "Status page turned off", 3500); }
    catch (err) { showToast(esc(err.message), 5000); }
  });
  $("#add-user").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try { await post("/api/users", { username: f.get("username"), password: f.get("password"), role: f.get("role") }); showToast(`Added ${esc(f.get("username"))}`, 2500); viewAdmin(); }
    catch (err) { showToast(esc(err.message), 5000); }
  });
  $$("[data-role]").forEach((sel) => sel.addEventListener("change", async () => {
    const uid = sel.closest("tr").dataset.uid;
    try { await post(`/api/users/${uid}`, { role: sel.value }, "PATCH"); showToast("Role changed", 2500); }
    catch (err) { showToast(esc(err.message), 5000); viewAdmin(); }
  }));
  $$("[data-reset]").forEach((b) => b.addEventListener("click", () => {
    const tr = b.closest("tr"), name = tr.querySelector("b").textContent;
    openModal(`<h2>Set a new password for ${esc(name)}</h2><form id="reset-form">
      <label>New password <small>8+ characters. They'll be signed out everywhere.</small><input class="input" type="password" name="password" minlength="8" autocomplete="new-password" required></label>
      <div class="actions"><button type="button" class="btn" onclick="closeModal()">Cancel</button><button class="btn primary" type="submit">Set password</button></div></form>`, (m) => {
      $("#reset-form", m).addEventListener("submit", async (e) => {
        e.preventDefault();
        try { await post(`/api/users/${tr.dataset.uid}`, { password: new FormData(e.target).get("password") }, "PATCH"); closeModal(); showToast("Password set", 2500); }
        catch (err) { showToast(esc(err.message), 5000); }
      });
    });
  }));
  $$("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    const tr = b.closest("tr"), name = tr.querySelector("b").textContent;
    if (!(await confirmBox(`Remove ${name}?`, "They'll be signed out and won't be able to sign in again.", "Remove"))) return;
    try { await api(`/api/users/${tr.dataset.uid}`, { method: "DELETE" }); showToast(`Removed ${esc(name)}`, 2500); viewAdmin(); }
    catch (err) { showToast(esc(err.message), 5000); }
  }));
}
