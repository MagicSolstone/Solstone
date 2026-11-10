"""Fishing on the website: which servers have it (the Tide fishing mod), and the journal of catches Solstone kept
from before (when its own data pack weighed vanilla fish). The pack was taken out in 1.16: retire_pack switches an
old copy off and removes it from the world."""
from __future__ import annotations

import logging
import re

from . import db, fishpack
from .rcon import RconError

log = logging.getLogger("solstone.fishing")
QUALITY_COLOR = {0: "gray", 1: "white", 2: "green", 3: "aqua", 4: "gold", 5: "light_purple"}
_retired: set[str] = set()              # servers whose world has been checked for the old pack (once each time Solstone runs)


def journal_on(srv) -> bool:
    """The fishing journal (every catch kept, with its weight, on the website): only with the Tide fishing mod.
    On a vanilla server fishing is just part of the game, so Solstone leaves it alone."""
    from . import tide
    try:
        return bool(tide.installed(srv))
    except Exception:
        return False


def available(srv) -> str | None:
    """What this server fishes with, for showing the Fishing tab, its leaderboards and fishing contests: "tide"
    (the Tide fishing mod), or None. Without Tide fishing stays plain vanilla: no Fishing tab, boards or contests."""
    from . import tide
    if not srv.is_java:
        return None
    return "tide" if tide.installed(srv) else None


async def retire_pack(srv) -> bool:
    """Solstone's old data pack, if it's still in this world: switched off in the game and its file removed (nothing
    uses it any more). Looked for once per server each time Solstone runs. True if one was found."""
    if srv.id in _retired:
        return False
    _retired.add(srv.id)
    try:
        path = srv.world_dir / "datapacks" / fishpack.PACK_FILE
        if not path.is_file():
            return False
    except OSError:
        return False
    if srv.rcon_conf():
        try:
            await srv.rcon(f'datapack disable "file/{fishpack.PACK_FILE}"')
        except RconError:
            _retired.discard(srv.id)                 # the server isn't answering: again next time round
            return False
    try:
        path.unlink()
        log.info("removed Solstone's old data pack from %s", srv.display_name)
    except OSError as e:                              # (the folder's read-only for Solstone: it stays, switched off)
        log.info("couldn't remove the old data pack from %s: %s", srv.display_name, e)
    return True


_OLD_QUALITY = {"Poor": 0, "Normal": 1, "Quality": 2, "Fine": 2, "Prime": 3, "Good": 2, "Great": 3, "Trophy": 3, "Exquisite": 4, "Legendary": 4, "Mythic": 5}
_CAUGHT = re.compile(r"^(?P<who>\S+) caught an? (?P<fish>.+?) · (?P<lb>[\d.]+) lb · (?P<p>\d+) points$")


def _backfill(sid: str) -> None:
    """Fill the journal from the activity feed once (catches from before it existed)."""
    if db.q("SELECT 1 FROM fish_catches WHERE server_id=? LIMIT 1", (sid,)):
        return
    by_name = {v[0]: k for k, v in fishpack.SPECIES.items()}
    for e in db.events(sid, ["fish", "bigfish"], None, 5000):
        m = _CAUGHT.match(e["message"] or "")
        if not m:
            continue
        fish, quality = m.group("fish"), 1
        for qn, qi in _OLD_QUALITY.items():
            if fish.startswith(qn + " ") and fish[len(qn) + 1:] in by_name:
                fish, quality = fish[len(qn) + 1:], qi
                break
        if fish not in by_name:
            continue
        db.x("INSERT INTO fish_catches(server_id, ts, player, species, name, quality, quality_name, weight, points) VALUES (?,?,?,?,?,?,?,?,?)",
             (sid, e["ts"], m.group("who"), by_name[fish], fish, quality, fishpack.QUALITIES[min(quality, len(fishpack.QUALITIES) - 1)][0],
              float(m.group("lb")), int(m.group("p"))))


def journal(sid: str) -> dict:
    """Everyone's fishing journal from the old pack's days: which species each player caught, their best of each,
    server records, and the latest catches."""
    _backfill(sid)
    rows = db.fish_catches(sid)
    players: dict[str, dict] = {}
    records: dict[str, dict] = {}
    for r in rows:
        p = players.setdefault(r["player"], {"name": r["player"], "species": {}, "total": 0, "points": 0, "qualities": [0] * len(fishpack.QUALITIES)})
        p["total"] += 1
        p["points"] += r["points"]
        if 0 <= r["quality"] < len(p["qualities"]):
            p["qualities"][r["quality"]] += 1
        sp = p["species"].setdefault(r["species"], {"count": 0, "best_lb": 0, "best_quality": 0, "first": r["ts"]})
        sp["count"] += 1
        sp["best_lb"] = max(sp["best_lb"], r["weight"])
        sp["best_quality"] = max(sp["best_quality"], r["quality"])
        rec = records.get(r["species"])
        if not rec or r["weight"] > rec["lb"]:
            records[r["species"]] = {"player": r["player"], "lb": r["weight"], "quality": r["quality"], "ts": r["ts"]}
    recent = [{"player": r["player"], "species": r["species"], "name": r["name"], "quality": r["quality"], "lb": r["weight"], "points": r["points"], "ts": r["ts"]}
              for r in rows[-20:]][::-1]
    return {"species": fishpack.guide(), "qualities": fishpack.qualities(), "players": sorted(players.values(), key=lambda p: (-len(p["species"]), -p["points"])),
            "records": records, "recent": recent}
