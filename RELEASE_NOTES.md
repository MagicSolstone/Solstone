# Solstone 1.19.0

- **Fixed: a server with only RCON (no Crafty, no host's panel) showed nothing on its home page card.** Its uptime, in-game time and weather were left out, because only Crafty or a panel could say it was running. Now RCON answering means it's running (and not answering means it's down), the same way Solstone's own uptime history already counted it.
- **New: ServerPrism as a connection.** Under Manage → Server setup → Connections → **Add a connection → ServerPrism**, paste a token from serverprism.com → Account → API Credentials (with **servers:read** and **servers:control**; **backups:create** too for Back up). Then, in your server's ⚙ Settings, part 4, pick it and your server from the list. It gives Solstone what Crafty gives it at home: running or not, CPU and memory against your plan, uptime, start, stop and restart, and backups. RCON still does the game itself: ServerPrism's commands don't send back the game's answer and are limited to 20 a minute, while games and Solstone's live pages send several a second.

# Solstone 1.18.0

- **New: Manage → Solstone → Server setup.** One place to set up your servers: **Your servers** (each one's settings, and adding one somewhere else) and the new **Connections**. What used to be "Servers & history" is now **History & data** (recaps, website traffic, what people read, storage, backups, clearing history).
- **Connections: Crafty and hosts' panels, set up in Solstone itself.** Crafty no longer has to be set in the container's settings: add it under Connections (its address and API token, with a **Test it** button that shows the servers it found). A game host's **Pterodactyl or Pelican** panel is a connection too, added once for every server on that account. There can be more than one of each.
  - **Nothing to redo:** if your container has CRAFTY_URL and CRAFTY_TOKEN, they're brought in as a Crafty connection the first time this version starts, marked "From the container's settings". Everything keeps working as it was; you can then remove those settings from the container (or leave them, they do nothing more).
- **A server somewhere else picks its panel from a list.** In its connection settings, choose the panel connection and then the server from the list it shows, instead of copying an ID and pasting a key into every server. Panels already set up on a server are moved into a connection by themselves.
- **One settings window for every server**, whether it's on this machine or somewhere else (**⚙ Settings** in Your servers). The same four parts in the same order: **1. General** (name, map, private, hidden), **2. Its files** (on this machine, with its folder; or somewhere else over SFTP, with Test the connection), **3. RCON** (the one place for it now), **4. Start, stop and stats** (Crafty, a host's panel, or none). The separate "🔌 Connection" window for servers elsewhere is gone, and RCON isn't asked in two places any more.

# Solstone 1.17.1

- **Fixed: adding a server somewhere else always said "Couldn't reach it: Permission denied"**, even with the right details (the same login worked in FileZilla). The SFTP connection looked for SSH settings files in a home folder that Solstone isn't allowed to open in its container, and stopped there. It doesn't look there any more (it never needed anything from it).

# Solstone 1.17.0

- **New: a server somewhere else.** Solstone no longer has to run on the same machine as your server. In **Manage → Solstone → Servers & history**, press **🌐 Add a server somewhere else**: fill in the SFTP details from your host's panel, press **Test the connection**, and add it. It then works like a server at home: the activity feed, chat, leaderboards, stats, player pages, contests, races, games, rewards, the whitelist.
  - Solstone keeps a copy of just the files it reads and keeps it up to date over SFTP: the log every few seconds (only its new lines), players' stats and the world's info every half a minute (only files that changed), mods and old logs every ten minutes. Pages are as fast as for a server at home.
  - **The host's panel (optional):** for hosts on Pterodactyl or Pelican (most game hosts), an API key gives Solstone what Crafty gives it at home: start, stop, restart and backups, whether it's running, CPU and memory, and sending a command when RCON isn't answering.
  - RCON works as before: Solstone reads its port and password from the server's server.properties, at the host's address.
  - **Safe:** the SFTP server's identity is learned the first time you test it and checked before the password is sent, every time. If it ever changes, Solstone stops and says so. Passwords and API keys never leave Solstone (the page only knows whether one is saved).
  - Each one shows in **Your servers** with how its files and panel are doing; **🔌 Connection** changes its details, and **Stop looking after it** removes it (its history in Solstone stays).

# Solstone 1.16.0

- **New: see who's had an event's reward.** In Manage → Events, an event with a reward has a **👥 Who's had it** button: everyone who's been given it, when, and for which time round (and which server, if you have more than one). Anyone whose reward is still waiting for room in their inventory is marked. Only admins see it; it's kept for 60 days after the event. (Times are recorded from this version on.)
- **Fixed: a broken symbol in the reward's message in the game.** The message started with a present emoji, which the game's font doesn't have (it showed as a box with an X). It's a gold star now, like Solstone's other messages. The same for a contest prize's message and the vote messages.
- **Simpler games: archery, spleef, King of the Hill and the mob arena are gone.** They made things complicated (the arena puffed up the monster-defeated rankings, and players dying in fights caused trouble). Hide and seek, the treasure hunt, races and contests stay, unchanged. Any of the removed games that was planned is called off, and one in an event night's line-up is taken out of it; games already played still show in Finished and Lately.
- **No more Solstone data pack.** Only archery used it, so it's gone too: Solstone doesn't need to put anything in your world any more. A copy still in a world is switched off and removed by itself the first time Solstone sees it. The data pack section on the Contests page is gone. (Fishing contests and the fishing journal still work with the Tide mod, as before.)
- **Every server's settings in one place: Manage → Solstone → Servers & history.** A new **Your servers** list shows every server Solstone has found, shown or hidden, with what matters at a glance (Shown or Hidden, Private, whether RCON answers, Crafty or a folder, its version, a web map). **⚙ Settings** on each opens its name, map address, RCON and who sees it. The ⚙ on each server's own page is gone, and the separate "Hidden servers" list is part of this one (a hidden server has **Show it**).
- **A server Solstone finds for the first time starts hidden** (marked **New**), so a test world or a new server never turns up on the website until you choose to show it. Servers you already have stay as they are.
- **An event can be on just some servers.** With two or more servers, an event's settings in Manage → Events have **Which servers**: all of them (as before), or just the ones you tick. Its reward is only given there, and the Events page says which server it's on. With one server nothing changes and the choice doesn't show, so the page stays as simple as it is.

# Solstone 1.15.39

- **Fixed: the Stats chart showed no bars on phones.** A style for the Storage list's little bars (hidden on narrow screens) had the same name as the chart's bars, so on a phone only the running-total line showed. The chart's bars have their own name now.
- **Deaths are noticed more reliably.** A line in the server's log counts as a death only when it starts with a player's name, and the names came from the server's own files, which can miss someone (no name saved for them yet, or a Bedrock player). Everyone who's ever played on the server is checked now too.
- **Fixed: deaths missing from the Stats page.** The Stats page counted deaths only from the server's log, which can miss some (the leaderboards, which read each player's own stats file, had them right). Deaths now come from the players' stats files too, so the Stats page counts every one from now on. The activity feed shows them as "respawned 2×" alongside what else they did.

# Solstone 1.15.38

- **Fixed: a whole-machine restart showed as a green day in the uptime popup.** When Unraid restarts, Solstone is off too, so its checks have a gap, and a gap was always called "Not watched" and never counted against the server. Now, if the game server started again during that gap (its log says so), or Solstone came back to find it still starting, it's counted as down: one outage from Solstone's last look until the server was back, and that day's bar turns yellow or red. A gap where only Solstone was off (an update) while the server kept going is still "Not watched", as before.

# Solstone 1.15.37

- **Fixed: the home page's little graphs could be hours old.** To be quick, the home page showed the last saved status straight away and fetched a fresh one in the background, but when nobody had looked in a while, that saved copy was hours old, and its graphs with it (the numbers beside them were fresh). Now a saved status more than a minute old isn't shown without trying for a fresh one first (a few seconds at most). The home page also refreshes its status as soon as you come back to the tab, or come back to Home from another page.
- **New: a timeline in What people read.** Like Website traffic, there's now a bar chart of which pages people opened, coloured by page (the five most viewed, the rest as "Other pages"). Pick **Today** for a bar each hour, **7 days** for every 6 hours, **30 days** for each day, or **A year** for each week. Point at (or tap) a bar to see every page opened then, with how many times. Tap a page in the list to see just that page on the chart; **Show every page** goes back. Hour-by-hour counts are kept for a month; the daily counts are still kept for two years.

# Solstone 1.15.36

- **Dying in the mob arena or King of the Hill keeps you there.** You used to respawn at your bed at home for a moment, then get moved back to watch from above the arena: a jarring blink. Now everyone's respawn point is in the game while it's on, so dying brings you straight back there. Your own bed (or respawn anchor) is put back when you're home with your things.
- **Only the arena's own monsters.** The arena is held at midnight, so ordinary monsters can spawn in it and get mixed up with a wave. Monsters that wandered in are now cleared when the arena starts and every few seconds while it's on (only hostile monsters inside the arena: never animals, pets or villagers, and nothing outside it).
- **/trigger leave takes you out of a game you're in.** In the middle of a race, the mob arena, King of the Hill, a treasure hunt, hide and seek, archery or spleef, `/trigger leave` now takes you out and sends you home with your own things (it used to only take you off events that hadn't started). Everyone else plays on.
- **Every game checks what it handed out.** A race's elytra, rockets and boat, archery's match bow and arrow, spleef's shovel and the treasure compass are now checked after they're given, like the arena's kit: anything that didn't arrive is given again (worn things that won't go on go in the inventory), and the game's reply goes in Solstone's log ("…'s things for the game arrived without …").
- **No more zoomed-in view at the start line.** Racers were held still by slowing them to a stop, which narrows the view on Java (the same "zoom" as a slowness potion). Now each sits on an invisible seat until GO, and is put back on if they hop off. Their view is normal.

# Solstone 1.15.35

- **Fixed: a quick restart didn't reset "Up for".** Solstone checks each server every 30 seconds, and a restart like the nightly one can be over between two checks, so it never saw the server down: "Up for" kept counting from days before, and the uptime history showed it steady. Now the server's own log tells it ("Stopping server", then "Done"), so "Up for" starts again from the restart, and the uptime history lists it as 🔁 Restarted, with how long it took. A start or stop that both the log and Crafty notice is written down once.
- **The Xbox friend's status says what it's about:** "Gamertag online · friends can join through it right now" (and Gamertag reconnecting, not working right now, offline), instead of a plain "Online" that read like the server's own status. On the home page's join card and the server's Control page.
- **The World tab is tidier:** the "Where everyone is" list (names and coordinates) is gone. The map above it still shows everyone where they are, live.

# Solstone 1.15.34

- **Dropped a game's thing? It comes straight back.** During any game (mob arena, King of the Hill, races, treasure hunt, archery, spleef, hide and seek), an item the game handed out that's dropped, by a slip of the Q key or on purpose, is handed straight back to whoever's nearest (normally whoever dropped it) within a second. A sword mid-fight or an elytra mid-race isn't lost, and nothing's left lying about to pick up later. With nobody near (thrown off a cliff), it's simply gone.
- **A game's things can't be kept afterwards.** When a game ends, any of its things left on the ground are cleared; and on every check of the server, any lying about are cleared and any in the hands of someone who isn't in a game are taken back. Dying still keeps the kit: games switch keep-inventory on.
- **Every game's things, not just the kit.** Archery's match bow and arrow, spleef's shovel, races' elytra, rockets and boats, the treasure compass, and a fishing contest's rods once no contest is on (each game marks what it hands out; nobody's own things are ever touched).
- **The mob arena's floor stays clear.** What the monsters drop in the arena is cleared every few seconds and once more at the end, so it doesn't pile up (anything picked up in a game is left behind at the end anyway). Only inside the arena: the rest of the world's drops are untouched.

# Solstone 1.15.33

- **Wider race checkpoints.** Each point of a course can now count from up to 40 blocks away (it was 16), and there's a new **Every point: reach within … blocks · Set for all** above the list of points, so a whole course changes in one go. Wide ones are easier to fly through by elytra (10 to 20 is a good start). New points take the size of the point before them. The glowing posts round each checkpoint follow its size, so it's plain how close counts.
- **Starting a game: no one sits out for picking something up.** When a game starts, everyone's things are copied into the vault and checked. If someone picked something up (or dropped something) while it was being copied, the copy didn't match and they sat that game out with their things untouched. Now the copy is simply made again (up to three tries), so they still play. Players also see **"Keeping your things safe… hold still a moment"** while it happens.

# Solstone 1.15.32

- **Security: the map only takes real dimension names.** The world map's dimension (overworld, nether, a mod's own) is now checked to be a dimension's name, so it can never point outside the world's folder. Only signed-in people could reach it, and it could only read map files, but now it can't at all.
- **Forgot your password?** On the sign-in page. It works like making an account: type your Minecraft name, get a code in the game chat (only whoever's playing as you sees it), and choose a new password. You're signed out everywhere else and signed in with the new one.
- **Two-step sign-in for admins (and Trusted, if they like).** Account menu → **🔐 Two-step sign-in**: scan the QR code with an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password…), type its code, and keep the ten one-time backup codes. After that, signing in asks for the 6-digit code after the password, with **Trust this device for 30 days**. Lost the phone? A backup code works; another admin can turn it off for you (Manage → Users → **Two-step off**); or from the server itself.
- **Getting back in from the server.** On Unraid (a terminal or the container's console): `docker exec -it solstone python -m app.cli reset-password <login>` prints a new password; `two-step-off <login>` turns two-step off; `make-admin <login>` makes a login an admin (or a new admin login); `list` shows them all. Nobody on the internet can use these, and each is in the activity log.

# Solstone 1.15.31

- **Ask to join lives on the home page only.** The form isn't under the join guide any more. Every "Ask to join" link (in the guide, in posts, and old links to `/guides/join#ask`) goes to the home page and opens the Ask to join pop-up there, where the request's progress shows afterwards.
- **More fireworks at once by hand.** Launching from the fireworks pop-up now allows up to 40 in the air at once (24 on smaller devices), up from 12, so fast clicking fills the sky. The sparks still thin out by themselves when there are a great many, so it stays smooth.
- **Everyone can pick their own show pace.** The 🎆 Launch list now starts with **Show pace: Calm · Normal · Lively**, just for that person's device. The pace in the fireworks settings is everyone's usual; picking it again goes back to following it.
- **One Show switch for the whole site.** The home pages and the app each kept their own, so turning the show on at Home didn't carry over to Events, Servers or Manage (and the other way round). Now it's one switch everywhere. (Sound already was.)

# Solstone 1.15.30

- **Fixed: a false "Xbox friend joining isn't working" alert.** When MCXboxBroadcast's regular update to Xbox timed out once ("Failed to update session information… request timed out"), Solstone took it for an outage: it said "Not working right now" and sent a notification, though Bedrock players could join all along. MCXboxBroadcast tries again by itself and says nothing when that works, so one of these is now just noted (admins still see it on the Control page). Only several in a few minutes count as a problem, and once they stop, it's working again. The lines of a stack trace under an error are no longer read as more errors.

# Solstone 1.15.29

- **Treasure hunt: a treasure compass.** When the hint starts, everyone playing gets a compass that points straight at the chest. It's the game's, so it goes when they're home with their things. You can switch it off in the setup.
- **Treasure hunt: hints that make sense without a compass.** The hint now says where the chest is from where you're looking: "⬆ straight ahead", "↗ ahead, to your right", "⬅ to your left", "⬇ behind you". It used to say "north-east", which needed knowing which way north is.
- **Treasure hunt: see the area.** Sparkles run along the edge of the area on the ground, and a column of sparkles marks the middle, so players know where to start (or that it's on). You can switch it off in the setup.
- **Treasure hunt: warmth fits the area.** Burning hot (under 10 blocks) and Hot (under 20) stay the same; Warm, Cool and Cold stretch with a big area, so a 500-block hunt isn't "Freezing" almost everywhere.
- **The game's things don't stay on the ground.** At the end of the mob arena, King of the Hill, races and the other games, any kit items left lying around (thrown down, or dropped by someone who died) are cleared away. Only the game's own items: nothing of anyone's.
- The compatibility check also tries the treasure compass.
- **Race checkpoints are easier to see.** Each checkpoint's glowing column is now three blocks wide instead of one, thin glowing posts mark the edge of the circle you have to reach, and the white sparkles are now big coloured dots (green, and gold for the finish). The floating names, the locator-bar dots and the height hints are as before.
- **Fixed: a prize too big for any inventory never arrived.** Some items don't stack (cake, tools, armour, potions…), so 64 cakes need 64 spaces, more than an inventory has: it waited for room that could never be there. Prizes and rewards now come as far as there's room, and the rest arrives by itself as space opens up ("Here's part of your reward…"). A prize already waiting, like those 64 cakes, starts coming the next time its winner is on.
- **Kits check themselves.** After handing out a kit (mob arena, King of the Hill), Solstone looks at what the player actually has. Armour or a shield that didn't go on is put on again, and if it still won't, it goes in their inventory to wear; anything else missing (sword, bow, arrows, food) is given again. What the game said is written in Solstone's log, so if a Minecraft version turns something away it shows up there.

# Solstone 1.15.28

- **Fixed: the mob arena (and King of the Hill) handing out only armour and a shield.** Commands that only work on players (give, clear, title, messages, game modes, scores) were aimed at each player by their id, and the game quietly turned those away. Armour and the shield go on a different way, so they arrived; the sword, bow, arrows and food never did, and nobody's own things were cleared for the game. Every command aimed at one player now goes out with their name (a long Bedrock name works too), for every game, race and message. Getting your things back at the end already worked, and still does.
- The same fix means these now arrive as they should: the countdown titles ("Back in…", "Heading back in…"), messages to one player ("Your things are back"), your game mode put back after a game, and the arena's own kill and death counts.
- The elytra race's rockets (and the boat for boat races) arrive again: they were turned away the same way.
- **A safety net when a game starts:** if a player's inventory isn't empty after their things are put in the vault, it's emptied slot by slot (their things are already safe in the vault).

# Solstone 1.15.27

- **Holiday descriptions keep their lines.** A new line in a holiday's description is now a new line on the Events page (the box is bigger too).
- **Underline** in everything formatted on the website: posts, announcements, holidays and their rewards. Wrap words in `__two underscores__`, or use the new **U** button next to **B** and **I**.
- **A reward's message in the game can have lines**, up to 5. Each line is its own line in the chat, with the game's colours carrying on.
- **The reward on a holiday's banner says "Now until" its last day**, like "Now until Tue 30 Dec" (or "Today only"), so it's clear the reward is on the whole time the banner is up. The holiday editor's preview shows the real date.
- **Your own words for the banner after the holiday.** With "Keep the banner up on those extra days" checked, there's a new box for what it says after the holiday, like "Merry Christmas! Rewards still available through the end of the week". Leave it blank for the usual "Christmas is over, but there's still time for its reward!".
- The Events page no longer mentions fireworks shows.
- **Manage → Announcements → Holidays is now "Events"**, since it can hold any day you plan for, not just holidays: a server birthday, a building week, a family get-together. Everything in it works as before, and old links to it still work. On the Events page, these show with an "Event" tag.

# Solstone 1.15.26

- **Fireworks are simpler: no more scheduled shows or game-event fireworks.**
  - Gone from Fireworks → Firework show: the **Shows** tab (the show builder, and the day and night base shows) and the **Game events** tab (fireworks on the website for advancements, deaths, level milestones, nightfall, the server starting, and contest, race and game winners).
  - Gone from holidays: their scheduled shows and the New Year countdown. They're also off the Events page. Holidays keep their colours, favourite kinds, banners, messages and rewards.
  - Gone from announcements: "At zero, play a show". The celebration look still sets off a few fireworks at zero.
  - What stays: **The show** tab (kinds, colours, pace, and everyone's fireworks from the editor), and **Join fireworks**. That tab now has its own switch for whether a firework goes off when someone joins: their own join firework, or a random one. Players can still pick their own.
  - Level milestones still show in the activity feed.

# Solstone 1.15.25

- **What people read:** a new section in Manage → Solstone, under Website traffic, lists each page of the website (the home page, News & Help, Events, every news post and guide, the rules) with how many **views**, how many different **people** (not signed in · signed-in players), how many **read it** (opened a post or guide, scrolled to the end, and kept it open 15 seconds or more), and the average **time on it**. Look back 7 days, 30 days or a year. Admins' own visits aren't counted, bots are left out, and nobody is named: it keeps counts per page, per day.
- **Holiday rewards can have up to 9 items** (a hotbar's worth), up from 3. As before, each waits until the player has room for it.
- **The events timeline counts in days:** "In 21 days" instead of "In 3 weeks", and the gaps between events say "21 days" too.

# Solstone 1.15.24

- **Memory on the home page:** each running server's status now has a **Memory** card next to CPU, showing how much it's using and what share of the computer's RAM that is. On phones the cards now fill even rows, and an odd one out stretches across the full width, so there's never a gap. Memory has its own little graph of the last 6 hours, like CPU.
- **Events: no more "All day"** under holidays. It sat below the rewards and read like part of them. Holidays already show under their date, and timed events still show their time.
- **Tap a card for its history:** on the home page's status, tap **Playing now**, **TPS**, **CPU** or **Memory** for a bigger graph of the last 24 hours, 7 days or 30 days, with the lowest, average and highest.
- **Uptime, like a status page:** tap **Up for** (or **See its uptime** while a server is offline) for its uptime over 24 hours, 7 days and 30 days, a bar for each day (green: up all day; yellow: down under 30 minutes; red: down 30 minutes or more), and every time it went down: when, and how long until it was back. A quick restart (back within 5 minutes, like the nightly one) shows as a restart, not an outage. Times Solstone itself was off or updating show as "not watched" and don't count against the server. It shows counts and times only, never who was playing.

# Solstone 1.15.23

- **Letting someone in only tells them once it really worked:** their page says "you're in" only when they're actually on the server's whitelist.
  - **If Let them in fails** (a gamertag or Java name that doesn't exist), they hear nothing and their request keeps waiting. Fix the name and try again.
  - **Only Deny ever turns a request down.**
  - **Before, without RCON,** Solstone couldn't read the game's reply and assumed it worked. Now it checks the whitelist file, and tells you if it can't confirm.
- **Cancel a request to join:** a waiting request now has **Cancel** next to it. It takes the request back altogether, off the admins' list as well, so nobody's left waiting on something that doesn't matter any more. Only the person who asked can cancel it. Answered requests still have **Clear** to tidy them off the page.

# Solstone 1.15.22

- **Fix the name on a request to join:** typed it wrong? Press **✏️ Fix name** on the request (on the Whitelist page or in Control), then **Let them in**. They still see they're in on the page where they asked, and the request shows the name they first typed.
  - **Bedrock tip:** Xbox shows newer gamertags like "mama bear#7349". On the server that's **.mama_bear7349**: a dot, spaces as `_`, and the number joined straight on.
- **Who is this?** On the Whitelist page, click any name on a server's list to see its id there, who that id belongs to, and whether they've played on the server (and under what name).
  - **Bedrock:** the Xbox gamertag that owns the account, looked up through GeyserMC.
  - **Java:** the Mojang name.
- **Ask to join for more than one person (or account):** after asking, the home page lists every request from that browser, each with its own status (waiting, you're in, not accepted). **🙋 Ask for someone else (or another account)** is always there, so a family, or someone with both a Java and a Bedrock account, can ask back to back. Up to 8 requests an hour from one internet connection (it was 3).

# Solstone 1.15.21

- **Choose how long past events stay on the Events page:** Manage → Website → Site details → **Past events on the Events page**. Choose don't show them, 1 day, 2, 3, 5, a week, 2 weeks or 30 days. It's 3 days to start. Finished contests, races and games are now kept long enough for a month of it.
- **Fixed: keeping your own things through a game.** A game saves everyone's things, then takes a few seconds to get ready (the kit, the monsters) before it's marked as running. The tidy-up that returns things after games runs on its own, and took those few seconds for a game that was over. It handed everything straight back, so you played with your own things and the kit on top. A game now counts as on from the moment it saves anyone's things.
- **Edit race courses on the map:** in the course editor, **drag any point** to move it. It lands on the ground there and the route redraws as you go. **Click a point** to pick it, and the next click on the map adds a new point right after it, so you can put a checkpoint in between without starting over.

# Solstone 1.15.20

- **Every game and race works the same way now: in with nothing of yours, home with everything.**
  - **Applies to:** hide and seek, archery, spleef, the treasure hunt, and races on foot or by boat. The mob arena, King of the Hill and elytra races already did.
  - **At the start:** your things, where you were and your game mode are kept safe in the sealed vault (and checked). You play with just the game's things: its kit, a Match Bow, a shovel, a boat, wings and rockets, or nothing.
  - **At the end:** a short countdown (**Back home with your things in 8…**), then the game's things and anything picked up are cleared. You're back where you were, in the game mode you were in, with exactly your own things.
  - **Prizes arrive once you're home.** Handed out during a game, they'd be cleared along with everything else. The same goes for holiday rewards earned while in a game.
  - **Treasure hunt:** what's in the chest is the finder's prize, given once they're home.
  - **Crash out of any race** (die) and you're out of it, and home with your things.
  - **Nobody joins a race halfway,** since their things weren't kept safe.
- **Fixed: things could be handed back in the middle of a race.** The tidy-up that returns people's things after a game only knew about games, not races.

# Solstone 1.15.19

- **"Time's paused" on the home page:** while nobody's playing, the server pauses its clock. The "In the world right now" strip now says **⏸ Time's paused while nobody's playing**, and the clock stays put until someone joins.

# Solstone 1.15.18

- **Your things in games: rebuilt to be simple and solid** (mob arena, King of the Hill, elytra races).
  - **At the start:** your whole inventory is copied into the vault and checked. Only then is it cleared and the kit handed out.
  - **At the end:** everything on you is cleared, the kit and anything picked up. Your own things are then copied back to the same slots and checked, and only then is the vault emptied.
  - **A retry never adds anything on top.** If something goes wrong and it's tried again, it either finds your things already back, or clears you and copies everything over again. Nothing can come back twice.
  - **No more "pocket" of things handed out later.** It's what caused the duplicates, and while it held anything it kept you out of the next game: you kept your own things and got no kit. Old pockets are emptied automatically, never handed out.
  - **If Solstone was down during a game,** nothing you're carrying is touched. Your things come back once your inventory is empty (put things in a chest), and you're told so once.
- **A moment before going home:** when a mob arena or King of the Hill ends, the result shows and everyone is protected. **"Heading back in 8…"** then counts down before anyone is teleported.
- **Pick-ups are left behind:** mob drops and anything else picked up during a game are cleared at the end. You get back exactly your own things.
- **Crashing out of an elytra race:** die during the race and you're out of it. Once you respawn, you're back where you were before the race with exactly your own things, and the race carries on for everyone else.

# Solstone 1.15.17

- **No automatic banners for contests, races and games.** They used to appear by themselves ("starting soon", "on now", and the result for half an hour afterwards). Now they only show if you turn them on: **Announcements → Also show banners for contests, races and games**. It's off to start. Your own announcements and holiday banners are unchanged.
- **In the world right now, on the home page:** each running server's status card opens with the time in the game and the weather (☀️ morning, 🌅 sunset, 🌙 night, 🌧️ rain, ⛈️ storms), in matching colours. The clock ticks along while people are playing. Nothing about who's on.
- **Time and weather instead of "Day N":** the World page and players' overview show the game's clock and the weather. The day number reset whenever the time was set, so it wasn't reliable.
- **Fixed: the world's day count being reset.** The mob arena's "make it night", and the time buttons on Control, used `/time set`, which resets the day count. That's why it showed Day 3 after weeks of play. They now move the clock forward with `/time add` instead, which keeps it.
- **Lately, on the Events pages:** contests, races and games from the last 3 days stay listed with how they went, never who. For example: "Survived all 7 waves · 3 players", "12 took part · best 42 fish", "4 racers · 3 finished · fastest 1:12".
- **Mob arena fixes:**
  - **Monsters are one team:** they can't hurt or target each other, so they all come for the players. Before, big waves fought among themselves (spears and arrows) and wiped themselves out.
  - **They come out a few a second,** spread around the monster spots, instead of all at once in one heap.
  - **A wave only counts as cleared when it really is:** everything has come out, and the game twice says none are left. An answer Solstone can't read no longer counts as "none left", which used to skip waves and end the game early.
- **Fixed: kit gear and duplicates after a game.**
  - **The kit is taken back slot by slot.** Not every Minecraft version understands the usual `clear` filter, which is how diamond armour and a shield came back after a match.
  - **Kit items never come back** from the pile of things picked up during the game.
  - **A retry after a failed check knows your things already went over,** so it doesn't hand them over twice, however few items you had.

# Solstone 1.15.16

- **Fishing is only for servers with the Tide mod.** On a vanilla server fishing stays plain vanilla, and Solstone leaves it alone:
  - **No Fishing tab**, and no fishing on players' pages.
  - **No fishing leaderboards:** Fish caught, Fishing level and Heaviest fish are gone, along with the Fishing group.
  - **No fishing contests** (Fishing contest, Fishing tournament, Biggest catch). Any already scheduled, or in an event night, are skipped when their time comes, and nobody is teleported.
  - **The Solstone data pack (version 14) is just for archery and spleef.** It no longer weighs or tracks fish. Press **Install / Update** on the Contests page (or download it again) to swap in the new version.
  - With Tide installed, everything fishing works as before.
- **Bigger mob arena waves:** up to **100 of one kind** (70 baby zombies with spears, say) and **150 monsters in a wave**. A wave over the limit now says so, instead of quietly being left out.
- **More arrows in the fighting kit** (mob arena, King of the Hill): up to **256**, or tick **♾️ Arrows never run out** for an Infinity bow and one arrow, like the archery games. Both are taken back afterwards as usual.
- **Storage page loads straight away:** Manage → Solstone → Storage keeps its last measurement for 10 minutes and re-measures in the background. Measuring every row of a big database took about 4 seconds. It shows when it was measured.
- **Fixed: games that keep your things safe could duplicate them, and end early** (mob arena, King of the Hill, elytra races).
  - **What went wrong:** the server got busy (a wave of monsters spawning), so one "where is everyone" check came back empty. That counted as everyone leaving, so a "together" game ended on the spot and started handing things back mid-game. Handing back a second time then gave the hotbar's items again, into free slots, and the leftover copy blocked the next game.
  - **Now:** leaving means really not on the server, two checks in a row. Nothing is handed back while someone's on the death screen. A second hand-back notices they already have their things and just clears the spare copy.
  - **Leftovers from before:** on the Games page, **🔒 Things kept safe** now has **Throw away X's** for leftover spare copies of things the player already has.
  - **The kit never outlives the game.** When a game ends, its gear (armour, shield, sword, arrows) is taken from everyone, then once more after their own things are back.

# Solstone 1.15.15

- **Fireworks are gentler on the eyes:** made safer for people sensitive to flashing lights. This applies to every firework, including ones already saved.
  - **Blink** used to switch a whole burst fully on and off up to 5 times a second. Now it's at most about twice a second, and it dims rather than going dark.
  - **Strobe** is a lighter scatter of white sparkles.
  - On devices set to **reduce motion**, Blink, Strobe and the thunderstorm flash are switched off.
  - The editor's Twinkle step says so.
- **Faster, steadier pages:** the server list (status, who's online) no longer waits on Crafty or the game. It used to wait 2–5 seconds when Crafty was busy, and pages arriving together each asked separately. Now pages get the last answer straight away while one shared fetch updates it in the background, every few seconds as before.

# Solstone 1.15.14

- **Fixed: new holiday reward pictures missing on Events (again).** The public Events page skipped any server whose Minecraft game files weren't marked ready. The app's own item pictures still use ones drawn before, so the two disagreed. Now they work the same way.
  - If a picture really can't be drawn, opening its address says why: not a reward, no Java server, or the state of the game files.

# Solstone 1.15.13

- **Website traffic chart, readable:** in Manage → Solstone, the traffic chart now shows real bars stacked and coloured by who asked: **you**, **other admins**, **signed-in players** and **visitors**. The boxes above double as the legend.
  - A scale on the left, and a short line saying what each bar is.
  - Point at or tap a bar to see who asked during that time.
  - **7 days** shows 6-hour bars and **30 days** shows one bar a day, so they stay readable.
  - Fixed: every bar used to show as a small dash, because it borrowed the Server stats page's style.
- **Fixed: games in an event night couldn't be placed on the map.** Setting up a mob arena (or any map-placed game) as part of an event night ignored clicks on the map. One-off games were fine.
- **Fixed: some holiday reward pictures missing on Events.** Reward pictures on the public Events page and banners now come from any Java server that can draw them, not only the first public one. A picture that can't be drawn yet isn't remembered as missing, so it appears as soon as it can.
- **🐢 The slowest lately:** under Website traffic, a fold-out list of the latest answers that took over a second, with which page or data each was (by its route, never who asked). Kept until Solstone restarts, to make slowdowns easy to pin down.

# Solstone 1.15.12

- **Firework editor, step by step:** the editor now walks through a firework in the order it happens. There are five numbered steps: 🚀 Launch → 💥 Burst → 🎨 Colours → ✨ Sparkle → 🔊 Sound.
  - **Next →** buttons move through the steps. The step bar ticks off each step ✓ and shows what it's set to.
  - **Launch** has big cards for Sky rocket, Fountain and Spinning wheel. Volley and lean settings fold under **More**.
  - **Burst** becomes **Spray** for a fountain and **Spin** for a wheel. "Then…" steps and "Some pieces burst again" live here under **What happens next**.
  - **Sparkle** has three parts: Sparkle; **Twinkle**, which is one slider with a style choice of Blink, Strobe or Breathe; and **How it ends**. Gravity, air and wind fold under More.
  - Every firework already saved works and looks exactly the same.
- **Picture fireworks need an admin's OK:** a picture drawn by a player or trusted account starts as ⏳ **Waiting for an admin**.
  - The maker can watch it in the editor. Until it's approved, it stays out of the show, the Launch list, join fireworks and everyone else's list.
  - Admins get a notification and a **Waiting for approval** list on the Fireworks page, with **Watch**, **Approve**, or **Not approved** with an optional reason the maker sees.
  - Drawing a new picture on an approved firework asks again. Changing its colours or anything else doesn't. Admins' own pictures don't wait.
- **Pictures in posts open big:** tap or click a picture in a news post or guide to see it full screen.
  - Zoom with a pinch, the mouse wheel, a double-tap or the **+ / −** buttons, then drag or scroll around.
  - ✕, Esc or tapping outside the picture closes it. Handy for screenshots with small writing.

# Solstone 1.15.11

- **Overview activity, readable with lots of people on:** the activity lines saved every few minutes per player ("defeated 3 zombies · dug 40 blocks") are added up into **one row of icons per player** in each play session, like "⚔️ 16 monsters · ⛏️ 1,980 dug · 🧭 8.6 km". The full name of each shows on hover.
  - **Every 10 minutes** opens the same rows for each 10-minute slice.
  - **The moments stay as their own lines:** joins, deaths, advancements, chat, big catches and results.

# Solstone 1.15.10

- **Website traffic** (Manage → Solstone): what Solstone answered over the last 24 hours, 7 or 30 days.
  - **Who asked:** you, other admins, signed-in players, and visitors who aren't signed in, with about how many different visitors.
  - **By hour,** and what was asked for: pages, data, the map, pictures and files.
  - **How quickly:** how much was answered in under 0.1 s, the average, and anything over a second.
  - **The container's whole network,** including talking to the game, Crafty and Modrinth.
  - **No addresses are kept:** visitors are counted with a scramble that changes every day. Cloudflare's dashboard still shows what never reaches here.
- **Kilometres or miles** (Website → Site details → Distances in): applies everywhere distance shows, including player stats, leaderboards, the home page's Today line, Server stats, Adventures and activity lines.
- **The Leaderboards tab is now Stats,** with Leaderboards and Server stats under it.
- **Server stats:**
  - **Most hours played in a day** is everyone's hours that day together.
  - **"Longest time on in one go" is gone:** it was one player's own, not the server's.
- **Answered lately:** a ✕ on each, and **Clear all**. This only clears your list: their own page still shows their answer.
- **Development builds on the Mods page** show their build number: "2.12.1 build 1288", not "2.12.1-SNAPSHOT".

# Solstone 1.15.9

- **Answered lately, tidier:** a button beside **Asked to join** on the whitelist page ("👀 Answered lately · 2 not seen yet") opens the list in a popup, instead of a section taking up the page.
- **Everyone you let in is on it straight away:** before, someone let in only showed up once their own page had checked back, so anyone who hadn't looked since was in neither list. Now they show as "Hasn't seen it on the website yet", then "Saw it" once they look.

# Solstone 1.15.8

- **Server stats** (Leaderboards → Server stats): what everyone did on a server, day by day, kept for good. For everyone signed in, server-wide with no names.
  - **Kept for good:** each day is boiled down to one small row of totals. It's filled in from the history still on hand the first time (up to 180 days), then kept up to date before the old detail is cleared.
  - **Totals** for the last 30 or 90 days, a year or all time, each with a fun way to picture it ("≈ 11.5 marathons", "about 691 trees").
  - **One chart at a time:**
    - 17 things to chart: hours played, monsters, distance, blocks dug and placed, fish, deaths and more;
    - by day, week or month, with a running total and the exact number on hover.
  - **When people play:** weekday by hour of the day.
  - **Records:** busiest day, most on at once, the biggest days, the longest time on in one go.
- **Fix:** the first thing in an activity line ("Sam dug 40 blocks") wasn't counted, because of the name in front. That affected the home page's Today line and Adventures.

# Solstone 1.15.7

- **Xbox friend watcher:** is joining through the Xbox friend (MCXboxBroadcast) working?
  - Solstone watches what MCXboxBroadcast writes in the server log. A dropped connection gets two minutes to reconnect, since it normally takes a second or two.
  - Not back by then: a notification (with the server notifications), and another when it's working again.
  - **Home page:** under the gamertag, it says Online, Reconnecting, Not working right now (the server address then unfolds), or that the server's off.
  - **Server → Control:** a panel with the state and since when, reconnects in the last day, and the last problem it logged.
- **Bedrock on the home page:**
  - "Gamertag:" before the gamertag, so it's clear what to add as a friend.
  - **Or add it as a server** says it's for phones, tablets and Windows, since consoles can't add servers.
- **Console help:** a post can be used as Console help (Website → Posts → Use as). Once one is, the Bedrock part links to it ("On a console? Here's another way in"), more plainly while the Xbox friend is down. Without one, nothing shows.
- **Saw it:** Manage → Whitelist lists requests answered lately, and whether they've seen the answer on the website ("Saw it 2 min ago"). A notification goes out the first time they see it.
- **Events, simpler:** each day with something on is one dot. A holiday with a reward has a gold ring on its dot, and its card says the reward and when to play for it. A reward that's already started, for a holiday still ahead, is said under Today.
- **The players graph ends at now:** it drops to 0 when everyone's gone.

# Solstone 1.15.6

- **Ask to join survives a restart:** someone waiting with the home page open gets "You're in!" after Solstone restarts, with no reload.
  - Before, the error page the proxy shows during a restart made the page forget the request.
  - Now an error page or no answer is tried again shortly. The request is only forgotten when Solstone itself says it doesn't know it.
- **A clear message for a read-only server folder:** adding a Bedrock player when the Solstone container can only read the server's folder says to set that folder's mapping to Read/Write, instead of a raw file system error.

# Solstone 1.15.5

- **Whitelisting Bedrock players works without Floodgate's `fwhitelist` command.** Floodgate on Fabric doesn't always have it, so adding a name like `.Lego8595` failed with "Unknown or incomplete command". Now, when the game says that:
  - the player goes on the server's own whitelist by their Floodgate id;
  - their Xbox id is looked up from the gamertag (trying spaces for underscores too);
  - the game reloads the whitelist straight away, no restart.
  - Removing works the same way, and a gamertag that isn't found says so.
  - The same goes for **Allow** on people turned away, and for letting in someone who asked to join.

# Solstone 1.15.4

- **The join card, by edition:** each server's card is in two clear parts.
  - **Java Edition (PC or Mac):** the address, the version to launch, and where to put it.
  - **Bedrock Edition (phones, tablets, consoles, Windows):** the friend's gamertag first, in green ("Add as a friend", works on every device, consoles too). The address and port are under **Or add it as a server**.
  - Small pixel badges of our own: a grass block for Java, a stone block for Bedrock, a controller for joining through a friend.
- **Who's on which edition:**
  - "Playing now" on the home page says how many are on Java and on Bedrock (counts, never names).
  - The players list has a Java or Bedrock badge beside each name.
- **Races:**
  - **A checkpoint flown through between looks counts.** An elytra covers about 30 blocks a second, so the whole stretch since the last look is checked, not just where they are now.
  - **Each checkpoint can have its own height:** "counts from 60 to 100 blocks above it". Its glowing column shows exactly that band.
  - **Clearer signs:** reaching a checkpoint flashes a big ✔ with the next one's name. Close to the next one, the line above the hotbar says to go higher or lower.

# Solstone 1.15.3

- **Setup windows keep their place:** adding a wave, a monster, a spot on the map or a checkpoint no longer jumps the window back to the top. That's every setup window.
- **Events: a reward that starts before its holiday has its own gold dot** on the day it starts ("Thanksgiving's reward starts · play any day until Sun 29 Nov").
  - The line is gold for as long as a reward is being given.
  - A reward that's already on shows under Today.
  - The holiday's own count still counts to the holiday, in days up to 60 ("In 23 days").
- **People not playing are kept out:**
  - Anyone in the mob arena who isn't playing (there when it starts, or wandering in) is moved just outside its edge, onto solid ground, and told why once.
  - Anyone not playing is kept a few blocks off King of the Hill's hill.
  - Admins in creative or spectator are left alone.
- **Arena monsters stay on the players in the arena:** they notice players about as far as across the arena, not people watching from nearby.

# Solstone 1.15.2

- **Events as a timeline:** today at the top with what's on now, then a dot for each day with something on, dotted stretches with how long between, and a gold stretch with the dates for a holiday's reward.
  - A holiday stays on Events while its reward is still being given after the day.
  - Holiday cards take their banner's look (or your own colours).
- **Times are typed in, not picked from a list:** every time in the contest, race and game setups is a number box with its unit (minutes or seconds). That covers:
  - contest length and breaks, and a night's breaks;
  - time limits, hiding and seeking, spleef's shrinking, the treasure hunt's hint, and hot zones;
  - "back in after" in King of the Hill and the mob arena;
  - the kit's arrows.
- **Mob arena:**
  - **Special monsters:** baby zombies, zombies in iron armour, zombies with spears (1.21.11+), skeletons with pumpkin heads, in chainmail or with swords, spider jockeys, charged creepers, big slimes, baby husks and drowned with tridents. Their gear never drops.
  - **Every monster has its weapon:** skeletons and strays have bows, pillagers crossbows, vindicators axes. Before, the arena's monsters came empty-handed.
  - **Night while it runs** (on by default), so spiders fight. The time of day goes back afterwards.
  - **Monsters come for players from anywhere in the arena,** not just within 16 blocks.
  - **The edge is marked every few blocks,** however big the arena is.
  - **The ready-made waves are a row each,** with **Change these** to start your own from them.
  - **A slime's smaller selves are the arena's too:** counted, kept in, and removed at the end.

# Solstone 1.15.1

- **Safer giving back after games:** only the game's own kit is taken away. Nothing else of a player's is ever cleared.
  - Anything else they're carrying (picked up in the game, a prize or holiday reward given during it, or things gathered while Solstone was down) is kept safe and checked first, then put back in their empty slots after their own things return.
  - Whatever doesn't fit waits until they make room, then arrives by itself. Nothing is dropped on the ground.
  - Their own things still come back exactly, slot for slot.
- **No surprise teleports:** someone whose things were kept from before Solstone last restarted gets them back where they are, not where they stood before the game.
- **One more check before a game:** if something changes in a player's inventory while it's being copied, they sit that game out and nothing of theirs is touched.

# Solstone 1.15.0

- **Players' things are kept safe during games:**
  - Before a game that needs it, everyone's inventory, armour and offhand are copied into a sealed storage box under spawn and checked item by item before anything is cleared. If the copy can't be confirmed, that player sits it out and nothing of theirs is touched.
  - Afterwards everything comes back exactly, and they're put back where they were, in the same game mode, healed and fed.
  - Someone who signs out or loses connection gets their things back when they next join, even after a server restart.
  - **Give back now** on the Games page, just in case.
- **King of the Hill:** free-for-all or 2, 3 or 4 teams. In teams, the side with the most players on the hill scores; level means nobody does. Respawns after a 3–15 second countdown. Keep inventory is on while it runs.
- **Mob arena:** Easy, Normal or Hard waves, or your own (which monsters, how many of each). Monsters come out of spots you mark on the map. Players and monsters are kept inside the arena, and creepers can't blow holes.
  - **Together:** anyone who falls watches until the wave is cleared, then comes back.
  - **Everyone for themselves:** most monsters defeated wins.
- **Races:**
  - **Elytra races:** everyone's own things are kept safe, then each racer gets an elytra and rockets. A checkpoint counts flying through it high up. **Safer flying** takes most of the damage out of crashes.
  - **Boats:** a normal race can give each racer a boat at GO, for courses across water and land. Taken back at the end.
- **Holidays have one banner each,** all the way through: counting down before, the message on the day, and "still time for its reward" after, if the reward runs on. The reward shows on it whenever it's being given.
  - **Its own look:** the announcement looks, or your own colours.
  - **Formatting:** the name, the day's message and the reward's description can be bold, italic or coloured. The reward's game message takes the game's colours, with a preview.
  - **A tidier editor:** the holiday, its banner and its reward in three sections, with a preview of the banner before, on and after the day.
- **No more prizes on the ground:** when someone's inventory is full, a reward or prize waits. They're told to make room, and it arrives by itself when they do.
- **Cleanup:** the old live status page's leftovers are gone; old `/status` links go to the home page.

# Solstone 1.14.3

- **Deny with a message:** saying no to someone who asked to join opens a box for a message ("Ask again with your real name in the note"). Only they see it, where they asked.
- **The answer where they asked:** the home page's Ask to join step shows the answer, not the corner badge.
  - **Let in:** with **Clear this**.
  - **Not accepted:** with the admins' message, **Ask again** and **Clear this**.
  - The corner badge is now just for the other pages.
- **A holiday's reward, shown properly:**
  - **Its own description** ("Reward for playing **Thanksgiving weekend**").
  - **Its own line on Events,** under the holiday: the item's picture, the amount and the days.
  - **A banner while it's given,** if you tick it: 🎁, the description, the item and when it ends.
- **Storage:** the world map's pictures are called what they are. They grow with the world explored, not with time.

# Solstone 1.14.2

- **All together on a player's page covers every tab but the inventory** (for someone with more than one Minecraft account):
  - **Play history:** each account's time stacked in its own colour, and every account's sessions and activity.
  - **Statistics:** added up across their accounts.
  - **Advancements:** from whichever account got each one first, and which account that was.
  - **Just one account** shows that account alone. The inventory is always that one character's.
- **Holiday rewards are picked from the item list,** with pictures and an amount, like a contest's prize.
- **A holiday's reward window:** given from some days before to some days after (Thanksgiving through Sunday: 0 and 3). The Events page shows the dates.
- **A holiday's colours window:** its firework colours from some days before to some days after (a red, green and white week for Christmas). The message banner stays on the day itself.
- **Players' own fireworks take a holiday's colours** when they go off by themselves (it can be switched off per holiday). One launched by hand keeps its own.
- **Storage in Manage → Solstone → Servers & history:**
  - how much room Solstone takes, part by part;
  - what's in its database and how long each kind is kept;
  - the disk's free space.

# Solstone 1.14.1

- **Bedrock players with long names:** the game takes a name of 16 characters at most in a command, and a Bedrock name through Floodgate can be 17 (a 16-character gamertag with its dot). Heal, teleport, messages, prizes and the rest now reach them by their UUID instead. When the game answers *No player was found*, the page says so instead of *done*.
- **Admin buttons on a player's own page** while they're playing: Heal & feed, Give items, Teleport, Game mode, Kick, and a private message.
- **A bell for notifications:** asks to join, messages and votes, each saying what it is with a link straight to it. The number moved off your name.
- **Linked Minecraft accounts:**
  - tucked in under the main one in the players list;
  - a player's page shows everyone's progress **All together** (or **Just** one account);
  - the **+** is in Most medals too, and can be tapped on a phone to see the other names.
- **Holidays:** a description (bold, colours, links) and a **reward**. Everyone who plays during it gets the reward once, each server, each year. Both show on Events.
- **Announcements:** six more looks (ocean, forest, sunset, candy, night, ruby) and **Your colours**, a gradient of two or three of your own.
- **News & Help** is one page; Questions shows only when there are some.
- **Asking to join** checks every 15 seconds while the page is open.
- **Footer:** Solstone made by Tyler J.

# Solstone 1.14.0

- **Getting started on the home page:** the join section is now three steps, one after another, all on the home page:
  1. **Ask to join:** a button with a slow glow. It opens the form in a pop-up. Once sent, the step says *Waiting for an admin to let you in*, then *You're in!*
  2. **Get in the game:** the server addresses, inside the step.
  3. **Make a website account:** a pop-up. If the name isn't in the game right now, it says to join first and check the spelling. Once the code is in their game chat, they type it and pick a password.
  - Both are switched on together in Website → Site details, under **Getting started**.
- **Bedrock through an Xbox friend (MCXboxBroadcast):** each server in Site details → *How to join each server* has an **Xbox friend** field. The gamertag shows first for Bedrock players (add it as a friend, join from the Friends tab, consoles too), and the join guide explains it. `{xbox_friend}` puts it in any post.
- **Sign-in page:** a clear **Make a new account** button and a centred **Back to home**. The guide links are gone.
- **Guides you delete stay gone:** deleting a post that stands in for a guide takes that guide off Help, with no links left to it. Solstone's built-in guides are listed in Website → Posts with **Remove** and **Bring it back**. The *making an account* guide starts off.
- **Home page status:**
  - little graphs of the last 6 hours for players, TPS and CPU;
  - a **Today** line: players, mobs defeated, blocks dug, logs, fish, advancements and distance, added up, never who.
  - **Never slow when Crafty is down:** the page shows the last status straight away and refreshes it in the background, and an unreachable Crafty isn't asked again for 30 seconds.
- **Manage in six tabs:** Players (Accounts, Whitelist), Website, Announcements (Banners, Holidays), Community (Messages, Votes), Play time, and Solstone (Servers & history, Notifications, Activity log). The old *live on the home page* switches, which did nothing any more, are gone.
- **Game messages** (was *Welcome in the game*): a new **Send a message** section with colours and a preview. Send it to everyone on now, to everyone the next time they join, or to one player (now, or when they next log in). A list shows what's waiting and who it reached.
- **Announcements can be formatted:** bold, italic, links and colours, with a formatting bar. The game gets the plain words.
- **One person, one line:** an account's Minecraft names (Java and Bedrock, say) count as one player on the leaderboards, the time-played chart and the daily recap, under its main name with a **+**.
- **Server tabs:** Adventures and Fishing are tabs of their own; contests, races and games are an admins' **Contests** tab.
- **Adventures:**
  - Tools no longer count as blocks placed (a stone pickaxe was counted as stone).
  - The feed opens summed up **every 10 minutes**: each player's mobs, blocks dug, logs, fish and damage as icons, with joins, deaths and advancements on their own lines. **Everything** shows the full feed.
- **World map:** players not seen in a week are left off.
- **Sounds:** a loaded sound can be saved over (**Save**) or copied (**Save as new**).
- **Fishing journal:** *Family record* now says *Server record*.
- **Player colours:** past 16 players, lighter and darker shades instead of grey.
- **Up for:** a Crafty start time from before a restart Solstone saw isn't used.

# Solstone 1.13.1

- **Up for is right:**
  - **The bug:** the home page's status panel worked out how long a server had been up from Crafty's start time, which has no time zone. In some setups it landed in the future, and the panel showed *0 min*.
  - **The fix:** Solstone now works out the start time itself and uses its own record of when it last saw the server go up whenever Crafty's time doesn't add up. That record survives Solstone restarts.
- **No memory on the status cards:** CPU stays.

# Solstone 1.13.0

- **A clean server status panel at the top of the home page,** above *Join the server*, the same for everyone. For each public server:
  - online or offline;
  - how many are playing (a number, never who);
  - TPS (with how smooth it's running);
  - the Minecraft version and loader;
  - how long it's been up, and its uptime over the last 7 days;
  - CPU and memory.
  - It refreshes every 30 seconds while the page is open. It's switched on with *Show the public servers' status on the home page* in Website → Site details.
- **The live section at the bottom of the home page is gone:** who's playing now, who was playing, where everyone is, leaderboards and *Today on the server*. Everyone who's signed in sees all of that on each server's own pages.
- **No player names for anyone not signed in:**
  - **Live data:** the data behind the old live section (who's on, leaderboards, recaps) now needs a sign-in.
  - **Banners and fireworks:** these name players only to people who are signed in.

# Solstone 1.12.6

- **Votes you haven't voted in, everywhere you're signed in:**
  - **Banners:** a vote's banner now shows on Home, News, Help and every other page, not just inside the app. It goes away once you've voted.
  - **The number on your name** counts unvoted votes too.
  - **In your name's menu:** **Messages** shows its own count and **Votes** shows its own. For example, 2 new messages and 1 vote gives **3** on your name, **2** by Messages and **1** by Votes. Voting updates the numbers straight away.
- **The offline page checks each server once, on its Java side:**
  - Java and Bedrock players play on the same server, and a Bedrock check is less reliable, so one check now covers both.
  - The page says **Online · 3 playing** or **Offline**, and still lists both the Java and the Bedrock address (with its port) for joining.
  - A new **Address for the up/down check** box in Website → Site details (on each server's join card) lets you give the address to check directly, like playit's `something.ply.gg:12345`. That helps when the address players use goes through DNS that a status checker can't follow. Empty means it checks the Java address.
  - **After changing it,** download the offline page again and paste it over the old one in Cloudflare.

# Solstone 1.12.5

- **The fishing journal is off to start (servers with the Solstone pack):**
  - **Why:** the game never shows a fish's weight outside a contest, so a journal full of weights players never saw was confusing.
  - **With it off:** fish caught outside a contest aren't weighed, kept or shown on the website. The Fishing tabs are hidden for players.
  - **Contests are unchanged:** catches are weighed, announced in chat and scored, with prizes.
  - **"Fish caught" on the leaderboards** still counts every fish (it's the game's own number).
  - **To turn it back on:** admins can, at the top of Play → Fishing (**Show the fishing journal**).
  - **With the Tide mod** it's always on, because Tide's fish show their weight in the game.
- **The same account menu everywhere:** on Home, News, Help and the other website pages, your name's menu now matches the one inside the app:
  - your role;
  - Messages and Votes (with the unread number);
  - Fireworks;
  - Manage, for admins;
  - display name, My Minecraft accounts, change password;
  - sign out.

# Solstone 1.12.4

- **Server start and stop icons on phones:** on the home page's live info (*Lately* and *Recent activity*), server starts and stops showed a crossed-out box in some phone browsers, because their fonts have no power symbol. They now use ⚙️, as the server page does.
- **The sky's settings moved to Website → Site details:** follow the game or always night, which server it follows, and fireworks in the daytime. It's the sky behind every page, so it belongs with the website's settings. Fireworks → Firework show links there.
- **Removing a player for good** (Manage → Whitelist, at the bottom):
  - **A step-by-step guide for the game side,** in order:
    1. take a backup;
    2. delete their land claims (Flan);
    3. take them off the whitelist (and deop or ban them if needed);
    4. delete their files (`playerdata`, `stats`, `advancements`, by their ID) while they're offline;
    5. remove their line from `usercache.json`, and look for other mods' files under their ID;
    6. delete their website account.
  - **🧹 Forget a player in Solstone:** takes them off Solstone's pages on every server:
    - their play history, play time and leaderboards;
    - their activity and chat lines, Adventures trail and fishing journal;
    - their name in daily recaps;
    - their play-time rules, join firework, prizes still owed, asks to join and in-game votes.
    - Finished contests, races and games keep their results, with "a former player" in place of their name.
    - Nothing in the game itself is changed.
  - **Guarded against accidents:**
    - It shows exactly what would go first, with their ID and any old names they played under.
    - You type their name again and tick that you've taken a server backup.
    - It won't run while they're playing anywhere.
    - Solstone makes its own backup just before, so it can be undone by restoring that.

# Solstone 1.12.3

- **Go by your Minecraft name only:** in **My Minecraft accounts** (account menu), once your Minecraft name is linked, **Use <name> as my login** makes it both your login and the name everyone sees.
  - The old login stops working completely. Your password stays the same.
  - Your fireworks, saved sounds, posts, Adventures and activity log move over to the new name.
  - There's no separate display name after that.
- **Deleting an account cleans up after it:**
  - **Gone:** its fireworks and saved sounds, its join firework and its weight in the firework show. Its messages, votes and *I'm coming* sign-ups already went.
  - **Kept:** posts on the website (they're the site's pages), Adventures saved for a server, and the activity log.
  - **Bedtime and play-time limits** set for that player move onto their Minecraft name, so they keep applying in the game without an account.
  - **Votes:** in votes still open, its vote is taken back (the vote isn't decided yet). In finished votes, its vote stays counted, so a result never changes afterwards; it just isn't anyone's any more.
- **A new Java name or Xbox gamertag:** the game knows each player by an ID that never changes, so their whitelist place, stats and history all carry on. They don't need to ask to join again. Solstone now notices the new name when they next join and moves to it:
  - the name linked to their account, and their login if it was that name;
  - their play-time limits and their join firework;
  - their votes from the game.
- **🧹 Unused pictures** (Website → Site details): pictures uploaded for posts and votes that nothing uses any more (taken out of a post, or the post or vote deleted). It shows how many there are and how much space they take, with **Remove them**. Pictures less than a day old are never counted, so one in a post you're still writing is safe.

# Solstone 1.12.2

- **Asks to join on your name:** for admins, the number on your name at the top now also counts asks to join that are still waiting (not yet let in on every server they asked for). **✅ Whitelist** in Manage shows how many, and the number goes down as you let people in.
- **An invitation to make a website account, for players who don't have one:**
  - **When:** when they join the game, a line in chat (after the welcome message) says they can make a free account to vote, see what's coming up and say they're coming, and how to do it.
  - **Who gets it:** only players whose Minecraft name isn't on an account yet, and only while sign-up is open on the website. Nobody has to make one.
  - **Settings:** Website → Welcome in the game, under the reminders.
    - **How often:** off, the first time they join, once a day (to start) or every time.
    - **The wording:** yours to write, with the same colours and fill-ins (`{site}` is the website's address, clickable on Java).

# Solstone 1.12.1

- **Firework editor:**
  - Coming back to the page (from another tab or app) no longer leaves the preview frozen until the next launch: whatever was in the air carries on.
  - The empty box above the save bar is gone. It's the *When you join the server* picker, and it only shows when you have a linked Minecraft account to pick a join firework for.
- **Weekly and daily repeats keep their time across daylight saving:** a contest or event set for 5:00 PM every Friday stays at 5:00 PM after the clocks change. Before, the next ones showed (and would have run) at 4:00 PM, because each repeat was exactly 7 × 24 hours later. This applies to the Events page and to when they actually run.
- **The Solstone data pack starts even when another mod or pack breaks the game's start-up list:**
  - **The problem:** every data pack and mod adds to the game's shared list of things to run when the world loads. One entry pointing at something missing can make the game drop the whole list. Then the Solstone pack never started: Solstone couldn't see its version, and Fishing tournament, Biggest catch, Archery and Spleef stayed unavailable.
  - **The fix:** when the pack is loaded but hasn't started, Solstone now starts it itself. This happens on **Load it**, on the server check, and every few minutes.
  - **The tick:** the pack's every-tick part (archery shots, spleef's safety net) keeps itself going instead of relying on the game's shared tick list.
  - **Update the pack:** the pack is now **version 13**. Press **Load it** on Play → Fishing to put it in the world.
- **Load it shows what matters:**
  - Only problems with the Solstone pack itself, not other mods' unrelated errors (like Flan's files for mods you don't have).
  - Whether Solstone had to start the pack.
  - What the game answered if it couldn't start.
  - What the game says it has, in a fold-out.

# Solstone 1.12.0

- **Events: a lineup of challenges under one name.** Play → Challenges has a new first tab, **🗓️ Events**.
  - **The event:** an event like *Fishing Fridays* has:
    - a name;
    - a description you write, if you want one;
    - a start time;
    - the break between challenges;
    - whether it repeats (once, every week or every day);
    - whether players choose to join.
  - **Its challenges:** each one is a contest, race or game, in order, with its own kind, length and prizes, and an optional 🏷️ note ("Warm-up", "Double prizes!").
    - Add one with **🏆 Contest**, **🏁 Race** or **🎲 Game**. These open the usual form, without its own time. A contest can be added several times over ("5 in a row").
    - Each challenge can be moved up or down (↑ ↓), copied (⧉), changed (✏️) or taken out (✕) until it starts. The event's name, description, break and start can be changed too.
  - **Times:** contests have set lengths, so their times are exact. After a race or game, whatever comes next starts the chosen break after it actually ends. Until then those times are shown with ≈.
  - **Joining:** players still join each challenge on its own with `/trigger join`.
  - **Repeats:** a weekly event comes back as a whole once it's over.
  - **Back to back:** choosing several contests "back to back" on the Contests page now makes an event of them, so they stay together.
  - **On the other tabs:** contests, races and games that are part of an event say *🗓️ Part of Fishing Fridays* on the Contests, Races and Games tabs. They're changed from the event.
- **Events page:**
  - **One card per event:** its name, time span (7:00–7:33), how often it repeats and your description, with its challenges as a row of cards in order (time, name, note) that scrolls sideways on phones. The one on now is highlighted.
  - **Signed in:** each challenge has its own **I'm coming**, with who's coming. **I'm coming to all of it** signs you up for every one at once.
  - **Visitors:** they see the same card, without names or buttons.
- **Sign-in page:** just signing in now, plus the announcements. The *See who's playing* box is gone, since visitors land on the home page, which already shows who's on.

# Solstone 1.11.1

- **Change a scheduled contest:** **✏️ Edit** on a contest that hasn't started puts it back in the form. You can change the time, the prizes, its length or anything else, then **Save the changes**.
  - For a contest that's one round of several, tick **Change every round still to come** to give the rest the same prizes and settings. Each round keeps its own time.
- **Several contests in a row, in one go:** in the new contest form, **Back to back** sets how many contests in a row (up to 10) and the break between them (0 to 15 minutes).
  - For example, *5 contests in a row with a 2 minute break* at 7:00, each 5 minutes long, makes rounds at 7:00, 7:07, 7:14, 7:21 and 7:28. The form shows that plan before you save.
  - Each round is its own contest, named *Fishing · round 2 of 5*. Players join each one on its own, and each has its own winner and prizes.
  - Weekly repeats bring the whole set back every week.
- **Events page, tidier:**
  - Each event after the first in a back-to-back run is a single short line under the one before (↪ name, time, *I'm coming!*), with no repeated description.
  - On phones, the name gets the whole width and the time and *I'm coming!* go on the line below, so nothing gets squeezed into a narrow column.
- **Birthdays are gone:**
  - **Sign-up** no longer asks for a birthday.
  - **Announcements** has no Birthdays tab: no birthday banners, no "birthday in 3 days", no birthday show, and no "Happy birthday" in the game.
  - **Events** no longer lists birthdays.
  - **Saved birthdays are deleted** the first time Solstone starts after updating.
- **Fireworks:** the *Cake* firework is now called *Barrage* (🧨), so it doesn't look like a birthday cake. It fires the same fast fan of shots.
- **Holidays:** a new holiday added with **+ Add** starts as *New holiday* (🎉) with no message, instead of a birthday.

# Solstone 1.11.0

Includes everything in 1.10.6 (not released on its own), plus:

- **Players choose to join:** contests, races and games have a new switch, **Players choose to join**. It's on for new ones; untick it and everyone online takes part, as before.
  - **In the game:** players type `/trigger join`. Any player can, no operator needed, and nobody else sees it. On Java they can also click it in the messages; on Bedrock they type it. `/trigger leave` takes them out again.
  - **On the website:** *I'm coming!* counts as joining once they're on the server.
  - **When:** joining opens an hour before the start (you can change that). Races and games close when they start. Contests can still be joined until they end, and only what's caught (or counted) after joining scores.
  - **What joining means:** only players who joined are teleported, get the contest rod and the fair fishing level, see the countdown and *Go!* on their screen, are scored, show on the sidebar and can win prizes.
  - **Who's in:** each event's card shows who has joined so far. A race or game nobody joined is called off, with a line in chat.
- **Countdown alerts:** before every event, a line in chat at 10, 5, 2 and 1 minutes, and at 30 seconds. Players who haven't joined get the join command; those who have get *You're in!*. Choose the times (anywhere from 30 minutes to 15 seconds) on the new tab. Players who come online while an event is coming up, or while a contest they could still join is on, are told about it.
- **Back-to-back nights:** **＋ Next** on a scheduled contest sets up another one straight after it, with a break you choose (0 to 30 minutes).
  - Each event is joined on its own: `/trigger join` joins the next event you're not in yet. Someone can play the first two and skip the rest.
  - Set each one to repeat weekly and the whole night comes back every week.
  - The Events page tucks each event of the night under the one before it.
- **Every message is yours to write:** **Play → Challenges → 📣 Joining** has every line Solstone sends about joining: the alerts (for players who haven't joined, players who have, and events everyone is in), what players see after joining, joining late, joining from the website, leaving, already in, too late, nothing to join, and *it has started, still time to join*.
  - They use the welcome message's & colour codes.
  - Fill-ins: `{event}`, `{left}` (like *5 minutes*), `{time}`, `{count}` (how many have joined), `{join}` and `{leave}` (the commands, clickable on Java), `{player}`, `{site}`.
  - A live preview shows each message as it will look, and **Back to Solstone's wording** puts the original text back.
  - Typing `/trigger join` into any welcome or reminder message makes it clickable on Java too.
- **The activity log can be searched and filtered:** **Manage → Activity log**.
  - **Filters:** search words (a command, a player's name), the kind of action (each one, or a whole group like *Player: all*), who did it, which server, a date range, and only failures. Newest or oldest first.
  - **Pages:** it shows 50 entries at a time with First, Newer/Older and Last buttons, so the page stays quick however long the log gets. Before, it showed only the newest 200.
  - **How long it's kept:** it has always kept everything. Now you choose: **Forever** (still the default), or 30 days, 90 days, 180 days, 1 year or 2 years. Older entries are deleted when you choose, and every hour after that. It says how many entries there are and the date of the first one.

# Solstone 1.10.6

- **Contests that repeat:** a contest's **Repeats** can be *every week* or *every day*. When it's over, the same contest (kind, length, prizes, everything) is put on again a week (or a day) after it started, so *Fishing night, Tuesdays 7:00* is set up once. Cancel it to stop. The Contests page marks them 🔁, and Events shows the next few.
- **Events is open to everyone:** visitors get an **Events** page in the top bar (contests, races, holidays, fireworks shows, announcements). Nothing with a player's name is on it: no birthdays, and no sign-ups.
- **See who's coming:** signed in, each event lists who has said *I'm coming!* under it (it was only a number, and names for admins).

# Solstone 1.10.5

- **Put posts in the order you want:** Website → Posts lists them by kind: **News**, **Guides** and **Questions**.
  - **Guides and questions** have **↑ ↓** buttons: the Help page and the home page show them in that order. New ones go at the end.
  - **News** goes by date, newest first, and each post now has a **Date** in its editor: change it to put a post where it belongs (or on the day of an event). The date is the one shown on the post.
  - **Pinned** posts still come first, whatever their date or place.

# Solstone 1.10.4

- **The top-down map no longer gets stuck when you zoom out fast:**
  - Zoomed-out pictures that were still filling in (their regions being drawn for the first time) are fetched again every few seconds, instead of staying half-empty or black until a reload.
  - While a zoom level loads, whatever was already loaded at other zoom levels stays on screen, so it never goes black.
  - At most a few pictures are fetched at a time, and asking again straight away gets the picture as it is, so zooming fast can't pile up work on the server or hold up the rest of the page.
  - The first time through a big world it says how far it's got: *Drawing the map… (40% of the world drawn so far: the first time takes a while)*. That happens once; after that, only changed regions are drawn again.
  - If loading the map's list of regions fails, it tries again instead of staying on *Loading the map…*.
  - The same on the home page's *Where everyone is*.

# Solstone 1.10.3

- **The home page stays tidy however many posts there are:** it shows the newest **3 news posts** and **4 guides**, then a **More news →** / **More guides and questions →** button to the full pages when there are more. Change how many (up to 12, or 0 to leave that part off) in Website → Site details.
- **The version at the bottom of every page:** *Made with Solstone 1.10.3* on the website, and *Solstone 1.10.3* under the signed-in pages, so you can see at a glance which version is running.

# Solstone 1.10.2

- **Reminders about the website, the way they should be** (Website → Welcome in the game → *Reminders about the website*):
  - **Every time they join**, if something's waiting for them (new messages, a vote they haven't voted in), a few seconds after the welcome message. Nothing if nothing's waiting, and not twice for a dropped connection.
  - **When a new message reaches them while they're playing**, straight away: from an admin, or a notice from Solstone (a vote's result, you won).
  - **While they keep playing with something still waiting**, the same reminder again **every 60 minutes** (you choose; 0 switches it off).
  - Two texts for those three: the *waiting* one (on joining, and the reminder) and the *new message* one.

# Solstone 1.10.1

## 🗺️ The top-down map zoomed out
- **Zooming out is quick now:** zoomed out, each picture covers 2×2, 4×4 and up to 32×32 regions instead of one, so a wide view of a big (Chunky-generated) world is a handful of pictures, not hundreds of full-size ones. They're made from the region pictures already drawn, kept, and made again only when a part of them changes. The same on the home page's *Where everyone is*.

## 🎣 Fishing stays vanilla with the Solstone pack
- **The pack no longer changes fishing:** no species, no renamed or described fish, no different odds. Cod, salmon, tropical fish and pufferfish are the game's own, and nothing extra is said in chat. Bedrock players (Geyser) fish exactly as before.
- **It just gives each fish a weight**, behind the scenes: a size for its kind (cod 1–12 lb, salmon 2–20 lb, tropical fish 0.2–1.5 lb, pufferfish 0.5–3 lb), big ones rarer, and a point a pound. Nothing is written on the item.
- **Contests use it:** during a *Fishing tournament* or *Biggest catch* you start, every catch is announced to everyone in chat with its weight (*≫ Tyler caught a Salmon · 15.5 lb · +16 points*), with the scoreboard on the side. Outside a contest, fishing is plain vanilla. The fishing journal on the website keeps every catch and its weight.
- **With the Tide mod installed**, the pack leaves fishing alone and contests use Tide's own catches (its fish, qualities and weights), as before.
- The pack is **version 12**: if you'd added an older one, download it again (or press *Install it in the world*) and load it. The *Test a catch* button is gone with the old fish tables.

- **Messages you've read stay read:** an admin opening a message now marks it read for the admins (a message an admin had sent to themselves kept its dot). Admins aren't offered *Write to the admins* any more: players' messages, and writing to them, are in Manage → Messages.
- **Tidying messages:** players can **remove** a conversation from their list (the admins keep it, and it comes back if someone writes in it again). Admins can **archive** one (it moves to *Archived* at the bottom, and comes back out if someone writes) or **delete** it for everyone. Notices (a vote closed, you won) delete themselves after 30 days.
- **Manage on phones is one dropdown** (*✉️ Messages (1)*) instead of rows of tabs.
- The *Write to players* form stays folded away until you open it.

# Solstone 1.10.0

## ⏰ Play time: bedtimes and screen time in one place
- **Manage → Play time** has everything about when the servers can be played, instead of bits in each server's Control, Announcements and Notifications.
- **Bedtime schedules:** each has its days, bedtime and wake-up time, and the servers it covers (tick **All servers**, or pick them). So school nights and weekends can be different: *School nights, Sun–Thu, 9 PM to 7 AM* and *Weekends, Fri–Sat, 10:30 PM to 8 AM*. A bedtime can be switched off without losing it. Under them it says which bedtimes each server has.
- The in-game warnings, the goodbye message and the countdown on the website are set there too.
- **Daily screen time:** what happens at the limit (warn them and notify you, or warn them then disconnect them after a few minutes), and **new: warnings before the limit** in the game (*Screen time: 15 minutes left today.*).
- **Each player** has one row: whether bedtime applies to them (or they stay up), a **daily limit** and a **weekend limit**, and how long they've played today (only admins see that).
- **One limit per person:** an account's Java and Bedrock names count together, so having both no longer means twice the time.
- Your settings move over by themselves: each server's bedtime becomes a schedule (servers with the same times share one), the stay-up lists and the limits from Notifications go into the players' rows.
- A server's Control shows its bedtimes with a link to Play time, the Users page shows each player's (*90 min a day · bedtime applies*), and Notifications points there for limits.

## 🗳️ Votes, build contests, event sign-ups and messages
Things for players to do on the website once signed in. Players pick, they don't write to each other: nothing a kid types is seen by other kids.
- **Votes** (account menu → 🗳️ Votes): admins start them in **Manage → Votes**: a question, the choices, when it closes (or close it yourself), and whether results show once someone has voted or only at the end. Everyone gets one vote and can change it until it closes. **Only totals are shown, never who voted for what**, not even to admins.
- **Build contests:** a vote where you say who built each entry (names from the game, with pictures if you like). **Nobody can vote for a build they made**, under any of their Minecraft names.
- **Voting in the game:** a new vote is announced in chat with its choices (click one on Java), and `!vote 2` in chat counts for the newest vote. It's the same vote as on the website, so nobody votes twice.
- **When a vote closes**, the result is announced in the game, everyone who voted gets a message with it, and the winning builders get a congratulations.
- A banner on the signed-in pages while a vote is open, counting down to when it closes.
- **I'm coming!** on Events: for contests, races, games and fireworks shows, with how many are coming. Admins see who (hover the button).
- **Messages** (account menu → ✉️ Messages): players write to the admins (an idea, something wrong, a question) and get your answers there; only the admins and that player see it, and players can't message each other. Admins see who wrote and answer in **Manage → Messages**, and can write to one player, several or every player (*You won the build contest!*). A number on the account button says when something's waiting. Notices from Solstone (a vote closed, you won) come here too.
- Get a phone notification when a player writes: Notifications → *A player sends a message* (on to start for new setups). Ten messages an hour per player at most.
- Removing an account removes its messages, votes and sign-ups too.
- **Reminders in the game, so the website isn't forgotten:** when a player joins and something's waiting for them on the website (new messages, a vote they haven't voted in), they get one line a few seconds after the welcome message: *✉ Waiting for you on the website: 2 new messages and a vote.* At most once every 12 hours (you choose), and never when nothing's waiting. When you write to someone who's playing right now, they get a heads-up straight away (at most every half hour). Change the wording or switch either off in **Website → Welcome in the game**, with the welcome message's colours and `{waiting}`, `{messages}`, `{votes}`, `{player}` and `{site}`.

## Smaller things
- **The top-down map draws what you're looking at first:** moving around a big world, the squares on your screen now come before ones you've scrolled past (those are dropped, and drawn when someone looks there again). Once someone opens a map, the rest of the world is drawn in the background, gently (one region at a time with a pause between), so after a while every square is ready and the map just shows. It's still one drawing at a time for everyone together, however many people have the map open.
- **Manage on phones** is just ⚙ in the bar, so the bar stays on one line. It's in the account menu too.
- **The map drawing check says when the world isn't finished:** for each region it checks, it counts the chunks the game only started (just the outline of the land, all air) and never finished, and says so: *r.-2.1.mca: 126 of 132 chunks were only started, never finished by the game. Run Chunky over this area again: it finishes them.* Those are black on every map, BlueMap's too.

# Solstone 1.9.10

- **No more blank pages while Solstone is busy:** a page that's slow to come (the server's disks busy with a map render or a backup, or Solstone just started) says **Loading…** straight away, and after 10 seconds *Still loading…* with **Try again**, instead of an empty page.
- **Just restarted?** Opening the app while Solstone isn't answering yet says *Waiting for Solstone…* and keeps trying every few seconds, then carries on, signed in. It used to show the sign-in page as if you'd been signed out.
- Pages open a little quicker: Solstone keeps its own page files in memory instead of reading them from disk each time.
- **Map drawing check, for black areas:** type the **X** and **Z** of a black spot and *Check* looks at just that spot: whether there's a region file there at all, and how its chunks draw. The report also starts with a **grid of the world's region files** (`#` a file, `.` none, `@` 0,0), so holes the world never generated or saved show up at a glance; these are black on every map, BlueMap's too.

# Solstone 1.9.9

- **Holiday countdown banners:** each holiday in Manage → Holidays has **Countdown banner [N] days before**. Set it to 7, say, and from a week ahead every page shows *🎃 Halloween is in 7 days* with a countdown, which turns into the holiday's message when the day comes. Leave it at 0 for just the usual banner on the day itself. No need to make a separate announcement. Weekly days don't have it.

# Solstone 1.9.8

- **🛠️ Planned maintenance:** Website → Site details → **Planned maintenance**: when it starts and ends, and a message (*Swapping in a faster drive. Your builds are safe!*). Every page shows a banner counting down to it. And while everything's off, the Cloudflare *website is down* page says **Down for maintenance, back around Saturday 3 PM**, with your message, instead of just "down" (and still shows whether each Minecraft server is up). Past the end time it says it's taking a little longer than planned. **Cancel the maintenance** takes it all away again.
- For the Cloudflare page to know, it needs the new Worker and somewhere to keep the notice: **download the Worker again** and paste it in, then add a free **KV namespace** to it bound as `SOLSTONE` (the steps are in Site details). Without it, everything else works as before, and Site details says why the page wasn't told.

# Solstone 1.9.7

- **Your join firework, your pick:** Fireworks (the editor page) has **When you join the server**: pick one of your own fireworks, or anyone's, and it goes off in everyone's sky when you join. Or leave it on *A random firework*. It covers both your Java and Bedrock names. Admins can still set anyone's in the firework show settings.
- **A limit on fireworks in the show:** besides how many each person can keep (20 to start), each person can have up to **5 in the show** at once, so everyone's turn up. Admins change both on the Fireworks page (*Each person can keep 20, with 5 in the show*); admins themselves have no limit. Saving one when your show spots are full keeps it, out of the show, and says so; the gallery shows *3 of 5 in the show*.
- **The Launch list is tidier:** **My fireworks** first, then **Made by players** as a row of names: pick someone to see theirs. Makers' names are only shown to people signed in; visitors get one plain list, so it's never a public list of players.
- **Holidays are simpler to edit:** a day shows its name, date and message; its colours, favourite kinds and scheduled show are folded away under **Fireworks for this day**. Easter's date option says *Easter Sunday (worked out each year)*.
- The web map through Solstone never lets a browser keep an empty map square, so squares drawn later show up.

# Solstone 1.9.6

- **Fewer stalls when the server's disks are busy:** the players list, the leaderboards and the home page's live section (who played this week, where they were) read players' files away from the part of Solstone that answers pages, so a slow disk (the mover, a backup) no longer holds up the whole website. More room for background work too.
- **A watchdog in the log:** if the website stops answering for more than a few seconds, Solstone's log says so (*The website has been held up for 12 s. It was busy with: …*) and when it's going again, and any page that takes over 5 seconds is logged (*Slow answer: …*). If it ever stalls again, those lines show why.

# Solstone 1.9.5

## One name per player
- **Your Minecraft name is your login:** making an account no longer asks for a username. You sign in with your Minecraft name (Java, or Bedrock with its dot) and the password you pick. Accounts made before keep their login.
- **Sign in with any of your Minecraft names:** with a Java and a Bedrock account linked, either name works, with the one password. The sign-in page says *Minecraft name or username*.
- **Players are shown by their Minecraft name:** on the website a player is always their in-game name, never a made-up one. With two linked, **My Minecraft accounts** (it was *My Minecraft players*) marks one **⭐ Main**, and **Make main** switches. Admins and Trusted accounts keep a display name of their own.
- The account menu says which login you're signed in with, and the guide to making an account explains linking Java and Bedrock.

## Players taken off the whitelist
- **Off the whitelist, off Solstone's lists:** with the whitelist on, someone no longer on it is left out of the players list, the leaderboards (and medals) and *who played*. Nothing is deleted: put them back on the whitelist and it all returns. Operators always count.
- Admins see *N no longer on the whitelist · Show them* under the players list, to look at them again (marked *Removed*).
- **Sign-ins in the activity log:** Manage → Activity log now shows each sign-in (*Signed in*, and with which name), not only failed ones.

## The web map from anywhere
- **Show the map through Solstone** (a server's ⚙ settings, under the map address): BlueMap, squaremap or Dynmap opens on the World tab from anywhere, not just at home, and only for people signed in who may see the map (Players only with *Players can see the map* on). The map itself stays on your home network: give its home address (like `http://192.168.1.10:8100`).
- **Walled off from the website:** the map runs in a sandbox, so nothing on it (a claim name, say) can reach anyone's account. Links to it carry a pass that runs out after 12 hours and stops at once if the map or a player's access is switched off.
- **Claims on the map:** with Flan's `bluemapIntegration` set to `true`, everyone's claims show on BlueMap.

# Solstone 1.9.4

- **Picture sizes in posts:** click on a picture's line in the text and pick **Picture size**: *Small*, *Medium*, *Large* or *Full width*. It's written into the text as `![Our castle|small](…)`, and the live view, Preview and the post all show it that size.
- **A card picture of its own:** Website → Posts → the editor's **Card picture**: *the first picture in the post* (as before), *a picture just for the card* (upload one; it isn't shown in the post's text), or *no picture*.

# Solstone 1.9.3

- **A card description for each post:** Website → Posts → the editor has **Card description**: a line or two shown under the title on the post's card (home page, News, Help), instead of the start of the post. Leave it empty for the start of the post, as before. Fill-ins like `{name}` work there too, and the templates start with the built-in guides' own card lines.
- **The firework show is on to start:** every page has the show going in the background straight away, with **sound still off** until someone turns it on. Anyone who switches the show off keeps it off (their browser remembers), and browsers set to reduce motion start with it off.
- **The top bar is complete straight away:** signed in, *Events*, *Servers* and *Manage* (and your name in the corner of the website) are there as the page opens, instead of popping in a moment later.
- **Banners line up with the page:** announcements and other banners on the Events, Servers and Manage pages sat off to one side on wide screens. They now line up with the page like on the home page.
- Website → Site details: the Cloudflare steps for the *website is down* page match Cloudflare's screens (*Start with Hello World*, a **Route** rather than a custom domain).

# Solstone 1.9.2

- **Contact email:** Website → Site details → **Contact email** (like contact@yourdomain). Where players and parents can reach you: account problems, questions, something stolen or broken. It shows at the bottom of every page (*Contact*) and in a **Contact** section on the Help page. `{contact}` puts it in any post (the toolbar's **Fill-in…** has it), and in the welcome message in the game. Without one, `{contact}` points to Discord, or says *an admin*.
- **A page for when the website is down:** Website → Site details → **If this website goes down** downloads a small Cloudflare Worker, filled in with the site's name, contact and servers, with the steps to add it (free on Cloudflare's free plan). When the website can't be reached (the computer's off, the tunnel's down, Solstone isn't running), visitors get a page with the site's name, your contact email and whether each Minecraft server is still up and how many are playing (never who), checked through mcsrvstat.us. Otherwise it changes nothing.
- Links in posts can be email links: `[write to us](mailto:you@example.com)`.

# Solstone 1.9.1

- **Manage → Holidays:** every holiday and special day in one list (New Year, Valentine's, St. Patrick's, Easter, 4th of July, Halloween, Thanksgiving, Christmas, the Friday night show and your own dates). Switch off the ones you don't celebrate and they're gone from the Events page, the message on every page and the fireworks. **Edit** changes a day's name, date, message, colours and show; **+ Add a date** adds your own. (It used to be the Calendar tab in the fireworks settings; that page links here now.)
- **Manage → Notifications is a page:** it opens like the other Manage tabs instead of in a pop-up, with the same settings.

# Solstone 1.9.0

## Mod updates
- **Which mods have a newer build:** a server's **Mods** page (admins) asks Modrinth about every mod, by each jar's fingerprint, and marks each one **⬆ 2.7.0 available** (with a link to that build), **✓ Up to date**, or **Not on Modrinth** (jars like Tide+, checked by hand). Only builds for the server's own Minecraft version and loader are offered. **Check again** asks right away; otherwise it's kept for an hour.
- **Geyser and Floodgate first:** when either has an update, a warning at the top says Bedrock players may not be able to join until it's updated.
- **A notification for new builds:** Notifications → *New builds of the server's mods* (off to start). Solstone checks every six hours and tells you once per new build, Geyser and Floodgate first.

## Guides and rules are posts now
- **Start a post from a template:** a new post in Website → Posts can start from **How to join the server**, **Making an account on this website** or **Server rules**: Solstone's wording, ready to make your own with the formatting toolbar and the live view. Pin it, unpublish it or preview it like any post.
- **Use as:** a post can be *the join guide*, *the guide to making an account* or *the server rules*. Everything that links there uses it: the home page's *Step-by-step guide*, the Ask to join form (and its rules box), and `{rules}` in the welcome message in the game. The join guide gets the Ask to join form under it. Only one post can be each; a draft doesn't stand in. Without one, Solstone's own wording shows, as before.
- **Fill-ins in every post:** `{java_address}`, `{bedrock_address}`, `{bedrock_port}`, `{java_version}`, `{name}`, `{discord}`, `{ask}` and `{rules}` work in all posts (the toolbar's **Fill-in…** puts one in). They're filled in from the main server's details, the first card on the home page, so posts stay right when an address, port or version changes. The live view and Preview show them filled in.
- **Guides you'd already rewritten move over by themselves:** each becomes a published post standing in for that guide, the first time the site is opened after the update.
- The **Rules and guides** tab is gone. Its *Ask to join* switch is in **Site details** now.

# Solstone 1.8.9

- **Which Minecraft version to play:** each server's card on the home page says it beside the Java address (*Minecraft 26.3*), and Bedrock says *newest version*. It's read from the world's own save, so it follows the server when it updates, and shows even while the server is off. The join guide says it too (*You need Minecraft 26.3*), with `{java_version}` for guides in your own words. When the version isn't known yet, the guide says *the version shown on the home page* instead.
- **Posts use the full width:** news posts, guides and the rules page now stretch across like the other panels (they were held to a narrow column).
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
