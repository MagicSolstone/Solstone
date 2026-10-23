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


def main() -> int:
    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="solstone-smoke-"))
    shots = Path(os.environ.get("SMOKE_SHOTS") or root / "shots")
    shots.mkdir(parents=True, exist_ok=True)
    helpers.build(root)
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    app = start_app(root, port)
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
                "leaderboards": f"#/s/{sid}/leaderboards", "fishing": f"#/s/{sid}/fishing", "fishing-player": f"#/s/{sid}/fishing/Tyler", "mods": f"#/s/{sid}/mods", "coming-up": "#/coming-up",
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
