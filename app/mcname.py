"""What a player's name on the server can look like. Java names are 1-16 letters, digits and underscores.
Bedrock players come in through Geyser and Floodgate with a dot in front (".Steve"), and their gamertag's
spaces turned into underscores, so the same check takes an optional dot."""
import re

PATTERN = r"\.?[A-Za-z0-9_]{1,16}"
NAME_RE = re.compile(rf"^{PATTERN}$")


def is_name(name: object) -> bool:
    return isinstance(name, str) and bool(NAME_RE.match(name))


def is_bedrock(name: str) -> bool:
    return name.startswith(".")
