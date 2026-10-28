/* Solstone — the built-in guides: how to join the server, making an account on the website, and the rules. Admins can
   rewrite each one (Website → Guides); {java_address} and the other {placeholders} are filled in from Site details,
   so the guides stay right when an address or a port changes. Shared by the home page and the Website editor. */
"use strict";

const GUIDE_PLACEHOLDERS = [["name", "The site's name"], ["java_address", "Java address"], ["bedrock_address", "Bedrock address"],
  ["bedrock_port", "Bedrock port"], ["java_version", "The server's Minecraft version"], ["discord", "Discord invite link"], ["ask", "A link to the Ask to join form"],
  ["rules", "A link to the rules"], ["contact", "The contact email (Site details)"]];

const GUIDES = {
  join: {
    title: "How to join the server",
    excerpt: "Step by step on Java (PC) and Bedrock (phone, tablet, Windows, console).",
    body: (s) => {
      const java = s.java_address || "the address an admin gives you";
      const bed = s.bedrock_address || s.java_address || "the address an admin gives you";
      const ask = s.join_requests ? "Use the [Ask to join](#ask) form at the bottom of this page"
        : s.discord ? `Send your exact in-game name to an admin on [Discord](${s.discord})` : "Send your exact in-game name to an admin";
      return `${s.name} is a Minecraft server you can join from Java Edition or Bedrock Edition. Everyone plays together in the same world.

## First: get on the list
The server only lets in people on its list (the whitelist). Read [the rules](/guides/rules) first. ${ask}. On Bedrock that's your Xbox gamertag.

## Java Edition (Windows, Mac, Linux)
You need Minecraft **${s.java_version || "the version shown on the home page"}**. If the launcher plays a newer one, pick this version in its **Installations** tab.
1. Open Minecraft: Java Edition and choose **Multiplayer**.
2. Choose **Add Server**. Give it any name, and type **${java}** as the Server Address.
3. Choose **Done**, then pick the server and **Join Server**.

## Bedrock Edition (phone, tablet, Windows, Xbox, PlayStation, Switch)
1. Open Minecraft and choose **Play**, then the **Servers** tab.
2. Scroll down and choose **Add Server**.
3. Give it any name. Server Address: **${bed}**. Port: **${s.bedrock_port}**.
4. Choose **Save**, then join it. You sign in with your Microsoft (Xbox) account as usual.

Good to know on Bedrock:
- Keep Minecraft up to date: the server follows the newest Bedrock version, so an up-to-date game always works.
- Your name on the server starts with a dot, like *.Steve*. That's how the server tells Bedrock players apart, and it's the name to use on this website.
- Xbox, PlayStation and Switch don't have **Add Server** for outside servers. A common way round it is *BedrockConnect*: search for it to find the steps for your console. Or join from a phone, tablet or Windows PC instead.

## It won't let me in
- **"You are not white-listed"**: you're not on the list yet. ${ask}.
- **Can't connect / timed out**: check the address${s.bedrock_address ? " and port" : ""} for typos, and that the server is running${s.live ? " ([see it live](/#live))" : ""}.
- **Outdated client or server**: on Java, play Minecraft ${s.java_version || "the version shown on the home page"} (not newer, not older). On Bedrock, update Minecraft.`;
    },
  },
  account: {
    title: "Making an account on this website",
    excerpt: "See the servers, leaderboards and your own stats. Takes a minute, from inside the game.",
    body: (s) => s.signup ? `Your account here shows the servers, who's on, the leaderboards and your own page: your inventory and stats.

## Make one
1. Join the server and stay in the game (see [How to join](/guides/join)).
2. Go to [Sign in](/app) and choose **Make an account**.
3. Type your Minecraft name as it shows in the game. On Bedrock it starts with a dot, like *.Steve*.
4. A six-digit code appears in your game chat. Only you can see it, and it works for 10 minutes.
5. Type the code, then pick a username and password for this website. **Don't use your Microsoft password.**
6. If you like, add your first name (only the admins see it) and your birthday (for a birthday banner and fireworks).

## Good to know
- Each Minecraft player can have one account.
- Forgot your password? Ask an admin to set a new one.
- Never share your code or password. Admins will never ask for them.` : `Accounts on this website are made by an admin. Ask one for a login${s.discord ? ` on [Discord](${s.discord})` : ""}.`,
  },
  rules: {
    title: "Server rules",
    excerpt: "Be kind, leave other people's builds alone, and play fair.",
    body: (s) => `Everyone on ${s.name} plays in the same world, so these rules keep it fun for all of us.

## Be kind
- Be nice in chat. No mean words, no bullying, no spamming.
- Help new players. Everyone was new once.

## Leave other people's things alone
- Don't break, change or take anything you didn't build, unless the owner says it's OK.
- Don't open other people's chests without asking.
- No TNT, lava or fire near anyone else's builds.
- Build a little way away from other people, unless you're building together.

## Play fair
- No hacks, cheats, x-ray or mods that give you an advantage.
- No attacking other players unless you've both agreed to a game.
- Don't trap or trick people.

## Stay safe
- Never share your password, your address or other private things.
- If something's wrong, or someone makes you feel bad, tell an admin or a grown-up.

## If a rule gets broken
Admins can usually see who changed what, and put it back. Breaking the rules can mean a warning, or losing your place on the server.`,
  },
};

// {java_address} and the other fill-ins, in any post or guide: the main server's details from Site details (the
// first card on the home page), so the text stays right when an address, a port or the version changes.
// onJoinPage: {ask} jumps to the form further down that page; anywhere else it links to it.
// {contact}: the site's contact email as a link, or the next best way to reach an admin
function contactLink(site) {
  return site.contact ? `[${site.contact}](mailto:${site.contact})` : site.discord ? `[Discord](${site.discord})` : "an admin";
}
function fillPostVars(text, site, onJoinPage = false) {
  const vals = { name: site.name, java_address: site.java_address || "", bedrock_address: site.bedrock_address || site.java_address || "",
    bedrock_port: site.bedrock_port, java_version: site.java_version || "the version shown on the home page", discord: site.discord || "",
    ask: onJoinPage ? "[Ask to join](#ask)" : "[Ask to join](/guides/join#ask)", rules: "[the rules](/guides/rules)",
    contact: contactLink(site) };
  return String(text || "").replace(/\{(\w+)\}/g, (m, k) => (k in vals ? String(vals[k]) : m));
}

// The guide's text: the admin's own wording (from before guides moved to Posts) with the fill-ins done, or Solstone's.
function guideText(key, site) {
  const own = site[`guide_${key}`];
  if (!own) return GUIDES[key].body(site);
  return fillPostVars(own, site, key === "join");
}
// Solstone's wording with {placeholders} left in: where an admin starts from when rewriting a guide.
function guideTemplate(key, site) {
  const ph = Object.fromEntries(GUIDE_PLACEHOLDERS.map(([k]) => [k, `{${k}}`]));
  return GUIDES[key].body({ ...site, ...ph, bedrock_port: "{bedrock_port}", java_version: "{java_version}", join_requests: site.join_requests })
    .replace("[Ask to join](#ask) form", "{ask} form").replace("[the rules](/guides/rules)", "{rules}");
}
