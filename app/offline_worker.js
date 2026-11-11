// Solstone's "website is down" page: a Cloudflare Worker that stands in front of the website.
//
// Every visit goes to the website as usual. Only when it can't be reached (the computer's off, the tunnel's down,
// Solstone isn't running) does this answer instead: a page with the site's name, how to contact the admins, and
// how to get on each Minecraft server (Java: its address; Bedrock: the Xbox friend first, the address and port as the
// other way), and whether each is still up. That's asked of mcsrvstat.us, a free public status checker, so it works
// even with Solstone off. Only "online", how many are playing, the version and its message are shown, never who.
//
// Planned maintenance: Solstone hands its details to this Worker ahead of time (POST /__solstone/maintenance, with the
// key below), and it keeps them in Cloudflare's storage (a KV namespace bound as SOLSTONE). While the website is off
// during it, the page says "Down for maintenance until …" instead.
//
// Made by Solstone (Website → Site details → If this website goes down). Download it again after changing the
// site's name, contact or servers. Settings below.
const SITE = __SITE__;

const DOWN = new Set([502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530]);   // Cloudflare's "can't reach it"

export default {
  async fetch(request, env) {
    if (new URL(request.url).pathname === "/__solstone/maintenance") return setMaintenance(request, env);
    try {
      const res = await fetch(request, { signal: AbortSignal.timeout(20000) });
      if (!DOWN.has(res.status)) return res;
    } catch {
      // unreachable or too slow: the page below
    }
    const url = new URL(request.url);
    if (request.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname.startsWith("/static/")) {
      return new Response(JSON.stringify({ detail: "The website is down right now." }),
        { status: 503, headers: { "content-type": "application/json", "retry-after": "60" } });
    }
    const [checks, planned] = await Promise.all([Promise.all(SITE.servers.map(status)), maintenance(env)]);
    return new Response(page(checks, planned), { status: 503, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "retry-after": "60" } });
  },
};

async function setMaintenance(request, env) {
  if (request.method !== "POST" || !SITE.key || request.headers.get("x-solstone-key") !== SITE.key) return new Response("Not found", { status: 404 });
  if (!env || !env.SOLSTONE) return Response.json({ ok: false, detail: "No KV namespace bound as SOLSTONE" }, { status: 501 });
  const m = await request.json().catch(() => null);
  if (m && m.end) await env.SOLSTONE.put("maintenance", JSON.stringify(m));
  else await env.SOLSTONE.delete("maintenance");
  return Response.json({ ok: true });
}

// The planned maintenance, from an hour before it starts until a few hours after it was meant to end.
async function maintenance(env) {
  try {
    const m = env && env.SOLSTONE ? JSON.parse((await env.SOLSTONE.get("maintenance")) || "null") : null;
    const now = Date.now() / 1000;
    return m && now >= m.start - 3600 && now <= m.end + 3 * 3600 ? m : null;
  } catch {
    return null;
  }
}

async function ask(path) {
  try {
    const r = await fetch(`https://api.mcsrvstat.us/${path}`, { headers: { "user-agent": "Solstone offline page" }, signal: AbortSignal.timeout(6000) });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

const host = (a) => String(a).replace(/[^\w.:-]/g, "");      // play.example.net or play.example.net:25566

// One check per server, of its Java side (its own check address, else its Java address): Java and Bedrock players
// play on the same server, and Bedrock is harder to ask reliably. A Bedrock-only server is asked over Bedrock.
async function status(s) {
  const r = s.check ? await ask(`3/${host(s.check)}`)
    : s.bedrock ? await ask(`bedrock/3/${host(s.bedrock)}:${Number(s.bedrock_port) || 19132}`) : null;
  const on = !!(r && r.online);
  // how many are playing (never who), its version, and its message of the day: what anyone's server list shows anyway
  return { ...s, online: on, known: !!r, playing: on ? r.players?.online || 0 : 0, max: on ? r.players?.max || 0 : 0,
           version: s.version || (on ? r.version || "" : ""), motd: on ? (r.motd?.clean || []).join(" ").trim() : "" };
}

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const ICON = {
  java: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="#e8a33d" d="M4 9h12v6a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zm12 1h1.5a2.5 2.5 0 0 1 0 5H16v-1.5h1.5a1 1 0 0 0 0-2H16zM7 3c1 1.2-.6 2 .4 3.4M10.5 2.5c1 1.4-.6 2.3.4 3.8"/></svg>`,
  bedrock: `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="#5fb85a" d="M12 2 21 7v10l-9 5-9-5V7z"/><path fill="#3f8f3c" d="m12 12 9-5v10l-9 5z"/><path fill="#7fd47a" d="m3 7 9-5 9 5-9 5z"/></svg>`,
};

function page(checks, planned) {
  const copy = (v, what) => `<button class="copy" type="button" data-copy="${esc(v)}" aria-label="Copy the ${what}">Copy</button>`;
  const card = (s) => {
    const pill = s.online ? `<span class="pill on">● Online · ${s.playing}${s.max ? ` of ${s.max}` : ""} playing</span>`
      : s.known ? `<span class="pill off">● Offline</span>` : `<span class="pill">Couldn't check</span>`;
    const java = s.java ? `<div class="ed"><div class="ed-head">${ICON.java}<b>Java Edition</b><span class="muted">PC or Mac</span>${s.version ? `<span class="ver" title="Launch this version">${esc(s.version)}</span>` : ""}</div>
        <div class="row"><code class="big">${esc(s.java)}</code>${copy(s.java, "address")}</div>
        <p class="how">Multiplayer → Add Server → paste the address.</p></div>` : "";
    const server = s.bedrock ? `<div class="row"><code>${esc(s.bedrock)}</code><span class="port">Port <b>${esc(s.bedrock_port || 19132)}</b></span>${copy(s.bedrock, "address")}</div>` : "";
    const bedrock = s.xbox || s.bedrock ? `<div class="ed"><div class="ed-head">${ICON.bedrock}<b>Bedrock Edition</b><span class="muted">phones, tablets, consoles, Windows</span></div>
        ${s.xbox ? `<div class="row"><span class="lbl">Add as a friend</span><code class="big">${esc(s.xbox)}</code>${copy(s.xbox, "gamertag")}</div>
          <p class="how">Add <b>${esc(s.xbox)}</b> as a friend on Xbox (<a href="https://account.xbox.com/en-us/profile?gamertag=${encodeURIComponent(s.xbox)}" rel="noopener">open its Xbox profile</a>), then in Minecraft: Play → Friends, and join from there. Works on every device, consoles too.</p>
          ${server ? `<details><summary>Or add it as a server <span class="muted">(phones, tablets and Windows)</span></summary>${server}<p class="how">Play → Servers → Add Server. Consoles can't add servers: join through the friend above.</p></details>` : ""}`
        : `${server}<p class="how">Play → Servers → Add Server, with the address and port. Consoles can't add servers.</p>`}</div>` : "";
    return `<section class="srv${s.online ? "" : " is-off"}"${s.color ? ` style="border-color:${esc(s.color)}"` : ""}>
      <header><h3>${esc(s.name)}</h3>${pill}</header>
      ${s.motd ? `<p class="motd">${esc(s.motd)}</p>` : ""}${s.note ? `<p class="note">${esc(s.note)}</p>` : ""}
      ${java}${bedrock}</section>`;
  };
  const ordered = [...checks].sort((a, b) => (b.main ? 1 : 0) - (a.main ? 1 : 0));
  const anyUp = checks.some((s) => s.online);
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(SITE.name)} · ${planned ? "down for maintenance" : "the website is down"}</title><meta name="robots" content="noindex">
<style>
:root { color-scheme: dark; --bg: #141a2b; --panel: #1f2740; --well: #ffffff0d; --text: #eef1f8; --muted: #a8b0c4; --on: #6fdc7a; --off: #ff8f6b; --gold: #f2c14e; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: linear-gradient(180deg, #0d1222, var(--bg)); color: var(--text); font: 16px/1.5 system-ui, sans-serif; display: grid; place-items: start center; padding: 28px 16px; }
main { width: min(680px, 100%); }
.top { background: var(--panel); border: 1px solid #ffffff1a; border-radius: 14px; padding: 22px 24px; margin-bottom: 16px; }
h1 { margin: 0 0 6px; font-size: 1.7rem; } h3 { margin: 0; font-size: 1.15rem; }
p { margin: 6px 0; } .muted { color: var(--muted); } a { color: var(--gold); }
.lead { font-size: 1.05rem; } .lead b { color: var(--on); }
.srv { background: var(--panel); border: 1px solid #ffffff1a; border-left-width: 4px; border-radius: 14px; padding: 18px 20px; margin-bottom: 14px; }
.srv.is-off { opacity: .8; }
.srv header { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 6px; }
.motd { color: var(--muted); font-style: italic; } .note { background: var(--well); border-radius: 8px; padding: 8px 10px; }
.ed { margin-top: 14px; padding-top: 12px; border-top: 1px solid #ffffff12; }
.ed-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; } .ed-head .muted { font-size: .85rem; }
.ver { font-size: .8rem; background: #ffffff14; border-radius: 99px; padding: 1px 8px; }
.row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; background: var(--well); border-radius: 10px; padding: 8px 10px; margin: 6px 0; }
code { font: 600 1rem ui-monospace, Menlo, Consolas, monospace; word-break: break-all; } code.big { font-size: 1.15rem; color: #fff; }
.lbl { color: var(--muted); font-size: .85rem; } .port { color: var(--muted); font-size: .9rem; } .port b { color: var(--text); }
.copy { margin-left: auto; background: var(--gold); color: #1a1406; border: 0; border-radius: 8px; padding: 6px 14px; font-weight: 700; cursor: pointer; }
.copy.done { background: var(--on); }
.how { color: var(--muted); font-size: .9rem; }
details { margin-top: 8px; } summary { cursor: pointer; color: var(--text); }
.pill { white-space: nowrap; font-size: .85rem; font-weight: 700; padding: 3px 10px; border-radius: 99px; background: #ffffff14; color: var(--muted); }
.pill.on { color: var(--on); background: #6fdc7a22; } .pill.off { color: var(--off); background: #ff8f6b22; }
.maint { background: #f2c14e1a; border: 1px solid #f2c14e55; border-radius: 10px; padding: 12px 14px; margin: 12px 0 0; }
.maint b { color: var(--gold); }
.foot { text-align: center; font-size: .85rem; }
.again { background: none; border: 1px solid #ffffff2a; color: var(--text); border-radius: 8px; padding: 6px 14px; cursor: pointer; }
</style></head><body><main>
<div class="top"><h1>${esc(SITE.name)}</h1>
${planned
    ? `<div class="maint"><p><b>🛠️ Down for maintenance</b></p>${planned.message ? `<p>${esc(planned.message)}</p>` : ""}
       <p>${Date.now() / 1000 > planned.end ? "It's taking a little longer than planned. It'll be back soon." : `Back around <b>${esc(planned.until)}</b>${planned.tz ? ` <span class="muted">(${esc(planned.tz)} time)</span>` : ""}.`}</p></div>`
    : `<p class="lead">The website is down right now${anyUp ? `, but <b>the game is still up: you can play</b>` : ""}.</p>
       <p class="muted">${anyUp ? "Here's how to get on. The rest of the website (stats, the map, your page) will be back soon." : "It'll be back soon, so try again in a little while."}</p>`}
</div>
${ordered.map(card).join("")}
${SITE.contact || SITE.discord ? `<div class="top"><h3>Need help?</h3><p>${SITE.contact ? `Email <a href="mailto:${esc(SITE.contact)}">${esc(SITE.contact)}</a>` : ""}${SITE.contact && SITE.discord ? " or ask on " : SITE.discord ? "Ask on " : ""}${SITE.discord ? `<a href="${esc(SITE.discord)}">Discord</a>` : ""}.</p></div>` : ""}
<p class="foot muted">Checked just now. <button class="again" type="button" onclick="location.reload()">Check again</button></p>
</main>
<script>
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-copy]");
  if (!b) return;
  try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; b.classList.add("done"); setTimeout(() => { b.textContent = "Copy"; b.classList.remove("done"); }, 1800); }
  catch { prompt("Copy this:", b.dataset.copy); }
});
</script>
</body></html>`;
}
