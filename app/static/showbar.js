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
  ctx: null, out: null, noise: null, solo: false, buses: {}, busChan: {}, dest: null, on: lsGet("solstone-fw-sound", false), volume: lsGet("solstone-fw-volume", 0.7), recent: {},
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
  // Separate switches: the sky behind every page ("sky", the corner 🔊), the firework
  // editor's preview ("editor") and the preview window ("preview").
  chan: { editor: lsGet("solstone-fw-sound-editor", true), preview: lsGet("solstone-fw-sound-preview", true) },
  isOn(channel) { return channel && channel in this.chan ? this.chan[channel] : this.on; },
  setChannel(channel, v) {
    if (!(channel in this.chan)) { this.setOn(v); return; }
    this.chan[channel] = v; lsSet(`solstone-fw-sound-${channel}`, v);
    if (v) this.ensure(); else this.silenceChannel(channel);
  },
  silenceChannel(channel) { for (const id of Object.keys(this.buses)) if (this.busChan[id] === channel) this.silence(id); },
  setVolume(v) { this.volume = v; lsSet("solstone-fw-volume", v); if (this.out) this.out.gain.value = v; },
  // Too many sounds at once is just noise: each kind gets a small budget per moment.
  allow(key, per, ms) {
    const now = performance.now(), list = (this.recent[key] ||= []).filter((t) => now - t < ms);
    this.recent[key] = list;
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
  bus(id, channel) {
    if (!id) return this.out;
    if (!this.buses[id]) { const g = this.ctx.createGain(); g.connect(this.out); this.buses[id] = g; }
    if (channel) this.busChan[id] = channel;
    return this.buses[id];
  },
  silence(id) {
    for (const k of Object.keys(this.recent)) if (k.startsWith(`${id}:`)) delete this.recent[k];   // a fresh start can sound straight away
    const g = this.buses[id];
    if (!g) return;
    delete this.buses[id];
    try { g.gain.cancelScheduledValues(this.ctx.currentTime); g.gain.setValueAtTime(g.gain.value, this.ctx.currentTime); g.gain.linearRampToValueAtTime(0, this.ctx.currentTime + 0.03); } catch { /* cut below */ }
    setTimeout(() => { try { g.disconnect(); } catch { /* already gone */ } }, 60);
  },
  play(type, info = {}) {
    if (!this.isOn(info.channel) || document.hidden || !this.ensure()) return;
    this.dest = this.bus(info.bus, info.channel || "sky");
    try { this.playNow(type, info); } finally { this.dest = null; }
  },
  playNow(type, info) {
    // The firework editor (or a preview window): only its sky makes sound, unless the page is
    // hidden to watch the big sky.
    if (this.solo && !info.solo && !document.body.classList.contains("ui-hidden")) return;
    const budget = { thunder: [1, 4000], launch: [5, 600], burst: [6, 500], crackle: [3, 900], fizzle: [3, 800], hiss: [3, 1500], ground: [3, 1500] }[type] || [4, 500];
    if (!this.allow(`${info.bus || ""}:${type}`, ...budget)) return;
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
// The music keeps its place: the track and position are saved every second, so a reload or
// another Solstone page picks up where it left off. Only one tab plays at a time. With the
// browser's go-ahead (any click) it runs through an equalizer and a little visualizer.
const MUSIC_EQ = {
  flat: ["Flat", 0, 0, 0, 0], bass: ["Bass boost", 8, 0, -1, 0], warm: ["Warm", 4, -1, -4, 0.1], bright: ["Bright", -1, 1, 6, 0],
  vocal: ["Voices", -3, 5, 2, 0], lofi: ["Lo-fi", 3, -2, -10, 0.12], radio: ["Old radio", -10, 6, -8, 0], hall: ["Big hall", 1, 0, 1, 0.5],
};
const FWMusic = {
  audio: null, tracks: [], idx: 0, shuffle: lsGet("solstone-music-shuffle", false),
  volume: lsGet("solstone-music-volume", 0.5), muted: lsGet("solstone-music-muted", false), loaded: false,
  eq: { preset: "flat", bass: 0, mid: 0, treble: 0, space: 0, ...lsGet("solstone-music-eq", {}) },
  graph: null, pendingSeek: null, waiting: false, listeners: new Set(), lastSave: 0,
  tab: Math.random().toString(36).slice(2), channel: "BroadcastChannel" in window ? new BroadcastChannel("solstone-music") : null,
  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); },
  emit(what = "state") { this.listeners.forEach((fn) => { try { fn(what); } catch { /* a view went away */ } }); },
  set onchange(fn) { this.on(fn); },
  // What's queued comes from a source: the radio (the default, which can follow a schedule),
  // a playlist, an album, an artist, or songs picked in the library.
  source: { type: "radio", id: "", name: "" }, radio: null,
  async fetchSource(src) {
    if (src.type === "radio" || !src.type) {
      const r = await fetch("/api/public/music", { credentials: "same-origin" });
      if (!r.ok) throw new Error(r.status);
      const d = await r.json();
      this.radio = d.radio;
      return { src: { type: "radio", id: "", name: `${d.radio.name}` }, tracks: d.tracks };
    }
    const r = await fetch(`/api/music/queue?type=${encodeURIComponent(src.type)}&id=${encodeURIComponent(src.id || "")}`, { credentials: "same-origin" });
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    return { src: { ...src, name: src.name || d.name }, tracks: d.tracks };
  },
  async load() {
    const saved = lsGet("solstone-music-state", null);
    let got = null;
    if (saved?.source && saved.source.type !== "radio") { try { got = await this.fetchSource(saved.source); if (!got.tracks.length) got = null; } catch { got = null; } }
    if (!got) { try { got = await this.fetchSource({ type: "radio" }); } catch { got = { src: { type: "radio", id: "", name: "" }, tracks: [] }; } }
    this.source = got.src; this.tracks = got.tracks;
    this.loaded = true;
    const at = saved ? this.tracks.findIndex((t) => t.id === saved.id) : -1;
    this.idx = at >= 0 ? at : 0;
    if (at >= 0 && saved.t > 0) this.pendingSeek = saved.t;
    if (this.tracks.length) { this.el(); this.setSrc(); }        // loads just the length, so the bar can show it
    if (!this.listening) this.listening = true, this.channel?.addEventListener("message", (e) => { if (e.data?.playing && e.data.playing !== this.tab && this.playing) { this.audio.pause(); this.emit(); } });
    this.emit();
  },
  // Play something else: { type, id, name }, starting at a song (by id) or the top.
  async playSource(src, startId = null, shuffle = false) {
    const got = await this.fetchSource(src);
    if (!got.tracks.length) throw new Error("Nothing to play there");
    this.source = got.src; this.tracks = got.tracks;
    let i = startId ? Math.max(0, this.tracks.findIndex((t) => t.id === startId)) : 0;
    if (shuffle) { this.shuffle = true; lsSet("solstone-music-shuffle", true); i = Math.floor(Math.random() * this.tracks.length); }
    this.idx = -1;                                   // so play() treats it as a new track
    this.play(i);
  },
  artUrl(t) { return t ? `/api/public/music/${encodeURIComponent(t.id)}/art` : ""; },
  el() {
    if (!this.audio) {
      const a = this.audio = new Audio();
      a.preload = "metadata";
      a.addEventListener("ended", () => this.next());
      ["play", "pause", "error"].forEach((e) => a.addEventListener(e, () => { this.save(); this.emit(); }));
      a.addEventListener("loadedmetadata", () => {
        if (this.pendingSeek != null && this.pendingSeek < a.duration - 1) a.currentTime = this.pendingSeek;
        this.pendingSeek = null; this.emit("time");
      });
      a.addEventListener("timeupdate", () => { this.emit("time"); if (Date.now() - this.lastSave > 1000) this.save(); });
      addEventListener("pagehide", () => this.save());
      this.applyVolume();
    }
    return this.audio;
  },
  setSrc() {
    const url = `/api/public/music/${encodeURIComponent(this.current.id)}`;
    if (!this.audio.src.endsWith(url)) this.audio.src = url;
  },
  save() {
    if (!this.audio || !this.current) return;
    this.lastSave = Date.now();
    lsSet("solstone-music-state", { id: this.current.id, t: Math.round(this.audio.currentTime * 10) / 10, playing: this.playing, source: this.source });
  },
  // The equalizer needs the page's audio engine, which a browser only starts after a click.
  wire() {
    if (this.graph || !this.audio || !FWAudio.ensure() || FWAudio.ctx.state !== "running") return;
    const ctx = FWAudio.ctx, src = ctx.createMediaElementSource(this.audio);
    const f = (type, freq, q) => { const n = ctx.createBiquadFilter(); n.type = type; n.frequency.value = freq; if (q) n.Q.value = q; return n; };
    const bass = f("lowshelf", 180), mid = f("peaking", 1200, 0.8), treble = f("highshelf", 4200);
    const gain = ctx.createGain(), dry = ctx.createGain(), wet = ctx.createGain(), conv = ctx.createConvolver(), an = ctx.createAnalyser();
    const len = Math.round(ctx.sampleRate * 2.4), ir = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let c = 0; c < 2; c++) { const d = ir.getChannelData(c); for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / len) ** 2.6; }
    conv.buffer = ir; an.fftSize = 128; an.smoothingTimeConstant = 0.75;
    src.connect(bass).connect(mid).connect(treble);
    treble.connect(dry).connect(gain); treble.connect(conv).connect(wet).connect(gain);
    gain.connect(an); gain.connect(ctx.destination);
    this.graph = { bass, mid, treble, gain, dry, wet, an };
    this.audio.volume = 1;
    this.applyEq(); this.applyVolume();
    this.emit();
  },
  applyEq() {
    lsSet("solstone-music-eq", this.eq);
    const g = this.graph;
    if (!g) return;
    g.bass.gain.value = this.eq.bass; g.mid.gain.value = this.eq.mid; g.treble.gain.value = this.eq.treble;
    g.wet.gain.value = this.eq.space * 0.9; g.dry.gain.value = 1 - this.eq.space * 0.4;
  },
  setPreset(k) { const p = MUSIC_EQ[k]; if (!p) return; Object.assign(this.eq, { preset: k, bass: p[1], mid: p[2], treble: p[3], space: p[4] }); this.applyEq(); this.emit(); },
  applyVolume() {
    const v = this.muted ? 0 : this.volume;
    if (this.graph) { this.graph.gain.gain.value = v; this.audio.volume = 1; }
    else if (this.audio) this.audio.volume = v;
  },
  get playing() { return !!this.audio && !this.audio.paused; },
  get current() { return this.tracks[this.idx]; },
  get time() { return this.audio?.currentTime || this.pendingSeek || 0; },
  get duration() { const d = this.audio?.duration; return Number.isFinite(d) ? d : this.current?.duration || 0; },
  play(i = this.idx) {
    if (!this.tracks.length) return;
    const changed = i !== this.idx || !this.audio || !this.audio.src.endsWith(encodeURIComponent(this.tracks[(i + this.tracks.length) % this.tracks.length].id));
    this.idx = (i + this.tracks.length) % this.tracks.length; lsSet("solstone-music-idx", this.idx);
    if (changed) this.pendingSeek = null;
    this.el(); this.setSrc(); this.wire();
    this.waiting = false;
    this.channel?.postMessage({ playing: this.tab });
    this.audio.play().catch((e) => { if (e?.name === "NotAllowedError") this.waitForClick(); });
    this.emit();
  },
  // A reload can't start sound by itself; carry on at the first click or key press.
  waitForClick() {
    if (this.waiting) return;
    this.waiting = true; this.emit();
    const go = () => { document.removeEventListener("pointerdown", go, true); document.removeEventListener("keydown", go, true); if (this.waiting) this.play(); };
    document.addEventListener("pointerdown", go, true); document.addEventListener("keydown", go, true);
  },
  pause() { this.waiting = false; this.audio?.pause(); this.save(); this.emit(); },
  toggle() { this.playing || this.waiting ? this.pause() : this.play(); },
  next() { this.play(this.shuffle && this.tracks.length > 2 ? this.idx + 1 + Math.floor(Math.random() * (this.tracks.length - 1)) : this.idx + 1); },
  prev() { if (this.audio && this.audio.currentTime > 4) { this.audio.currentTime = 0; return; } this.play(this.idx - 1); },
  seek(t) { if (!this.audio) return; if (this.audio.readyState >= 1) this.audio.currentTime = t; else this.pendingSeek = t; this.save(); this.emit("time"); },
  setVolume(v) { this.volume = v; lsSet("solstone-music-volume", v); if (v > 0 && this.muted) this.setMuted(false); this.applyVolume(); this.emit("volume"); },
  setMuted(m) { this.muted = m; lsSet("solstone-music-muted", m); this.applyVolume(); this.emit("volume"); },
  stop() { if (this.audio) { this.save(); this.audio.pause(); lsSet("solstone-music-state", { ...lsGet("solstone-music-state", {}), playing: false }); } this.emit(); },
};

// ================================================================ the bar
// opts: key (localStorage name for the Show switch), defaultOn, hide (offer "hide the page"),
// controls (false = director only, e.g. the sign-in page), onEvent(item) to show a message.
function startShowBar(scene, opts = {}) {
  const els = [];
  const cleanup = [];
  let musicChanged = () => {};
  if (opts.controls !== false) {
    let on = lsGet(opts.key || "solstone-sky", null);
    if (on == null) on = !!opts.defaultOn && !matchMedia("(prefers-reduced-motion: reduce)").matches;
    scene.setAuto(on);

    // ---- one bar along the bottom: the music on the left, the sky's controls on the right
    const bar = document.createElement("div");
    bar.className = "mbar glass no-music"; bar.setAttribute("role", "region"); bar.setAttribute("aria-label", "Music and fireworks");
    bar.innerHTML = `<div class="mb-music">
        <div class="mb-btns"><button type="button" data-mb="prev" title="Back (or to the start)" aria-label="Previous track">⏮</button>
          <button type="button" data-mb="toggle" class="mb-play" aria-label="Play">▶</button>
          <button type="button" data-mb="next" title="Skip ahead" aria-label="Next track">⏭</button></div>
        <span class="mb-art"><img alt="" hidden><canvas class="mb-viz" aria-hidden="true"></canvas></span>
        <div class="mb-mid"><div class="mb-title"><b></b><span class="mb-sub"></span></div>
          <div class="mb-seek"><span class="mb-t">0:00</span><input type="range" min="0" max="1000" step="1" value="0" aria-label="Position in the track"><span class="mb-d">0:00</span></div></div>
        <div class="mb-btns"><button type="button" data-mb="list" title="Up next, playlists, shuffle and equalizer" aria-label="Up next">☰</button></div>
      </div>
      <div class="mb-sky" role="group" aria-label="Fireworks">
        <button type="button" data-sky="launch" class="mb-launch" title="Launch a firework" aria-label="Launch a firework">🎆</button>
        <button type="button" data-sky="auto" class="sky-auto" aria-pressed="${on}" title="Keep launching fireworks"><span class="sky-sw"></span><span>Show</span></button>
        <button type="button" data-sky="volume" class="mb-vol" title="Firework and music volume" aria-label="Volume" aria-haspopup="dialog">🔊</button>
        ${opts.hide ? `<button type="button" data-sky="hide" class="mb-hide" title="Hide the page and just watch (Esc to come back)" aria-label="Hide the page">👁</button>` : ""}
      </div>`;
    document.body.append(bar); els.push(bar);
    document.body.classList.add("has-mbar"); cleanup.push(() => document.body.classList.remove("has-mbar"));
    const sync = () => {
      bar.querySelector('[data-sky="auto"]').setAttribute("aria-pressed", String(on));
      const v = bar.querySelector('[data-sky="volume"]');
      v.textContent = !FWAudio.on && (FWMusic.muted || !FWMusic.tracks.length) ? "🔇" : "🔊";
      const h = bar.querySelector('[data-sky="hide"]');
      if (h) { const hidden = document.body.classList.contains("ui-hidden"); h.textContent = hidden ? "🗔" : "👁"; h.title = hidden ? "Show the page again (Esc)" : "Hide the page and just watch (Esc to come back)"; }
    };

    // ---- one pop-up for volume, Up next (with shuffle) and the equalizer
    const pop = document.createElement("div");
    pop.className = "music-pop glass"; pop.hidden = true; pop.setAttribute("role", "dialog");
    document.body.append(pop); els.push(pop);
    let popMode = null, popAnchor = null, popLists = null, popListsLoading = false, popFind = "", popAnon = false;
    const fmt = (t) => { t = Math.max(0, Math.floor(t || 0)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
    const pct = (v) => `${Math.round(v * 100)}%`;
    const renderPop = () => {
      if (pop.hidden) return;
      if (popMode === "volume") {
        pop.setAttribute("aria-label", "Volume");
        pop.innerHTML = `<h4>Volume</h4>
          <div class="vol-row"><button type="button" data-vol-mute="fx" aria-pressed="${!FWAudio.on}" title="${FWAudio.on ? "Mute" : "Turn on"} firework sounds">${FWAudio.on ? "💥" : "🔇"}</button>
            <span>Firework sounds</span><input type="range" min="0" max="1" step="0.05" value="${FWAudio.volume}" data-vol="fx" aria-label="Firework sound volume" ${FWAudio.on ? "" : "disabled"}><b>${FWAudio.on ? pct(FWAudio.volume) : "Off"}</b></div>
          ${FW.music && FWMusic.tracks.length ? `<div class="vol-row"><button type="button" data-vol-mute="music" aria-pressed="${FWMusic.muted}" title="${FWMusic.muted ? "Unmute" : "Mute"} music">${FWMusic.muted ? "🔇" : "🎵"}</button>
            <span>Music</span><input type="range" min="0" max="1" step="0.05" value="${FWMusic.volume}" data-vol="music" aria-label="Music volume"><b>${FWMusic.muted ? "Muted" : pct(FWMusic.volume)}</b></div>` : ""}
          <p class="muted small">The firework editor and the preview window have their own sound switches.</p>`;
      } else if (popMode === "list") {
        pop.setAttribute("aria-label", "Up next");
        const src = FWMusic.source, lists = popLists || [];
        const opts = [`<option value="radio:" ${src.type === "radio" ? "selected" : ""}>📻 ${esc(FWMusic.radio?.name || "Solstone radio")}${FWMusic.radio?.why && FWMusic.radio.why !== "The main library" ? ` (${esc(FWMusic.radio.why)})` : ""}</option>`];
        if (src.type !== "radio" && !(src.type === "playlist" && lists.some((l) => l.id === src.id))) opts.push(`<option value="${esc(src.type)}:${esc(src.id || "")}" selected>🎧 ${esc(src.name || "Picked songs")}</option>`);
        lists.forEach((l) => opts.push(`<option value="playlist:${esc(l.id)}" ${src.type === "playlist" && src.id === l.id ? "selected" : ""}>${l.schedule?.on ? "🗓" : l.mine ? "🎶" : "👪"} ${esc(l.name)} · ${l.count}</option>`));
        pop.innerHTML = `<div class="mq-head"><h4>Up next</h4>
            <button type="button" class="mq-tool" data-mq="shuffle" aria-pressed="${FWMusic.shuffle}" title="Shuffle">🔀 Shuffle</button>
            <button type="button" class="mq-tool" data-mq="eq" title="Equalizer">🎚 Equalizer</button></div>
          <select class="input sm mq-src" aria-label="What to play">${opts.join("")}${popListsLoading ? `<option disabled>Loading playlists…</option>` : ""}</select>
          <input class="input sm mq-find" type="search" placeholder="Find a song in this list" aria-label="Find a song" value="${esc(popFind)}">
          <ol class="mp-list mq-list">${FWMusic.tracks.map((x, i) => ({ x, i })).filter(({ x }) => !popFind || `${x.title} ${x.artist} ${x.album}`.toLowerCase().includes(popFind.toLowerCase())).slice(0, 400).map(({ x, i }) => `<li><button type="button" data-mp-i="${i}" ${i === FWMusic.idx ? 'aria-current="true"' : ""}>
            <img src="${FWMusic.artUrl(x)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'"><span><b>${i === FWMusic.idx && FWMusic.playing ? "♪ " : ""}${esc(x.title)}</b><small>${esc([x.artist, x.album].filter(Boolean).join(" · "))}</small></span><i>${x.duration ? fmt(x.duration) : ""}</i></button></li>`).join("") || `<li class="muted small">Nothing matches.</li>`}</ol>
          ${!popAnon && !document.body.classList.contains("status-page") ? `<a class="mq-more" href="#/music">🎵 Open the music library</a>` : ""}`;
        const cur = pop.querySelector('[aria-current="true"]');
        if (cur && !popFind) cur.scrollIntoView({ block: "center" });
        if (popLists == null && !popListsLoading && !popAnon) {
          popListsLoading = true;
          fetch("/api/music/playlists", { credentials: "same-origin" }).then(async (r) => {
            popListsLoading = false;
            if (r.status === 401) { popAnon = true; popLists = []; } else popLists = r.ok ? (await r.json()).playlists : [];
            renderPop();
          }).catch(() => { popListsLoading = false; popLists = []; renderPop(); });
        }
      } else if (popMode === "eq") {
        pop.setAttribute("aria-label", "Equalizer");
        const eq = FWMusic.eq, row = (k, label, min, max, step, show) => `<label class="eq-row"><span>${label}</span><input type="range" min="${min}" max="${max}" step="${step}" value="${eq[k]}" data-eq="${k}"><b>${show(eq[k])}</b></label>`;
        const db = (v) => `${v > 0 ? "+" : ""}${Math.round(v)} dB`;
        pop.innerHTML = `<div class="mq-head"><button type="button" class="mq-tool" data-mq="list">← Up next</button><h4>Equalizer</h4></div>
          <div class="eq-presets">${Object.entries(MUSIC_EQ).map(([k, p]) => `<button type="button" class="btn sm" data-eq-preset="${k}" aria-pressed="${eq.preset === k}">${p[0]}</button>`).join("")}</div>
          ${row("bass", "Bass", -12, 12, 1, db)}${row("mid", "Middle", -12, 12, 1, db)}${row("treble", "Treble", -12, 12, 1, db)}${row("space", "Room echo", 0, 1, 0.05, pct)}
          ${FWMusic.graph ? "" : `<p class="muted small">Press play to hear the equalizer.</p>`}`;
      }
      place();
    };
    const place = () => {
      if (!popAnchor || pop.hidden) return;
      const r = popAnchor.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
      const left = Math.min(innerWidth - w - 10, Math.max(10, r.left + r.width / 2 - w / 2));
      pop.style.left = `${left}px`; pop.style.top = `${Math.max(10, r.top - h - 10)}px`;
    };
    const openPop = (mode, anchor) => {
      if (!pop.hidden && popMode === mode && popAnchor === anchor) { pop.hidden = true; return; }
      if (mode === "list") { popLists = null; popFind = ""; }       // fresh playlists each time it opens
      popMode = mode; popAnchor = anchor; pop.hidden = false; renderPop();
    };
    pop.addEventListener("click", (e) => {
      e.stopPropagation();
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.volMute === "fx") { FWAudio.setOn(!FWAudio.on); if (FWAudio.on) scene.launch(); sync(); }
      else if (b.dataset.volMute === "music") { FWMusic.setMuted(!FWMusic.muted); sync(); }
      else if (b.dataset.mpI) FWMusic.play(+b.dataset.mpI);
      else if (b.dataset.eqPreset) FWMusic.setPreset(b.dataset.eqPreset);
      else if (b.dataset.mq === "shuffle") { FWMusic.shuffle = !FWMusic.shuffle; lsSet("solstone-music-shuffle", FWMusic.shuffle); }
      else if (b.dataset.mq === "eq" || b.dataset.mq === "list") { popMode = b.dataset.mq; }
      renderPop();
    });
    pop.addEventListener("change", async (e) => {
      if (e.target.matches(".mq-src")) {
        const [type, id] = e.target.value.split(":");
        try { await FWMusic.playSource({ type, id, name: e.target.selectedOptions[0].textContent.replace(/^\S+\s/, "").replace(/ · \d+$/, "") }); } catch { /* keep what's playing */ }
        renderPop();
      }
      if (e.target.dataset.vol === "fx" && FWAudio.on) scene.launch();      // hear the new level
    });
    pop.addEventListener("input", (e) => {
      if (e.target.matches(".mq-find")) {
        popFind = e.target.value; const at = e.target.selectionStart; renderPop();
        const f = pop.querySelector(".mq-find"); f.focus(); f.setSelectionRange(at, at); return;
      }
      const t = e.target, out = t.parentElement.querySelector("b");
      if (t.dataset.vol === "fx") { FWAudio.setVolume(+t.value); if (out) out.textContent = pct(+t.value); }
      if (t.dataset.vol === "music") { FWMusic.setVolume(+t.value); if (out) out.textContent = pct(+t.value); }
      if (t.dataset.eq) {
        FWMusic.eq[t.dataset.eq] = +t.value; FWMusic.eq.preset = "custom"; FWMusic.applyEq();
        if (out) out.textContent = t.dataset.eq === "space" ? pct(+t.value) : `${+t.value > 0 ? "+" : ""}${t.value} dB`;
        pop.querySelectorAll("[data-eq-preset]").forEach((x) => x.setAttribute("aria-pressed", "false"));
      }
    });
    const closePop = (e) => { if (!pop.hidden && !pop.contains(e.target) && !e.target.closest?.("[data-sky='volume'], [data-mb='list']")) pop.hidden = true; };
    document.addEventListener("click", closePop); cleanup.push(() => document.removeEventListener("click", closePop));
    addEventListener("resize", place); cleanup.push(() => removeEventListener("resize", place));

    // ---- the bar's buttons
    let seeking = false, vizRaf = 0;
    bar.addEventListener("click", (e) => {
      const s = e.target.closest("[data-sky]"), m = e.target.closest("[data-mb]");
      if (s) {
        const k = s.dataset.sky;
        if (k === "launch") { if (FWAudio.on) FWAudio.ensure(); scene.launch(); }
        else if (k === "auto") { on = !on; scene.setAuto(on); lsSet(opts.key || "solstone-sky", on); sync(); }
        else if (k === "volume") { e.stopPropagation(); openPop("volume", s); }
        else if (k === "hide") setHidden(!document.body.classList.contains("ui-hidden"));
      } else if (m) {
        const k = m.dataset.mb;
        if (k === "toggle") FWMusic.toggle();
        else if (k === "prev") FWMusic.prev();
        else if (k === "next") FWMusic.next();
        else if (k === "list") { e.stopPropagation(); openPop("list", m); }
      }
    });
    const range = bar.querySelector('.mb-seek input');
    range.addEventListener("input", () => { seeking = true; bar.querySelector(".mb-t").textContent = fmt((range.value / 1000) * FWMusic.duration); });
    range.addEventListener("change", () => { seeking = false; FWMusic.seek((range.value / 1000) * FWMusic.duration); });
    const renderTime = () => {
      const d = FWMusic.duration, t = FWMusic.time;
      if (!seeking) {
        bar.querySelector(".mb-t").textContent = fmt(t);
        range.value = d ? Math.round((t / d) * 1000) : 0;
        range.style.setProperty("--p", `${d ? (t / d) * 100 : 0}%`);
      }
      bar.querySelector(".mb-d").textContent = fmt(d);
    };
    const hasMusic = () => !!(FW.music && FWMusic.tracks.length);
    const renderBar = () => {
      bar.classList.toggle("no-music", !hasMusic());
      const t = FWMusic.current, playing = FWMusic.playing;
      bar.classList.toggle("playing", playing);
      const pb = bar.querySelector(".mb-play");
      pb.textContent = playing ? "⏸" : "▶"; pb.setAttribute("aria-label", playing ? "Pause" : "Play");
      const tb = bar.querySelector(".mb-title b");
      tb.textContent = t?.title || ""; tb.title = [t?.title, t?.artist, t?.album].filter(Boolean).join(" · ");
      const img = bar.querySelector(".mb-art img"), url = FWMusic.artUrl(t);
      if (t && img.dataset.src !== url) { img.dataset.src = url; img.hidden = true; img.onload = () => { img.hidden = false; }; img.onerror = () => { img.hidden = true; }; img.src = url; }
      bar.querySelector(".mb-sub").textContent = FWMusic.waiting ? "Click anywhere to carry on" : t?.artist || (FWMusic.tracks.length ? `${FWMusic.idx + 1} of ${FWMusic.tracks.length}` : "");
      renderTime(); sync();
      cancelAnimationFrame(vizRaf);
      drawViz();
    };
    // A small spectrum: bars that dance while music plays (flat when it isn't).
    const drawViz = () => {
      const cv = bar.querySelector(".mb-viz");
      if (!cv.isConnected) return;
      const w = cv.clientWidth, h = cv.clientHeight, dpr = devicePixelRatio || 1;
      if (!w) return;
      if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
      const c = cv.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
      const n = 10, gap = 2, bw = (w - gap * (n - 1)) / n, an = FWMusic.graph?.an;
      const data = an ? new Uint8Array(an.frequencyBinCount) : null;
      if (an) an.getByteFrequencyData(data);
      for (let i = 0; i < n; i++) {
        const v = data ? data[Math.min(data.length - 1, Math.floor(1 + i ** 1.45))] / 255 : (FWMusic.playing ? 0.25 + 0.2 * Math.sin(performance.now() / 300 + i) : 0.08);
        const bh = Math.max(2, Math.round(v * h));
        c.fillStyle = `hsl(${42 - i * 3}, 85%, ${55 + v * 20}%)`;
        c.fillRect(Math.round(i * (bw + gap)), h - bh, Math.max(1, Math.floor(bw)), bh);
      }
      if (FWMusic.playing && !document.hidden) vizRaf = requestAnimationFrame(drawViz);
    };
    cleanup.push(FWMusic.on((what) => { if (what === "time") renderTime(); else { renderBar(); renderPop(); } }));
    cleanup.push(() => cancelAnimationFrame(vizRaf));
    renderBar();
    musicChanged = () => renderBar();
    loadFireworkSettings().then(async () => {
      if (!FW.music) { renderBar(); return; }
      if (!FWMusic.loaded) await FWMusic.load();
      renderBar();
      // Carry on where it left off (same track, same spot). The browser may need a click first.
      if (FWMusic.tracks.length && lsGet("solstone-music-state", {}).playing && !FWMusic.playing) FWMusic.play();
    });

    // ---- hide the page, keep the sky (the bar stays, and fades when the mouse is still)
    let setHidden = () => {};
    if (opts.hide) {
      let wasOn = on, idle = 0;
      setHidden = (hidden) => {
        document.body.classList.toggle("ui-hidden", hidden);
        if (hidden) { wasOn = on; if (!on) { on = true; scene.setAuto(true); } } else if (!wasOn) { on = false; scene.setAuto(false); }
        sync(); poke();
      };
      const poke = () => {
        bar.classList.remove("faded"); document.body.classList.remove("pointer-idle"); clearTimeout(idle);
        if (document.body.classList.contains("ui-hidden")) idle = setTimeout(() => { if (pop.hidden) { bar.classList.add("faded"); document.body.classList.add("pointer-idle"); } }, 3000);
      };
      const onKey = (e) => { if (e.key === "Escape" && document.body.classList.contains("ui-hidden")) setHidden(false); };
      document.addEventListener("keydown", onKey); addEventListener("pointermove", poke);
      addEventListener("pointerdown", poke);
      cleanup.push(() => { document.removeEventListener("keydown", onKey); removeEventListener("pointermove", poke); removeEventListener("pointerdown", poke); document.body.classList.remove("ui-hidden", "pointer-idle"); });
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
    musicChanged: () => musicChanged(),
    remove() {
      clearTimeout(pollT); clearTimeout(tickT); clearInterval(refresh); clearTimeout(skyT);
      cleanup.forEach((f) => f()); els.forEach((e) => e.remove());
    },
  };
}
