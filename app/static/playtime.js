/* Solstone — Manage → Play time (admins): bedtimes, daily screen time and each player's settings, in one place.
   The server side is playtime.py; guard.py enforces it in the game. */

const PT_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const pt = { data: null };

async function viewPlaytime() {
  if (!isAdmin()) { location.replace("#/"); return; }
  curSid = null;
  document.title = `Play time · ${SITE_NAME}`;
  fillServersMenu(state.servers, null);
  pt.data = await api("/api/settings/playtime");
  setView(`<div class="fwe-head"><h1>Play time</h1>
      <p class="muted">When the servers close for the night, how long everyone can play each day, and who it applies to. Everything about play time is here.</p></div>
    <form id="pt-form" class="pt-page"></form>`);
  renderPlaytime();
}

const ptMins = (s) => { const m = Math.floor((s || 0) / 60), h = Math.floor(m / 60); return s ? (h ? `${h} h ${m % 60} min` : `${m} min`) : "—"; };
const ptList = (v) => String(v || "").split(/[ ,]+/).map(Number).filter((n) => n > 0 && n <= 120);

function ptRuleHtml(r, i) {
  const servers = pt.data.servers.filter((s) => s.java);
  const all = r.servers === "all";
  return `<div class="pt-rule ${r.enabled ? "" : "off"}" data-i="${i}">
    <div class="pt-rule-head">
      <input class="input sm" name="name" value="${esc(r.name)}" aria-label="Name of this bedtime" maxlength="40">
      <label class="check"><input type="checkbox" name="enabled" ${r.enabled ? "checked" : ""}> On</label>
      <span style="flex:1"></span>
      <button type="button" class="btn sm" data-pt-del>Remove</button>
    </div>
    <div class="pt-rule-row">
      <span class="pt-days">${PT_DAYS.map((d, n) => `<label class="check"><input type="checkbox" name="day" value="${n}" ${r.days.includes(n) ? "checked" : ""}> ${d}</label>`).join("")}</span>
    </div>
    <div class="pt-rule-row">
      <label>Bedtime <input class="input sm" type="time" name="start" value="${esc(r.start)}"></label>
      <label>Wake up <input class="input sm" type="time" name="end" value="${esc(r.end)}"></label>
      <span class="muted small">${r.start > r.end ? "Overnight: a night's bedtime runs into the next morning." : ""}</span>
    </div>
    <div class="pt-rule-row pt-servers">
      <label class="check"><input type="checkbox" name="all" ${all ? "checked" : ""}> <b>All servers</b></label>
      ${servers.map((s) => `<label class="check"><input type="checkbox" name="srv" value="${esc(s.id)}" ${all || r.servers.includes(s.id) ? "checked" : ""} ${all ? "disabled" : ""}> ${esc(s.name)}</label>`).join("")}
    </div></div>`;
}

function renderPlaytime() {
  const d = pt.data, form = $("#pt-form");
  const javaServers = d.servers.filter((s) => s.java);
  const covers = javaServers.map((s) => {
    const names = d.bedtimes.filter((r) => r.enabled && (r.servers === "all" || r.servers.includes(s.id))).map((r) => r.name);
    return `<li><b>${esc(s.name)}</b>: ${names.length ? esc(names.join(", ")) : '<span class="muted">no bedtime</span>'}</li>`;
  }).join("");
  form.innerHTML = `
    <section class="panel"><div class="section-head"><h2>🌙 Bedtimes</h2></div>
      <p class="muted small">Each bedtime has its days, times and servers, so school nights and weekends can be different. At bedtime the world is saved and everyone it applies to is disconnected until wake-up time.</p>
      <div id="pt-rules">${d.bedtimes.map(ptRuleHtml).join("") || '<p class="muted">No bedtimes yet.</p>'}</div>
      <div class="btn-row"><button type="button" class="btn sm" id="pt-add">+ Add a bedtime</button></div>
      ${javaServers.length ? `<ul class="pt-covers">${covers}</ul>` : ""}
      <div class="pt-grid">
        <label>Warn in the game <small>minutes before, like 15, 5, 1</small><input class="input" name="warn_minutes" value="${esc(d.warn_minutes.join(", "))}"></label>
        <label>Goodbye message <small>Empty: “Bedtime! The server opens again at 7:00 AM.”</small><input class="input" name="message" maxlength="120" value="${esc(d.message)}"></label>
      </div>
      <label class="check pt-banner"><input type="checkbox" name="banner_show" ${d.banner.show ? "checked" : ""}> Count down on the website, from <input class="input sm" type="number" min="5" max="180" name="banner_minutes" value="${d.banner.minutes}" style="width:70px"> minutes before, then “asleep until…” overnight</label>
    </section>
    <section class="panel"><div class="section-head"><h2>⏳ Daily screen time</h2></div>
      <p class="muted small">Counted across every server, and every Minecraft name a person plays as. Set each person's limit below.</p>
      <div class="pt-grid">
        <label>At the limit
          <select class="input" name="limit_action">
            <option value="notify" ${d.limit_action !== "kick" ? "selected" : ""}>Warn them in the game and notify me</option>
            <option value="kick" ${d.limit_action === "kick" ? "selected" : ""}>Warn them, then disconnect them</option>
          </select></label>
        <label>Disconnect after <small>minutes past the limit</small><input class="input" type="number" min="1" max="30" name="grace_minutes" value="${d.grace_minutes}"></label>
        <label>Warn before the limit <small>minutes left, like 15, 5</small><input class="input" name="limit_warn" value="${esc(d.limit_warn.join(", "))}"></label>
      </div>
      ${d.notify_set ? "" : '<p class="muted small">To be notified when someone reaches their limit, set up <a href="#/manage/notifications">Notifications</a>.</p>'}
    </section>
    <section class="panel"><div class="section-head"><h2>👥 Each player</h2></div>
      ${d.rows.length ? `<div class="table-wrap"><table class="pt-people"><thead><tr><th>Player</th><th>Bedtime</th><th>Daily limit</th><th>Weekends</th><th>Today</th></tr></thead><tbody>
        ${d.rows.map((r) => `<tr data-key="${esc(r.key)}">
          <td><b>${esc(r.label)}</b>${r.account && (r.names.length > 1 || r.names[0] !== r.label) ? `<br><small class="muted">${esc(r.names.join(" + "))}</small>` : ""}</td>
          <td><label class="check"><input type="checkbox" name="bedtime" ${r.bedtime ? "checked" : ""}> ${r.bedtime ? "Applies" : "Stays up"}</label></td>
          <td><input class="input sm" type="number" min="0" max="1440" step="15" name="limit" value="${r.limit || ""}" placeholder="No limit" aria-label="Daily limit for ${esc(r.label)}"> <small class="muted">min</small></td>
          <td><input class="input sm" type="number" min="0" max="1440" step="15" name="weekend_limit" value="${r.weekend_limit || ""}" placeholder="Same" aria-label="Weekend limit for ${esc(r.label)}"> <small class="muted">min</small></td>
          <td class="muted">${ptMins(r.today)}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="muted small">Weekends are Saturday and Sunday. Leave <b>Weekends</b> empty to use the daily limit then too.</p>` : '<p class="muted">Players show here once they have joined a server.</p>'}
    </section>
    <div class="actions pt-save"><button class="btn primary" type="submit">Save play time</button></div>`;
  wirePlaytime(form);
}

function ptRead(form) {
  const rules = $$(".pt-rule", form).map((el) => {
    const v = (n) => el.querySelector(`[name=${n}]`);
    return { id: pt.data.bedtimes[+el.dataset.i]?.id || "", name: v("name").value, enabled: v("enabled").checked,
      start: v("start").value || "21:00", end: v("end").value || "07:00",
      days: [...el.querySelectorAll("[name=day]:checked")].map((x) => +x.value),
      servers: v("all").checked ? "all" : [...el.querySelectorAll("[name=srv]:checked")].map((x) => x.value) };
  });
  const people = {};
  $$(".pt-people tr[data-key]", form).forEach((tr) => {
    people[tr.dataset.key] = { bedtime: tr.querySelector("[name=bedtime]").checked,
      limit: +tr.querySelector("[name=limit]").value || 0, weekend_limit: +tr.querySelector("[name=weekend_limit]").value || 0 };
  });
  return { bedtimes: rules, warn_minutes: ptList(form.warn_minutes.value), message: form.message.value,
    limit_action: form.limit_action.value, grace_minutes: +form.grace_minutes.value || 5, limit_warn: ptList(form.limit_warn.value),
    people, banner: { show: form.banner_show.checked, minutes: +form.banner_minutes.value || 30 } };
}

function wirePlaytime(form) {
  const keep = () => { const r = ptRead(form); pt.data = { ...pt.data, ...r, banner: r.banner,
    rows: pt.data.rows.map((x) => ({ ...x, ...r.people[x.key] })) }; };
  $("#pt-add", form).addEventListener("click", () => {
    keep();
    const first = !pt.data.bedtimes.length;
    pt.data.bedtimes.push(first ? { id: "", name: "School nights", enabled: true, days: [6, 0, 1, 2, 3], start: "21:00", end: "07:00", servers: "all" }
      : { id: "", name: "Weekends", enabled: true, days: [4, 5], start: "22:30", end: "08:00", servers: "all" });
    renderPlaytime();
  });
  form.addEventListener("click", (e) => {
    const del = e.target.closest("[data-pt-del]");
    if (!del) return;
    keep();
    pt.data.bedtimes.splice(+del.closest(".pt-rule").dataset.i, 1);
    renderPlaytime();
  });
  form.addEventListener("change", (e) => {
    if (e.target.name === "all") {
      e.target.closest(".pt-servers").querySelectorAll("[name=srv]").forEach((c) => { c.disabled = e.target.checked; if (e.target.checked) c.checked = true; });
    }
    if (e.target.name === "bedtime") e.target.parentElement.lastChild.textContent = e.target.checked ? " Applies" : " Stays up";
    if (e.target.name === "enabled") e.target.closest(".pt-rule").classList.toggle("off", !e.target.checked);
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = ptRead(form);
    if (body.bedtimes.some((r) => !r.days.length)) { showError("Pick at least one day for each bedtime", 4000); return; }
    if (body.bedtimes.some((r) => r.servers !== "all" && !r.servers.length)) { showError("Pick the servers each bedtime is for", 4000); return; }
    try {
      pt.data = await post("/api/settings/playtime", body, "PUT");
      renderPlaytime(); showToast("Play time saved", 2500);
      appSky.board?.refresh();
    } catch (err) { showError(`Couldn't save: ${esc(err.message)}`, 5000); }
  });
}

// A line for a person elsewhere (the Users page): "90 min a day · bedtime applies".
function ptSummary(row) {
  if (!row) return "";
  const lim = row.limit ? `${row.limit} min a day${row.weekend_limit ? `, ${row.weekend_limit} at weekends` : ""}` : row.weekend_limit ? `${row.weekend_limit} min at weekends` : "no daily limit";
  return `${lim} · ${row.bedtime ? "bedtime applies" : "stays up after bedtime"}`;
}
