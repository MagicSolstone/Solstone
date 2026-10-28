"""The welcome message in the game's chat when someone joins, and the rules page."""
import json

from app import servers as S
from app import settings_store, welcome


def test_colours_links_and_placeholders():
    text = welcome.fill("&6&lHi {player}&r on {server}\n&aRules: https://fbc.example/guides/rules.\nstill green &rplain", ".Kid", "Family")
    cmds = welcome.commands(".Kid", text)
    assert len(cmds) == 3 and all(c.startswith("tellraw .Kid [") for c in cmds)
    first = json.loads(cmds[0][len("tellraw .Kid "):])
    assert {"text": "Hi .Kid", "color": "gold", "bold": True} in first and {"text": " on Family"} in first
    link = next(p for p in json.loads(cmds[1][len("tellraw .Kid "):]) if p["text"].startswith("https"))
    assert link["text"] == "https://fbc.example/guides/rules"                       # the full stop isn't part of it
    assert link["clickEvent"]["value"] == link["click_event"]["url"] == link["text"]  # before and after 1.21.5
    third = json.loads(cmds[2][len("tellraw .Kid "):])
    assert third[1] == {"text": "still green ", "color": "green"} and third[2] == {"text": "plain"}   # colours carry on


def test_clean_limits_lines_and_length():
    assert welcome.clean("\n".join(["x" * 50] * 12)).count("\n") == welcome.MAX_LINES - 1
    assert len(welcome.clean("x" * 300)) == welcome.LINE_LEN
    assert len(welcome.clean("\n".join(["x" * 300] * 8))) <= welcome.MAX_LEN


def test_first_time_or_every_time(client, sid):
    srv = S.registry.servers[sid]
    try:
        r = client.put(f"/api/servers/{sid}/settings", json={"welcome": "Hi {player}", "welcome_when": "sometimes"})
        assert r.json()["welcome_when"] == "off"
        assert welcome.fill("{rules}", "A", "B") == "http://testserver/guides/rules"          # the address the admin used
        assert welcome.due(srv, "New_Kid") is None                                   # off
        client.put(f"/api/servers/{sid}/settings", json={"welcome_when": "first"})
        srv = S.registry.servers[sid]
        welcome._recent.clear()
        assert welcome.due(srv, "New_Kid") == ['tellraw New_Kid [{"text": ""}, {"text": "Hi New_Kid"}]']
        welcome._recent.clear()
        assert welcome.due(srv, "New_Kid") is None                                   # only the first time
        client.put(f"/api/servers/{sid}/settings", json={"welcome_when": "every"})
        srv = S.registry.servers[sid]
        welcome._recent.clear()
        assert welcome.due(srv, "New_Kid")
        assert welcome.due(srv, "New_Kid") is None                                   # log and online check: once
    finally:
        client.put(f"/api/servers/{sid}/settings", json={"welcome": "", "welcome_when": "off"})
        settings_store.save_section("welcomed", {})
        welcome._recent.clear()


def test_trying_it_needs_someone_on(client, viewer, sid):
    assert viewer.post(f"/api/servers/{sid}/welcome/try", json={"player": "Tyler", "text": "Hi"}).status_code == 403
    assert client.post(f"/api/servers/{sid}/welcome/try", json={"player": "Tyler", "text": ""}).status_code == 400
    assert client.post(f"/api/servers/{sid}/welcome/try", json={"player": "Nobody_On", "text": "Hi"}).status_code == 400


def test_asking_to_join_needs_the_rules_ticked(client, anon):
    from app import main, signup
    signup._sent.clear()
    client.put("/api/settings/site", json={"join_requests": True, "guide_rules": "## Be kind"})
    try:
        r = anon.post("/api/public/join-request", json={"player": "Rule_Kid"})
        assert r.status_code == 400 and "rules" in r.json()["detail"]
        assert anon.get("/api/public/site").json()["guide_rules"] == "## Be kind"
    finally:
        client.put("/api/settings/site", json={"join_requests": False, "guide_rules": ""})
        main.settings_store.save_section("join_requests", [])
        signup._sent.clear()
