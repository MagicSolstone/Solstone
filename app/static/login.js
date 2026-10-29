/* Solstone — sign-in page: pixel fireworks over the hill, and the announcements. The sky itself lives in sky.js. */
"use strict";

const loginScene = { stop: null };

function startLoginScene() {
  stopLoginScene();
  const cv = document.getElementById("login-sky");
  const card = document.querySelector(".login-card");
  if (!cv || !card) return;
  const scene = startSkyScene(cv, { avoid: card, dim: () => 0.25 });
  // No controls here, but holidays, scheduled shows and game events still play.
  const bar = startShowBar(scene, { controls: false });
  const board = startBoard(document.getElementById("login-board"), { where: "login", scene: () => scene, max: 2 });
  loginScene.stop = () => { scene.stop(); bar.remove(); board?.remove(); };
}

function stopLoginScene() { if (loginScene.stop) { loginScene.stop(); loginScene.stop = null; } }
