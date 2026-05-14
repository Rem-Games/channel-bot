from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any

MIN_INTERVAL_MINUTES = 10
DEFAULT_INTERVAL_MINUTES = 60
ROTATION_MODE_ONE = "one"
ROTATION_MODE_ALL = "all"
ROTATION_MODES = {ROTATION_MODE_ONE, ROTATION_MODE_ALL}
LIST_MODE_RANDOM = "random"
LIST_MODE_EXHAUSTIVE = "exhaustive"
LIST_MODES = {LIST_MODE_RANDOM, LIST_MODE_EXHAUSTIVE}


@dataclass
class GuildState:
    command_channel_id: int | None = None
    rotation_channel_ids: list[int] = field(default_factory=list)
    candidate_names: list[str] = field(default_factory=list)
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    rotation_mode: str = ROTATION_MODE_ONE
    list_mode: str = LIST_MODE_RANDOM
    quiet_mode: bool = False
    next_rotation_index: int = 0
    next_candidate_index: int = 0
    used_candidate_keys: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> GuildState:
        interval = int(payload.get("interval_minutes", DEFAULT_INTERVAL_MINUTES))
        rotation_mode = str(payload.get("rotation_mode", ROTATION_MODE_ONE))
        list_mode = str(payload.get("list_mode", LIST_MODE_RANDOM))
        return cls(
            command_channel_id=_optional_int(payload.get("command_channel_id")),
            rotation_channel_ids=[int(value) for value in payload.get("rotation_channel_ids", [])],
            candidate_names=[str(value) for value in payload.get("candidate_names", [])],
            interval_minutes=max(interval, MIN_INTERVAL_MINUTES),
            rotation_mode=rotation_mode,
            list_mode=list_mode,
            quiet_mode=bool(payload.get("quiet_mode", False)),
            next_rotation_index=int(payload.get("next_rotation_index", 0)),
            next_candidate_index=int(payload.get("next_candidate_index", 0)),
            used_candidate_keys=[str(value) for value in payload.get("used_candidate_keys", [])],
        )

    def normalized(self) -> GuildState:
        self.rotation_channel_ids = list(dict.fromkeys(self.rotation_channel_ids))
        self.candidate_names = list(dict.fromkeys(self.candidate_names))
        self.interval_minutes = max(int(self.interval_minutes), MIN_INTERVAL_MINUTES)
        if self.rotation_mode not in ROTATION_MODES:
            self.rotation_mode = ROTATION_MODE_ONE
        if self.list_mode not in LIST_MODES:
            self.list_mode = LIST_MODE_RANDOM
        if self.rotation_channel_ids:
            self.next_rotation_index %= len(self.rotation_channel_ids)
        else:
            self.next_rotation_index = 0
        if self.candidate_names:
            self.next_candidate_index %= len(self.candidate_names)
        else:
            self.next_candidate_index = 0
        valid_candidate_keys = {_candidate_key(name) for name in self.candidate_names}
        self.used_candidate_keys = list(
            dict.fromkeys(key for key in self.used_candidate_keys if key in valid_candidate_keys)
        )
        if valid_candidate_keys and set(self.used_candidate_keys) == valid_candidate_keys:
            self.used_candidate_keys = []
        return self


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = RLock()
        self._guilds: dict[int, GuildState] = {}
        self.load()

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._guilds = {}
                return

            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)

            guilds = payload.get("guilds", {})
            self._guilds = {
                int(guild_id): GuildState.from_dict(state).normalized()
                for guild_id, state in guilds.items()
            }

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "guilds": {
                    str(guild_id): asdict(state.normalized())
                    for guild_id, state in sorted(self._guilds.items())
                }
            }
            with self.path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")

    def get_guild(self, guild_id: int) -> GuildState:
        with self._lock:
            state = self._guilds.setdefault(guild_id, GuildState())
            return state.normalized()

    def update_guild(self, guild_id: int, state: GuildState) -> None:
        with self._lock:
            self._guilds[guild_id] = state.normalized()
            self.save()


def clean_candidate_name(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    if not 1 <= len(cleaned) <= 100:
        raise ValueError("Candidate names must be 1 to 100 characters long.")
    return cleaned


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _candidate_key(name: str) -> str:
    normalized = re.sub(r"\s+", "-", name.strip().lower())
    normalized = re.sub(r"[^a-z0-9_-]+", "", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized.strip("-")
