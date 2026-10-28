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
    .replace(/!\[([^\]]*)\]\((\/api\/public\/images\/[0-9a-f]{16}\.(?:png|jpg|gif|webp))\)/g, '<img class="post-img" src="$2" alt="$1" loading="lazy">')
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
