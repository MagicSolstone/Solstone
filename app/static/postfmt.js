/* Solstone — the text of posts and guides: a small, safe subset of Markdown, plus colours and sizes.
   Shared by the public site (home.js) and the post editor's live preview (website.js), so the preview is exactly
   what visitors see. The text is escaped first and only then formatted, so it can never carry HTML of its own.

   One line break is a new line; a blank line is a new paragraph.
   # Heading · ## Subheading · ### Small heading · **bold** · *italic* · - list · 1. list · > quote · --- line
   [a link](https://…) or (mailto:…) · ![a picture](/api/public/images/…) · {red}coloured{/red} · {big}bigger{/big} · {small}smaller{/small} */
"use strict";

const POST_COLOURS = [["red", "Red"], ["orange", "Orange"], ["gold", "Gold"], ["green", "Green"], ["aqua", "Aqua"],
  ["blue", "Blue"], ["purple", "Purple"], ["pink", "Pink"], ["gray", "Grey"]];
const POST_SIZES = [["big", "Bigger"], ["small", "Smaller"]];
const _STYLE_RE = new RegExp(`\\{(${[...POST_COLOURS, ...POST_SIZES].map(([k]) => k).join("|")})\\}([\\s\\S]*?)\\{\\/\\1\\}`, "g");

function inline(s) {
  let out = s
    // pictures uploaded in Website (only those: nothing loaded from elsewhere)
    // ![words|small](…): a size after the words (small, medium, large); none is full width
    .replace(/!\[([^\]|]*)(?:\|(small|medium|large))?\]\((\/api\/public\/images\/[0-9a-f]{16}\.(?:png|jpg|gif|webp))\)/g,
      (_, alt, size, src) => `<img class="post-img${size ? ` post-img-${size}` : ""}" src="${src}" alt="${alt}" loading="lazy">`)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(>])[*_]([^*_]+)[*_](?=[\s).,!?:;<]|$)/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\(((?:https?:\/\/|mailto:|\/(?!\/)|#[\w-]+(?=\)))[^\s)]*)\)/g, (_, t, href) =>
      `<a href="${href}"${/^(\/|#|mailto:)/.test(href) ? "" : ' target="_blank" rel="noopener"'}>${t}</a>`);
  for (let i = 0; i < 3 && _STYLE_RE.test(out); i++) {          // a colour inside a size (or the other way round)
    _STYLE_RE.lastIndex = 0;
    out = out.replace(_STYLE_RE, (_, k, t) => `<span class="pf-${k}">${t}</span>`);
  }
  _STYLE_RE.lastIndex = 0;
  return out;
}

function markdown(src) {
  const lines = esc(src).replace(/\r/g, "").split("\n");
  const out = [];
  let list = null, para = [];
  const flush = () => {
    if (para.length) { out.push(`<p>${inline(para.join("<br>"))}</p>`); para = []; }
    if (list) { out.push(`</${list}>`); list = null; }
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    let m;
    if (!line.trim()) { flush(); continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { flush(); out.push("<hr>"); continue; }
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) { flush(); const n = Math.min(4, m[1].length + 1); out.push(`<h${n}>${inline(m[2])}</h${n}>`); continue; }
    if ((m = line.match(/^&gt;\s?(.*)$/))) { flush(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if ((m = line.match(/^\s*[-*]\s+(.*)$/)) || (m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      const kind = /^\s*\d/.test(line) ? "ol" : "ul";
      if (para.length) { out.push(`<p>${inline(para.join("<br>"))}</p>`); para = []; }
      if (list !== kind) { if (list) out.push(`</${list}>`); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline(m[1])}</li>`);
      continue;
    }
    if (list) { out.push(`</${list}>`); list = null; }
    para.push(line.trim());
  }
  flush();
  return out.join("");
}

// An event on the Events page (app and public): its name, time and description, then its challenges in order
// as a row of cards that scrolls sideways. Signed in, each says who's coming and has its own "I'm coming!".
function upEventHtml(it, signedIn = false) {
  const parts = it.parts || [];
  const allMe = signedIn && parts.length && parts.every((p) => p.me);
  const desc = (it.detail || "").split("\n").map((l) => esc(l)).join("<br>");
  const pill = (p) => `<li class="up-pill ${p.live ? "live" : ""} ${p.done ? "done" : ""}">
      <span class="up-pill-time">${p.live ? "On now" : `${p.approx ? "≈" : ""}${esc(p.time)}`}</span>
      <span class="up-pill-name"><span aria-hidden="true">${esc(p.emoji)}</span> ${esc(p.title)}</span>
      ${p.note ? `<span class="up-pill-note">${esc(p.note)}</span>` : ""}
      ${signedIn && !p.done ? `<button type="button" class="btn sm up-coming ${p.me ? "on" : ""}" data-coming="${esc(p.key)}" aria-pressed="${!!p.me}"
        title="${esc((p.who || []).join(", "))}">${p.me ? "✅ Coming" : "🙋 I'm coming"}${p.coming ? ` · ${p.coming}` : ""}</button>` : ""}</li>`;
  const who = signedIn ? [...new Set(parts.flatMap((p) => p.who || []))].sort((a, b) => a.localeCompare(b)) : [];
  return `<li class="up-event ${it.live ? "live" : ""}">
    <div class="up-event-head"><div class="up-main"><b>${it.link && signedIn ? `<a href="${esc(it.link)}">${esc(it.title)}</a>` : esc(it.title)}</b>
        <span class="muted small">${esc([it.server, `${parts.length} challenge${parts.length === 1 ? "" : "s"}`, it.repeat === "weekly" ? "every week" : it.repeat === "daily" ? "every day" : ""].filter(Boolean).join(" · "))}</span></div>
      <span class="up-when">${it.live ? '<span class="state-pill live"><span class="status-dot on"></span>On now</span>' : `${esc(it.time)}${it.end_time ? `–${esc(it.end_time)}` : ""}`}</span></div>
    ${desc ? `<p class="up-event-desc">${desc}</p>` : ""}
    <ol class="up-pills">${parts.map(pill).join("")}</ol>
    <div class="up-event-foot">${it.optin ? `<span class="muted small">Join each one in the game with <code>/trigger join</code></span>` : ""}
      ${signedIn && parts.some((p) => !p.done) ? `<button type="button" class="btn sm up-coming ${allMe ? "on" : ""}" data-coming-all="${esc(parts.filter((p) => !p.done).map((p) => p.key).join(","))}" aria-pressed="${allMe}">${allMe ? "✅ Coming to all of it" : "🙋 I'm coming to all of it"}</button>` : ""}</div>
    ${who.length ? `<p class="small up-who">🙋 ${esc(who.join(", "))}</p>` : ""}
  </li>`;
}
