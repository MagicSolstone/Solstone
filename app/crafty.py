"""Crafty Controller 4 API v2 client (read-only usage)."""
from __future__ import annotations

import ast
import json
import logging
import time
from typing import Any

import httpx

from .config import config

log = logging.getLogger("lodestone.crafty")


class CraftyClient:
    def __init__(self) -> None:
        self.base = config.crafty_url
        self._token = config.crafty_token
        self._client = httpx.AsyncClient(verify=config.crafty_verify_ssl, timeout=8.0)
        self._cache: dict[str, tuple[float, Any]] = {}
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.base and (self._token or (config.crafty_user and config.crafty_password)))

    async def _login(self) -> None:
        r = await self._client.post(
            f"{self.base}/api/v2/auth/login",
            json={"username": config.crafty_user, "password": config.crafty_password},
        )
        r.raise_for_status()
        self._token = r.json()["data"]["token"]

    async def _get(self, path: str, ttl: float = 5.0) -> Any:
        now = time.monotonic()
        hit = self._cache.get(path)
        if hit and now - hit[0] < ttl:
            return hit[1]
        if not self._token:
            await self._login()
        for attempt in range(2):
            r = await self._client.get(
                f"{self.base}{path}", headers={"Authorization": f"Bearer {self._token}"}
            )
            if r.status_code in (401, 403) and attempt == 0 and config.crafty_user:
                await self._login()
                continue
            r.raise_for_status()
            body = r.json()
            self._cache[path] = (now, body)
            return body
        raise RuntimeError("unreachable")

    async def servers(self) -> list[dict]:
        try:
            body = await self._get("/api/v2/servers", ttl=30)
            self.last_error = None
            return body.get("data", []) or []
        except Exception as e:  # network / auth problems should not kill the app
            self.last_error = f"{type(e).__name__}: {e}"
            log.warning("Crafty server list failed: %s", self.last_error)
            return []

    async def stats(self, server_id: str) -> dict | None:
        try:
            body = await self._get(f"/api/v2/servers/{server_id}/stats", ttl=5)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return None
        data = body.get("data") if isinstance(body.get("data"), dict) else None
        if data is None or "running" not in data:
            data = {**body, **(data or {})}
        return data

    async def close(self) -> None:
        await self._client.aclose()


def parse_player_list(raw: Any) -> list[str]:
    """Crafty returns players as a string like "['Tyler', 'Sam']" or a JSON list."""
    if isinstance(raw, list):
        return [str(p) for p in raw]
    if not raw or not isinstance(raw, str):
        return []
    for parser in (json.loads, ast.literal_eval):
        try:
            val = parser(raw)
            if isinstance(val, (list, tuple)):
                return [str(p) for p in val]
        except Exception:
            continue
    return []


crafty = CraftyClient()
