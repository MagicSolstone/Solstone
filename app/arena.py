"""The mob arena: waves of monsters, each harder than the last.

An admin sets the arena (a spot and a size on the map; players are kept inside it), the spots monsters come out of
(each one picks one at random), and the waves: a difficulty (easy, normal, hard) or their own list, so many of each
monster per wave. Everyone's own things go safely into the vault (kits.py) and they get the kit.

  - Together (co-op): everyone fights the waves as a team. Someone who falls watches until the wave is cleared, then
    comes back in. If everyone's down, it's over: the waves you got through are your score.
  - Everyone for themselves: most monsters defeated wins. Falling means a few seconds watching, then back in.

The monsters are the game's own, marked as the arena's, kept inside it, and removed at the end. Mob griefing is off
while it runs (no creeper holes). By default it's midnight while it runs, with the day-night cycle held (spiders only
fight in the dark); the time of day and the cycle go back to how they were afterwards. It's the whole server's time. Everyone's things are given back exactly afterwards, and they're put back where
they were.
"""
from __future__ import annotations

import random
import re
import time

from . import battle, hud, kits
from . import servers as S

TAG = "solarena"
BREAK = 10                                   # seconds between waves
FOLLOW = 128                                 # at most, how far away a monster notices a player (the arena's width, really)
MOBS = {"zombie": "Zombie", "husk": "Husk", "drowned": "Drowned", "zombie_villager": "Zombie villager", "skeleton": "Skeleton",
        "stray": "Stray", "spider": "Spider", "cave_spider": "Cave spider", "creeper": "Creeper", "slime": "Slime",
        "witch": "Witch", "pillager": "Pillager", "vindicator": "Vindicator", "blaze": "Blaze", "wither_skeleton": "Wither skeleton",
        "piglin_brute": "Piglin brute", "magma_cube": "Magma cube", "ravager": "Ravager", "breeze": "Breeze"}
# Special monsters: the game's own, dressed up. (key: label, what it is, its gear, anything else, and the version it needs)
SPECIALS = {
    "baby_zombie": ("Baby zombie", "zombie", {}, "IsBaby:1b", None),
    "armoured_zombie": ("Zombie in iron armour", "zombie", {"mainhand": "iron_sword", "head": "iron_helmet", "chest": "iron_chestplate"}, "", None),
    "spear_zombie": ("Zombie with a spear", "zombie", {"mainhand": "iron_spear"}, "", (1, 21, 11)),
    "baby_spear_zombie": ("Baby zombie with a spear", "zombie", {"mainhand": "iron_spear"}, "IsBaby:1b", (1, 21, 11)),
    "pumpkin_skeleton": ("Skeleton with a pumpkin head", "skeleton", {"mainhand": "bow", "head": "carved_pumpkin"}, "", None),
    "armoured_skeleton": ("Skeleton in chainmail", "skeleton", {"mainhand": "bow", "head": "chainmail_helmet", "chest": "chainmail_chestplate"}, "", None),
    "sword_skeleton": ("Skeleton with a sword", "skeleton", {"mainhand": "iron_sword"}, "", None),
    "spider_jockey": ("Spider jockey (a skeleton riding a spider)", "spider", {}, "RIDER:skeleton", None),
    "charged_creeper": ("Charged creeper", "creeper", {}, "powered:1b", None),
    "big_slime": ("Big slime", "slime", {}, "Size:3", None),
    "baby_husk": ("Baby husk", "husk", {}, "IsBaby:1b", None),
    "trident_drowned": ("Drowned with a trident", "drowned", {"mainhand": "trident"}, "", None),
}
# what each monster normally carries: summoned with anything extra (like the arena's mark), the game leaves them empty-handed
GEAR = {"skeleton": {"mainhand": "bow"}, "stray": {"mainhand": "bow"}, "wither_skeleton": {"mainhand": "stone_sword"},
        "pillager": {"mainhand": "crossbow"}, "vindicator": {"mainhand": "iron_axe"}, "piglin_brute": {"mainhand": "golden_axe"}}
PLURALS = {"baby_zombie": "baby zombies", "armoured_zombie": "zombies in iron armour", "spear_zombie": "zombies with spears",
           "baby_spear_zombie": "baby zombies with spears", "pumpkin_skeleton": "skeletons with pumpkin heads",
           "armoured_skeleton": "skeletons in chainmail", "sword_skeleton": "skeletons with swords", "spider_jockey": "spider jockeys",
           "charged_creeper": "charged creepers", "big_slime": "big slimes", "baby_husk": "baby husks", "trident_drowned": "drowned with tridents"}
FALLBACK = {"iron_spear": "iron_sword"}          # an older server without spears: a sword instead
SPLITS = ("slime", "magma_cube")                  # their smaller selves come without the arena's mark
MAX_PER_WAVE = 40


def _version(srv) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", getattr(srv, "mc_version", "") or "")[:3]]
    return tuple(nums + [0] * (3 - len(nums))) if nums else (99, 0, 0)        # unknown: assume it's new


def specials_for(srv) -> dict[str, str]:
    """The special monsters this server can have (spears need 1.21.11)."""
    v = _version(srv)
    return {k: x[0] for k, x in SPECIALS.items() if not x[4] or v >= x[4]}


def _gear(srv, gear: dict) -> str:
    """Their gear, in the game's words for this version, and never dropped (no farming the arena for armour)."""
    if not gear:
        return ""
    if _version(srv) < (1, 21, 11):
        gear = {k: FALLBACK.get(v, v) for k, v in gear.items()}
    if _version(srv) >= (1, 21, 5):
        eq = ",".join(f'{k}:{{id:"minecraft:{v}",count:1}}' for k, v in gear.items())
        return f"equipment:{{{eq}}},drop_chances:{{{','.join(f'{k}:0f' for k in gear)}}}"
    item = lambda slot: f'{{id:"minecraft:{gear[slot]}",count:1}}' if gear.get(slot) else "{}"      # noqa: E731
    return (f"HandItems:[{item('mainhand')},{{}}],ArmorItems:[{item('feet')},{item('legs')},{item('chest')},{item('head')}],"
            "HandDropChances:[0f,0f],ArmorDropChances:[0f,0f,0f,0f]")


def summon_nbt(srv, kind: str, tag: str) -> tuple[str, str]:
    """What to summon for a wave's monster (plain or special), and its NBT: marked as the arena's, kept, geared."""
    base, gear, extra = kind, GEAR.get(kind, {}), ""
    if kind in SPECIALS:
        _label, base, gear, extra, _v = SPECIALS[kind]
    mark = f'Tags:["{tag}"],PersistenceRequired:1b'
    if extra.startswith("RIDER:"):                     # a jockey: the rider's marked and geared too
        rider = extra.split(":", 1)[1]
        parts = [mark, f"Passengers:[{{id:\"minecraft:{rider}\",{','.join(x for x in (mark, _gear(srv, GEAR.get(rider, {}))) if x)}}}]"]
    else:
        parts = [mark, _gear(srv, gear), extra]
    return f"minecraft:{base}", "{" + ",".join(x for x in parts if x) + "}"


def preset(level: str) -> list[dict]:
    """Waves for a difficulty: more of them, and tougher monsters as it goes."""
    if level == "easy":
        return [{"zombie": 2 + i} | ({"skeleton": i - 1} if i > 1 else {}) for i in range(5)]
    if level == "hard":
        return [{"zombie": 3 + i, "skeleton": 1 + i // 2} | ({"creeper": i // 3} if i >= 3 else {}) | ({"witch": 1} if i >= 5 else {})
                | ({"vindicator": i // 4} if i >= 6 else {}) | ({"ravager": 1} if i == 9 else {}) for i in range(10)]
    return [{"zombie": 2 + i, "skeleton": i // 2} | ({"spider": i // 3} if i >= 2 else {}) | ({"creeper": 1} if i >= 5 else {})
            for i in range(7)]


def clean_waves(raw) -> list[dict]:
    waves = []
    for w in (raw or [])[:20]:
        if not isinstance(w, dict):
            continue
        wave = {}
        for m, n in w.items():
            try:
                n = max(0, min(20, int(n)))
            except (TypeError, ValueError):
                continue
            if (m in MOBS or m in SPECIALS) and n:
                wave[m] = n
        if wave and sum(wave.values()) <= MAX_PER_WAVE:
            waves.append(wave)
    return waves


def settings(body: dict, num, point) -> dict:
    spots = [point(p, "monster spot") for p in (body.get("mob_spots") or [])[:8] if isinstance(p, dict)]
    if not spots:
        raise ValueError("Set at least one spot for the monsters to come out of")
    level = body.get("level") if body.get("level") in ("easy", "normal", "hard", "custom") else "normal"
    waves = clean_waves(body.get("waves")) if level == "custom" else preset(level)
    if not waves:
        raise ValueError("Add at least one wave")
    c = point(body.get("center"), "middle of the arena")
    return {"zone": {**c, "r": round(num(body.get("radius"), 6, 60, 15), 1), "h": 12}, "mob_spots": spots,
            "spawns": [c], "level": level, "waves": waves, "coop": bool(body.get("coop", True)),
            "respawn_secs": int(num(body.get("respawn_secs"), 1, 60, 5)), "no_dig": bool(body.get("no_dig", True)),
            "night": bool(body.get("night", True)),          # midnight while it runs: spiders fight, nothing burns
            "kit": kits.clean_kit(body.get("kit") or {})}


async def start(srv, r: dict) -> None:
    from .games import _say
    names = r.get("entrants") or (await S.online_players(srv))[0]
    if not names:
        r["state"], r["result"] = "skipped", "Nobody" + (" joined" if r.get("optin") else " was online")
        return
    night = r.get("night", True) and r.get("dim", "minecraft:overworld") == "minecraft:overworld"
    await battle.rules_on(srv, r, {"mob_griefing": False, **({"daylight": False} if night else {})})
    if night:                                        # midnight, held there (spiders only fight in the dark); the time
        m = re.search(r"(\d+)", await battle._rcon(srv, "time query daytime"))       # of day goes back afterwards
        r["time_before"] = int(m.group(1)) if m else None
        await battle._rcon(srv, "time set 18000")
    playing = await battle.ready(srv, r, names, TAG)
    if not playing:
        await battle.finish(srv, r, TAG)
        r["state"], r["result"] = "skipped", "Nobody's things could be kept safe, so the arena didn't start"
        return
    await battle._rcon(srv, f"scoreboard objectives add {TAG}_k minecraft.custom:minecraft.mob_kills")
    for p in r["players"].values():
        await battle._rcon(srv, f"scoreboard players set {p['uuid']} {TAG}_k 0")
    for n in r["players"]:
        await battle.send_in(srv, r, n)
    r["state"], r["wave"], r["ticks"], r["next_wave"] = "running", 0, 0, time.time() + 5
    how = "Fight together and survive every wave" if r["coop"] else "Most monsters defeated wins"
    await _say(srv, [("★ ", "gold"), ("Mob arena! ", "yellow"), (f"{len(r['waves'])} waves. {how}. ", None), (", ".join(r["players"]), "aqua")],
               "Mob arena!", f"{len(r['waves'])} waves")


def _mob_tag(r: dict) -> str:
    return f"{TAG}_{r['id']}"


async def _summon(srv, r: dict, wave: dict) -> None:
    tag = _mob_tag(r)
    for mob, n in wave.items():
        what, nbt = summon_nbt(srv, mob, tag)
        for _ in range(n):
            s = random.choice(r["mob_spots"])
            await battle._rcon(srv, f"execute in {r['dim']} run summon {what} {s['x'] + random.uniform(-1, 1):.1f} {s['y']} "
                               f"{s['z'] + random.uniform(-1, 1):.1f} {nbt}")
    # no burning up in the daylight, and no wandering off
    await battle._rcon(srv, f"effect give @e[tag={tag}] minecraft:fire_resistance infinite 0 true")
    # they come for the players from anywhere in the arena: a monster usually only notices someone within about
    # 16 blocks (the attribute's name changed in 1.21.2: one of these two works, the other's ignored)
    # (only as far as across the arena: they're after the players in it, not people watching from further off)
    follow = min(FOLLOW, int(2 * r["zone"]["r"] + 8))
    for attr in ("minecraft:follow_range", "minecraft:generic.follow_range"):
        await battle._rcon(srv, f"execute as @e[tag={tag}] run attribute @s {attr} base set {follow}")


async def _mark_splits(srv, r: dict) -> None:
    """A slime that splits: its smaller selves are the arena's too (counted, kept in, and removed at the end)."""
    if not any(SPECIALS.get(m, (0, m))[1] in SPLITS for w in r["waves"] for m in w):
        return
    c, tag = r["zone"], _mob_tag(r)
    for t in SPLITS:
        await battle._rcon(srv, f"execute in {r['dim']} positioned {c['x']} {c['y']} {c['z']} as @e[type=minecraft:{t},distance=..{c['r'] + 8},"
                           f"tag=!{tag}] run tag @s add {tag}")


async def _left(srv, r: dict) -> int:
    m = re.search(r"count: (\d+)", await battle._rcon(srv, f"execute if entity @e[tag={_mob_tag(r)}]"))
    return int(m.group(1)) if m else 0


async def _keep_in(srv, r: dict, where: dict) -> None:
    """Players and monsters stay in the arena: anyone outside it is put back."""
    c, tag = r["zone"], _mob_tag(r)
    for n, p in r["players"].items():
        pos = where.get(n.lower())
        if pos and not p.get("out") and not p.get("back_at") and not battle.inside({**r, "zone": {**c, "r": c["r"] + 2}}, pos):
            await battle._rcon(srv, f"execute in {r['dim']} run tp {p['uuid']} {c['x']} {c['y']} {c['z']}")
    s = random.choice(r["mob_spots"])
    await battle._rcon(srv, f"execute in {r['dim']} positioned {c['x']} {c['y']} {c['z']} as @e[tag={tag},distance={c['r'] + 4}..] "
                       f"run tp @s {s['x']} {s['y']} {s['z']}")


async def _kills(srv, r: dict) -> None:
    for p in r["players"].values():
        m = re.search(r"has (\d+) \[", await battle._rcon(srv, f"scoreboard players get {p['uuid']} {TAG}_k"))
        p["kills"] = int(m.group(1)) if m else p.get("kills", 0)


async def tick(srv, r: dict) -> None:
    from .adventures import _everyone
    from .games import _say
    now = time.time()
    r["ticks"] = r.get("ticks", 0) + 1
    where = {k.lower(): v for k, v in (await _everyone(srv)).items()}
    await battle.left_and_back(srv, r, where)
    await battle.keep_out(srv, r, where)                 # people not playing: moved just outside the arena
    died = await battle.deaths(srv, r, TAG, now)
    if r["coop"]:
        for n in died:                                  # together: watch until this wave's cleared
            r["players"][n]["back_at"] = 1e12
            await _say(srv, [("★ ", "gold"), (f"{n} is down! Clear the wave to bring them back.", "yellow")])
        if all(p.get("out") or p.get("back_at") for p in r["players"].values()):
            await _end(srv, r, wiped=True)
            return
    await battle.comebacks(srv, r, now)
    await _keep_in(srv, r, where)
    await _kills(srv, r)
    await battle.ring(srv, r, "minecraft:soul_fire_flame")
    if r.get("next_wave") is not None:
        if now >= r["next_wave"]:
            r.pop("next_wave")
            wave = r["waves"][r["wave"]]
            r["wave"] += 1
            await _summon(srv, r, wave)
            await _say(srv, [("★ ", "gold"), (f"Wave {r['wave']} of {len(r['waves'])}: ", "yellow"),
                             (", ".join(f"{n} {battle_name(m, n)}" for m, n in wave.items()), "red")], f"Wave {r['wave']}", "Here they come!")
        else:
            left = int(r["next_wave"] - now) + 1
            for p in r["players"].values():
                if not p.get("out"):
                    await hud.status(srv, r, p["uuid"], f"⚔️ Wave {r['wave'] + 1} in {left}...", "gold")
    else:
        await _mark_splits(srv, r)
        mobs = await _left(srv, r)
        for p in r["players"].values():
            if not p.get("out") and not p.get("back_at"):
                await hud.status(srv, r, p["uuid"], f"⚔️ Wave {r['wave']} of {len(r['waves'])} · {mobs} left", "red")
        if mobs == 0:
            if r["coop"]:                                   # wave cleared: everyone who fell comes back
                for n, p in r["players"].items():
                    if p.get("back_at") and not p.get("out"):
                        p.pop("back_at")
                        await battle.send_in(srv, r, n)
            r["survived"] = r["wave"]
            if r["wave"] >= len(r["waves"]):
                await _end(srv, r)
                return
            r["next_wave"] = now + BREAK
            await _say(srv, [("★ ", "gold"), (f"Wave {r['wave']} cleared! Next one in {BREAK} seconds.", "green")])
    rows = {n: p.get("kills", 0) for n, p in r["players"].items()}
    await hud.scores(srv, r, f"⚔️ Wave {max(1, r['wave'])}/{len(r['waves'])}", rows)


def battle_name(mob: str, n: int) -> str:
    if mob in SPECIALS:
        return SPECIALS[mob][0].split(" (")[0].lower() if n == 1 else PLURALS[mob]
    name = MOBS.get(mob, mob).lower()
    return name if n == 1 else (name[:-1] + "ies" if name.endswith("y") else name + ("es" if name.endswith("ch") else "s"))


async def _end(srv, r: dict, wiped: bool = False, called_off: bool = False) -> None:
    from .games import _award, _finish, _say
    await hud.clear(srv, r)
    await battle._rcon(srv, f"kill @e[tag={_mob_tag(r)}]")
    await _kills(srv, r)
    survived = r.get("survived", 0)
    if called_off:
        winners, result = [], "The mob arena was called off."
    elif r["coop"]:
        winners = [] if wiped else list(r["players"])
        result = (f"Everyone survived all {len(r['waves'])} waves of the mob arena!" if not wiped
                  else f"The mob arena got everyone after {survived} wave{'s' if survived != 1 else ''}.")
    else:
        best = max((p.get("kills", 0) for p in r["players"].values()), default=0)
        winners = [n for n, p in r["players"].items() if p.get("kills", 0) == best] if best else []
        result = f"{' & '.join(winners)} won the mob arena with {best} monsters defeated!" if winners else "The mob arena: nobody defeated a monster."
    await _say(srv, [("★ ", "gold"), (result, "yellow")], "Arena over" if not called_off else "", (" & ".join(winners))[:40] if winners else "")
    await battle._rcon(srv, f"scoreboard objectives remove {TAG}_k")
    if r.get("time_before") is not None:             # the time of day it was before
        await battle._rcon(srv, f"time set {r.pop('time_before')}")
    await battle.finish(srv, r, TAG)
    _finish(srv, r, result)
    if winners:
        await _award(srv, r, winners)


async def cancel(srv, r: dict) -> None:
    await _end(srv, r, called_off=True)


def live_rows(r: dict) -> tuple[list[dict], str]:
    rows = [{"name": n, "value": f"{p.get('kills', 0)} defeated", "note": "down" if p.get("back_at") else ""}
            for n, p in sorted(r["players"].items(), key=lambda kv: -kv[1].get("kills", 0))]
    return rows, (f"Wave {r.get('wave', 0)} of {len(r['waves'])}" + (" · together" if r["coop"] else ""))
