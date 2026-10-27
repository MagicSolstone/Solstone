"""Browser smoke test: start Solstone on a synthetic world, open every page in Chromium
and try the main interactive bits. Fails on any JavaScript error, any page that shows
"Something went wrong", and any Content-Security-Policy violation.

    python tests/e2e/smoke.py            (needs: pip install playwright; playwright install chromium)

Screenshots of each page land in $SMOKE_SHOTS (default: a temp folder) for a quick look.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
import helpers  # noqa: E402

H = {"X-Solstone": "1"}
ADMIN = {"username": "admin", "password": "admin-pass-123"}
# Failing image/icon loads are normal (no game files in the test world); real errors aren't.
IGNORED_CONSOLE = ("Failed to load resource", "net::ERR_", "favicon")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_app(root: Path, port: int) -> subprocess.Popen:
    env = {**os.environ,
           "SERVERS_DIR": str(root / "servers"), "DATA_DIR": str(root / "data"), "BACKUPS_DIR": str(root / "backups"),
           "DOWNLOAD_ASSETS": "false", "CRAFTY_URL": "", "CRAFTY_TOKEN": "", "RCON_HOST": "127.0.0.1", "RCON_TIMEOUT": "1",
           "ADMIN_USERNAME": ADMIN["username"], "ADMIN_PASSWORD": ADMIN["password"], "RECORDER_ENABLED": "false",
           "TZ": "America/Chicago"}
    log = open(root / "app.log", "w")
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=REPO, env=env,
                         stdout=log, stderr=subprocess.STDOUT)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            return p
        except Exception:
            if p.poll() is not None:
                break
            time.sleep(0.2)
    p.kill()
    print((root / "app.log").read_text())
    raise SystemExit("Solstone didn't start")


def seed_adventure(path: Path, sid: str) -> None:
    """A finished play session with two players walking about and a few things happening, for the Adventures pages."""
    import math
    import sqlite3
    c = sqlite3.connect(path)
    t0 = time.time() - 3 * 3600
    c.execute("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?)", (sid, "Tyler", t0, t0 + 3600, t0 + 3600))
    c.execute("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?)", (sid, "Gimli_Jr", t0 + 300, t0 + 3300, t0 + 3300))
    for i in range(0, 3600, 20):
        c.execute("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)",
                  (sid, t0 + i, "Tyler", "minecraft:overworld", 40 * math.cos(i / 400), 64, 40 * math.sin(i / 400) + i / 40))
        if 300 <= i <= 3300:
            c.execute("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)",
                      (sid, t0 + i, "Gimli_Jr", "minecraft:overworld", -i / 30, 70, 20 * math.sin(i / 300)))
    for dt, kind, who, msg in [(5, "join", "Tyler", "Tyler joined the game"), (300, "join", "Gimli_Jr", "Gimli_Jr joined the game"),
                               (900, "progress", "Tyler", "Tyler defeated 3 zombies, 1 skeleton · mined 2 diamond ore"),
                               (1500, "fish", "Gimli_Jr", "Gimli_Jr caught a Great Bluegill"), (2000, "death", "Tyler", "Tyler was slain by Zombie"),
                               (2400, "chat", "Gimli_Jr", "found a cave!")]:
        c.execute("INSERT INTO events(server_id, ts, type, player, message) VALUES (?,?,?,?,?)", (sid, t0 + dt, kind, who, msg))
    c.commit()
    c.close()


def main() -> int:
    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="solstone-smoke-"))
    shots = Path(os.environ.get("SMOKE_SHOTS") or root / "shots")
    shots.mkdir(parents=True, exist_ok=True)
    helpers.build(root)
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    app = start_app(root, port)
    seed_adventure(root / "data" / "solstone.db", helpers.SID)
    problems: list[str] = []
    sid, (pname, puuid) = helpers.SID, helpers.PLAYERS[0]
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get("SMOKE_CHROMIUM") or None)

            def page(width=1280, height=860):
                pg = browser.new_page(viewport={"width": width, "height": height})
                pg.add_init_script("""window.__csp = []; document.addEventListener('securitypolicyviolation',
                    (e) => window.__csp.push(e.violatedDirective + ' ' + (e.blockedURI || 'inline') + ' ' + (e.sourceFile || '') + ':' + e.lineNumber));""")
                pg.on("pageerror", lambda e: problems.append(f"{pg.url}: JS error: {e}"))
                pg.on("console", lambda m: m.type == "error" and not any(s in m.text for s in IGNORED_CONSOLE)
                      and problems.append(f"{pg.url}: console: {m.text}"))
                r = pg.request.post(f"{base}/api/auth/login", data=ADMIN, headers=H)
                assert r.ok, r.text()
                return pg

            def check(pg, name):
                for v in pg.evaluate("window.__csp || []"):
                    problems.append(f"{name}: CSP blocked {v}")
                if pg.locator("text=Something went wrong").count():
                    problems.append(f"{name}: page shows 'Something went wrong'")
                pg.screenshot(path=str(shots / f"{name}.png"))

            pg = page()
            hdrs = pg.request.get(f"{base}/").headers
            if "script-src 'self'" not in hdrs.get("content-security-policy", ""):
                problems.append("index: no Content-Security-Policy header")
            # turn on live server info so the home page shows it too
            pg.request.put(f"{base}/api/settings/status", data={"enabled": True, "show_positions": True}, headers=H)
            # the website: how to join, and a post of each kind
            pg.request.put(f"{base}/api/settings/site", data={"name": "Smoke SMP", "tagline": "A test server", "java_address": "play.example.net",
                                                              "bedrock_address": "play.example.net", "about": "We **fish** a lot."}, headers=H)
            for cat, title in (("news", "Welcome to the server"), ("guide", "How to join on Bedrock"), ("faq", "Can I play on my phone?")):
                pg.request.post(f"{base}/api/posts", data={"title": title, "category": cat,
                                                           "body": "# Heading\n\nSome **bold** text and a [link](/faq).\n\n- one\n- two"}, headers=H)

            # a news post with a picture
            import io as _io

            from PIL import Image as _Image
            _b = _io.BytesIO(); _Image.new("RGB", (320, 180), (60, 140, 220)).save(_b, "PNG")
            pic = pg.request.post(f"{base}/api/posts/images", data=_b.getvalue(), headers={**H, "Content-Type": "image/png"}).json()["url"]
            pg.request.post(f"{base}/api/posts", data={"title": "Our new castle", "category": "news",
                                                       "body": f"Look what we built!\n\n![The castle]({pic})\n\nCome and see it."}, headers=H)
            routes = {
                "home": "#/", "overview": f"#/s/{sid}", "player": f"#/s/{sid}/p/{puuid}",
                "player-stats": f"#/s/{sid}/p/{puuid}/stats", "player-history": f"#/s/{sid}/p/{puuid}/history", "player-fishing": f"#/s/{sid}/p/{puuid}/fishing",
                "player-advancements": f"#/s/{sid}/p/{puuid}/advancements", "world": f"#/s/{sid}/world",
                "control": f"#/s/{sid}/control", "check": f"#/s/{sid}/check", "chat": f"#/s/{sid}/chat", "challenges": f"#/s/{sid}/challenges", "races": f"#/s/{sid}/challenges/races", "games": f"#/s/{sid}/challenges/games", "performance": f"#/s/{sid}/performance",
                "leaderboards": f"#/s/{sid}/leaderboards", "fishing": f"#/s/{sid}/fishing", "fishing-player": f"#/s/{sid}/fishing/Tyler", "mods": f"#/s/{sid}/mods", "adventures": f"#/s/{sid}/adventures", "events": "#/events",
                "fireworks-editor": "#/fireworks", "fireworks-settings": "#/fireworks/show",
                "announcements": "#/manage/announcements", "admin": "#/manage/users", "manage-servers": "#/manage/servers",
                "manage-activity": "#/manage/activity", "website": "#/manage/website",
            }
            pg.goto(f"{base}/app"); pg.wait_for_timeout(1200)
            for name, hash_ in routes.items():
                pg.goto(f"{base}/app{hash_}"); pg.wait_for_timeout(1300)
                check(pg, name)

            # editing a saved picture firework with another tab of the controls open (the painter isn't on screen)
            pic = pg.request.post(f"{base}/api/fireworks", data={"name": "Smoke picture", "pattern": "picture", "colors": ["#ff0000", "#00ff00"],
                                                                 "picture": ["..00..", ".0110.", "..00.."]}, headers=H).json()
            pg.goto(f"{base}/app#/fireworks"); pg.wait_for_timeout(1000)
            for tab in ("colours", "sound", "look"):
                pg.evaluate(f"ed.tab = '{tab}'")
                pg.goto(f"{base}/app#/fireworks/{pic['id']}"); pg.wait_for_timeout(900)
                if pg.locator("text=Something went wrong").count():
                    problems.append(f"firework editor: editing a picture firework broke with the {tab} tab open")
                pg.goto(f"{base}/app#/fireworks"); pg.wait_for_timeout(600)

            # fireworks settings: every tab, then edit a show (copy a step)
            pg.goto(f"{base}/app#/fireworks/settings"); pg.wait_for_timeout(1200)
            for tab in pg.locator(".fws-tabs [data-tab]").all():
                tab.click(); pg.wait_for_timeout(300)
            pg.click('.fws-tabs [data-tab="shows"]'); pg.wait_for_timeout(300)
            edit = pg.locator(".fws-show-row [data-edit]")
            if edit.count():
                edit.first.click(); pg.wait_for_timeout(300)
                n = pg.locator(".fws-step[data-k]").count()
                pg.locator(".fws-step[data-k] [data-dup]").first.click(); pg.wait_for_timeout(300)
                if pg.locator(".fws-step[data-k]").count() != n + 1:
                    problems.append("show editor: copying a step didn't add one")
                pg.click(".fws-show-edit [data-cancel]"); pg.wait_for_timeout(300)
            check(pg, "fireworks-shows")

            # the fireworks launch list, and the give-items dialog
            pg.goto(f"{base}/app#/"); pg.wait_for_timeout(1000)
            pg.click(".fwbar [data-sky='pick']"); pg.wait_for_timeout(300)
            if pg.locator(".fw-pick .fwp-grid button").count() < 10:
                problems.append("fireworks: the launch list is missing its fireworks")
            pg.locator(".fw-pick .fwp-grid button").nth(2).click(); pg.wait_for_timeout(200)
            check(pg, "firework-launch-list")
            pg.mouse.click(5, 5); pg.wait_for_timeout(200)
            if pg.locator(".fw-pick:not([hidden])").count():
                problems.append("fireworks: the launch list didn't close")
            pg.goto(f"{base}/app#/s/{sid}/control"); pg.wait_for_timeout(1000)
            pg.evaluate(f"openGiveItem({sid!r}, {pname!r})"); pg.wait_for_timeout(500)
            if not pg.locator(".gv-modal").count():
                problems.append("give items: dialog didn't open")
            pg.fill("#gv-q", "a"); pg.wait_for_timeout(200)
            # picking an item shows what it does (the server's answer is faked here: there's no game running)
            tip = {"item": "x", "source": "game", "lines": [{"text": "Rod: +1 luck, +10% bite speed", "color": "#55FFFF"},
                                                             {"text": "Part of: Storm rig (1/3)", "color": "#FF55FF"}]}
            pg.route("**/assets/describe*", lambda r: r.fulfill(json=tip))
            pg.locator(".gv-item").first.click(); pg.wait_for_timeout(400)
            if "Storm rig" not in (pg.locator(".gv-desc").text_content() or ""):
                problems.append("give items: picking an item didn't show its description")
            check(pg, "give-items")
            pg.click(".gv-modal [data-close]")

            # an adventure replay: open the first session, jump to an event, screenshot
            pg.goto(f"{base}/app#/s/{sid}/adventures"); pg.wait_for_timeout(800)
            if not pg.locator(".rp-row").count():
                problems.append("adventures: no sessions listed")
            else:
                pg.locator(".rp-row").first.click(); pg.wait_for_timeout(1200)
                if not pg.locator("#rp-map canvas").count() or pg.locator(".rp-ev").count() < 5:
                    problems.append("adventures: replay didn't show the map and the feed")
                pg.locator(".rp-ev").nth(3).click(); pg.wait_for_timeout(300)
                check(pg, "adventure-replay")
                pg.fill("#rp-save input[name=title]", "Smoke test cave"); pg.click("#rp-save button[type=submit]"); pg.wait_for_timeout(800)
                if "Smoke test cave" not in (pg.locator(".section-head h2").first.text_content() or ""):
                    problems.append("adventures: saving didn't take")

            # the tackle guide (the game's answer is faked: no server is running)
            guide = {"live": True, "why": "", "fetched_at": time.time() - 90, "whens": {"THUNDER": "in a thunderstorm", "JUNGLE": "in jungles"},
                     "found": {"tide:copper_bobber": ["Tyler", "Gimli_Jr"]},
                     "rigs": [{"name": "Storm", "when": "THUNDER", "when_text": "in a thunderstorm", "two": "+8% bite speed in a thunderstorm",
                               "full": "+15% bite speed, +1 fishing luck in a thunderstorm", "members": ["tide:copper_bobber", "tide:storm_line", "tide:lightning_hook"]}],
                     "items": [{"id": "tide:copper_bobber", "name": "Copper Bobber", "category": "Bobbers", "when": ["THUNDER"], "rig": "Storm",
                                "lines": [{"text": "+5% hook window", "color": "#00AAAA"}, {"text": "+10% bite speed in a thunderstorm", "color": "#FF55FF"}, {"text": "Part of: Storm rig", "color": "#FF55FF"}],
                                "recipe": {"kind": "crafting", "width": 3, "height": 3, "slots": [[], ["minecraft:copper_ingot"], [], ["minecraft:copper_ingot"], ["minecraft:string"], ["minecraft:copper_ingot"], [], ["minecraft:copper_ingot"], []], "note": ""}},
                               {"id": "tide:bamboo_fishing_rod", "name": "Bamboo Fishing Rod", "category": "Rods", "when": ["JUNGLE"], "rig": "",
                                "lines": [{"text": "+5% casting range", "color": "#00AAAA"}, {"text": "+25% bite speed in jungles", "color": "#FF55FF"}],
                                "recipe": {"kind": "found", "width": 0, "height": 0, "slots": [], "note": "Found in jungle temple chests."}}]}
            pg.route("**/fishing/tackle", lambda r: r.fulfill(json=guide))
            pg.evaluate(f"openTackleGuide({sid!r})"); pg.wait_for_timeout(600)
            if pg.locator(".tg-card").count() != 2:
                problems.append(f"tackle guide: expected 2 items, saw {pg.locator('.tg-card').count()}")
            pg.select_option("#tg-when", "JUNGLE"); pg.wait_for_timeout(150)
            if pg.locator(".tg-card").count() != 1:
                problems.append("tackle guide: the place/time filter didn't filter")
            pg.select_option("#tg-when", ""); pg.wait_for_timeout(150)
            check(pg, "tackle-guide")
            pg.locator(".tg-tag.rig").first.click(); pg.wait_for_timeout(200)
            if "3+ pieces" not in (pg.locator(".tg-list").text_content() or ""):
                problems.append("tackle guide: the rig link didn't open the rig")
            check(pg, "tackle-guide-rigs")
            pg.click(".tg-modal [data-close]")

            # the public website, signed out
            anon = browser.new_page(viewport={"width": 1280, "height": 800})
            anon.add_init_script("window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + (e.blockedURI || 'inline')));")
            anon.on("pageerror", lambda e: problems.append(f"website: JS error: {e}"))
            # the public website, signed out
            for name, url in (("site-home", "/"), ("site-news", "/news"), ("site-help", "/help"),
                              ("site-post", "/post/welcome-to-the-server")):
                anon.goto(f"{base}{url}"); anon.wait_for_timeout(1200)
                check(anon, name)
            anon.goto(f"{base}/"); anon.wait_for_timeout(1200)
            if "play.example.net" not in (anon.locator(".hp-join").text_content() or ""):
                problems.append("home: the join addresses aren't shown")
            if anon.locator(".hp-post").count() < 1:
                problems.append("home: the latest news isn't shown")
            anon.goto(f"{base}/post/our-new-castle"); anon.wait_for_timeout(1000)
            if not anon.locator(".hp-body img.post-img").count():
                problems.append("post: its picture isn't shown")
            check(anon, "site-post-picture")
            anon.goto(f"{base}/"); anon.wait_for_timeout(1000)
            if not anon.locator(".hp-post .hp-post-pic").count():
                problems.append("home: a post's picture isn't on its card")
            anon.goto(f"{base}/post/welcome-to-the-server"); anon.wait_for_timeout(1000)
            if not anon.locator(".hp-body b").count() or not anon.locator(".hp-body li").count():
                problems.append("post: its Markdown wasn't formatted")
            anon.goto(f"{base}/#/coming-up"); anon.wait_for_timeout(1200)
            if "/app" not in anon.url:
                problems.append("home: an old /#/ link didn't forward to the app")
            anon.goto(f"{base}/faq"); anon.wait_for_timeout(1200)
            if not anon.url.endswith("/help#faq") or not anon.locator("#faq details").count():
                problems.append("help: /faq didn't lead to the questions on the Help page")
            anon.goto(f"{base}/guides/join"); anon.wait_for_timeout(1000)
            check(anon, "site-guide-join")
            if "play.example.net" not in (anon.locator(".hp-body").text_content() or "") or anon.title().find("Smoke SMP") < 0:
                problems.append("join guide: the addresses or the site name are missing")
            # asking to join from the guide
            pg.request.put(f"{base}/api/settings/site", data={"join_requests": True}, headers=H)
            anon.goto(f"{base}/"); anon.reload(); anon.wait_for_timeout(1200)
            if not anon.locator(".hp-join .hp-ask-btn").count():
                problems.append("home: no Ask to join button by the addresses")
            else:
                check(anon, "site-home-ask-button")
                anon.click(".hp-join .hp-ask-btn"); anon.wait_for_timeout(1200)
                if not anon.url.endswith("/guides/join#ask"):
                    problems.append("home: the Ask to join button didn't lead to the form")
            if not anon.locator("#ask-form").count() or not anon.locator('.hp-body a[href="#ask"]').count():
                problems.append("join guide: no Ask to join form (or link to it) with it turned on")
            else:
                anon.fill("#ask-form [name=player]", "Smoke_Kid"); anon.fill("#ask-form [name=note]", "Tyler's friend")
                anon.click("#ask-form button[type=submit]"); anon.wait_for_timeout(800)
                if not anon.locator(".hp-ask-done").count():
                    problems.append("join guide: asking to join didn't go through")
                check(anon, "site-guide-ask")
                pg.goto(f"{base}/app#/s/{sid}/control"); pg.wait_for_timeout(1800)
                if "Smoke_Kid" not in (pg.locator(".turned-away.asked").text_content() if pg.locator(".turned-away.asked").count() else ""):
                    problems.append("control: someone who asked to join isn't listed")
                pg.locator(".turned-away.asked").scroll_into_view_if_needed() if pg.locator(".turned-away.asked").count() else None
                check(pg, "control-asked")
                anon.goto(f"{base}/"); anon.wait_for_timeout(1200)
                if "waiting" not in (anon.locator("#ask-status").get_attribute("class") or ""):
                    problems.append("home: someone who asked doesn't see their request waiting")
                if "Request sent" not in (anon.locator("#ask-badge").text_content() if anon.locator("#ask-badge").count() else ""):
                    problems.append("home: no Request sent badge while waiting")
                check(anon, "site-home-waiting")
                pg.locator('.turned-away.asked [data-allow="Smoke_Kid"]').click(); pg.wait_for_timeout(300)
                pg.click("#cf-yes"); pg.wait_for_timeout(1200)
                anon.reload(); anon.wait_for_timeout(1500)
                if "in" not in (anon.locator("#ask-status").get_attribute("class") or "").split():
                    problems.append("home: someone let in doesn't see that they're in")
                if "in" not in (anon.locator("#ask-badge").get_attribute("class") or "").split():
                    problems.append("home: the badge didn't turn to You're in")
                anon.click("#ask-badge [data-ask-forget]"); anon.wait_for_timeout(200)
                if anon.locator("#ask-badge").count():
                    problems.append("home: closing the badge didn't close it")
                check(anon, "site-home-youre-in")
                pg.goto(f"{base}/app#/manage/website"); pg.wait_for_timeout(1000)
                pg.click('.fws-tabs [data-tab="guides"]'); pg.wait_for_timeout(400)
                pg.click('.ws-guide[data-guide="join"] [data-start]'); pg.wait_for_timeout(200)
                if "{java_address}" not in pg.locator('.ws-guide[data-guide="join"] textarea').input_value():
                    problems.append("website: Start from Solstone's wording didn't put the placeholders in")
                check(pg, "website-guides")
            # the guides in your own words
            pg.request.put(f"{base}/api/settings/site", data={"guide_account": "Hello from **{name}**, port {bedrock_port}."}, headers=H)
            anon.goto(f"{base}/guides/account"); anon.wait_for_timeout(900)
            if "Hello from Smoke SMP, port 19132." not in (anon.locator(".hp-body").text_content() or ""):
                problems.append("account guide: the admin's own wording wasn't used or filled in")
            pg.request.put(f"{base}/api/settings/site", data={"guide_account": ""}, headers=H)
            # sign-up from the sign-in page, and what a player account sees
            pg.request.put(f"{base}/api/settings/site", data={"signup": True}, headers=H)
            anon.goto(f"{base}/app"); anon.wait_for_timeout(1500)
            if "Smoke SMP" not in (anon.locator(".login-title h1").text_content() or ""):
                problems.append("sign-in: the site name isn't shown")
            if not anon.locator("#btn-signup").is_visible():
                problems.append("sign-in: no Make an account button with sign-up on")
            else:
                anon.click("#btn-signup"); anon.wait_for_timeout(400)
                check(anon, "signup")
                if not anon.locator("#su-start").count():
                    problems.append("sign-up: the form didn't open")
            u = pg.request.post(f"{base}/api/users", data={"username": "smoke_player", "password": "player-pass-1", "role": "player"}, headers=H).json()
            pg.request.patch(f"{base}/api/users/{u['id']}", data={"player": "Tyler"}, headers=H)
            pl = browser.new_page(viewport={"width": 1280, "height": 860})
            pl.on("pageerror", lambda e: problems.append(f"player account: JS error: {e}"))
            pl.request.post(f"{base}/api/auth/login", data={"username": "smoke_player", "password": "player-pass-1"}, headers=H)
            pl.goto(f"{base}/app#/s/{sid}"); pl.wait_for_timeout(1500)
            check(pl, "player-account-overview")
            tabs = pl.locator("nav[aria-label='Server sections']").text_content() or ""
            hrefs = " ".join(pl.eval_on_selector_all("nav[aria-label='Server sections'] a", "els => els.map(e => e.getAttribute('href'))"))
            if "World" in tabs or "/chat" in hrefs or "/adventures" in hrefs or pl.locator("nav[aria-label='Server sections'] a").count() < 2:
                problems.append(f"player account: wrong tabs ({tabs.strip()})")
            pl.goto(f"{base}/app#/s/{sid}/p/{puuid}"); pl.wait_for_timeout(1300)
            check(pl, "player-account-own-page")
            # signed in, the website offers the way back to the servers, and the app links back to the website
            pl.goto(f"{base}/"); pl.wait_for_timeout(1200)
            if not pl.locator(".hp-nav #btn-servers").is_visible() or not pl.locator(".hp-nav a[href='/app#/events']").is_visible() or pl.locator("#hp-signin").count():
                problems.append("home: no Servers and Events in the bar, or still Sign in, when signed in")
            if pl.locator(".hp-nav [data-admin]:not([hidden])").count():
                problems.append("home: a player sees Manage")
            pl.click("#hp-account"); pl.wait_for_timeout(300)
            if not pl.locator("#hp-account-menu a[href='/app#/fireworks']").is_visible():
                problems.append("home: no Fireworks in the account menu")
            check(pl, "site-home-signed-in")
            pg.goto(f"{base}/"); pg.wait_for_timeout(1200)
            if not pg.locator(".hp-nav [data-admin]").is_visible():
                problems.append("home: an admin doesn't see Manage")
            pg.goto(f"{base}/status"); pg.wait_for_timeout(800)
            if not pg.url.endswith("/#live"):
                problems.append("status: the old address doesn't lead to the home page's live section")
            pl.goto(f"{base}/app#/s/{sid}"); pl.wait_for_timeout(1200)
            if not pl.locator(".app-top .hp-nav a[href='/']").is_visible():
                problems.append("app: no link back to the website")
            # live on the home page, signed out: the old status page's screens, as tabs
            anon.goto(f"{base}/#live"); anon.wait_for_timeout(2500)
            check(anon, "site-home-live")
            if not anon.locator("#live:not([hidden])").count():
                problems.append("home: the live section isn't shown")
            tabs = anon.locator("#live .tv-dots [data-tv]")
            if tabs.count() < 2:
                problems.append("live: the screens aren't offered as tabs")
            else:
                tabs.nth(1).click(); anon.wait_for_timeout(500)
                if anon.locator(".tv-slide.on").count() != 1:
                    problems.append("live: picking a screen didn't show it")
                if not anon.locator("#hp-main .hp-join").count():
                    problems.append("live: picking a screen redrew the page")
                check(anon, "live-tab")
                feed = anon.locator(".tv-dots [data-tv='feed']")
                if feed.count():
                    feed.click(); anon.wait_for_timeout(500)
                    check(anon, "live-activity")
                    clipped = anon.evaluate("""() => { const s = document.querySelector('.tv-slide.on'); if (!s) return 'no slide';
                        for (let el = s; el && el !== document.body; el = el.parentElement) {
                          const cs = getComputedStyle(el); if (cs.overflowY !== 'visible' && el.scrollHeight > el.clientHeight + 2) return el.className; }
                        return ''; }""")
                    if clipped:
                        problems.append(f"live: Recent activity is cut off by {clipped}")
            # the map on the live section: drag to move around, then Reset view; the screens' names fit on one line
            anon.goto(f"{base}/#live"); anon.wait_for_timeout(2500)
            rows = anon.evaluate("() => new Set([...document.querySelectorAll('#live .tv-dots [data-tv]')].map(b => Math.round(b.getBoundingClientRect().top))).size")
            if rows > 1:
                problems.append(f"live: the screens' names take {rows} lines")
            if anon.locator("#live .tv-dots [data-tv='map']").count():
                problems.append("live: someone not signed in can see where everyone is")
            # a busy server: everyone's card, compact (the game's answer is made up here)
            def busy(route):
                b = json.loads(route.fetch().text())
                b["online_count"] = 4
                b["players"] = [{"name": n, "uuid": puuid, "health": h, "max_health": 20, "food": f, "xp_level": lv, "xp_progress": .4,
                                 "dimension": "minecraft:overworld", "held": {"id": "minecraft:diamond_sword", "name": "Diamond Sword", "count": 1}}
                                for n, h, f, lv in (("Tyler", 20, 18, 31), ("Gimli_Jr", 13, 20, 12), (".Steve_K", 7.5, 9, 4), ("MomCrafts", 20, 20, 50))]
                route.fulfill(json=b)
            anon.route(f"**/api/public/status/{sid}", busy)
            anon.set_viewport_size({"width": 1280, "height": 800}); anon.goto(f"{base}/#live"); anon.reload(); anon.wait_for_timeout(2500)
            anon.locator("#live .sp-players").scroll_into_view_if_needed() if anon.locator("#live .sp-players").count() else None
            check(anon, "live-busy")
            if anon.locator("#live .sp-player").count() != 4 or "❤️" not in (anon.locator("#live .sp-player").first.text_content() or ""):
                problems.append("live: the players' compact cards aren't shown")
            anon.unroute(f"**/api/public/status/{sid}")
            # signed in, the map is there: drag to move around, then Reset view
            pg.goto(f"{base}/#live"); pg.wait_for_timeout(2500)
            mp = pg.locator("#live .tv-dots [data-tv='map']")
            if not mp.count():
                problems.append("live: no map screen for an admin with positions on")
            else:
                mp.click(); pg.wait_for_timeout(1200)
                box = pg.locator("#sp-map canvas").bounding_box()
                pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2); pg.mouse.down()
                pg.mouse.move(box["x"] + box["width"] / 2 + 120, box["y"] + box["height"] / 2 + 60, steps=6); pg.mouse.up()
                pg.wait_for_timeout(300)
                if not pg.locator("#sp-map [data-reset]:not([hidden])").count():
                    problems.append("live map: dragging didn't move the view (no Reset view)")
                check(pg, "live-map-moved")
                pg.click("#sp-map [data-reset]"); pg.wait_for_timeout(1200)
                if pg.locator("#sp-map [data-reset]:not([hidden])").count():
                    problems.append("live map: Reset view stayed")
            anon.set_viewport_size({"width": 390, "height": 800}); anon.goto(f"{base}/#live"); anon.wait_for_timeout(2000)
            check(anon, "m-live")
            off = anon.evaluate("() => [...document.querySelectorAll('.tv-dots [data-tv]')].filter(b => b.getBoundingClientRect().right > innerWidth).length")
            if off:
                problems.append(f"phone live: {off} screen tabs run off the side")

            # phone width
            m = page(390, 800)
            for name, hash_ in (("m-overview", f"#/s/{sid}"), ("m-player", f"#/s/{sid}/p/{puuid}"), ("m-fireworks", "#/fireworks")):
                m.goto(f"{base}/app{hash_}"); m.wait_for_timeout(1200)
                check(m, name)
            m.goto(f"{base}/app#/s/{sid}/fishing"); m.wait_for_timeout(1000)
            check(m, "m-fishing")
            # Servers: a list with several servers, straight to the server with one
            m.goto(f"{base}/app#/events"); m.wait_for_timeout(1000)
            m.click("#btn-servers"); m.wait_for_timeout(600)
            if m.locator("#btn-servers .caret[hidden]").count():
                if f"#/s/{sid}" not in m.url:
                    problems.append("phone: with one server, Servers didn't go to it")
            else:
                if not m.locator("#rail-servers .rail-item").first.is_visible():
                    problems.append("phone: the server list didn't open")
                check(m, "m-menu")
                m.locator("#rail-servers .rail-item").last.click(); m.wait_for_timeout(800)
                if m.locator("#rail-servers:not([hidden])").count():
                    problems.append("phone: the server list stayed open after picking a server")
            # Manage is in the bar for admins on every page, and its tabs have no scrollbars
            if not m.locator(".app-nav [data-admin]").is_visible():
                problems.append("app: an admin doesn't see Manage in the bar")
            m.goto(f"{base}/app#/manage/users"); m.wait_for_timeout(1000)
            bars = m.evaluate("() => [...document.querySelectorAll('.tabs, .subtabs')].filter(t => t.offsetHeight - t.clientHeight > 2 || t.offsetWidth - t.clientWidth > 2).length")
            if bars:
                problems.append(f"manage: {bars} tab rows show a scrollbar")
            browser.close()
    finally:
        app.terminate()
        app.wait(timeout=10)
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in dict.fromkeys(problems):
            print("  -", p)
        print("\napp log:\n" + (root / "app.log").read_text()[-3000:])
        return 1
    print(f"Smoke test passed: {len(routes) + 6} pages, screenshots in {shots}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
