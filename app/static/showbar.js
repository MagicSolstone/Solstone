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
  ctx: null, out: null, noise: null, solo: false, buses: {}, dest: null, on: lsGet("solstone-fw-sound", false), volume: lsGet("solstone-fw-volume", 0.7), recent: {},
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
    const out = this.dest || this.out;
    if (this.ctx.createStereoPanner) { const p = this.ctx.createStereoPanner(); p.pan.value = pan * 0.8; g.connect(p).connect(out); }
    else g.connect(out);
    return g;
  },
  noiseSrc(t0, dur, rate = 1) {
    const s = this.ctx.createBufferSource();
    s.buffer = this.noise; s.playbackRate.value = rate;
    s.start(t0, Math.random() * 1.5, dur);
    return s;
  },
  filter(type, freq, q = 0.8) { const f = this.ctx.createBiquadFilter(); f.type = type; f.frequency.value = freq; f.Q.value = q; return f; },
  // Each sky has its own channel. Cutting it silences everything it started at once,
  // including sounds already scheduled for later (a fountain's hiss, an echo).
  bus(id) {
    if (!id) return this.out;
    if (!this.buses[id]) { const g = this.ctx.createGain(); g.connect(this.out); this.buses[id] = g; }
    return this.buses[id];
  },
  silence(id) {
    const g = this.buses[id];
    if (!g) return;
    delete this.buses[id];
    try { g.gain.setTargetAtTime(0, this.ctx.currentTime, 0.015); setTimeout(() => g.disconnect(), 120); } catch { g.disconnect(); }
  },
  play(type, info = {}) {
    if (!this.on || document.hidden || !this.ensure()) return;
    this.dest = this.bus(info.bus);
    try { this.playNow(type, info); } finally { this.dest = null; }
  },
  playNow(type, info) {
    if (this.solo && !info.solo) return;            // the firework editor: only the preview makes sound
    const budget = { thunder: [1, 4000], launch: [5, 600], burst: [6, 500], crackle: [3, 900], fizzle: [3, 800], hiss: [3, 1500], ground: [3, 1500] }[type] || [4, 500];
    if (!this.allow(type, ...budget)) return;
    const ctx = this.ctx, t0 = ctx.currentTime + (info.delay || 0) + 0.01, pan = info.pan || 0;
    if (info.sfx && type === "ground") {          // a made-up sound, repeated while a fountain or wheel runs
      const one = Math.max(0.12, sfxLength({ ...info.sfx, echo: 0 }) * 0.9), dur = Math.min(12, info.dur || 4);
      for (let t = 0, n = 0; t < dur && n < 40; t += one, n++) sfxPlay(ctx, this.dest, this.noise, info.sfx, t0 + t, pan, 0.6);
      return;
    }
    if (info.sfx) { sfxPlay(ctx, this.dest, this.noise, info.sfx, t0, pan, type === "launch" ? 0.7 : Math.min(1.3, 0.7 + (info.size || 1) * 0.25)); return; }
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

// ================================================================ "make your own" sounds
// A small bfxr-style synth: one wave (or noise) through an envelope, pitch moves, filters,
// crunch, drive, repeats and an echo. Works on the live context and on an offline one
// (for drawing the waveform in the editor).
const SFX_DEFAULT = { wave: "noise", freq: 600, slide: -0.25, vib: 0, vib_speed: 6, jump: 0, jump_at: 0.5, duty: 0.5, attack: 0, sustain: 0.08,
  punch: 0.5, decay: 1.1, lp: 0.42, lp_sweep: -0.5, res: 0.1, hp: 0, crunch: 0, drive: 0.35, repeat: 1, repeat_gap: 0.08, echo: 0.3, echo_delay: 0.28, volume: 0.6 };
const sfxWaves = new WeakMap();
function sfxPulse(ctx, duty) {
  const key = Math.round(duty * 40);
  let m = sfxWaves.get(ctx);
  if (!m) { m = {}; sfxWaves.set(ctx, m); }
  if (!m[key]) {
    const n = 48, re = new Float32Array(n), im = new Float32Array(n), d = key / 40;
    for (let k = 1; k < n; k++) { re[k] = (2 / (k * Math.PI)) * Math.sin(k * Math.PI * d) * Math.cos(k * Math.PI * d); im[k] = (2 / (k * Math.PI)) * Math.sin(k * Math.PI * d) ** 2; }
    m[key] = ctx.createPeriodicWave(re, im);
  }
  return m[key];
}
const sfxCurves = {};
function sfxShaper(ctx, kind, amount) {
  const key = `${kind}${Math.round(amount * 20)}`;
  if (!sfxCurves[key]) {
    const n = 1024, c = new Float32Array(n);
    if (kind === "crunch") { const steps = 2 ** Math.max(1, Math.round(8 - amount * 7)); for (let i = 0; i < n; i++) { const x = i / (n - 1) * 2 - 1; c[i] = Math.round(x * steps) / steps; } }
    else { const k = 1 + amount * 14; for (let i = 0; i < n; i++) { const x = i / (n - 1) * 2 - 1; c[i] = Math.tanh(k * x) / Math.tanh(k); } }
    sfxCurves[key] = c;
  }
  const w = ctx.createWaveShaper(); w.curve = sfxCurves[key]; return w;
}
const sfxLength = (p) => { const one = (p.attack || 0) + (p.sustain || 0) + (p.decay || 0); return one + ((p.repeat || 1) - 1) * (p.repeat_gap || 0.08) + (p.echo ? (p.echo_delay || 0.25) * 4 : 0); };
function sfxPlay(ctx, dest, noise, p, t0, pan = 0, mul = 1) {
  p = { ...SFX_DEFAULT, ...p };
  // Shared tail: pan, then a dry path and an echo (sound bouncing off the hills).
  const bus = ctx.createGain();
  let tail = bus;
  if (ctx.createStereoPanner && pan) { const pn = ctx.createStereoPanner(); pn.pan.value = pan * 0.8; bus.connect(pn); tail = pn; }
  tail.connect(dest);
  if (p.echo > 0) {
    const dl = ctx.createDelay(1), fb = ctx.createGain(), wet = ctx.createGain();
    dl.delayTime.value = p.echo_delay; fb.gain.value = p.echo * 0.55; wet.gain.value = p.echo * 0.7;
    tail.connect(dl); dl.connect(fb).connect(dl); dl.connect(wet).connect(dest);
  }
  const one = Math.max(0.02, p.attack + p.sustain + p.decay);
  for (let i = 0; i < p.repeat; i++) sfxVoice(ctx, bus, noise, p, t0 + i * p.repeat_gap, one, mul * p.volume * 0.55 * 0.82 ** i);
}
function sfxVoice(ctx, dest, noise, p, ts, dur, level) {
  let src, freqParam;
  if (p.wave === "noise") {
    src = ctx.createBufferSource(); src.buffer = noise; src.loop = true;
    freqParam = src.playbackRate;
    const r = Math.max(0.05, Math.min(8, p.freq / 800));
    freqParam.setValueAtTime(r, ts);
    freqParam.exponentialRampToValueAtTime(Math.max(0.03, Math.min(16, r * 2 ** (p.slide * 3))), ts + dur);
  } else {
    src = ctx.createOscillator();
    if (p.wave === "square" && Math.abs(p.duty - 0.5) > 0.01) src.setPeriodicWave(sfxPulse(ctx, p.duty));
    else src.type = { square: "square", saw: "sawtooth", triangle: "triangle", sine: "sine" }[p.wave] || "square";
    freqParam = src.frequency;
    freqParam.setValueAtTime(p.freq, ts);
    freqParam.exponentialRampToValueAtTime(Math.max(20, Math.min(20000, p.freq * 2 ** (p.slide * 3))), ts + dur);
  }
  if (src.detune) {
    if (p.jump) src.detune.setValueAtTime(p.jump * 100, ts + p.jump_at * dur);
    if (p.vib > 0 && p.vib_speed > 0) {
      const lfo = ctx.createOscillator(), lg = ctx.createGain();
      lfo.frequency.value = p.vib_speed; lg.gain.value = p.vib * 700;
      lfo.connect(lg).connect(src.detune); lfo.start(ts); lfo.stop(ts + dur + 0.05);
    }
  }
  let node = src;
  if (p.crunch > 0) node = node.connect(sfxShaper(ctx, "crunch", p.crunch));
  if (p.hp > 0) { const hp = ctx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 20 * 400 ** p.hp; node = node.connect(hp); }
  if (p.lp < 1 || p.lp_sweep) {
    const lp = ctx.createBiquadFilter(), f0 = 80 * 250 ** p.lp;
    lp.type = "lowpass"; lp.Q.value = 0.5 + p.res * 14;
    lp.frequency.setValueAtTime(f0, ts);
    lp.frequency.exponentialRampToValueAtTime(Math.max(40, Math.min(20000, f0 * 2 ** (p.lp_sweep * 5))), ts + dur);
    node = node.connect(lp);
  }
  if (p.drive > 0) node = node.connect(sfxShaper(ctx, "drive", p.drive));
  const env = ctx.createGain(), g = env.gain, a = ts + p.attack, sEnd = a + p.sustain;
  g.setValueAtTime(0.0001, ts);
  g.linearRampToValueAtTime(level * (1 + p.punch), Math.max(ts + 0.002, a));
  g.linearRampToValueAtTime(level, Math.max(ts + 0.003, sEnd));
  g.exponentialRampToValueAtTime(0.0001, sEnd + Math.max(0.01, p.decay));
  node.connect(env).connect(dest);
  if (p.wave === "noise") src.start(ts, Math.random() * 1.5); else src.start(ts);
  src.stop(ts + dur + 0.05);
}
// The editor's ▶: play one sound now (even with sounds off, because someone asked).
FWAudio.preview = function (p) {
  if (!this.ensure()) return;
  this.silence("sfx-preview");
  sfxPlay(this.ctx, this.bus("sfx-preview"), this.noise, p, this.ctx.currentTime + 0.02, 0, 1);
};
// Draw what a sound looks like (rendered offline, so nothing plays).
async function sfxRender(p, sampleRate = 11025) {
  const C = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  if (!C) return null;
  const secs = Math.min(8, sfxLength({ ...SFX_DEFAULT, ...p }) + 0.1), ctx = new C(1, Math.ceil(secs * sampleRate), sampleRate);
  const len = sampleRate * 2, buf = ctx.createBuffer(1, len, sampleRate), data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
  sfxPlay(ctx, ctx.destination, buf, p, 0, 0, 1);
  return (await ctx.startRendering()).getChannelData(0);
}

// Starting points, bfxr style: each press makes a new variation.
const SFX_MAKERS = (() => {
  const r = (a, b) => a + Math.random() * (b - a), pick = (...xs) => xs[Math.floor(Math.random() * xs.length)];
  const base = { ...SFX_DEFAULT, slide: 0, punch: 0, lp: 1, lp_sweep: 0, res: 0, drive: 0, echo: 0, vib: 0, jump: 0, crunch: 0, hp: 0, repeat: 1 };
  return {
    boom: () => ({ ...base, wave: "noise", freq: r(350, 800), slide: r(-0.4, -0.1), sustain: r(0.04, 0.14), punch: r(0.3, 0.8), decay: r(0.8, 1.6), lp: r(0.3, 0.5), lp_sweep: r(-0.7, -0.3), drive: r(0.2, 0.5), echo: r(0.15, 0.4), echo_delay: r(0.2, 0.35) }),
    pop: () => ({ ...base, wave: pick("noise", "square"), freq: r(700, 1600), slide: r(-0.5, 0), sustain: r(0.01, 0.04), punch: r(0.4, 0.9), decay: r(0.08, 0.2), lp: r(0.6, 0.85), duty: r(0.2, 0.5) }),
    thud: () => ({ ...base, wave: pick("sine", "triangle"), freq: r(70, 130), slide: r(-0.6, -0.3), sustain: r(0.03, 0.08), punch: r(0.5, 1), decay: r(0.3, 0.6), drive: r(0.3, 0.7) }),
    crackle: () => ({ ...base, wave: "noise", freq: r(2500, 5000), sustain: 0.004, decay: r(0.02, 0.05), hp: r(0.4, 0.7), repeat: Math.round(r(5, 8)), repeat_gap: r(0.035, 0.09), volume: 0.5 }),
    whistle: () => ({ ...base, wave: pick("sine", "triangle"), freq: r(650, 1100), slide: r(0.3, 0.55), attack: r(0.03, 0.08), sustain: r(0.6, 1), decay: r(0.15, 0.35), vib: r(0, 0.08), vib_speed: r(6, 12), volume: 0.35 }),
    whoosh: () => ({ ...base, wave: "noise", freq: r(200, 450), slide: r(0.15, 0.4), attack: r(0.1, 0.2), sustain: r(0.2, 0.4), decay: r(0.4, 0.7), lp: r(0.4, 0.55), lp_sweep: r(0.2, 0.5), hp: r(0.05, 0.15) }),
    zap: () => ({ ...base, wave: pick("square", "saw"), freq: r(1200, 2600), slide: r(-0.8, -0.45), duty: r(0.1, 0.5), sustain: r(0.05, 0.15), decay: r(0.1, 0.25), volume: 0.35 }),
    sparkle: () => ({ ...base, wave: "square", freq: r(900, 1600), jump: pick(4, 5, 7, 12), jump_at: r(0.2, 0.4), duty: r(0.25, 0.5), sustain: r(0.05, 0.12), punch: r(0.2, 0.5), decay: r(0.15, 0.35), repeat: pick(1, 2, 3), repeat_gap: r(0.08, 0.14), volume: 0.3 }),
    thunder: () => ({ ...base, wave: "noise", freq: r(90, 180), attack: r(0.1, 0.3), sustain: r(0.3, 0.6), decay: r(1.8, 2.8), lp: r(0.1, 0.2), drive: r(0.2, 0.4), echo: r(0.3, 0.6), echo_delay: r(0.3, 0.5) }),
    chip: () => ({ ...base, wave: "square", freq: r(200, 600), slide: r(-0.3, 0.3), duty: pick(0.125, 0.25, 0.5), sustain: r(0.05, 0.2), decay: r(0.1, 0.3), crunch: r(0.3, 0.7), jump: pick(0, 7, 12, -12), volume: 0.35 }),
    random: () => {
      const p = { wave: pick("square", "saw", "triangle", "sine", "noise", "noise") };
      for (const [k, [lo, hi]] of Object.entries(SFX_RANGES)) p[k] = r(lo, hi);
      p.repeat = Math.random() < 0.7 ? 1 : Math.round(r(2, 6)); p.jump = Math.random() < 0.6 ? 0 : Math.round(p.jump);
      p.attack *= Math.random() * 0.5; p.sustain *= 0.4; p.decay = Math.min(p.decay, 1.5); p.lp = Math.max(0.25, p.lp); p.hp *= 0.5; p.volume = 0.5;
      p.vib *= Math.random() < 0.5 ? 0 : 0.5; p.crunch *= Math.random() < 0.6 ? 0 : 1; p.echo *= Math.random() < 0.5 ? 0 : 1;
      return p;
    },
  };
})();
// [min, max, step] for every slider, matching the server's limits.
const SFX_RANGES = { freq: [20, 5000, 1], slide: [-1, 1, 0.01], vib: [0, 1, 0.01], vib_speed: [0, 30, 0.5], jump: [-12, 12, 1], jump_at: [0, 1, 0.01],
  duty: [0.05, 0.5, 0.01], attack: [0, 1, 0.01], sustain: [0, 2, 0.01], punch: [0, 1, 0.01], decay: [0, 3, 0.01], lp: [0, 1, 0.01], lp_sweep: [-1, 1, 0.01],
  res: [0, 1, 0.01], hp: [0, 1, 0.01], crunch: [0, 1, 0.01], drive: [0, 1, 0.01], repeat: [1, 8, 1], repeat_gap: [0.02, 0.5, 0.01], echo: [0, 1, 0.01], echo_delay: [0.05, 0.6, 0.01], volume: [0, 1, 0.01] };
function sfxMutate(p) {
  const out = { ...SFX_DEFAULT, ...p };
  for (const [k, [lo, hi, step]] of Object.entries(SFX_RANGES)) {
    if (k === "volume" || k === "repeat" || Math.random() < 0.4) continue;
    const v = out[k] + (Math.random() - 0.5) * (hi - lo) * 0.1;
    out[k] = Math.max(lo, Math.min(hi, Math.round(v / step) * step));
  }
  return out;
}

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

  // ---- director: game events, holidays, finales (the holiday banner itself is in board.js)
  const count = document.createElement("div");
  count.className = "fw-countdown"; count.hidden = true;
  document.body.append(count); els.push(count);
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
    const now = Date.now() / 1000;
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
