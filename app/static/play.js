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
    const icon = { join: "→", leave: "←", death: "☠", advancement: "★", challenge: "🏆" }[e.type] || "•";
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
  let d = await api(base);
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
    return `<ol class="ch-scores">${rows.map(([n, v], i) => `<li class="${(c.winners || []).includes(n) ? "win" : ""}"><span class="rank">${i + 1}</span>${faceHtml({ name: n }, 22)}<b>${esc(n)}</b><span class="val">${v}</span></li>`).join("")}</ol>`;
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
      <div class="ch-kinds" role="radiogroup" aria-label="What counts">${d.kinds.map((k) => `<label class="ch-kind ${draft.kind === k.key ? "on" : ""}"><input type="radio" name="kind" value="${k.key}" ${draft.kind === k.key ? "checked" : ""}><span>${k.emoji}</span><b>${esc(k.label)}</b><small>most ${esc(k.unit)}</small></label>`).join("")}</div>
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
    setView(serverHeader(s, "challenges") + `
      <p class="muted ch-intro">Timed contests for whoever's playing. The game counts the score live and shows it on everyone's screen; the winner gets the prize straight away, or the next time they join.</p>
      ${live.length ? `<section class="section"><div class="section-head"><h2>Happening now</h2></div><div class="ch-list">${live.map(card).join("")}</div></section>` : ""}
      <section class="section">${formHtml()}</section>
      ${soon.length ? `<section class="section"><div class="section-head"><h2>Coming up</h2></div><div class="ch-list">${soon.map(card).join("")}</div></section>` : ""}
      ${d.gifts.length ? `<section class="section"><div class="section-head"><h2>Prizes waiting</h2><span class="muted">Given the next time they join</span></div><div class="panel">${d.gifts.map((g) => `<div class="ch-gift">${faceHtml({ name: g.player }, 22)}<b>${esc(g.player)}</b> ${itemIcon({ id: g.item })} ${g.count} × ${esc(itemName({ id: g.item }))} <span class="muted small">for: ${esc(g.why)}</span></div>`).join("")}</div></section>` : ""}
      ${past.length ? `<section class="section"><div class="section-head"><h2>Finished</h2></div><div class="ch-list">${past.map(card).join("")}</div></section>` : ""}`);
    wireHeader(s);
    wire();
  };
  const reload = async () => { d = await api(base); render(); };
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
