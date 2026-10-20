/* Solstone — sign-in page: pixel fireworks over the hill, and a link to the public
   status page when it's turned on. The sky itself lives in sky.js. */
"use strict";

const loginScene = { stop: null };

function startLoginScene() {
  stopLoginScene();
  const cv = document.getElementById("login-sky");
  const card = document.querySelector(".login-card");
  if (!cv || !card) return;
  loginScene.stop = startSkyScene(cv, { avoid: card }).stop;
}

function stopLoginScene() { if (loginScene.stop) { loginScene.stop(); loginScene.stop = null; } }

async function loadPublicStatus() {
  const link = document.getElementById("login-status-link");
  if (!link) return;
  let data;
  try { data = await (await fetch("/api/public/status")).json(); } catch { return; }
  if (!data.enabled) { link.hidden = true; return; }
  const playing = data.servers.reduce((a, s) => a + (s.running !== false ? s.online : 0), 0);
  const up = data.servers.filter((s) => s.running !== false).length;
  link.hidden = false;
  link.innerHTML = `<span class="status-dot ${up ? "on" : ""}"></span><span><b>Live server status</b><small>${
    !data.servers.length ? "No servers" : !up ? "Servers are offline" : playing ? `${playing} playing now` : "Online · nobody playing"}</small></span><span aria-hidden="true">→</span>`;
}
