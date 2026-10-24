"""Browser smoke test: start Solstone on a synthetic world, open every page in Chromium
and try the main interactive bits. Fails on any JavaScript error, any page that shows
"Something went wrong", and any Content-Security-Policy violation.

    python tests/e2e/smoke.py            (needs: pip install playwright; playwright install chromium)

Screenshots of each page land in $SMOKE_SHOTS (default: a temp folder) for a quick look.
"""
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
            browser = pw.chromium.launch()

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
            # turn on the public status page so it can be checked too
            pg.request.put(f"{base}/api/settings/status", data={"enabled": True}, headers=H)

            routes = {
                "home": "#/", "overview": f"#/s/{sid}", "player": f"#/s/{sid}/p/{puuid}",
                "player-stats": f"#/s/{sid}/p/{puuid}/stats", "player-history": f"#/s/{sid}/p/{puuid}/history", "player-fishing": f"#/s/{sid}/p/{puuid}/fishing",
                "player-advancements": f"#/s/{sid}/p/{puuid}/advancements", "world": f"#/s/{sid}/world",
                "control": f"#/s/{sid}/control", "check": f"#/s/{sid}/check", "chat": f"#/s/{sid}/chat", "challenges": f"#/s/{sid}/challenges", "races": f"#/s/{sid}/challenges/races", "games": f"#/s/{sid}/challenges/games", "performance": f"#/s/{sid}/performance",
                "leaderboards": f"#/s/{sid}/leaderboards", "fishing": f"#/s/{sid}/fishing", "fishing-player": f"#/s/{sid}/fishing/Tyler", "mods": f"#/s/{sid}/mods", "adventures": f"#/s/{sid}/adventures", "coming-up": "#/coming-up",
                "fireworks-editor": "#/fireworks", "fireworks-settings": "#/fireworks/settings",
                "music": "#/music", "announcements": "#/announcements", "admin": "#/admin",
            }
            pg.goto(f"{base}/"); pg.wait_for_timeout(1200)
            for name, hash_ in routes.items():
                pg.goto(f"{base}/{hash_}"); pg.wait_for_timeout(1300)
                check(pg, name)

            # fireworks settings: every tab, then edit a show (copy a step)
            pg.goto(f"{base}/#/fireworks/settings"); pg.wait_for_timeout(1200)
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

            # the music bar's popovers and the give-items dialog
            pg.goto(f"{base}/#/"); pg.wait_for_timeout(1000)
            for sel in (".mbar [data-mb='list']", ".mbar [data-sky='volume']"):
                if pg.locator(sel).count() and pg.locator(sel).first.is_visible():
                    pg.click(sel); pg.wait_for_timeout(250); pg.mouse.click(5, 5)
            pg.goto(f"{base}/#/s/{sid}/control"); pg.wait_for_timeout(1000)
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
            pg.goto(f"{base}/#/s/{sid}/adventures"); pg.wait_for_timeout(800)
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

            # public status page and TV mode, signed out
            anon = browser.new_page(viewport={"width": 1280, "height": 800})
            anon.add_init_script("window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + (e.blockedURI || 'inline')));")
            anon.on("pageerror", lambda e: problems.append(f"status: JS error: {e}"))
            for name, url in (("status", "/status"), ("status-tv", f"/status/{sid}?tv=1")):
                anon.goto(f"{base}{url}"); anon.wait_for_timeout(2000)
                check(anon, name)

            # phone width
            m = page(390, 800)
            for name, hash_ in (("m-overview", f"#/s/{sid}"), ("m-player", f"#/s/{sid}/p/{puuid}"), ("m-fireworks", "#/fireworks")):
                m.goto(f"{base}/{hash_}"); m.wait_for_timeout(1200)
                check(m, name)
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
