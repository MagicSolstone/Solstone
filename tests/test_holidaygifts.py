"""A holiday's reward: everyone who plays during it gets it once, and the Events list says so."""
import asyncio
from datetime import datetime

from app import board, challenges, db, fwshow, holidaygifts, settings_store, upcoming


def _today():
    """Solstone's day (its time zone), not the machine's: at night they're different days."""
    return datetime.now(db.tz()).date()


class FakeServer:
    id = "hg-test"
    display_name = "Test"
    is_java = True
    said: list

    def rcon_conf(self):
        return True

    async def rcon(self, cmd):
        self.said.append(cmd)
        return ""


def test_reward_once_each_during_the_holiday(monkeypatch):
    from datetime import timedelta
    today = datetime.now(db.tz()).date()
    keep = settings_store.load().get("fw_calendar")
    fwshow.save_calendar([{"id": "party", "name": "Party week", "emoji": "🎉", "days": 7, "date": {"type": "once", "iso": today.isoformat()},
                           "detail": "**Come** and play {gold}all week{/gold}!",
                           "reward": {"items": [{"item": "diamond", "count": 2}, {"item": "nope nope"}], "message": "Happy party week"}}])
    given = []

    async def award(srv, player, prize, why, note=""):
        given.append((player, prize["item"], prize["count"]))
        return True
    monkeypatch.setattr(challenges, "award", award)
    srv = FakeServer()
    srv.said = []
    settings_store.save_section(holidaygifts.SECTION, {})
    try:
        e = fwshow.calendar()[0]
        assert e["reward"]["items"] == [{"item": "minecraft:diamond", "count": 2, "name": ""}] and e["detail"].startswith("**Come**")
        assert asyncio.run(holidaygifts.tick(srv, ["Alex", "Sam"])) == 2
        assert given == [("Alex", "minecraft:diamond", 2), ("Sam", "minecraft:diamond", 2)]
        assert any("Happy party week" in c for c in srv.said) and any("2 diamond" in c for c in srv.said)
        assert asyncio.run(holidaygifts.tick(srv, ["Alex", "Kid"])) == 1 and given[-1][0] == "Kid"       # once each
        items = upcoming.items({"hg-test": "Test"})
        h = next(i for i in items if i["kind"] == "holiday")
        assert h["reward"]["items"] == [{"item": "minecraft:diamond", "count": 2, "name": "Diamond"}] and h["about"].startswith("**Come**")
        assert h["reward"]["when"] == today.strftime("%a %-d %b") + " to " + (today + timedelta(days=6)).strftime("%a %-d %b")
        cal = fwshow.calendar()
        cal[0]["reward"].update(note="A present for party week")
        cal[0].update(name_fmt="**Party** week", message_fmt="{gold}Party{/gold} all week!", banner={"style": "custom", "colors": ["#112233", "#aabbcc"]})
        fwshow.save_calendar(cal)
        e = fwshow.calendar()[0]
        assert e["name"] == "Party week" and e["message"] == "Party all week!"                # plain, for the game and lists
        b = [x for x in board.holiday_banners(datetime.now(db.tz())) if x["id"].startswith("hol-party")]
        assert len(b) == 1 and b[0]["text"] == "{gold}Party{/gold} all week!" and b[0]["style"] == "custom" and b[0]["colors"] == ["#112233", "#aabbcc"]
        assert b[0]["reward_note"] == "A present for party week" and b[0]["items"][0]["item"] == "minecraft:diamond"
        assert next(i for i in upcoming.items({"hg-test": "Test"}) if i["kind"] == "holiday")["title_fmt"] == "**Party** week"
    finally:
        settings_store.save_section(holidaygifts.SECTION, {})
        settings_store.save_section("fw_calendar", keep)          # None: back to Solstone's own list


def test_reward_and_colours_reach_past_the_day():
    from datetime import timedelta
    today = datetime.now(db.tz()).date()
    keep = settings_store.load().get("fw_calendar")
    try:
        # over two days ago and only a day long, but its reward runs three days after (Thanksgiving to Sunday)
        fwshow.save_calendar([{"id": "thanks", "name": "Thanksgiving", "days": 1, "date": {"type": "once", "iso": (today - timedelta(days=2)).isoformat()},
                               "reward": {"items": [{"item": "pumpkin_pie", "count": 1}], "before": 0, "after": 3}},
                              # in three days, with its colours from five days before
                              {"id": "xmas", "name": "Christmas", "days": 2, "date": {"type": "once", "iso": (today + timedelta(days=3)).isoformat()},
                               "colors": ["#ff0000", "#00aa00", "#ffffff"], "message": "Merry Christmas!", "colors_before": 5,
                               "reward": {"items": [{"item": "diamond"}], "before": 1}}])
        assert [e["id"] for e, _s in holidaygifts.active()] == ["thanks"]               # Christmas's reward isn't on yet
        first, last = holidaygifts.window(fwshow.calendar()[1], today + timedelta(days=3))
        assert (first, last) == (today + timedelta(days=2), today + timedelta(days=4))
        th = fwshow.today_state()["theme"]
        assert th["id"] == "xmas" and th["colors"] == ["#ff0000", "#00aa00", "#ffffff"] and not th["on_day"] and th["message"] == ""
    finally:
        settings_store.save_section("fw_calendar", keep)


def test_one_banner_from_the_countdown_to_the_last_reward_day():
    from datetime import timedelta
    now = datetime.now(db.tz())
    today = now.date()
    keep = settings_store.load().get("fw_calendar")
    try:
        cal = [{"id": "thanks", "name": "Thanksgiving", "emoji": "🦃", "days": 1, "banner_days": 3, "message": "Happy Thanksgiving!",
                "reward": {"items": [{"item": "pumpkin_pie", "count": 1}], "after": 3, "banner": True}}]

        def banners(day_offset):
            cal[0]["date"] = {"type": "once", "iso": (today + timedelta(days=day_offset)).isoformat()}
            fwshow.save_calendar(cal)
            return [b for b in board.active("home", now=now) if b["id"].startswith("hol-thanks")]
        soon = banners(2)                                   # in two days: counting down, no reward yet
        assert len(soon) == 1 and soon[0]["kind"] == "holiday-soon" and soon[0]["countdown"] and "items" not in soon[0]
        day = banners(0)
        assert len(day) == 1 and day[0]["text"] == "Happy Thanksgiving!" and day[0]["items"]
        after = banners(-2)                                 # two days on: still one banner, now about the reward
        assert len(after) == 1 and after[0]["kind"] == "reward" and "still time" in after[0]["text"] and after[0]["reward_until"].startswith("Now until")
        cal[0]["reward"]["after_text"] = "Happy  Thanksgiving! Rewards   still on through the weekend"   # its own words after the day
        assert banners(-2)[0]["text"] == "Happy Thanksgiving! Rewards still on through the weekend"
        cal[0]["reward"]["after_text"] = ""
        assert banners(-4) == []                            # the reward's over: so is the banner
        cal[0]["reward"]["banner"] = False                  # not kept up for the reward's extra days
        assert banners(-2) == []
        cal[0]["banner"] = {"show": False}
        assert banners(0) == []
    finally:
        settings_store.save_section("fw_calendar", keep)


class RoomServer(FakeServer):
    """A pretend server where Alex's inventory has 35 of its 36 spaces full."""
    full = 35

    async def rcon(self, cmd):
        self.said.append(cmd)
        if cmd.startswith("data get entity Alex Inventory"):
            return "Alex has the following entity data: [" + ", ".join(f"{{Slot: {i}b, id: \"minecraft:dirt\", count: 64}}" for i in range(self.full)) + "]"
        if cmd.startswith("give Alex"):
            return "Gave 1 [Diamond Sword] to Alex"
        return ""


def test_a_prize_waits_for_room_instead_of_dropping(monkeypatch):
    async def online(srv):
        return ["Alex"], "rcon"
    monkeypatch.setattr(challenges.S, "online_players", online)
    srv = RoomServer()
    srv.said = []
    srv.full = 36                                                        # not a space free
    keep = challenges._load()
    try:
        challenges._save({**keep, "gifts": []})
        assert challenges.slots_needed("minecraft:diamond_sword", 2) == 2 and challenges.slots_needed("minecraft:cookie", 64) == 1
        assert not asyncio.run(challenges.award(srv, "Alex", {"item": "minecraft:diamond_sword", "count": 2}, "won", note="Here you go!"))
        assert not any(c.startswith("give ") for c in srv.said) and any("inventory is full" in c for c in srv.said)
        told = len(srv.said)
        asyncio.run(challenges.waiting_for_room(srv, ["Alex"]))       # still full: no give, and not told again
        assert not any(c.startswith("give ") for c in srv.said) and sum("inventory is full" in c for c in srv.said) == 1 and len(srv.said) > told
        srv.full = 30                                                    # made room
        asyncio.run(challenges.waiting_for_room(srv, ["Alex"]))
        assert any(c == "give Alex minecraft:diamond_sword 2" for c in srv.said) and any("Here you go!" in c for c in srv.said)
        assert not challenges._load()["gifts"]
    finally:
        challenges._save(keep)


def test_events_keep_a_holiday_while_its_reward_is_still_on():
    from datetime import timedelta
    today = datetime.now(db.tz()).date()
    keep = settings_store.load().get("fw_calendar")
    try:
        fwshow.save_calendar([{"id": "thanks", "name": "Thanksgiving", "days": 1, "date": {"type": "once", "iso": (today - timedelta(days=1)).isoformat()},
                               "banner": {"style": "sunset"}, "reward": {"items": [{"item": "pumpkin_pie"}], "after": 3}}])
        h = [i for i in upcoming.items({}) if i["kind"] == "holiday"]
        assert len(h) == 1 and h[0]["live"] and "still being given" in h[0]["detail"] and h[0]["look"]["style"] == "sunset"
        cal = fwshow.calendar()
        cal[0]["reward"]["after"] = 0                        # no reward after it: gone from Events once it's over
        fwshow.save_calendar(cal)
        assert not [i for i in upcoming.items({}) if i["kind"] == "holiday"]
    finally:
        settings_store.save_section("fw_calendar", keep)


def test_a_holiday_reward_can_hold_up_to_nine_things():
    from app import fwshow
    items = [{"item": f"minecraft:{x}", "count": 1} for x in ("cake", "cookie", "apple", "bread", "carrot", "melon_slice", "pumpkin_pie", "sweet_berries", "honey_bottle", "golden_apple")]
    assert len(fwshow._clean_reward({"items": items})["items"]) == 9


def test_a_rewards_game_message_keeps_its_lines():
    r = fwshow._clean_reward({"items": [{"item": "cake"}], "message": "&6Merry Christmas!\r\n\n&aJohn 3:16  For God so loved\nline 3\n4\n5\n6"})
    assert r["message"].split("\n") == ["&6Merry Christmas!", "&aJohn 3:16 For God so loved", "line 3", "4", "5"]
    assert board.plain("__under__ and **bold**") == "under and bold"
    nxt = fwshow.with_next([fwshow._clean_entry({"id": "x", "name": "X", "date": {"type": "fixed", "month": 12, "day": 25}})])[0]["next"]
    assert nxt.endswith("-12-25")


def test_a_prize_too_big_for_any_inventory_comes_in_parts(monkeypatch):
    """64 cakes don't stack: 64 spaces, more than an inventory has. They come as far as there's room, the rest later."""
    async def online(srv):
        return ["Alex"], "rcon"
    monkeypatch.setattr(challenges.S, "online_players", online)
    srv = RoomServer()
    srv.said, srv.full = [], 0                                           # an empty inventory: 36 spaces
    keep = challenges._load()
    try:
        challenges._save({**keep, "gifts": []})
        assert challenges.slots_needed("minecraft:cake", 64) == 64
        assert not asyncio.run(challenges.award(srv, "Alex", {"item": "minecraft:cake", "count": 64}, "won the race"))
        assert "give Alex minecraft:cake 36" in srv.said and any("part of your reward" in c for c in srv.said)
        left = challenges._load()["gifts"]
        assert len(left) == 1 and left[0]["count"] == 28
        asyncio.run(challenges.waiting_for_room(srv, ["Alex"]))       # room again (the pretend inventory never fills)
        assert "give Alex minecraft:cake 28" in srv.said and not challenges._load()["gifts"]
    finally:
        challenges._save(keep)


def test_who_has_had_the_reward(monkeypatch):
    """An admin can see who's had an event's reward, and who's still waiting for room for it."""
    from app import challenges, holidaygifts, settings_store
    from app import servers as S
    e = {"id": "party", "name": "Party"}
    monkeypatch.setattr(holidaygifts.fwshow, "calendar", lambda: [e])
    monkeypatch.setattr(S.registry, "servers", {})
    settings_store.save_section(holidaygifts.SECTION, {"party:2026-11-01:srv1": ["ann", "bo"], "other:2026-11-01:srv1": ["cy"]})
    settings_store.save_section(holidaygifts.WHEN, {"party:2026-11-01:srv1": {"ann": 100, "bo": 200}})
    d = challenges._load()
    d["gifts"].append({"server": "srv1", "player": "Ann", "item": "minecraft:stick", "count": 1, "why": "Party reward"})
    challenges._save(d)
    try:
        g = holidaygifts.given_to("party")
        assert len(g) == 1 and g[0]["start"] == "2026-11-01" and [p["name"] for p in g[0]["players"]] == ["bo", "ann"]
        assert [p["waiting"] for p in g[0]["players"]] == [False, True]
        assert holidaygifts.given_to("nothing") == []
    finally:
        settings_store.save_section(holidaygifts.SECTION, {})
        settings_store.save_section(holidaygifts.WHEN, {})
        d = challenges._load()
        d["gifts"] = [x for x in d["gifts"] if x.get("why") != "Party reward"]
        challenges._save(d)


def test_an_event_on_just_one_server(monkeypatch):
    """With two servers, an event can be on just one: its reward only there, and the Events page says which."""
    import asyncio

    from app import fwshow, holidaygifts, upcoming
    e = fwshow._clean_entry({"id": "build", "name": "Build week", "date": {"type": "once", "iso": _today().isoformat()}, "days": 3,
                             "servers": ["creative", "creative", ""], "reward": {"items": [{"item": "minecraft:stick", "count": 1}]}})
    assert e["servers"] == ["creative"]
    assert fwshow._clean_entry({"name": "x"})["servers"] == []                        # none: every server
    monkeypatch.setattr(fwshow, "calendar", lambda: [e])
    gave = []

    async def award(srv, name, item, why, note=""):
        gave.append((srv.id, name))
        return True

    async def say(srv, name, ev, items):
        pass
    monkeypatch.setattr(holidaygifts.challenges, "award", award)
    monkeypatch.setattr(holidaygifts, "say", say)

    class Srv:
        is_java = True

        def __init__(self, sid):
            self.id = sid

        def rcon_conf(self):
            return True
    try:
        asyncio.run(holidaygifts.tick(Srv("survival"), ["Ann"]))
        asyncio.run(holidaygifts.tick(Srv("creative"), ["Ann"]))
        assert gave == [("creative", "Ann")]
        both = [x for x in upcoming.items({"survival": "Survival", "creative": "Creative"}) if x["kind"] == "holiday"]
        assert both and both[0]["server"] == "Creative"
        one = [x for x in upcoming.items({"creative": "Creative"}) if x["kind"] == "holiday"]
        assert one and not one[0].get("server")                                        # one server: nothing to tell apart
        assert not [x for x in upcoming.items({"survival": "Survival"}) if x["kind"] == "holiday"]   # not shown where it isn't
    finally:
        from app import settings_store
        settings_store.save_section(holidaygifts.SECTION, {})
        settings_store.save_section(holidaygifts.WHEN, {})
