# Solstone 1.2.0

## A website at `/`
- **A public home page** anyone can open without signing in: how to join (the Java address, and the Bedrock address and port, each with a copy button), the public servers' live status, announcements, the latest news and guides, and an about section with your Discord link.
- **News, Guides and FAQ**: posts admins write in the app, each on its own page (`/news`, `/guides`, `/faq`, `/post/...`). FAQ answers open in place.
- **The signed-in app moves to `/app`.** Old `/#/...` links and bookmarks forward there. The status page has Home and Sign in links.

## Website page (admins, 🌐 in the sidebar)
- **Posts**: write a news post, guide or FAQ entry with simple formatting (headings, **bold**, *italic*, lists, links, quotes). Keep it as a draft until it's ready, and pin the important ones to the top.
- **Site details**: the site's name, tagline, Java and Bedrock addresses, Discord invite, the about text, and whether the home page shows the servers' live status.
- **Announcements** can also show on the home page (the ones already showing on the status page do).

## Private servers
- **Server settings → Private**: only admins see the server. It never shows on the website or the status page (not even in the firework feed), and signed-in players don't see it. Admins manage it as before, so a home server and a public server can share one Solstone and one sign-in.

## Bedrock players
- **Real skins for Bedrock players** joining through Geyser and Floodgate (heads, bodies and the firework face stamp), from GeyserMC's skin service by their Xbox ID.

## Releases
- **Image name**: `ghcr.io/magicsolstone/solstone` (it followed the GitHub rename). If your server still pulls `ghcr.io/tjusczak/solstone`, change the `image:` line.
- **One stable channel**: a new version on `main` publishes `latest`, `stable` and the version (`1.2.0`) and makes a GitHub release. There is no beta channel any more; changes are tested on a branch first.
