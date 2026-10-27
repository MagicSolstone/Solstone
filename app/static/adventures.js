// ================================================================ Adventures: replays of play sessions
// The list: each play session (anyone on), newest first, with who played and any saved title. Open one to replay
// it on the world map: everyone's trail up to the moment on the timeline, faces where they are, and the feed
// (joins, chat, deaths, advancements, fish, kills and ores from the game's statistics) beside it. Save it with a
// title and a note to keep it (and its trail) for good.

const ADV_COLOURS = ["#ffcf4a", "#5ac8ff", "#ff7a7a", "#8ce99a", "#d0a2ff", "#ffa94d", "#63e6be", "#f783ac"];
const ADV_ICONS = { join: "➡️", leave: "⬅️", chat: "💬", webchat: "💬", death: "💀", advancement: "🏅", challenge: "🏆", race: "🏁",
  fish: "🎣", bigfish: "🐟", game: "🎲", progress: "⚔️" };

function advDay(ts) {
  return new Date(ts * 1000).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}
function advClock(ts) {
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
function advLength(sec) {
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

async function viewAdventures(sid, which) {
  if (which) return viewAdventure(sid, which);
  const s = await serverFrame(sid, "adventures");
  setView(serverHeader(s, "adventures") + `<section class="section"><p class="muted">Loading…</p></section>`);
  wireHeader(s);
  const d = await api(`/api/servers/${encodeURIComponent(sid)}/adventures?days=60`);
  let showHidden = false;
  const row = (x) => {
    const saved = x.saved[0];
    const key = saved ? `a${saved.id}` : `${Math.floor(x.start)}-${Math.ceil(x.end)}`;
    return `<li class="${x.hidden ? "rp-hidden" : ""}"><a class="rp-row" href="#/s/${encodeURIComponent(sid)}/adventures/${key}">
      <span class="rp-when"><b>${esc(saved ? saved.title : advDay(x.start))}</b>
        <span class="muted small">${saved ? `${esc(advDay(x.start))} · ` : ""}${esc(advClock(x.start))}–${esc(advClock(x.end))} · ${esc(advLength(x.end - x.start))}</span></span>
      <span class="rp-faces">${x.players.slice(0, 8).map((n) => faceHtml({ name: n }, 22)).join("")}${x.players.length > 8 ? `<small>+${x.players.length - 8}</small>` : ""}</span>
      ${saved ? '<span class="rp-saved" title="Saved">★</span>' : ""}</a>
      ${saved ? "" : `<button type="button" class="icon-btn rp-hide" data-hide="${x.start}:${x.end}:${x.hidden ? 0 : 1}" title="${x.hidden ? "Show it in the list again" : "Hide from the list"}" aria-label="${x.hidden ? "Show again" : "Hide"}">${x.hidden ? "↩" : "✕"}</button>`}</li>`;
  };
  const draw = () => {
    const nHidden = d.sessions.filter((x) => x.hidden).length;
    const list = d.sessions.filter((x) => showHidden || !x.hidden);
    setView(serverHeader(s, "adventures") + `
      <section class="section"><div class="section-head"><h2>🗺️ Adventures</h2><span class="muted">Every play session of the last 45 days, replayed on the map. Save the good ones to keep them for good.</span>
        ${nHidden ? `<button type="button" class="btn sm" id="rp-show-hidden">${showHidden ? "Hide the hidden ones" : `Show hidden (${nHidden})`}</button>` : ""}</div>
        ${list.length ? `<ul class="panel rp-list">${list.map(row).join("")}</ul>`
          : `<div class="empty"><h3>No adventures yet</h3><p>Once people play, each session shows up here to replay: where everyone went and what happened. Solstone needs RCON to follow where players are.</p></div>`}
      </section>`);
    wireHeader(s);
    $("#rp-show-hidden")?.addEventListener("click", () => { showHidden = !showHidden; draw(); });
    document.querySelectorAll("[data-hide]").forEach((b) => b.addEventListener("click", async () => {
      const [start, end, hide] = b.dataset.hide.split(":").map(Number);
      try {
        await post(`/api/servers/${encodeURIComponent(sid)}/adventures/hide`, { start, end, hidden: !!hide });
        d.sessions.forEach((x) => { if (x.start === start && x.end === end) x.hidden = !!hide; });
        draw();
      } catch (err) { showError(esc(err.message), 4000); }
    }));
  };
  draw();
}

async function viewAdventure(sid, key) {
  const s = await serverFrame(sid, "adventures");
  const base = `/api/servers/${encodeURIComponent(sid)}/adventures`;
  let saved = null, start, end;
  if (key.startsWith("a")) {
    const all = (await api(`${base}?days=365`)).sessions.flatMap((x) => x.saved);
    saved = all.find((a) => String(a.id) === key.slice(1));
    if (!saved) { location.replace(`#/s/${encodeURIComponent(sid)}/adventures`); return; }
    start = saved.start; end = saved.end;
  } else [start, end] = key.split("-").map(Number);
  const d = await api(`${base}/timeline?start=${start}&end=${end}`);
  const players = Object.keys(d.trails).sort((a, b) => a.localeCompare(b));
  const colour = Object.fromEntries(players.map((p, i) => [p, ADV_COLOURS[i % ADV_COLOURS.length]]));
  const dims = [...new Set(Object.values(d.trails).flatMap((t) => t.map((p) => p[1])))];
  const dimName = (id) => ({ "minecraft:overworld": "Overworld", "minecraft:the_nether": "Nether", "minecraft:the_end": "The End" }[id] || id.split(":").pop());
  const st = { t: start, playing: false, speed: 60, dim: dims[0] || "minecraft:overworld", follow: "" };

  const where = (trail, t) => {           // the last point at or before t (and the next, to glide between them)
    let lo = 0, hi = trail.length - 1, i = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (trail[m][0] <= t) { i = m; lo = m + 1; } else hi = m - 1; }
    if (i < 0) return null;
    const a = trail[i], b = trail[i + 1];
    if (!b || b[1] !== a[1] || b[0] - a[0] > 90) return a;
    const f = (t - a[0]) / (b[0] - a[0]);
    return [t, a[1], a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f, a[4] + (b[4] - a[4]) * f];
  };
  const first = Object.values(d.trails)[0]?.[0];

  setView(serverHeader(s, "adventures") + `
    <section class="section rp">
      <div class="section-head"><h2>${esc(saved ? saved.title : `${advDay(start)}`)}</h2>
        <span class="muted">${esc(advDay(start))} · ${esc(advClock(start))}–${esc(advClock(end))} · ${esc(advLength(end - start))}</span>
        <a class="btn sm" href="#/s/${encodeURIComponent(sid)}/adventures">All adventures</a></div>
      ${saved?.note ? `<p class="rp-note">${esc(saved.note)}</p>` : ""}
      <div class="rp-grid">
        <div class="rp-mapcol">
          <div class="rp-map" id="rp-map"></div>
          <div class="rp-controls">
            <button type="button" class="btn sm" id="rp-play" aria-label="Play">▶</button>
            <input type="range" id="rp-t" min="${start}" max="${end}" step="1" value="${start}" aria-label="Time">
            <span class="rp-clock" id="rp-clock"></span>
            <select class="input sm" id="rp-speed" aria-label="Speed">${[[10, "10×"], [60, "60×"], [180, "3 min/s"], [600, "10 min/s"]].map(([v, l]) => `<option value="${v}" ${v === 60 ? "selected" : ""}>${l}</option>`).join("")}</select>
          </div>
          <div class="rp-who">${players.map((p) => `<button type="button" class="chip-btn" data-follow="${esc(p)}" style="--c:${colour[p]}">${faceHtml({ name: p }, 18)} ${esc(p)}</button>`).join("")}
            ${dims.length > 1 ? `<select class="input sm" id="rp-dim" aria-label="Dimension">${dims.map((x) => `<option value="${esc(x)}">${esc(dimName(x))}</option>`).join("")}</select>` : ""}</div>
          ${players.length ? "" : `<p class="muted small">No trail for this session (Solstone needs RCON to follow where players are, and trails start from this update).</p>`}
        </div>
        <aside class="rp-feed panel" id="rp-feed" aria-label="What happened">${d.events.map((e, i) => `<button type="button" class="rp-ev" data-i="${i}">
            <span class="rp-ev-t">${esc(advClock(e.ts))}</span><span>${ADV_ICONS[e.type] || "•"}</span><span>${e.type === "chat" || e.type === "webchat" ? `<b>${esc(e.player || "")}</b>: ` : ""}${esc(e.message)}</span></button>`).join("") || '<p class="muted small">Nothing in the feed for this stretch.</p>'}</aside>
      </div>
      <form class="panel rp-save" id="rp-save">
        <h3>${saved ? "This adventure" : "Save this adventure"}</h3>
        <label>Title<input class="input" name="title" maxlength="80" required value="${esc(saved?.title || "")}" placeholder="The day we found the stronghold"></label>
        <label>Note<textarea class="input" name="note" rows="3" maxlength="2000" placeholder="What happened, who was there, what to remember">${esc(saved?.note || "")}</textarea></label>
        <div class="btn-row"><button class="btn primary" type="submit">${saved ? "Save changes" : "Save adventure"}</button>
          ${saved ? `<button type="button" class="btn danger" id="rp-del">Delete</button>` : ""}
          ${isAdmin() ? `<button type="button" class="btn danger" id="rp-erase" title="Admins: delete this session's trail and statistics lines for good">Delete the trail</button>` : ""}</div>
      </form>
    </section>`);
  wireHeader(s);

  const range = $("#rp-t"), clock = $("#rp-clock"), feed = $("#rp-feed"), playBtn = $("#rp-play");
  const map = worldMapCanvas($("#rp-map"), sid, {
    dim: st.dim, center: first ? { x: first[2], z: first[4] } : { x: 0, z: 0 }, scale: 1,
    overlay: (ctx, toScreen) => {
      for (const p of players) {
        const trail = d.trails[p];
        ctx.strokeStyle = colour[p]; ctx.lineWidth = 2.5; ctx.lineJoin = "round"; ctx.globalAlpha = 0.85;
        ctx.beginPath(); let drawing = false, prevTs = 0;
        for (const pt of trail) {
          if (pt[0] > st.t) break;
          if (pt[1] !== st.dim || pt[0] - prevTs > 120) { drawing = false; }
          prevTs = pt[0];
          if (pt[1] !== st.dim) continue;
          const [x, y] = toScreen(pt[2], pt[4]);
          if (drawing) ctx.lineTo(x, y); else { ctx.moveTo(x, y); drawing = true; }
        }
        ctx.stroke(); ctx.globalAlpha = 1;
        const now = where(trail, st.t);
        if (now && now[1] === st.dim && st.t - now[0] < 90) {
          const [x, y] = toScreen(now[2], now[4]);
          ctx.fillStyle = colour[p]; ctx.strokeStyle = "#000"; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
          ctx.font = "bold 12px system-ui"; ctx.fillStyle = "#fff"; ctx.strokeStyle = "rgba(0,0,0,.8)"; ctx.lineWidth = 3;
          ctx.strokeText(p, x + 10, y + 4); ctx.fillText(p, x + 10, y + 4);
        }
      }
    },
  });

  const show = () => {
    range.value = st.t;
    clock.textContent = advClock(st.t);
    if (st.follow) {
      const now = where(d.trails[st.follow], st.t);
      if (now) { if (now[1] !== st.dim) setDim(now[1]); map.view.cx = now[2]; map.view.cz = now[4]; }
    }
    map.draw();
    let last = null;
    feed.querySelectorAll(".rp-ev").forEach((b) => { const past = d.events[+b.dataset.i].ts <= st.t; b.classList.toggle("future", !past); if (past) last = b; });
    feed.querySelectorAll(".rp-ev.now").forEach((b) => b.classList.remove("now"));
    if (last) { last.classList.add("now"); if (st.playing) last.scrollIntoView({ block: "nearest" }); }
  };
  const setDim = (dim) => {
    st.dim = dim;
    const sel = $("#rp-dim"); if (sel) sel.value = dim;
    map.setDim?.(dim);
  };
  let timer = null, lastFrame = 0;
  const tick = (now) => {
    if (!st.playing) return;
    const dt = lastFrame ? (now - lastFrame) / 1000 : 0; lastFrame = now;
    st.t = Math.min(end, st.t + dt * st.speed);
    show();
    if (st.t >= end) { st.playing = false; playBtn.textContent = "▶"; return; }
    timer = requestAnimationFrame(tick);
  };
  playBtn.addEventListener("click", () => {
    st.playing = !st.playing; playBtn.textContent = st.playing ? "⏸" : "▶"; playBtn.setAttribute("aria-label", st.playing ? "Pause" : "Play");
    if (st.playing) { if (st.t >= end) st.t = start; lastFrame = 0; timer = requestAnimationFrame(tick); }
  });
  range.addEventListener("input", () => { st.t = +range.value; show(); });
  $("#rp-speed").addEventListener("change", (e) => { st.speed = +e.target.value; });
  $("#rp-dim")?.addEventListener("change", (e) => { setDim(e.target.value); show(); });
  document.querySelectorAll("[data-follow]").forEach((b) => b.addEventListener("click", () => {
    st.follow = st.follow === b.dataset.follow ? "" : b.dataset.follow;
    document.querySelectorAll("[data-follow]").forEach((x) => x.classList.toggle("on", x.dataset.follow === st.follow));
    show();
  }));
  feed.addEventListener("click", (e) => {
    const b = e.target.closest(".rp-ev"); if (!b) return;
    const ev = d.events[+b.dataset.i];
    st.t = ev.ts;
    const tr = ev.player && d.trails[ev.player];
    const now = tr && where(tr, st.t);
    if (now) { if (now[1] !== st.dim) setDim(now[1]); map.view.cx = now[2]; map.view.cz = now[4]; }
    show();
  });
  $("#rp-save").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const a = await post(base, { id: saved?.id, start, end, title: f.get("title"), note: f.get("note") });
      showToast(`Saved “${esc(a.title)}”`, 2500);
      location.replace(`#/s/${encodeURIComponent(sid)}/adventures/a${a.id}`);
      if (saved) route();
    } catch (err) { showError(esc(err.message), 5000); }
  });
  $("#rp-erase")?.addEventListener("click", async () => {
    if (!confirm("Delete this session's trail and its kill/ore lines for good? Joins, chat and play time stay. This can't be undone.")) return;
    try { await post(`${base}/erase`, { start, end }); showToast("Trail deleted", 2500); location.hash = `#/s/${encodeURIComponent(sid)}/adventures`; }
    catch (err) { showError(esc(err.message), 5000); }
  });
  $("#rp-del")?.addEventListener("click", async () => {
    if (!confirm(`Delete "${saved.title}"? The session stays in the list; only the title and note go.`)) return;
    try { await api(`${base}/${saved.id}`, { method: "DELETE" }); location.hash = `#/s/${encodeURIComponent(sid)}/adventures`; }
    catch (err) { showError(esc(err.message), 5000); }
  });
  state.cleanups.push(() => { st.playing = false; cancelAnimationFrame(timer); });
  show();
}
