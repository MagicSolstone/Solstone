# Solstone

A family-friendly web dashboard for Minecraft Java servers run by **Crafty Controller 4**.

- **Website** at `/`, no sign-in needed: how to join (Java and Bedrock addresses, with copy buttons), the public servers' live status, announcements, and posts in three kinds (**News**, **Guides** and **FAQ**). Admins write the posts and set the site's details in the app (🌐 Website). The signed-in app lives at `/app`; old `/#/...` links forward there.
- **Private servers:** mark a server private (Server settings) and only admins see it. It never appears on the website or the status page, and signed-in players don't see it. Admins keep managing it from the same sign-in, so a home server and a public one can share one Solstone.
- **Bedrock players** joining through Geyser and Floodgate get their real skins (heads, bodies, the firework face stamp), from GeyserMC's skin service by Xbox ID.
- **Servers:** every Crafty server with running state, players online, version, loader, CPU, RAM and world size.
- **Players:** everyone who has ever joined, with online status, level, health and time played.
- **Player pages:**
  - Inventory, armour, offhand and ender chest in a Minecraft-style grid.
  - Enchantments, durability and custom names, plus shulker box and bundle contents.
  - Health, hunger, XP, position, bed, last death and status effects.
  - Every tracked statistic (general, items, mobs) and advancement progress.
- **Live data:** for online players this comes from RCON (refreshes every few seconds). Offline players are read from their last save.
- **World:** day and time, weather, seed, spawn, where everyone is, chunks explored per dimension, game rules, data packs, plus an embedded BlueMap or squaremap.
- **Activity:** time played per player per day, and a timeline of play sessions. Players who were on at the same time share one block, so their chat reads as a conversation, along with deaths and advancements.
- **Performance:** TPS, tick time, CPU, memory, players online and uptime, graphed over 6 hours to 30 days.
- **Notifications** to ntfy or Discord when someone joins, leaves, dies or earns an advancement, a server stops, or backups are overdue. Also included: daily screen-time limits per player, a weekly digest, and quiet hours.
- **Backup status:** when the last Crafty backup ran, with a warning when it's overdue.
- **Leaderboards** across the family.
- **Firework editor:** anyone signed in can design fireworks: sky rockets (volleys, fans, mirror pairs, rocket styles, hang time, lean), ground fountains and spinning wheels, nine patterns, colour styles (mixed, taking turns, changing, rainbow), "then…" stages (burst again, every piece bursts, shatter, implode), effects (flash, crackle, trails, falling glitter, wobble, grow, blink, strobe, breathe, fizzle) and a two-frame pixel painter for picture fireworks that can fly and spin, with a stamp that paints any player's Minecraft face from their skin. Saved designs can join the show on every page. People can change their own; admins can change anyone's. Admins also choose which built-in kinds, colours and pace the show uses.
- **Firework show settings** (admins, Fireworks → Firework show): which kinds, colours and pace the show uses; fireworks for game events (joins, advancements, challenges, goals, deaths, level milestones, nightfall, server start); a join firework for each player. **Holidays** (Manage → Holidays): New Year with a countdown, Valentine's, St. Patrick's, Easter, 4th of July, Halloween, Thanksgiving, Christmas and your own dates, each switched on or off, with colours, favourite kinds, a message and an optional scheduled show. Only the ones switched on show on the Events page. A **show builder** makes timed shows; pick a base show for daytime and night, and use shows for holidays and game events. Admins can also set how often each kind, each person's designs and each single design turns up.
- **Game sky:** the sky behind every page follows the game: sun, moon phases, sunset glow, clouds, rain and thunder. During the day fireworks leave coloured smoke and go up less often (or wait for night, or behave as at night).
- **Announcements** (admins, Manage → Announcements): banners across the home page, the signed-in pages and the sign-in page, each with a look (info, celebration, heads-up), start and end times, and an optional live countdown that fills the screen for the last ten seconds, then plays a show and posts in the game chat. Birthdays get a banner and their show on the day (and a happy-birthday in the game when they join), with a "birthday in 3 days" banner before. The bedtime countdown and the holiday of the day show up automatically.
- **Daily recap and "on this day":** each server's day is summarised (who played and for how long, challenges, first visits, advancements, deaths) and kept for good, so the Overview tab and the home page can show today, yesterday, any earlier day, and the same date in past years. On first start Solstone also reads the server's old `logs/*.log.gz` files to fill in the days before it was installed.
- **Sounds:** firework sounds made in the browser (whoosh, whistle, boom, pop, crackle, fizzle, fountain hiss), off until someone turns them on. In the editor you can also **make your own** launch and burst sounds, bfxr style: wave (square with adjustable width, saw, triangle, sine, noise), attack, sustain, punch and decay, pitch, slide, vibrato and pitch jumps, low-pass (with sweep and resonance) and high-pass, crunch, drive, repeats and echo, with a live waveform and starting points (boom, pop, crackle, whistle, zap, chiptune, random, mutate…). Sounds can be saved by name and reused in any firework, and fountains and wheels can hiss, crackle, play your own sound on repeat, or be silent. While you're in the editor only its preview makes sound. A small control in the corner of every page holds **Launch** (a list of every kind of firework and the ones made for the show, with Surprise me at the top), the **Show** switch (fireworks by themselves), sound on and off, and 👁 to hide the page so only the sky is left. The show is on to start (sound off); a visitor who switches it off is remembered, and browsers set to reduce motion start with it off.
- **Mods:** the Fabric or Quilt mods installed, with modded item icons and names read from the mod jars.
- **Live on the home page** (under Help, off until an admin turns it on in Manage → Servers & live info): a live, read-only view with no sign-in. Server state, in-game day and weather, TPS, and a card per online player with health, hunger, level, dimension, coordinates, held item and armour, plus a map of where everyone is, drawn from the world's own region files (terrain from the game's block textures, shaded by height, water by depth, the Nether's cave floor), and recent joins, deaths and advancements. Fireworks go off when someone joins. Chat is never shown, and admins can hide coordinates, items or activity.
- **Mods:** item icons, names and advancements come from the jars in each server's `mods` folder. RPG gear shows its attribute bonuses, and items mods keep in extra slots (Trinkets, Accessories, backpacks) appear under the inventory.
- **Accounts:** everyone signs in to the app (the website, with its live section, is public). Three levels: **Players** see the servers, who's on, CPU/RAM/TPS, leaderboards, fishing and their own page (never anyone else's position, inventory or chat); **Trusted** see everything read-only and can chat; **Admins** also get the Control tab, settings and user management. Every admin action is logged. With sign-up on (Users & activity), players make their own account: they type their Minecraft name on the sign-in page while playing, get a six-digit code in the game chat, and pick a login. The whitelist decides who can.
- **Control (admins):** a live console with command history, one-click time, weather and difficulty, game-rule switches, and a message to everyone (optionally shown big on screen). Player actions: heal, send to spawn or bed, teleport, game mode, give items, private message and kick. Also whitelist and operator management, and start, stop, restart and back up through Crafty.
- **Letting people in:** whoever the whitelist turns away shows in Control → Whitelist with their exact name, **Copy** and **Let them in** (Bedrock names go to Floodgate's whitelist), with an optional notification. An optional **Ask to join** form on the join guide sends you their name, first name and a note.
- **Guides in your own words:** in Website → Posts, start a post from a template (How to join the server, Making an account, Server rules) and make it your own. *Use as* makes it the page the site links to (the join guide gets the Ask to join form under it). `{java_address}`, `{bedrock_port}`, `{java_version}` and the other fill-ins work in every post, filled in from the main server's details.
- **Bedtime mode:** in-game warnings, then save and disconnect at a set time, with joins blocked until wake-up. Daily screen-time limits can also warn then disconnect a player.

It's read-only. Solstone never writes to your servers, and the servers folder can be mounted `:ro`.

## How it gets the data

| Data | Source |
|---|---|
| Server list, running state, CPU/RAM, MOTD | Crafty API v2 (`/api/v2/servers`, `/servers/{id}/stats`) |
| Stats, advancements | `world/stats/<uuid>.json`, `world/advancements/<uuid>.json` |
| Inventory, XP, health, position (offline) | `world/playerdata/<uuid>.dat` (NBT) |
| Inventory, XP, health, position (online) | RCON `data get entity <name>` |
| Who's online | RCON `list`, falling back to Crafty |
| Names | `usercache.json` |
| Sessions, metrics, TPS | Recorded by Solstone every 30 s (who's online, Crafty stats, RCON `tick query`) into `/data/solstone.db` |
| Activity feed | New lines in each server's `logs/latest.log` |
| Item icons, item/stat/mob names, advancements | Minecraft client jar for the server's version, downloaded once from Mojang (~30 MB, ~10 MB kept) |

Minecraft only writes `playerdata` on autosave (every 5 minutes) or logout. That's why RCON matters for live inventories.

## Setup

### 1. Crafty API token
In Crafty, open **Settings → Users → your user → API Keys** and create a key. Read access to the servers is enough.

### 2. Enable RCON on each server (for live data)
In Crafty's file manager, edit `server.properties`:

```properties
enable-rcon=true
rcon.port=25575
rcon.password=pick-a-long-random-password
```

Restart the server. Solstone reads the port and password from `server.properties` automatically. Make sure the RCON port is published from the Crafty container. The official Crafty compose file publishes `25500-25600`, which covers the default. Don't forward RCON through your router.

### 3. Run it

```yaml
services:
  solstone:
    image: ghcr.io/magicsolstone/solstone:latest   # or a pinned version like :1.2.0, or build: .
    restart: unless-stopped
    ports: ["8085:8080"]
    environment:
      CRAFTY_URL: https://192.168.150.10:8443
      CRAFTY_TOKEN: your-api-token
      CRAFTY_VERIFY_SSL: "false"
      PUID: "99"
      PGID: "100"
    volumes:
      - /mnt/user/appdata/crafty-4/servers:/servers:ro
      - /mnt/user/appdata/solstone:/data
```

Open `http://<host>:8085`. If you only have one server, Solstone opens straight to it.

**Unraid:** add a container from `ghcr.io/magicsolstone/solstone:latest` with those two paths and env vars. `PUID`/`PGID` decide who owns `/data`; `99`/`100` is nobody:users.

### 4. Sign in

On first start Solstone creates an admin account. If you didn't set `ADMIN_PASSWORD`, the password is in the container log (Unraid: the Solstone icon → Logs) and in `/data/admin_credentials.txt`. Sign in, change it from the account menu, and delete that file. Add family and friends under **Users & activity**.

For start, stop, restart and backup buttons, the Crafty API key needs command permission on the servers. A full-access key already has it.

### 5. Optional: a live map
Install **BlueMap** (or squaremap) on the Fabric server. BlueMap serves a web map on port 8100. Then in Solstone open **⚙ Server settings** and paste the map address (e.g. `http://192.168.150.10:8100`). It appears on the World tab.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CRAFTY_URL` | – | Crafty base URL, e.g. `https://host:8443` |
| `CRAFTY_TOKEN` | – | Crafty API token (or use `CRAFTY_USERNAME` + `CRAFTY_PASSWORD`) |
| `CRAFTY_VERIFY_SSL` | `false` | Verify Crafty's TLS certificate |
| `SERVERS_DIR` | `/servers` | Where Crafty's `servers` folder is mounted |
| `RCON_HOST` | Crafty host | Host the RCON ports are reachable on |
| `RCON_TIMEOUT` | `4` | Seconds |
| `LIVE_TTL` | `3` | Seconds to cache live RCON data |
| `DOWNLOAD_ASSETS` | `true` | Download the Minecraft client jar for icons and names. If `false`, you can drop a `client.jar` into `/data/assets/<version>/` yourself |
| `ADMIN_USERNAME` | `admin` | Username of the first admin, created on first start |
| `ADMIN_PASSWORD` | generated | Password for that first admin. If unset, one is generated, printed in the container log and saved to `/data/admin_credentials.txt`. Only used while there are no users |
| `TRUST_PROXY_HEADERS` | `false` | Set `true` behind Cloudflare Tunnel or a reverse proxy you control |
| `PUBLIC_REQUESTS_PER_MINUTE` | `240` | Most public (not signed in) requests one address can make a minute; `0` turns the limit off. Behind a proxy it only works with `TRUST_PROXY_HEADERS=true` |
| `SESSION_DAYS` | `30` | How long a sign-in lasts |
| `LOGIN_MAX_ATTEMPTS` | `8` | Failed sign-ins per IP or username before a 15-minute lockout |
| `TZ` | `UTC` | Your time zone (e.g. `America/Chicago`). Decides where "today" starts in play time |
| `POLL_INTERVAL` | `30` | Seconds between recordings of who's online and performance |
| `METRICS_RETENTION_DAYS` | `30` | How long performance history is kept |
| `EVENTS_RETENTION_DAYS` | `180` | How long the activity feed is kept. Sessions are kept forever |
| `NTFY_URL` / `NTFY_TOKEN` | – | Default ntfy topic and token (can also be set in the UI) |
| `DISCORD_WEBHOOK_URL` | – | Default Discord webhook (can also be set in the UI) |
| `DATA_DIR` | `/data` | Settings, history database and cached assets |
| `BACKUPS_DIR` | `/backups` | Where Crafty's backups folder is mounted (optional, read-only) |
| `BACKUP_STALE_HOURS` | `48` | A backup older than this shows a warning and can send a notification |
| `SOLSTONE_BACKUP_DIR` | `/data/backups` | Where Solstone's own daily backups go (its database, settings and the website's pictures). Point an off-site backup tool at it, or mount a share here |
| `SOLSTONE_BACKUP_KEEP` | `14` | How many of Solstone's own backups to keep |
| `SOLSTONE_BACKUP_HOURS` | `24` | How often Solstone backs itself up |
| `PUID` / `PGID` | `1000` | Host user/group that owns `/data` |
| `ONLY_SERVERS` | – | Only these servers (Crafty names, Crafty ids or folder names, comma-separated). For running two Solstones against one Crafty, see below |

Without Crafty configured, Solstone still works by scanning `SERVERS_DIR` for folders containing `server.properties`.

### Two communities, two websites
To give two Minecraft servers their own website, accounts and settings, run two Solstone containers against the same Crafty. Give each its own `/data` folder, its own port (each domain or tunnel points at one), and `ONLY_SERVERS` naming its server:

```yaml
  solstone-family:
    image: ghcr.io/magicsolstone/solstone:latest
    ports: ["8080:8080"]
    volumes: ["/mnt/user/appdata/solstone-family:/data", "/mnt/user/appdata/crafty/servers:/servers:ro"]
    environment: { ONLY_SERVERS: "Family Realm", CRAFTY_URL: "...", CRAFTY_TOKEN: "..." }
  solstone-friends:
    image: ghcr.io/magicsolstone/solstone:latest
    ports: ["8081:8080"]
    volumes: ["/mnt/user/appdata/solstone-friends:/data", "/mnt/user/appdata/crafty/servers:/servers:ro"]
    environment: { ONLY_SERVERS: "Friends SMP", CRAFTY_URL: "...", CRAFTY_TOKEN: "..." }
```

Each Solstone only records, greets, announces and runs events on its own server, so nothing happens twice in the game.

## Notes and limits

- **Unraid storage:** the history database works on `/mnt/user/appdata`. Solstone switches SQLite out of WAL mode when the filesystem can't support it. Pointing `/data` at a pool path (e.g. `/mnt/safestorage/appdata/solstone`) is a little faster.
- **History starts when Solstone does.** Play time per day, sessions and performance graphs build up from the moment it first runs. Minecraft's own statistics only keep lifetime totals.
- **TPS and tick time** need RCON and Minecraft 1.20.3 or newer, which added `/tick query`.
- **Chat** is stored in Solstone's database and shown on the Activity tab. It's never sent in notifications.

- **Player skins** come from mc-heads.net in the visitor's browser. Offline-mode servers fall back to initials.
- **Block-entity items** (chests, beds, heads, banners) are drawn as a cube of their particle texture. Everything else renders like the game's own icons.
- **Exposing it outside your LAN:** everything needs a sign-in, so a Cloudflare Tunnel or reverse proxy is reasonable. Set `TRUST_PROXY_HEADERS=true` behind one so sign-in rate limits see real visitor IPs and cookies are marked secure. Give friends Player accounts (or let them sign up); keep Trusted for family. Only admins can send commands.
- **Bedrock servers** aren't supported. They store player data in LevelDB and have no statistics files.

## Choosing a release channel

Releases work the same way as Tide+: changes are made and tested on a branch, then merged to `main`.

| Tag | Updates when | For |
|---|---|---|
| `latest` / `stable` | `main` gets a new `VERSION` (in `app/main.py`) | Everyday use |
| `1.2.0` | Never, it's pinned | Rolling back |

Every build runs lint, the tests and a browser check of every page first; a failing build is never published. A branch build stops after the checks. A new version also makes a GitHub release from `RELEASE_NOTES.md`. Images are multi-arch (amd64 and arm64).

To release: raise `VERSION` in `app/main.py`, write `RELEASE_NOTES.md`, and merge to `main`.

The first time the workflow publishes, set the package to **Public** under your GitHub profile → Packages → solstone → Package settings. Otherwise pulls get a 401.

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check . && pytest -q        # tests build a synthetic world, no game needed
SERVERS_DIR=/path/to/crafty/servers DATA_DIR=./data CRAFTY_URL=... CRAFTY_TOKEN=... \
  uvicorn app.main:app --reload --port 8080
```

Backend: FastAPI (`app/`). Frontend: vanilla JS in `app/static/`, with no build step. **How it all fits together, and which files to change for what: [docs/HOW-SOLSTONE-WORKS.md](docs/HOW-SOLSTONE-WORKS.md).** Fonts are bundled (Pixelify Sans and Atkinson Hyperlegible, SIL OFL).
