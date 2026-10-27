# Solstone 1.7.1

## Bedrock players
- Names with Floodgate's dot in front (like **.Steve**) work everywhere a name is typed or checked: giving items, healing, teleporting, kicking, game mode, birthdays, bedtime exemptions, join fireworks and the level check.
- **The log reader now counts Bedrock players too.** Before, their joins, leaves, deaths, advancements and chat were skipped. Now they show in recent activity, the recap, Adventures and notifications like everyone else's.
- **Whitelist:** adding a name that starts with a dot uses Floodgate's own whitelist (`fwhitelist add Steve`), which is how Bedrock players are let in.

## The map is for people signed in
- Where everyone is (coordinates, the position map and the web map) is no longer sent to visitors who aren't signed in, even with *Show coordinates and the position map* on. Signed in, Trusted and Admins see it, and Players do when *Players can see the map* is on.
- The map pictures can't be fetched without signing in either, so strangers can't make Solstone draw the world over and over.
- Everything else on the home page's live section (who's playing, the world, leaderboards, recap, activity) stays public.

## Busy times
- One address can make at most 240 public requests a minute (an open home page makes about 35). Above that it gets *Too many requests* for a little while. Change it with `PUBLIC_REQUESTS_PER_MINUTE` (0 turns it off).
- Who's online is asked of the game at most once every two seconds, however many pages are open.

# Solstone 1.7.0

## Fireworks in one place
- The **Firework show** tab has left Manage. Admins now find it on the Fireworks page (in the menu under your name), next to the **Editor**: Fireworks → 🎨 Editor · 🎆 Firework show. Old links still work.

## The map
- **Move around the live map**: on the home page's *Where everyone is*, drag to move, scroll or pinch to zoom, or use **+** and **−**. **Reset view** goes back to following everyone.
- **Players can see the map** (new switch in Manage → Users, off to start): Players get the World tab, with the map of the world, where everyone is, and the web map (BlueMap or squaremap) if the server has one. The world's seed stays hidden, and other players' own pages stay private.

## Live on the home page
- The screens' names sit in one row across the whole width, so *Recent activity* stays on the same line as *World map*.
- *Lately* lines up with the panel beside it on every screen.
- *Live · updated* sits next to the heading.

## Events
- Opens straight away, without waiting for every server's details first.
- With nothing planned, it says so: **No events scheduled**, and (for admins) where to add some.

## Player accounts
- The *You* card says "your inventory and stats", and only mentions fishing on servers with the fishing mod.

# Solstone 1.6.0

## One bar on every page
- The top bar is now the same everywhere: **Home, News, Help, Events, Servers**, and **⚙ Manage** for admins.
  - **Events** is the new name for *Coming up*. Old links still work.
  - **Servers** opens a list of your servers straight away. With only one server, it goes right to it.
  - **⚙ Manage** shows on every page for admins, the home page included.
  - **Fireworks** moved into the menu under your name, on the home page too. That menu also has *Sign out* on the home page.

## Live status is on the home page
- The live status page is gone. What it showed is now on the home page, under Help: who's playing, the world, the map, leaderboards, the recap and recent activity. Pick a server with its tab, or click its card under *Servers*.
- Old `/status` links (and wall screens) open the home page at the live section.
- **TV mode is gone** with the status page, and so is its tab in Announcements. *Read old logs again* moved to Manage → Servers & live info.
- The setting is now **Show the servers live on the home page** (Manage → Servers & live info), with the same choices as before: coordinates and map, items, activity, the web map.
- Banners set for the status page show on the home page, and the bedtime countdown now shows there too.

## Fixes
- **Manage:** *Notifications* no longer sits far off on its own at the end of the tabs.
- **Tabs** no longer show a small scrollbar beside them.
- **Firework editor:** clearing or starting a new firework can't trip over a missing button any more ("Cannot read properties of null").

## Who played, not how long
- **No more "Time played" leaderboard.** Nobody should be racing to play the longest. Get outside!
- **Only admins see how long anyone played.** You keep it for screen-time limits and the weekly digest. Everyone else, and the public pages, see *who* played and *which days*, never for how long:
  - The recap lists who played, in the order they joined, without hours. "Played the longest" is gone.
  - *Time played* becomes **Who played**: a square for each day each person played.
  - Players' pages show **Days played** ("12 of the last 30 days"). The "Time played" stat is gone from the stats strip and the statistics.
  - The activity timeline shows when a session started, not how long it lasted.
  - The live section says *Playing now*, never "playing for 2 h" or "3 h today".
  - The server leaves the numbers out of what it sends, so they can't be dug out of the page either.
- *Last seen* still sorts the players list.

## A fuller overview for Player accounts
- **At a glance**, above the recap:
  - **Server**: how many are playing, the version, and whether it's running smoothly.
  - **In the world**: the in-game day, time and weather.
  - **You**: your level and last seen, linking to your inventory, stats and fishing.
  - **Events**: the next three coming up.
- **Who played** over the last two weeks.
