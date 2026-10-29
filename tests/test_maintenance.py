"""Planned maintenance: a countdown banner, the details kept for the Cloudflare page, and clearing it again."""
import asyncio
import json

import httpx

from app import board, maintenance


def test_plan_and_clear(client, viewer):
    assert viewer.put("/api/settings/maintenance", json={"start": "2030-01-01T10:00"}).status_code == 403
    assert client.put("/api/settings/maintenance", json={"start": "2030-01-01T10:00", "end": "2030-01-01T09:00"}).status_code == 400
    r = client.put("/api/settings/maintenance", json={"start": "2030-01-01T10:00", "end": "2030-01-01T12:30", "message": "New SSD"}).json()
    try:
        assert r["maintenance"] == {"start": "2030-01-01T10:00", "end": "2030-01-01T12:30", "message": "New SSD"}
        assert r["worker"] != "ok"                     # the tests have no Cloudflare in front: it says why, it doesn't fail
        item = next(i for i in board.config()["items"] if i["id"] == maintenance.BOARD_ID)
        assert item["countdown"] == "2030-01-01T10:00" and item["end"] == "2030-01-01T12:30" and item["detail"] == "New SSD"
        assert client.get("/api/settings/maintenance").json()["maintenance"]["message"] == "New SSD"
        code = client.get("/api/settings/site/offline-worker").text
        assert maintenance.worker_key() in code and "/__solstone/maintenance" in code
    finally:
        client.put("/api/settings/maintenance", json={"start": ""})
    assert client.get("/api/settings/maintenance").json()["maintenance"] is None
    assert not any(i["id"] == maintenance.BOARD_ID for i in board.config()["items"])


def test_handing_it_to_the_worker(monkeypatch):
    seen = {}

    def answer(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["key"], seen["body"] = str(request.url), request.headers.get("x-solstone-key"), json.loads(request.content)
        return httpx.Response(200, json={"ok": True})
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(answer), **kw))
    m = {"start": "2030-01-01T10:00", "end": "2030-01-01T12:30", "message": "New SSD"}
    assert asyncio.run(maintenance.push("https://fbc.example", m)) is None
    assert seen["url"] == "https://fbc.example/__solstone/maintenance" and seen["key"] == maintenance.worker_key()
    assert seen["body"]["message"] == "New SSD" and seen["body"]["end"] > seen["body"]["start"] and seen["body"]["until"]
    assert asyncio.run(maintenance.push("http://10.0.0.5:8025", m))           # not the public https address: says so
