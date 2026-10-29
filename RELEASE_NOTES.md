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
