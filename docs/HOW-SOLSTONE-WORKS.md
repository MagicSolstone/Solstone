# How Solstone works

A guide for whoever looks after Solstone next (probably you, months from now). It explains how the pieces fit,
where things live, and which files to touch for common changes. The README covers installing it; this covers
changing it.

---

## The big picture

```
 Browser ──► FastAPI (app/main.py) ──┬──► Crafty API      (server list, start/stop, CPU/RAM)       app/crafty.py
   │                                 ├──► RCON            (live data, commands in the game)         app/rcon.py
   │                                 ├──► server files    (world, playerdata, stats, logs, mods)    app/servers.py, nbtutil.py
   │                                 ├──► /data/solstone.db  (history: sessions, events, posts...)   app/db.py, auth.py
   │                                 └──► /data/settings.json (every setting you change in the UI)  app/settings_store.py
   │
   └── static pages: home.html (public site at /) and index.html (the app at /app), plain JavaScript, no build step

 Background (app/recorder.py, started with the app): every few seconds/minutes it polls who's online, reads new log
 lines, records metrics, runs games/contests/races, enforces bedtime, makes recaps, backs Solstone up.
```

- **One Python process** (FastAPI + uvicorn) does everything: the web pages, the API and the background jobs.
- **Read-only to the game:** Solstone reads the server folder (mounted `:ro`) and talks to the game through RCON
  commands and Crafty's API. It never edits world files directly.
- **No database server:** SQLite in `/data/solstone.db`, plus one JSON file for settings.
- **No frontend build:** the JavaScript files in `app/static/` are served as they are. Edit, reload, done.

---

## Where things live

### Backend (`app/`)

Every file starts with a docstring saying what it's for. The main ones:

| Area | Files |
|---|---|
| **The web app and all API routes** | `main.py` (big: grouped by section headers like `# ---- races`) |
| Settings from environment variables | `config.py` |
| Settings changed in the UI | `settings_store.py` (`/data/settings.json`, one section per feature) |
| History database | `db.py` (tables at the top in `SCHEMA`) |
| Accounts, roles, sign-in, audit log | `auth.py` |
| Players making their own account / linking another player | `signup.py` |
| Finding servers, reading worlds, players, stats, mods | `servers.py`, `nbtutil.py`, `mcname.py` (Java/Bedrock names) |
| Talking to the game | `rcon.py` (the protocol), `control.py` (console, player actions, whitelist) |
| Crafty | `crafty.py` |
| The background loop | `recorder.py` |
| Reading the server log (joins, chat, deaths...) | `logparse.py` |
| Notifications (ntfy, Discord) | `notify.py` |
| Public website: site details, posts, guides, ask to join | `site.py` |
| The "website is down" page on Cloudflare (a Worker, downloaded from Site details) | `offline_worker.js` (filled in by `offline_worker` in `main.py`) |
| Welcome message in the game | `welcome.py` |
| Bedtime and screen time | `guard.py` |
| Announcements and birthdays | `board.py` |
| Daily recaps, "on this day" | `recap.py` |
| Top-down map pictures | `worldmap.py`; item icons and names: `assets.py` |
| Adventures (trails, "what happened", "lately") | `adventures.py` |
| Contests, races, games | `challenges.py`, `races.py`, `games.py`, `spleef.py`, `gather.py`, `hotzone.py`; on-screen bits: `hud.py`, `bossbar.py` |
| Fishing | `tide.py` (the Tide+ mod), `fishing.py` + `fishpack.py` (the data pack) |
| Fireworks, holidays | `fireworks.py` (designs), `fwshow.py` (the show, events, the holiday calendar edited in Manage → Holidays) |
| Modpack (packwiz and .mrpack) | `modpack.py` |
| Skins | `skins.py` |
| Backups: Crafty's status / Solstone's own | `backups.py` / `selfbackup.py` |
| Compatibility check (the Check tab) | `selfcheck.py` |
| Events page | `upcoming.py` |

### Frontend (`app/static/`)

Two HTML pages load a list of scripts (in order, see the bottom of each HTML file):

| Page | Scripts |
|---|---|
| **`home.html`**: the public site at `/` (home, news, help, guides, live) | `home.js` (pages, posts, ask to join), `live.js` (the live section), `guides.js` (built-in guides), shared ones below |
| **`index.html`**: the app at `/app` (signed in) | `app.js` (router, server pages, players, world, leaderboards, mods), `control.js` (Control tab, Manage → Users / Servers / Whitelist), `history.js` (performance, activity, Manage → Notifications), `play.js` (chat, contests, races, games, fishing), `adventures.js`, `editor.js` + `fwsettings.js` (fireworks, Manage → Holidays), `announce.js` (announcements), `website.js` (Manage → Website), `login.js` (sign-in) |
| Shared by both | `hud.js` (top bar, menus, escaping), `sky.js` (the animated sky and fireworks), `showbar.js` (the Launch/Show control), `board.js` (banners), `recap.js` |

- **Routing in the app** is the `#/...` part of the address. `route()` near the bottom of `app.js` maps it to a
  `view…()` function: `#/s/<server>/leaderboards` → `viewLeaderboards()`, `#/manage/whitelist` → `viewWhitelist()`.
- **All styling** is in `app.css` (one file, sections with comments).
- **Cache busting** is automatic: `main.py` adds `?v=<stamp>` to every file in `ASSET_NAMES`.

---

## Rules the code keeps (don't break these)

1. **Privacy for kids**
   - Positions, maps, chat, inventories: never for visitors who aren't signed in.
   - Player accounts see their own page, not anyone else's.
   - How long anyone played: admins only (`_shows_play_time`, `_no_durations` in `main.py`).
2. **Player accounts are default-deny.** A player login can only call API routes listed in `PLAYER_ROUTES` (top of
   `main.py`). **A new route you add is blocked for players until you list it there.** Routes under
   `/api/public/` and `/api/auth/` are open to them.
3. **Private servers** never appear on the public site or to non-admins (`_private`, `_visible`, `_allowed`).
4. **No inline scripts.** The Content-Security-Policy (`CSP` in `main.py`) forbids `onclick=` and `<script>` in
   HTML strings. Wire events with `addEventListener`. The browser test fails on any CSP violation.
5. **Escape everything** put into HTML: `esc()` in JS. Post text is Markdown escaped first, never stored as HTML.
6. **Bedrock names start with a dot** (`.Steve`). Use `mcname.py` checks, not your own regex.
7. **Commands in the game must work before and after Minecraft 1.21.5** (text components changed). Use
   `control.component()` for chat text; it writes JSON, which both read.

---

## How to make common changes

| I want to… | Change |
|---|---|
| Change wording on a page | Search the text in `app/static/*.js` (`grep -rn "the words" app/static`) |
| Change colours, spacing, sizes | `app/static/app.css` |
| Add a setting to a server's ⚙ settings | Add the key to `ALLOWED` in `settings_store.py`, check it in `put_settings` in `main.py`, add the field in `openSettings()` in `app.js` |
| Add a site-wide setting (Website → Site details) | `DEFAULTS` + `clean_config` in `site.py`, the form in `wsSite()` in `website.js` |
| Add a page to the app | A `viewSomething()` function, a line in `route()` in `app.js`, a link in the nav (`index.html` for Manage, the tab list in `serverHeader()` for server tabs) |
| Add an API route | A function in `main.py` with `@app.get/post(...)`. Add `auth.require_admin(request)` (or `require_user`) at the top. For players: add it to `PLAYER_ROUTES` |
| Add a new JS file | Put it in `app/static/`, add a `<script>` to the HTML page, and add its name to `ASSET_NAMES` in `main.py` |
| Add a leaderboard | `LEADERBOARDS` and `LEADERBOARD_GROUPS` in `servers.py` (and where the number comes from in `leaderboard_stats`) |
| Add a "what happened" line to Adventures | `progress_line()` in `adventures.py`; "lately" labels: `doing()` |
| Add a notification event | `EVENT_TYPES` in `notify.py`, then `maybe_notify("type", ...)` where it happens |
| Change the built-in guides or rules | In the app: Website → Posts → a new post started from a template, with *Use as* set. Solstone's own wording (the templates, and what shows when no post stands in): `guides.js` |
| Add a fill-in like `{java_address}` | `fillPostVars()` and `GUIDE_PLACEHOLDERS` in `guides.js`; the value comes from `/api/public/site` (`public_site` in `main.py`) |
| Change the welcome message colours/codes | `welcome.py` |
| Add a game | Look at `spleef.py` (the newest, self-contained one) and how `games.py` calls it |
| Keep something for longer / shorter | Environment variables in `config.py` and the README table |

---

## Testing a change

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check .                 # style and common mistakes
pytest -q                    # ~260 tests, about 15 seconds, on a fake server in tests/helpers.py
python tests/e2e/smoke.py    # opens every page in Chromium; fails on JS errors and CSP violations
```

- Tests use a fake world (`tests/helpers.py` builds it) and fake RCON. Nothing touches a real server.
- The smoke test saves screenshots of every page (`SMOKE_SHOTS=folder` to choose where). Look at them.
- `node --check app/static/file.js` catches JavaScript syntax errors in a second.

---

## Releasing

- Work on a branch. Run its checks on GitHub: Actions → *Build and publish Docker image* → *Run workflow* on the
  branch. That runs the lint, the tests and the browser test.
- **A release** = a new `VERSION` in `app/main.py` plus a new section at the top of `RELEASE_NOTES.md`, merged
  into `main`. The workflow builds the image (`ghcr.io/magicsolstone/solstone:<version>`, `:latest`, `:stable`)
  and makes the GitHub release from the notes.
- A push to `main` without a new `VERSION` only runs the checks.
- Updating your server: Unraid → Docker → Solstone → *Force update*.

---

## Where the data is (inside `/data`)

| File | What |
|---|---|
| `solstone.db` | Accounts, sign-in sessions, audit log, play sessions, metrics, activity events, recaps, fishing catches, positions (adventure trails), posts |
| `settings.json` | Every setting changed in the UI, one section per feature (`site`, `notify`, `servers`, `board`, `modpacks`, `join_requests`, `welcomed`, firework sections...) |
| `site/` | The logo and pictures in posts |
| `backups/` | Solstone's own daily backups |
| `assets/`, `maptiles/`, `skins/`, `mrpack/` | Downloaded or drawn again by themselves; safe to delete |

---

## Honest notes on the code's shape

- **It's been checked on every release:** lint clean, ~260 tests, a browser test of every page. It hasn't had a
  separate "tidy everything" pass, and doesn't urgently need one.
- **`main.py` is the big one** (~2,800 lines). It's grouped by section headers, so search for `# ---- ` to jump
  around. Splitting it into one file per area (FastAPI "routers") would be the most useful tidy-up, but it touches
  every route. Do it only with the tests passing before and after, and on its own release.
- **`app.js` is the other big file.** The same idea applies: it could be split by page, as `control.js`,
  `website.js` and others already are.
- Some older names and comments still say "family" (the fishing journal's "Family record", some docstrings). They're
  harmless.
- If something breaks after a Minecraft update, run the **Check** tab on a server first: it tries every kind of
  command and file Solstone relies on, and says which fail.
