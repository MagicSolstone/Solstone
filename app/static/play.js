/* Solstone — Chat (what's said in the game, and talking back from here) and Challenges
   (timed family contests with prizes). Both are admin pages on a server. */

// ---------------------------------------------------------------- chat
async function viewChat(sid) {
  if (!isAdmin()) { location.replace(`#/s/${encodeURIComponent(sid)}`); return; }
  const s = await serverFrame(sid, "chat");
  const base = `/api/servers/${encodeURIComponent(sid)}`;
  setView(serverHeader(s, "chat") + `
    <section class="chat-wrap panel">
      <div class="chat-log" id="chat-log" role="log" aria-live="polite" aria-label="Chat"><p class="muted">Loading…</p></div>
      <form class="chat-send" id="chat-form" autocomplete="off">
        <select class="input sm" id="chat-to" aria-label="Send to"><option value="">Everyone</option></select>
        <input class="input grow" id="chat-text" maxlength="256" placeholder="Say something in the game…" aria-label="Message" enterkeyhint="send">
        <button class="btn primary" type="submit">Send</button>
      </form>
      <p class="muted small chat-note" id="chat-note"></p>
    </section>`);
  wireHeader(s);
  const logEl = $("#chat-log"), toSel = $("#chat-to");
  let last = 0, lastDay = "", first = true;
  const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const dayOf = (ts) => new Date(ts * 1000).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
  const row = (e) => {
    const t = `<time datetime="${new Date(e.ts * 1000).toISOString()}">${clock(e.ts)}</time>`;
    if (e.type === "chat") return `<div class="cm">${t}${faceHtml({ name: e.player }, 22)}<b>${esc(e.player)}</b><span>${esc(e.message)}</span></div>`;
    if (e.type === "webchat") return `<div class="cm web">${t}<span class="cm-from">🌐</span><b>${esc(e.player)}</b><span>${esc(e.message)}</span></div>`;
    if (e.type === "webdm") return `<div class="cm web dm">${t}<span class="cm-from">✉</span><b>${esc(e.player)} → ${esc(e.to)}</b><span>${esc(e.message)}</span></div>`;
    const icon = { join: "→", leave: "←", death: "☠", advancement: "★", challenge: "🏆", race: "🏁", fish: "🎣", bigfish: "🐟", game: "🎲" }[e.type] || "•";
    return `<div class="cm sys">${t}<span class="cm-from">${icon}</span><span>${esc(e.message)}</span></div>`;
  };
  const render = (items) => {
    const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 60;
    let html = "";
    for (const e of items) {
      const d = dayOf(e.ts);
      if (d !== lastDay) { html += `<div class="cm-day">${esc(d)}</div>`; lastDay = d; }
      html += row(e);
      last = Math.max(last, e.id);
    }
    if (first) { logEl.innerHTML = html || `<p class="muted cm-empty">Nothing said yet. What people type in the game shows up here.</p>`; first = false; }
    else if (html) { logEl.querySelector(".cm-empty")?.remove(); logEl.insertAdjacentHTML("beforeend", html); }
    if (atBottom || items.length && items[items.length - 1].type.startsWith("web")) logEl.scrollTop = logEl.scrollHeight;
  };
  const people = (online) => {
    const cur = toSel.value;
    toSel.innerHTML = `<option value="">Everyone</option>${online.map((n) => `<option value="${esc(n)}">Just ${esc(n)}</option>`).join("")}`;
    toSel.value = online.includes(cur) ? cur : "";
    $("#chat-note").textContent = online.length ? `Online now: ${online.join(", ")}` : "Nobody is online, so messages won't reach anyone right now.";
  };
  const load = async () => {
    try {
      const d = await api(`${base}/chat?after=${last}`);
      render(d.items); people(d.online || []);
      if (!d.can_send) $("#chat-note").textContent = "Turn on RCON for this server to send messages.";
    } catch (e) { if (first) logEl.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
  };
  await load();
  logEl.scrollTop = logEl.scrollHeight;
  every(3000, load);
  $("#chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#chat-text"), text = input.value.trim();
    if (!text) return;
    input.disabled = true;
    try { await post(`${base}/chat`, { message: text, to: toSel.value }); input.value = ""; await load(); }
    catch (err) { showToast(esc(err.message), 4000); }
    input.disabled = false; input.focus();
  });
}

// ---------------------------------------------------------------- challenges
async function viewChallenges(sid) {
  if (!isAdmin()) { location.replace(`#/s/${encodeURIComponent(sid)}`); return; }
  const s = await serverFrame(sid, "challenges");
  const base = `/api/servers/${encodeURIComponent(sid)}/challenges`;
  let [d, fish] = await Promise.all([api(base), api(`/api/servers/${encodeURIComponent(sid)}/fishing`).catch(() => null)]);
  const fishOn = () => !!fish?.status?.version || !!fish?.tide;        // the fishing pack, or the Tide mod
  const draft = { kind: "fish", name: "", when: "now", at: "", minutes: 10, prize: null, second: null, say: true, lure: 0, fair: true, hot: false, hot_bonus: 2, hot_on: 60, hot_off: 30, hot_far: 40, g: { on: false, spot: null, r: 4 } };
  const ROD_KINDS = ["fish", "fish_points", "fish_heaviest"];
  // default time for "later": the next 8 PM, or the next hour if that's already past today
  const next8 = () => { const t = new Date(); t.setHours(20, 0, 0, 0); if (t < new Date()) { t.setTime(Date.now() + 3600e3); t.setMinutes(0, 0, 0); } return t; };
  const localInput = (t) => new Date(t.getTime() - t.getTimezoneOffset() * 60e3).toISOString().slice(0, 16);
  draft.at = localInput(next8());
  const kind = (k) => d.kinds.find((x) => x.key === k) || { label: k, emoji: "🏆", unit: "" };
  const prizeHtml = (p) => (p ? `${itemIcon({ id: p.item })}<span>${p.count} × ${esc(p.label || itemName({ id: p.item }))}</span>` : `<span class="muted">Choose…</span>`);
  const fmtWhen = (ts) => new Date(ts * 1000).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const left = (ts) => { const sec = Math.max(0, Math.round(ts - Date.now() / 1000)); return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`; };
  const scoresHtml = (c) => {
    const rows = Object.entries(c.scores || {}).sort((a, b) => b[1] - a[1]);
    if (!rows.length) return `<p class="muted small">No scores yet.</p>`;
    const lb = (v) => (c.tide ? fmtWeight(v / 10 * 453.59237) : `${v / 10} lb`);
    const show = (n, v) => (c.kind === "fish_heaviest" ? `${lb(v)}${c.best?.[n] ? ` · ${esc(c.best[n].name)}` : ""}` : c.kind === "fish_points" ? `${v} pts` : v);
    return `<ol class="ch-scores">${rows.map(([n, v], i) => `<li class="${(c.winners || []).includes(n) ? "win" : ""}"><span class="rank">${i + 1}</span>${faceHtml({ name: n }, 22)}<b>${esc(n)}</b><span class="val">${show(n, v)}</span></li>`).join("")}</ol>`;
  };
  const card = (c) => {
    const k = kind(c.kind);
    const status = c.state === "running" ? `<span class="ch-live">● Live · <span data-left="${c.ends_at}">${left(c.ends_at)}</span> left</span>`
      : c.state === "scheduled" ? `<span class="muted">${esc(fmtWhen(c.start))} · ${c.minutes} min</span>`
      : `<span class="muted">${esc({ done: "Finished", skipped: "Didn't run", cancelled: "Called off" }[c.state] || c.state)} · ${esc(fmtWhen(c.start))}</span>`;
    return `<div class="ch-card panel ch-${c.state}" data-cid="${esc(c.id)}">
      <div class="ch-head"><span class="ch-emoji">${k.emoji}</span><div><h3>${esc(c.name)}</h3>${status}</div>
        <div class="ch-acts">${c.state === "scheduled" || c.state === "running" ? `<button class="btn sm danger" type="button" data-cancel>${c.state === "running" ? "Stop" : "Cancel"}</button>` : `<button class="btn sm" type="button" data-again title="Set up the same challenge again">Run again</button><button class="icon-btn" type="button" data-cancel title="Remove from the list" aria-label="Remove">✕</button>`}</div></div>
      <div class="ch-prize">🏆 ${prizeHtml({ ...c.prize, label: c.prize.name })}${c.second ? ` <span class="muted">· 2nd:</span> ${prizeHtml({ ...c.second, label: c.second.name })}` : ""}</div>
      ${c.result ? `<p class="ch-result">${esc(c.result)}</p>` : ""}
      ${c.state === "running" || c.state === "done" ? scoresHtml(c) : ""}
    </div>`;
  };
  const formHtml = () => `<form class="panel ch-form" id="ch-form">
      <h3>New challenge</h3>
      <div class="ch-kinds" role="radiogroup" aria-label="What counts">${d.kinds.filter((k) => !k.retired).map((k) => {
        const off = k.pack && !fishOn();
        const what = k.key === "fish_points" ? "most points (needs the fishing pack or Tide)" : k.key === "fish_heaviest" ? "heaviest fish (needs the fishing pack or Tide)" : `most ${k.unit}`;
        return `<label class="ch-kind ${draft.kind === k.key ? "on" : ""} ${off ? "off" : ""}" ${off ? 'title="Add the Solstone Fishing pack to the world first (below)"' : ""}><input type="radio" name="kind" value="${k.key}" ${draft.kind === k.key ? "checked" : ""} ${off ? "disabled" : ""}><span>${k.emoji}</span><b>${esc(k.label)}</b><small>${esc(off ? what : what.replace(" (needs the fishing pack or Tide)", ""))}</small></label>`;
      }).join("")}</div>
      <div class="ch-grid">
        <label>Name <input class="input" name="name" maxlength="40" placeholder="${esc(kind(draft.kind).label)}" value="${esc(draft.name)}"></label>
        <label>How long <select class="input" name="minutes">${[5, 10, 15, 20, 30, 45, 60].map((m) => `<option value="${m}" ${draft.minutes === m ? "selected" : ""}>${m} minutes</option>`).join("")}</select></label>
        <div class="ch-when"><span class="lbl">When</span>
          <label class="check"><input type="radio" name="when" value="now" ${draft.when === "now" ? "checked" : ""}> Right now</label>
          <label class="check"><input type="radio" name="when" value="later" ${draft.when === "later" ? "checked" : ""}> At <input class="input sm" type="datetime-local" name="at" value="${esc(draft.at)}"></label></div>
        <div class="ch-prizes"><span class="lbl">Prize for the winner</span><button type="button" class="btn ch-pick" data-pick="prize">${prizeHtml(draft.prize)}</button>
          <span class="lbl">Second place <small class="muted">(optional)</small></span><span class="ch-second"><button type="button" class="btn ch-pick" data-pick="second">${prizeHtml(draft.second)}</button>${draft.second ? `<button type="button" class="icon-btn" data-clear-second aria-label="No second prize">✕</button>` : ""}</span></div>
      </div>
      <div class="ch-hot" ${draft.kind === "fish_points" ? "" : "hidden"}>
        <label class="check"><input type="checkbox" name="hot" ${draft.hot ? "checked" : ""}> Hot zones: a fiery patch of open water opens near someone now and then; fish hooked inside it score extra</label>
        <div class="gm-row">
          <label>Bonus <select class="input" name="hot_bonus">${[1.5, 2, 3].map((v) => `<option value="${v}" ${draft.hot_bonus === v ? "selected" : ""}>×${v}</option>`).join("")}</select></label>
          ${hotTimes(draft)}
          <label>Up to <select class="input" name="hot_far">${[24, 40, 64].map((v) => `<option value="${v}" ${draft.hot_far === v ? "selected" : ""}>${v} blocks from a player</option>`).join("")}</select></label>
        </div></div>
      ${gatherHtml(draft.g, state.servers.find((x) => x.id === sid)?.online || [])}
      <label class="ch-lure" ${ROD_KINDS.includes(draft.kind) ? "" : "hidden"}>Faster bites <select class="input" name="lure">
        <option value="0" ${draft.lure === 0 ? "selected" : ""}>Off: everyone uses their own rod</option>
        <option value="3" ${draft.lure === 3 ? "selected" : ""}>Contest Rod with Lure III (bites within ~15 s)</option>
        <option value="5" ${draft.lure === 5 ? "selected" : ""}>Contest Rod with Lure V (bites within ~5 s)</option></select>
        <small class="muted">Each player gets one when it starts (or when they join); it's taken back at the end.</small></label>
      ${fish?.tide ? `<label class="check ch-fair" ${ROD_KINDS.includes(draft.kind) ? "" : "hidden"}><input type="checkbox" name="fair" ${draft.fair ? "checked" : ""}> Fair play: everyone fishes at the same level for the contest (Tide levels are switched off until it ends)</label>` : ""}
      <label class="check"><input type="checkbox" name="say" ${draft.say ? "checked" : ""}> Announce it in the game (start, last minute, winner) and show the scores on everyone's screen</label>
      ${d.rcon ? "" : `<p class="notice">This server needs RCON turned on for challenges (⚙ settings).</p>`}
      <div class="btn-row"><button class="btn primary" type="submit" ${d.rcon ? "" : "disabled"}>${draft.when === "now" ? "Start the challenge" : "Schedule it"}</button></div>
    </form>`;
  const render = () => {
    const live = d.items.filter((c) => c.state === "running"), soon = d.items.filter((c) => c.state === "scheduled"), past = d.items.filter((c) => !["running", "scheduled"].includes(c.state));
    setView(serverHeader(s, "challenges") + playSwitch(sid, "contests") + rconEchoNote(d) + `
      <p class="muted ch-intro">Timed contests for whoever's playing. The game counts the score live and shows it on everyone's screen; the winner gets the prize straight away, or the next time they join.</p>
      ${live.length ? `<section class="section"><div class="section-head"><h2>Happening now</h2></div><div class="ch-list">${live.map(card).join("")}</div></section>` : ""}
      <section class="section">${formHtml()}</section>
      ${soon.length ? `<section class="section"><div class="section-head"><h2>Coming up</h2></div><div class="ch-list">${soon.map(card).join("")}</div></section>` : ""}
      ${d.gifts.length ? `<section class="section"><div class="section-head"><h2>Prizes waiting</h2><span class="muted">Given the next time they join</span></div><div class="panel">${d.gifts.map((g) => `<div class="ch-gift">${faceHtml({ name: g.player }, 22)}<b>${esc(g.player)}</b> ${itemIcon({ id: g.item })} ${g.count} × ${esc(itemName({ id: g.item }))} <span class="muted small">for: ${esc(g.why)}</span></div>`).join("")}</div></section>` : ""}
      ${past.length ? `<section class="section"><div class="section-head"><h2>Finished</h2></div><div class="ch-list">${past.map(card).join("")}</div></section>` : ""}
      ${fishHtml()}`);
    wireHeader(s);
    wire();
    wireFish();
  };
  const reload = async () => { d = await api(base); render(); };
  // --- the fishing pack: is it in the world, how to add it, and the guide to what's out there
  const fishHtml = () => {
    if (!fish) return "";
    const st = fish.status, on = !!st.version, old = on && st.version < st.current;
    const steps = st.writable
      ? `<button class="btn primary" type="button" data-fish="install">Install it in the world</button>`
      : `<ol class="fish-steps"><li><a class="btn sm" href="/api/fishing/${esc(st.file)}?server=${encodeURIComponent(sid)}" download>⬇ Download ${esc(st.file)}</a></li>
          <li>Put the file (still zipped) in this world's <code>datapacks</code> folder: <code>${esc(st.folder.replace(/^\/servers\//, "…/crafty-4/servers/"))}</code></li>
          <li><button class="btn sm primary" type="button" data-fish="reload">Load it</button> <span class="muted small">(runs /reload in the game and checks)</span></li></ol>`;
    const q = fish.qualities.map((x) => `<span class="fish-q fq-${x.color}">${esc(x.name)} <small>${x.one_in <= 2 ? `${x.chance}%` : `1 in ${x.one_in}`}</small></span>`).join("");
    const rows = fish.guide.map((g) => `<tr><td>${itemIcon({ id: g.item })}<b>${esc(g.name)}</b></td><td>${esc(g.waters.join(", "))}</td><td>${g.min_lb}–${g.max_lb} lb</td><td>${g.min_points}–${g.max_points}</td><td class="muted">${esc(g.rarity)}</td></tr>`).join("");
    return `<section class="section" id="fish-sec"><div class="section-head"><h2>🎣 Solstone data pack</h2><span class="muted">${on ? `In the world${old ? " (an update is ready)" : " ✓"}` : "Not in this world yet"}</span></div>
      <div class="panel fish-panel">
        <p>One data pack for fishing and archery. Fishing: every catch is a species with a weight and a quality: <b>${fish.guide.length} kinds of fish</b> that depend on where you cast (rivers and lakes, oceans, warm or cold water, swamps, jungle rivers, the deep ocean). It unlocks the <b>Fishing tournament</b> (most points) and <b>Biggest catch</b> contests, and Trophy and Legendary catches are announced to everyone. Archery: it notes where each shot was taken from and how close to the centre it hit, for the archery games.</p>
        ${!fish.rcon ? `<p class="notice">Needs RCON turned on for this server.</p>` : on && !old ? `<p class="muted small">Loaded (version ${st.version}). <button class="link-btn" type="button" data-fish="reload">Reload</button> · <button class="link-btn" type="button" data-fish="test">Test a catch</button></p>` : steps}
        <div id="fish-diag"></div>
        ${filesHtml(st)}
        ${old && !st.writable ? `<p class="muted small">Replace the old file with the new download, then load it.</p>` : ""}
        ${st.error ? `<p class="notice small">${esc(st.error)}</p>` : ""}
        <div class="fish-qs">${q}</div>
        <details class="fish-guide"><summary>Fish guide</summary><div class="table-wrap"><table class="data"><thead><tr><th>Fish</th><th>Where</th><th>Size</th><th>Points</th><th>How often</th></tr></thead><tbody>${rows}</tbody></table></div></details>
        ${fish.recent.length ? `<h3>Recent catches</h3><ul class="fish-recent">${fish.recent.slice(0, 8).map((e) => `<li>${e.player ? faceHtml({ name: e.player }, 20) : ""}<span>${esc(e.message)}</span><time class="muted small">${esc(fmtAgo(e.ts))}</time></li>`).join("")}</ul>` : ""}
      </div></section>`;
  };
  // What's really in the world's datapacks folder: a second (older) copy, or a zip with an extra
  // folder inside it, is the usual reason the game runs an old version.
  const filesHtml = (st) => {
    const fl = st.files || [];
    const ours = fl.filter((f) => f.version != null);
    const warn = [];
    if (ours.length > 1) warn.push(`There are <b>${ours.length} copies</b> of the Solstone pack in the folder. The game may use the old one: delete all but <code>${esc(st.file)}</code>, then restart the server.`);
    if (ours.some((f) => f.nested)) warn.push("A copy has an extra folder inside the zip, so the game can't read it properly. Use the download as it is, without unzipping and re-zipping it.");
    if (ours.length === 1 && ours[0].version === st.current && st.version && st.version !== st.current) warn.push(`The file is version ${st.current} but the game is still running version ${st.version}. Restart the server (a reload doesn't pick up a replaced file).`);
    if (ours.some((f) => f.loot_format && st.loot_format && f.loot_format !== st.loot_format)) warn.push(`The pack in the folder is written for ${ours.find((f) => f.loot_format !== st.loot_format).loot_format === "26.3" ? "Minecraft 26.3 and newer" : "Minecraft before 26.3"}, but this server is ${esc(st.mc_version || "?")}. Download it again from here: the download is made for this server.`);
    if (!ours.length && fl.length) warn.push(`No Solstone pack in this folder. Is it the right world? The game reads <code>${esc(st.folder)}</code>.`);
    if (!fl.length) return warn.length ? `<p class="notice small">${warn.join("<br>")}</p>` : "";
    const fmt = (f) => `<li><code>${esc(f.name)}</code>${f.folder ? " (folder)" : ""} ${f.version != null ? `<b>Solstone v${f.version}</b>${f.fish_table ? "" : " · no fish table"}` : `<span class="muted">other pack</span>`}${f.modified ? ` <span class="muted small">${esc(fmtAgo(f.modified))}</span>` : ""}${f.error ? ` <span class="notice small">${esc(f.error)}</span>` : ""}</li>`;
    return `${warn.length ? `<p class="notice small">${warn.join("<br>")}</p>` : ""}<details class="fish-files" ${warn.length ? "open" : ""}><summary>In the world's datapacks folder (${fl.length})</summary><ul>${fl.map(fmt).join("")}</ul></details>`;
  };
  const diag = (html) => { const el = $("#fish-diag"); if (el) el.innerHTML = html; };
  const wireFish = () => $$("[data-fish]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    if (b.dataset.fish === "test") {
      diag(`<p class="muted small">Casting a few test lines…</p>`);
      try {
        const t = await post(`/api/servers/${encodeURIComponent(sid)}/fishing/test`, {});
        const what = (r) => r.pack_fish ? `${r.pack_fish.quality} ${r.pack_fish.name} (${r.pack_fish.lb} lb)`
          : r.item ? `${r.named ? `"${r.named}" ` : "plain "}${r.item.replace("minecraft:", "")}${r.probe ? " (tagged)" : ""}` : `nothing (${r.command_reply || "no reply"})`;
        const rodPack = t.rod.filter((r) => r.pack_fish).length;
        const verdict = rodPack ? `<p class="fish-ok">✔ The pack's fish are working: ${rodPack} of ${t.rod.length} rod casts were Solstone fish (the rest are junk and treasure, as usual).</p>`
          : t.pack_fish || t.own.pack_fish ? `<p class="notice small"><b>The pack's fish table works, but the rod's table doesn't use it.</b></p>`
          : t.probe.probe ? `<p class="notice small"><b>The pack's loot functions work, but its fish tables aren't being used.</b></p>`
          : `<p class="notice small"><b>The game isn't applying the pack's loot tables</b> (even the one-line probe).</p>`;
        const lines = [`Tested ${t.where} · pack version ${t.version ?? "?"}${t.barrel && !/changed/i.test(t.barrel) ? ` · barrel: ${t.barrel}` : ""}`,
          `fish table: ${what(t)}`, `solfish:fish: ${what(t.own)}`, `probe: ${what(t.probe)}`, ...t.rod.map((r, i) => `rod cast ${i + 1}: ${what(r)}`),
          "", "probes (3 or 7 = that way works):", ...Object.entries(t.probes || {}).map(([k, v]) => `  ${k}: ${v}`),
          "", "raw:", ...[t, t.own, t.probe].map((r) => `${r.table}: ${r.command_reply} | ${r.item_reply}`),
          "", `packs: ${t.packs}`, ...(t.log?.length ? ["", "game log:", ...t.log] : [])];
        diag(`${verdict}<pre class="mc-out">${esc(lines.join("\n"))}</pre><p class="muted small">Send this to get it fixed.</p>`);
      } catch (e) { diag(`<p class="notice small">${esc(e.message)}</p>`); }
      b.disabled = false;
      return;
    }
    try {
      const r = await post(`/api/servers/${encodeURIComponent(sid)}/fishing/${b.dataset.fish}`, {});
      if (r.problems?.length) { fish = await api(`/api/servers/${encodeURIComponent(sid)}/fishing`); render(); diag(`<div class="notice small"><b>The game reported problems loading data packs:</b><pre class="mc-out">${esc(r.problems.join("\n"))}</pre></div>`); return; }
      showToast(r.version ? `Solstone Fishing is loaded (version ${r.version})` : r.listed === false ? "The game didn't load it. Is the file in the world's datapacks folder?" : "Reloaded, but the pack didn't start. Check the server log for errors.", 5000);
      fish = await api(`/api/servers/${encodeURIComponent(sid)}/fishing`); render();
      if (r.packs) diag(`<details class="fish-files" open><summary>What the game says it has</summary><pre class="mc-out">${esc(r.packs)}</pre></details>`);
    } catch (e) { showToast(esc(e.message), 5000); b.disabled = false; }
  }));
  const wire = () => {
    const form = $("#ch-form");
    const sync = () => { const f = new FormData(form); draft.kind = f.get("kind"); draft.name = f.get("name"); draft.minutes = +f.get("minutes"); draft.when = f.get("when"); draft.at = f.get("at"); draft.say = !!f.get("say"); draft.lure = +(f.get("lure") || 0); draft.fair = !!f.get("fair");
      draft.hot = !!f.get("hot"); for (const k of ["hot_bonus", "hot_on", "hot_off", "hot_far"]) if (f.get(k)) draft[k] = +f.get(k); };
    form.addEventListener("change", (e) => {
      sync();
      if (e.target.name === "kind") { form.querySelectorAll(".ch-kind").forEach((l) => l.classList.toggle("on", l.querySelector("input").checked)); form.name.placeholder = kind(draft.kind).label; form.querySelector(".ch-lure").hidden = !ROD_KINDS.includes(draft.kind); if (form.querySelector(".ch-fair")) form.querySelector(".ch-fair").hidden = !ROD_KINDS.includes(draft.kind); form.querySelector(".ch-hot").hidden = draft.kind !== "fish_points"; }
      if (e.target.name === "at") { draft.when = "later"; form.querySelector('[name=when][value=later]').checked = true; }
      form.querySelector("[type=submit]").textContent = draft.when === "now" ? "Start the challenge" : "Schedule it";
    });
    form.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", () => {
      sync();
      const which = b.dataset.pick;
      openGiveItem(sid, "", { title: which === "prize" ? "Prize for the winner" : "Prize for second place", count: draft[which]?.count || (which === "prize" ? 1 : 1),
        pick: (item, count) => { draft[which] = { item: item.id, count, label: item.name }; render(); } });
    }));
    form.querySelector("[data-clear-second]")?.addEventListener("click", () => { sync(); draft.second = null; render(); });
    wireGather(form, sid, draft.g, () => { sync(); render(); }, d.spawn);
    form.addEventListener("submit", async (e) => {
      e.preventDefault(); sync();
      if (!draft.prize) { showToast("Choose a prize for the winner first", 2500); return; }
      if (draft.g.on && !draft.g.spot) { showToast("Pick the spot to teleport everyone to (or untick teleporting)", 3000); return; }
      const start = draft.when === "now" ? Date.now() / 1000 : new Date(draft.at).getTime() / 1000;
      try {
        const c = await post(base, { kind: draft.kind, name: draft.name, start, minutes: draft.minutes, say: draft.say, lure: ROD_KINDS.includes(draft.kind) ? draft.lure : 0, fair: ROD_KINDS.includes(draft.kind) && !!fish?.tide && draft.fair,
          gather: gatherBody(draft.g),
          hot: draft.kind === "fish_points" && draft.hot, hot_bonus: draft.hot_bonus, hot_on: draft.hot_on, hot_off: draft.hot_off, hot_far: draft.hot_far,
          prize: { item: draft.prize.item, count: draft.prize.count, name: draft.prize.label }, second: draft.second ? { item: draft.second.item, count: draft.second.count, name: draft.second.label } : null });
        showToast(draft.when === "now" ? `${esc(c.name)} starts in a few seconds` : `${esc(c.name)} is scheduled`, 3000);
        draft.name = ""; await reload();
      } catch (err) { showToast(esc(err.message), 4000); }
    });
    $$(".ch-card").forEach((el) => {
      const c = d.items.find((x) => x.id === el.dataset.cid);
      el.querySelector("[data-cancel]")?.addEventListener("click", async () => {
        if ((c.state === "running" || c.state === "scheduled") && !(await confirmBox(c.state === "running" ? `Stop ${c.name}?` : `Cancel ${c.name}?`, c.state === "running" ? "Nobody wins and the scores are cleared from the game." : "It won't start.", c.state === "running" ? "Stop it" : "Cancel it"))) return;
        try { await api(`${base}/${encodeURIComponent(c.id)}`, { method: "DELETE" }); await reload(); } catch (err) { showToast(esc(err.message), 4000); }
      });
      el.querySelector("[data-again]")?.addEventListener("click", () => {
        Object.assign(draft, { kind: c.kind, name: c.name, minutes: c.minutes, say: c.say, lure: c.lure || 0, fair: c.fair !== false, hot: !!c.hot, hot_bonus: c.hot_bonus || 2, hot_on: c.hot_on || 60, hot_off: c.hot_off || 30, hot_far: c.hot_far || 40, when: "now",
          prize: { ...c.prize, label: c.prize.name }, second: c.second ? { ...c.second, label: c.second.name } : null });
        render(); $("#ch-form").scrollIntoView({ behavior: "smooth", block: "center" });
      });
    });
  };
  render();
  // live scores and countdowns while something's on (and pick up a scheduled start)
  every(1000, () => $$("[data-left]").forEach((el) => { el.textContent = left(+el.dataset.left); }));
  every(5000, async () => {
    if (!d.items.some((c) => c.state === "running" || (c.state === "scheduled" && c.start - Date.now() / 1000 < 30))) return;
    if (document.activeElement?.closest?.("#ch-form") || $(".modal")) return;      // don't redraw under someone typing
    await reload();
  });
}

// Shown on all three pages while the server echoes RCON commands to operators.
// Teleport everyone to a spot when an event starts, and back afterwards. `g` = {on, spot, r}.
function gatherHtml(g, names) {
  return `<div class="gather-box gm-wide">
    <label class="check"><input type="checkbox" data-g-on ${g.on ? "checked" : ""}> Teleport everyone to a spot when it starts, then back to where they were afterwards</label>
    ${g.on ? `<div class="gather-pick">
      <div class="btn-row"><select class="input sm" data-g-player>${names.map((n) => `<option>${esc(n)}</option>`).join("") || "<option value=''>Nobody online</option>"}</select>
        <button type="button" class="btn sm" data-g-here>Use where they're standing</button>
        <label class="small">Spread out <select class="input sm" data-g-r>${[2, 4, 6, 8].map((v) => `<option value="${v}" ${g.r === v ? "selected" : ""}>${v} blocks</option>`).join("")}</select> around it</label></div>
      <div class="gather-map" data-g-map></div>
      <p class="small ${g.spot ? "" : "muted"}">${g.spot ? `📍 Everyone goes to <b>${Math.round(g.spot.x)}, ${Math.round(g.spot.y)}, ${Math.round(g.spot.z)}</b> when it starts, and home 10 seconds after it ends (with a countdown).` : "Click the map, or use where someone is standing."}</p></div>` : ""}</div>`;
}
function wireGather(root, sid, g, rerender, center) {
  root.querySelector("[data-g-on]")?.addEventListener("change", (e) => { g.on = e.target.checked; rerender(); });
  root.querySelector("[data-g-r]")?.addEventListener("change", (e) => { g.r = +e.target.value; map?.draw(); });
  root.querySelector("[data-g-here]")?.addEventListener("click", async () => {
    const who = root.querySelector("[data-g-player]").value;
    if (!who) return;
    try { g.spot = await api(`/api/servers/${encodeURIComponent(sid)}/races/spot?player=${encodeURIComponent(who)}`); rerender(); } catch (err) { showToast(esc(err.message), 4000); }
  });
  const el = root.querySelector("[data-g-map]");
  const map = el ? worldMapCanvas(el, sid, {
    center: g.spot || center || { x: 0, z: 0 }, scale: 2,
    overlay: (ctx, toScreen, view) => {
      if (!g.spot) return;
      const [x, y] = toScreen(g.spot.x, g.spot.z);
      ctx.fillStyle = "rgba(90, 200, 255, .22)"; ctx.beginPath(); ctx.arc(x, y, Math.max(6, g.r * view.scale), 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#5ac8ff"; ctx.strokeStyle = "#000"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    },
    onClick: async (x, z) => { g.spot = await api(`/api/servers/${encodeURIComponent(sid)}/races/spot?x=${x}&z=${z}`).catch(() => ({ x, y: 64, z })); rerender(); },
  }) : null;
}
const gatherBody = (g) => (g.on && g.spot ? { x: g.spot.x, y: g.spot.y, z: g.spot.z, r: g.r } : null);

// How long each hot zone stays open, and the wait before the next (archery and the fishing tournament).
function hotTimes(f) {
  const opt = (vals, cur, fmt) => vals.map((v) => `<option value="${v}" ${cur === v ? "selected" : ""}>${fmt(v)}</option>`).join("");
  const secs = (v) => (v < 60 ? `${v} seconds` : `${v / 60} minute${v > 60 ? "s" : ""}`);
  return `<label>Open for <select class="input" name="hot_on">${opt([30, 45, 60, 90, 120], f.hot_on, secs)}</select></label>
    <label>Next one after <select class="input" name="hot_off">${opt([10, 20, 30, 60, 120], f.hot_off, secs)}</select></label>`;
}
function rconEchoNote(d) {
  return d?.rcon_echo ? `<div class="notice small echo-note"><b>Ops will see a lot of "[Rcon: …]" lines in chat</b> while contests, races and games run: the server shows operators every command Solstone sends. To turn that off, set <code>broadcast-rcon-to-ops=false</code> in this server's <code>server.properties</code> (in Crafty: the server's Config tab) and restart it.</div>` : "";
}

// Contests and races share the Challenges tab.
function playSwitch(sid, on) {
  const base = `#/s/${encodeURIComponent(sid)}/challenges`;
  return `<nav class="seg play-switch" aria-label="Kind of challenge"><a href="${base}" ${on === "contests" ? 'aria-current="page"' : ""}>🏆 Contests</a><a href="${base}/races" ${on === "races" ? 'aria-current="page"' : ""}>🏁 Races</a><a href="${base}/games" ${on === "games" ? 'aria-current="page"' : ""}>🎲 Games</a></nav>`;
}

// ---------------------------------------------------------------- a small world map (course editor)
// Region pictures from the map renderer; drag to move, wheel or buttons to zoom, click to add.
function worldMapCanvas(el, sid, o) {
  el.innerHTML = `<canvas class="rm-canvas" aria-label="World map: click to add a point"></canvas>
    <div class="rm-zoom"><button type="button" class="icon-btn" data-z="1" aria-label="Zoom in">＋</button><button type="button" class="icon-btn" data-z="-1" aria-label="Zoom out">－</button></div>
    <div class="rm-note muted small"></div>`;
  const cv = el.querySelector("canvas"), ctx = cv.getContext("2d"), note = el.querySelector(".rm-note");
  const dim = o.dim || "minecraft:overworld";
  const view = { cx: o.center?.x ?? 0, cz: o.center?.z ?? 0, scale: o.scale || 1 };     // scale: pixels per block
  const tiles = {}; let regions = null;
  fetch(`/api/public/map/${encodeURIComponent(sid)}/regions?dim=${encodeURIComponent(dim)}`, { credentials: "same-origin" })
    .then((r) => (r.ok ? r.json() : null)).then((d) => { regions = new Set((d?.regions || []).map(([x, z]) => `${x},${z}`)); draw(); }).catch(() => { regions = new Set(); draw(); });
  const tile = (rx, rz) => {
    const k = `${rx},${rz}`;
    let t = tiles[k];
    if (t && (t.img || t.loading || (t.retry && Date.now() < t.retry))) return t;
    t = tiles[k] = { loading: true };
    fetch(`/api/public/map/${encodeURIComponent(sid)}/tile?dim=${encodeURIComponent(dim)}&x=${rx}&z=${rz}`, { credentials: "same-origin" })
      .then(async (r) => {
        t.loading = false;
        if (r.status === 202) { t.retry = Date.now() + 3000; setTimeout(draw, 3100); return; }
        if (r.ok) { t.img = await createImageBitmap(await r.blob()); draw(); }
      }).catch(() => { t.loading = false; t.retry = Date.now() + 10000; });
    return t;
  };
  const toScreen = (x, z) => [cv.clientWidth / 2 + (x - view.cx) * view.scale, cv.clientHeight / 2 + (z - view.cz) * view.scale];
  const toWorld = (px, py) => [view.cx + (px - cv.clientWidth / 2) / view.scale, view.cz + (py - cv.clientHeight / 2) / view.scale];
  function draw() {
    if (!cv.isConnected) return;
    const dpr = devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#101826"; ctx.fillRect(0, 0, w, h);
    let waiting = 0;
    if (regions) {
      const [x0, z0] = toWorld(0, 0), [x1, z1] = toWorld(w, h);
      ctx.imageSmoothingEnabled = view.scale < 1;
      for (let rx = Math.floor(x0 / 512); rx <= Math.floor(x1 / 512); rx++) {
        for (let rz = Math.floor(z0 / 512); rz <= Math.floor(z1 / 512); rz++) {
          if (!regions.has(`${rx},${rz}`)) continue;
          const t = tile(rx, rz);
          if (t.img) { const [sx, sy] = toScreen(rx * 512, rz * 512); ctx.drawImage(t.img, Math.round(sx), Math.round(sy), Math.ceil(512 * view.scale) + 1, Math.ceil(512 * view.scale) + 1); }
          else waiting++;
        }
      }
    }
    note.textContent = !regions ? "Loading the map…" : waiting ? "Drawing the map…" : "";
    // grid every 64 or 256 blocks, labelled
    const step = view.scale >= 1 ? 64 : view.scale >= 0.25 ? 256 : 1024;
    const [gx0, gz0] = toWorld(0, 0);
    ctx.strokeStyle = "rgba(255,255,255,.08)"; ctx.fillStyle = "rgba(255,255,255,.45)"; ctx.font = "11px system-ui";
    for (let x = Math.ceil(gx0 / step) * step; toScreen(x, 0)[0] < w; x += step) { const sx = Math.round(toScreen(x, 0)[0]) + 0.5; ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, h); ctx.stroke(); ctx.fillText(x, sx + 3, h - 5); }
    for (let z = Math.ceil(gz0 / step) * step; toScreen(0, z)[1] < h; z += step) { const sy = Math.round(toScreen(0, z)[1]) + 0.5; ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(w, sy); ctx.stroke(); ctx.fillText(z, 4, sy - 3); }
    o.overlay?.(ctx, toScreen, view);
  }
  // pan / click / zoom
  let drag = null;
  cv.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, cx: view.cx, cz: view.cz, moved: false }; cv.setPointerCapture(e.pointerId); });
  cv.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
    if (drag.moved) { view.cx = drag.cx - dx / view.scale; view.cz = drag.cz - dy / view.scale; draw(); }
  });
  cv.addEventListener("pointerup", (e) => {
    const d = drag; drag = null;
    if (d && !d.moved) { const r = cv.getBoundingClientRect(); const [x, z] = toWorld(e.clientX - r.left, e.clientY - r.top); o.onClick?.(Math.round(x), Math.round(z)); }
  });
  const zoom = (f, px, py) => {
    const [wx, wz] = toWorld(px, py);
    view.scale = Math.max(1 / 16, Math.min(8, view.scale * f));
    const [nx, nz] = toWorld(px, py); view.cx += wx - nx; view.cz += wz - nz; draw();
  };
  cv.addEventListener("wheel", (e) => { e.preventDefault(); const r = cv.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1.25 : 0.8, e.clientX - r.left, e.clientY - r.top); }, { passive: false });
  el.querySelectorAll("[data-z]").forEach((b) => b.addEventListener("click", () => zoom(b.dataset.z === "1" ? 1.5 : 1 / 1.5, cv.clientWidth / 2, cv.clientHeight / 2)));
  const ro = new ResizeObserver(() => draw()); ro.observe(cv);
  return {
    draw,
    fit(points) {
      if (!points.length) return;
      const xs = points.map((p) => p.x), zs = points.map((p) => p.z);
      view.cx = (Math.min(...xs) + Math.max(...xs)) / 2; view.cz = (Math.min(...zs) + Math.max(...zs)) / 2;
      const span = Math.max(64, Math.max(...xs) - Math.min(...xs), Math.max(...zs) - Math.min(...zs)) * 1.4;
      view.scale = Math.max(1 / 16, Math.min(4, Math.min(cv.clientWidth || 600, cv.clientHeight || 400) / span));
      draw();
    },
  };
}

// The course drawn on a map: route lines, then S / 1..n / F markers.
function drawCourse(ctx, toScreen, pts, opts = {}) {
  if (!pts.length) return;
  ctx.lineWidth = 3; ctx.strokeStyle = "rgba(242,193,78,.85)"; ctx.setLineDash([8, 6]);
  ctx.beginPath(); pts.forEach((p, i) => { const [x, y] = toScreen(p.x, p.z); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); }); ctx.stroke();
  ctx.setLineDash([]);
  const last = pts.length - 1;
  ctx.font = "bold 12px system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  pts.forEach((p, i) => {
    const [x, y] = toScreen(p.x, p.z);
    const label = i === 0 ? "S" : i === last ? "F" : String(i);
    const done = opts.reached != null && i <= opts.reached;
    ctx.fillStyle = i === 0 ? "#ebe6d9" : i === last ? "#f2c14e" : done ? "#5fb59a" : "#4cd964";
    ctx.beginPath(); ctx.arc(x, y, 11, 0, Math.PI * 2); ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = opts.selected === i ? "#fff" : "rgba(0,0,0,.6)"; ctx.stroke();
    ctx.fillStyle = "#101826"; ctx.fillText(label, x, y + 0.5);
  });
  ctx.textAlign = "start"; ctx.textBaseline = "alphabetic";
}

// ---------------------------------------------------------------- races
async function viewRaces(sid) {
  if (!isAdmin()) { location.replace(`#/s/${encodeURIComponent(sid)}`); return; }
  const s = await serverFrame(sid, "challenges");
  const base = `/api/servers/${encodeURIComponent(sid)}/races`;
  let d = await api(base);
  let editing = null;                     // the course being edited: { id?, name, points: [...] }
  const fmtT = (sec) => (sec == null ? "" : `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`);
  const fmtWhen = (ts) => new Date(ts * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
  const length = (pts) => Math.round(pts.slice(1).reduce((a, p, i) => a + Math.hypot(p.x - pts[i].x, p.z - pts[i].z), 0));
  const online = () => state.servers.find((x) => x.id === sid)?.online || [];
  const pointName = (pts, i) => (i === 0 ? "Start" : i === pts.length - 1 ? "Finish" : `Checkpoint ${i}`);

  const runCard = (r) => {
    const last = r.points.length - 1;
    const live = r.state === "running" || r.state === "countdown";
    const rows = (r.standings || []).map((x, i) => `<li class="${x.finished != null && i === 0 ? "win" : ""}"><span class="rank">${i + 1}</span>${faceHtml({ name: x.name }, 22)}<b>${esc(x.name)}</b>
      <span class="val">${x.finished != null ? `🏁 ${fmtT(x.finished)}` : `${x.reached}/${last}`}</span></li>`).join("");
    const status = r.state === "countdown" ? `<span class="ch-live">● Starting…</span>` : r.state === "running" ? `<span class="ch-live">● Racing · <span data-left="${r.ends_at}"></span> left</span>`
      : r.state === "scheduled" ? `<span class="muted">${esc(fmtWhen(r.start))} · ${r.minutes} min limit</span>`
      : `<span class="muted">${esc({ done: "Finished", skipped: "Didn't run", cancelled: "Called off" }[r.state] || r.state)} · ${esc(fmtWhen(r.start))}</span>`;
    return `<div class="ch-card panel ch-${live ? "running" : r.state}" data-rid="${esc(r.id)}">
      <div class="ch-head"><span class="ch-emoji">🏁</span><div><h3>${esc(r.name)}</h3>${status}</div>
        <div class="ch-acts">${["scheduled", "countdown", "running"].includes(r.state) ? `<button class="btn sm danger" type="button" data-stop>${r.state === "scheduled" ? "Cancel" : "Stop"}</button>` : `<button class="icon-btn" type="button" data-stop title="Remove from the list" aria-label="Remove">✕</button>`}</div></div>
      ${r.prizes?.some(Boolean) ? `<div class="ch-prize">${r.prizes.map((p, i) => (p ? `<span class="muted">${["🥇", "🥈", "🥉"][i]}</span> ${itemIcon({ id: p.item })}<span>${p.count} × ${esc(p.name || itemName({ id: p.item }))}</span>` : "")).join(" ")}</div>` : ""}
      ${r.marker_error ? `<p class="notice small">The markers didn't place: ${esc(r.marker_error)}</p>` : ""}
      ${r.result ? `<p class="ch-result">${esc(r.result)}</p>` : ""}
      ${rows ? `<ol class="ch-scores">${rows}</ol>` : live ? `<p class="muted small">Waiting for racers…</p>` : ""}
    </div>`;
  };
  const courseCard = (c) => `<div class="ch-card panel" data-cid="${esc(c.id)}">
      <div class="ch-head"><span class="ch-emoji">🗺️</span><div><h3>${esc(c.name)}</h3><span class="muted">${c.points.length - 2} checkpoints · about ${length(c.points)} blocks</span></div>
        <div class="ch-acts"><button class="btn sm primary" type="button" data-race>Race</button><button class="btn sm" type="button" data-edit>Edit</button><button class="icon-btn" type="button" data-del aria-label="Delete course">✕</button></div></div>
    </div>`;

  const render = () => {
    if (editing) return renderEditor();
    const live = d.runs.filter((r) => ["running", "countdown"].includes(r.state)), soon = d.runs.filter((r) => r.state === "scheduled"), past = d.runs.filter((r) => !["running", "countdown", "scheduled"].includes(r.state));
    setView(serverHeader(s, "challenges") + playSwitch(sid, "races") + rconEchoNote(d) + `
      <p class="muted ch-intro">Lay out a course of checkpoints on the map, then race it. In the game each point is a tall glowing column with its name floating above it, and everyone sees which way to go and how far.</p>
      ${d.rcon ? "" : `<p class="notice">Races need RCON turned on for this server (⚙ settings).</p>`}
      ${live.length ? `<section class="section"><div class="section-head"><h2>Racing now</h2></div><div class="ch-list">${live.map(runCard).join("")}</div></section>` : ""}
      <section class="section"><div class="section-head"><h2>Courses</h2><button class="btn sm primary" type="button" id="rc-new" style="margin-left:auto">＋ New course</button></div>
        ${d.courses.length ? `<div class="ch-list">${d.courses.map(courseCard).join("")}</div>` : `<div class="empty"><p>No courses yet. Make one to start racing.</p></div>`}</section>
      ${soon.length ? `<section class="section"><div class="section-head"><h2>Coming up</h2></div><div class="ch-list">${soon.map(runCard).join("")}</div></section>` : ""}
      ${past.length ? `<section class="section"><div class="section-head"><h2>Finished</h2></div><div class="ch-list">${past.map(runCard).join("")}</div></section>` : ""}`);
    wireHeader(s);
    $("#rc-new").addEventListener("click", () => { editing = { name: "", points: [] }; render(); });
    $$("[data-cid]").forEach((el) => {
      const c = d.courses.find((x) => x.id === el.dataset.cid);
      el.querySelector("[data-edit]").addEventListener("click", () => { editing = JSON.parse(JSON.stringify(c)); render(); });
      el.querySelector("[data-del]").addEventListener("click", async () => {
        if (!(await confirmBox(`Delete ${c.name}?`, "The course is removed. Past results stay.", "Delete"))) return;
        await api(`${base}/courses/${encodeURIComponent(c.id)}`, { method: "DELETE" }).catch((e) => showToast(esc(e.message), 4000)); await reload();
      });
      el.querySelector("[data-race]").addEventListener("click", () => openRaceStart(c));
    });
    $$("[data-rid]").forEach((el) => el.querySelector("[data-stop]")?.addEventListener("click", async () => {
      const r = d.runs.find((x) => x.id === el.dataset.rid);
      const active = ["scheduled", "countdown", "running"].includes(r.state);
      if (active && !(await confirmBox(r.state === "scheduled" ? `Cancel ${r.name}?` : `Stop ${r.name}?`, "The markers are removed and nobody gets a prize.", r.state === "scheduled" ? "Cancel it" : "Stop it"))) return;
      await api(`${base}/runs/${encodeURIComponent(r.id)}`, { method: "DELETE" }).catch((e) => showToast(esc(e.message), 4000)); await reload();
    }));
    tickLeft();
  };
  const tickLeft = () => $$("[data-left]").forEach((el) => { el.textContent = fmtT(Math.max(0, +el.dataset.left - Date.now() / 1000)); });

  // --- the course editor
  let map = null, selected = null;
  const renderEditor = () => {
    const pts = editing.points;
    setView(serverHeader(s, "challenges") + playSwitch(sid, "races") + `
      <form class="rc-edit" id="rc-form" autocomplete="off">
        <div class="rc-top"><label>Course name <input class="input" name="name" maxlength="40" value="${esc(editing.name)}" placeholder="Mountain loop" required></label>
          <div class="btn-row"><button class="btn" type="button" id="rc-cancel">Cancel</button><button class="btn primary" type="submit">Save course</button></div></div>
        <p class="muted small">Click the map to add points in order: the first is the start, the last is the finish. Or stand somewhere in the game and add that spot.</p>
        <div class="rc-grid">
          <div class="rc-map" id="rc-map"></div>
          <div class="rc-side">
            <div class="btn-row rc-here"><select class="input sm" id="rc-player" aria-label="Player">${online().map((n) => `<option>${esc(n)}</option>`).join("") || "<option value=''>Nobody online</option>"}</select>
              <button class="btn sm" type="button" id="rc-addhere" ${online().length ? "" : "disabled"}>＋ Add where they're standing</button></div>
            <ol class="rc-points">${pts.map((p, i) => `<li class="${selected === i ? "sel" : ""}" data-i="${i}">
                <span class="rc-badge ${i === 0 ? "s" : i === pts.length - 1 && pts.length > 1 ? "f" : ""}">${i === 0 ? "S" : i === pts.length - 1 && pts.length > 1 ? "F" : i}</span>
                <div class="rc-pt"><input class="input sm" data-name value="${esc(p.name || "")}" placeholder="${pointName(pts, i)}" maxlength="32" aria-label="Name for point ${i + 1}">
                  <span class="muted small">${Math.round(p.x)}, ${Math.round(p.y)}, ${Math.round(p.z)} · reach within <input class="input sm num-in" type="number" data-radius min="2" max="16" value="${p.radius || 4}" aria-label="Radius"> blocks</span></div>
                <span class="rc-acts"><button type="button" class="icon-btn" data-up ${i === 0 ? "disabled" : ""} aria-label="Move up">▲</button><button type="button" class="icon-btn" data-down ${i === pts.length - 1 ? "disabled" : ""} aria-label="Move down">▼</button><button type="button" class="icon-btn" data-rm aria-label="Remove">✕</button></span></li>`).join("")}</ol>
            ${pts.length ? `<p class="muted small">${Math.max(0, pts.length - 2)} checkpoints · about ${length(pts)} blocks</p>` : `<p class="muted small">No points yet.</p>`}
          </div>
        </div>
      </form>`);
    wireHeader(s);
    const form = $("#rc-form");
    map = worldMapCanvas($("#rc-map"), sid, {
      center: pts[0] || d.spawn || { x: 0, z: 0 }, scale: 1,
      overlay: (ctx, toScreen) => {
        if (d.spawn) { const [x, y] = toScreen(d.spawn.x, d.spawn.z); ctx.fillStyle = "#f2c14e"; ctx.beginPath(); ctx.moveTo(x, y - 6); ctx.lineTo(x + 6, y); ctx.lineTo(x, y + 6); ctx.lineTo(x - 6, y); ctx.fill(); }
        drawCourse(ctx, toScreen, editing.points, { selected });
      },
      onClick: async (x, z) => {
        try { const p = await api(`${base}/spot?x=${x}&z=${z}`); addPoint(p); } catch (e) { showToast(esc(e.message), 3000); }
      },
    });
    if (pts.length > 1) setTimeout(() => map.fit(pts), 0);
    const sync = () => {
      editing.name = form.name.value;
      $$(".rc-points li", form).forEach((li) => { const p = editing.points[+li.dataset.i]; p.name = li.querySelector("[data-name]").value.trim(); p.radius = +li.querySelector("[data-radius]").value || 4; });
    };
    const addPoint = (p) => { sync(); editing.points.push({ x: p.x, y: p.y, z: p.z, radius: 4, name: "" }); selected = editing.points.length - 1; renderEditor(); };
    $("#rc-addhere").addEventListener("click", async () => {
      try { addPoint(await api(`${base}/spot?player=${encodeURIComponent($("#rc-player").value)}`)); } catch (e) { showToast(esc(e.message), 4000); }
    });
    $$(".rc-points li", form).forEach((li) => {
      const i = +li.dataset.i;
      li.querySelector("[data-rm]").addEventListener("click", () => { sync(); editing.points.splice(i, 1); selected = null; renderEditor(); });
      li.querySelector("[data-up]").addEventListener("click", () => { sync(); const a = editing.points; [a[i - 1], a[i]] = [a[i], a[i - 1]]; selected = i - 1; renderEditor(); });
      li.querySelector("[data-down]").addEventListener("click", () => { sync(); const a = editing.points; [a[i + 1], a[i]] = [a[i], a[i + 1]]; selected = i + 1; renderEditor(); });
      li.addEventListener("focusin", () => { selected = i; map.draw(); });
    });
    $("#rc-cancel").addEventListener("click", () => { editing = null; render(); });
    form.addEventListener("submit", async (e) => {
      e.preventDefault(); sync();
      if (editing.points.length < 2) { showToast("Add at least a start and a finish", 3000); return; }
      try {
        const body = { name: editing.name, points: editing.points, dim: "minecraft:overworld" };
        await (editing.id ? post(`${base}/courses/${encodeURIComponent(editing.id)}`, body, "PUT") : post(`${base}/courses`, body));
        showToast("Course saved", 2000); editing = null; await reload();
      } catch (err) { showToast(esc(err.message), 4000); }
    });
  };

  // --- starting a race
  const openRaceStart = (c) => {
    const prizes = [null, null, null];
    const at = (() => { const t = new Date(Date.now() + 15 * 60e3); t.setSeconds(0, 0); return new Date(t.getTime() - t.getTimezoneOffset() * 60e3).toISOString().slice(0, 16); })();
    const prizeBtn = (i) => `<button type="button" class="btn ch-pick" data-prize="${i}">${prizes[i] ? `${itemIcon({ id: prizes[i].item })}<span>${prizes[i].count} × ${esc(prizes[i].name)}</span>` : `<span class="muted">${i ? "Optional" : "Choose…"}</span>`}</button>`;
    const body = () => `<h2>Race ${esc(c.name)}</h2>
      <form id="rs-form" class="rs-form">
        <div class="ch-when"><span class="lbl">When</span>
          <label class="check"><input type="radio" name="when" value="now" checked> Right now (10-second countdown)</label>
          <label class="check"><input type="radio" name="when" value="later"> At <input class="input sm" type="datetime-local" name="at" value="${at}"></label></div>
        <label>Time limit <select class="input" name="minutes">${[5, 10, 15, 20, 30].map((m) => `<option value="${m}" ${m === 15 ? "selected" : ""}>${m} minutes</option>`).join("")}</select></label>
        <label class="check"><input type="checkbox" name="teleport" checked> Line everyone up at the start, held still until GO, and send them back where they were afterwards</label>
        <div class="rs-prizes">${["🥇 1st", "🥈 2nd", "🥉 3rd"].map((l, i) => `<span class="lbl">${l}</span><span id="rs-p${i}">${prizeBtn(i)}</span>`).join("")}</div>
        <div class="actions"><button type="button" class="btn" data-close-modal>Cancel</button><button class="btn primary" type="submit">Start</button></div>
      </form>`;
    openModal(body(), (m) => {
      const wire = () => m.querySelectorAll("[data-prize]").forEach((b) => b.addEventListener("click", () => {
        const i = +b.dataset.prize, keep = $("#rs-form", m).cloneNode(true);
        openGiveItem(sid, "", { title: `Prize for ${["first", "second", "third"][i]} place`, pick: (item, count) => {
          prizes[i] = { item: item.id, count, name: item.name };
          openModal(body(), (m2) => { restore(m2, keep); wireAll(m2); });
        } });
      }));
      const restore = (m2, keep) => {
        const f = $("#rs-form", m2);
        f.when.value = keep.when.value; f.at.value = keep.at.value; f.minutes.value = keep.minutes.value; f.teleport.checked = keep.teleport.checked;
      };
      const wireAll = (mm) => {
        m = mm; wire();
        $("#rs-form", mm).addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = e.target;
          const start = f.when.value === "now" ? Date.now() / 1000 : new Date(f.at.value).getTime() / 1000;
          try {
            await post(`${base}/runs`, { course: c.id, start, minutes: +f.minutes.value, teleport: f.teleport.checked, prizes });
            closeModal(); showToast(f.when.value === "now" ? "Race starting: 10-second countdown in the game" : "Race scheduled", 3000); await reload();
          } catch (err) { showToast(esc(err.message), 4000); }
        });
      };
      wireAll(m);
    });
  };

  const reload = async () => { d = await api(base); render(); };
  render();
  every(1000, tickLeft);
  every(2000, async () => {
    if (editing || $(".modal")) return;
    if (!d.runs.some((r) => ["countdown", "running"].includes(r.state) || (r.state === "scheduled" && r.start - Date.now() / 1000 < 20))) return;
    await reload();
  });
}

// ---------------------------------------------------------------- games
const GAME_INFO = {
  hideseek: ["🙈", "Hide and seek", "One seeker, everyone else hides inside an area. Optional no-digging, Marco Polo in chat, and found hiders can join the seekers."],
  treasure: ["💰", "Treasure hunt", "A chest of prizes hidden somewhere in an area. Everyone's hotbar says how warm they are. First to take the treasure wins."],
  archery: ["🎯", "Archery", "Longest bullseye, most points, or HORSE: make the setter's shot from the same spot or take a letter. Needs the Solstone data pack."],
  spleef: ["❄️", "Spleef", "A snow arena high in the sky, a shovel each: dig the floor out from under everyone else. Last one standing wins the round. Teams, layers, a shrinking floor. Needs the Solstone data pack."],
};

async function viewGames(sid) {
  if (!isAdmin()) { location.replace(`#/s/${encodeURIComponent(sid)}`); return; }
  const s = await serverFrame(sid, "challenges");
  const base = `/api/servers/${encodeURIComponent(sid)}/games`;
  let d = await api(base);
  const fmtT = (sec) => `${Math.floor(Math.max(0, sec) / 60)}:${String(Math.floor(Math.max(0, sec) % 60)).padStart(2, "0")}`;
  const fmtWhen = (ts) => new Date(ts * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
  const online = () => state.servers.find((x) => x.id === sid)?.online || [];
  const runCard = (r) => {
    const live = ["countdown", "hiding", "running"].includes(r.state);
    const [emoji] = GAME_INFO[r.game];
    let body = "";
    if (r.game === "hideseek" && Object.keys(r.players || {}).length) {
      body = `<ul class="gm-players">${Object.entries(r.players).map(([n, p]) => `<li>${faceHtml({ name: n }, 20)}<b>${esc(n)}</b><span class="gm-role ${p.role}">${{ seeker: "seeker", hider: "hiding", found: "found" }[p.role]}${p.found_by ? ` (by ${esc(p.found_by)})` : ""}</span></li>`).join("")}</ul>`;
    } else if (r.game === "archery" && Object.keys(r.players || {}).length) {
      const rows = Object.entries(r.players).sort((a, b) => (r.mode === "horse" ? a[1].letters.length - b[1].letters.length : r.mode === "points" ? b[1].points - a[1].points : b[1].best - a[1].best));
      body = `<ol class="ch-scores">${rows.map(([n, p], i) => `<li><span class="rank">${i + 1}</span>${faceHtml({ name: n }, 22)}<b>${esc(n)}${r.turn === n && live ? " 🎯" : ""}</b><span class="val">${r.mode === "horse" ? esc(p.letters || "–") : r.mode === "points" ? `${p.points} pts` : p.best ? `${p.best} m` : "–"}</span></li>`).join("")}</ol>`;
    } else if (r.game === "spleef" && Object.keys(r.players || {}).length) {
      const rows = Object.entries(r.players).sort((a, b) => b[1].wins - a[1].wins || a[0].localeCompare(b[0]));
      body = `${r.teams ? `<p class="muted small">Red ${r.team_wins?.red || 0} · Blue ${r.team_wins?.blue || 0}</p>` : ""}<ol class="ch-scores">${rows.map(([n, p], i) => `<li><span class="rank">${i + 1}</span>${faceHtml({ name: n }, 22)}<b>${esc(n)}${r.teams ? ` <span class="gm-team ${esc(p.team || "")}">${esc(p.team || "")}</span>` : ""}</b><span class="val">${live ? (p.alive ? "standing" : "out") : ""}${r.teams ? "" : ` · ${p.wins} won`}</span></li>`).join("")}</ol>`;
    } else if (r.game === "treasure" && r.items) {
      body = `<div class="ch-prize">${r.items.map((it) => `${itemIcon({ id: it.item })}<span>${it.count} × ${esc(it.name || itemName({ id: it.item }))}</span>`).join(" ")}</div>`;
    }
    const status = live ? `<span class="ch-live">● ${r.state === "hiding" ? "Hiding" : "On now"}${r.phase_ends ? ` · <span data-left="${r.phase_ends}"></span> left` : ""}</span>`
      : r.state === "scheduled" ? `<span class="muted">${esc(fmtWhen(r.start))}</span>` : `<span class="muted">${esc({ done: "Finished", skipped: "Didn't run", cancelled: "Called off" }[r.state] || r.state)} · ${esc(fmtWhen(r.start))}</span>`;
    return `<div class="ch-card panel ch-${live ? "running" : r.state}" data-gid="${esc(r.id)}">
      <div class="ch-head"><span class="ch-emoji">${emoji}</span><div><h3>${esc(r.name)}</h3>${status}</div>
        <div class="ch-acts">${live || r.state === "scheduled" ? `<button class="btn sm danger" type="button" data-stop>${live ? "Stop" : "Cancel"}</button>` : `<button class="icon-btn" type="button" data-stop aria-label="Remove">✕</button>`}</div></div>
      ${r.result ? `<p class="ch-result">${esc(r.result)}</p>` : ""}${r.chest_error ? `<p class="notice small">The chest didn't place: ${esc(r.chest_error)}</p>` : ""}${body}</div>`;
  };
  const render = () => {
    const live = d.runs.filter((r) => ["countdown", "hiding", "running"].includes(r.state)), soon = d.runs.filter((r) => r.state === "scheduled"), past = d.runs.filter((r) => !["countdown", "hiding", "running", "scheduled"].includes(r.state));
    const packOk = (d.pack || 0) >= d.pack_needed, spleefOk = (d.pack || 0) >= (d.pack_needed_spleef || 10);
    const needsPack = (k) => (k === "archery" && !packOk) || (k === "spleef" && !spleefOk);
    setView(serverHeader(s, "challenges") + playSwitch(sid, "games") + rconEchoNote(d) + `
      ${d.rcon ? "" : `<p class="notice">Games need RCON turned on for this server (⚙ settings).</p>`}
      ${live.length ? `<section class="section"><div class="section-head"><h2>Playing now</h2></div><div class="ch-list">${live.map(runCard).join("")}</div></section>` : ""}
      <section class="section"><div class="ch-list">${Object.entries(GAME_INFO).map(([k, [e, t, about]]) => `<div class="ch-card panel gm-pick">
        <div class="ch-head"><span class="ch-emoji">${e}</span><div><h3>${esc(t)}</h3></div></div><p class="muted">${esc(about)}</p>
        ${needsPack(k) ? `<p class="notice small">Add the Solstone data pack to the world first (on the <a href="#/s/${encodeURIComponent(sid)}/challenges">Contests</a> page${d.pack ? ": it needs the newer version" : ""}).</p>` : ""}
        <div class="btn-row"><button class="btn primary" type="button" data-setup="${k}" ${!d.rcon || needsPack(k) ? "disabled" : ""}>Set up</button></div></div>`).join("")}</div></section>
      ${soon.length ? `<section class="section"><div class="section-head"><h2>Coming up</h2></div><div class="ch-list">${soon.map(runCard).join("")}</div></section>` : ""}
      ${past.length ? `<section class="section"><div class="section-head"><h2>Finished</h2></div><div class="ch-list">${past.map(runCard).join("")}</div></section>` : ""}`);
    wireHeader(s);
    $$("[data-setup]").forEach((b) => b.addEventListener("click", () => openSetup(b.dataset.setup)));
    $$("[data-gid]").forEach((el) => el.querySelector("[data-stop]")?.addEventListener("click", async () => {
      const r = d.runs.find((x) => x.id === el.dataset.gid);
      const active = ["scheduled", "countdown", "hiding", "running"].includes(r.state);
      if (active && !(await confirmBox(`Stop ${r.name}?`, "Everything is put back (game modes, the chest or target) and nobody gets a prize.", "Stop it"))) return;
      await api(`${base}/${encodeURIComponent(r.id)}`, { method: "DELETE" }).catch((e) => showToast(esc(e.message), 4000)); await reload();
    }));
    tickLeft();
  };
  const tickLeft = () => $$("[data-left]").forEach((el) => { el.textContent = fmtT(+el.dataset.left - Date.now() / 1000); });
  const reload = async () => { d = await api(base); render(); };

  // --- setting a game up
  const openSetup = (game) => {
    const f = { game, when: "now", at: "", center: null, radius: game === "treasure" ? 150 : 40, spot: null, target: null, place_target: false,
      hide_secs: 60, minutes: game === "treasure" ? 15 : game === "archery" ? 10 : 6, seeker: "", no_dig: true, marco: true, infect: true,
      mode: "bullseye", word: "HORSE", give_bow: true, hint_after: 5, items: [], prize: null, hot: false, hot_bonus: 2, hot_far: 40, hot_on: 45, hot_off: 20,
      underwater: false, g: { on: false, spot: null, r: 4 }, layers: 1, best_of: 3, teams: false, snowballs: true, shrink: true, shrink_after: 60 };
    if (game === "spleef") f.radius = 10;
    const at = (() => { const t = new Date(Date.now() + 15 * 60e3); t.setSeconds(0, 0); return new Date(t.getTime() - t.getTimezoneOffset() * 60e3).toISOString().slice(0, 16); })();
    f.at = at;
    let map = null;
    const pickBtn = (p, empty) => (p ? `${itemIcon({ id: p.item })}<span>${p.count} × ${esc(p.name)}</span>` : `<span class="muted">${empty}</span>`);
    const where = () => (game === "archery"
      ? `<div class="gm-where"><span class="lbl">Target</span>
          <div class="btn-row"><select class="input sm" id="gm-player">${online().map((n) => `<option>${esc(n)}</option>`).join("") || "<option value=''>Nobody online</option>"}</select>
            <button class="btn sm" type="button" id="gm-under">Use the target block they're standing on</button></div>
          <p class="muted small">Or click the map to have Solstone put a target there (removed afterwards).</p>
          <p class="gm-chosen" id="gm-chosen">${f.target ? `${f.place_target ? "New target at" : "🎯 Target block at"} ${Math.round(f.target.x)}, ${Math.round(f.target.y)}, ${Math.round(f.target.z)}` : "No target yet"}</p></div>`
      : `<div class="gm-where"><span class="lbl">Play area</span>
          <div class="btn-row"><select class="input sm" id="gm-player">${online().map((n) => `<option>${esc(n)}</option>`).join("") || "<option value=''>Nobody online</option>"}</select>
            <button class="btn sm" type="button" id="gm-here">Centre it where they're standing</button></div>
          <p class="muted small">Or click the map${game === "treasure" ? ". Shift-click to choose the exact treasure spot (otherwise it's random)" : ""}.</p>
          ${game === "spleef" ? `<p class="muted small">The arena is built high in the sky above this spot (well clear of anything there) and taken down afterwards.</p>` : ""}
          <label>Size: <input type="range" name="radius" min="${game === "treasure" ? 30 : game === "spleef" ? 6 : 10}" max="${game === "treasure" ? 500 : game === "spleef" ? 20 : 150}" step="${game === "spleef" ? 1 : 5}" value="${f.radius}"> <b id="gm-r">${f.radius}${game === "spleef" ? ` (${f.radius * 2 + 1} × ${f.radius * 2 + 1})` : ""}</b> blocks from the middle</label>
          <p class="gm-chosen" id="gm-chosen">${f.center ? `Middle at ${Math.round(f.center.x)}, ${Math.round(f.center.z)}${f.spot ? ` · treasure at ${Math.round(f.spot.x)}, ${Math.round(f.spot.z)}` : ""}` : "No area yet"}</p></div>`);
    const options = () => game === "hideseek" ? `
        <label>Seeker <select class="input" name="seeker"><option value="">Random</option>${online().map((n) => `<option ${f.seeker === n ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></label>
        <label>Hiding time <select class="input" name="hide_secs">${[30, 45, 60, 90, 120].map((v) => `<option value="${v}" ${f.hide_secs === v ? "selected" : ""}>${v} seconds</option>`).join("")}</select></label>
        <label>Seeking time <select class="input" name="minutes">${[3, 5, 6, 8, 10, 15].map((v) => `<option value="${v}" ${f.minutes === v ? "selected" : ""}>${v} minutes</option>`).join("")}</select></label>
        <label class="check"><input type="checkbox" name="no_dig" ${f.no_dig ? "checked" : ""}> No digging or building (Adventure mode during the game)</label>
        <label class="check"><input type="checkbox" name="marco" ${f.marco ? "checked" : ""}> Marco Polo: the seeker can type <b>marco</b> to hear roughly where everyone is</label>
        <label class="check"><input type="checkbox" name="infect" ${f.infect ? "checked" : ""}> Found hiders join the seekers (otherwise they watch)</label>`
      : game === "spleef" ? `
        <label>Floors <select class="input" name="layers">${[1, 2, 3].map((v) => `<option value="${v}" ${f.layers === v ? "selected" : ""}>${v === 1 ? "1 floor" : `${v} floors, ${5} blocks apart`}</option>`).join("")}</select></label>
        <label>Rounds <select class="input" name="best_of">${[1, 3, 5].map((v) => `<option value="${v}" ${f.best_of === v ? "selected" : ""}>${v === 1 ? "One round" : `Best of ${v}`}</option>`).join("")}</select></label>
        <label class="check"><input type="checkbox" name="teams" ${f.teams ? "checked" : ""}> Teams: red against blue, picked at random</label>
        <label class="check"><input type="checkbox" name="snowballs" ${f.snowballs ? "checked" : ""}> Snowballs: broken snow drops snowballs to knock people around with</label>
        <label class="check"><input type="checkbox" name="shrink" ${f.shrink ? "checked" : ""}> Shrinking floor: the edges start falling away after
          <select class="input sm" name="shrink_after">${[30, 60, 90, 120].map((v) => `<option value="${v}" ${f.shrink_after === v ? "selected" : ""}>${v < 60 ? `${v} seconds` : `${v / 60} minute${v > 60 ? "s" : ""}`}</option>`).join("")}</select></label>
        <p class="muted small gm-wide">Everyone online plays. Falling out lands you in a pool of water; nobody takes damage. When it's over everyone goes back to exactly where they were, and anyone offline is sent back when they next join.</p>`
      : game === "treasure" ? `
        <label>Time limit <select class="input" name="minutes">${[5, 10, 15, 20, 30].map((v) => `<option value="${v}" ${f.minutes === v ? "selected" : ""}>${v} minutes</option>`).join("")}</select></label>
        <label>Show the direction after <select class="input" name="hint_after">${[0, 2, 5, 10, 60].map((v) => `<option value="${v}" ${f.hint_after === v ? "selected" : ""}>${v === 60 ? "never" : v ? `${v} minutes` : "straight away"}</option>`).join("")}</select></label>
        <label class="check gm-wide"><input type="checkbox" name="underwater" ${f.underwater ? "checked" : ""}> It can be underwater, on the bottom of a lake or the sea (otherwise always on dry ground, never in a tree)</label>
        <div class="gm-items"><span class="lbl">In the chest</span>${f.items.map((it, i) => `<span class="chip">${itemIcon({ id: it.item })} ${it.count} × ${esc(it.name)} <button type="button" class="chip-x" data-rmitem="${i}" aria-label="Remove">×</button></span>`).join("")}
          <button type="button" class="btn sm" id="gm-additem">＋ Add treasure</button></div>`
      : `
        <label>Game <select class="input" name="mode"><option value="bullseye" ${f.mode === "bullseye" ? "selected" : ""}>Longest bullseye</option><option value="points" ${f.mode === "points" ? "selected" : ""}>Most points (aim × distance from 15 blocks; repeat hits from one spot count half)</option><option value="horse" ${f.mode === "horse" ? "selected" : ""}>HORSE (match the shot or take a letter)</option></select></label>
        ${f.mode === "points" ? `<label class="check gm-wide"><input type="checkbox" name="hot" ${f.hot ? "checked" : ""}> Hot zones: a fiery spot opens somewhere around the target for a while; hits shot from inside it score extra</label>
          ${f.hot ? `<div class="gm-row"><label>Hot zone bonus <select class="input" name="hot_bonus">${[1.5, 2, 3].map((v) => `<option value="${v}" ${f.hot_bonus === v ? "selected" : ""}>×${v}</option>`).join("")}</select></label>
          ${hotTimes(f)}
          <label>Opens up to <select class="input" name="hot_far">${[20, 30, 40, 60].map((v) => `<option value="${v}" ${f.hot_far === v ? "selected" : ""}>${v} blocks away</option>`).join("")}</select></label></div>` : ""}` : ""}
        ${f.mode === "points" ? `<p class="muted small gm-wide">Aim: an edge hit counts ×0.2, the middle rings about ×1, a dead-centre bullseye ×3. Distance: nothing under 15 blocks, ×1 at 15, ×2 at 25, ×4 at 35, ×14 at 65. Each further hit from within 3 blocks of an earlier one counts half, so moving around pays. Bullseyes from 30, 45 and 60+ blocks get Great, Amazing and Legendary in chat.</p>` : ""}
        ${f.mode === "horse" ? `<label>Word <input class="input" name="word" maxlength="10" value="${esc(f.word)}"></label>` : ""}
        <label>Time limit <select class="input" name="minutes">${[5, 10, 15, 20, 30, 45].map((v) => `<option value="${v}" ${f.minutes === v ? "selected" : ""}>${v} minutes</option>`).join("")}</select></label>
        <label class="check"><input type="checkbox" name="give_bow" ${f.give_bow ? "checked" : ""}> Give everyone a Match Bow (Infinity, one arrow; both taken back at the end, nobody's own bows or arrows touched)</label>`;
    const body = () => `<h2>${GAME_INFO[game][0]} ${esc(GAME_INFO[game][1])}</h2>
      <form id="gm-form" class="gm-form">
        <div class="gm-map" id="gm-map"></div>
        ${where()}
        <div class="gm-opts">${options()}</div>
        ${game === "archery" || game === "treasure" ? gatherHtml(f.g, online()) : game === "hideseek" ? `<p class="muted small">Everyone is brought to the middle of the area when it starts, and back to where they were when it's over.</p>` : ""}
        ${game !== "treasure" ? `<div class="gm-prize"><span class="lbl">Prize for the winner${game === "hideseek" ? "s" : ""}</span><button type="button" class="btn ch-pick" id="gm-prize">${pickBtn(f.prize, "Optional")}</button></div>` : ""}
        <div class="ch-when"><span class="lbl">When</span>
          <label class="check"><input type="radio" name="when" value="now" ${f.when === "now" ? "checked" : ""}> Right now</label>
          <label class="check"><input type="radio" name="when" value="later" ${f.when === "later" ? "checked" : ""}> At <input class="input sm" type="datetime-local" name="at" value="${esc(f.at)}"></label></div>
        <div class="actions"><button type="button" class="btn" data-close-modal>Cancel</button><button class="btn primary" type="submit">Start</button></div>
      </form>`;
    const sync = (m) => {
      const fm = $("#gm-form", m);
      for (const k of ["seeker", "mode", "word"]) if (fm[k]) f[k] = fm[k].value;
      for (const k of ["hide_secs", "minutes", "hint_after", "radius", "hot_bonus", "hot_far", "hot_on", "hot_off", "layers", "best_of", "shrink_after"]) if (fm[k]) f[k] = +fm[k].value;
      for (const k of ["no_dig", "marco", "infect", "give_bow", "hot", "teams", "snowballs", "shrink", "underwater"]) if (fm[k]) f[k] = fm[k].checked;
      f.when = fm.when.value; f.at = fm.at.value;
    };
    const show = () => openModal(body(), (m) => {
      m.classList.add("gm-modal");
      map = worldMapCanvas($("#gm-map", m), sid, {
        center: f.center || f.target || d.spawn || { x: 0, z: 0 }, scale: game === "treasure" ? 0.5 : game === "spleef" ? 3 : 1,
        overlay: (ctx, toScreen, view) => {
          if (f.center) {
            const [x, y] = toScreen(f.center.x, f.center.z);
            ctx.strokeStyle = "#f2c14e"; ctx.lineWidth = 2; ctx.setLineDash([6, 5]); ctx.beginPath();
            if (game === "spleef") ctx.rect(x - (f.radius + 0.5) * view.scale, y - (f.radius + 0.5) * view.scale, (f.radius * 2 + 1) * view.scale, (f.radius * 2 + 1) * view.scale);
            else ctx.arc(x, y, f.radius * view.scale, 0, Math.PI * 2);
            ctx.stroke(); ctx.setLineDash([]);
            ctx.fillStyle = "#f2c14e"; ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
          }
          if (f.target && f.mode === "points" && f.hot) {         // where hot zones can open
            const [x, y] = toScreen(f.target.x, f.target.z);
            ctx.fillStyle = "rgba(255, 110, 40, .16)"; ctx.beginPath(); ctx.arc(x, y, f.hot_far * view.scale, 0, Math.PI * 2); ctx.arc(x, y, 10 * view.scale, 0, Math.PI * 2, true); ctx.fill();
          }
          for (const [p, c] of [[f.spot, "#ffd84a"], [f.target, "#e0503f"]]) {
            if (!p) continue;
            const [x, y] = toScreen(p.x, p.z);
            ctx.fillStyle = c; ctx.strokeStyle = "#000"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
          }
        },
        onClick: async (x, z) => {
          sync(m);
          const spot = await api(`/api/servers/${encodeURIComponent(sid)}/races/spot?x=${x}&z=${z}`).catch(() => ({ x, y: 64, z }));
          if (game === "archery") { f.target = spot; f.place_target = true; }
          else if (game === "treasure" && clickShift && f.center) f.spot = spot;
          else { f.center = spot; f.spot = null; }
          show();
        },
      });
      let clickShift = false;
      $("#gm-map", m).addEventListener("pointerdown", (e) => { clickShift = e.shiftKey; }, true);
      const fm = $("#gm-form", m);
      fm.radius?.addEventListener("input", () => { f.radius = +fm.radius.value; $("#gm-r", m).textContent = game === "spleef" ? `${f.radius} (${f.radius * 2 + 1} × ${f.radius * 2 + 1})` : f.radius; map.draw(); });
      for (const k of ["hot", "hot_bonus", "hot_far", "hot_on", "hot_off"]) fm[k]?.addEventListener("change", () => { sync(m); show(); });
      fm.mode?.addEventListener("change", () => { sync(m); if (f.mode === "horse" && f.minutes < 30) f.minutes = 30; show(); });
      $("#gm-here", m)?.addEventListener("click", async () => {
        sync(m);
        try { f.center = await api(`/api/servers/${encodeURIComponent(sid)}/races/spot?player=${encodeURIComponent($("#gm-player", m).value)}`); f.spot = null; show(); } catch (e) { showToast(esc(e.message), 4000); }
      });
      $("#gm-under", m)?.addEventListener("click", async () => {
        sync(m);
        try {
          const t = await api(`${base}/target?player=${encodeURIComponent($("#gm-player", m).value)}`);
          if (!t.is_target) { showToast("That isn't a target block. Stand right on top of it and try again", 4000); return; }
          f.target = t; f.place_target = false; show();
        } catch (e) { showToast(esc(e.message), 4000); }
      });
      const pickItem = (title, then) => { sync(m); openGiveItem(sid, "", { title, pick: (item, count) => { then({ item: item.id, count, name: item.name }); show(); } }); };
      wireGather(m, sid, f.g, () => { sync(m); show(); }, f.target || f.center || d.spawn);
      $("#gm-prize", m)?.addEventListener("click", () => pickItem("Prize for the winner", (p) => { f.prize = p; }));
      $("#gm-additem", m)?.addEventListener("click", () => pickItem("Treasure for the chest", (p) => { f.items.push(p); }));
      m.querySelectorAll("[data-rmitem]").forEach((b) => b.addEventListener("click", () => { sync(m); f.items.splice(+b.dataset.rmitem, 1); show(); }));
      fm.addEventListener("submit", async (e) => {
        e.preventDefault(); sync(m);
        if (game === "archery" ? !f.target : !f.center) { showToast(game === "archery" ? "Choose the target first" : "Choose the play area first", 3000); return; }
        if (game === "treasure" && !f.items.length) { showToast("Put something in the treasure chest", 3000); return; }
        if (f.g.on && !f.g.spot) { showToast("Pick the spot to teleport everyone to (or untick teleporting)", 3000); return; }
        const start = f.when === "now" ? Date.now() / 1000 : new Date(f.at).getTime() / 1000;
        try {
          await post(base, { ...f, start, prizes: f.prize ? [f.prize] : [], gather: gatherBody(f.g) });
          closeModal(); showToast(f.when === "now" ? `${GAME_INFO[game][1]} is starting` : "Scheduled", 3000); await reload();
        } catch (err) { showToast(esc(err.message), 4000); }
      });
    });
    show();
  };

  render();
  every(1000, tickLeft);
  every(2000, async () => {
    if ($(".modal")) return;
    if (!d.runs.some((r) => ["countdown", "hiding", "running"].includes(r.state) || (r.state === "scheduled" && r.start - Date.now() / 1000 < 20))) return;
    await reload();
  });
}

// ================================================================ compatibility check
// One button: try every kind of command and file Solstone relies on, on this server. For after
// a Minecraft update (on a copy of the server first, ideally).
async function viewCheck(sid) {
  if (!isAdmin()) { location.replace(`#/s/${encodeURIComponent(sid)}`); return; }
  const s = await serverFrame(sid, "check");
  let d = await api(`/api/servers/${encodeURIComponent(sid)}/check`), busy = false;
  const render = () => {
    const last = d.last, rows = last?.rows || [];
    const bad = rows.filter((r) => r.ok === false).length, good = rows.filter((r) => r.ok === true).length, skip = rows.filter((r) => r.ok === null).length;
    const areas = [...new Set(rows.map((r) => r.area))];
    const row = (r) => `<li class="ck-row ${r.ok === false ? "bad" : r.ok ? "ok" : "skip"}">
        <span class="ck-mark" aria-label="${r.ok === false ? "Problem" : r.ok ? "Works" : "Not checked"}">${r.ok === false ? "✘" : r.ok ? "✔" : "–"}</span>
        <div class="ck-main"><b>${esc(r.label)}</b>${r.used_by ? `<span class="muted small">Used by: ${esc(r.used_by)}</span>` : ""}
          ${r.ok === false && r.fix ? `<span class="ck-fix small">${esc(r.fix)}</span>` : ""}
          ${r.detail ? `<details ${r.ok === false ? "open" : ""}><summary class="small muted">${r.ok === false ? "What the game said" : "Details"}</summary><pre class="mc-out">${esc(r.detail)}</pre></details>` : ""}</div></li>`;
    setView(`${serverHeader(s, "check")}
      <section class="section"><div class="section-head"><h2>Compatibility check</h2></div>
        <div class="panel ck-intro"><p>Tries, on this server, every kind of command and file Solstone relies on: scoreboards, boss bars, titles, floating markers, locator-bar dots,
          holding racers still, teleporting, building blocks, special items, the data pack's fish, archery and spleef, and reading the map and player files.
          Run it after every Minecraft update, ideally on a copy of the server before updating the real one.</p>
          <p class="muted small">Harmless: messages go to nobody, and the blocks and entities it makes for a moment high above spawn are removed. Takes about ten seconds.</p>
          <div class="btn-row"><button class="btn primary" type="button" id="ck-run" ${busy || !d.rcon ? "disabled" : ""}>${busy ? "Checking…" : "▶ Run the check"}</button>
            ${!d.rcon ? `<span class="notice small">RCON is off for this server.</span>` : ""}
            ${last ? `<span class="muted small">Last run ${esc(fmtAgo(last.at))} on Minecraft ${esc(last.version || "?")}${last.version !== d.version && d.version ? ` · <b>the server is now on ${esc(d.version)}: run it again</b>` : ""}</span>` : ""}</div></div></section>
      ${last ? `<section class="section"><div class="ck-summary ${bad ? "bad" : "ok"}">${bad ? `✘ <b>${bad}</b> ${bad === 1 ? "thing doesn't" : "things don't"} work` : "✔ <b>Everything works</b>"}
          <span class="muted">· ${good} working${skip ? ` · ${skip} not checked` : ""}</span></div>
        ${bad ? `<p class="muted small">Send the red lines (with what the game said) to get them fixed.</p>` : ""}
        ${areas.map((a) => `<h3 class="ck-area">${esc(a)}</h3><ul class="ck-list panel">${rows.filter((r) => r.area === a).map(row).join("")}</ul>`).join("")}</section>` : ""}`);
    wireHeader(s);
    $("#ck-run")?.addEventListener("click", async () => {
      busy = true; render();
      try { d.last = await post(`/api/servers/${encodeURIComponent(sid)}/check`, {}); d.version = d.last.version; }
      catch (err) { showToast(esc(err.message), 5000); }
      busy = false; render();
    });
  };
  render();
}

// ================================================================ fishing journal
// Every species each player has caught (with their best), family records, the latest catches.
const FQ = ["gray", "white", "green", "aqua", "gold", "light_purple"];
async function viewFishingJournal(sid, who) {
  const s = await serverFrame(sid, "fishing");
  const d = await api(`/api/servers/${encodeURIComponent(sid)}/fishing/journal`);
  if (d.source === "tide") return viewTideFishing(s, sid, d, who);
  const qName = (i) => d.qualities[i]?.name || "";
  let pick = who && d.players.find((p) => p.name === who) ? who : d.players[0]?.name || "";
  const render = () => {
    const p = d.players.find((x) => x.name === pick);
    const total = d.species.length, have = p ? Object.keys(p.species).length : 0;
    const card = (sp) => {
      const mine = p?.species[sp.key], rec = d.records[sp.key];
      const where = `${sp.waters.join(", ")} · ${sp.rarity}`;
      return mine
        ? `<div class="fj-card got"><div class="fj-top">${itemIcon({ id: sp.item })}<b>${esc(sp.name)}</b></div>
            <span class="fj-best">Best <b>${mine.best_lb} lb</b> · <span class="fq-${FQ[mine.best_quality]}">${esc(mine.best_quality === 1 ? "Normal" : qName(mine.best_quality))}</span></span>
            <span class="muted small">Caught ${mine.count}× · ${esc(where)}</span>
            ${rec ? `<span class="small ${rec.player === pick ? "fj-mine" : "muted"}">${rec.player === pick ? "🏆 Family record" : `Record: ${rec.lb} lb by ${esc(rec.player)}`}${rec.player === pick ? `: ${rec.lb} lb` : ""}</span>` : ""}</div>`
        : `<div class="fj-card"><div class="fj-top"><span class="fj-unknown" aria-hidden="true">?</span><b class="muted">???</b></div>
            <span class="muted small">Not caught yet</span><span class="muted small">Look in: ${esc(where)}</span>
            ${rec ? `<span class="muted small">${esc(rec.player)} has caught one</span>` : ""}</div>`;
    };
    setView(`${serverHeader(s, "fishing")}
      <section class="section"><div class="section-head"><h2>🎣 Fishing journal</h2><span class="muted">Every fish from the Solstone data pack</span></div>
        ${d.players.length ? `<div class="fj-players">${d.players.map((x) => `<button type="button" class="chip-btn ${x.name === pick ? "on" : ""}" data-fj="${esc(x.name)}">${faceHtml({ name: x.name }, 20)} ${esc(x.name)} <small>${Object.keys(x.species).length}/${total}</small></button>`).join("")}</div>` : `<p class="muted">Nobody has caught a Solstone fish yet.</p>`}
        ${p ? `<div class="panel fj-head">
            <div class="fj-progress"><span><b>${have} of ${total}</b> kinds of fish</span><div class="fj-bar"><i style="width:${(have / total) * 100}%"></i></div></div>
            <div class="fj-stats"><span><b>${p.total}</b> caught</span><span><b>${p.points.toLocaleString()}</b> points</span></div>
            <div class="fish-qs">${d.qualities.map((q, i) => `<span class="fish-q fq-${q.color}" title="1 in ${q.one_in} catches">${esc(q.name)} <small>${p.qualities[i] || 0}</small></span>`).join("")}</div></div>` : ""}
        <div class="fj-grid">${d.species.map(card).join("")}</div></section>
      ${d.recent.length ? `<section class="section"><div class="section-head"><h2>Latest catches</h2></div><ul class="panel fj-recent">${d.recent.map((c) => `<li>${faceHtml({ name: c.player }, 20)}<b>${esc(c.player)}</b>
          <span class="fq-${FQ[c.quality]}">${esc(c.quality === 1 ? "" : `${qName(c.quality)} `)}${esc(c.name)}</span><span class="muted small">${c.lb} lb · ${c.points} pts · ${esc(fmtAgo(c.ts))}</span></li>`).join("")}</ul></section>` : ""}
      <section class="section"><div class="section-head"><h2>How rare</h2></div><div class="fish-qs">${d.qualities.map((q) => `<span class="fish-q fq-${q.color}">${esc(q.name)} <small>${q.one_in <= 2 ? `${q.chance}%` : `1 in ${q.one_in}`}</small></span>`).join("")}</div></section>`);
    wireHeader(s);
    $$("[data-fj]").forEach((b) => b.addEventListener("click", () => { pick = b.dataset.fj; render(); }));
  };
  render();
}


// ================================================================ fishing with the Tide mod
// Tide keeps its own journal per player; this shows the family's: records (hover for who),
// the top three of every fish, how much of each rarity tier has been caught, and everyone's level.
function fmtWeight(g) {
  if (!g) return "";
  const oz = g / 28.349523125;
  if (oz < 16) return `${oz < 10 ? oz.toFixed(1) : Math.round(oz)} oz`;
  let lb = Math.floor(oz / 16), rest = Math.round(oz - lb * 16);
  if (rest === 16) { lb++; rest = 0; }
  return lb >= 100 ? `${lb.toLocaleString()} lb` : `${lb} lb${rest ? ` ${rest} oz` : ""}`;
}
function fmtLength(cm) {
  if (!cm) return "";
  const inch = cm / 2.54;
  if (inch < 12) return `${inch.toFixed(1).replace(/\.0$/, "")} in`;
  const t = Math.round(inch), ft = Math.floor(t / 12), rest = t % 12;
  return rest ? `${ft} ft ${rest} in` : `${ft} ft`;
}
const qMarks = (q) => "◆".repeat(Math.max(0, q)) + "◇".repeat(Math.max(0, 5 - q));

function viewTideFishing(s, sid, d, who) {
  const QC = d.qualities.map((q) => q.color);
  const qLabel = (q) => q >= 0 ? `<span class="fq-${QC[q]}">${qMarks(q)} ${esc(d.qualities[q].name)}</span>` : "";
  const total = d.species.length;
  let pick = who && d.players.find((p) => p.name === who) ? who : "";
  const stars = (n) => `<span class="tf-stars" title="${n} star rarity">${"★".repeat(n)}</span>`;
  const size = (e) => [fmtWeight(e.weight_g), fmtLength(e.length_cm)].filter(Boolean).join(" · ");

  const familyCard = (sp) => {
    const rec = d.records[sp.id], top = d.top[sp.id] || [];
    if (!rec) return `<div class="fj-card"><div class="fj-top fj-dark">${itemIcon({ id: sp.id })}<b class="muted">${esc(sp.name)}</b>${stars(sp.stars)}</div>
        <span class="muted small">Nobody has caught one yet</span>${sp.where ? `<span class="muted small">Look in: ${esc(sp.where)}</span>` : ""}</div>`;
    return `<div class="fj-card got"><div class="fj-top">${itemIcon({ id: sp.id })}<b>${esc(sp.name)}</b>${stars(sp.stars)}</div>
        <span class="fj-best" title="Family record, caught by ${esc(rec.player)}${rec.quality >= 0 ? ` · ${esc(d.qualities[rec.quality].name)}` : ""}">🏆 <b>${esc(size(rec) || `${rec.count} caught`)}</b> <span class="muted small">${esc(rec.player)}</span></span>
        <ol class="tf-top">${top.map((e, i) => `<li title="${esc(e.player)}: ${esc(size(e))}${e.quality >= 0 ? ` · best quality ${esc(d.qualities[e.quality].name)}` : ""} · ${e.count} caught">
          <span class="rank">${i + 1}</span>${faceHtml({ name: e.player, uuid: e.uuid }, 16)}<span>${esc(e.player)}</span><span class="muted small">${esc(fmtWeight(e.weight_g) || fmtLength(e.length_cm))}</span></li>`).join("")}</ol></div>`;
  };
  const playerCard = (p) => (sp) => {
    const mine = p.species[sp.id], rec = d.records[sp.id];
    const recLine = rec ? (rec.player === p.name ? `<span class="small fj-mine">🏆 Family record</span>`
      : `<span class="small muted" title="${esc(size(rec))}">Record: ${esc(fmtWeight(rec.weight_g) || fmtLength(rec.length_cm))} by ${esc(rec.player)}</span>`) : "";
    if (!mine) return `<div class="fj-card"><div class="fj-top fj-dark">${itemIcon({ id: sp.id })}<b class="muted">${esc(sp.name)}</b>${stars(sp.stars)}</div>
        <span class="muted small">Not caught yet${sp.where ? ` · ${esc(sp.where)}` : ""}</span>${recLine}</div>`;
    const bits = [mine.heaviest_g && `Heaviest <b>${esc(fmtWeight(mine.heaviest_g))}</b>`, mine.longest_cm && `Longest <b>${esc(fmtLength(mine.longest_cm))}</b>`,
      mine.shortest_cm && `Shortest <b>${esc(fmtLength(mine.shortest_cm))}</b>`].filter(Boolean);
    return `<div class="fj-card got"><div class="fj-top">${itemIcon({ id: sp.id })}<b>${esc(sp.name)}</b>${stars(sp.stars)}</div>
        <span class="small">Caught <b>${mine.count}×</b>${mine.best_quality >= 0 ? ` · best ${qLabel(mine.best_quality)}` : ""}</span>
        ${bits.length ? `<span class="small">${bits.join(" · ")}</span>` : ""}${recLine}</div>`;
  };

  const render = () => {
    const p = d.players.find((x) => x.name === pick);
    const card = p ? playerCard(p) : familyCard;
    const have = p ? Object.keys(p.species).length : d.family_species;
    const head = p
      ? `<div class="panel fj-head">
          <div class="tf-level">${faceHtml(p, 40)}<div><b class="tf-lv">Fishing level ${p.level}</b> <span class="muted">${esc(p.title)}</span>${p.fair ? ' <span class="fish-q fq-gold">Fair play</span>' : ""}
            <div class="fj-bar" title="${p.next == null ? "Max level" : `${p.next.toLocaleString()} XP to level ${p.level + 1}`}"><i style="width:${p.progress * 100}%"></i></div>
            <span class="muted small">${p.xp.toLocaleString()} XP${p.next == null ? " · max level" : ` · ${p.next.toLocaleString()} to level ${p.level + 1}`}</span></div></div>
          <div class="fj-progress"><span><b>${have} of ${total}</b> kinds of fish · <b>${p.caught.toLocaleString()}</b> caught</span><div class="fj-bar"><i style="width:${(have / Math.max(1, total)) * 100}%"></i></div></div>
          <div class="fish-qs">${d.qualities.map((q, i) => `<span class="fish-q fq-${q.color}">${qMarks(i)} ${esc(q.name)} <small>${p.qualities[i] || 0}</small></span>`).join("")}</div></div>`
      : `<div class="panel fj-head">
          <div class="fj-progress"><span>The family has caught <b>${have} of ${total}</b> kinds of fish</span><div class="fj-bar"><i style="width:${(have / Math.max(1, total)) * 100}%"></i></div></div>
          <div class="tf-tiers">${d.tiers.map((t) => `<div class="tf-tier ${t.family === t.total ? "done" : ""}" title="${esc(Object.entries(t.players).map(([n, c]) => `${n}: ${c}/${t.total}`).join("\n"))}">
            <span>${esc(t.label)} <span class="tf-stars">${"★".repeat(t.stars)}</span></span><b>${t.family === t.total ? "✓ All caught!" : `${t.family} / ${t.total}`}</b>
            <div class="fj-bar"><i style="width:${(t.family / t.total) * 100}%"></i></div></div>`).join("")}</div></div>`;
    const anglers = !p && d.players.length ? `<section class="section"><div class="section-head"><h2>Anglers</h2>${d.levels_on ? "" : '<span class="muted">Levels are switched off on this server</span>'}</div>
        <ol class="panel tf-anglers">${d.players.map((x) => `<li><button type="button" class="linkish" data-fj="${esc(x.name)}">${faceHtml(x, 24)}<b>${esc(x.name)}</b></button>
          <span class="tf-lvl">Lv <b>${x.level}</b></span><span class="muted">${esc(x.title)}</span>
          <div class="fj-bar" title="${x.xp.toLocaleString()} XP"><i style="width:${x.progress * 100}%"></i></div>
          <span class="muted small">${Object.keys(x.species).length}/${total} fish · ${x.caught.toLocaleString()} caught</span></li>`).join("")}</ol></section>` : "";
    const groups = d.groups.map((g) => {
      const list = d.species.filter((sp) => sp.group === g.key);
      if (!list.length) return "";
      const got = list.filter((sp) => p ? p.species[sp.id] : d.records[sp.id]).length;
      return `<h3 class="tf-group">${esc(g.label)} <span class="muted small">${got} / ${list.length}</span></h3><div class="fj-grid">${list.map(card).join("")}</div>`;
    }).join("");
    setView(`${serverHeader(s, "fishing")}
      <section class="section"><div class="section-head"><h2>🎣 Fishing</h2><span class="muted">From the Tide fishing mod</span></div>
        <div class="fj-players"><button type="button" class="chip-btn ${!p ? "on" : ""}" data-fj="">👪 Family</button>${d.players.map((x) => `<button type="button" class="chip-btn ${x.name === pick ? "on" : ""}" data-fj="${esc(x.name)}">${faceHtml(x, 20)} ${esc(x.name)} <small>Lv ${x.level}</small></button>`).join("")}</div>
        ${d.players.length ? "" : `<p class="muted">Nobody has caught anything with Tide yet.</p>`}
        ${head}</section>
      ${anglers}
      <section class="section"><div class="section-head"><h2>${p ? `${esc(p.name)}'s journal` : "Family records"}</h2><span class="muted">${p ? "Their best of every fish" : "Hover a record to see who caught it"}</span></div>${groups}</section>
      ${d.recent.length ? `<section class="section"><div class="section-head"><h2>Latest catches</h2></div><ul class="panel fj-recent">${d.recent.map((c) => `<li>${faceHtml({ name: c.player }, 20)}<b>${esc(c.player)}</b>
          ${itemIcon({ id: c.species })}<span class="fq-${QC[c.quality]}">${esc(c.quality === 1 ? "" : `${c.quality_name} `)}${esc(c.name)}</span><span class="muted small">${esc(fmtWeight(c.weight_g))} · ${c.points} pts · ${esc(fmtAgo(c.ts))}</span></li>`).join("")}</ul></section>` : ""}
      <section class="section"><div class="section-head"><h2>Catch quality</h2><span class="muted">At level ${d.baseline} with a normal hook; higher levels and better hooks improve them</span></div>
        <div class="fish-qs">${d.qualities.map((q, i) => `<span class="fish-q fq-${q.color}">${qMarks(i)} ${esc(q.name)} <small>${q.chance >= 1 ? `${q.chance}%` : `1 in ${Math.round(100 / q.chance).toLocaleString()}`}</small></span>`).join("")}</div></section>`);
    wireHeader(s);
    $$("[data-fj]").forEach((b) => b.addEventListener("click", () => { pick = b.dataset.fj; render(); window.scrollTo({ top: 0 }); }));
  };
  render();
}
