"""A holiday's reward: everyone who plays during it gets it once, and the Events list says so."""
import asyncio
from datetime import datetime

from app import challenges, db, fwshow, holidaygifts, settings_store, upcoming


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
    today = datetime.now(db.tz()).date()
    keep = settings_store.load().get("fw_calendar")
    fwshow.save_calendar([{"id": "party", "name": "Party week", "emoji": "🎉", "days": 7, "date": {"type": "once", "iso": today.isoformat()},
                           "detail": "**Come** and play {gold}all week{/gold}!",
                           "reward": {"items": [{"item": "diamond", "count": 2}, {"item": "nope nope"}], "message": "Happy party week"}}])
    given = []

    async def award(srv, player, prize, why):
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
        assert any("Happy party week" in c and "2 diamond" in c for c in srv.said)
        assert asyncio.run(holidaygifts.tick(srv, ["Alex", "Kid"])) == 1 and given[-1][0] == "Kid"       # once each
        items = upcoming.items({"hg-test": "Test"})
        h = next(i for i in items if i["kind"] == "holiday")
        assert h["reward"] == "2 diamond" and h["about"].startswith("**Come**")
    finally:
        settings_store.save_section(holidaygifts.SECTION, {})
        settings_store.save_section("fw_calendar", keep)          # None: back to Solstone's own list
