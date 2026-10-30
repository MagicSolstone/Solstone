"""Going by your Minecraft name only (the old login gone, everything carried over), and what goes with a deleted account."""
from app import auth, db, fireworks, playtime, settings_store


def _design(author, name):
    return {"id": f"{author}-{name}", "name": name, "author": author, "in_show": True}


def test_use_your_minecraft_name_as_your_login(client, anon):
    u = auth.create_user("old_login", "long-enough-1", "admin", check=False)
    auth.add_player(u.id, ("00000000-0000-0000-0000-0000000000a1", "SkyTyler"))
    auth.set_display_name(u.id, "Tyler")
    keep_fw, keep_snd = fireworks._load(), fireworks.sounds()
    fireworks._save([*keep_fw, _design("old_login", "Blue burst")])
    settings_store.save_section("sounds", [*keep_snd, {"id": "s1", "name": "Pop", "author": "old_login", "sfx": {}}])
    auth.audit("old_login", None, "test", "before the rename")
    try:
        c = anon
        assert c.post("/api/auth/login", json={"username": "old_login", "password": "long-enough-1"}).status_code == 200
        r = c.post("/api/auth/use-minecraft-name", json={}).json()["user"]
        assert r["username"] == "SkyTyler" and r["shown"] == "SkyTyler" and r["display_name"] is None
        assert any(d["author"] == "SkyTyler" for d in fireworks._load() if d["name"] == "Blue burst")
        assert any(s["author"] == "SkyTyler" for s in fireworks.sounds() if s["id"] == "s1")
        assert not db.q("SELECT 1 FROM audit WHERE username='old_login'")                  # gone completely
        c.post("/api/auth/logout")
        assert c.post("/api/auth/login", json={"username": "old_login", "password": "long-enough-1"}).status_code == 401
        assert c.post("/api/auth/login", json={"username": "skytyler", "password": "long-enough-1"}).status_code == 200
    finally:
        fireworks._save(keep_fw)
        settings_store.save_section("sounds", keep_snd)
        auth.delete_user(u.id)


def test_a_name_another_account_uses_isnt_taken(client):
    a = auth.create_user("first_one", "long-enough-1", "player", check=False)
    b = auth.create_user("SameName", "long-enough-1", "player", check=False)
    auth.add_player(a.id, ("00000000-0000-0000-0000-0000000000a2", "SameName"))
    try:
        try:
            auth.use_player_name(a.id)
            raise AssertionError("should have been refused")
        except Exception as e:
            assert getattr(e, "status_code", 0) == 409
    finally:
        auth.delete_user(a.id)
        auth.delete_user(b.id)


def test_deleting_an_account_takes_what_was_only_theirs():
    u = auth.create_user("goes_away", "long-enough-1", "player", check=False)
    auth.add_player(u.id, ("00000000-0000-0000-0000-0000000000a3", "LeavingKid"))
    keep_fw, keep_snd = fireworks._load(), fireworks.sounds()
    fireworks._save([*keep_fw, _design("goes_away", "Mine"), _design("someone_else", "Theirs")])
    settings_store.save_section("sounds", [*keep_snd, {"id": "s2", "name": "Fizz", "author": "goes_away", "sfx": {}}])
    settings_store.save_section("fw_signatures", {"leavingkid": "x1", "other": "x2"})
    pt = playtime.config()
    pt["people"][f"u{u.id}"] = {"bedtime": True, "limit": 60, "weekend_limit": 0}
    playtime.save(pt)
    try:
        auth.delete_user(u.id)
        names = [d["name"] for d in fireworks._load()]
        assert "Mine" not in names and "Theirs" in names
        assert not [s for s in fireworks.sounds() if s["id"] == "s2"]
        assert settings_store.load()["fw_signatures"] == {"other": "x2"}
        people = playtime.config()["people"]
        assert f"u{u.id}" not in people and people["p:leavingkid"]["limit"] == 60          # their limits still apply in the game
    finally:
        fireworks._save(keep_fw)
        settings_store.save_section("sounds", keep_snd)
        settings_store.save_section("fw_signatures", {})
        pt = playtime.config()
        pt["people"].pop("p:leavingkid", None)
        playtime.save(pt)


def test_finished_votes_keep_their_result_when_an_account_goes():
    from app import community
    u = auth.create_user("voter_gone", "long-enough-1", "player", check=False)
    done = community.create_poll({"question": "Best mob?", "options": ["Cat", "Bee"]})
    still = community.create_poll({"question": "Next build?", "options": ["Castle", "Boat"]})
    try:
        community.vote(done["id"], f"u{u.id}", done["options"][0]["id"])
        community.vote(still["id"], f"u{u.id}", still["options"][0]["id"])
        community.close_now(done["id"])
        auth.delete_user(u.id)
        assert community.view(community.get_poll(done["id"]), "p:someone", admin=True)["counts"][done["options"][0]["id"]] == 1        # history stays
        assert community.view(community.get_poll(still["id"]), "p:someone", admin=True)["counts"][still["options"][0]["id"]] == 0      # still open: taken back
        assert not db.q("SELECT 1 FROM poll_votes WHERE voter=?", (f"u{u.id}",))                      # nobody's any more
    finally:
        community.delete_poll(done["id"])
        community.delete_poll(still["id"])


def test_unused_pictures_found_and_removed(client):
    import time

    from app import site
    folder = site.app_config.data_dir / "site" / "images"
    folder.mkdir(parents=True, exist_ok=True)
    old = time.time() - 3 * 86400
    import os
    for name in ("aaaaaaaaaaaaaaaa.png", "bbbbbbbbbbbbbbbb.png", "cccccccccccccccc.png"):
        (folder / name).write_bytes(b"x")
        os.utime(folder / name, (old, old))
    (folder / "dddddddddddddddd.png").write_bytes(b"new")                  # just uploaded: not counted yet
    p = site.save({"title": "Pics", "body": "![a](/api/public/images/aaaaaaaaaaaaaaaa.png)", "category": "news"}, "admin")
    try:
        names = {x["name"] for x in client.get("/api/site/images/unused").json()["images"]}
        assert {"bbbbbbbbbbbbbbbb.png", "cccccccccccccccc.png"} <= names and "aaaaaaaaaaaaaaaa.png" not in names and "dddddddddddddddd.png" not in names
        assert client.delete("/api/site/images/unused").json()["removed"] >= 2
        assert (folder / "aaaaaaaaaaaaaaaa.png").is_file() and not (folder / "bbbbbbbbbbbbbbbb.png").exists()
    finally:
        site.delete(p["id"])
        for f in folder.glob("[a-d]" * 16 + ".png"):
            f.unlink()


def test_a_new_minecraft_name_follows_through():
    from app import accounts
    u = auth.create_user("OldName", "long-enough-1", "player", check=False)
    auth.add_player(u.id, ("00000000-0000-0000-0000-0000000000a4", "OldName"))
    settings_store.save_section("fw_signatures", {"oldname": "sig1"})
    try:
        assert accounts.follow_name("00000000-0000-0000-0000-0000000000a4", "NewName") == "OldName"
        v = auth.get_user(u.id)
        assert v.username == "NewName" and [p["name"] for p in v.players] == ["NewName"] and v.shown == "NewName"
        assert settings_store.load()["fw_signatures"] == {"newname": "sig1"}
        assert auth._login_rows("NewName") and not auth._login_rows("OldName")                      # signs in as the new name
    finally:
        settings_store.save_section("fw_signatures", {})
        auth.delete_user(u.id)
