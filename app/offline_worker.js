// Solstone's "website is down" page: a Cloudflare Worker that stands in front of the website.
//
// Every visit goes to the website as usual. Only when it can't be reached (the computer's off, the tunnel's down,
// Solstone isn't running) does this answer instead: a page with the site's name, how to contact the admins, and
// whether each Minecraft server is still up. That's asked of mcsrvstat.us, a free public status checker, so it
// works even with Solstone off. Only "online" and how many are playing are shown, never who.
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

async function status(s) {
  const [java, bedrock] = await Promise.all([
    s.java ? ask(`3/${host(s.java)}`) : null,
    s.bedrock ? ask(`bedrock/3/${host(s.bedrock)}:${Number(s.bedrock_port) || 19132}`) : null,
  ]);
  const up = [java, bedrock].filter((x) => x && x.online);
  const known = [java, bedrock].some((x) => x);
  return { ...s, online: up.length > 0, known, playing: up.length ? Math.max(...up.map((x) => x.players?.online || 0)) : 0 };
}

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function page(checks, planned) {
  const row = (s) => `<li><div><b>${esc(s.name)}</b>
      <span class="addr">${[s.java && `Java: ${esc(s.java)}`, s.bedrock && `Bedrock: ${esc(s.bedrock)} port ${esc(s.bedrock_port || 19132)}`].filter(Boolean).join(" · ")}</span></div>
      <span class="pill ${s.online ? "on" : s.known ? "off" : ""}">${s.online ? `Up · ${s.playing} playing` : s.known ? "Down" : "Couldn't check"}</span></li>`;
  const anyUp = checks.some((s) => s.online);
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(SITE.name)} · ${planned ? "down for maintenance" : "down for now"}</title><meta name="robots" content="noindex">
<style>
:root { color-scheme: dark; --bg: #141a2b; --panel: #1f2740; --text: #eef1f8; --muted: #a8b0c4; --on: #6fdc7a; --off: #ff8f6b; --gold: #f2c14e; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: linear-gradient(180deg, #0d1222, var(--bg)); color: var(--text); font: 16px/1.5 system-ui, sans-serif; display: grid; place-items: center; padding: 24px 16px; }
main { width: min(620px, 100%); background: var(--panel); border: 1px solid #ffffff1a; border-radius: 12px; padding: 24px; }
h1 { margin: 0 0 4px; font-size: 1.6rem; } h2 { font-size: 1.05rem; margin: 22px 0 8px; }
p { margin: 6px 0; } .muted { color: var(--muted); } a { color: var(--gold); }
ul { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
li { display: flex; justify-content: space-between; align-items: center; gap: 12px; background: #ffffff0d; border-radius: 8px; padding: 10px 12px; }
.addr { display: block; color: var(--muted); font-size: .85rem; word-break: break-all; }
.pill { white-space: nowrap; font-size: .85rem; font-weight: 700; padding: 3px 10px; border-radius: 99px; background: #ffffff14; color: var(--muted); }
.pill.on { color: var(--on); background: #6fdc7a22; } .pill.off { color: var(--off); background: #ff8f6b22; }
.maint { background: #f2c14e1a; border: 1px solid #f2c14e55; border-radius: 10px; padding: 12px 14px; margin: 12px 0; }
.maint b { color: var(--gold); }
</style></head><body><main>
<h1>${esc(SITE.name)}</h1>
${planned
    ? `<div class="maint"><p><b>🛠️ Down for maintenance</b></p>${planned.message ? `<p>${esc(planned.message)}</p>` : ""}
       <p>${Date.now() / 1000 > planned.end ? "It's taking a little longer than planned. It'll be back soon." : `Back around <b>${esc(planned.until)}</b>${planned.tz ? ` <span class="muted">(${esc(planned.tz)} time)</span>` : ""}.`}</p></div>`
    : "<p>The website is down right now. It'll be back soon, so try again in a little while.</p>"}
${checks.length ? `<h2>The Minecraft servers</h2><ul>${checks.map(row).join("")}</ul>
<p class="muted">${anyUp ? "You can still play while the website is down." : "Checked just now."}</p>` : ""}
${SITE.contact || SITE.discord ? `<h2>Need help?</h2><p>${SITE.contact ? `Email <a href="mailto:${esc(SITE.contact)}">${esc(SITE.contact)}</a>` : ""}${SITE.contact && SITE.discord ? " or ask on " : SITE.discord ? "Ask on " : ""}${SITE.discord ? `<a href="${esc(SITE.discord)}">Discord</a>` : ""}.</p>` : ""}
</main></body></html>`;
}
