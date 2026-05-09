from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    token: str
    guild_id: int | None
    state_file: str
    log_level: str


def load_config() -> Config:
    load_dotenv()

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN is required")

    raw_guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
    guild_id = int(raw_guild_id) if raw_guild_id else None

    return Config(
        token=token,
        guild_id=guild_id,
        state_file=os.getenv("STATE_FILE", "data/state.json"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
