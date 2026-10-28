# Solstone 1.8.9

- **Enter starts a new line in posts:** one line break in the text is now a new line in the post (it used to run on into the same line), and a blank line still starts a new paragraph. The editor's live view, Preview and the published post all show it the same way.

# Solstone 1.8.8

- **Formatting toolbar and a live view in the post editor:** select some text and click **B** (bold), **I** (italic), **Heading / Subheading / Small heading**, a **Colour** (red, orange, gold, green, aqua, blue, purple, pink, grey), a **Size** (bigger, smaller), **• List**, **1. List**, **❝ Quote** or **― Line**, plus **🔗 Link** and **🖼 Picture** as before. Beside the text, **How it looks** shows it formatted as you type. The text itself stays plain, so you can still see exactly where links and pictures point: colours and sizes are written `{red}like this{/red}` and `{big}this{/big}`, and headings `## like this`.
- **👁 Preview a post before anyone sees it:** Website → Posts → the post editor has a **Preview** button. It opens the post in a tab of its own exactly as visitors will see it (the real post page, pictures and formatting included), from what's typed right now: saved or not, published or not. Only your browser has it, so nobody else can see a preview. Change something and press Preview again: the same tab updates.
- **Save draft:** with *Published* unticked, the editor's button says **Save draft** instead of *Publish*, so it's clear nothing goes out yet.

# Solstone 1.8.7

## Accounts
- **More than one Minecraft player per login:** someone with a Java name and a Bedrock name (*.Name*) can have both. Both players' pages are theirs, and every server either one is on the whitelist of shows in their account.
  - **Players link their other one themselves:** account menu → **🎮 My Minecraft players** → type the name while playing as them, and a code appears in their game chat, the same way as making an account. They can unlink one too, but a Player login always keeps at least one.
  - **Admins** (Manage → Users → the player button) see who's linked, can unlink each, and can add one by typing or by clicking a name: everyone on a whitelist or who has played, not linked to anyone yet, shows as a button.

## Leaderboards
- **🥇 Most medals** at the top: 1st, 2nd and 3rd places across every leaderboard (equal scores share a place), the top five shown and *Everyone* folded away below. Nobody gets a medal for *Most deaths*.
- **Grouped by kind:** Adventure, Fighting, Mining and making, Getting around, Fishing, Farm and village, with buttons to jump to each.
- **Every board shows**, even ones nobody has scored on yet (*Nobody yet. Be the first!*). Untick *Show boards nobody has scored on yet* to hide those; each browser remembers it.

## Adventures
- **Players can see the adventures they were in** (Play → Adventures): their own trail and lines, plus what's public anyway (joins, deaths, advancements, contests, fish). Never anyone else's chat, and others' trails only when *Players can see the map* is on. They can watch, not save, hide or delete.
- **More of what happened** in the feed: chopped logs, harvested crops, placed blocks, opened chests, traded with villagers, bred animals, enchanted items, slept, how far they travelled, and more ores (coal, copper, lapis, redstone, quartz).

## Live on the home page
- **What they've been up to:** each player's card says what they've been doing lately, from their statistics: ⛏️ Mining, 🪓 Chopping trees, 🧱 Building, 🎣 Fishing, ⚔️ Fighting mobs, 🌾 Farming, 💰 Trading or 🧭 Exploring. The game saves statistics every few minutes, so it follows a few minutes behind.

## Smaller things
- The World tab's own map is called **Top-down map** (it said *Solstone map*).

# Solstone 1.8.6

- **📊 Go to live stats:** each server's card on the home page links to its live section with *Go to live stats →* (it said *See who's on, live*).

# Solstone 1.8.5

- **💾 Solstone backs itself up:** once a day, a zip of its database (accounts, posts, history, fishing and the rest), its settings and the website's pictures, in `/data/backups` (the newest 14 kept). The database is copied with SQLite's own backup, so it's whole even when Solstone was busy. Manage → Servers & live info → **Solstone's own backups** lists them, with **Download** and **Back up now**. A failed backup sends a *Backup* notification. Point your off-site backup at the folder (or set `SOLSTONE_BACKUP_DIR` to a share). The world itself is still in Crafty's backups.
- **⬇ The modpack as one file:** a server's Mods page can now hand out its pack as a **.mrpack** file. In Prism it's **Add Instance → Import**: one file sets up the right Minecraft, Fabric and every mod (the Modrinth App and CurseForge import it too). Mods from Modrinth are downloaded by the launcher; the server's own jars (like Tide+) go inside the file, so they don't need to be on Modrinth. **Download the .mrpack** to give it to someone yourself, or tick **Offer it on the website** to put a download, with step-by-step install help, on the server's card on the home page (off to start). Packwiz is still there for Prism instances that keep themselves up to date.
- **🧹 Clear saved history** (Manage → Servers & live info): pick a server and what to clear: chat, activity, daily recaps, play history, performance graphs, the fishing journal, map pictures. **Tick what a new world needs** picks play history, activity and the map. Only what Solstone kept: the game server, its world, items, whitelist and logs aren't touched.
- **A cleaner home page:** the big site name and tagline at the top are gone (the bar already has the logo and name). Want them back? Website → Site details → *Show the name (and tagline) big at the top of the home page*.
- **No star on the main server:** it's still first everywhere, just without the ⭐ chip or a gold border. Give it a border colour in Site details to make it stand out.
- **Rules and guides:** the text boxes use the full width. The three built-in guides are in the same order everywhere: joining, making an account, the rules.

# Solstone 1.8.4

- **Deny a request:** *Asked to join* (in Manage → Whitelist and in a server's Control) has a **Deny** button. The request comes off the list, nobody is added to a whitelist, and the person who asked sees *Request not accepted* on their badge and page. They can ask again later.
- **The web map (BlueMap) is off the home page:** the live section no longer has a *World map* screen, and the setting for it is gone. The web map is on a server's World tab, for people signed in.
- **Not just for family:** the home page's mods list no longer says to ask for "the family modpack", and the Mods page's modpack box is just *Modpack*, keeping *players'* Prism instances up to date.

- **📜 Server rules:** a Rules page on the website (*Server rules*, under Help, and linked from the join guide), with family-friendly rules to start from: be kind, leave other people's builds and chests alone, no TNT or lava near anyone's builds, play fair, stay safe. Rewrite them in your own words in Website → **Rules and guides** (`{rules}` links to them from the other guides).
- **Read the rules before asking to join:** the Ask to join form has a box to tick, *I've read the rules and I'll follow them*, with a link to them. It can't be sent without it.
- **👋 A welcome message in the game:** Website → **Welcome in the game** has one message for each server, sent in chat only to the player who joined, on their first time or every time. Colour and style it with the buttons (the game's own `&` codes, like `&6` gold and `&l` bold), add `{player}`, `{server}`, `{rules}` or `{site}`, and web addresses become links Java players can click (Bedrock players see them written out). Up to 8 lines. The preview shows it as the game will, and **Send it to them now** tries it on someone who's on.

# Solstone 1.8.2

- **✅ Manage → Whitelist, all servers on one page:** everyone who asked to join, with a **Let in on …** button for each server they asked for (✅ once they're in) and **Let in on all**; everyone the whitelist turned away lately, by server; and each server's whitelist, with × to take someone off and a box to add a name to one or more servers at once.
- **Tap the notification, land on the whitelist:** the *Asking to join* and *Turned away* notifications (ntfy, and a link in Discord) open Manage → Whitelist. For the turned-away one, set the public address (`PUBLIC_URL`).

- **No more "access other devices on your local network" prompt:** a web map (BlueMap) set to a home-network address (like `http://192.168.1.10:8100`) was loaded by the home page and the World tab even when its screen wasn't open, and a public website reaching into your home network is what that prompt asks about. Now the map's frame is only made when you open it, and from outside your home a home-network map shows a note (with a link) instead of trying. To show it to everyone, give the map a public address (a Cloudflare tunnel to it, for example).
- **Where everyone is only on your own servers:** a Player who can see the map, but whose login doesn't have a server, no longer gets that server's *Where everyone is* screen (or anyone's position on it) on the home page.

- **How to join is set in one place:** Website → Site details → *How to join each server* is now just your servers, one block each (Java, Bedrock and port, a note, the mods). The separate "main address" is gone: if you had one, it moves into the first server the next time you open Site details and press Save. The fields are no longer in each server's ⚙ settings either.
- **⭐ Main server:** pick one in Site details. It's always first: its card on the home page (starred, with a gold border), its tab in the live section, and first (and ticked) in Ask to join. The join guide uses its addresses.
- **A border colour for each server's card** (or none), and **About this server**: a few lines on its card about what it is and who it's for.

# Solstone 1.8.1

- **On the whitelist means it's in their account:** a player's account now sees every server they're on the whitelist of, however they were added (Control, the game's console, Crafty), not just the one they signed up from. No need to sign up again with a code on each server. Private servers are never included.
- **Ask to join for the servers you want:** with more than one server, the form asks which (one or more). Each shows only in that server's Control, and the player's page and badge say which they're in on so far (*In on Family Realm. Waiting on Mods*).
- **"You're in" however you let them in:** adding someone from the game's console or Crafty counts too. Their page notices within a minute.
- **A card for each server** in the home page's *Join the servers*: its name and picture, Java and Bedrock (or *Java only*), how it's doing, the addresses to copy, its note and mods, and *See who's on, live*. Set them all in Website → Site details → **How to join each server** (or in each server's ⚙). The main address there is used by the join guide and by the first server left empty.
- **The join box says how each server is doing:** *Online · 3 / 10 playing · up 3 h · running smoothly (19.9 TPS)*, or *Offline right now* (with *Show the public servers' status* on in Site details).
- **The mods to install for a modded server:** tick *List the mods players need* in the server's ⚙ How to join this server, and its box shows them (folded away until opened), with the loader and Minecraft version. With the family modpack on, it's the modpack's list, links included.

- **Letting someone in that the game doesn't know:** Java names are checked with Mojang (and Bedrock gamertags with Xbox) before they're added, which can take a few seconds. Solstone now waits for that instead of giving up with a 502, and when the name doesn't exist it says so (*"Fake_Kid wasn't added. The game said: That player does not exist"*). Their request stays in *Asked to join* until they've really been added.
- **More than one server to join:** a server's ⚙ settings have **How to join this server**: its own Java address (with :port), a Bedrock address and port if Bedrock players can join it, and a note such as *Needs the modpack*. The home page's box becomes **Join the servers**, with the main one from Site details first and then each of those, marked *Java only* where it is.

- **Ask to join** is easy to find: with it turned on, a big **🙋 Ask to join** button sits in the home page's *Join the server* box, right under the addresses and port, and takes people straight to the form.

# Solstone 1.8.0

## Letting people in
- **Tried to join:** when the whitelist turns someone away, their exact name shows in the server's Control → Whitelist, with **Copy** and **Let them in**. There's a notification for it too (Notifications → *Someone the whitelist turned away*).
- **Ask to join** (Website → Join and account guides, off to start): a form at the bottom of the join guide. People pick Java or Bedrock, type their name in the game and, if they like, their first name and a note. You get a notification, and they show in Control → Whitelist under *Asked to join*, ready to let in. A few requests an hour from one address at most.

- **"Are you in yet?"** Whoever asked gets a small **Request sent** badge in the corner, with a spinner, that checks once a minute and turns into **You're in!** when you let them in. The home page and the join guide say the same. The badge can be closed, goes by itself after a week, and is never left behind for a request that's gone. Only their own browser can see it (it keeps a private ticket), so there's no public list of names.

## Pictures in posts
- Website → Posts: **🖼 Add a picture** uploads a picture (PNG, JPEG, WebP or GIF, under 4 MB) and puts it in the post where the cursor is. **🔗 Add a link** puts a link in. The first picture also shows on the post's card on the home page and News.

## The guides, in your own words
- Website → **Join and account guides**: rewrite *How to join the server* and *Making an account on this website*. **Start from Solstone's wording** puts the current text in with `{java_address}`, `{bedrock_address}`, `{bedrock_port}`, `{name}`, `{discord}` and `{ask}` in place, so the guides still follow Site details when an address or port changes. **Back to Solstone's wording** undoes it.
- Solstone's own join guide no longer says some things from mods can be missing on Bedrock.

## Notifications for each server
- In Notifications, each server can stay **Same as above**, be switched **off**, or have **its own choices**: which events, and its own quiet hours.

## Accounts
- Making an account asks, both optional, for a **first name** (only admins see it: in Users, and as a tooltip on the account button) and a **birthday**, which adds their birthday banner and fireworks. Admins can set the name too (Users → the player button).

## Maps
- The World tab's map shows **everyone's head** instead of a dot, and moves them **every few seconds** without reloading.

## Home page
- Players' cards on the live section are **compact**: the player in their skin, health and food as numbers (❤️ 9/10 · 🍗 10/10), what they're holding. More fit on the screen.

## Smaller things
- **Heads show the right skin straight away:** skins are fetched when a player joins and kept, so pages don't show Steve for a moment first.
- **Messages at the top stand out more**, and problems show in **orange** with ⚠️ and stay up longer.
- **Firework editor:** editing a saved picture firework with another tab of the controls open no longer breaks the page ("Cannot read properties of null").
- Bedrock players' placeholder heads show their first letter, not the dot.


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
