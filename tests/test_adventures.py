import asyncio
import time


class Srv:
    id = "adv-test"

    def __init__(self, where):
        self.where, self.cmds = where, []

    def rcon_conf(self):
        return ("h", 1, "p")

    async def rcon(self, cmd):
        self.cmds.append(cmd)
        if cmd.endswith(" Pos"):
            return "".join(f"{n} has the following entity data: [{x}d, {y}d, {z}d]" for n, (x, y, z) in self.where.items())
        return "".join(f'{n} has the following entity data: "minecraft:overworld"' for n in self.where)


def test_track_writes_movement_not_standing_still(client):
    from app import adventures, db
    db.x("DELETE FROM positions WHERE server_id='adv-test'")
    adventures._last.clear()
    srv = Srv({"Tyler": (10.0, 64.0, -5.0)})
    assert asyncio.run(adventures.track(srv, ["Tyler"])) == 1
    assert asyncio.run(adventures.track(srv, ["Tyler"])) == 0          # hasn't moved
    srv.where["Tyler"] = (14.0, 64.0, -5.0)
    assert asyncio.run(adventures.track(srv, ["Tyler"])) == 1
    rows = db.q("SELECT x FROM positions WHERE server_id='adv-test' ORDER BY ts")
    assert [r["x"] for r in rows] == [10.0, 14.0]
    srv.where["Gimli_Jr"] = (-3.5, 70.0, 8.25)                                 # two on: still two commands
    n = len(srv.cmds)
    assert asyncio.run(adventures.track(srv, ["Tyler", "Gimli_Jr"])) == 1 and len(srv.cmds) == n + 2


def test_progress_line():
    from app.adventures import progress_line
    before = {"minecraft:killed": {"minecraft:zombie": 2}, "minecraft:mined": {}, "minecraft:custom": {"minecraft:damage_taken": 0}}
    after = {"minecraft:killed": {"minecraft:zombie": 5, "minecraft:skeleton": 1},
             "minecraft:mined": {"minecraft:diamond_ore": 1, "minecraft:deepslate_diamond_ore": 2},
             "minecraft:custom": {"minecraft:damage_taken": 240}}
    line = progress_line(before, after)
    assert line == "defeated 3 zombies, 1 skeleton · mined 3 diamond ore · took 12 ❤ of damage"
    assert progress_line(after, after) is None


def test_sessions_timeline_and_saving(client, viewer, sid):
    from app import db
    now = time.time()
    db.x("DELETE FROM sessions WHERE server_id=?", (sid,))
    db.x("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?)", (sid, "Tyler", now - 7200, now - 3600, now - 3600))
    db.x("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?)", (sid, "Gimli_Jr", now - 3900, now - 1800, now - 1800))
    db.x("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)", (sid, now - 5000, "Tyler", "minecraft:overworld", 1, 64, 2))
    eid = db.add_event(sid, now - 4000, "progress", "Tyler defeated 2 zombies", "Tyler")
    try:
        s = viewer.get(f"/api/servers/{sid}/adventures").json()["sessions"]
        assert len(s) >= 1 and s[0]["players"] == ["Gimli_Jr", "Tyler"]               # overlapping: one session
        t = viewer.get(f"/api/servers/{sid}/adventures/timeline?start={s[0]['start']}&end={s[0]['end']}").json()
        assert t["trails"]["Tyler"][0][2:] == [1, 64, 2] and any(e["message"] == "Tyler defeated 2 zombies" for e in t["events"])
        a = viewer.post(f"/api/servers/{sid}/adventures", json={"start": s[0]["start"], "end": s[0]["end"], "title": "The big cave", "note": "Found diamonds"}).json()
        assert a["title"] == "The big cave"
        assert viewer.post(f"/api/servers/{sid}/adventures", json={"start": 1, "end": 2, "title": " "}).status_code == 400
        s2 = viewer.get(f"/api/servers/{sid}/adventures").json()["sessions"]
        assert s2[0]["saved"][0]["title"] == "The big cave"
        assert client.delete(f"/api/servers/{sid}/adventures/{a['id']}").json()["ok"]        # an admin can delete it
    finally:
        db.x("DELETE FROM events WHERE id=?", (eid,))
        db.x("DELETE FROM sessions WHERE server_id=?", (sid,))
        db.x("DELETE FROM positions WHERE server_id=?", (sid,))


def test_hide_and_erase(client, viewer, sid):
    from app import db
    now = time.time()
    db.x("DELETE FROM sessions WHERE server_id=?", (sid,))
    db.x("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?)", (sid, "Tyler", now - 7200, now - 3600, now - 3600))
    db.x("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)", (sid, now - 5000, "Tyler", "minecraft:overworld", 1, 64, 2))
    try:
        s = viewer.get(f"/api/servers/{sid}/adventures").json()["sessions"][0]
        assert not s["hidden"]
        assert viewer.post(f"/api/servers/{sid}/adventures/hide", json={"start": s["start"], "end": s["end"]}).json()["ok"]
        assert viewer.get(f"/api/servers/{sid}/adventures").json()["sessions"][0]["hidden"]
        viewer.post(f"/api/servers/{sid}/adventures/hide", json={"start": s["start"], "end": s["end"], "hidden": False})
        assert not viewer.get(f"/api/servers/{sid}/adventures").json()["sessions"][0]["hidden"]
        assert viewer.post(f"/api/servers/{sid}/adventures/erase", json={"start": s["start"], "end": s["end"]}).status_code == 403
        r = client.post(f"/api/servers/{sid}/adventures/erase", json={"start": s["start"], "end": s["end"]}).json()
        assert r["positions"] == 1
        assert viewer.get(f"/api/servers/{sid}/adventures").json()["sessions"][0]["hidden"]      # erased ones are hidden too
    finally:
        db.x("DELETE FROM sessions WHERE server_id=?", (sid,))
        db.x("DELETE FROM adventures_hidden WHERE server_id=?", (sid,))


def test_more_of_what_happened_and_what_they_are_up_to():
    from app import adventures as A
    before = {"minecraft:mined": {"minecraft:oak_log": 2}, "minecraft:used": {}, "minecraft:custom": {"minecraft:walk_one_cm": 0}}
    after = {"minecraft:mined": {"minecraft:oak_log": 14, "minecraft:diamond_ore": 2, "minecraft:wheat": 5},
             "minecraft:used": {"minecraft:oak_planks": 30, "minecraft:diamond_pickaxe": 40, "minecraft:stone_pickaxe": 90,
                                "minecraft:stone_sword": 12, "minecraft:water_bucket": 3},     # tools: not blocks placed
             "minecraft:custom": {"minecraft:walk_one_cm": 120000, "minecraft:open_chest": 3, "minecraft:traded_with_villager": 2}}
    line = A.progress_line(before, after)
    for bit in ("mined 2 diamond ore", "chopped 12 logs", "harvested 5 crops", "placed 30 blocks", "opened 3 chests",
                "traded with villagers 2×", "travelled 1.2 km"):
        assert bit in line, bit
    assert A.doing(before, after) == "🧱 Building"                       # 30 blocks placed beats 12 logs (24) and the rest
    assert A.doing(before, before) is None
    fishing = {"minecraft:custom": {"minecraft:fish_caught": 3}}
    assert A.doing({}, fishing) == "🎣 Fishing"


def test_the_feed_summed_up_every_ten_minutes():
    from app import adventures as A
    t = 1_000_000.0
    evs = [{"ts": t + 30, "type": "join", "player": "Alex", "message": "Alex joined the game"},
           {"ts": t + 200, "type": "progress", "player": "Alex", "message": "defeated 3 zombies, 1 spider · dug 40 blocks · chopped 12 logs"},
           {"ts": t + 400, "type": "progress", "player": "Alex", "message": "defeated 2 zombies · took 6 ❤ of damage"},
           {"ts": t + 450, "type": "fish", "player": "Sam", "message": "Sam caught a Cod"},
           {"ts": t + 460, "type": "chat", "player": "Sam", "message": "hi"},
           {"ts": t + 1300, "type": "death", "player": "Alex", "message": "Alex was slain by a Zombie"}]
    s = A.summary(evs, t, t + 1800)
    assert [round(b["start"] - t) for b in s] == [0, 1200]                        # the empty block in between is left out
    assert s[0]["players"]["Alex"] == {"mobs": 6, "mined": 40, "logs": 12, "damage": 6}
    assert s[0]["players"]["Sam"] == {"fish": 1, "chat": 1}
    assert [e["type"] for e in s[0]["moments"]] == ["join"] and s[1]["moments"][0]["type"] == "death"


def test_every_block_advancement_and_death_reaches_the_stats_page(monkeypatch):
    """The feed only mentions trips of 500 blocks or more, and the log's advancement line wasn't being seen: the Stats
    page had no distance for short trips and no advancements at all. Each save's exact gains go to it now."""
    import time
    from datetime import date

    from app import adventures, db, serverstats
    from app import servers as S

    class Srv:
        id = "tally-test"
    stats = {"minecraft:custom": {"minecraft:walk_one_cm": 0, "minecraft:deaths": 0}}
    advs = {"minecraft:story/root": {"done": True}, "minecraft:recipes/misc/stick": {"done": True}}
    monkeypatch.setattr(S, "player_stats", lambda srv, uuid: {k: dict(v) for k, v in stats.items()})
    monkeypatch.setattr(S, "player_advancements", lambda srv, uuid: {k: dict(v) for k, v in advs.items()})
    adventures._tally_ensure()
    db.x("DELETE FROM stat_tally WHERE server_id=?", (Srv.id,))
    db.x("DELETE FROM events WHERE server_id=?", (Srv.id,))
    adventures._stats.pop((Srv.id, "Ann"), None)
    adventures.progress(Srv(), {"Ann": "u-1"})                       # first look: what's done so far isn't counted
    stats["minecraft:custom"]["minecraft:walk_one_cm"] = 12000        # 120 blocks: too few for the feed to mention
    stats["minecraft:custom"]["minecraft:deaths"] = 1
    advs["minecraft:story/mine_stone"] = {"done": True}
    advs["minecraft:recipes/misc/torch"] = {"done": True}             # (a recipe: not an advancement)
    advs["minecraft:adventure/root"] = {"done": True}
    adventures.progress(Srv(), {"Ann": "u-1"})
    today = date.fromtimestamp(time.time())
    day = serverstats.compute(Srv.id, [today])[today.isoformat()]
    assert day["travelled"] == 120 and day["advancements"] == 2 and day["deaths"] == 1
    assert not db.q("SELECT 1 FROM events WHERE server_id=? AND type='tally'", (Srv.id,))       # nothing new in any feed
    db.x("DELETE FROM stat_tally WHERE server_id=?", (Srv.id,))
    db.x("DELETE FROM events WHERE server_id=?", (Srv.id,))
