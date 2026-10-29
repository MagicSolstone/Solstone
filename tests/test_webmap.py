"""The web map through Solstone: passes, the sandbox around it, and the map's files handed on as they are."""
import gzip
import http.server
import threading

import pytest
from fastapi.testclient import TestClient

from app import main, webmap

TILE = gzip.compress(b"tile-bytes" * 50)
PAGE = b"<!doctype html><html><head><title>BlueMap</title></head><body><script type=module src=./assets/app.js></script></body></html>"


class _Map(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            body, kind, enc = PAGE, "text/html", None
        elif self.path == "/settings.json":
            body, kind, enc = b'{"maps":["world"]}', "application/json", None
        elif self.path.startswith("/maps/world/tiles/0.prbm"):
            body, kind, enc = TILE, "application/octet-stream", "gzip"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        if enc:
            self.send_header("Content-Encoding", enc)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def fake_map(client, sid):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Map)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    client.put(f"/api/servers/{sid}/settings", json={"map_url": url, "map_proxy": True})
    yield url
    client.put(f"/api/servers/{sid}/settings", json={"map_url": "", "map_proxy": ""})
    srv.shutdown()


def test_map_through_solstone(client, anon, sid, fake_map):
    assert anon.get(f"/api/servers/{sid}/webmap").status_code == 401
    url = client.get(f"/api/servers/{sid}/webmap").json()["url"]
    assert url.startswith(f"/map/{sid}/") and url.endswith("/")
    page = anon.get(url)                       # the pass is what counts, not the cookie (the map can't send one)
    assert page.status_code == 200
    assert page.headers["content-security-policy"].startswith("sandbox allow-scripts")      # walled off from Solstone
    assert "allow-same-origin" not in page.headers["content-security-policy"]
    assert b"localStorage" in page.content and page.content.index(b"localStorage") < page.content.index(b"<script type=module")
    assert anon.get(url + "settings.json").json() == {"maps": ["world"]}
    tile = anon.get(url + "maps/world/tiles/0.prbm", headers={"Accept-Encoding": "gzip"})
    assert tile.status_code == 200 and tile.headers.get("access-control-allow-origin") == "*"
    assert anon.get(url + "nothing-here").status_code == 404
    assert anon.get(url + "../../api/servers").status_code in (400, 403, 404)        # never reaches anything else
    assert anon.get(url + "%2e%2e/%2e%2e/etc/passwd").status_code == 400


def test_map_passes(client, anon, sid, fake_map):
    url = client.get(f"/api/servers/{sid}/webmap").json()["url"]
    token = url.rstrip("/").split("/")[-1]
    uid, exp, sig = token.split("-")
    assert anon.get(f"/map/{sid}/{uid}-{exp}-{'0' * 32}/").status_code == 403                 # forged
    assert anon.get(f"/map/{sid}/{uid}-{int(exp) + 1}-{sig}/").status_code == 403             # changed
    assert anon.get(f"/map/other-server/{token}/").status_code == 403                         # another server's
    old = webmap.make_pass(int(uid), sid)
    webmap.PASS_HOURS, keep = -1, webmap.PASS_HOURS
    try:
        stale = webmap.make_pass(int(uid), sid)
    finally:
        webmap.PASS_HOURS = keep
    assert anon.get(f"/map/{sid}/{stale}/").status_code == 403                                # run out
    assert anon.get(f"/map/{sid}/{old}/").status_code == 200
    # switched off: every pass stops working at once
    client.put(f"/api/servers/{sid}/settings", json={"map_proxy": ""})
    assert anon.get(url).status_code == 403
    assert client.get(f"/api/servers/{sid}/webmap").status_code == 404


def test_players_need_the_map_switch(client, sid, fake_map):
    u = client.post("/api/users", json={"username": "map_player", "password": "player-pass-1", "role": "player"}).json()
    client.patch(f"/api/users/{u['id']}", json={"player": "Tyler"})
    try:
        c = TestClient(main.app, headers={"X-Solstone": "1"})
        assert c.post("/api/auth/login", json={"username": "map_player", "password": "player-pass-1"}).status_code == 200
        assert c.get(f"/api/servers/{sid}/webmap").status_code == 404             # Players can see the map is off
        assert "map_url" not in c.get(f"/api/servers/{sid}").json() or not c.get(f"/api/servers/{sid}").json().get("map_url")
        main.settings_store.save_section("players", {**main.settings_store.load().get("players", {}), "see_map": True})
        try:
            url = c.get(f"/api/servers/{sid}/webmap").json()["url"]
            assert c.get(url).status_code == 200
            assert c.get(f"/api/servers/{sid}").json().get("map_url") is None   # the map's home address stays hidden
        finally:
            main.settings_store.save_section("players", {**main.settings_store.load().get("players", {}), "see_map": False})
        assert c.get(url).status_code == 403                                       # and the pass stops with the switch
    finally:
        client.delete(f"/api/users/{u['id']}")


def test_map_address_must_be_a_web_address(client, sid):
    assert client.put(f"/api/servers/{sid}/settings", json={"map_url": "file:///etc/passwd"}).status_code == 400
    assert client.put(f"/api/servers/{sid}/settings", json={"map_url": ""}).status_code == 200
