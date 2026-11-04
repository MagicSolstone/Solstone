"""A holiday reward's picture on the public Events page comes from any Java server whose game can draw it, and a
"not found" is never kept by browsers or Cloudflare (a new reward showed no picture there)."""
from types import SimpleNamespace


def test_reward_picture_from_any_server_and_404_not_cached(anon, monkeypatch):
    from app import holidaygifts
    from app import main as M

    monkeypatch.setattr(holidaygifts, "rewarded_items", lambda: {"minecraft:redstone", "minecraft:coal"})
    state = {"ready": False, "ensured": 0}
    asked = []

    def fake_assets(srv):
        def ensure():
            state["ensured"] += 1
        def icon(item):
            asked.append(item)
            return b"PNG" if item == "minecraft:redstone" else None
        return SimpleNamespace(ready=state["ready"], vs=SimpleNamespace(version="1.21.x", ensure=ensure, state="ready" if state["ready"] else "missing"), icon=icon)

    monkeypatch.setattr(M, "_assets", fake_assets)
    # Its game files aren't here yet: it starts fetching them, and says not found (not kept anywhere)
    r = anon.get("/api/public/reward-item/minecraft/redstone.png")
    assert r.status_code == 404 and r.headers.get("cache-control") == "no-store" and state["ensured"] == 1
    state["ready"] = True
    # Not one of the public servers (the only one here is Private, say): still drawn from it
    monkeypatch.setattr(M, "_public_servers_list", lambda: [])
    r = anon.get("/api/public/reward-item/minecraft/redstone.png")
    assert r.status_code == 200 and r.content == b"PNG" and "max-age" in r.headers["cache-control"]
    r = anon.get("/api/public/reward-item/minecraft/coal.png")                      # nobody can draw it
    assert r.status_code == 404 and r.headers.get("cache-control") == "no-store"
    assert anon.get("/api/public/reward-item/minecraft/diamond.png").status_code == 404   # not a reward: never asked
    assert "minecraft:diamond" not in asked
