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
    const icon = { join: "→", leave: "←", death: "☠", advancement: "★", challenge: "🏆", race: "🏁", fish: "🎣", bigfish: "🐟" }[e.type] || "•";
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
  const fishOn = () => !!fish?.status?.version;
  const draft = { kind: "fish", name: "", when: "now", at: "", minutes: 10, prize: null, second: null, say: true };
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
    const show = (n, v) => (c.kind === "fish_heaviest" ? `${v / 10} lb${c.best?.[n] ? ` · ${esc(c.best[n].name)}` : ""}` : c.kind === "fish_points" ? `${v} pts` : v);
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
      <div class="ch-kinds" role="radiogroup" aria-label="What counts">${d.kinds.filter((k) => !["jumps", "walk"].includes(k.key) || draft.kind === k.key).map((k) => {
        const off = k.pack && !fishOn();
        const what = k.key === "fish_points" ? "most points (needs the fishing pack)" : k.key === "fish_heaviest" ? "heaviest fish (needs the fishing pack)" : `most ${k.unit}`;
        return `<label class="ch-kind ${draft.kind === k.key ? "on" : ""} ${off ? "off" : ""}" ${off ? 'title="Add the Solstone Fishing pack to the world first (below)"' : ""}><input type="radio" name="kind" value="${k.key}" ${draft.kind === k.key ? "checked" : ""} ${off ? "disabled" : ""}><span>${k.emoji}</span><b>${esc(k.label)}</b><small>${esc(off ? what : what.replace(" (needs the fishing pack)", ""))}</small></label>`;
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
      <label class="check"><input type="checkbox" name="say" ${draft.say ? "checked" : ""}> Announce it in the game (start, last minute, winner) and show the scores on everyone's screen</label>
      ${d.rcon ? "" : `<p class="notice">This server needs RCON turned on for challenges (⚙ settings).</p>`}
      <div class="btn-row"><button class="btn primary" type="submit" ${d.rcon ? "" : "disabled"}>${draft.when === "now" ? "Start the challenge" : "Schedule it"}</button></div>
    </form>`;
  const render = () => {
    const live = d.items.filter((c) => c.state === "running"), soon = d.items.filter((c) => c.state === "scheduled"), past = d.items.filter((c) => !["running", "scheduled"].includes(c.state));
    setView(serverHeader(s, "challenges") + playSwitch(sid, "contests") + `
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
      : `<ol class="fish-steps"><li><a class="btn sm" href="/api/fishing/${esc(st.file)}" download>⬇ Download ${esc(st.file)}</a></li>
          <li>Put the file (still zipped) in this world's <code>datapacks</code> folder: <code>${esc(st.folder.replace(/^\/servers\//, "…/crafty-4/servers/"))}</code></li>
          <li><button class="btn sm primary" type="button" data-fish="reload">Load it</button> <span class="muted small">(runs /reload in the game and checks)</span></li></ol>`;
    const q = fish.qualities.map((x) => `<span class="fish-q fq-${x.color}">${esc(x.name)} <small>${x.chance}%</small></span>`).join("");
    const rows = fish.guide.map((g) => `<tr><td>${itemIcon({ id: g.item })}<b>${esc(g.name)}</b></td><td>${esc(g.waters.join(", "))}</td><td>${g.min_lb}–${g.max_lb} lb</td><td>${g.min_points}–${g.max_points}</td><td class="muted">${esc(g.rarity)}</td></tr>`).join("");
    return `<section class="section" id="fish-sec"><div class="section-head"><h2>🎣 Solstone Fishing</h2><span class="muted">${on ? `In the world${old ? " (an update is ready)" : " ✓"}` : "Not in this world yet"}</span></div>
      <div class="panel fish-panel">
        <p>A data pack that makes every catch a species with a weight and a quality: <b>${fish.guide.length} kinds of fish</b> that depend on where you cast (rivers and lakes, oceans, warm or cold water, swamps, jungle rivers, the deep ocean). It unlocks the <b>Fishing tournament</b> (most points) and <b>Biggest catch</b> contests, and Prime and Exquisite catches are announced to everyone.</p>
        ${!fish.rcon ? `<p class="notice">Needs RCON turned on for this server.</p>` : on && !old ? `<p class="muted small">Loaded (version ${st.version}). <button class="link-btn" type="button" data-fish="reload">Reload</button></p>` : steps}
        ${old && !st.writable ? `<p class="muted small">Replace the old file with the new download, then load it.</p>` : ""}
        ${st.error ? `<p class="notice small">${esc(st.error)}</p>` : ""}
        <div class="fish-qs">${q}</div>
        <details class="fish-guide"><summary>Fish guide</summary><div class="table-wrap"><table class="data"><thead><tr><th>Fish</th><th>Where</th><th>Size</th><th>Points</th><th>How often</th></tr></thead><tbody>${rows}</tbody></table></div></details>
        ${fish.recent.length ? `<h3>Recent catches</h3><ul class="fish-recent">${fish.recent.slice(0, 8).map((e) => `<li>${e.player ? faceHtml({ name: e.player }, 20) : ""}<span>${esc(e.message)}</span><time class="muted small">${esc(fmtAgo(e.ts))}</time></li>`).join("")}</ul>` : ""}
      </div></section>`;
  };
  const wireFish = () => $$("[data-fish]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      const r = await post(`/api/servers/${encodeURIComponent(sid)}/fishing/${b.dataset.fish}`, {});
      showToast(r.version ? `Solstone Fishing is loaded (version ${r.version})` : r.listed === false ? "The game didn't load it. Is the file in the world's datapacks folder?" : "Reloaded, but the pack didn't start. Check the server log for errors.", 5000);
      fish = await api(`/api/servers/${encodeURIComponent(sid)}/fishing`); render();
    } catch (e) { showToast(esc(e.message), 5000); b.disabled = false; }
  }));
  const wire = () => {
    const form = $("#ch-form");
    const sync = () => { const f = new FormData(form); draft.kind = f.get("kind"); draft.name = f.get("name"); draft.minutes = +f.get("minutes"); draft.when = f.get("when"); draft.at = f.get("at"); draft.say = !!f.get("say"); };
    form.addEventListener("change", (e) => {
      sync();
      if (e.target.name === "kind") { form.querySelectorAll(".ch-kind").forEach((l) => l.classList.toggle("on", l.querySelector("input").checked)); form.name.placeholder = kind(draft.kind).label; }
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
    form.addEventListener("submit", async (e) => {
      e.preventDefault(); sync();
      if (!draft.prize) { showToast("Choose a prize for the winner first", 2500); return; }
      const start = draft.when === "now" ? Date.now() / 1000 : new Date(draft.at).getTime() / 1000;
      try {
        const c = await post(base, { kind: draft.kind, name: draft.name, start, minutes: draft.minutes, say: draft.say,
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
        Object.assign(draft, { kind: c.kind, name: c.name, minutes: c.minutes, say: c.say, when: "now",
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

// Contests and races share the Challenges tab.
function playSwitch(sid, on) {
  const base = `#/s/${encodeURIComponent(sid)}/challenges`;
  return `<nav class="seg play-switch" aria-label="Kind of challenge"><a href="${base}" ${on === "contests" ? 'aria-current="page"' : ""}>🏆 Contests</a><a href="${base}/races" ${on === "races" ? 'aria-current="page"' : ""}>🏁 Races</a></nav>`;
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
    setView(serverHeader(s, "challenges") + playSwitch(sid, "races") + `
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
        <label class="check"><input type="checkbox" name="teleport" checked> Teleport everyone to the start line first</label>
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
