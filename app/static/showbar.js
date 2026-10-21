/* Solstone — everything around the fireworks sky that isn't drawing it:
   - the floating control (launch, Show, sounds, music, hide the page),
   - firework sounds made in the browser (Web Audio, nothing to download),
   - the music player for the playlist an admin uploads,
   - the "director": fireworks for things happening in the game, holiday themes,
     scheduled finales and the New Year countdown.
   Loaded after sky.js and hud.js. Pages call startShowBar(scene, opts). */
"use strict";

const lsGet = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage is optional */ } };

// ================================================================ firework sounds
const FWAudio = {
  ctx: null, out: null, noise: null, on: lsGet("solstone-fw-sound", false), volume: lsGet("solstone-fw-volume", 0.7), recent: {},
  ensure() {
    if (!this.ctx) {
      const C = window.AudioContext || window.webkitAudioContext;
      if (!C) return false;
      this.ctx = new C();
      this.out = this.ctx.createGain();
      this.out.gain.value = this.volume;
      // A gentle limiter so a big finale can't clip.
      const comp = this.ctx.createDynamicsCompressor();
      comp.threshold.value = -14; comp.ratio.value = 8;
      this.out.connect(comp).connect(this.ctx.destination);
      const len = this.ctx.sampleRate * 2, buf = this.ctx.createBuffer(1, len, this.ctx.sampleRate), data = buf.getChannelData(0);
      for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
      this.noise = buf;
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
    return true;
  },
  setOn(v) { this.on = v; lsSet("solstone-fw-sound", v); if (v) this.ensure(); },
  setVolume(v) { this.volume = v; lsSet("solstone-fw-volume", v); if (this.out) this.out.gain.value = v; },
  // Too many sounds at once is just noise: each kind gets a small budget per moment.
  allow(type, per, ms) {
    const now = performance.now(), list = (this.recent[type] ||= []).filter((t) => now - t < ms);
    this.recent[type] = list;
    if (list.length >= per) return false;
    list.push(now);
    return true;
  },
  chain(pan, t0) {
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0, t0);
    if (this.ctx.createStereoPanner) { const p = this.ctx.createStereoPanner(); p.pan.value = pan * 0.8; g.connect(p).connect(this.out); }
    else g.connect(this.out);
    return g;
  },
  noiseSrc(t0, dur, rate = 1) {
    const s = this.ctx.createBufferSource();
    s.buffer = this.noise; s.playbackRate.value = rate;
    s.start(t0, Math.random() * 1.5, dur);
    return s;
  },
  filter(type, freq, q = 0.8) { const f = this.ctx.createBiquadFilter(); f.type = type; f.frequency.value = freq; f.Q.value = q; return f; },
  play(type, info = {}) {
    if (!this.on || document.hidden || !this.ensure()) return;
    const budget = { thunder: [1, 4000], launch: [5, 600], burst: [6, 500], crackle: [3, 900], fizzle: [3, 800], hiss: [3, 1500] }[type] || [4, 500];
    if (!this.allow(type, ...budget)) return;
    const ctx = this.ctx, t0 = ctx.currentTime + (info.delay || 0) + 0.01, pan = info.pan || 0;
    if (type === "launch" && info.style === "whistle") {
      const o = ctx.createOscillator(), g = this.chain(pan, t0);
      o.type = "triangle"; o.frequency.setValueAtTime(900, t0); o.frequency.exponentialRampToValueAtTime(2600, t0 + 1.1);
      g.gain.linearRampToValueAtTime(0.07, t0 + 0.08); g.gain.linearRampToValueAtTime(0.0001, t0 + 1.2);
      o.connect(g); o.start(t0); o.stop(t0 + 1.25);
    } else if (type === "launch") {
      const f = this.filter("bandpass", 500, 1.2), g = this.chain(pan, t0);
      f.frequency.exponentialRampToValueAtTime(1900, t0 + 0.75);
      g.gain.linearRampToValueAtTime(0.16, t0 + 0.12); g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.95);
      this.noiseSrc(t0, 1).connect(f).connect(g);
    } else if (type === "burst") {
      const size = Math.min(2, info.size || 1), kind = info.kind || "boom";
      if (kind === "crack") { for (let i = 0; i < 5; i++) this.click(t0 + i * 0.03 + Math.random() * 0.02, pan, 0.35); return; }
      const lp = this.filter("lowpass", kind === "pop" ? 2600 : 1100), g = this.chain(pan, t0);
      const dur = kind === "pop" ? 0.18 : kind === "thud" ? 0.45 : 0.9 + size * 0.5;
      lp.frequency.exponentialRampToValueAtTime(kind === "pop" ? 600 : 140, t0 + dur);
      g.gain.linearRampToValueAtTime((kind === "pop" ? 0.45 : 0.75) * (0.6 + size * 0.3), t0 + 0.006);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      this.noiseSrc(t0, dur + 0.05).connect(lp).connect(g);
      if (kind !== "pop") {                          // the low thump you feel
        const o = ctx.createOscillator(), og = this.chain(pan, t0);
        o.frequency.setValueAtTime(kind === "thud" ? 90 : 70, t0); o.frequency.exponentialRampToValueAtTime(32, t0 + 0.45);
        og.gain.linearRampToValueAtTime(0.5 * size, t0 + 0.01); og.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.5);
        o.connect(og); o.start(t0); o.stop(t0 + 0.55);
      }
    } else if (type === "crackle") {
      const n = Math.round((info.dur || 1.2) * 45);
      for (let i = 0; i < n; i++) this.click(t0 + Math.random() * (info.dur || 1.2), pan + (Math.random() - 0.5) * 0.3, 0.05 + Math.random() * 0.16);
    } else if (type === "thunder") {                 // a low rolling rumble
      const lp = this.filter("lowpass", 220, 0.7), g = this.chain(pan, t0 + 0.4);
      g.gain.linearRampToValueAtTime(0.5, t0 + 0.55); g.gain.exponentialRampToValueAtTime(0.0001, t0 + 3.4);
      this.noiseSrc(t0 + 0.4, 3.2, 0.5).connect(lp).connect(g);
    } else if (type === "fizzle" || type === "hiss") {
      const dur = type === "hiss" ? Math.min(10, info.dur || 4) : 1.1;
      const f = this.filter("bandpass", type === "hiss" ? 4200 : 2600, 0.7), g = this.chain(pan, t0);
      const level = type === "hiss" ? (info.soft ? 0.025 : 0.06) : 0.09;
      g.gain.linearRampToValueAtTime(level, t0 + 0.15); g.gain.setValueAtTime(level, t0 + dur * 0.8); g.gain.linearRampToValueAtTime(0.0001, t0 + dur);
      const src = this.ctx.createBufferSource();
      src.buffer = this.noise; src.loop = true; src.start(t0); src.stop(t0 + dur + 0.05);
      src.connect(f).connect(g);
      if (type === "hiss") for (let i = 0; i < dur * 8; i++) this.click(t0 + Math.random() * dur, pan, 0.04 + Math.random() * 0.05);
    }
  },
  click(t, pan, level) {
    const hp = this.filter("highpass", 1500 + Math.random() * 2500), g = this.chain(pan, t);
    g.gain.linearRampToValueAtTime(level, t + 0.002); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.012 + Math.random() * 0.02);
    this.noiseSrc(t, 0.04, 1 + Math.random()).connect(hp).connect(g);
  },
};

// ================================================================ music player
const FWMusic = {
  audio: null, tracks: [], idx: lsGet("solstone-music-idx", 0), shuffle: lsGet("solstone-music-shuffle", false),
  volume: lsGet("solstone-music-volume", 0.5), loaded: false, onchange: () => {},
  async load() {
    try { const r = await fetch("/api/public/music", { credentials: "same-origin" }); this.tracks = r.ok ? await r.json() : []; } catch { this.tracks = []; }
    this.loaded = true;
    if (this.idx >= this.tracks.length) this.idx = 0;
    this.onchange();
  },
  el() {
    if (!this.audio) {
      this.audio = new Audio();
      this.audio.preload = "none";
      this.audio.volume = this.volume;
      this.audio.addEventListener("ended", () => this.next());
      ["play", "pause", "error"].forEach((e) => this.audio.addEventListener(e, () => this.onchange()));
    }
    return this.audio;
  },
  get playing() { return !!this.audio && !this.audio.paused; },
  get current() { return this.tracks[this.idx]; },
  play(i = this.idx) {
    if (!this.tracks.length) return;
    this.idx = (i + this.tracks.length) % this.tracks.length; lsSet("solstone-music-idx", this.idx);
    const a = this.el(), url = `/api/public/music/${encodeURIComponent(this.current.id)}`;
    if (!a.src.endsWith(url)) a.src = url;
    a.play().catch(() => {});
    lsSet("solstone-music-on", true);
    this.onchange();
  },
  pause() { this.audio?.pause(); lsSet("solstone-music-on", false); this.onchange(); },
  toggle() { this.playing ? this.pause() : this.play(); },
  next() { this.play(this.shuffle && this.tracks.length > 2 ? this.idx + 1 + Math.floor(Math.random() * (this.tracks.length - 1)) : this.idx + 1); },
  prev() { if (this.audio && this.audio.currentTime > 4) { this.audio.currentTime = 0; return; } this.play(this.idx - 1); },
  setVolume(v) { this.volume = v; lsSet("solstone-music-volume", v); if (this.audio) this.audio.volume = v; },
  stop() { if (this.audio) { this.audio.pause(); this.audio.removeAttribute("src"); this.audio.load(); } this.onchange(); },
};

// ================================================================ the bar
// opts: key (localStorage name for the Show switch), defaultOn, hide (offer "hide the page"),
// controls (false = director only, e.g. the sign-in page), onEvent(item) to show a message.
function startShowBar(scene, opts = {}) {
  const els = [];
  const cleanup = [];
  if (opts.controls !== false) {
    let on = lsGet(opts.key || "solstone-sky", null);
    if (on == null) on = !!opts.defaultOn && !matchMedia("(prefers-reduced-motion: reduce)").matches;
    scene.setAuto(on);
    const box = document.createElement("div");
    box.className = "sky-ctl glass";
    box.innerHTML = `<button type="button" class="sky-launch" title="Launch a firework" aria-label="Launch a firework">🎆</button>
      <button type="button" class="sky-auto" aria-pressed="${on}" title="Keep launching fireworks"><span class="sky-sw"></span><span>Show</span></button>
      <button type="button" class="sky-sound" aria-pressed="${FWAudio.on}" title="Firework sounds" aria-label="Firework sounds">${FWAudio.on ? "🔊" : "🔇"}</button>
      <button type="button" class="sky-music" title="Music" aria-label="Music" hidden>🎵</button>
      ${opts.hide ? `<button type="button" class="sky-hide" title="Hide the page and just watch (Esc to come back)" aria-label="Hide the page">👁</button>` : ""}`;
    document.body.append(box); els.push(box);
    const pop = document.createElement("div");
    pop.className = "music-pop glass"; pop.hidden = true;
    document.body.append(pop); els.push(pop);

    const autoBtn = box.querySelector(".sky-auto"), soundBtn = box.querySelector(".sky-sound"), musicBtn = box.querySelector(".sky-music");
    box.querySelector(".sky-launch").addEventListener("click", () => { FWAudio.on && FWAudio.ensure(); scene.launch(); });
    autoBtn.addEventListener("click", () => { on = !on; scene.setAuto(on); autoBtn.setAttribute("aria-pressed", String(on)); lsSet(opts.key || "solstone-sky", on); });
    soundBtn.addEventListener("click", () => {
      FWAudio.setOn(!FWAudio.on);
      soundBtn.setAttribute("aria-pressed", String(FWAudio.on)); soundBtn.textContent = FWAudio.on ? "🔊" : "🔇";
      if (FWAudio.on) scene.launch();                // a firework so you hear it straight away
    });

    // ---- music
    const renderPop = () => {
      const t = FWMusic.current;
      pop.innerHTML = !FWMusic.tracks.length
        ? `<p class="muted small">No music yet.${typeof me !== "undefined" && me.user?.role === "admin" ? ` Add some under <a href="#/fireworks/settings">Firework settings → Music</a>.` : ""}</p>`
        : `<div class="mp-now"><b>${esc(t?.title || "")}</b><span class="muted small">${FWMusic.idx + 1} of ${FWMusic.tracks.length}</span></div>
          <div class="mp-ctl"><button type="button" data-mp="prev" aria-label="Previous">⏮</button>
            <button type="button" data-mp="toggle" class="mp-play" aria-label="${FWMusic.playing ? "Pause" : "Play"}">${FWMusic.playing ? "⏸" : "▶"}</button>
            <button type="button" data-mp="next" aria-label="Next">⏭</button>
            <button type="button" data-mp="shuffle" aria-pressed="${FWMusic.shuffle}" title="Shuffle" aria-label="Shuffle">🔀</button></div>
          <label class="mp-vol">🔈<input type="range" min="0" max="1" step="0.05" value="${FWMusic.volume}" data-mp-vol aria-label="Music volume"></label>
          <label class="mp-vol">💥<input type="range" min="0" max="1" step="0.05" value="${FWAudio.volume}" data-fx-vol aria-label="Firework sound volume"></label>
          <ol class="mp-list">${FWMusic.tracks.map((x, i) => `<li><button type="button" data-mp-i="${i}" ${i === FWMusic.idx ? 'aria-current="true"' : ""}>${esc(x.title)}</button></li>`).join("")}</ol>`;
      musicBtn.classList.toggle("playing", FWMusic.playing);
    };
    FWMusic.onchange = renderPop;
    pop.addEventListener("click", (e) => {
      e.stopPropagation();                         // re-rendering replaces the button; don't let that count as "outside"
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.mp === "shuffle") { FWMusic.shuffle = !FWMusic.shuffle; lsSet("solstone-music-shuffle", FWMusic.shuffle); renderPop(); }
      else if (b.dataset.mp) FWMusic[b.dataset.mp]();
      else if (b.dataset.mpI) FWMusic.play(+b.dataset.mpI);
    });
    pop.addEventListener("input", (e) => {
      if (e.target.matches("[data-mp-vol]")) FWMusic.setVolume(+e.target.value);
      if (e.target.matches("[data-fx-vol]")) FWAudio.setVolume(+e.target.value);
    });
    musicBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      pop.hidden = !pop.hidden;
      if (!pop.hidden) { renderPop(); const r = box.getBoundingClientRect(); pop.style.right = `${innerWidth - r.right}px`; pop.style.bottom = `${innerHeight - r.top + 8}px`; }
    });
    const closePop = (e) => { if (!pop.hidden && !pop.contains(e.target) && e.target !== musicBtn) pop.hidden = true; };
    document.addEventListener("click", closePop); cleanup.push(() => document.removeEventListener("click", closePop));
    loadFireworkSettings().then(async () => {
      if (!FW.music) return;
      if (!FWMusic.loaded) await FWMusic.load();
      musicBtn.hidden = false; renderPop();
      // Carry on with music if it was playing last time (the browser may need a click first).
      if (lsGet("solstone-music-on", false) && FWMusic.tracks.length && !FWMusic.playing) {
        FWMusic.play();
        const resume = () => { if (lsGet("solstone-music-on", false) && !FWMusic.playing) FWMusic.play(); };
        document.addEventListener("pointerdown", resume, { once: true });
      }
    });

    // ---- hide the page, keep the sky
    if (opts.hide) {
      let wasOn = on, idle = 0;
      const set = (hidden) => {
        document.body.classList.toggle("ui-hidden", hidden);
        if (hidden) { wasOn = on; if (!on) scene.setAuto(true); } else if (!wasOn) scene.setAuto(on);
        poke();
      };
      const poke = () => { box.classList.remove("faded"); clearTimeout(idle); if (document.body.classList.contains("ui-hidden")) idle = setTimeout(() => box.classList.add("faded"), 2500); };
      box.querySelector(".sky-hide").addEventListener("click", () => set(!document.body.classList.contains("ui-hidden")));
      const onKey = (e) => { if (e.key === "Escape" && document.body.classList.contains("ui-hidden")) set(false); };
      document.addEventListener("keydown", onKey); addEventListener("pointermove", poke);
      cleanup.push(() => { document.removeEventListener("keydown", onKey); removeEventListener("pointermove", poke); document.body.classList.remove("ui-hidden"); });
    }
  }

  // ---- director: game events, holidays, finales
  const banner = document.createElement("div");
  banner.className = "fw-banner glass"; banner.hidden = true;
  const count = document.createElement("div");
  count.className = "fw-countdown"; count.hidden = true;
  document.body.append(banner, count); els.push(banner, count);
  let last = -1, pollT = 0, tickT = 0, done = new Set();
  const runShow = (show) => {
    const n = Math.max(1, Math.min(5, show.count || 1));
    for (let i = 0; i < n; i++) setTimeout(() => {
      if (show.play) return;
      if (show.design) scene.launch(show.design);
      else if (show.kind === "showpiece") scene.showpiece();
      else if (show.kind === "random" || !show.kind) scene.launch();
      else scene.launch(show.kind);
    }, i * 450);
    if (show.show) scene.boost(show.show);
    if (show.play) scene.playShow(show.play);
  };
  const poll = async () => {
    clearTimeout(pollT);
    if (!document.hidden) {
      try {
        const r = await fetch(`/api/public/fireworks/feed?since=${last}`, { credentials: "same-origin", cache: "no-store" });
        if (r.ok) {
          const f = await r.json();
          if (last >= 0) for (const item of f.items) { runShow(item.show); opts.onEvent?.(item); }
          last = f.last;
        }
      } catch { /* try again soon */ }
    }
    pollT = setTimeout(poll, 4000);
  };
  const tick = () => {
    const now = Date.now() / 1000, th = FW.theme;
    const holidayText = th && (th.message || th.name) ? `${th.emoji || ""} ${th.message || th.name}`.trim() : "";
    banner.hidden = !holidayText; banner.textContent = holidayText;
    let cd = null;
    for (const f of FW.finales || []) {
      if (f.countdown && f.start - now <= 10 && f.start - now > 0) cd = Math.ceil(f.start - now);
      if (now >= f.start && now < f.end && !done.has(f.id + f.start)) {
        done.add(f.id + f.start);
        scene.boost(f.end - now, f.show);
        if (!f.show) for (let i = 0; i < (f.countdown ? 10 : 4); i++) setTimeout(() => scene.launch(), i * 220);   // the opening salvo
        if (f.countdown || f.message) {
          count.hidden = false; count.classList.add("msg"); count.textContent = f.message || f.name;
          setTimeout(() => { count.hidden = true; count.classList.remove("msg"); }, 6000);
        }
      }
    }
    if (cd != null) { count.hidden = false; count.classList.remove("msg"); count.textContent = String(cd); }
    else if (!count.classList.contains("msg")) count.hidden = true;
    tickT = setTimeout(tick, 250);
  };
  // The sky follows a server's in-game time and weather (Show settings → Sky).
  let skyT = 0, lastSkySid = null;
  const pollSky = async () => {
    clearTimeout(skyT);
    const sid = opts.skyServer?.() || "";
    if (!document.hidden || lastSkySid !== sid) {
      lastSkySid = sid;
      try {
        const r = await fetch(`/api/public/sky?sid=${encodeURIComponent(sid)}`, { cache: "no-store" });
        const sky = r.ok ? await r.json() : null;
        scene.setGameSky(sky?.mode === "game" ? sky : null);
      } catch { /* keep the last sky */ }
    }
    skyT = setTimeout(pollSky, 15000);
  };
  // Pages call bar.skyChanged() when the server in view changes.
  const skyChanged = (force) => { if (force || (opts.skyServer?.() || "") !== lastSkySid) pollSky(); };
  // Settings (theme, finales) refresh now and then, so a page left open picks up a new day.
  const refresh = setInterval(() => { fwLoaded = null; loadFireworkSettings(); }, 10 * 60 * 1000);
  loadFireworkSettings().then(() => { poll(); tick(); pollSky(); });
  return {
    skyChanged,
    remove() {
      clearTimeout(pollT); clearTimeout(tickT); clearInterval(refresh); clearTimeout(skyT);
      cleanup.forEach((f) => f()); els.forEach((e) => e.remove());
    },
  };
}
