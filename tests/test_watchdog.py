"""The watchdog notices when the main loop is held up, says what it was doing, and when it's going again."""
import asyncio
import logging
import time

from app import watchdog


def _held_up_for_a_moment():
    time.sleep(2.5)                      # a slow disk read, say, done right on the main loop


def test_watchdog_reports_a_held_up_loop(caplog, monkeypatch):
    monkeypatch.setattr(watchdog, "STALL_SECONDS", 0.8)

    async def main():
        watchdog.start()
        await asyncio.sleep(0.6)
        _held_up_for_a_moment()
        await asyncio.sleep(2.2)

    with caplog.at_level(logging.WARNING, logger="solstone.watchdog"):
        asyncio.run(main())
    text = caplog.text
    assert "held up" in text and "_held_up_for_a_moment" in text      # what it was busy with
    assert "answering again" in text
