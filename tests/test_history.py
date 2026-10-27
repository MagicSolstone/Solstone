"""Recorder, log parsing, history API and notifications."""
import time
from datetime import datetime, timedelta

import helpers
from app import db, notify
from app.logparse import parse_line
from app.recorder import parse_mem_mb, parse_tick_query, recorder

KNOWN = {"tyler", "gimli_jr"}


# ---------------------------------------------------------------- log parsing
def test_parse_join_leave_chat():
    assert parse_line("[18:01:02] [Server thread/INFO]: Tyler joined the game", KNOWN).type == "join"
    assert parse_line("[18:01:02] [Server thread/INFO]: Tyler left the game", KNOWN).type == "leave"
    chat = parse_line("[18:01:02] [Server thread/INFO]: [Not Secure] <Gimli_Jr> dad look", KNOWN)
    assert (chat.type, chat.player, chat.message) == ("chat", "Gimli_Jr", "dad look")


def test_parse_advancement_and_deaths():
    adv = parse_line("[18:01:02] [Server thread/INFO]: Tyler has made the advancement [Diamonds!]", KNOWN)
    assert adv.type == "advancement" and adv.player == "Tyler"
    for msg in ("Tyler was slain by Zombie", "Tyler fell from a high place", "Gimli_Jr drowned",
                "Tyler was blown up by Creeper", "Gimli_Jr tried to swim in lava"):
        ev = parse_line(f"[18:01:02] [Server thread/INFO]: {msg}", KNOWN)
        assert ev and ev.type == "death", msg


def test_parse_ignores_noise():
    lines = [
        "[18:01:02] [Server thread/INFO]: Tyler lost connection: Disconnected",
        "[18:01:02] [Server thread/WARN]: Tyler moved too quickly! 1,2,3",
        "[18:01:02] [Server thread/INFO]: Stranger was slain by Zombie",  # not a known player
        "[18:01:02] [Worker-Main-1/INFO]: Tyler joined the game",          # not the server thread
        "random garbage",
    ]
    assert all(parse_line(line, KNOWN) is None for line in lines)


def test_parse_paper_layout():
    ev = parse_line("[18:01:02 INFO]: Tyler joined the game", KNOWN)
    assert ev.type == "join" and (ev.hour, ev.minute, ev.second) == (18, 1, 2)


def test_tick_and_memory_parsing():
    out = "The game is running normally\nTarget tick rate: 20.0 per second.\nAverage time per tick: 62.5ms (Target: 50.0ms)"
    assert parse_tick_query(out) == (16.0, 62.5)
    assert parse_tick_query("Unknown or incomplete command") == (None, None)
    assert parse_mem_mb("2.5GB") == 2560.0
    assert parse_mem_mb("512.0MB") == 512.0
    assert parse_mem_mb(None) is None


# ---------------------------------------------------------------- recorder
def _server(client, sid):
    from app import servers as S
    client.get("/api/servers")
    return S.registry.servers[sid]


def test_log_tail_records_events_and_resumes(client, sid):
    srv = _server(client, sid)
    logs = srv.dir / "logs"
    logs.mkdir(exist_ok=True)
    now = datetime.now(db.tz())
    t1 = (now - timedelta(minutes=10)).strftime("%H:%M:%S")
    t2 = now.strftime("%H:%M:%S")
    (logs / "latest.log").write_text(
        f"[{t1}] [Server thread/INFO]: Tyler joined the game\n"
        f"[{t1}] [Server thread/INFO]: <Tyler> hello\n"
        f"[{t2}] [Server thread/INFO]: Gimli_Jr joined the game\n")
    pending = recorder.tail_server(srv)
    # The old join and the chat are recorded but not pushed; the fresh join is.
    assert pending == []                                  # join/leave alerts come from the online check
    evs = db.events(sid)
    assert [e["type"] for e in evs][:3] == ["join", "chat", "join"]
    assert evs[0]["uuid"] == helpers.PLAYERS[1][1]
    # A second pass with no new lines does nothing
    assert recorder.tail_server(srv) == []
    with (logs / "latest.log").open("a") as fh:
        fh.write(f"[{t2}] [Server thread/INFO]: Gimli_Jr was slain by Zombie\n")
    assert recorder.tail_server(srv) == [("death", "Gimli_Jr was slain by Zombie")]
    # Rotation: a new file is read from the start
    (logs / "latest.log").write_text(f"[{t2}] [Server thread/INFO]: Tyler left the game\n")
    assert recorder.tail_server(srv) == []


def test_sessions_and_daily_split():
    zone = db.tz()
    midnight = datetime.combine(datetime.now(zone).date(), datetime.min.time(), zone).timestamp()
    s = midnight - 1800  # 30 min before midnight ... 1h after
    db.x("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?)",
         ("split-test", "Tyler", s, s + 5400, s + 5400))
    days = db.daily_playtime("split-test", 2)
    assert days[0]["players"]["Tyler"] == 1800
    assert days[1]["players"]["Tyler"] == 3600


def test_update_sessions_open_and_close():
    now = time.time()
    joined, left = db.update_sessions("sess-test", {"Tyler": None}, now)
    assert joined == ["Tyler"] and left == []
    joined, left = db.update_sessions("sess-test", {"Tyler": None}, now + 30)
    assert joined == [] and left == []
    joined, left = db.update_sessions("sess-test", {}, now + 60)
    assert left == ["Tyler"]
    s = db.sessions("sess-test")[0]
    assert s["seconds"] == 30 and s["open"] is False


def test_poll_records_metric_when_offline(client, sid):
    import asyncio
    srv = _server(client, sid)
    asyncio.run(recorder.poll_server(srv))  # RCON unreachable, no Crafty -> offline sample
    latest = db.metrics(sid, "6h")["latest"]
    assert latest["running"] == 0


# ---------------------------------------------------------------- API
def test_history_endpoints(client, sid, tyler):
    a = client.get(f"/api/servers/{sid}/activity?days=7").json()
    assert len(a["daily"]) == 7
    evs = client.get(f"/api/servers/{sid}/events?types=chat").json()
    assert all(e["type"] == "chat" for e in evs)
    m = client.get(f"/api/servers/{sid}/metrics?range=24h").json()
    assert m["range"] == "24h" and "points" in m
    h = client.get(f"/api/servers/{sid}/players/{tyler}/history").json()
    assert len(h["daily"]) == 30 and all("seconds" in d for d in h["daily"])
    players = client.get(f"/api/servers/{sid}/players").json()["players"]
    assert all("today_seconds" in p for p in players)


def test_notification_settings(client, viewer):
    url = "/api/settings/notifications"
    assert viewer.put(url, json={"ntfy_url": "https://ntfy.example/t"}).status_code == 403
    hdr = {}
    r = client.put(url, json={"ntfy_url": "https://ntfy.example/t", "ntfy_token": "tk", "events": ["join", "death", "bogus"]}, headers=hdr)
    body = r.json()
    assert body["events"] == ["join", "death"]
    assert body["ntfy_token_set"] is True and "ntfy_token" not in body
    assert notify.get_config()["ntfy_token"] == "tk"
    client.put(url, json={"ntfy_url": "", "ntfy_token": ""}, headers=hdr)
    r = client.post(f"{url}/test", headers=hdr).json()
    assert r["ok"] is False and "No notification channel" in r["errors"][0]


def test_quiet_hours_wraparound():
    assert notify._in_quiet_hours({"quiet_enabled": True, "quiet_start": "00:00", "quiet_end": "23:59"}) is True
    assert notify._in_quiet_hours({"quiet_start": "", "quiet_end": ""}) is False


# ---------------------------------------------------------------- timeline
def _seed_timeline(sid: str, base: float) -> None:
    def sess(player, start, end):
        db.x("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?)",
             (sid, player, start, end, end))
    sess("Tyler", base, base + 3600)            # older
    sess("Gimli_Jr", base + 600, base + 1800)   # overlaps Tyler
    sess("Tyler", base + 7200, base + 9000)     # newest
    for ts, typ, p, msg in [
        (base + 5, "join", "Tyler", "Tyler joined the game"),
        (base + 100, "death", "Tyler", "Tyler drowned"),
        (base + 700, "chat", "Gimli_Jr", "hi dad"),
        (base + 4000, "server", None, "Server stopped"),
        (base + 7300, "advancement", "Tyler", "Tyler has made the advancement [Diamonds!]"),
        (base + 8990, "leave", "Tyler", "Tyler left the game"),
    ]:
        db.add_event(sid, ts, typ, msg, p)


def test_timeline_merges_overlapping_sessions():
    sid, base = "tl-test", 1_700_000_000.0
    _seed_timeline(sid, base)
    t = db.timeline(sid, before=base + 20000)
    kinds = [(i["kind"], i.get("players"), i.get("message")) for i in t["items"]]
    assert kinds == [("session", ["Tyler"], None), ("event", None, "Server stopped"),
                     ("group", ["Tyler", "Gimli_Jr"], None)]
    solo, _, group = t["items"]
    assert [e["type"] for e in solo["events"]] == ["advancement"]  # its leave line is the block edge
    # The group reads in time order across both players, joins included
    assert [(e["type"], e["player"]) for e in group["events"]] == [("join", "Tyler"), ("death", "Tyler"), ("chat", "Gimli_Jr")]
    assert group["start"] == base and group["end"] == base + 3600 and group["seconds"] == 3600
    assert group["counts"] == {"join": 1, "death": 1, "chat": 1}
    assert t["next_before"] is None


def test_timeline_paging_keeps_every_event_once():
    sid, base = "tl-page", 1_700_000_000.0
    _seed_timeline(sid, base)
    seen, blocks, before = [], 0, base + 20000
    for _ in range(10):
        t = db.timeline(sid, before=before, sessions_limit=1)
        for it in t["items"]:
            blocks += it["kind"] != "event"
            seen += [e["id"] for e in it.get("events", [])] + ([it["id"]] if it["kind"] == "event" else [])
        if not t["next_before"]:
            break
        before = t["next_before"]
    assert blocks == 2  # the solo session and the group, each shown once
    assert len(seen) == len(set(seen)) == 5  # advancement, join, death, chat, server stop


def test_timeline_player_filter_keeps_group_context():
    sid, base = "tl-filter", 1_700_000_000.0
    _seed_timeline(sid, base)
    t = db.timeline(sid, player="Gimli_Jr", before=base + 20000, include_chat=False)
    blocks = [i for i in t["items"] if i["kind"] != "event"]
    assert [b["players"] for b in blocks] == [["Tyler", "Gimli_Jr"]]  # Gimli played with Tyler
    assert all(e["type"] != "chat" for e in blocks[0]["events"])
    assert not any(i.get("message") == "Server stopped" and i["ts"] > base + 9000 for i in t["items"])


def test_duplicate_log_lines_stored_once():
    db.add_event("dup-test", 123.0, "chat", "hello", "Tyler")
    db.add_event("dup-test", 123.0, "chat", "hello", "Tyler")
    assert len(db.events("dup-test")) == 1


def test_timeline_endpoint(client, sid):
    r = client.get(f"/api/servers/{sid}/timeline?chat=false")
    assert r.status_code == 200 and "items" in r.json()


def test_memory_bytes_from_crafty():
    assert parse_mem_mb(1646161920) == 1569.9          # newer Crafty: bytes
    assert parse_mem_mb("1646161920") == 1569.9
    assert parse_mem_mb(2048) == 2048.0                # small bare numbers are MB
    db.add_metric("mem-fix", time.time(), True, 0, 1.0, 1646161920.0, 5.0, None, None)
    # The start-up fix-up converts values stored in bytes by earlier builds
    db.conn().execute("UPDATE metrics SET mem_mb = ROUND(mem_mb / 1048576.0, 1) WHERE mem_mb > 100000")
    assert db.metrics("mem-fix", "6h")["latest"]["mem_mb"] == 1569.9


def test_log_in_another_time_zone_still_counts_as_now(client, sid):
    """Crafty's container on UTC, Solstone on Chicago time: the log's clock is hours off.
    Joins written just now must still count as now (fireworks, notifications)."""
    from app import fwshow
    from app.recorder import recorder
    srv = _server(client, sid)
    logs = srv.dir / "logs"
    logs.mkdir(exist_ok=True)
    ahead = datetime.now(db.tz()) + timedelta(hours=5)                       # the log is 5 h ahead
    (logs / "latest.log").write_text(f"[{ahead.strftime('%H:%M:%S')}] [Server thread/INFO]: MomCrafts joined the game\n")
    db.x("DELETE FROM log_state WHERE server_id=?", (sid,))
    recorder._offsets.pop(sid, None)
    last = fwshow.feed_since(-1, True)["last"]
    assert recorder.tail_server(srv) == []
    ev = db.events(sid, types=["join"], player="MomCrafts", limit=1)[0]
    assert abs(ev["ts"] - time.time()) < 120
    pushed = [i for i in fwshow.feed_since(last, True)["items"] if i["event"] == "join" and i["player"] == "MomCrafts"]
    assert len(pushed) == 1
    # the online check noticing the same join doesn't set off a second firework
    assert fwshow.pushed_recently(sid, "join", "momcrafts")
    recorder._offsets.pop(sid, None)


def test_join_and_leave_alerts_come_from_the_online_check(client, sid, monkeypatch):
    """With a server log present, join/leave pushes still come from who's online (the log's
    clock can be off), once per change, and not for whoever is on when Solstone starts."""
    import asyncio

    from app import recorder as rec_mod
    from app import servers as S
    srv = _server(client, sid)
    srv.dir.joinpath("logs").mkdir(exist_ok=True)
    srv.dir.joinpath("logs", "latest.log").touch()
    sent = []
    monkeypatch.setattr(rec_mod, "maybe_notify", lambda t, name, msg, sid=None: sent.append((t, msg)))
    online = {"names": ["Tyler"]}

    async def fake_online(_srv):
        return list(online["names"]), "rcon"
    monkeypatch.setattr(S, "online_players", fake_online)
    monkeypatch.setattr(srv, "rcon_conf", lambda: None)
    recorder._running_state.pop(srv.id, None)
    db.update_sessions(srv.id, {}, time.time())
    asyncio.run(recorder.poll_server(srv))               # first look after a start: no alerts
    assert sent == []
    online["names"] = ["Tyler", "Gimli_Jr"]
    asyncio.run(recorder.poll_server(srv))
    online["names"] = ["Tyler"]
    asyncio.run(recorder.poll_server(srv))
    assert sent == [("join", "Gimli_Jr joined the game"), ("leave", "Gimli_Jr left the game")]
    db.update_sessions(srv.id, {}, time.time())
