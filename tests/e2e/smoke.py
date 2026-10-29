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
import threading
import time
import urllib.request
import functools
import http.server
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


def appear(pg, selector: str, n: int = 1, ms: int = 15000) -> bool:
    """Wait until at least n of these are on the page (a slow test machine can take a while), without failing here."""
    try:
        pg.wait_for_function("([s, n]) => document.querySelectorAll(s).length >= n", arg=[selector, n], timeout=ms)
        return True
    except Exception:
        return False


def start_app(root: Path, port: int) -> subprocess.Popen:
    env = {**os.environ,
           "SERVERS_DIR": str(root / "servers"), "DATA_DIR": str(root / "data"), "BACKUPS_DIR": str(root / "backups"),
           "DOWNLOAD_ASSETS": "false", "CRAFTY_URL": "", "CRAFTY_TOKEN": "", "RCON_HOST": "127.0.0.1", "RCON_TIMEOUT": "1",
           "ADMIN_USERNAME": ADMIN["username"], "ADMIN_PASSWORD": ADMIN["password"], "RECORDER_ENABLED": "false",
           "TZ": "America/Chicago",
           # every page here comes from one address, quicker than any visitor: the public limit (240 a minute) would
           # answer some with "Too many requests" (the sign-in page then hid Make an account). It has its own pytest.
           "PUBLIC_REQUESTS_PER_MINUTE": "0"}
    log = open(root / "app.log", "w")
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port),
                          # idle connections stay open a while: with uvicorn's 5 s, a request reusing one as it closes gets
                          # "socket hang up" (ECONNRESET), which failed a release once
                          "--timeout-keep-alive", "120"], cwd=REPO, env=env,
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
                "manage-activity": "#/manage/activity", "manage-whitelist": "#/manage/whitelist", "website": "#/manage/website",
                "manage-holidays": "#/manage/holidays", "manage-notifications": "#/manage/notifications",
            }
            pg.goto(f"{base}/app"); pg.wait_for_timeout(1200)
            for name, hash_ in routes.items():
                pg.goto(f"{base}/app{hash_}"); pg.wait_for_timeout(1300)
                check(pg, name)

            # a draft, previewed before anyone else can see it
            pg.goto(f"{base}/app#/manage/website"); pg.wait_for_timeout(1200)
            # posts grouped by kind; guides and questions move with ↑ ↓, news has a date in its editor
            for t in ("Smoke guide one", "Smoke guide two"):
                pg.request.post(f"{base}/api/posts", data={"title": t, "body": "x", "category": "guide"}, headers=H)
            pg.reload(); pg.wait_for_timeout(1200)
            if not pg.locator(".ws-kind:has-text('Guides')").count():
                problems.append("website: posts aren't grouped by kind")
            two = pg.locator('.ws-post:has-text("Smoke guide two") [data-move="up"]')
            if not two.count():
                problems.append("website: guides have no ↑ ↓")
            else:
                two.click(); pg.wait_for_timeout(1000)
                names = pg.locator(".ws-post b").all_text_contents()
                if names.index("Smoke guide two") > names.index("Smoke guide one"):
                    problems.append("website: ↑ didn't move the guide up")
            pg.click("#ws-new"); pg.wait_for_timeout(300)
            pg.fill("#ws-edit [name=title]", "Secret draft"); pg.fill("#ws-edit [name=body]", "Coming **soon**.")
            pg.uncheck("#ws-edit [name=published]")
            # the toolbar and the live view: select a word, make it a colour, add a subheading
            pg.evaluate("""() => { const t = document.querySelector('#ws-edit [name=body]'); t.focus(); t.setSelectionRange(0, 6); }""")
            pg.select_option("#ws-edit [data-style][aria-label=Colour]", "red"); pg.wait_for_timeout(200)
            pg.evaluate("""() => { const t = document.querySelector('#ws-edit [name=body]'); t.setSelectionRange(t.value.length, t.value.length); }""")
            pg.press("#ws-edit [name=body]", "Enter"); pg.press("#ws-edit [name=body]", "Enter"); pg.keyboard.type("Part two")
            pg.select_option("#ws-edit [data-line]", "## "); pg.wait_for_timeout(300)
            body = pg.locator("#ws-edit [name=body]").input_value()
            if "{red}Coming{/red}" not in body or "## Part two" not in body:
                problems.append(f"post editor: the toolbar didn't format the text ({body!r})")
            if not pg.locator(".ws-live .pf-red").count() or not pg.locator(".ws-live h3").count() or not pg.locator(".ws-live b").count():
                problems.append("post editor: the live view doesn't show the colour, subheading or bold")
            check(pg, "post-editor-toolbar")
            if (pg.locator("#ws-edit [data-save]").text_content() or "").strip() != "Save draft":
                problems.append("post editor: an unpublished post's button doesn't say Save draft")
            with pg.expect_popup() as pop:
                pg.click("#ws-edit [data-preview]")
            prev = pop.value; prev.wait_for_timeout(1500)
            if "Secret draft" not in (prev.locator(".hp-article").text_content() or "") or not prev.locator(".hp-body strong, .hp-body b").count():
                problems.append("post editor: Preview doesn't show the post as it'll look")
            check(prev, "post-preview"); prev.close()
            pg.fill("#ws-edit [name=body]", "Line one\nLine two\n\nNew paragraph"); pg.wait_for_timeout(300)
            if pg.locator(".ws-live p").count() != 2 or pg.locator(".ws-live p br").count() != 1:
                problems.append("post editor: one Enter isn't a new line, or a blank line isn't a new paragraph")
            # a picture's size, picked from the toolbar with the cursor on its line; the card's own picture
            pg.fill("#ws-edit [name=body]", "Hi\n\n![Our castle](/api/public/images/0123456789abcdef.png)\n\nBye")
            pg.evaluate("""() => { const t = document.querySelector('#ws-edit [name=body]'); t.focus(); t.setSelectionRange(10, 10); }""")
            pg.select_option("#ws-edit [data-picsize]", "small"); pg.wait_for_timeout(300)
            if "![Our castle|small](" not in pg.locator("#ws-edit [name=body]").input_value() or not pg.locator(".ws-live img.post-img-small").count():
                problems.append("post editor: Picture size didn't make the picture small")
            pg.select_option("#ws-edit [data-card-mode]", "own"); pg.wait_for_timeout(200)
            if pg.locator("#ws-edit [data-card-upload]").is_hidden():
                problems.append("post editor: choosing a picture just for the card doesn't offer an upload")
            check(pg, "post-editor-pictures")
            pg.click("#ws-edit [data-cancel]"); pg.wait_for_timeout(300)
            pg.goto(f"{base}/app#/s/{sid}/leaderboards"); pg.wait_for_timeout(1500)
            if not pg.locator(".board-group h2").count():
                problems.append("leaderboards: no headings for the kinds of board")
            n_all = pg.locator(".board").count()
            pg.uncheck("#lb-empty"); pg.wait_for_timeout(1200)
            if pg.locator(".empty-board").count() or pg.locator(".board").count() > n_all:
                problems.append("leaderboards: hiding empty boards didn't hide them")
            pg.check("#lb-empty"); pg.wait_for_timeout(1200)
            pg.click("#btn-account"); pg.click("#btn-my-players"); pg.wait_for_timeout(500)
            if not pg.locator("#mp-form").count():
                problems.append("account menu: My Minecraft players doesn't open")
            check(pg, "my-players"); pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
            pg.goto(f"{base}/app#/manage/users"); pg.wait_for_timeout(1200)
            pg.locator("[data-link]").first.click(); pg.wait_for_timeout(1200)
            if not pg.locator("#link-pills [data-pick], #link-pills .muted").count():
                problems.append("users: the link dialog doesn't offer players to pick")
            check(pg, "users-link-players"); pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
            pg.goto(f"{base}/app#/manage/servers"); pg.wait_for_timeout(1200)
            if not pg.locator("#clear-form [name=what]").count():
                problems.append("manage: no Clear saved history")
            pg.goto(f"{base}/app#/s/{sid}/mods"); pg.wait_for_timeout(1500)
            appear(pg, "#mod-updates button, #mod-updates .mod-bedrock", 1, 20000)
            if not pg.locator("#mod-updates").count():
                problems.append("mods: no update check for admins")
            if not pg.locator("[data-mrpack]").count() or not pg.locator("[data-mp-public]").count():
                problems.append("mods: no .mrpack download or website switch")
            else:
                pg.locator("[data-mrpack]").scroll_into_view_if_needed(); check(pg, "mods-modpack")
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

            # a banner on an app page lines up with the page (it sat at the left edge on wide screens)
            pg.request.put(f"{base}/api/board", data={"items": [{"text": "Smoke banner", "emoji": "🎬"}]}, headers=H)
            pg.set_viewport_size({"width": 1920, "height": 900})
            pg.goto(f"{base}/app#/events"); pg.reload()         # the banners load with the page
            if appear(pg, "#app-board .bn"):
                bn, mn = pg.locator("#app-board .bn").first.bounding_box(), pg.locator("main#view h1").first.bounding_box()
                if abs(bn["x"] - mn["x"]) > 2:
                    problems.append(f"banners: an app page's banner starts at {bn['x']:.0f}px, the page at {mn['x']:.0f}px")
            else:
                problems.append("banners: an announcement doesn't show on the app's pages")
            pg.request.put(f"{base}/api/board", data={"items": []}, headers=H)
            pg.set_viewport_size({"width": 1280, "height": 860})
            # the web map through Solstone: in a walled-off frame, where a map's own code still has storage and its
            # files, but no reach into Solstone (a claim name on the map could be anything)
            mapdir = Path(tempfile.mkdtemp(prefix="smoke-map-"))
            (mapdir / "settings.json").write_text('{"maps":["world"]}')
            (mapdir / "index.html").write_text("""<!doctype html><html><head><title>map</title></head><body><div id="out">starting</div><script>
              (async () => { const o = [];
                try { localStorage.setItem("k", "1"); o.push("storage:" + localStorage.getItem("k")); } catch (e) { o.push("storage:" + e.name); }
                try { o.push("files:" + (await (await fetch("settings.json")).json()).maps[0]); } catch (e) { o.push("files:failed"); }
                try { o.push("solstone:" + (parent.document.title ? "reached" : "reached") + document.cookie); } catch (e) { o.push("solstone:blocked"); }
                document.getElementById("out").textContent = o.join(" "); })();</script></body></html>""")
            map_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(mapdir)))
            threading.Thread(target=map_srv.serve_forever, daemon=True).start()
            pg.request.put(f"{base}/api/servers/{sid}/settings", data={"map_url": f"http://127.0.0.1:{map_srv.server_address[1]}", "map_proxy": True}, headers=H)
            pg.goto(f"{base}/app#/s/{sid}/world"); pg.wait_for_timeout(1200)
            pg.click('[data-wm="web"]'); pg.wait_for_timeout(2500)
            frame = next((f for f in pg.frames if "/map/" in f.url), None)
            got = (frame.locator("#out").text_content() or "") if frame else ""
            if got != "storage:1 files:world solstone:blocked":
                problems.append(f"web map: the map through Solstone isn't walled off and working ({got or 'no frame'})")
            check(pg, "world-web-map")
            pg.click('[data-wm="own"]')
            pg.request.put(f"{base}/api/servers/{sid}/settings", data={"map_url": "", "map_proxy": ""}, headers=H)
            map_srv.shutdown()
            # The top-down map: zooming all the way out fast mustn't leave it stuck black
            pg.goto(f"{base}/app#/s/{sid}/world"); pg.wait_for_timeout(1500)
            cvs = pg.locator("#wm-own canvas")
            if cvs.count():
                cvs.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
                box = cvs.bounding_box()
                scale0 = pg.evaluate("() => window.scrollY")
                pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                for _ in range(25):
                    pg.mouse.wheel(0, 400)                         # out, out, out
                pg.wait_for_timeout(6000)
                note = pg.locator("#wm-own .rm-note").text_content() or ""
                lit = pg.evaluate("""() => { const c = document.querySelector('#wm-own canvas'), x = c.getContext('2d');
                    const d = x.getImageData(0, 0, c.width, c.height).data; let n = 0;
                    for (let i = 0; i < d.length; i += 4 * 97) if (d[i] + d[i + 1] + d[i + 2] > 120) n++; return n; }""")
                if pg.evaluate("() => window.scrollY") != scale0:
                    problems.append("top-down map: the mouse wheel scrolled the page instead of zooming the map")
                if "Loading the map" in note or not lit:
                    problems.append(f"top-down map: stuck after zooming out fast ({note or 'no note'}, {lit} lit pixels)")
                check(pg, "world-zoomed-out")

            # Manage → Notifications is a page (not a popup), Manage → Holidays switches days on and off
            pg.goto(f"{base}/app#/manage/notifications"); pg.wait_for_timeout(1200)
            if not pg.locator("#notify-form").count() or pg.locator("#modal-root .modal").count():
                problems.append("manage: Notifications isn't shown as a page")
            pg.goto(f"{base}/app#/manage/holidays"); pg.wait_for_timeout(1200)
            if pg.locator(".fws-cal-row").count() < 5:
                problems.append("manage: Holidays doesn't list the holidays")
            else:
                row = pg.locator('.fws-cal-row:has-text("Thanksgiving")')
                row.locator("[data-en]").uncheck(); pg.wait_for_timeout(800)
                if not pg.locator('.fws-cal-row.off:has-text("Thanksgiving")').count():
                    problems.append("manage: switching Thanksgiving off didn't stick")
                pg.locator('.fws-cal-row:has-text("Thanksgiving") [data-en]').check(); pg.wait_for_timeout(800)
                pg.locator('.fws-cal-row:has-text("Halloween") [data-edit]').click(); pg.wait_for_timeout(300)
                if not pg.locator(".fws-cal-edit").count():
                    problems.append("manage: a holiday doesn't open for editing")
                elif pg.locator(".fws-cal-edit .fws-more[open]").count() or not pg.locator(".fws-cal-edit .fws-more").count():
                    problems.append("manage: a holiday's fireworks details aren't folded away to start")

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
            pg.request.put(f"{base}/api/servers/{sid}/settings", data={"join_address": "mods.example.net:25566", "join_note": "Needs the modpack", "join_mods": True}, headers=H)
            def running(route):                  # the server as if it were up (there's no game here)
                d = json.loads(route.fetch().text())
                up = {"running": True, "online": 3, "max": 10, "tps": 19.9, "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 3 * 3600 - 600))}
                for x in d.get("servers", []):
                    x.update(up)
                for j in d.get("joins", []):
                    j["status"] = {**(j.get("status") or {}), **up}
                route.fulfill(json=d)
            anon.route("**/api/public/site", running)
            anon.goto(f"{base}/"); anon.reload(); anon.wait_for_timeout(1200)
            anon.locator(".hp-mods summary").first.click() if anon.locator(".hp-mods summary").count() else None
            if "Online" not in (anon.locator(".hp-join").text_content() or ""):
                problems.append("home: the join box doesn't say the server is online")
            if "mods.example.net:25566" not in (anon.locator(".hp-join .hp-join-card").text_content() if anon.locator(".hp-join .hp-join-card").count() else ""):
                problems.append("home: a second server's own join address isn't shown")
            check(anon, "site-home-two-servers")
            anon.unroute("**/api/public/site")
            pg.request.put(f"{base}/api/servers/{sid}/settings", data={"join_address": "", "join_note": "", "join_mods": False}, headers=H)
            anon.reload(); anon.wait_for_timeout(1000)
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
                anon.check("#ask-form [name=rules]")
                anon.click("#ask-form button[type=submit]"); anon.wait_for_timeout(800)
                if not anon.locator(".hp-ask-done").count():
                    problems.append("join guide: asking to join didn't go through")
                check(anon, "site-guide-ask")
                pg.goto(f"{base}/app#/s/{sid}/control"); pg.wait_for_timeout(1800)
                if "Smoke_Kid" not in (pg.locator(".turned-away.asked").text_content() if pg.locator(".turned-away.asked").count() else ""):
                    problems.append("control: someone who asked to join isn't listed")
                pg.locator(".turned-away.asked").scroll_into_view_if_needed() if pg.locator(".turned-away.asked").count() else None
                check(pg, "control-asked")
                pg.goto(f"{base}/app#/manage/whitelist"); pg.wait_for_timeout(1500)
                if not pg.locator('.wl-req [data-let="Smoke_Kid"]').count():
                    problems.append("whitelist page: someone who asked to join has no Let in button")
                if not pg.locator(".wl-grid .panel").count():
                    problems.append("whitelist page: no list for each server")
                check(pg, "manage-whitelist-asked")
                pg.goto(f"{base}/app#/s/{sid}/control"); pg.wait_for_timeout(1500)
                anon.goto(f"{base}/"); anon.wait_for_timeout(1200)
                if "waiting" not in (anon.locator("#ask-status").get_attribute("class") or ""):
                    problems.append("home: someone who asked doesn't see their request waiting")
                if "Request sent" not in (anon.locator("#ask-badge").text_content() if anon.locator("#ask-badge").count() else ""):
                    problems.append("home: no Request sent badge while waiting")
                check(anon, "site-home-waiting")
                # no game here to run the command: Let them in says so, and the request stays waiting
                pg.locator('.turned-away.asked [data-allow="Smoke_Kid"]').click(); pg.wait_for_timeout(300)
                pg.click("#cf-yes"); pg.wait_for_timeout(1500)
                anon.reload(); anon.wait_for_timeout(1200)
                if "waiting" not in (anon.locator("#ask-status").get_attribute("class") or ""):
                    problems.append("home: a request that couldn't be let in shows as let in")
                # let in from the game instead (their name on the whitelist): the page notices
                wl = root / "servers" / sid / "whitelist.json"
                wl.write_text(json.dumps([{"uuid": "00000000-0000-0000-0000-000000000001", "name": "Smoke_Kid"}]))
                anon.reload(); anon.wait_for_timeout(1500)
                if "in" not in (anon.locator("#ask-status").get_attribute("class") or "").split():
                    problems.append("home: someone let in doesn't see that they're in")
                if "in" not in (anon.locator("#ask-badge").get_attribute("class") or "").split():
                    problems.append("home: the badge didn't turn to You're in")
                anon.click("#ask-badge [data-ask-forget]"); anon.wait_for_timeout(200)
                if anon.locator("#ask-badge").count():
                    problems.append("home: closing the badge didn't close it")
                check(anon, "site-home-youre-in")
                wl.unlink()
                # asked again, and an admin says no: off the list, and their page says so
                t = anon.request.post(f"{base}/api/public/join-request", data={"rules": True, "player": "Nope_Kid"}, headers={"X-Solstone": "1"}).json()["token"]
                anon.evaluate("t => localStorage.setItem('solstone-ask', JSON.stringify({token: t, player: 'Nope_Kid', at: Date.now()}))", t)
                pg.goto(f"{base}/app#/manage/whitelist"); pg.wait_for_timeout(1500)
                if not pg.locator('.wl-req [data-deny="Nope_Kid"]').count():
                    problems.append("whitelist page: no Deny button on a request")
                else:
                    pg.locator('.wl-req [data-deny="Nope_Kid"]').click(); pg.wait_for_timeout(300)
                    pg.click("#cf-yes"); pg.wait_for_timeout(1500)
                    if pg.locator('.wl-req [data-deny="Nope_Kid"]').count():
                        problems.append("whitelist page: a denied request is still listed")
                anon.reload(); anon.wait_for_timeout(1500)
                if "denied" not in (anon.locator("#ask-badge").get_attribute("class") or "").split():
                    problems.append("home: someone denied doesn't see that their request wasn't accepted")
                check(anon, "site-home-denied")
                anon.click("#ask-badge [data-ask-forget]"); anon.wait_for_timeout(200)
                pg.goto(f"{base}/app#/manage/website"); pg.wait_for_timeout(1000)
                pg.click('.fws-tabs [data-tab="site"]'); pg.wait_for_timeout(800)
                if not pg.locator(".ws-join").count():
                    problems.append("website: no join details for each server in Site details")
                pg.wait_for_timeout(500)
                if pg.locator('#ws-site [name="java_address"]').count():
                    problems.append("website: the old main address fields are still there")
                if pg.locator('.ws-join [data-j="join_address"]').first.input_value() != "play.example.net":
                    problems.append("website: the old main address didn't move to the first server")
                pg.locator(".ws-joins").scroll_into_view_if_needed() if pg.locator(".ws-joins").count() else None
                pg.locator('.ws-join input[name="main_server"]').first.check()
                pg.evaluate("""() => { const c = document.querySelector('.ws-join [data-j="join_color"]'); c.value = '#4cd964'; c.dispatchEvent(new Event('input')); }""")
                pg.locator('.ws-join [data-j="join_note"]').first.fill("Our survival world for the whole family.")
                check(pg, "website-joins")
                pg.fill('#ws-site [name="contact"]', "contact@example.net")
                if not pg.locator('.ws-offline a[href="/api/settings/site/offline-worker"]').count():
                    problems.append("website: no download for the Cloudflare offline page")
                if not pg.locator("#ws-maint-form [name=start]").count():
                    problems.append("website: no Planned maintenance in Site details")
                pg.click('#ws-site button[type="submit"]'); pg.wait_for_timeout(1500)
                anon.goto(f"{base}/"); anon.reload(); anon.wait_for_timeout(1200)
                if "main" not in (anon.locator(".hp-join-card").first.get_attribute("class") or "").split() or "survival world" not in (anon.locator(".hp-join-card.main").text_content() or ""):
                    problems.append("home: the main server isn't first, or its About text is missing")
                if anon.locator(".hp-hero").count():
                    problems.append("home: the big name shows with Show the name big off")
                check(anon, "site-home-main-server")
                if anon.locator("#hp-foot-contact").is_hidden() or "mailto:contact@example.net" not in (anon.locator("#hp-foot-contact a").get_attribute("href") or ""):
                    problems.append("home: the footer doesn't link the contact email")
                anon.goto(f"{base}/help"); anon.wait_for_timeout(1200)
                if "contact@example.net" not in (anon.locator("#contact").text_content() if anon.locator("#contact").count() else ""):
                    problems.append("help: no Contact section with the email")
                check(anon, "site-help-contact")
            # a guide from a template, standing in for the built-in join guide, with its fill-ins done on the page
            pg.goto(f"{base}/app#/manage/website"); pg.wait_for_timeout(1200)
            pg.click('.fws-tabs [data-tab="posts"]'); pg.wait_for_timeout(400)
            pg.click("#ws-new"); pg.wait_for_timeout(300)
            pg.select_option("#ws-edit [data-template]", "join"); pg.wait_for_timeout(300)
            if "{java_address}" not in pg.locator("#ws-edit [name=body]").input_value() or pg.locator("#ws-edit [name=role]").input_value() != "join":
                problems.append("post editor: the join guide template didn't fill in (with its fill-ins) or set Use as")
            if "{java_address}" in (pg.locator(".ws-live").text_content() or ""):
                problems.append("post editor: the live view shows {java_address} instead of the address")
            check(pg, "post-template")
            if not pg.locator("#ws-edit [name=summary]").input_value():
                problems.append("post editor: the template didn't fill in the card description")
            pg.fill("#ws-edit [name=body]", "Hello from **{name}**, port {bedrock_port}. {ask}")
            pg.fill("#ws-edit [name=summary]", "Our own words for {name}'s card")
            pg.click("#ws-edit [data-save]"); pg.wait_for_timeout(1200)
            anon.goto(f"{base}/help"); anon.wait_for_timeout(1200)
            if not anon.locator(".hp-post:has-text(\"Our own words for Smoke SMP's card\")").count():
                problems.append("help: a guide's card doesn't show its own card description")
            check(anon, "help-card-description")
            anon.goto(f"{base}/guides/join"); anon.wait_for_timeout(1200)
            if "Hello from Smoke SMP, port 19132." not in (anon.locator(".hp-body").text_content() or ""):
                problems.append("join guide: the post standing in for it wasn't shown, or its fill-ins weren't done")
            for x in pg.request.get(f"{base}/api/posts", headers=H).json()["posts"]:
                if x.get("role") == "join":
                    pg.request.delete(f"{base}/api/posts/{x['id']}", headers=H)
            # the rules page, and a welcome message in the game
            anon.goto(f"{base}/guides/rules"); anon.wait_for_timeout(900)
            if "Leave other people's things alone" not in (anon.locator(".hp-body").text_content() or ""):
                problems.append("rules: the rules page doesn't show Solstone's rules")
            check(anon, "site-rules")
            anon.goto(f"{base}/guides/join"); anon.wait_for_timeout(900)
            if "You need Minecraft" not in (anon.locator(".hp-body").text_content() or ""):
                problems.append("join guide: it doesn't say which Minecraft version to play")
            pg.goto(f"{base}/app#/manage/website"); pg.wait_for_timeout(1000)
            pg.click('.fws-tabs [data-tab="welcome"]'); pg.wait_for_timeout(1200)
            wel = pg.locator(".ws-wel").first
            if not wel.count():
                problems.append("website: no welcome message for a server")
            else:
                wel.locator("[data-start]").click(); pg.wait_for_timeout(200)
                wel.locator('.wel-col[data-code="&c"]').click(); pg.keyboard.type("red bit"); pg.wait_for_timeout(200)
                if "color:#ff5555" not in (wel.locator(".wel-preview").inner_html() or "") or "Steve" not in (wel.locator(".wel-preview").text_content() or ""):
                    problems.append("website: the welcome preview doesn't show colours or fill in {player}")
                wel.locator("button[type=submit]").click(); pg.wait_for_timeout(600)
                saved = pg.request.get(f"{base}/api/servers/{sid}/settings", headers=H).json()
                if saved.get("welcome_when") != "first" or "&cred bit" not in (saved.get("welcome") or ""):
                    problems.append("website: the welcome message didn't save")
                check(pg, "website-welcome")
            nf = pg.locator("#ws-nudge")
            if not nf.count() or "2 new messages and a vote" not in (nf.locator(".wel-preview").first.text_content() or ""):
                problems.append("website: the reminder about the website isn't there, or its preview doesn't fill in {waiting}")
            else:
                nf.locator("[name=repeat_minutes]").fill("90"); nf.locator("button[type=submit]").click(); pg.wait_for_timeout(600)
                if pg.request.get(f"{base}/api/settings/nudge", headers=H).json().get("repeat_minutes") != 90:
                    problems.append("website: the reminder settings didn't save")
            # sign-up from the sign-in page, and what a player account sees
            pg.request.put(f"{base}/api/settings/site", data={"signup": True}, headers=H)
            anon.goto(f"{base}/app"); anon.wait_for_timeout(1000)
            try:
                anon.wait_for_selector("#btn-signup", state="visible", timeout=15000)
            except Exception:
                pass                                         # reported just below
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
            # a player is shown by their Minecraft name, and has no display name of their own to pick
            pl.click("#btn-account"); pl.wait_for_timeout(300)
            if (pl.locator("#account-name").text_content() or "").strip() != "Tyler" or pl.locator("#btn-display-name").is_visible():
                problems.append("player account: not shown as their Minecraft name, or offered a display name")
            if "signed in as smoke_player" not in (pl.locator("#account-role").text_content() or ""):
                problems.append("player account: the menu doesn't say which login they're signed in with")
            pl.keyboard.press("Escape")
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
            anon.goto(f"{base}/#live"); anon.wait_for_timeout(1000)
            appear(anon, "#live .tv-dots [data-tv]", 2)
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
            anon.set_viewport_size({"width": 1280, "height": 800}); anon.goto(f"{base}/#live"); anon.reload(); anon.wait_for_timeout(1000)
            appear(anon, "#live .sp-player", 4)
            anon.locator("#live .sp-players").scroll_into_view_if_needed() if anon.locator("#live .sp-players").count() else None
            check(anon, "live-busy")
            if anon.locator("#live .sp-player").count() != 4 or "❤️" not in (anon.locator("#live .sp-player").first.text_content() or ""):
                problems.append("live: the players' compact cards aren't shown")
            anon.unroute(f"**/api/public/status/{sid}")
            # a web map (BlueMap) is never on the home page, only on a server's World tab (signed in)
            pg.request.put(f"{base}/api/servers/{sid}/settings", data={"map_url": "http://192.168.1.10:8100"}, headers=H)
            pg.goto(f"{base}/#live"); pg.reload(); pg.wait_for_timeout(2500)
            if pg.locator("iframe").count() or pg.locator("#live .tv-dots [data-tv='web']").count():
                problems.append("live: the web map is on the home page")
            pg.request.put(f"{base}/api/servers/{sid}/settings", data={"map_url": ""}, headers=H)
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
            if m.viewport_size["width"] <= 700 and m.locator(".app-nav [data-nav=manage] .nav-label").is_visible():
                problems.append("phone: Manage in the bar still has its word (it should be just ⚙)")
            # Manage → Play time: bedtimes with their own days and servers, and each player's row
            m.goto(f"{base}/app#/manage/playtime"); m.wait_for_timeout(1200)
            if not m.locator(".pt-people tr[data-key]").count():
                problems.append("play time: no player rows")
            m.locator("#pt-add").click(); m.wait_for_timeout(200)
            if not m.locator(".pt-rule").count():
                problems.append("play time: + Add a bedtime added nothing")
            m.locator(".pt-people tr[data-key] [name=limit]").first.fill("90")
            m.locator(".pt-save button").click(); m.wait_for_timeout(1000)
            if "Play time saved" not in (m.locator("#toast").inner_text() or ""):
                problems.append("play time: saving didn't say saved")
            check(m, "playtime")
            m.reload(); m.wait_for_timeout(1200)
            if m.locator(".pt-people tr[data-key] [name=limit]").first.input_value() != "90" or not m.locator(".pt-rule").count():
                problems.append("play time: the bedtime or limit wasn't kept")
            m.goto(f"{base}/app#/manage/users"); m.wait_for_timeout(1000)
            # Votes: an admin starts one in Manage → Votes, then votes on the Votes page
            m.goto(f"{base}/app#/manage/votes"); m.wait_for_timeout(1000)
            m.locator("#cmv-new").click()
            m.locator("#cmv-f [name=question]").fill("What should we build next?")
            m.locator("#cmv-f .cmv-opt [name=text]").nth(0).fill("Castle")
            m.locator("#cmv-f .cmv-opt [name=text]").nth(1).fill("Theme park")
            m.locator("#cmv-f button[type=submit]").click(); m.wait_for_timeout(1000)
            if not m.locator("#cmv-list .cm-vote").count():
                problems.append("votes: starting a vote didn't list it")
            m.goto(f"{base}/app#/votes"); m.wait_for_timeout(1000)
            m.locator("[data-vote]").first.click(); m.wait_for_timeout(1000)
            if "1 vote" not in m.locator("#cm-votes").inner_text():
                problems.append("votes: voting didn't count")
            check(m, "votes")
            # Messages: a player writes to the admins; the admin reads it (the dot goes), archives it; admins can't write to themselves
            pl.goto(f"{base}/app#/messages"); pl.wait_for_timeout(800)
            pl.locator("#cm-new").click()
            pl.locator("#cm-new-form [name=body]").fill("Can we have a zoo?")
            pl.locator("#cm-new-form button[type=submit]").click(); pl.wait_for_timeout(1000)
            if "Can we have a zoo?" not in pl.locator("#view").inner_text():
                problems.append("messages: the sent message isn't shown")
            m.goto(f"{base}/app#/messages"); m.wait_for_timeout(800)
            if m.locator("#cm-new").is_visible():
                problems.append("messages: an admin is offered 'Write to the admins'")
            m.goto(f"{base}/app#/manage/messages"); m.wait_for_timeout(1000)
            if not m.locator(".cm-threads li").count():
                problems.append("messages: Manage → Messages is empty after a message")
            check(m, "messages")
            m.locator(".cm-threads a").first.click(); m.wait_for_timeout(1000)
            m.locator("[data-archive]").click(); m.wait_for_timeout(1000)
            if m.locator(".cm-threads a.unread").count() or not m.locator(".cm-archive").count():
                problems.append("messages: reading didn't clear the dot, or archiving didn't move it to Archived")
            if m.viewport_size["width"] <= 700 and not m.locator("#manage-select").is_visible():
                problems.append("phone: Manage isn't a dropdown")
            m.goto(f"{base}/app#/manage/users"); m.wait_for_timeout(800)
            # A slow answer shows "Loading…" instead of a blank page, and the page once it comes
            held = []
            m.route("**/api/users", lambda r: held.append(r))
            m.reload(); m.wait_for_timeout(1200)
            if "Loading" not in m.locator("#view").inner_text():
                problems.append("app: a slow page stays blank instead of saying Loading…")
            for r in held:
                r.continue_()
            m.unroute("**/api/users")
            m.wait_for_timeout(1000)
            if "Loading" in m.locator("#view").inner_text():
                problems.append("app: Loading… stayed up after the page came")
            # Solstone not answering (just restarted): wait and try again, not the sign-in page
            tries = []
            def restarting(r):
                tries.append(1)
                r.fulfill(status=502, body="Bad gateway") if len(tries) == 1 else r.continue_()
            m.route("**/api/auth/me", restarting)
            m.reload(); m.wait_for_timeout(800)
            if "Waiting for Solstone" not in m.locator("#view").inner_text():
                problems.append("app: Solstone not answering didn't say it's waiting")
            m.wait_for_timeout(3500)
            if m.locator("#login-root:not([hidden])").count() or len(tries) < 2:
                problems.append("app: after Solstone answered again it didn't sign back in")
            m.unroute("**/api/auth/me")
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
