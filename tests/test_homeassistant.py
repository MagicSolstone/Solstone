"""Home Assistant: a key that can only read the servers' status, at one address, and the settings to paste."""
from app import homeassistant, settings_store


def test_a_key_reads_the_status_and_nothing_else(client, viewer, anon, sid):
    assert viewer.post("/api/manage/ha/keys", json={"name": "HA"}).status_code == 403
    r = client.post("/api/manage/ha/keys", json={"name": "Home Assistant", "names": True}).json()
    key, kid = r["key"], r["id"]
    try:
        assert key.startswith("sol_ha_") and all("hash" not in k and "key" not in k for k in r["keys"])
        assert key not in str(settings_store.load())                                      # only its hash is kept
        assert anon.get("/api/ha/status").status_code == 401
        assert anon.get("/api/ha/status", headers={"Authorization": "Bearer sol_ha_wrong"}).status_code == 401
        homeassistant._cache.clear()
        st = anon.get("/api/ha/status", headers={"Authorization": f"Bearer {key}"}).json()
        srv = next(v for v in st["servers"].values() if v["id"] == sid)
        assert {"online", "players_online", "players_max", "tps", "cpu", "mem_mb", "uptime_7d", "version", "players", "backup_overdue"} <= set(srv)
        assert isinstance(srv["players"], list) and "join_requests" in st and st["solstone"]["version"]
        # the key only reads this: nothing else, and no signing in with it
        assert anon.get("/api/servers", headers={"Authorization": f"Bearer {key}"}).status_code == 401
        assert anon.get(f"/api/servers/{sid}/players", params={"key": key}).status_code == 401
        # names off: counts only
        client.put(f"/api/manage/ha/keys/{kid}", json={"names": False})
        st = anon.get("/api/ha/status", params={"key": key}).json()
        srv = next(v for v in st["servers"].values() if v["id"] == sid)
        assert "players" not in srv and "played_today_minutes" not in srv and "players_online" in srv
        assert next(k for k in client.get("/api/manage/ha").json()["keys"] if k["id"] == kid)["last_used"]
    finally:
        client.delete(f"/api/manage/ha/keys/{kid}")
    assert anon.get("/api/ha/status", params={"key": key}).status_code == 401               # removed: it stops working


def test_the_settings_to_paste_into_home_assistant(client, sid):
    import yaml as Y

    class Loader(Y.SafeLoader):
        pass
    Loader.add_constructor("!secret", lambda loader, node: f"<secret {node.value}>")
    r = client.get("/api/manage/ha/yaml", params={"base": "http://192.168.1.20:8085"}).json()
    conf = Y.load(r["yaml"], Loader=Loader)
    rest = conf["rest"][0]
    assert rest["resource"] == "http://192.168.1.20:8085/api/ha/status" and rest["headers"]["Authorization"] == "<secret solstone_auth>"
    key = r["servers"][0]["key"]
    ids = {s["unique_id"] for s in rest["sensor"]} | {s["unique_id"] for s in rest["binary_sensor"]}
    assert {f"solstone_{key}_players_online", f"solstone_{key}_tps", f"solstone_{key}_online", "solstone_join_requests"} <= ids
    tps = next(s for s in rest["sensor"] if s["unique_id"] == f"solstone_{key}_tps")
    assert f"value_json.servers.{key}.tps" in tps["value_template"] and "is not none" in tps["availability"]
    assert client.get("/api/manage/ha/yaml", params={"base": "javascript:alert(1)"}).status_code == 400


def test_short_names_for_home_assistant():
    taken: set[str] = set()
    assert homeassistant.slug("Jusczak Family Realm", taken) == "jusczak_family_realm"
    assert homeassistant.slug("Jusczak Family Realm!", taken) == "jusczak_family_realm_2"
    assert homeassistant.slug("2nd World", taken) == "s_2nd_world"
