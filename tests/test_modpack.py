"""The family modpack (packwiz): what Prism's installer reads, served from the server's own
jars plus projects from Modrinth (faked here)."""
import hashlib
import tomllib

import pytest

# A tiny fake Modrinth: projects, their newest version for 26.3, and search
FAKE = {
    "sodium": {"title": "Sodium", "versions": [{"id": "s2", "project_id": "AANobbMI", "version_number": "0.7.0", "deps": []}]},
    "lambdynamiclights": {"title": "LambDynamicLights", "versions": [{"id": "l1", "project_id": "yBW8D80W", "version_number": "4.13.0",
                                                                       "deps": ["P7dR8mSH", "spruce"]}]},
    "P7dR8mSH": {"title": "Fabric API", "slug": "fabric-api", "versions": [{"id": "f1", "project_id": "P7dR8mSH", "version_number": "0.163.0", "deps": []}]},
    "spruce": {"title": "SpruceUI", "versions": [{"id": "sp1", "project_id": "spruce", "version_number": "6.0.0", "deps": []}]},
    "fresh-animations": {"title": "Fresh Animations", "versions": [{"id": "fa1", "project_id": "fresh", "version_number": "1.10", "deps": []}]},
}


def _version(slug, v):
    return {"id": v["id"], "project_id": v["project_id"], "version_number": v["version_number"],
            "files": [{"primary": True, "filename": f"{slug}-{v['version_number']}.jar", "url": f"https://cdn.modrinth.com/data/{slug}/{v['id']}.jar",
                       "hashes": {"sha512": hashlib.sha512(v["id"].encode()).hexdigest(), "sha1": "x"}, "size": 10}],
            "dependencies": [{"project_id": d, "dependency_type": "required"} for d in v["deps"]]}


@pytest.fixture()
def modrinth(monkeypatch):
    from app import modpack, settings_store
    settings_store.save_section(modpack.SECTION, {})
    calls = []

    async def fake(url, params=None):
        calls.append((url, params))
        path = url.split("/v2/", 1)[1]
        if path == "search":
            q = params["query"].lower().replace(" ", "")
            hits = [{"slug": k, "title": p["title"], "description": "", "icon_url": None} for k, p in FAKE.items()
                    if q in k.replace("-", "") or q in p["title"].lower().replace(" ", "")]
            return {"hits": hits[:params["limit"]]}
        if path == "versions":                                                     # several versions by id (for sha1)
            import json
            ids = json.loads(params["ids"])
            return [_version(pp.get("slug", k), v) for k, pp in FAKE.items() for v in pp["versions"] if v["id"] in ids]
        parts = path.split("/")
        p = FAKE.get(parts[1])
        if p is None:
            raise AssertionError(f"unexpected {url}")
        if len(parts) == 2:
            return {"slug": p.get("slug", parts[1]), "title": p["title"], "icon_url": None}
        assert '"26.3"' in params["game_versions"] or params["game_versions"]
        return [_version(p.get("slug", parts[1]), v) for v in p["versions"]]
    monkeypatch.setattr(modpack, "_get_json", fake)
    yield modpack, calls
    settings_store.save_section(modpack.SECTION, {})


def _srv(sid):
    import asyncio

    from app import servers as S
    return asyncio.run(S.registry.get(sid))


def test_pack_with_server_jars_and_modrinth(client, sid, modrinth):
    modpack, _calls = modrinth
    base = f"/api/servers/{sid}/modpack"
    v = client.get(base).json()
    assert v["enabled"] is False and {m["id"] for m in v["server_mods"] if m["included"]} == {"tide"}   # fixture has no Fabric API jar
    v = client.put(base, json={"enabled": True}).json()
    assert v["enabled"] and v["url"].endswith("/pack.toml") and "packwiz-installer-bootstrap.jar" in v["command"]
    token = v["url"].split("/api/public/pack/")[1].split("/")[0]

    r = client.post(f"{base}/add", json={"slug": "lambdynamiclights"}).json()
    assert [a["slug"] for a in r["added"]] == ["lambdynamiclights", "fabric-api", "spruce"]          # requirements come along
    r = client.post(f"{base}/add", json={"names": "Sodium\nresourcepack: Fresh Animations\nNo Such Mod"}).json()
    assert [a["slug"] for a in r["added"]] == ["sodium", "fresh-animations"] and r["missing"] == ["No Such Mod"]
    assert {e["slug"]: e["kind"] for e in r["pack"]["extra"]}["fresh-animations"] == "resourcepack"

    # what packwiz-installer reads (no sign-in: the token is the key)
    pub = f"/api/public/pack/{token}"
    pack = tomllib.loads(client.get(f"{pub}/pack.toml").text)
    index_text = client.get(f"{pub}/index.toml").text
    assert pack["pack-format"] == "packwiz:1.1.0" and pack["index"]["hash"] == hashlib.sha256(index_text.encode()).hexdigest()
    index = tomllib.loads(index_text)
    paths = {f["file"] for f in index["files"]}
    assert {"mods/tide.pw.toml", "mods/sodium.pw.toml", "mods/fabric-api.pw.toml", "resourcepacks/fresh-animations.pw.toml"} <= paths
    for f in index["files"]:                                                       # every metafile matches its hash
        body = client.get(f"{pub}/{f['file']}").text
        assert hashlib.sha256(body.encode()).hexdigest() == f["hash"]
    tide = tomllib.loads(client.get(f"{pub}/mods/tide.pw.toml").text)
    assert tide["side"] == "both" and tide["download"]["hash-format"] == "sha256"
    jar = client.get(tide["download"]["url"].split("testserver", 1)[-1])
    assert jar.status_code == 200 and hashlib.sha256(jar.content).hexdigest() == tide["download"]["hash"]
    sodium = tomllib.loads(client.get(f"{pub}/mods/sodium.pw.toml").text)
    assert sodium["side"] == "client" and sodium["download"]["url"].startswith("https://cdn.modrinth.com/")

    # only what the pack includes is served; a wrong token or a disabled pack gets nothing
    assert client.get(f"{pub}/jar/lithium.jar").status_code == 404
    assert client.get(f"{pub}/jar/..%2Fserver.properties").status_code == 404
    assert client.get("/api/public/pack/wrong-token/pack.toml").status_code == 404
    client.put(base, json={"enabled": False})
    assert client.get(f"{pub}/pack.toml").status_code == 404


def test_server_mod_choice_and_updates(client, sid, modrinth):
    modpack, _calls = modrinth
    base = f"/api/servers/{sid}/modpack"
    client.put(base, json={"enabled": True, "server_mods": ["tide", "lithium"]})
    v = client.post(f"{base}/add", json={"slug": "sodium"}).json()["pack"]
    assert {m["id"] for m in v["server_mods"] if m["included"]} == {"tide", "lithium"}
    assert client.post(f"{base}/check").json()["updates"] == []
    FAKE["sodium"]["versions"].insert(0, {"id": "s3", "project_id": "AANobbMI", "version_number": "0.7.1", "deps": []})
    try:
        ups = client.post(f"{base}/check").json()["updates"]
        assert ups == [{"slug": "sodium", "title": "Sodium", "current": "0.7.0", "latest": "0.7.1"}]
        r = client.post(f"{base}/update-all").json()
        assert r["changed"][0]["to"] == "0.7.1" and r["pack"]["extra"][0]["version"] == "0.7.1"
    finally:
        FAKE["sodium"]["versions"].pop(0)
    v = client.delete(f"{base}/extra/sodium").json()
    assert v["extra"] == []


def test_modpack_is_admin_only(viewer, anon, sid):
    assert viewer.get(f"/api/servers/{sid}/modpack").status_code == 403
    assert anon.get(f"/api/servers/{sid}/modpack").status_code == 401


def test_pack_links_use_the_address_people_came_in_on(client, sid, modrinth, monkeypatch):
    """Behind Cloudflare or a reverse proxy the page is https://playsolstone.com, not the container's
    http address: the pack's links must say so (a browser won't download http from an https page)."""
    from app import config as C
    base = f"/api/servers/{sid}/modpack"
    behind = {"x-forwarded-proto": "https", "x-forwarded-host": "playsolstone.com"}
    v = client.put(base, json={"enabled": True}, headers=behind).json()
    assert v["url"].startswith("https://playsolstone.com/api/public/pack/") and v["bootstrap"] == "/api/public/packwiz-installer-bootstrap.jar"
    token = v["url"].split("/api/public/pack/")[1].split("/")[0]
    tide = client.get(f"/api/public/pack/{token}/mods/tide.pw.toml", headers=behind).text
    assert 'url = "https://playsolstone.com/api/public/pack/' in tide
    monkeypatch.setattr(C.config, "public_url", "https://mc.example.org")           # PUBLIC_URL wins
    assert client.get(base).json()["url"].startswith("https://mc.example.org/")


def test_one_file_to_import(client, anon, sid, modrinth, monkeypatch):
    import io
    import json
    import zipfile

    modpack, _calls = modrinth
    monkeypatch.setattr(modpack, "fabric_loader_version", lambda srv: "0.19.5")
    base = f"/api/servers/{sid}/modpack"
    client.post(f"{base}/add", json={"names": "Sodium\nresourcepack: Fresh Animations"})
    assert anon.get(f"{base}.mrpack").status_code in (401, 403)
    r = client.get(f"{base}.mrpack")
    assert r.status_code == 200 and r.headers["content-disposition"].endswith('.mrpack"')
    z = zipfile.ZipFile(io.BytesIO(r.content))
    index = json.loads(z.read("modrinth.index.json"))
    assert index["formatVersion"] == 1 and index["dependencies"]["fabric-loader"] == "0.19.5" and index["dependencies"]["minecraft"]
    by_path = {f["path"]: f for f in index["files"]}
    assert set(by_path) == {"mods/sodium-0.7.0.jar", "resourcepacks/fresh-animations-1.10.jar"}
    assert all(f["hashes"]["sha1"] and f["hashes"]["sha512"] and f["downloads"][0].startswith("https://cdn.modrinth.com/") for f in index["files"])
    assert any(n.startswith("overrides/mods/") and "tide" in n for n in z.namelist())           # the server's own jar goes inside
    # on the website only when the admin says so
    assert anon.get(f"/api/public/modpack/{sid}.mrpack").status_code == 404
    client.put(base, json={"public_download": True})
    assert anon.get(f"/api/public/modpack/{sid}.mrpack").status_code == 200
    client.put(f"/api/servers/{sid}/settings", json={"join_address": "mods.example.net"})
    try:
        join = next(j for j in anon.get("/api/public/site").json()["joins"] if j["id"] == sid)
        assert join["mods"]["download"] == f"/api/public/modpack/{sid}.mrpack"      # even without the mods list ticked
    finally:
        client.put(f"/api/servers/{sid}/settings", json={"join_address": ""})
        client.put(base, json={"public_download": False})
