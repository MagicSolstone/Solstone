"""Parse Minecraft server log lines into activity events.

Handles the vanilla/Fabric log4j layout `[12:34:56] [Server thread/INFO]: ...`
and the Paper layout `[12:34:56 INFO]: ...`. Death messages have dozens of
variants, so a line counts as a death only when it starts with a known
player's name followed by one of the death-message verbs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import mcname

_LINE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?\] \[([^\]]+?)/(\w+)\]: (.*)$")
_LINE_PAPER = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2}) (\w+)\]: (.*)$")
_NAME = rf"({mcname.PATTERN})"       # Java names, and Bedrock ones with Floodgate's dot
_JOIN = re.compile(rf"^{_NAME} joined the game$")
_LEAVE = re.compile(rf"^{_NAME} left the game$")
_CHAT = re.compile(rf"^(?:\[Not Secure\] )?<{_NAME}> (.*)$")
_ADV = re.compile(rf"^{_NAME} has (made the advancement|completed the challenge|reached the goal) \[(.+)\]$")
_DONE = re.compile(r"^Done \([\d.,]+s\)! For help")
_STOP = re.compile(r"^Stopping (the )?server$")
_DEATH_VERBS = re.compile(
    r"^(was |were |fell |drowned|died|blew up|burned|went (up in flames|off with a bang)|walked into|tried to swim|"
    r"hit the ground|experienced kinetic|froze to death|starved|suffocated|withered away|discovered the floor|"
    r"didn't want to live|left the confines|got finished off|is |hit |was killed|went off|"
    r"was squashed|was squished|was pricked|was poked|was impaled|was stung|was shot|was fireballed)"
)
_NOT_DEATH = re.compile(r"^(lost connection|joined|left|has made|has completed|has reached|issued|moved|logged in|"
                        r"was kicked|is now|was banned|was unbanned)")


@dataclass
class LogEvent:
    hour: int
    minute: int
    second: int
    type: str
    message: str
    player: str | None = None


def parse_line(line: str, known_players: set[str]) -> LogEvent | None:
    line = line.rstrip("\r\n")
    m = _LINE.match(line)
    if m:
        h, mi, s, thread, level, msg = m.groups()
        if level != "INFO" or not thread.startswith("Server thread"):
            return None
    else:
        m = _LINE_PAPER.match(line)
        if not m:
            return None
        h, mi, s, level, msg = m.groups()
        if level != "INFO":
            return None
    h, mi, s = int(h), int(mi), int(s)

    def ev(t, message, player=None):
        return LogEvent(h, mi, s, t, message, player)

    if mm := _JOIN.match(msg):
        return ev("join", msg, mm.group(1))
    if mm := _LEAVE.match(msg):
        return ev("leave", msg, mm.group(1))
    if mm := _CHAT.match(msg):
        return ev("chat", mm.group(2), mm.group(1))
    if mm := _ADV.match(msg):
        return ev("advancement", msg, mm.group(1))
    if _DONE.match(msg):
        return ev("server", "Server started")
    if _STOP.match(msg):
        return ev("server", "Server stopping")
    # Deaths: "<known player> <death verb ...>"
    first, _, rest = msg.partition(" ")
    if rest and first.lower() in known_players and _DEATH_VERBS.match(rest) and not _NOT_DEATH.match(rest):
        return ev("death", msg, first)
    return None
