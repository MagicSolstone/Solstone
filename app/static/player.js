/* Solstone: a player's page (Inventory, Play history, Travels, Statistics, Advancements, Fishing), with their trophies,
   favourites and a Bedrock account linked to a Java one. Loaded after app.js and uses its helpers. */
// ---------------------------------------------------------------- player page
async function viewPlayer(sid, uuid, tab = "inventory") {
  const s = await serverFrame(sid, "overview");
  let p;
  try { p = await api(`/api/servers/${sid}/players/${uuid}`); }
  catch (e) { setView(serverHeader(s, "overview") + `<div class="empty"><h3>Player not found</h3><p>${esc(e.message)}</p></div>`); wireHeader(s); return; }
  const base = `#/s/${encodeURIComponent(sid)}/p/${uuid}`;
  const tabs = [["inventory", "Inventory"], ["history", "Play history"], ["travels", "🗺 Travels"], ["stats", "Statistics"], ["advancements", "Advancements"],
    ...(s.fishing_journal ? [["fishing", "Fishing"]] : [])];
  setView(`<a class="back" href="#/s/${encodeURIComponent(sid)}">← ${esc(s.name)}</a>
    <div id="hero">${playerHero(p)}</div>
    <div id="hero-acts">${giveBtn(p)}</div>
    <div id="plink"></div>
    <div id="strip">${statStrip(p)}</div>
    <div id="trophies"></div>
    <div id="favs">${favouritesHtml(p.together?.stats || p.stats)}</div>
    <nav class="tabs" aria-label="Player sections">${tabs.map(([k, l]) => `<a href="${base}${k === "inventory" ? "" : "/" + k}" ${k === tab ? 'aria-current="page"' : ""}>${l}</a>`).join("")}</nav>
    <div id="player-tab"></div>`);
  document.title = `${p.name} · ${s.name}`;
  const renderTab = () => {
    state.items.clear();
    const el = $("#player-tab");
    if (!el) return;
    el.onclick = null;                                  // (a tab's own clicks, like Travels', go with it)
    // All together (someone with more than one Minecraft account): statistics added up, advancements from whichever
    // got each first, and every account's play history. The inventory is always this one character's.
    const all = !!p.together && !stripAlone;
    const shown = all ? { ...p, stats: p.together.stats, advancements: p.together.advancements } : p;
    const note = all && tab !== "inventory" ? `<p class="muted small together-note">All of ${esc(p.together.accounts.map((a) => a.name).join(" + "))} together. <button type="button" class="link-btn" data-strip="one">Just ${esc(p.name)}</button></p>` : "";
    if (tab === "inventory") el.innerHTML = inventoryHtml(p);
    else if (tab === "stats") { renderStats(el, shown); el.insertAdjacentHTML("afterbegin", note); }
    else if (tab === "advancements") el.innerHTML = note + advancementsHtml(shown);
    else if (tab === "history") { renderPlayerHistory(el, sid, p, all); }
    else if (tab === "fishing") renderPlayerFishing(el, sid, p);
    else if (tab === "travels") renderPlayerTravels(el, sid, p);
  };
  renderTab();
  // Another tab of the same player: just that part changes, so the page stays where it's scrolled to
  state.playerPage = { sid, uuid, setTab(t) {
    tab = tabs.some(([k]) => k === t) ? t : "inventory";
    $$('nav[aria-label="Player sections"] a').forEach((a) => { if (a.getAttribute("href") === `${base}${tab === "inventory" ? "" : "/" + tab}`) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
    hideTip();
    renderTab();
  } };
  loadTrophies(sid, p);
  loadBedrockLink(sid, p);
  $("#favs")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-fav]");
    if (b) openFavourites(p.name, p.together?.stats || p.stats, +b.dataset.fav);
  });
  const flip = (e) => {
    const b = e.target.closest("[data-strip]");
    if (b) { stripAlone = b.dataset.strip === "one"; $("#strip").innerHTML = statStrip(p); renderTab(); }
  };
  $("#strip").addEventListener("click", flip);
  $("#player-tab").addEventListener("click", flip);
  const acts = $("#hero-acts");
  const doIt = async (action, body, said) => {
    try {
      const r = await post(`/api/servers/${encodeURIComponent(sid)}/control/player/${encodeURIComponent(p.name)}/${action}`, body);
      const bad = (r.results || []).find((x) => x.ok === false);
      if (bad) showError(esc((bad.output || "The game said no").slice(0, 160)), 6000); else showToast(esc(said), 2500);
      return !bad;
    } catch (err) { showError(esc(err.message), 5000); return false; }
  };
  acts.addEventListener("click", async (e) => {
    if (e.target.closest("[data-give]")) { openGiveItem(sid, p.name); return; }
    const b = e.target.closest("button[data-pa]");
    if (!b) return;
    if (b.dataset.pa === "kick") {
      if (await confirmBox(`Kick ${p.name}?`, "They can join again right away unless bedtime or a screen-time limit is on.", "Kick")) doIt("kick", { reason: "Kicked by an admin" }, `Kicked ${p.name}`);
      return;
    }
    doIt(b.dataset.pa, {}, b.dataset.pa === "heal" ? `${p.name} healed and fed` : "Done");
  });
  acts.addEventListener("change", (e) => {
    const sel = e.target.closest("[data-tp], [data-gm]");
    if (!sel?.value) return;
    if (sel.matches("[data-gm]")) doIt("gamemode", { mode: sel.value }, `${p.name} is now in ${sel.value}`);
    else { const [action, target] = sel.value.split(":"); doIt(action, { target }, `${sel.selectedOptions[0].textContent}: done`); }
    sel.value = "";
  });
  acts.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (await doIt("message", { message: new FormData(e.target).get("message") }, "Message sent")) e.target.reset();
  });
  if (p.online) {
    let last = JSON.stringify(p.data);
    every(4000, async () => {
      const n = await api(`/api/servers/${sid}/players/${uuid}`).catch(() => null);
      if (!n || !$("#hero")) return;
      const sig = JSON.stringify(n.data);
      $("#hero").innerHTML = playerHero(n);
      if (n.online !== p.online && !acts.contains(document.activeElement)) { acts.innerHTML = giveBtn(n); p.online = n.online; }     // they left
      if (sig !== last) {
        last = sig; p = n;
        $("#strip").innerHTML = statStrip(n);
        if (tab === "inventory" && !document.querySelector(".modal")) { hideTip(); renderTab(); }
      }
    });
  }
}

// Giving needs the player in the game, and only admins can do it.
// Teleporting likewise; "others" are the other players online now.
// An admin's buttons for someone playing now, on their own page: the same as the Control tab has for them.
const giveBtn = (p) => {
  if (!isAdmin() || !p.online) return "";
  const others = (state.servers.find((x) => x.id === curSid)?.online || []).filter((n) => n.toLowerCase() !== p.name.toLowerCase());
  return `<div class="btn-row hero-actions"><button class="btn sm" type="button" data-pa="heal">❤ Heal &amp; feed</button>
    <button class="btn sm" type="button" data-give>🎁 Give items</button>
    <select class="input sm" data-tp aria-label="Teleport ${esc(p.name)}"><option value="">📍 Teleport…</option>
      <option value="tp_spawn">Send to spawn</option><option value="tp_bed">Send to their bed</option>
      ${others.map((n) => `<option value="tp_to_player:${esc(n)}">Send to ${esc(n)}</option>`).join("")}
      ${others.map((n) => `<option value="bring:${esc(n)}">Bring ${esc(n)} here</option>`).join("")}</select>
    <select class="input sm" data-gm aria-label="Game mode for ${esc(p.name)}"><option value="">🎮 Game mode…</option>${["survival", "creative", "adventure", "spectator"].map((m) => `<option value="${m}">${humanize(m)}</option>`).join("")}</select>
    <button class="btn sm danger" type="button" data-pa="kick">Kick</button></div>
    <form class="btn-row hero-msg" data-msg><input class="input sm grow" name="message" placeholder="A private message to ${esc(p.name)}" maxlength="256" required><button class="btn sm">Send</button></form>`;
};

function playerHero(p) {
  const d = p.data;
  const body = p.uuid ? `<img src="/api/skins/${p.uuid.replace(/-/g, "")}/body.png?size=256" alt="${esc(p.name)}'s skin" data-fail="letter" data-letter="${esc(p.name[0])}">` : "";
  let presence;
  if (p.online) {
    presence = p.source === "live"
      ? `<span class="live-tag"><span class="status-dot on"></span>Playing now · live</span>`
      : `<span class="live-tag"><span class="status-dot on"></span>Playing now</span><span>Inventory from last save, ${esc(fmtAgo(p.as_of))}${p.live_available ? "" : " (turn on RCON for live data)"}</span>`;
  } else presence = `<span>Last seen ${esc(fmtAgo(p.last_seen))}</span>`;
  if (!d) return `<div class="player-hero"><div class="body-render">${body}</div><div><h1>${esc(p.name)}</h1><div class="presence">${presence}</div><p class="muted" style="margin-top:12px">No saved player data yet.</p></div></div>`;
  const pos = d.position;
  const effects = (d.effects || []).map((e) => `<span class="chip"><img src="${textureUrl(`mob_effect/${splitId(e.id)[1]}`)}" alt="" data-fail="remove"><b>${esc(effectName(e.id))} ${roman(e.amplifier + 1)}</b> ${e.duration > 0 && e.duration < 1e6 ? fmtDuration(e.duration) : ""}</span>`).join("");
  return `<div class="player-hero">
    <div class="body-render">${body}</div>
    <div>
      <h1>${esc(p.name)} ${p.op ? '<span class="op-badge">OP</span>' : ""}</h1>
      <div class="presence">${presence}</div>
      <div class="vitals">${heartsHtml(d.health, d.max_health)}${foodHtml(d.food)}${xpHtml(d.xp_level, d.xp_progress)}</div>
      <div class="chips">
        <span class="chip dim-tag ${dimClass(pos.dimension)}">${esc(dimName(pos.dimension))}</span>
        <span class="chip">X <b>${Math.round(pos.x)}</b> Y <b>${Math.round(pos.y)}</b> Z <b>${Math.round(pos.z)}</b></span>
        <span class="chip">${esc(humanize(d.gamemode))}${d.flying ? " · flying" : ""}</span>
        ${d.respawn ? `<span class="chip" title="Respawn point">Bed <b>${d.respawn.x}, ${d.respawn.y}, ${d.respawn.z}</b></span>` : ""}
        ${d.last_death ? `<span class="chip" title="Where they last died">Last death <b>${d.last_death.x}, ${d.last_death.y}, ${d.last_death.z}</b> ${esc(dimName(d.last_death.dimension))}</span>` : ""}
        ${fishingChip(p)}
        ${effects}
      </div>

    </div></div>`;
}

// The Tide fishing mod: level and title, a link to their fishing journal, more on hover.
function fishingChip(p) {
  const f = p.fishing;
  if (!f) return "";
  const tip = `${f.xp.toLocaleString()} fishing XP · ${f.species}/${f.species_total} kinds of fish · ${f.caught.toLocaleString()} caught${f.biggest ? ` · biggest: ${f.biggest.name}, ${fmtStat("grams", f.biggest.weight_g)}` : ""}`;
  return `<a class="chip chip-link" href="#/s/${encodeURIComponent(curSid)}/fishing/${encodeURIComponent(p.name)}" title="${esc(tip)}">🎣 Fishing <b>Lv ${f.level}</b> ${esc(f.title)}</a>`;
}

// One person with more than one Minecraft account: their progress all together (the default), or one account's.
// What's one character's own (level, health, inventory, advancements) stays on that account's page.
let stripAlone = false;
function statStrip(p) {
  const t = p.together;
  const h = (t && !stripAlone ? t.headline : p.headline) || {};
  const switcher = t ? `<div class="strip-together"><span>${t.accounts.map((a) => a.uuid === p.uuid ? `<b>${esc(a.name)}</b>`
      : `<a href="#/s/${encodeURIComponent(curSid)}/p/${a.uuid}">${esc(a.name)}</a>`).join(" + ")}</span>
    <span class="seg" role="group" aria-label="Whose numbers"><button type="button" data-strip="all" aria-pressed="${!stripAlone}">All together</button><button type="button" data-strip="one" aria-pressed="${stripAlone}">Just ${esc(p.name)}</button></span></div>` : "";
  const cells = [
    ...(typeof h.play_time === "number" ? [[fmtDuration(h.play_time), "Time played"]] : []),     // admins only
    [fmtNum(h.mob_kills), "Mobs defeated"], [fmtNum(h.deaths), "Deaths"],
    [fmtNum(h.blocks_mined), "Blocks mined"], [fmtDistance(h.distance_cm), "Distance travelled"], [fmtNum(h.items_crafted), "Items crafted"],
  ];
  return `${switcher}<div class="stat-strip">${cells.map(([v, k]) => `<div><div class="v">${esc(v)}</div><div class="k">${esc(k)}</div></div>`).join("")}</div>`;
}

function inventoryHtml(p) {
  const d = p.data;
  if (!d) return `<div class="empty"><h3>No inventory saved yet</h3><p>Minecraft writes player data when the world saves or the player logs out.</p></div>`;
  const inv = d.inventory;
  const body = p.uuid ? `<img src="/api/skins/${p.uuid.replace(/-/g, "")}/body.png?size=160" alt="" data-fail="remove">` : "";
  const armor = [["head", "helmet"], ["chest", "chestplate"], ["legs", "leggings"], ["feet", "boots"]]
    .map(([k, g]) => slotHtml(inv.armor[k], { ghost: g })).join("");
  const hotbar = inv.hotbar.map((it, i) => slotHtml(it, { selected: i === d.selected_slot })).join("");
  const asOf = p.source === "live" ? "Live" : `Saved ${fmtAgo(p.as_of)}`;
  return `<div class="inv-layout">
    <div>
      <div class="mc-panel">
        <h3>Inventory <span style="float:right;font-size:.85rem;color:#666">${esc(asOf)}</span></h3>
        <div class="inv-top"><div class="armor-col">${armor}</div>
          <div class="inv-stage"><div class="mini-body">${body}</div>${slotHtml(inv.offhand, { ghost: "shield" })}</div></div>
        <div class="mc-grid">${inv.main.map((it) => slotHtml(it)).join("")}</div>
        <div class="hotbar-gap"></div>
        <div class="mc-grid">${hotbar}</div>
      </div>
    </div>
    <div>
      <div class="mc-panel"><h3>Ender Chest</h3><div class="mc-grid">${gridHtml(d.ender_chest, 27)}</div></div>
      ${(d.mod_items || []).map((g) => `<div class="mc-panel mod-slots"><h3>${esc(g.label.split(" › ").map(humanize).join(" › "))}</h3>
        <div class="mc-grid">${gridHtml(g.items, Math.max(9, Math.ceil(g.items.length / 9) * 9), false)}</div></div>`).join("")}
      <p class="muted" style="margin-top:12px;font-size:.9rem;max-width:480px">Hover an item for details. Shulker boxes and bundles with a gold corner can be opened.</p>
    </div>
  </div>`;
}

// ---------------------------------------------------------------- statistics
const TIME_STATS = /play_time|play_one_minute|time_since|sneak_time|total_world_time/;
function fmtCustom(key, v) {
  if (TIME_STATS.test(key)) return fmtDuration(v);
  if (key.endsWith("_one_cm")) return fmtDistance(v);
  if (key.includes("damage")) return `${fmtNum(v / 20)} ♥`;
  return fmtNum(v);
}
const ITEM_COLS = [["mined", "Mined"], ["crafted", "Crafted"], ["used", "Used"], ["broken", "Broken"], ["picked_up", "Picked up"], ["dropped", "Dropped"]];
function renderStats(el, p) {
  const st = p.stats || {};
  const ui = { mode: "general", q: "", sort: "total", dir: -1 };
  const draw = () => {
    const q = ui.q.toLowerCase();
    let body = "";
    if (ui.mode === "general") {
      const custom = Object.entries(st["minecraft:custom"] || {})
        .map(([k, v]) => [statName(k), fmtCustom(k, v)])
        .filter(([n]) => n.toLowerCase().includes(q)).sort((a, b) => a[0].localeCompare(b[0]));
      body = custom.length ? `<div class="general-grid">${custom.map(([n, v]) => `<div class="row"><span>${esc(n)}</span><span>${esc(v)}</span></div>`).join("")}</div>` : emptyStats();
    } else if (ui.mode === "items") {
      const rows = new Map();
      for (const [cat] of ITEM_COLS) for (const [id, v] of Object.entries(st[`minecraft:${cat}`] || {})) {
        if (!rows.has(id)) rows.set(id, { id, total: 0 });
        rows.get(id)[cat] = v; rows.get(id).total += v;
      }
      let list = [...rows.values()].map((r) => ({ ...r, name: itemName(r.id) })).filter((r) => r.name.toLowerCase().includes(q));
      list.sort((a, b) => ui.sort === "name" ? a.name.localeCompare(b.name) * -ui.dir : ((a[ui.sort] || 0) - (b[ui.sort] || 0)) * ui.dir);
      const th = (k, l) => `<th data-sort="${k}" ${ui.sort === k ? `aria-sort="${ui.dir < 0 ? "descending" : "ascending"}"` : ""}>${l}${ui.sort === k ? (ui.dir < 0 ? " ▾" : " ▴") : ""}</th>`;
      body = list.length ? `<div class="table-wrap"><table class="data"><thead><tr>${th("name", "Item")}${ITEM_COLS.map(([k, l]) => th(k, l)).join("")}</tr></thead><tbody>
        ${list.slice(0, 400).map((r) => `<tr><td><div class="namecell">${itemIcon(r)}${esc(r.name)}</div></td>${ITEM_COLS.map(([k]) => `<td class="${r[k] ? "" : "zero"}">${r[k] ? fmtNum(r[k]) : "–"}</td>`).join("")}</tr>`).join("")}
        </tbody></table></div>` : emptyStats();
    } else {
      const ids = new Set([...Object.keys(st["minecraft:killed"] || {}), ...Object.keys(st["minecraft:killed_by"] || {})]);
      let list = [...ids].map((id) => ({ id, name: entityName(id), killed: st["minecraft:killed"]?.[id] || 0, killed_by: st["minecraft:killed_by"]?.[id] || 0 }))
        .filter((r) => r.name.toLowerCase().includes(q));
      const key = ["killed", "killed_by", "name"].includes(ui.sort) ? ui.sort : "killed";
      list.sort((a, b) => key === "name" ? a.name.localeCompare(b.name) * -ui.dir : (a[key] - b[key]) * ui.dir);
      const th = (k, l) => `<th data-sort="${k}" ${key === k ? `aria-sort="${ui.dir < 0 ? "descending" : "ascending"}"` : ""}>${l}${key === k ? (ui.dir < 0 ? " ▾" : " ▴") : ""}</th>`;
      body = list.length ? `<div class="table-wrap"><table class="data"><thead><tr>${th("name", "Mob")}${th("killed", "Defeated")}${th("killed_by", "Defeated by")}</tr></thead><tbody>
        ${list.map((r) => `<tr><td>${esc(r.name)}</td><td class="${r.killed ? "" : "zero"}">${r.killed ? fmtNum(r.killed) : "–"}</td><td class="${r.killed_by ? "" : "zero"}">${r.killed_by ? fmtNum(r.killed_by) : "–"}</td></tr>`).join("")}
        </tbody></table></div>` : emptyStats();
    }
    $("#stats-body", el).innerHTML = body;
    $$("th[data-sort]", el).forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.sort; if (ui.sort === k) ui.dir *= -1; else { ui.sort = k; ui.dir = k === "name" ? 1 : -1; } draw();
    }));
  };
  el.innerHTML = `<div class="toolbar">
      <div class="seg" role="group" aria-label="Statistic type">${[["general", "General"], ["items", "Items"], ["mobs", "Mobs"]].map(([k, l]) => `<button data-mode="${k}" aria-pressed="${k === ui.mode}">${l}</button>`).join("")}</div>
      <input class="input" type="search" placeholder="Filter statistics" aria-label="Filter statistics" style="flex:1;max-width:320px">
    </div><div id="stats-body"></div>`;
  $$(".seg button", el).forEach((b) => b.addEventListener("click", () => {
    ui.mode = b.dataset.mode; ui.sort = ui.mode === "mobs" ? "killed" : "total"; ui.dir = -1;
    $$(".seg button", el).forEach((x) => x.setAttribute("aria-pressed", x === b)); draw();
  }));
  $("input", el).addEventListener("input", (e) => { ui.q = e.target.value; draw(); });
  draw();
}
const emptyStats = () => `<div class="empty"><h3>Nothing here yet</h3><p>Statistics fill in as this player explores, mines and fights.</p></div>`;

// ---------------------------------------------------------------- advancements
const ADV_ORDER = ["story", "nether", "end", "adventure", "husbandry"];
const ADV_TITLES = { story: "Minecraft", nether: "Nether", end: "The End", adventure: "Adventure", husbandry: "Husbandry" };
function compText(c) {
  if (!c) return "";
  if (typeof c === "string") return c;
  if (c.translate) return tr(c.translate, c.fallback || humanize(c.translate.replace(/\.(title|description)$/, "")));
  return c.text || "";
}
function advancementsHtml(p) {
  const defs = state.advDefs[curSid] || [];
  const mine = p.advancements || {};
  if (!defs.length) {
    const done = Object.entries(mine).filter(([k, v]) => v.done && !k.includes("recipes/"));
    if (!done.length) return `<div class="empty"><h3>No advancements yet</h3><p>Completed advancements show up here.</p></div>`;
    return `<div class="adv-grid">${done.map(([k, v]) => `<div class="adv done"><div class="frame"></div><div><div class="t">${esc(humanize(k))}</div><div class="when">${esc(v.completed_at || "")}</div></div></div>`).join("")}</div>`;
  }
  const byCat = {};
  for (const d of defs) (byCat[d.category] ||= []).push(d);
  const cats = Object.keys(byCat).sort((a, b) => ((ADV_ORDER.indexOf(a) + 1 || 99) - (ADV_ORDER.indexOf(b) + 1 || 99)) || a.localeCompare(b));
  const catTitle = (cat) => ADV_TITLES[cat] || (byCat[cat][0].category_title ? compText(byCat[cat][0].category_title) : humanize(cat.split(":")[0]));
  return `<div class="adv-cats">${cats.map((cat) => {
    const list = treeOrder(byCat[cat]);
    const done = list.filter((d) => mine[d.id]?.done).length;
    return `<section><div class="adv-cat-head"><h2>${esc(catTitle(cat))}</h2><span class="num muted">${done} / ${list.length}</span>
      <div class="adv-progress"><span style="width:${(done / list.length) * 100}%"></span></div></div>
      <div class="adv-grid">${list.map((d) => {
        const m = mine[d.id], isDone = !!m?.done, secret = d.hidden && !isDone;
        return `<div class="adv ${isDone ? "done" : "locked"}">
          <div class="frame ${esc(d.frame)}">${d.icon && !secret ? itemIcon({ id: d.icon }) : ""}</div>
          <div><div class="t">${secret ? "Hidden advancement" : esc(compText(d.title))}</div>
            <div class="d">${secret ? "Keep playing to discover this one." : esc(compText(d.description))}</div>
            ${isDone && m.completed_at ? `<div class="when">${esc(new Date(m.completed_at.replace(" ", "T").replace(/ ([+-]\d\d)(\d\d)$/, "$1:$2")).toLocaleDateString() || m.completed_at)}${m.by && p.together ? ` · ${esc(m.by)}` : ""}</div>` : ""}
          </div></div>`;
      }).join("")}</div></section>`;
  }).join("")}</div>`;
}
function treeOrder(list) {
  const ids = new Set(list.map((d) => d.id));
  const kids = {};
  const roots = [];
  for (const d of list) { if (d.parent && ids.has(d.parent)) (kids[d.parent] ||= []).push(d); else roots.push(d); }
  const out = [];
  const walk = (d) => { out.push(d); (kids[d.id] || []).sort((a, b) => a.id.localeCompare(b.id)).forEach(walk); };
  roots.sort((a, b) => a.id.localeCompare(b.id)).forEach(walk);
  return out;
}

// ---------------------------------------------------------------- favourites (a player's page)
// The top one in each kind, read from the game's own statistics: how much of that kind it is, and what comes next.
const FAV_FOODS = new Set(["apple", "bread", "cooked_beef", "cooked_porkchop", "cooked_chicken", "cooked_mutton", "cooked_rabbit", "cooked_cod",
  "cooked_salmon", "baked_potato", "carrot", "golden_carrot", "golden_apple", "enchanted_golden_apple", "melon_slice", "sweet_berries",
  "glow_berries", "cookie", "pumpkin_pie", "mushroom_stew", "rabbit_stew", "beetroot_soup", "suspicious_stew", "beef", "porkchop", "chicken",
  "mutton", "rabbit", "cod", "salmon", "tropical_fish", "potato", "beetroot", "dried_kelp", "honey_bottle", "chorus_fruit", "rotten_flesh",
  "spider_eye", "poisonous_potato", "pufferfish"].map((x) => `minecraft:${x}`));
const FAV_TOOL = /_(pickaxe|axe|shovel|hoe)$|^minecraft:(shears|flint_and_steel|brush|fishing_rod)$/;
const FAV_WEAPON = /_sword$|^minecraft:(bow|crossbow|trident|mace)$/;
const FAV_MOVES = [["walk_one_cm", "Walking", "🚶"], ["sprint_one_cm", "Sprinting", "🏃"], ["crouch_one_cm", "Sneaking", "🐾"],
  ["swim_one_cm", "Swimming", "🏊"], ["walk_under_water_one_cm", "Walking under water", "🫧"], ["walk_on_water_one_cm", "Walking on water", "💧"],
  ["aviate_one_cm", "Elytra", "🪽"], ["fly_one_cm", "Flying", "🕊"], ["boat_one_cm", "Boat", "🛶"], ["horse_one_cm", "Horse", "🐎"],
  ["minecart_one_cm", "Minecart", "🛤"], ["pig_one_cm", "Pig", "🐖"], ["strider_one_cm", "Strider", "🔥"], ["climb_one_cm", "Climbing", "🧗"],
  ["happy_ghast_one_cm", "Happy ghast", "👻"], ["nautilus_one_cm", "Nautilus", "🐚"]];
function favourites(st) {
  const top = (obj, keep = () => true) => {
    const rows = Object.entries(obj || {}).filter(([k, v]) => v > 0 && keep(k)).sort((a, b) => b[1] - a[1]);
    const total = rows.reduce((n, [, v]) => n + v, 0);
    return rows.length ? { id: rows[0][0], n: rows[0][1], total, rows: rows.slice(0, 5), all: rows, kinds: rows.length } : null;
  };
  const mobIcon = (id) => itemIcon({ id: `${id}_spawn_egg` });
  const itemIco = (id) => itemIcon({ id });
  const out = [];
  const add = (title, t, icon, name, unit, fmt = fmtNum) => t && out.push({ title, t, icon, name, unit, fmt });
  const used = st["minecraft:used"] || {};
  add("⛏ Favourite tool", top(used, (k) => FAV_TOOL.test(k)), itemIco, itemName, "uses");
  add("⚔ Favourite weapon", top(used, (k) => FAV_WEAPON.test(k)), itemIco, itemName, "uses");
  add("🍖 Favourite food", top(used, (k) => FAV_FOODS.has(k)), itemIco, itemName, "eaten");
  add("🧟 Most defeated", top(st["minecraft:killed"]), mobIcon, entityName, "defeated");
  add("🧱 Most mined", top(st["minecraft:mined"]), itemIco, itemName, "mined");
  add("🔨 Most crafted", top(st["minecraft:crafted"]), itemIco, itemName, "crafted");
  const custom = st["minecraft:custom"] || {};
  const move = Object.fromEntries(FAV_MOVES.map(([k, l, e]) => [k, { l, e }]));
  add("🧭 Getting around", top(Object.fromEntries(FAV_MOVES.map(([k]) => [k, custom[`minecraft:${k}`] || 0]))),
    (id) => `<span class="fav-emo">${move[id].e}</span>`, (id) => move[id].l, "", (v) => fmtStat("cm", v));
  add("💀 Defeated most by", top(st["minecraft:killed_by"]), mobIcon, entityName, "times");
  return out;
}
function favouritesHtml(st) {
  const favs = favourites(st || {});
  if (!favs.length) return "";
  return `<section class="favs"><div class="trophies-head"><h2>⭐ Favourites</h2><span class="muted small">from the game's own statistics · tap one for the top five of each</span></div>
    <div class="fav-shelf">${favs.map((f, i) => `<button type="button" class="fav" data-fav="${i}">
      <span class="fav-title">${f.title}</span>
      <span class="fav-main">${f.icon(f.t.id)}<span><b>${esc(f.name(f.t.id))}</b><span class="muted small">${esc(f.fmt(f.t.n))}${f.unit ? ` ${esc(f.unit)}` : ""}</span></span></span>
    </button>`).join("")}</div></section>`;
}
function favRow(f, [id, n], j, numbered = false) {
  return `<li class="${j ? "" : "top"}">${f.icon(id)}<span class="fav-n">${numbered ? `<small class="muted">${j + 1}.</small> ` : ""}${esc(f.name(id))}</span><span class="fav-v">${esc(f.fmt(n))}</span>
    <span class="fav-pct">${n / f.t.total < 0.005 ? "<1" : Math.round((n / f.t.total) * 100)}%</span><span class="fav-bar"><span style="width:${Math.max(2, (n / f.t.total) * 100)}%"></span></span></li>`;
}
function openFavourites(name, st, first = 0) {
  const favs = favourites(st || {});
  openModal(`<h2>⭐ ${esc(name)}'s favourites</h2>
    <p class="muted small">The top five of each kind, from the game's own statistics. The bar is each one's share of everything of that kind. <b>Show all</b> lists every one.</p>
    <div class="fav-all">${favs.map((f, i) => `<section class="fav-cat" data-cat="${i}"><h3>${f.title} <small class="muted">${f.t.kinds} kind${f.t.kinds === 1 ? "" : "s"} · ${esc(f.fmt(f.t.total))}${f.unit ? ` ${esc(f.unit)}` : ""} in all</small></h3>
      <ol>${f.t.rows.map((r, j) => favRow(f, r, j)).join("")}</ol>
      ${f.t.kinds > 5 ? `<button type="button" class="link-btn" data-all="${i}">Show all ${f.t.kinds} →</button>` : ""}</section>`).join("")}</div>
    <div class="actions"><button type="button" class="btn" data-close-modal>Close</button></div>`, (m) => {
    m.classList.add("fav-modal");
    m.querySelector(`[data-cat="${first}"]`)?.scrollIntoView({ block: "nearest" });
    m.addEventListener("click", (e) => { const b = e.target.closest("[data-all]"); if (b) openFavouriteKind(name, st, +b.dataset.all); });
  });
}
// Every one of a kind (every block mined, every mob…), biggest first, with a box to find one and a way back
function openFavouriteKind(name, st, i) {
  const f = favourites(st || {})[i];
  if (!f) return;
  const list = f.t.all.map((r, j) => ({ r, j, name: f.name(r[0]).toLowerCase() }));
  openModal(`<h2>${f.title}</h2>
    <p class="muted small">Every one of ${esc(name)}'s, biggest first: ${f.t.kinds} kind${f.t.kinds === 1 ? "" : "s"}, ${esc(f.fmt(f.t.total))}${f.unit ? ` ${esc(f.unit)}` : ""} in all.</p>
    ${list.length > 12 ? `<input class="input fav-find" type="search" placeholder="Find one…" aria-label="Find one">` : ""}
    <div class="fav-cat fav-every"><ol></ol></div>
    <div class="actions"><button type="button" class="btn" data-back>← All favourites</button><span style="flex:1"></span><button type="button" class="btn" data-close-modal>Close</button></div>`, (m) => {
    m.classList.add("fav-modal");
    const ol = m.querySelector("ol");
    const paint = (q = "") => { ol.innerHTML = list.filter((x) => !q || x.name.includes(q)).map((x) => favRow(f, x.r, x.j, true)).join("") || `<li class="muted small">None called that</li>`; };
    paint();
    m.querySelector(".fav-find")?.addEventListener("input", (e) => paint(e.target.value.trim().toLowerCase()));
    m.querySelector("[data-back]").addEventListener("click", () => openFavourites(name, st, i));
  });
}

// ---------------------------------------------------------------- travels (a player's page → Travels)
// Where they've been: every chunk they were seen in (warmer = more often), with their bed, last death, where they are or
// left off, and their records (deepest, highest, farthest). From the positions Solstone keeps.
async function renderPlayerTravels(el, sid, p, span = "all") {
  el.innerHTML = `<p class="muted">Loading…</p>`;
  let t;
  try { t = await api(`/api/servers/${encodeURIComponent(sid)}/players/${p.uuid}/travels?span=${span}`); }
  catch (err) { el.innerHTML = `<p class="muted">Couldn't load their travels: ${esc(err.message)}</p>`; return; }
  const DIM_ORDER = ["minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"];
  const dims = Object.keys(t.dims).sort((a, b) => ((DIM_ORDER.indexOf(a) + 1 || 9) - (DIM_ORDER.indexOf(b) + 1 || 9)));
  const spanSeg = `<div class="seg" role="group" aria-label="How far back">${[["all", "All time"], ["recent", `Last ${t.keep_days} days`]].map(([k, l]) => `<button type="button" data-span="${k}" aria-pressed="${k === span}">${l}</button>`).join("")}</div>`;
  el.onclick = (e) => { const b = e.target.closest("[data-span]"); if (b && b.dataset.span !== span) renderPlayerTravels(el, sid, p, b.dataset.span); };
  if (!dims.length) { el.innerHTML = `<div class="tv-head">${spanSeg}</div><div class="empty"><h3>No travels yet</h3><p>Where ${esc(p.name)} goes shows here once they've played a while.</p></div>`; return; }
  const d0 = p.data || {};
  const here = d0.position ? { dim: d0.position.dimension || "minecraft:overworld", x: d0.position.x, z: d0.position.z } : null;
  const pins = (dim) => [
    d0.respawn && (d0.respawn.dimension || "minecraft:overworld") === dim && { ...d0.respawn, label: "Bed", emo: "🛏" },
    d0.last_death && d0.last_death.dimension === dim && { ...d0.last_death, label: "Last death", emo: "💀" },
    here && here.dim === dim && here.x != null && { ...here, label: p.online ? "Here now" : "Left off here", emo: "📍" },
  ].filter(Boolean);
  let dim = dims.includes(here?.dim) ? here.dim : dims[0];
  const coords = (r) => `${fmtNum(r.x)}, ${fmtNum(r.y)}, ${fmtNum(r.z)}`;
  const recordsHtml = () => {
    const d = t.dims[dim];
    const rec = (emo, label, r, extra = "") => r ? `<button type="button" class="tv-rec" data-go="${r.x},${r.z}"><span>${emo}</span><b>${label}</b><span>${extra}</span><small class="muted">${coords(r)} · ${esc(fmtAgo(r.ts))}</small></button>` : "";
    return `${rec("⬇", "Deepest", d.deepest, `Y ${d.deepest?.y}`)}${d.highest?.y !== d.deepest?.y ? rec("⬆", "Highest", d.highest, `Y ${d.highest?.y}`) : ""}
      ${d.farthest ? `<button type="button" class="tv-rec" data-go="${d.farthest.x},${d.farthest.z}"><span>🧭</span><b>Farthest out</b><span>${esc(fmtStat("cm", d.farthest.dist * 100))}</span><small class="muted">from ${d.farthest.from === "spawn" ? "the world spawn" : "0, 0"} · around ${fmtNum(d.farthest.x)}, ${fmtNum(d.farthest.z)}</small></button>` : ""}
      ${pins(dim).map((x) => `<button type="button" class="tv-rec" data-go="${x.x},${x.z}"><span>${x.emo}</span><b>${esc(x.label)}</b><span></span><small class="muted">${fmtNum(x.x)}, ${fmtNum(x.z)}</small></button>`).join("")}`;
  };
  el.innerHTML = `<div class="tv-head">${spanSeg}
      ${dims.length > 1 ? `<div class="seg" role="group" aria-label="Dimension">${dims.map((x) => `<button type="button" data-dim="${esc(x)}" aria-pressed="${x === dim}">${esc(dimName(x))}</button>`).join("")}</div>` : ""}
      <span class="muted small" id="tv-sum"></span></div>
    <div class="tv-wrap"><div id="tv-map" class="world-own-map"></div><div class="tv-recs" id="tv-recs"></div></div>
    <p class="muted small">Each square is a chunk (16 × 16 blocks) they've been in, warmer the more time they spent there: ${span === "all" ? "all the time Solstone has kept count" : `the last ${t.keep_days} days, and saved adventures`}${t.since ? ` (since ${esc(new Date(t.since * 1000).toLocaleDateString())})` : ""}.${t.names.length > 1 ? ` All of ${esc(t.names.join(" + "))}.` : ""}</p>`;
  let cells = [], max = 1;
  const pick = () => {
    const d = t.dims[dim];
    cells = d.cells; max = Math.max(1, ...cells.slice(0, 50).map((c) => c[2]));
    $("#tv-sum", el).textContent = `${fmtNum(d.chunks)} chunks explored in ${dimName(dim)}`;
    $("#tv-recs", el).innerHTML = recordsHtml();
  };
  pick();
  const heat = (n) => { const f = Math.log1p(n) / Math.log1p(max); return `hsla(${Math.round(200 - 170 * f)}, 90%, ${55 + f * 5}%, ${0.35 + 0.45 * f})`; };
  const map = worldMapCanvas($("#tv-map", el), sid, { dim, center: { x: cells[0][0] * t.cell, z: cells[0][1] * t.cell }, scale: 0.5,
    overlay: (ctx, toScreen, view) => {
      const sz = Math.max(1.5, t.cell * view.scale);
      for (const [cx, cz, n] of cells) {
        const [x, y] = toScreen(cx * t.cell, cz * t.cell);
        if (x < -sz || y < -sz || x > ctx.canvas.width || y > ctx.canvas.height) continue;
        ctx.fillStyle = heat(n); ctx.fillRect(x, y, sz, sz);
      }
      ctx.font = "16px system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      for (const pin of pins(dim)) {
        const [x, y] = toScreen(pin.x, pin.z);
        ctx.fillStyle = "rgba(0,0,0,.55)"; ctx.beginPath(); ctx.arc(x, y, 13, 0, Math.PI * 2); ctx.fill();
        ctx.fillText(pin.emo, x, y + 1);
      }
      ctx.textAlign = "start"; ctx.textBaseline = "alphabetic";
    } });
  el.querySelector("canvas")?.setAttribute("aria-label", `Map of where ${p.name} has been`);
  const fit = () => map.fit(cells.slice(0, 400).map(([cx, cz]) => ({ x: cx * t.cell, z: cz * t.cell })));
  fit();
  el.onclick = (e) => {
    const s0 = e.target.closest("[data-span]");
    if (s0) { if (s0.dataset.span !== span) renderPlayerTravels(el, sid, p, s0.dataset.span); return; }
    const b = e.target.closest("[data-dim]");
    if (b) { dim = b.dataset.dim; $$("[data-dim]", el).forEach((x) => x.setAttribute("aria-pressed", String(x === b))); pick(); map.setDim(dim); fit(); return; }
    const g = e.target.closest("[data-go]");
    if (g) { const [x, z] = g.dataset.go.split(",").map(Number); map.view.cx = x; map.view.cz = z; map.view.scale = Math.max(map.view.scale, 2); map.draw(); }
  };
}

// ---------------------------------------------------------------- a Bedrock account linked to a Java one (Floodgate)
async function loadBedrockLink(sid, p) {
  const box = $("#plink");
  const l = await api(`/api/servers/${encodeURIComponent(sid)}/players/${p.uuid}/link`).catch(() => null);
  if (!box || !l || l.error) return;
  const who = (x) => x.here ? `<a href="#/s/${encodeURIComponent(sid)}/p/${x.uuid}">${esc(x.name)}</a>` : `<b>${esc(x.name || "a Java player")}</b>`;
  if (l.bedrock && l.plays_as) {
    box.innerHTML = `<p class="plink on">🔗 <span>Linked: from Bedrock, ${esc(p.name)} joins as ${who(l.plays_as)} (Java), with that player's name, items and progress. What's shown here is the Bedrock player from before the link.</span></p>`;
  } else if (l.bedrock) {
    box.innerHTML = `<p class="plink">🔗 <span>Not linked to a Java account. Someone who plays both can link them once, then join from Bedrock as their Java player. <a href="https://geysermc.org/wiki/floodgate/linking/" target="_blank" rel="noopener">How</a></span></p>`;
  } else if (l.linked_bedrock?.length) {
    box.innerHTML = `<p class="plink on">🔗 <span>Also plays from Bedrock: ${l.linked_bedrock.map(who).join(", ")} ${l.linked_bedrock.length === 1 ? "is" : "are"} linked to ${esc(p.name)}, and join${l.linked_bedrock.length === 1 ? "s" : ""} as this player.</span></p>`;
  }
}

// ---------------------------------------------------------------- trophies (a player's page)
// The places a player holds on this server's leaderboards right now: 🥇🥈🥉 on each board (equal scores share a
// place, as on the Leaderboards page), and the boards where they're just off the podium. Linked accounts count as one.
function boardPlaces(data, match) {
  const won = [], close = [];
  for (const b of data.boards || []) {
    if (b.medals === false) continue;
    const rows = data.players.filter((r) => r[b.key] > 0);
    const me = rows.find(match);
    if (!me) continue;
    const values = [...new Set(rows.map((r) => r[b.key]))].sort((x, y) => y - x);
    const place = values.indexOf(me[b.key]);
    const shared = rows.filter((r) => r[b.key] === me[b.key]).length > 1;
    const item = { board: b, value: me[b.key], place, shared, of: rows.length, gap: place > 0 ? values[place - 1] - me[b.key] : 0 };
    if (place < 3) won.push(item); else if (place < 5) close.push(item);
  }
  won.sort((x, y) => x.place - y.place || x.board.title.localeCompare(y.board.title));
  close.sort((x, y) => x.place - y.place);
  return { won, close };
}
async function loadTrophies(sid, p) {
  const box = $("#trophies");
  const data = await api(`/api/servers/${encodeURIComponent(sid)}/leaderboard`).catch(() => null);
  if (!box || !data?.players?.length) return;
  const names = new Set([p.name, ...(p.together?.accounts || []).map((a) => a.name)].map((n) => n.toLowerCase()));
  const match = (r) => r.uuid === p.uuid || names.has(r.name.toLowerCase()) || (r.also || []).some((n) => names.has(n.toLowerCase()));
  const { won, close } = boardPlaces(data, match);
  if (!won.length && !close.length) return;
  const MEDAL = ["🥇", "🥈", "🥉"], CLS = ["gold", "silver", "bronze"], PLACE = ["1st", "2nd", "3rd", "4th", "5th"];
  const count = [0, 1, 2].map((i) => won.filter((w) => w.place === i).length);
  const lb = `#/s/${encodeURIComponent(sid)}/leaderboards`;
  const card = (w) => `<a class="trophy ${CLS[w.place]}" href="${lb}" title="${w.shared ? "Tied " : ""}${PLACE[w.place]} of ${w.of}">
      <span class="trophy-medal">${MEDAL[w.place]}</span><span class="trophy-title">${esc(w.board.title)}</span>
      <span class="trophy-val">${esc(fmtStat(w.board.kind, w.value))}</span><span class="trophy-place">${w.shared ? "tied " : ""}${PLACE[w.place]} of ${w.of}</span></a>`;
  box.innerHTML = `<section class="trophies">
    <div class="trophies-head"><h2>🏆 Trophies</h2><span class="muted small">${won.length ? count.map((n, i) => n ? `${MEDAL[i]} ${n}` : "").filter(Boolean).join(" · ") + " · held right now on" : "On"} <a href="${lb}">the leaderboards</a></span></div>
    ${won.length ? `<div class="trophy-shelf">${won.slice(0, 6).map(card).join("")}</div>
      ${won.length > 6 ? `<details class="trophy-more"><summary>All ${won.length} trophies</summary><div class="trophy-shelf">${won.slice(6).map(card).join("")}</div></details>` : ""}` : ""}
    ${close.length ? `<p class="trophy-close muted small"><b>Nearly there:</b> ${close.slice(0, 4).map((c) => `${PLACE[c.place]} in ${esc(c.board.title)} (${esc(fmtStat(c.board.kind, c.gap))} off ${PLACE[c.place - 1]})`).join(" · ")}</p>` : ""}
  </section>`;
}
