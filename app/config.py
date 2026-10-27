"""Runtime configuration, all from environment variables."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # Crafty Controller 4
    crafty_url: str = os.getenv("CRAFTY_URL", "").rstrip("/")
    crafty_token: str = os.getenv("CRAFTY_TOKEN", "")
    crafty_user: str = os.getenv("CRAFTY_USERNAME", "")
    crafty_password: str = os.getenv("CRAFTY_PASSWORD", "")
    crafty_verify_ssl: bool = _bool("CRAFTY_VERIFY_SSL", False)

    # Where Crafty's "servers" folder is mounted inside this container (read-only is fine)
    servers_dir: Path = Path(os.getenv("SERVERS_DIR", "/servers"))

    # RCON host used to reach the Minecraft servers. Defaults to the Crafty host.
    rcon_host: str = os.getenv("RCON_HOST", "")
    rcon_timeout: float = float(os.getenv("RCON_TIMEOUT", "4"))

    # Optional: a music library to share (e.g. Jellyfin's music folder, mounted read-only).
    # Solstone reads its tags and plays it alongside the music uploaded in the app.
    music_library_dir: str = os.getenv("MUSIC_LIBRARY_DIR", "")
    # Where Solstone files music uploaded in the app: a folder inside the library that it may
    # write to (mount just this one read-write). Defaults to <MUSIC_LIBRARY_DIR>/Solstone.
    music_upload_dir: str = os.getenv("MUSIC_UPLOAD_DIR", "")

    # Optional: only these servers (Crafty names, Crafty ids or folder names, comma-separated). For running
    # one Solstone per community, each with its own website, accounts and settings, against one Crafty.
    only_servers: tuple[str, ...] = tuple(x.strip().lower() for x in os.getenv("ONLY_SERVERS", "").split(",") if x.strip())

    # App data (settings + downloaded game assets)
    data_dir: Path = Path(os.getenv("DATA_DIR", "/data"))
    # The address people reach Solstone at (https://playsolstone.com), for links Solstone hands out
    # (the family modpack). Optional: otherwise worked out from each request and the proxy's headers.
    public_url: str = os.getenv("PUBLIC_URL", "").rstrip("/")

    # Optional: require this token for changing settings (header X-Admin-Token)
    admin_token: str = os.getenv("ADMIN_TOKEN", "")

    # Download Minecraft client jar for item icons / names
    download_assets: bool = _bool("DOWNLOAD_ASSETS", True)

    # How often (seconds) live player data is refreshed for online players
    live_ttl: float = float(os.getenv("LIVE_TTL", "3"))

    @property
    def default_rcon_host(self) -> str:
        if self.rcon_host:
            return self.rcon_host
        if self.crafty_url:
            host = urlparse(self.crafty_url).hostname
            if host:
                return host
        return "127.0.0.1"


config = Config()
config.data_dir.mkdir(parents=True, exist_ok=True)
