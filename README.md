# Lodestone

A family-friendly web dashboard for Minecraft Java servers run by **Crafty Controller 4**.

- **Servers:** every Crafty server with running state, players online, version, loader, CPU, RAM and world size.
- **Players:** everyone who has ever joined, with online status, level, health and time played.
- **Player pages:**
  - Inventory, armour, offhand and ender chest in a Minecraft-style grid.
  - Enchantments, durability and custom names, plus shulker box and bundle contents.
  - Health, hunger, XP, position, bed, last death and status effects.
  - Every tracked statistic (general, items, mobs) and advancement progress.
- **Live data:** for online players this comes from RCON (refreshes every few seconds). Offline players are read from their last save.
- **World:** day and time, weather, seed, spawn, where everyone is, chunks explored per dimension, game rules, data packs, plus an embedded BlueMap or squaremap.
- **Activity:** time played per player per day, recent sessions, and a feed of joins, chat, deaths and advancements read from the server log.
- **Performance:** TPS, tick time, CPU, memory, players online and uptime, graphed over 6 hours to 30 days.
- **Notifications** to ntfy or Discord when someone joins, leaves, dies or earns an advancement, or a server stops. Quiet hours are supported.
- **Leaderboards** across the family.
- **Mods:** the Fabric or Quilt mods installed, with modded item icons and names read from the mod jars.

It's read-only. Lodestone never writes to your servers, and the servers folder can be mounted `:ro`.

## How it gets the data

| Data | Source |
|---|---|
| Server list, running state, CPU/RAM, MOTD | Crafty API v2 (`/api/v2/servers`, `/servers/{id}/stats`) |
| Stats, advancements | `world/stats/<uuid>.json`, `world/advancements/<uuid>.json` |
| Inventory, XP, health, position (offline) | `world/playerdata/<uuid>.dat` (NBT) |
| Inventory, XP, health, position (online) | RCON `data get entity <name>` |
| Who's online | RCON `list`, falling back to Crafty |
| Names | `usercache.json` |
| Sessions, metrics, TPS | Recorded by Lodestone every 30 s (who's online, Crafty stats, RCON `tick query`) into `/data/lodestone.db` |
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

Restart the server. Lodestone reads the port and password from `server.properties` automatically. Make sure the RCON port is published from the Crafty container. The official Crafty compose file publishes `25500-25600`, which covers the default. Don't forward RCON through your router.

### 3. Run it

```yaml
services:
  lodestone:
    image: ghcr.io/tjusczak/lodestone:latest   # or :beta, or build: .
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
      - /mnt/user/appdata/lodestone:/data
```

Open `http://<host>:8085`. If you only have one server, Lodestone opens straight to it.

**Unraid:** add a container from `ghcr.io/tjusczak/lodestone:latest` with those two paths and env vars. `PUID`/`PGID` decide who owns `/data`; `99`/`100` is nobody:users.

### 4. Optional: a live map
Install **BlueMap** (or squaremap) on the Fabric server. BlueMap serves a web map on port 8100. Then in Lodestone open **⚙ Server settings** and paste the map address (e.g. `http://192.168.150.10:8100`). It appears on the World tab.

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
| `ADMIN_TOKEN` | – | If set, changing settings in the UI requires this token |
| `TZ` | `UTC` | Your time zone (e.g. `America/Chicago`). Decides where "today" starts in play time |
| `POLL_INTERVAL` | `30` | Seconds between recordings of who's online and performance |
| `METRICS_RETENTION_DAYS` | `30` | How long performance history is kept |
| `EVENTS_RETENTION_DAYS` | `180` | How long the activity feed is kept. Sessions are kept forever |
| `NTFY_URL` / `NTFY_TOKEN` | – | Default ntfy topic and token (can also be set in the UI) |
| `DISCORD_WEBHOOK_URL` | – | Default Discord webhook (can also be set in the UI) |
| `DATA_DIR` | `/data` | Settings and cached assets |
| `PUID` / `PGID` | `1000` | Host user/group that owns `/data` |

Without Crafty configured, Lodestone still works by scanning `SERVERS_DIR` for folders containing `server.properties`.

## Notes and limits

- **History starts when Lodestone does.** Play time per day, sessions and performance graphs build up from the moment it first runs. Minecraft's own statistics only keep lifetime totals.
- **TPS and tick time** need RCON and Minecraft 1.20.3 or newer, which added `/tick query`.
- **Chat** is stored in Lodestone's database and shown on the Activity tab. It's never sent in notifications.

- **Player skins** come from mc-heads.net in the visitor's browser. Offline-mode servers fall back to initials.
- **Block-entity items** (chests, beds, heads, banners) are drawn as a cube of their particle texture. Everything else renders like the game's own icons.
- **Exposing it outside your LAN:** put it behind your reverse proxy or Tailscale. There's no login, because it's meant for the family network. `ADMIN_TOKEN` only protects the settings.
- **Bedrock servers** aren't supported. They store player data in LevelDB and have no statistics files.

## Choosing a release channel

Releases work the same way as The Coop Ledger:

| Tag | Updates when | For |
|---|---|---|
| `latest` / `stable` | A version tag like `v1.2.0` is pushed (or a GitHub release is published with one) | Everyday use |
| `1.2.0` | Never, it's pinned | Rolling back |
| `beta` | Every push to `main` | Trying new things early. Shows a "Beta build" badge in the sidebar |

Every build runs lint and tests first; a failing build is never published. Images are multi-arch (amd64 and arm64).

To release: `git tag v1.0.0 && git push origin v1.0.0`, or create a release on GitHub with a new `v1.0.0` tag.

The first time the workflow publishes, set the package to **Public** under your GitHub profile → Packages → lodestone → Package settings. Otherwise pulls get a 401.

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check . && pytest -q        # tests build a synthetic world, no game needed
SERVERS_DIR=/path/to/crafty/servers DATA_DIR=./data CRAFTY_URL=... CRAFTY_TOKEN=... \
  uvicorn app.main:app --reload --port 8080
```

Backend: FastAPI (`app/`). Frontend: vanilla JS in `app/static/`, with no build step. Fonts are bundled (Pixelify Sans and Atkinson Hyperlegible, SIL OFL).
