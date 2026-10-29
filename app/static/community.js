/* Solstone — votes (polls and build contests), messages with the admins, and their Manage tabs.
   The server side is community.py; "!vote 2" in the game is votegame.py. */

const cm = { tid: null };
const cmWhen = (ts) => new Date(ts * 1000).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const cmPara = (t) => esc(t).replace(/\n/g, "<br>");

// ---------------------------------------------------------------- unread badge (account button and menu)
async function cmRefreshUnread() {
  if (!me.user) return;
  try {
    const n = await api("/api/community/unread");
    const total = n.mine + (n.admin || 0) + (n.requests || 0);
    const badge = (el, count) => { if (el) { el.textContent = count ? String(count) : ""; el.hidden = !count; } };
    badge($("#account-unread"), total);
    badge($("#menu-unread"), n.mine);
    badge($("#menu-admin-unread"), n.admin);
    badge($("#menu-requests"), n.requests);
    const cur = $("#manage-nav [aria-current]")?.dataset.m;
    if (cur) setManageNav(cur);                       // the phone dropdown's count too
  } catch { /* offline for a moment */ }
}

// ---------------------------------------------------------------- votes (everyone signed in)
function cmVoteCard(p, admin = false) {
  const build = p.kind === "build";
  const max = Math.max(1, ...Object.values(p.counts || {}));
  const opts = p.options.map((o) => {
    const own = p.own.includes(o.id), picked = p.mine === o.id, n = p.counts?.[o.id];
    return `<li class="cm-opt ${picked ? "picked" : ""} ${own ? "own" : ""}">
      ${o.image ? `<img class="cm-opt-img" src="${esc(o.image)}" alt="" loading="lazy">` : ""}
      <div class="cm-opt-main"><b>${esc(o.text)}</b>${o.builders?.length ? `<small class="muted">Built by ${esc(o.builders.join(", "))}</small>` : ""}
        ${p.show_results ? `<div class="cm-bar"><span style="width:${Math.round(((n || 0) / max) * 100)}%"></span></div><small class="muted">${n || 0} vote${n === 1 ? "" : "s"}</small>` : ""}</div>
      ${p.open && !admin ? (own ? '<span class="muted small">Your build</span>'
        : `<button type="button" class="btn sm ${picked ? "primary" : ""}" data-vote="${p.id}" data-opt="${esc(o.id)}">${picked ? "✅ Your vote" : "Vote"}</button>`) : ""}</li>`;
  }).join("");
  const state = p.open ? (p.closes ? `Closes ${cmWhen(p.closes)}` : "Open") : `Closed${p.closed ? ` ${cmWhen(p.closed)}` : ""}`;
  return `<article class="panel cm-vote">
    <div class="cm-vote-head"><span class="cm-emoji">${build ? "🏆" : "🗳️"}</span><div><h3>${esc(p.question)}</h3>
      <small class="muted">${build ? "Build contest · " : ""}${esc(state)}${p.show_results ? ` · ${p.total} vote${p.total === 1 ? "" : "s"}` : ""}</small></div></div>
    ${p.detail ? `<p>${cmPara(p.detail)}</p>` : ""}
    <ul class="cm-opts">${opts}</ul>
    ${p.open && !p.show_results ? `<p class="muted small">${p.results === "closed" ? "The results show when the vote closes." : "Vote to see how it's going."} You can change your vote until it closes.</p>` : ""}
    ${p.open && !admin ? `<p class="muted small">In the game: type <code>!vote 1</code>, <code>!vote 2</code>… for the newest vote.</p>` : ""}
  </article>`;
}

async function viewVotes() {
  curSid = null;
  document.title = `Votes · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  const d = await api("/api/community/votes");
  setView(`<div class="fwe-head"><h1>Votes</h1>
      <p class="muted">Have your say! Pick one choice in each vote. Nobody sees who voted for what, only how many votes each one has.${isAdmin() ? ' Make a new vote in <a href="#/manage/votes">Manage → Votes</a>.' : ""}</p></div>
    <div id="cm-votes">${d.open.map((p) => cmVoteCard(p)).join("") || '<div class="panel"><p class="muted">No votes open right now.</p></div>'}</div>
    ${d.closed.length ? `<section class="section"><div class="section-head"><h2>Finished</h2></div>${d.closed.map((p) => cmVoteCard(p)).join("")}</section>` : ""}`);
  $$("[data-vote]", view()).forEach((b) => b.addEventListener("click", async () => {
    try {
      await post(`/api/community/votes/${b.dataset.vote}`, { option: b.dataset.opt });
      showToast("🗳️ Thanks for voting!", 2000);
      viewVotes();
    } catch (err) { showError(esc(err.message), 4000); }
  }));
}

// ---------------------------------------------------------------- messages (a player and the admins)
function cmThreadList(threads, admin) {
  if (!threads.length) return `<p class="muted">${admin ? "No messages yet." : "No messages yet. Write to the admins with the button above."}</p>`;
  return `<ul class="cm-threads">${threads.map((t) => {
    const unread = admin ? t.unread_admin : t.unread_user;
    return `<li><a href="#/${admin ? "manage/messages" : "messages"}/${t.id}" class="${unread ? "unread" : ""}">
      <span class="cm-dot" ${unread ? "" : "hidden"}></span><b>${esc(t.subject)}</b>
      <small class="muted">${admin ? `${esc(t.with)} · ` : ""}${t.kind === "notice" ? "Notice · " : ""}${esc(cmWhen(t.updated))}</small></a></li>`;
  }).join("")}</ul>`;
}

function cmThreadHtml(t, admin) {
  const tools = admin
    ? `<button type="button" class="btn sm" data-archive="${t.archived ? "0" : "1"}">${t.archived ? "Take out of the archive" : "🗄️ Archive"}</button>
       <button type="button" class="btn sm danger" data-delete>Delete for everyone</button>`
    : `<button type="button" class="btn sm" data-delete>Remove from my messages</button>`;
  return `<div class="panel cm-thread"><div class="cm-thread-top"><a href="#/${admin ? "manage/messages" : "messages"}" class="small">← All messages</a>
    <span class="btn-row">${tools}</span></div>
    <h2>${esc(t.subject)}</h2>${admin ? `<p class="muted small">With <b>${esc(t.with)}</b></p>` : ""}
    <div class="cm-msgs">${t.messages.map((m) => `<div class="cm-msg ${m.from_admin ? "from-admin" : "from-player"}">
      <small class="muted"><b>${esc(m.from_admin ? (admin ? m.author : `${m.author} (admin)`) : m.author)}</b> · ${esc(cmWhen(m.ts))}</small>
      <div>${cmPara(m.body)}</div></div>`).join("")}</div>
    ${t.kind === "notice" && !admin ? '<p class="muted small">This is a notice from Solstone: there\'s nothing to answer.</p>'
      : `<form id="cm-reply" class="cm-reply"><textarea class="input" name="body" rows="3" maxlength="1000" placeholder="Write an answer…" required></textarea>
        <div class="actions"><button class="btn primary" type="submit">Send</button></div></form>`}</div>`;
}

function cmWireReply(t, again, admin = false) {
  const back = admin ? "#/manage/messages" : "#/messages";
  $("[data-delete]")?.addEventListener("click", async () => {
    const ok = admin ? await confirmBox("Delete this conversation?", "It's gone for good, for the player too.", "Delete")
      : await confirmBox("Remove it from your messages?", "The admins still have it. If someone writes in it again, it comes back.", "Remove", false);
    if (!ok) return;
    try { await api(`/api/community/messages/${t.id}`, { method: "DELETE" }); location.hash = back; }
    catch (err) { showError(esc(err.message), 4000); }
  });
  $("[data-archive]")?.addEventListener("click", async (e) => {
    try { await post(`/api/community/admin/messages/${t.id}/archive`, { archived: e.target.dataset.archive === "1" }); location.hash = back; }
    catch (err) { showError(esc(err.message), 4000); }
  });
  $("#cm-reply")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await post(`/api/community/messages/${t.id}`, { body: e.target.body.value }); showToast("Sent", 1500); again(); }
    catch (err) { showError(esc(err.message), 4000); }
  });
}

async function viewMessages(tid) {
  curSid = null;
  document.title = `Messages · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  if (tid) {
    const t = await api(`/api/community/messages/${encodeURIComponent(tid)}`);
    setView(`<div class="fwe-head"><h1>Messages</h1></div>${cmThreadHtml(t, false)}`);
    cmWireReply(t, () => viewMessages(tid));
    cmRefreshUnread();
    return;
  }
  const d = await api("/api/community/messages");
  setView(`<div class="fwe-head"><h1>Messages</h1>
      <p class="muted">${isAdmin() ? 'You\'re an admin: players\' messages, and writing to them, are in <a href="#/manage/messages">Manage → Messages</a>. Notices for you come here.'
        : "Write to the admins: an idea, something that's wrong, a question. Only the admins see it, and their answers come here. Notices (a vote closed, you won) come here too."}</p></div>
    <div class="panel"><button type="button" class="btn primary" id="cm-new" ${isAdmin() ? "hidden" : ""}>✉️ Write to the admins</button>
      <form id="cm-new-form" class="cm-new" hidden>
        <label>What's it about?<select class="input" name="kind">${Object.entries(d.kinds).map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join("")}</select></label>
        <label>Subject <small>Optional</small><input class="input" name="subject" maxlength="80"></label>
        <label>Message<textarea class="input" name="body" rows="4" maxlength="1000" required></textarea></label>
        <div class="actions"><button type="button" class="btn" id="cm-cancel">Cancel</button><button class="btn primary" type="submit">Send</button></div></form>
      ${cmThreadList(d.threads, false)}</div>`);
  const form = $("#cm-new-form");
  $("#cm-new").addEventListener("click", () => { form.hidden = false; $("#cm-new").hidden = true; form.body.focus(); });
  $("#cm-cancel").addEventListener("click", () => { form.hidden = true; $("#cm-new").hidden = false; });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await post("/api/community/messages", { kind: form.kind.value, subject: form.subject.value, body: form.body.value });
      showToast("Sent to the admins", 2000);
      location.hash = `#/messages/${r.id}`;
    } catch (err) { showError(esc(err.message), 4000); }
  });
  cmRefreshUnread();
}

// ---------------------------------------------------------------- Manage → Messages
async function viewManageMessages(tid) {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = `Messages · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  if (tid) {
    const t = await api(`/api/community/messages/${encodeURIComponent(tid)}`);
    setView(`<div class="fwe-head"><h1>Messages</h1></div>${cmThreadHtml(t, true)}`);
    cmWireReply(t, () => viewManageMessages(tid), true);
    cmRefreshUnread();
    return;
  }
  const d = await api("/api/community/admin/messages");
  setView(`<div class="fwe-head"><h1>Messages</h1>
      <p class="muted">Messages from players, and yours to them. Only you (the admins) and that player see each one. Players can't message each other. Get a notification for new ones: <a href="#/manage/notifications">Notifications</a> → <i>A player sends a message</i>.</p></div>
    <div class="panel"><button type="button" class="btn primary" id="cm-new">✉️ Write to players</button>
      <form id="cm-new-form" class="cm-new" hidden>
        <fieldset class="checks"><legend>To</legend>
          <label class="check"><input type="checkbox" name="all"> <b>Every player</b></label>
          <div class="day-checks">${d.players.map((p) => `<label class="check"><input type="checkbox" name="to" value="${p.id}"> ${esc(p.name)}</label>`).join("") || '<span class="muted">No player accounts yet.</span>'}</div></fieldset>
        <label>Subject<input class="input" name="subject" maxlength="80" required placeholder="You won the build contest!"></label>
        <label>Message<textarea class="input" name="body" rows="4" maxlength="1000" required></textarea></label>
        <div class="actions"><button type="button" class="btn" id="cm-cancel">Cancel</button><button class="btn primary" type="submit">Send</button></div></form>
      ${cmThreadList(d.threads.filter((t) => !t.archived), true)}
      ${d.threads.some((t) => t.archived) ? `<details class="cm-archive"><summary>🗄️ Archived (${d.threads.filter((t) => t.archived).length})</summary>${cmThreadList(d.threads.filter((t) => t.archived), true)}</details>` : ""}</div>`);
  const form = $("#cm-new-form");
  $("#cm-new").addEventListener("click", () => { form.hidden = false; $("#cm-new").hidden = true; });
  $("#cm-cancel").addEventListener("click", () => { form.hidden = true; $("#cm-new").hidden = false; });
  form.all.addEventListener("change", () => $$("[name=to]", form).forEach((c) => { c.disabled = form.all.checked; }));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const to = form.all.checked ? "all" : $$("[name=to]:checked", form).map((c) => +c.value);
    try {
      const r = await post("/api/community/admin/messages", { to, subject: form.subject.value, body: form.body.value });
      showToast(`Sent to ${r.sent} player${r.sent === 1 ? "" : "s"}`, 2500);
      viewManageMessages();
    } catch (err) { showError(esc(err.message), 4000); }
  });
  cmRefreshUnread();
}

// ---------------------------------------------------------------- Manage → Votes
async function viewManageVotes() {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = `Votes · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  const [list, names] = await Promise.all([api("/api/community/admin/votes"), api("/api/players/all").catch(() => [])]);
  cm.names = names;
  setView(`<div class="fwe-head"><h1>Votes</h1>
      <p class="muted">Polls and build contests for players to vote on, on the <a href="#/votes">Votes</a> page or with <code>!vote</code> in the game. A new vote is announced in the game and shown as a banner. When it closes, the result is announced and everyone who voted gets a message (and the winning builders a congratulations). Only totals are shown, never who voted for what.</p></div>
    <div class="panel"><button type="button" class="btn primary" id="cmv-new">+ New vote</button><div id="cmv-form"></div></div>
    <datalist id="cmv-names">${names.map((n) => `<option value="${esc(n)}">`).join("")}</datalist>
    <div id="cmv-list">${list.map((p) => `<div class="cmv-item">${cmVoteCard(p, true)}
      <div class="btn-row cmv-actions">${p.open ? `<button class="btn sm" data-edit="${p.id}">Edit</button><button class="btn sm" data-close="${p.id}">Close it now</button>` : ""}
        <button class="btn sm danger" data-del="${p.id}">Delete</button></div></div>`).join("") || '<p class="muted">No votes yet.</p>'}</div>`);
  $("#cmv-new").addEventListener("click", () => cmVoteForm(null));
  $$("[data-edit]").forEach((b) => b.addEventListener("click", () => cmVoteForm(list.find((p) => p.id === +b.dataset.edit))));
  $$("[data-close]").forEach((b) => b.addEventListener("click", async () => {
    if (!(await confirmBox("Close this vote now?", "The result is announced in the game and everyone who voted gets a message.", "Close it", false))) return;
    try { const r = await post(`/api/community/admin/votes/${b.dataset.close}/close`, {}); showToast(esc(r.result), 4000); viewManageVotes(); }
    catch (err) { showError(esc(err.message), 4000); }
  }));
  $$("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    if (!(await confirmBox("Delete this vote?", "It's gone for everyone, with its votes.", "Delete"))) return;
    try { await api(`/api/community/admin/votes/${b.dataset.del}`, { method: "DELETE" }); viewManageVotes(); }
    catch (err) { showError(esc(err.message), 4000); }
  }));
}

function cmOptRow(o = {}, build = false) {
  return `<div class="cmv-opt" data-id="${esc(o.id || "")}">
    <input class="input" name="text" maxlength="80" placeholder="${build ? "The build's name (a castle, a farm…)" : "A choice"}" value="${esc(o.text || "")}">
    <span class="cmv-build" ${build ? "" : "hidden"}>
      <input class="input" name="builders" list="cmv-names" placeholder="Built by (names, with commas)" value="${esc((o.builders || []).join(", "))}">
      <label class="btn sm">📷 Picture<input type="file" accept="image/*" name="pic" hidden></label>
      <input type="hidden" name="image" value="${esc((o.image || "").split("/").pop())}">
      <img class="cmv-thumb" ${o.image ? `src="${esc(o.image)}"` : "hidden"} alt=""></span>
    <button type="button" class="btn sm" data-rm aria-label="Remove this choice">✕</button></div>`;
}

function cmVoteForm(p) {
  const build = p?.kind === "build";
  const local = (ts) => { if (!ts) return ""; const d = new Date(ts * 1000); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
  const el = $("#cmv-form");
  $("#cmv-new").hidden = true;
  el.innerHTML = `<form class="cmv-form" id="cmv-f">
    <div class="btn-row"><label class="check"><input type="radio" name="kind" value="poll" ${build ? "" : "checked"}> 🗳️ Poll</label>
      <label class="check"><input type="radio" name="kind" value="build" ${build ? "checked" : ""}> 🏆 Build contest <small class="muted">(say who built each one: nobody can vote for their own)</small></label></div>
    <label>Question<input class="input" name="question" maxlength="120" required value="${esc(p?.question || "")}" placeholder="What should we build next?"></label>
    <label>More about it <small>Optional</small><textarea class="input" name="detail" rows="2" maxlength="400">${esc(p?.detail || "")}</textarea></label>
    <div id="cmv-opts">${(p?.options || [{}, {}]).map((o) => cmOptRow(o, build)).join("")}</div>
    <button type="button" class="btn sm" id="cmv-add">+ Add a choice</button>
    <div class="pt-grid">
      <label>Closes <small>Empty: stays open until you close it</small><input class="input" type="datetime-local" name="closes" value="${local(p?.closes)}"></label>
      <label>Results<select class="input" name="results"><option value="voted" ${p?.results !== "closed" ? "selected" : ""}>Shown to each person once they've voted</option>
        <option value="closed" ${p?.results === "closed" ? "selected" : ""}>Only when the vote closes</option></select></label>
    </div>
    <div class="actions"><button type="button" class="btn" id="cmv-cancel">Cancel</button><button class="btn primary" type="submit">${p ? "Save" : "Start the vote"}</button></div></form>`;
  const f = $("#cmv-f");
  const kind = () => f.querySelector("[name=kind]:checked").value;
  f.addEventListener("change", async (e) => {
    if (e.target.name === "kind") $$(".cmv-build", f).forEach((s) => { s.hidden = kind() !== "build"; });
    if (e.target.name === "pic" && e.target.files[0]) {
      const file = e.target.files[0], row = e.target.closest(".cmv-opt");
      try {
        const r = await fetch("/api/posts/images", { method: "POST", credentials: "same-origin", headers: { "X-Solstone": "1", "Content-Type": file.type || "application/octet-stream" }, body: file });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || `Upload failed (${r.status})`);
        row.querySelector("[name=image]").value = d.url.split("/").pop();
        const img = row.querySelector(".cmv-thumb"); img.src = d.url; img.hidden = false;
      } catch (err) { showError(esc(err.message), 5000); }
    }
  });
  $("#cmv-add").addEventListener("click", () => $("#cmv-opts").insertAdjacentHTML("beforeend", cmOptRow({}, kind() === "build")));
  f.addEventListener("click", (e) => { if (e.target.closest("[data-rm]")) e.target.closest(".cmv-opt").remove(); });
  $("#cmv-cancel").addEventListener("click", () => { el.innerHTML = ""; $("#cmv-new").hidden = false; });
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { kind: kind(), question: f.question.value, detail: f.detail.value, results: f.results.value,
      closes_ts: f.closes.value ? new Date(f.closes.value).getTime() / 1000 : null,
      options: $$(".cmv-opt", f).map((r) => ({ id: r.dataset.id, text: r.querySelector("[name=text]").value, image: r.querySelector("[name=image]").value,
        builders: r.querySelector("[name=builders]").value.split(",").map((x) => x.trim()).filter(Boolean) })) };
    try {
      if (p) await post(`/api/community/admin/votes/${p.id}`, body, "PUT");
      else await post("/api/community/admin/votes", body);
      showToast(p ? "Saved" : "🗳️ The vote is open!", 2500);
      viewManageVotes();
    } catch (err) { showError(esc(err.message), 5000); }
  });
}
