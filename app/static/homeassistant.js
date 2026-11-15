/* Solstone: Manage → Solstone → Home Assistant. A key for Home Assistant (read-only, shown once), and the settings to
   paste into Home Assistant's configuration.yaml: every server's status as sensors. Loaded after app.js. */

async function viewHomeAssistant() {
  if (!isAdmin()) { location.replace("#/"); return; }
  document.title = `Home Assistant · ${SITE_NAME}`;
  let d;
  try { d = await api("/api/manage/ha"); }
  catch (err) { setView(`<div class="panel"><p>Couldn't load this: ${esc(err.message)}</p></div>`); return; }
  let base = "";
  try { base = localStorage.getItem("solstone-ha-base") || ""; } catch { /* fine */ }
  base ||= d.base || location.origin;
  const when = (ts) => ts ? fmtAgo(ts) : "never";
  setView(`<div class="fwe-head"><h1>🏠 Home Assistant</h1>
      <p class="muted">Every server's status in Home Assistant, beside everything else you keep an eye on there: up or not, who's on, TPS, CPU,
      memory, uptime, today's play, backups, the full copy, the Xbox friend, and anyone asking to join. Home Assistant asks Solstone every 30 seconds.</p></div>
    <section class="panel ha-steps"><h2>Set it up</h2>
      <ol>
        <li><b>Make a key</b> below and copy the line it gives you into Home Assistant's <code>secrets.yaml</code>.</li>
        <li><b>Write the settings</b> below and paste them into <code>configuration.yaml</code> (if it already has a <code>rest:</code> section, put the <code>- resource:</code> part under that one).</li>
        <li>In Home Assistant: <b>Developer tools → YAML → Check configuration</b>, then <b>Restart</b>.</li>
        <li>The sensors appear as <code>sensor.&lt;server&gt;_players_online</code>, <code>binary_sensor.&lt;server&gt;_online</code> and so on: add them to a dashboard (an Entities card), or use them in automations.</li>
      </ol>
      <p class="muted small">Added a server, or renamed one? Write the settings again and paste them over the old ones.</p>
    </section>
    <section class="panel"><div class="section-head"><h2>🔑 Keys</h2></div>
      <p class="muted small">A key can only read this status: it can't sign in, change anything, or see anything else. Remove it and Home Assistant stops getting it.</p>
      <div id="ha-keys"></div>
      <form id="ha-new" class="ha-new">
        <label>Name <input class="input" name="name" maxlength="60" value="Home Assistant"></label>
        <label class="check"><input type="checkbox" name="names" checked> <span><b>With player names</b><br><small class="muted">who's on and how long each played today, as attributes. Off: counts only</small></span></label>
        <button class="btn primary" type="submit">Make a key</button>
      </form>
      <div id="ha-made"></div>
    </section>
    <section class="panel"><div class="section-head"><h2>📋 The settings to paste</h2></div>
      <label class="ha-field">Solstone's address, as Home Assistant reaches it <small class="muted">At home, its address on your network is best, like <code>http://192.168.1.20:8085</code> (it doesn't depend on the internet). Otherwise the website's.</small>
        <input class="input" id="ha-base" value="${esc(base)}" placeholder="http://192.168.1.20:8085"></label>
      <div class="btn-row"><button class="btn primary" type="button" id="ha-write">Write the settings</button></div>
      <div id="ha-yaml"></div>
    </section>`);
  const paintKeys = (list) => {
    $("#ha-keys").innerHTML = list.length ? `<div class="ha-keylist">${list.map((k) => `<div class="ha-key" data-kid="${esc(k.id)}">
        <div><b>${esc(k.name)}</b> <span class="muted small">…${esc(k.hint)} · made ${esc(when(k.created))} · last used ${esc(when(k.last_used))}</span></div>
        <label class="check small"><input type="checkbox" data-names ${k.names ? "checked" : ""}> player names</label>
        <button class="btn sm danger" type="button" data-rm>Remove</button></div>`).join("")}</div>`
      : `<p class="muted">No keys yet.</p>`;
    $$("#ha-keys [data-kid]").forEach((row) => {
      row.querySelector("[data-names]").addEventListener("change", async (e) => {
        try { paintKeys((await post(`/api/manage/ha/keys/${row.dataset.kid}`, { names: e.target.checked }, "PUT")).keys); showToast(e.target.checked ? "Names on" : "Counts only", 2000); }
        catch (err) { showError(esc(err.message), 4000); }
      });
      row.querySelector("[data-rm]").addEventListener("click", async (e) => {
        if (!sureTwice(e.currentTarget, "Sure? Remove")) return;
        try { paintKeys((await api(`/api/manage/ha/keys/${row.dataset.kid}`, { method: "DELETE" })).keys); showToast("Removed: it doesn't work any more", 2500); }
        catch (err) { showError(esc(err.message), 4000); }
      });
    });
  };
  paintKeys(d.keys);
  const copyBox = (id, text) => `<div class="ha-copy"><pre id="${id}">${esc(text)}</pre><button class="btn sm" type="button" data-copyfrom="${id}">Copy</button></div>`;
  const wireCopy = (root) => root.querySelectorAll("[data-copyfrom]").forEach((b) => b.addEventListener("click", () => {
    navigator.clipboard?.writeText($("#" + b.dataset.copyfrom).textContent); showToast("Copied", 1500);
  }));
  $("#ha-new").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const r = await post("/api/manage/ha/keys", { name: f.get("name"), names: !!f.get("names") });
      paintKeys(r.keys);
      const box = $("#ha-made");
      box.innerHTML = `<div class="notice ha-once"><b>Here's the key. It's shown this once</b> (Solstone keeps only a fingerprint of it): copy this line into Home Assistant's <code>secrets.yaml</code>.
        ${copyBox("ha-secret", `solstone_auth: "Bearer ${r.key}"`)}</div>`;
      wireCopy(box);
    } catch (err) { showError(esc(err.message), 4000); }
  });
  $("#ha-write").addEventListener("click", async () => {
    const b = $("#ha-base").value.trim();
    try { localStorage.setItem("solstone-ha-base", b); } catch { /* fine */ }
    const out = $("#ha-yaml");
    out.innerHTML = `<p class="muted">Writing…</p>`;
    try {
      const r = await api(`/api/manage/ha/yaml?base=${encodeURIComponent(b)}`);
      out.innerHTML = `<p class="muted small">For ${r.servers.map((s) => `<b>${esc(s.name)}</b> (<code>${esc(s.key)}</code>)`).join(", ")}. Paste into <code>configuration.yaml</code>:</p>${copyBox("ha-conf", r.yaml)}`;
      wireCopy(out);
    } catch (err) { out.innerHTML = `<p class="notice">${esc(err.message)}</p>`; }
  });
}
