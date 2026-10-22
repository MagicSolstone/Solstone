/* Solstone — Music: browse the library (songs, albums, artists), make playlists, and (admins)
   upload music, connect an external library, set what the radio plays when, and block or
   approve music. Loaded after app.js and showbar.js. */
"use strict";

const MU_TABS = [["songs", "Songs"], ["albums", "Albums"], ["artists", "Artists"], ["playlists", "Playlists"]];
const mu = { tab: "songs", q: "", filter: "", view: null, lists: null, settings: null, page: 0, results: null, sel: new Map(), lastSel: null };
const muFmt = (t) => { t = Math.max(0, Math.round(t || 0)); return t >= 3600 ? `${Math.floor(t / 3600)}:${String(Math.floor((t % 3600) / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}` : `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
const muArt = (id, cls = "") => `<span class="mu-art ${cls}"><img src="/api/public/music/${encodeURIComponent(id)}/art" alt="" loading="lazy" data-fail="remove"></span>`;
const muMonths = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

async function viewMusic(tab, id) {
  curSid = null;
  document.title = "Music · Solstone";
  $("#rail-servers").innerHTML = railHtml(null);
  if (tab && (MU_TABS.some(([k]) => k === tab) || tab === "library")) mu.tab = tab;
  mu.view = id ? { type: mu.tab, id } : null;
  setView(`<div class="mu-head"><h1>Music</h1>
      <p class="muted" id="mu-radio"></p></div>
    <nav class="tabs mu-tabs" aria-label="Music">${[...MU_TABS, ...(isAdmin() ? [["library", "⚙ Library"]] : [])].map(([k, l]) => `<a href="#/music/${k}" ${mu.tab === k ? 'aria-current="page"' : ""}>${l}</a>`).join("")}</nav>
    <div class="mu-search" ${mu.tab === "library" || mu.view ? "hidden" : ""}><input class="input" type="search" id="mu-q" placeholder="Search songs, artists and albums" value="${esc(mu.q)}" aria-label="Search music">
      ${isAdmin() && mu.tab !== "playlists" ? `<select class="input sm" id="mu-filter" aria-label="Show"><option value="">Everything playable</option><option value="all" ${mu.filter === "all" ? "selected" : ""}>Everything, including hidden</option>
        <option value="blocked" ${mu.filter === "blocked" ? "selected" : ""}>🚫 Blocked</option><option value="unapproved" ${mu.filter === "unapproved" ? "selected" : ""}>⏳ Waiting for approval</option></select>` : ""}</div>
    <div id="mu-body" class="mu-body"><p class="muted">Loading…</p></div>`);
  let t = 0;
  $("#mu-q")?.addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { mu.q = e.target.value; mu.page = 0; muRender(); }, 250); });
  $("#mu-filter")?.addEventListener("change", (e) => { mu.filter = e.target.value; mu.page = 0; muRender(); });
  api("/api/music/playlists").then((d) => {
    mu.lists = d.playlists; mu.radio = d.radio; mu.radioDefault = d.radio_default;
    const el = $("#mu-radio");
    if (el) el.innerHTML = `📻 The radio is playing <b>${esc(d.radio.name)}</b>${d.radio.why && d.radio.why !== "The main library" ? ` <span class="muted">(${esc(d.radio.why)})</span>` : ""}. That's what the status page and anyone who hasn't picked something else hears.`;
  }).catch(() => {});
  state.cleanups.push(() => $("#mu-selbar")?.remove());       // leaving Music: the bar goes (the selection stays)
  await muRender();
}
const muHidden = () => isAdmin() && mu.filter ? 1 : 0;

async function muRender() {
  const el = $("#mu-body");
  if (!el) return;
  try { await muRenderView(el); } finally { muSelBar(); }
}
async function muRenderView(el) {
  try {
    if (mu.view?.type === "albums") return await muAlbum(el, mu.view.id);
    if (mu.view?.type === "artists") return await muArtist(el, mu.view.id);
    if (mu.view?.type === "playlists") return await muPlaylist(el, mu.view.id);
    if (mu.tab === "songs") return await muSongs(el);
    if (mu.tab === "albums") return await muAlbums(el);
    if (mu.tab === "artists") return await muArtists(el);
    if (mu.tab === "playlists") return await muPlaylists(el);
    if (mu.tab === "library") return await muLibrary(el);
  } catch (e) { el.innerHTML = `<div class="empty"><h3>Couldn't load the music</h3><p>${esc(e.message)}</p></div>`; }
}

// ---------------------------------------------------------------- song rows (shared)
function muRowsHtml(tracks, o = {}) {
  if (!tracks.length) return `<p class="muted mu-none">${o.empty || "No songs here."}</p>`;
  const pick = !o.playlist && !o.noPick;
  return `<ol class="mu-rows ${pick ? "pickable" : ""}">${tracks.map((t, i) => `<li class="mu-row ${t.status && t.status !== "ok" ? `is-${t.status}` : ""} ${FWMusic.current?.id === t.id ? "now" : ""} ${mu.sel.has(t.id) ? "picked" : ""}" data-id="${esc(t.id)}" data-i="${i}">
      ${pick ? `<input type="checkbox" class="mu-pick" ${mu.sel.has(t.id) ? "checked" : ""} aria-label="Select ${esc(t.title)}" title="Select (Shift-click for a range)">` : ""}
      ${o.numbers ? `<span class="mu-n">${o.numbers === "track" && t.track ? t.track : i + 1}</span>` : muArt(t.id, "sm")}
      <button type="button" class="mu-main" data-play title="Play">${FWMusic.current?.id === t.id && FWMusic.playing ? "<i>♪</i> " : ""}<b>${esc(t.title)}</b>
        <small>${esc([t.artist, o.noAlbum ? "" : t.album].filter(Boolean).join(" · "))}${t.status === "blocked" ? " · 🚫 Blocked" : t.status === "unapproved" ? " · ⏳ Not approved" : ""}${t.source === "external" && isAdmin() && o.showSource ? ' <span class="chip mu-src">External</span>' : ""}</small></button>
      <span class="mu-dur">${t.duration ? muFmt(t.duration) : ""}</span>
      <span class="mu-acts">
        ${o.playlist ? `<button type="button" class="icon-btn" data-move="-1" ${i === 0 ? "disabled" : ""} title="Move up" aria-label="Move up">▲</button><button type="button" class="icon-btn" data-move="1" ${i === tracks.length - 1 ? "disabled" : ""} title="Move down" aria-label="Move down">▼</button>
          <button type="button" class="icon-btn" data-remove title="Take out of this playlist" aria-label="Remove">✕</button>` : `<button type="button" class="icon-btn" data-add title="Add to a playlist" aria-label="Add to a playlist">＋</button>`}
        ${isAdmin() && t.uploaded ? `<button type="button" class="icon-btn" data-retag title="Fix the title, artist or album" aria-label="Edit">✎</button><button type="button" class="icon-btn" data-delete title="Delete (only for music uploaded here)" aria-label="Delete">🗑</button>` : ""}
        ${isAdmin() ? (t.status === "blocked" ? `<button type="button" class="btn sm" data-rule="blocked" data-on="0" title="Let people play it again">Unblock</button>`
          : `${t.status === "unapproved" ? `<button type="button" class="btn sm" data-rule="approved" data-on="1">Approve</button>` : ""}<button type="button" class="icon-btn mu-block" data-rule="blocked" data-on="1" title="Block: nobody can play it, anywhere" aria-label="Block">🚫</button>`) : ""}
      </span></li>`).join("")}</ol>`;
}
// Clicks on rows: play (the list becomes the queue), add to a playlist, block.
function muWireRows(el, tracks, src, o = {}) {
  el.querySelectorAll(".mu-row").forEach((li) => {
    const t = tracks[+li.dataset.i];
    li.querySelector(".mu-pick")?.addEventListener("click", (e) => {
      const on = e.currentTarget.checked, i = +li.dataset.i;
      // Shift-click: everything between the last ticked row and this one
      const range = e.shiftKey && mu.lastSel && mu.lastSel.list === tracks ? [Math.min(mu.lastSel.i, i), Math.max(mu.lastSel.i, i)] : [i, i];
      for (let k = range[0]; k <= range[1]; k++) {
        const tk = tracks[k];
        if (on) mu.sel.set(tk.id, tk.title); else mu.sel.delete(tk.id);
        const row = el.querySelector(`.mu-row[data-i="${k}"]`);
        row?.classList.toggle("picked", on);
        const cb = row?.querySelector(".mu-pick"); if (cb) cb.checked = on;
      }
      mu.lastSel = { list: tracks, i };
      muSelBar();
    });
    li.querySelector("[data-play]")?.addEventListener("click", () => muPlay(src, t.id));
    li.querySelector("[data-add]")?.addEventListener("click", (e) => muAddMenu(e.currentTarget, [t.id]));
    li.querySelectorAll("[data-rule]").forEach((b) => b.addEventListener("click", async () => {
      await muRule(b.dataset.rule, "tracks", t.id, b.dataset.on === "1", t.title);
      muRender();
    }));
    li.querySelector("[data-remove]")?.addEventListener("click", () => o.onRemove?.(t.id));
    li.querySelector("[data-retag]")?.addEventListener("click", () => muRetag(t));
    li.querySelector("[data-delete]")?.addEventListener("click", async () => {
      if (!(await confirmBox(`Delete “${t.title}”?`, "It was uploaded through Solstone, so the file is removed from the Solstone folder (and from Jellyfin).", "Delete"))) return;
      try { await api(`/api/music/${encodeURIComponent(t.id)}`, { method: "DELETE" }); showToast("Deleted", 1500); muRender(); }
      catch (e) { showToast(esc(e.message), 4000); }
    });
    li.querySelectorAll("[data-move]").forEach((b) => b.addEventListener("click", () => o.onMove?.(+li.dataset.i, +b.dataset.move)));
  });
}
async function muPlay(src, startId, shuffle = false) {
  if (!FWMusic.loaded) await FWMusic.load();
  try { await FWMusic.playSource(src, startId, shuffle); appSky.bar?.musicChanged(); setTimeout(() => muMarkNow(), 300); }
  catch (e) { showToast(esc(e.message), 3000); }
}
function muMarkNow() { $$(".mu-row").forEach((li) => li.classList.toggle("now", li.dataset.id === FWMusic.current?.id)); }
async function muRule(action, kind, value, on, label = "") {
  try {
    await post("/api/music/rule", { action, kind, value, on });
    showToast(action === "blocked" ? (on ? `Blocked ${esc(label || value)}. Nobody can play it now.` : `${esc(label || value)} can be played again`) : (on ? `Approved ${esc(label || value)}` : `Took away approval for ${esc(label || value)}`), 3000);
  } catch (e) { showToast(esc(e.message), 4000); }
}
// Ticked songs (kept while you search around), and what to do with them.
function muSelBar() {
  let bar = $("#mu-selbar");
  if (!mu.sel.size || !$("#mu-body")) { bar?.remove(); return; }
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "mu-selbar"; bar.className = "mu-selbar glass"; bar.setAttribute("role", "region"); bar.setAttribute("aria-label", "Selected songs");
    document.body.append(bar);
    bar.addEventListener("click", (e) => {
      if (e.target.closest("[data-sel-add]")) muAddMenu(e.target.closest("[data-sel-add]"), [...mu.sel.keys()], () => muClearSel());
      else if (e.target.closest("[data-sel-play]")) muPlay({ type: "ids", id: [...mu.sel.keys()].join(","), name: "Selected songs" });
      else if (e.target.closest("[data-sel-clear]")) muClearSel();
    });
  }
  bar.innerHTML = `<b>${mu.sel.size} ${mu.sel.size === 1 ? "song" : "songs"} selected</b>
    <button type="button" class="btn sm primary" data-sel-add>＋ Add to playlist</button><button type="button" class="btn sm" data-sel-play>▶ Play</button><button type="button" class="btn sm" data-sel-clear>Clear</button>`;
}
function muClearSel() {
  mu.sel.clear(); mu.lastSel = null;
  $$(".mu-row.picked").forEach((r) => { r.classList.remove("picked"); const cb = r.querySelector(".mu-pick"); if (cb) cb.checked = false; });
  muSelBar();
}

// "Add to a playlist": the playlists you can change, or a new one.
function muAddMenu(anchor, ids, done) {
  $(".mu-menu")?.remove();
  const mine = (mu.lists || []).filter((p) => p.can_edit);
  const m = document.createElement("div");
  m.className = "mu-menu glass";
  m.innerHTML = `<b>Add to…</b>${mine.map((p) => `<button type="button" data-pl="${esc(p.id)}">${p.schedule?.on ? "🗓" : "🎶"} ${esc(p.name)} <small>${p.count}</small></button>`).join("")}
    <button type="button" data-new>＋ New playlist…</button>`;
  document.body.append(m);
  const r = anchor.getBoundingClientRect();
  m.style.top = `${Math.min(innerHeight - m.offsetHeight - 10, r.bottom + 4)}px`; m.style.left = `${Math.max(10, r.right - m.offsetWidth)}px`;
  const close = (e) => { if (!m.contains(e.target)) { m.remove(); document.removeEventListener("click", close, true); } };
  setTimeout(() => document.addEventListener("click", close, true));
  m.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    m.remove(); document.removeEventListener("click", close, true);
    try {
      if (b.dataset.new != null) {
        const name = await muAsk("New playlist", "Name", "");
        if (!name) return;
        const p = await post("/api/music/playlists", { name, tracks: ids });
        showToast(`Made “${esc(p.name)}” with ${ids.length} ${ids.length === 1 ? "song" : "songs"}`, 2500);
      } else {
        const before = (mu.lists || []).find((x) => x.id === b.dataset.pl)?.count ?? 0;
        const p = await post(`/api/music/playlists/${b.dataset.pl}`, { add: ids }, "PUT");
        const added = Math.max(0, (p.count ?? before + ids.length) - before), dup = ids.length - added;
        showToast(ids.length === 1 ? `Added to “${esc(p.name)}”` : `Added ${added} to “${esc(p.name)}”${dup ? ` (${dup} already there)` : ""}`, 2500);
      }
      done?.();
      mu.lists = (await api("/api/music/playlists")).playlists;
    } catch (err) { showToast(esc(err.message), 4000); }
  });
}
function muRetag(t) {
  openModal(`<h2>Fix the details</h2><form id="mu-retag">
      <label>Title<input class="input" name="title" value="${esc(t.title)}" maxlength="120" required></label>
      <label>Artist<input class="input" name="artist" value="${esc(t.artist)}" maxlength="120"></label>
      <label>Album<input class="input" name="album" value="${esc(t.album)}" maxlength="120"></label>
      <p class="muted small">Written into the file's tags, and the file moves to Solstone/Artist/Album so Jellyfin files it the same way.</p>
      <div class="actions"><button type="button" class="btn" id="mu-rt-no">Cancel</button><button class="btn primary" type="submit">Save</button></div></form>`, (m) => {
    $("#mu-rt-no", m).addEventListener("click", closeModal);
    $("#mu-retag", m).addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      try { await post(`/api/music/tracks/${encodeURIComponent(t.id)}`, { title: f.get("title"), artist: f.get("artist"), album: f.get("album") }, "PUT"); closeModal(); showToast("Saved and re-filed", 2000); muRender(); }
      catch (err) { showToast(esc(err.message), 4000); }
    });
  });
}
function muAsk(title, label, value) {
  return new Promise((resolve) => {
    openModal(`<h2>${esc(title)}</h2><form id="mu-ask"><label>${esc(label)}<input class="input" name="v" maxlength="60" value="${esc(value)}" required></label>
      <div class="actions"><button type="button" class="btn" id="mu-ask-no">Cancel</button><button class="btn primary" type="submit">OK</button></div></form>`, (m) => {
      const inp = $("[name=v]", m); inp.focus(); inp.select();
      $("#mu-ask-no", m).addEventListener("click", () => { closeModal(); resolve(null); });
      $("#mu-ask", m).addEventListener("submit", (e) => { e.preventDefault(); const v = inp.value.trim(); closeModal(); resolve(v || null); });
    });
  });
}

// ---------------------------------------------------------------- songs
async function muSongs(el) {
  const status = mu.filter && mu.filter !== "all" ? mu.filter : "";
  const d = await api(`/api/music/library?q=${encodeURIComponent(mu.q)}&status=${status}&limit=${(mu.page + 1) * 200}`);
  const tracks = muHidden() ? d.tracks : d.tracks.filter((t) => (t.status || "ok") === "ok");
  el.innerHTML = `<div class="mu-bar"><span class="muted">${d.total.toLocaleString()} ${d.total === 1 ? "song" : "songs"}</span>
      ${tracks.length ? `<button class="btn sm primary" type="button" id="mu-playall">▶ Play these</button><button class="btn sm" type="button" id="mu-shuf">🔀 Shuffle</button><button class="btn sm" type="button" id="mu-addall" title="Add every song listed here to a playlist">＋ Add these</button>` : ""}</div>
    ${muRowsHtml(tracks, { showSource: true, empty: mu.q ? "No songs match." : "No music yet." })}
    ${d.total > d.tracks.length ? `<button class="btn" type="button" id="mu-more">Show more</button>` : ""}`;
  const src = { type: "ids", id: tracks.slice(0, 500).map((t) => t.id).join(","), name: mu.q ? `Search: ${mu.q}` : "All songs" };
  muWireRows(el, tracks, src);
  $("#mu-playall")?.addEventListener("click", () => muPlay(src));
  $("#mu-shuf")?.addEventListener("click", () => muPlay(src, null, true));
  $("#mu-more")?.addEventListener("click", () => { mu.page++; muRender(); });
  $("#mu-addall")?.addEventListener("click", (e) => muAddMenu(e.currentTarget, tracks.map((t) => t.id)));
}

// ---------------------------------------------------------------- albums
async function muAlbums(el) {
  let list = await api(`/api/music/albums?q=${encodeURIComponent(mu.q)}`);
  if (mu.filter === "blocked" || mu.filter === "unapproved") list = list.filter((a) => a.status === mu.filter);
  else if (!mu.filter) list = list.filter((a) => (a.status || "ok") === "ok");
  el.innerHTML = list.length ? `<div class="mu-grid">${list.map((a) => `<a class="mu-card ${a.status && a.status !== "ok" ? `is-${a.status}` : ""}" href="#/music/albums/${encodeURIComponent(a.key)}">
      ${muArt(a.art, "big")}<b>${esc(a.album)}</b><small>${esc(a.artist)}${a.year ? ` · ${esc(a.year)}` : ""}</small></a>`).join("")}</div>` : `<p class="muted">No albums${mu.q ? " match" : " yet"}.</p>`;
}
async function muAlbum(el, key) {
  const d = await api(`/api/music/library?album=${encodeURIComponent(key)}&limit=500`);
  const tracks = d.tracks, first = tracks[0] || {};
  const status = tracks.every((t) => t.status === "blocked") ? "blocked" : tracks.some((t) => t.status === "unapproved") ? "unapproved" : "ok";
  const total = tracks.reduce((a, t) => a + (t.duration || 0), 0);
  el.innerHTML = `<a class="mu-back" href="#/music/albums">← Albums</a>
    <div class="mu-hero">${first.id ? muArt(first.id, "hero") : ""}<div><p class="muted small">Album</p><h2>${esc(first.album || "Album")}</h2>
      <p><a href="#/music/artists/${encodeURIComponent(first.albumartist || first.artist || "")}">${esc(first.albumartist || first.artist || "")}</a>${first.year ? ` · ${esc(first.year)}` : ""} · ${tracks.length} songs · ${muFmt(total)}</p>
      <div class="btn-row"><button class="btn primary" type="button" id="mu-play">▶ Play</button><button class="btn" type="button" id="mu-shuf">🔀 Shuffle</button><button class="btn" type="button" id="mu-add">＋ Add to playlist</button>
        ${isAdmin() ? `${status === "unapproved" ? `<button class="btn" type="button" data-arule="approved" data-on="1">✓ Approve album</button>` : ""}${status === "blocked" ? `<button class="btn" type="button" data-arule="blocked" data-on="0">Unblock album</button>` : `<button class="btn danger" type="button" data-arule="blocked" data-on="1">🚫 Block album</button>`}` : ""}</div></div></div>
    ${muRowsHtml(tracks, { numbers: "track", noAlbum: true })}`;
  const src = { type: "album", id: key, name: first.album };
  muWireRows(el, tracks, src);
  $("#mu-play").addEventListener("click", () => muPlay(src));
  $("#mu-shuf").addEventListener("click", () => muPlay(src, null, true));
  $("#mu-add").addEventListener("click", (e) => muAddMenu(e.currentTarget, tracks.map((t) => t.id)));
  el.querySelectorAll("[data-arule]").forEach((b) => b.addEventListener("click", async () => {
    if (b.dataset.arule === "blocked" && b.dataset.on === "1" && !(await confirmBox(`Block “${first.album}”?`, "Nobody will be able to see or play any of it, anywhere. The files aren't touched, and you can unblock it later.", "Block it"))) return;
    await muRule(b.dataset.arule, "albums", key, b.dataset.on === "1", first.album); muRender();
  }));
}

// ---------------------------------------------------------------- artists
async function muArtists(el) {
  let list = await api(`/api/music/artists?q=${encodeURIComponent(mu.q)}`);
  if (mu.filter === "blocked" || mu.filter === "unapproved") list = list.filter((a) => a.status === mu.filter);
  else if (!mu.filter) list = list.filter((a) => (a.status || "ok") === "ok");
  el.innerHTML = list.length ? `<div class="mu-artists">${list.map((a) => `<a class="mu-artist ${a.status && a.status !== "ok" ? `is-${a.status}` : ""}" href="#/music/artists/${encodeURIComponent(a.name)}">${muArt(a.art, "round")}<span><b>${esc(a.name)}</b><small>${a.status === "blocked" ? "🚫 Blocked · " : a.status === "unapproved" ? "⏳ Not approved · " : ""}${a.albums} ${a.albums === 1 ? "album" : "albums"} · ${a.count} ${a.count === 1 ? "song" : "songs"}</small></span></a>`).join("")}</div>`
    : `<p class="muted">No artists${mu.q ? " match" : " yet"}.</p>`;
}
async function muArtist(el, name) {
  const [d, albums] = await Promise.all([api(`/api/music/library?artist=${encodeURIComponent(name)}&limit=500`), api(`/api/music/albums`)]);
  const keys = new Set(d.tracks.map((t) => `${(t.albumartist || t.artist || "").trim().toLowerCase().replace(/\s+/g, " ")}|${(t.album || "").trim().toLowerCase().replace(/\s+/g, " ")}`));
  const theirs = albums.filter((a) => keys.has(a.key));
  const blocked = (mu.settings?.blocked?.artists || []).includes(name.trim().toLowerCase());
  el.innerHTML = `<a class="mu-back" href="#/music/artists">← Artists</a>
    <div class="mu-hero">${d.tracks[0] ? muArt(d.tracks[0].id, "hero round") : ""}<div><p class="muted small">Artist</p><h2>${esc(name)}</h2><p>${theirs.length} albums · ${d.total} songs</p>
      <div class="btn-row"><button class="btn primary" type="button" id="mu-play">▶ Play all</button><button class="btn" type="button" id="mu-shuf">🔀 Shuffle</button>
      ${isAdmin() ? `<button class="btn" type="button" data-xrule="approved" data-on="1">✓ Approve artist</button><button class="btn ${blocked ? "" : "danger"}" type="button" data-xrule="blocked" data-on="${blocked ? 0 : 1}">${blocked ? "Unblock artist" : "🚫 Block artist"}</button>` : ""}</div></div></div>
    ${theirs.length > 1 ? `<h3 class="mu-sub">Albums</h3><div class="mu-grid">${theirs.map((a) => `<a class="mu-card" href="#/music/albums/${encodeURIComponent(a.key)}">${muArt(a.art, "big")}<b>${esc(a.album)}</b><small>${a.year ? esc(a.year) : ""}</small></a>`).join("")}</div>` : ""}
    <h3 class="mu-sub">Songs</h3>${muRowsHtml(d.tracks)}`;
  const src = { type: "artist", id: name, name };
  muWireRows(el, d.tracks, src);
  $("#mu-play").addEventListener("click", () => muPlay(src));
  $("#mu-shuf").addEventListener("click", () => muPlay(src, null, true));
  el.querySelectorAll("[data-xrule]").forEach((b) => b.addEventListener("click", async () => {
    if (b.dataset.xrule === "blocked" && b.dataset.on === "1" && !(await confirmBox(`Block ${name}?`, "Nobody will be able to see or play anything by them, anywhere. The files aren't touched.", "Block"))) return;
    await muRule(b.dataset.xrule, "artists", name, b.dataset.on === "1", name);
    mu.settings = null; location.hash = "#/music/artists";
  }));
  if (isAdmin() && !mu.settings) api("/api/music/settings").then((s) => { mu.settings = s; }).catch(() => {});
}

// ---------------------------------------------------------------- playlists
// Radio playlists whose dates overlap: which one plays on the shared days (the shorter range).
function muOverlaps(p, lists) {
  const s = p.schedule;
  if (!s?.on) return [];
  const days = (sc) => { const out = []; const d = new Date(2024, +sc.from.slice(0, 2) - 1, +sc.from.slice(3)); const end = `${sc.to}`;
    for (let i = 0; i < 366; i++) { const md = `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; out.push(md); if (md === end) break; d.setDate(d.getDate() + 1); } return out; };
  const mine = days(s), out = [];
  for (const q of lists || []) {
    if (q.id === p.id || !q.schedule?.on) continue;
    const theirs = new Set(days(q.schedule)), shared = mine.filter((md) => theirs.has(md));
    if (!shared.length) continue;
    const wins = mine.length < theirs.size || (mine.length === theirs.size && (p.created || 0) < (q.created || 0));
    const md = (x) => `${+x.slice(3)} ${muMonths[+x.slice(0, 2) - 1]}`;
    out.push({ with: q.name, wins, when: shared.length === 1 ? md(shared[0]) : `${md(shared[0])} – ${md(shared[shared.length - 1])}` });
  }
  return out;
}
const muOverlapNote = (p, lists) => muOverlaps(p, lists).map((o) => `<small class="mu-overlap" title="When radio playlists overlap, the one with the shorter dates plays">⚠ ${o.wins ? `Plays instead of ${esc(o.with)} on ${esc(o.when)}` : `${esc(o.with)} plays instead on ${esc(o.when)}`}</small>`).join("");
const muRange = (s) => s?.on ? `${+s.from.slice(3)} ${muMonths[+s.from.slice(0, 2) - 1]} – ${+s.to.slice(3)} ${muMonths[+s.to.slice(0, 2) - 1]}` : "";
async function muPlaylists(el) {
  const d = await api("/api/music/playlists");
  mu.lists = d.playlists;
  const q = mu.q.trim().toLowerCase();
  const list = d.playlists.filter((p) => !q || p.name.toLowerCase().includes(q));
  const card = (p) => `<a class="mu-pl" href="#/music/playlists/${encodeURIComponent(p.id)}"><span class="mu-pl-ic">${p.schedule?.on ? "🗓" : p.shared ? "👪" : "🎶"}</span>
    <span><b>${esc(p.name)}</b><small>${p.count} ${p.count === 1 ? "song" : "songs"} · ${p.mine ? "yours" : `by ${esc(p.owner)}`}${p.shared ? " · shared" : ""}</small>
    ${p.schedule?.on ? `<small class="mu-sched">📻 Radio ${esc(muRange(p.schedule))}</small>${muOverlapNote(p, d.playlists)}` : ""}${d.radio_default === p.id ? `<small class="mu-sched">📻 Default radio</small>` : ""}</span></a>`;
  const mine = list.filter((p) => p.mine), others = list.filter((p) => !p.mine);
  el.innerHTML = `<div class="mu-bar"><button class="btn primary" type="button" id="mu-new">＋ New playlist</button></div>
    <h3 class="mu-sub">Yours</h3>${mine.length ? `<div class="mu-pls">${mine.map(card).join("")}</div>` : `<p class="muted">You haven't made any yet. Use ＋ on any song, or start one here.</p>`}
    ${others.length ? `<h3 class="mu-sub">Shared with everyone</h3><div class="mu-pls">${others.map(card).join("")}</div>` : ""}`;
  $("#mu-new").addEventListener("click", async () => {
    const name = await muAsk("New playlist", "Name", "");
    if (!name) return;
    try { const p = await post("/api/music/playlists", { name }); location.hash = `#/music/playlists/${p.id}`; }
    catch (e) { showToast(esc(e.message), 4000); }
  });
}
async function muPlaylist(el, id) {
  const [p, all] = await Promise.all([api(`/api/music/playlists/${encodeURIComponent(id)}`), api("/api/music/playlists")]);
  mu.lists = all.playlists; mu.radioDefault = all.radio_default;
  const total = p.items.reduce((a, t) => a + (t.duration || 0), 0), s = p.schedule || {};
  const mdSel = (name, v) => { const [mo, d] = (v || "12-01").split("-").map(Number);
    return `<span class="mu-md"><select class="input sm" data-md="${name}-m">${muMonths.map((m, i) => `<option value="${i + 1}" ${i + 1 === mo ? "selected" : ""}>${m}</option>`).join("")}</select>
      <input class="input sm" type="number" min="1" max="31" value="${d}" data-md="${name}-d" style="width:64px"></span>`; };
  el.innerHTML = `<a class="mu-back" href="#/music/playlists">← Playlists</a>
    <div class="mu-hero">${p.items[0] ? muArt(p.items[0].id, "hero") : `<span class="mu-art hero"></span>`}<div><p class="muted small">Playlist · ${p.mine ? "yours" : `by ${esc(p.owner)}`}</p>
      ${p.can_edit ? `<input class="input mu-title" id="mu-name" value="${esc(p.name)}" maxlength="60" aria-label="Playlist name">` : `<h2>${esc(p.name)}</h2>`}
      <p>${p.items.length} songs · ${muFmt(total)}${p.count > p.items.length ? ` <span class="muted">(${p.count - p.items.length} hidden or gone)</span>` : ""}</p>
      <div class="btn-row"><button class="btn primary" type="button" id="mu-play" ${p.items.length ? "" : "disabled"}>▶ Play</button><button class="btn" type="button" id="mu-shuf" ${p.items.length ? "" : "disabled"}>🔀 Shuffle</button>
        ${p.can_edit ? `<label class="check"><input type="checkbox" id="mu-shared" ${p.shared ? "checked" : ""}> Share with everyone</label><button class="btn danger" type="button" id="mu-del">Delete</button>` : ""}</div></div></div>
    ${isAdmin() ? `<section class="panel mu-radio-set"><h3 class="fws-sub">📻 Radio</h3>
      <p class="muted small">The radio is what plays by default: on the status page, and for everyone who hasn't picked something else. A playlist with dates takes over every year between them (the shortest range wins when they overlap).</p>
      <label class="check"><input type="checkbox" id="mu-sched" ${s.on ? "checked" : ""}> Play on the radio every year from ${mdSel("from", s.from || "12-01")} to ${mdSel("to", s.to || "12-26")}</label>
      ${muOverlapNote(p, mu.lists)}
      <label class="check"><input type="checkbox" id="mu-default" ${mu.radioDefault === p.id ? "checked" : ""}> The default radio the rest of the year</label>
      <button class="btn sm" type="button" id="mu-sched-save">Save radio settings</button></section>` : ""}
    <div id="mu-pl-rows">${muRowsHtml(p.items, { playlist: p.can_edit, empty: "Empty for now. Find songs under Songs, Albums or Artists and press ＋." })}</div>`;
  const src = { type: "playlist", id: p.id, name: p.name };
  const ids = p.items.map((t) => t.id);
  const save = async (body, msg) => { try { await post(`/api/music/playlists/${p.id}`, body, "PUT"); if (msg) showToast(msg, 1800); muRender(); } catch (e) { showToast(esc(e.message), 4000); } };
  muWireRows(el, p.items, src, {
    onRemove: (tid) => save({ remove: [tid] }),
    onMove: (i, dir) => { const o = [...ids]; const [x] = o.splice(i, 1); o.splice(i + dir, 0, x); save({ tracks: o }); },
  });
  $("#mu-play").addEventListener("click", () => muPlay(src));
  $("#mu-shuf").addEventListener("click", () => muPlay(src, null, true));
  $("#mu-name")?.addEventListener("change", (e) => save({ name: e.target.value }, "Renamed"));
  $("#mu-shared")?.addEventListener("change", (e) => save({ shared: e.target.checked }, e.target.checked ? "Shared with everyone" : "Only you can see it now"));
  $("#mu-del")?.addEventListener("click", async () => {
    if (!(await confirmBox(`Delete “${p.name}”?`, "Just the playlist; the songs stay in the library.", "Delete"))) return;
    await api(`/api/music/playlists/${p.id}`, { method: "DELETE" }).catch((e) => showToast(esc(e.message), 4000));
    location.hash = "#/music/playlists";
  });
  $("#mu-sched-save")?.addEventListener("click", async () => {
    const md = (n) => `${String($(`[data-md="${n}-m"]`).value).padStart(2, "0")}-${String(Math.max(1, Math.min(31, +$(`[data-md="${n}-d"]`).value || 1))).padStart(2, "0")}`;
    await save({ schedule: { on: $("#mu-sched").checked, from: md("from"), to: md("to") }, radio_default: $("#mu-default").checked }, "Radio settings saved");
    const d = await api("/api/music/playlists"); mu.radioDefault = d.radio_default;
    FWMusic.loaded && FWMusic.source.type === "radio" && FWMusic.fetchSource({ type: "radio" }).then(() => {});
  });
}

// ---------------------------------------------------------------- library settings (admins)
async function muLibrary(el) {
  const s = mu.settings = await api("/api/music/settings");
  const x = s.external, mb = (n) => `${(n / 1024 / 1024).toFixed(1)} MB`;
  const blocked = s.blocked;
  el.innerHTML = `<div class="mu-lib">
    <section class="panel"><h3 class="fws-sub">Who can listen</h3>
      <label class="switch-row"><span>Play the radio on the public status page<br><small class="muted">Visitors only ever get the radio, never the rest of the library.</small></span><input type="checkbox" role="switch" id="mu-public" ${s.public ? "checked" : ""}></label>
      <div class="fw-row" style="margin-top:12px"><span>Default radio</span><select class="input sm" id="mu-default-radio"><option value="">The main library (uploads)</option>${(mu.lists || []).filter((p) => p.shared || p.mine).map((p) => `<option value="${esc(p.id)}" ${s.radio_default === p.id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></div>
      <p class="muted small">Dated playlists (Christmas, Halloween…) take over on their days; set dates on the playlist itself.</p></section>

    <section class="panel"><h3 class="fws-sub">Upload music</h3>
      ${x.upload_ok ? `<p class="small">Uploads go into <code>${esc(x.upload_dir)}</code>, sorted as <i>Artist / Album / 01 - Title</i> from the file's tags, so Jellyfin sees them too. ${x.uploaded ? `${x.uploaded} ${x.uploaded === 1 ? "song" : "songs"} there so far.` : ""} Songs without tags go in <i>Unsorted</i>; use ✎ on a song to fix its details.</p>`
        : x.configured ? `<p class="small">The easy way to add music is to put it in your music library (<code>${esc(x.root)}</code>), the way you do for Jellyfin: Solstone finds it on its own (see below). Uploading here is optional, for a quick song or two; those are kept in Solstone's own data folder, so only Solstone plays them.</p>
          <details class="mu-more"><summary class="small">Want uploads to go into the library too, so Jellyfin sees them?</summary>
            <p class="small">Let Solstone write to just one folder inside it, <code>${esc(x.upload_dir)}</code>, by adding this volume (the rest of the library stays read-only):</p>
            <pre class="mu-code">- /mnt/user/media/music/Solstone:/music/Solstone</pre></details>`
        : `<p class="muted small">Uploads are kept in Solstone's data folder. Set up a music library below to keep everything in one place.</p>`}
      <div class="fws-upload"><label class="btn primary">Add music…<input type="file" accept="audio/*" multiple hidden id="mu-file"></label><span class="muted small" id="mu-up">MP3, OGG, M4A, WAV, FLAC or Opus, up to 60 MB each.</span></div>
      ${s.main.length && x.upload_ok ? `<div class="notice" style="margin-top:12px">${s.main.length} ${s.main.length === 1 ? "song was" : "songs were"} uploaded before the library was set up. <button class="btn sm" type="button" id="mu-move">Move them into the Solstone folder</button><br><small class="muted">They're kept together as the “Minecraft music” playlist, which becomes the default radio if you haven't picked one.</small></div>` : ""}
      ${s.main.length ? `<ol class="fws-tracks">${s.main.map((t, i) => `<li data-id="${t.id}"><span class="num muted">${i + 1}</span>
        <input class="input sm" value="${esc(t.title)}" data-title aria-label="Title"><span class="muted small">${esc(t.artist || "")}${t.artist ? " · " : ""}${t.ext.toUpperCase()} · ${mb(t.size)}</span>
        <span class="row-actions"><button type="button" class="icon-btn" data-up ${i === 0 ? "disabled" : ""} title="Move up">▲</button>
        <button type="button" class="icon-btn" data-down ${i === s.main.length - 1 ? "disabled" : ""} title="Move down">▼</button><button type="button" class="btn sm danger" data-del>Delete</button></span></li>`).join("")}</ol>` : ""}</section>

    <section class="panel"><h3 class="fws-sub">External library <span class="muted small">your own music folder, read-only</span></h3>
      ${!x.configured ? `<p class="muted">Point Solstone at a music folder (Jellyfin's, say) to add it here. Mount it read-only and set <code>MUSIC_LIBRARY_DIR</code>:</p>
        <pre class="mu-code">volumes:\n  - /mnt/user/media/music:/music:ro\n  - /mnt/user/media/music/Solstone:/music/Solstone\nenvironment:\n  MUSIC_LIBRARY_DIR: /music</pre>
        <p class="muted small">The whole library is read-only; only the Solstone folder inside it can be written to, for uploads.</p>`
      : !x.found ? `<div class="notice">Can't find <code>${esc(x.root)}</code>. Check the folder is mounted into the container.</div>`
      : `<p><b>${x.count.toLocaleString()}</b> songs in <code>${esc(x.root)}</code>${x.scanned ? ` · read ${esc(fmtAgo(x.scanned))}` : ""}${x.scanning ? ` · <b>reading… ${x.progress.toLocaleString()} so far</b>` : ""}</p>
        ${x.error ? `<div class="notice">${esc(x.error)}</div>` : ""}
        <button class="btn sm" type="button" id="mu-rescan" ${x.scanning ? "disabled" : ""}>Look for new music now</button> <span class="muted small">It also checks every 6 hours. Nothing in the folder is ever changed.</span>`}
      <h3 class="fws-sub" style="margin-top:14px">What's allowed from it</h3>
      <div class="seg" role="group" id="mu-mode"><button type="button" data-v="all" aria-pressed="${s.mode === "all"}">Everything except what I block</button><button type="button" data-v="approved" aria-pressed="${s.mode === "approved"}">Only what I approve</button></div>
      <p class="muted small">${s.mode === "approved" ? `Nothing from the external library shows up until you approve it: a song, an album or a whole artist. Use “⏳ Waiting for approval” in the search filter to find things.` : `All of it can be played, apart from what you block. Block songs, albums or whole artists from their pages.`}</p></section>

    <section class="panel"><h3 class="fws-sub">🚫 Blocked <span class="muted small">hidden everywhere and can't be played; the files stay where they are</span></h3>
      ${!blocked.artists.length && !blocked.albums.length && !blocked.tracks.length ? `<p class="muted">Nothing blocked.</p>` : ""}
      ${blocked.artists.length ? `<p class="mu-blk-h">Artists</p><div class="mu-chips">${blocked.artists.map((a) => `<span class="chip">${esc(a)} <button type="button" class="chip-x" data-unblock="artists" data-v="${esc(a)}" aria-label="Unblock ${esc(a)}">×</button></span>`).join("")}</div>` : ""}
      ${blocked.albums.length ? `<p class="mu-blk-h">Albums</p><div class="mu-chips">${blocked.albums.map((a) => `<span class="chip">${esc(a.split("|")[1] || a)} <small class="muted">${esc(a.split("|")[0])}</small> <button type="button" class="chip-x" data-unblock="albums" data-v="${esc(a)}" aria-label="Unblock">×</button></span>`).join("")}</div>` : ""}
      ${blocked.tracks.length ? `<p class="mu-blk-h">Songs</p><div id="mu-blk-songs"><p class="muted small">Loading…</p></div>` : ""}
    </section>
    ${s.mode === "approved" && (s.approved.artists.length || s.approved.albums.length) ? `<section class="panel"><h3 class="fws-sub">✓ Approved</h3>
      ${s.approved.artists.length ? `<p class="mu-blk-h">Artists</p><div class="mu-chips">${s.approved.artists.map((a) => `<span class="chip">${esc(a)} <button type="button" class="chip-x" data-unapprove="artists" data-v="${esc(a)}" aria-label="Take away approval">×</button></span>`).join("")}</div>` : ""}
      ${s.approved.albums.length ? `<p class="mu-blk-h">Albums</p><div class="mu-chips">${s.approved.albums.map((a) => `<span class="chip">${esc(a.split("|")[1] || a)} <button type="button" class="chip-x" data-unapprove="albums" data-v="${esc(a)}" aria-label="Take away approval">×</button></span>`).join("")}</div>` : ""}</section>` : ""}
  </div>`;
  const reload = async () => { await muLibrary(el); FWMusic.loaded = false; await FWMusic.load(); appSky.bar?.musicChanged(); };
  $("#mu-public").addEventListener("change", (e) => post("/api/music/settings", { public: e.target.checked }, "PUT").then(() => showToast("Saved", 1500)));
  $("#mu-default-radio").addEventListener("change", (e) => post("/api/music/settings", { radio_default: e.target.value }, "PUT").then(() => { showToast("Saved", 1500); mu.radioDefault = e.target.value; }));
  $("#mu-move")?.addEventListener("click", async (e) => {
    e.target.disabled = true;
    try { const r = await post("/api/music/move-uploads"); showToast(`Moved ${r.moved} ${r.moved === 1 ? "song" : "songs"} into the Solstone folder`, 3000); }
    catch (err) { showToast(esc(err.message), 4000); }
    reload();
  });
  $("#mu-rescan")?.addEventListener("click", async () => { await post("/api/music/rescan").catch((e) => showToast(esc(e.message), 4000)); showToast("Reading the music folder…", 2500); setTimeout(() => muLibrary(el), 2500); });
  $$("#mu-mode button").forEach((b) => b.addEventListener("click", async () => { await post("/api/music/settings", { mode: b.dataset.v }, "PUT"); muLibrary(el); }));
  el.querySelectorAll("[data-unblock]").forEach((b) => b.addEventListener("click", async () => { await muRule("blocked", b.dataset.unblock, b.dataset.v, false); muLibrary(el); }));
  el.querySelectorAll("[data-unapprove]").forEach((b) => b.addEventListener("click", async () => { await muRule("approved", b.dataset.unapprove, b.dataset.v, false); muLibrary(el); }));
  if (blocked.tracks.length) {
    const d = await api("/api/music/library?status=blocked&limit=500");
    const box = $("#mu-blk-songs");
    if (box) { box.innerHTML = muRowsHtml(d.tracks.filter((t) => blocked.tracks.includes(t.id))); muWireRows(box, d.tracks.filter((t) => blocked.tracks.includes(t.id)), { type: "ids", id: "" }); }
  }
  $("#mu-file").addEventListener("change", async (e) => {
    const files = [...e.target.files];
    for (const [k, f] of files.entries()) {
      $("#mu-up").textContent = `Uploading ${k + 1} of ${files.length}: ${f.name}…`;
      const send = (force) => fetch(`/api/music?filename=${encodeURIComponent(f.name)}${force ? "&force=true" : ""}`, { method: "POST", body: f, credentials: "same-origin",
        headers: { "X-Solstone": "1", "Content-Type": f.type || "application/octet-stream" } });
      try {
        let r = await send(false);
        if (r.status === 409) {
          const why = (await r.json().catch(() => ({}))).detail || "It's already in the library";
          if (await confirmBox(`${f.name}`, `${esc(why)}. Upload another copy anyway?`, "Upload anyway", false)) r = await send(true);
          else continue;
        }
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
      } catch (err) { showToast(`${esc(f.name)}: ${esc(err.message)}`, 5000); }
    }
    reload();
  });
  el.querySelectorAll(".fws-tracks li").forEach((li) => {
    const id = li.dataset.id, ids = s.main.map((t) => t.id), i = ids.indexOf(id);
    li.querySelector("[data-title]").addEventListener("change", (e) => post("/api/music", { titles: { [id]: e.target.value } }, "PUT").then(reload));
    const move = (to) => { const o = [...ids]; o.splice(i, 1); o.splice(to, 0, id); post("/api/music", { order: o }, "PUT").then(reload); };
    li.querySelector("[data-up]").addEventListener("click", () => move(i - 1));
    li.querySelector("[data-down]").addEventListener("click", () => move(i + 1));
    li.querySelector("[data-del]").addEventListener("click", async () => {
      if (!(await confirmBox("Delete this track?", esc(s.main[i].title), "Delete"))) return;
      await api(`/api/music/${id}`, { method: "DELETE" }).catch((err) => showToast(esc(err.message), 3000));
      reload();
    });
  });
  if (x.scanning) setTimeout(() => { if ($("#mu-rescan") || $(".mu-lib")) muLibrary(el); }, 3000);
}
