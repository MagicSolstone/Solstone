"""The fish Solstone knows by weight: for the fishing journal's older pages.

Solstone once had a data pack of its own (fishing weights, then archery and spleef). It was taken out in 1.16: with
the Tide fishing mod, Tide's own catches are read (tide.py); without it fishing is plain vanilla and Solstone leaves
it alone. What's here names the fish and their sizes for catches recorded back then.
"""
from __future__ import annotations

PACK_ID = "solstone-pack"                     # the old pack's name in a world's datapacks folder (fishing.retire_pack)
PACK_FILE = f"{PACK_ID}.zip"

# ------------------------------------------------------------------ the fish (vanilla)
# key (the vanilla item): (name, smallest lb, biggest lb)
SPECIES: dict[str, tuple[str, float, float]] = {
    "cod": ("Cod", 1.0, 12.0),
    "salmon": ("Salmon", 2.0, 20.0),
    "tropical_fish": ("Tropical Fish", 0.2, 1.5),
    "pufferfish": ("Pufferfish", 0.5, 3.0),
}
# Older catches (from the pack's fancier days) kept their quality; new ones are all "Normal" (index 1).
QUALITIES = [("Poor", "gray"), ("Normal", "white"), ("Fine", "green"), ("Trophy", "aqua"), ("Legendary", "gold"), ("Mythic", "light_purple")]


def fmt_lb(w: float) -> str:
    return f"{w:.2f}".rstrip("0").rstrip(".") if w < 1 else f"{w:.1f}"


def points(lb: float) -> int:
    return int(lb) + 1


def guide() -> list[dict]:
    """For the web page: each fish and its size range."""
    return [{"key": k, "name": n, "item": f"minecraft:{k}", "waters": [], "min_lb": lo, "max_lb": hi,
             "min_points": points(lo), "max_points": points(hi), "rarity": ""} for k, (n, lo, hi) in SPECIES.items()]


def qualities() -> list[dict]:
    return []                                 # vanilla fish have no quality
