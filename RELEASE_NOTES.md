# Solstone 1.3.0

## Accounts for players
- **Three levels**: Player, Trusted and Admin. **Players** see the servers, who's on, CPU, RAM and TPS, the leaderboards, fishing and their own page. They never see anyone else's position, inventory, history or chat, or the World, Adventures and Chat tabs. **Trusted** is what "Viewer" was: everything read-only, plus chat. Existing viewers become Trusted, so nothing changes for them.
- **Players make their own account** (Users & activity → *Let players make their own account*, off until you turn it on). On the sign-in page they choose *Make an account*, type their Minecraft name while they're playing on a public server, get a six-digit code in the game chat that only they can see, and pick a login and password. Java and Bedrock both work. Your whitelist decides who can do it.
  - The page answers the same whether or not someone is online, so it can't be used to see who's playing. Codes last 10 minutes and take 5 tries; a player gets at most 3 codes an hour, so nobody can flood their chat.
- **Link any account to a player** from Users & activity, so a Player account has its own page.
- The server side refuses anything a Player account isn't meant to use, including routes added later, until they're added to the list on purpose.

## Your server's name everywhere
- The name from **Website → Site details** is the name on the sign-in page, the app's sidebar, page titles, the status page and the home page. Solstone is a small "Made with Solstone" line.

## Guides that are always there
- **How to join the server**: step by step for Java and Bedrock (phones, tablets, Windows, consoles), with your addresses and port, the dot in front of Bedrock names, consoles, and what to do when it won't let you in.
- **Making an account on this website**: the in-game code steps (or "ask an admin" while sign-up is off).
- Both are linked from the home page's join card and the sign-in page.

## Fixes
- **Bedrock skins**: skins with the classic (wide-arm) model showed as Steve. GeyserMC's "is_steve" flag means the arm model, not the default skin. The log now says why a skin is missing.
- **Private servers stay private**: their announcements, contests, races and games no longer show on the home or status page or under Coming up.

## Security
- Wrong passwords count per address, and per account from that address, so a stranger can't lock someone out of their account. There's still a high cap for any one account.
- A warning in the log when requests come through a proxy but `TRUST_PROXY_HEADERS` is off. HSTS is sent when Solstone is reached over HTTPS.
- **The status page's coordinates and map are now off until you turn them on.** Turning the status page on no longer shows where everyone is.
- Modpack links work for private servers again. The home page's server list is cached for 15 seconds, so lots of visitors don't each check every server.
