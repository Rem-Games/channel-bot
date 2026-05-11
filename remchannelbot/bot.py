from __future__ import annotations

import asyncio
import io
import logging
import random
import re
from datetime import UTC, datetime
from typing import Callable

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .config import load_config
from .state import (
    LIST_MODE_EXHAUSTIVE,
    LIST_MODE_RANDOM,
    MIN_INTERVAL_MINUTES,
    ROTATION_MODE_ALL,
    ROTATION_MODE_ONE,
    StateStore,
    clean_candidate_name,
)

LOGGER = logging.getLogger(__name__)
NAMES_PER_PAGE = 20
RenameableChannel = discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.ForumChannel


class RemChannelBot(commands.Bot):
    def __init__(self, store: StateStore, guild_id: int | None):
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.store = store
        self.guild_id = guild_id

    async def setup_hook(self) -> None:
        self.tree.add_command(RemChannelGroup(self))
        if self.guild_id:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            try:
                await self.tree.sync(guild=guild)
            except discord.Forbidden as exc:
                LOGGER.error(
                    "Discord rejected guild command sync for guild %s. "
                    "Check that DISCORD_GUILD_ID is the target server ID and that the bot was "
                    "invited to that server with both the bot and applications.commands scopes.",
                    self.guild_id,
                )
                raise RuntimeError(
                    "Unable to sync slash commands. Check DISCORD_GUILD_ID and reinvite the "
                    "bot with bot + applications.commands scopes."
                ) from exc
            LOGGER.info("Synced commands to guild %s", self.guild_id)
        else:
            await self.tree.sync()
            LOGGER.info("Synced global commands")
        self.rotation_loop.start()

    async def close(self) -> None:
        self.rotation_loop.cancel()
        await super().close()

    @tasks.loop(minutes=1)
    async def rotation_loop(self) -> None:
        await self.wait_until_ready()
        now = datetime.now(UTC)
        for guild in list(self.guilds):
            state = self.store.get_guild(guild.id)
            last_key = f"_last_rotation_at_{guild.id}"
            last_rotation_at = getattr(self, last_key, None)
            if last_rotation_at is None:
                setattr(self, last_key, now)
                continue
            elapsed = (now - last_rotation_at).total_seconds() / 60
            if elapsed < state.interval_minutes:
                continue
            changes = await rotate_channels(guild, state, reason="scheduled rotation")
            if changes:
                self.store.update_guild(guild.id, state)
                setattr(self, last_key, now)
                if not state.quiet_mode:
                    await send_command_channel_notice(guild, state, "\n".join(changes))

    @rotation_loop.before_loop
    async def before_rotation_loop(self) -> None:
        await self.wait_until_ready()


class RemChannelGroup(app_commands.Group):
    def __init__(self, bot: RemChannelBot):
        super().__init__(name="remchannel", description="Manage rotating channel names")
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return False

        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "Only the server owner or members with Administrator can use this bot.",
                ephemeral=True,
            )
            return False

        state = self.bot.store.get_guild(interaction.guild_id)
        if interaction.command and interaction.command.name == "setup":
            return True
        if state.command_channel_id is None:
            await interaction.response.send_message(
                "Run `/remchannel setup` in the channel this bot should use first.",
                ephemeral=True,
            )
            return False
        if interaction.channel_id != state.command_channel_id:
            channel = interaction.guild.get_channel(state.command_channel_id)
            mention = channel.mention if channel else f"`{state.command_channel_id}`"
            await interaction.response.send_message(
                f"Use this bot in {mention}.", ephemeral=True
            )
            return False
        return True

    @app_commands.command(name="setup", description="Set the command and response channel")
    @app_commands.describe(command_channel="Channel where bot commands and responses are allowed")
    @app_commands.default_permissions(administrator=True)
    async def setup(
        self,
        interaction: discord.Interaction,
        command_channel: discord.TextChannel,
    ) -> None:
        state = self.bot.store.get_guild(interaction.guild_id)
        state.command_channel_id = command_channel.id
        self.bot.store.update_guild(interaction.guild_id, state)
        await interaction.response.send_message(
            f"Command channel set to {command_channel.mention}.", ephemeral=True
        )
        await command_channel.send("Rem Channel Bot is configured for this channel.")

    @app_commands.command(name="interval", description="Set the rotation interval in minutes")
    @app_commands.describe(minutes=f"Minimum {MIN_INTERVAL_MINUTES} minutes")
    @app_commands.default_permissions(administrator=True)
    async def interval(
        self,
        interaction: discord.Interaction,
        minutes: app_commands.Range[int, 10, 10080],
    ) -> None:
        state = self.bot.store.get_guild(interaction.guild_id)
        state.interval_minutes = int(minutes)
        self.bot.store.update_guild(interaction.guild_id, state)
        await interaction.response.send_message(
            f"Rotation interval set to {state.interval_minutes} minutes."
        )

    @app_commands.command(name="mode", description="Set whether rotations update one channel or all channels")
    @app_commands.describe(mode="Use one for the default one-channel rotation or all to update every channel")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="one channel", value=ROTATION_MODE_ONE),
            app_commands.Choice(name="all channels", value=ROTATION_MODE_ALL),
        ]
    )
    @app_commands.default_permissions(administrator=True)
    async def mode(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
    ) -> None:
        state = self.bot.store.get_guild(interaction.guild_id)
        state.rotation_mode = mode.value
        self.bot.store.update_guild(interaction.guild_id, state)
        await interaction.response.send_message(f"Rotation mode set to `{mode.value}`.")

    @app_commands.command(name="list-mode", description="Set how candidate names are selected")
    @app_commands.describe(
        mode="Use fully random selection or exhaust all candidate names before repeats"
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="fully random", value=LIST_MODE_RANDOM),
            app_commands.Choice(name="exhaustive", value=LIST_MODE_EXHAUSTIVE),
        ]
    )
    @app_commands.default_permissions(administrator=True)
    async def list_mode(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
    ) -> None:
        state = self.bot.store.get_guild(interaction.guild_id)
        state.list_mode = mode.value
        if mode.value == LIST_MODE_RANDOM:
            state.used_candidate_keys = []
        self.bot.store.update_guild(interaction.guild_id, state)
        await interaction.response.send_message(f"List mode set to `{mode.value}`.")

    @app_commands.command(name="quiet", description="Toggle scheduled rotation notices")
    @app_commands.describe(enabled="True suppresses scheduled rotation messages; false sends them")
    @app_commands.default_permissions(administrator=True)
    async def quiet(self, interaction: discord.Interaction, enabled: bool) -> None:
        state = self.bot.store.get_guild(interaction.guild_id)
        state.quiet_mode = enabled
        self.bot.store.update_guild(interaction.guild_id, state)
        mode = "enabled" if state.quiet_mode else "disabled"
        await interaction.response.send_message(f"Quiet mode {mode}.")

    @app_commands.command(name="rotation-list", description="List channels in the rotation")
    @app_commands.default_permissions(administrator=True)
    async def rotation_list(self, interaction: discord.Interaction) -> None:
        state = self.bot.store.get_guild(interaction.guild_id)
        quiet = "enabled" if state.quiet_mode else "disabled"
        lines = [
            f"Mode: `{state.rotation_mode}`",
            f"List mode: `{state.list_mode}`",
            f"Quiet mode: `{quiet}`",
        ]
        for channel_id in state.rotation_channel_ids:
            channel = interaction.guild.get_channel(channel_id)
            name = channel.name if channel else "missing"
            lines.append(f"- {name} (`{channel_id}`)")
        await interaction.response.send_message("\n".join(lines) if lines else "No channels configured.")

    @app_commands.command(name="rotation-add", description="Add a channel to the rotation")
    @app_commands.describe(channel="Channel to rename during rotation")
    @app_commands.default_permissions(administrator=True)
    async def rotation_add(
        self,
        interaction: discord.Interaction,
        channel: RenameableChannel,
    ) -> None:
        state = self.bot.store.get_guild(interaction.guild_id)
        if channel.id in state.rotation_channel_ids:
            await interaction.response.send_message(
                f"{format_channel(channel)} is already in the rotation."
            )
            return
        state.rotation_channel_ids.append(channel.id)
        self.bot.store.update_guild(interaction.guild_id, state)
        await interaction.response.send_message(f"Added {format_channel(channel)} (`{channel.id}`).")

    @app_commands.command(name="rotation-remove", description="Remove a channel by channel, ID, or unique name")
    @app_commands.describe(channel="Channel mention, channel ID, or unique current channel name")
    @app_commands.default_permissions(administrator=True)
    async def rotation_remove(self, interaction: discord.Interaction, channel: str) -> None:
        state = self.bot.store.get_guild(interaction.guild_id)
        channel_id = resolve_channel_id(interaction.guild, channel, state.rotation_channel_ids)
        if channel_id is None:
            await interaction.response.send_message(
                "No unique configured channel matched that input.", ephemeral=True
            )
            return
        state.rotation_channel_ids = [value for value in state.rotation_channel_ids if value != channel_id]
        self.bot.store.update_guild(interaction.guild_id, state)
        await interaction.response.send_message(f"Removed channel `{channel_id}` from the rotation.")

    @app_commands.command(name="names-list", description="List candidate channel names")
    @app_commands.describe(page="Page number", export="Attach the full list as a text file")
    @app_commands.default_permissions(administrator=True)
    async def names_list(
        self,
        interaction: discord.Interaction,
        page: int = 1,
        export: bool = False,
    ) -> None:
        state = self.bot.store.get_guild(interaction.guild_id)
        if not state.candidate_names:
            await interaction.response.send_message("No candidate names configured.")
            return
        if export:
            content = "\n".join(state.candidate_names) + "\n"
            file = discord.File(io.BytesIO(content.encode("utf-8")), filename="candidate-names.txt")
            await interaction.response.send_message("Candidate names exported.", file=file)
            return
        total_pages = max(1, (len(state.candidate_names) + NAMES_PER_PAGE - 1) // NAMES_PER_PAGE)
        page = min(max(page, 1), total_pages)
        start = (page - 1) * NAMES_PER_PAGE
        visible = state.candidate_names[start : start + NAMES_PER_PAGE]
        lines = [f"{start + index + 1}. {name}" for index, name in enumerate(visible)]
        await interaction.response.send_message(
            f"Candidate names page {page}/{total_pages}\n" + "\n".join(lines)
        )

    @app_commands.command(name="name-add", description="Add a candidate channel name")
    @app_commands.describe(name="Name to include in future rotations")
    @app_commands.default_permissions(administrator=True)
    async def name_add(self, interaction: discord.Interaction, name: str) -> None:
        try:
            cleaned = clean_candidate_name(name)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        state = self.bot.store.get_guild(interaction.guild_id)
        if cleaned in state.candidate_names:
            await interaction.response.send_message("That candidate name already exists.")
            return
        state.candidate_names.append(cleaned)
        self.bot.store.update_guild(interaction.guild_id, state)
        await interaction.response.send_message(f"Added candidate name: `{cleaned}`.")

    @app_commands.command(name="name-remove", description="Remove a candidate channel name")
    @app_commands.describe(name="Exact candidate name to remove")
    @app_commands.default_permissions(administrator=True)
    async def name_remove(self, interaction: discord.Interaction, name: str) -> None:
        state = self.bot.store.get_guild(interaction.guild_id)
        try:
            cleaned = clean_candidate_name(name)
        except ValueError:
            cleaned = name.strip()
        if cleaned not in state.candidate_names:
            await interaction.response.send_message("That candidate name was not found.", ephemeral=True)
            return
        state.candidate_names.remove(cleaned)
        self.bot.store.update_guild(interaction.guild_id, state)
        await interaction.response.send_message(f"Removed candidate name: `{cleaned}`.")

    @app_commands.command(name="rotate-now", description="Rotate the next configured channel immediately")
    @app_commands.default_permissions(administrator=True)
    async def rotate_now(self, interaction: discord.Interaction) -> None:
        state = self.bot.store.get_guild(interaction.guild_id)
        changes = await rotate_channels(interaction.guild, state, reason="manual rotation")
        if not changes:
            await interaction.response.send_message(
                "No channels could be rotated. Rotation needs configured channels, candidate names, "
                "and at least one candidate name that is not already in use.",
                ephemeral=True,
            )
            return
        self.bot.store.update_guild(interaction.guild_id, state)
        await interaction.response.send_message("\n".join(changes))


def is_admin(member: discord.Member) -> bool:
    return member.guild.owner_id == member.id or member.guild_permissions.administrator


def resolve_channel_id(guild: discord.Guild, value: str, allowed_channel_ids: list[int]) -> int | None:
    raw = value.strip()
    if raw.startswith("<#") and raw.endswith(">"):
        raw = raw[2:-1]
    if raw.isdigit():
        channel_id = int(raw)
        return channel_id if channel_id in allowed_channel_ids else None

    matches = [
        channel.id
        for channel_id in allowed_channel_ids
        if (channel := guild.get_channel(channel_id)) and channel.name == raw
    ]
    return matches[0] if len(matches) == 1 else None


def format_channel(channel: discord.abc.GuildChannel) -> str:
    mention = getattr(channel, "mention", None)
    return mention if mention else f"`{channel.name}`"


async def rotate_channels(guild: discord.Guild, state, reason: str) -> list[str]:
    if state.rotation_mode == ROTATION_MODE_ALL:
        return await rotate_all_channels(guild, state, reason)

    changed = await rotate_next_channel(guild, state, reason)
    return [changed] if changed else []


async def rotate_next_channel(guild: discord.Guild, state, reason: str) -> str | None:
    if not state.rotation_channel_ids or not state.candidate_names:
        return None

    current_keys = current_rotation_candidate_keys(guild, state.rotation_channel_ids)
    attempts = len(state.rotation_channel_ids)
    for _ in range(attempts):
        channel_id = state.rotation_channel_ids[state.next_rotation_index]
        state.next_rotation_index = (state.next_rotation_index + 1) % len(
            state.rotation_channel_ids
        )
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.abc.GuildChannel):
            continue

        name = next_candidate_name(
            state,
            channel.name,
            current_keys - {candidate_key(channel.name)},
            name_transform=lambda candidate: candidate_name_for_channel(channel, candidate),
        )
        if name is None:
            continue

        old_name = channel.name
        try:
            await channel.edit(name=name, reason=reason)
        except discord.Forbidden:
            LOGGER.warning("Missing permissions to rename channel %s in guild %s", channel_id, guild.id)
            return f"Missing permissions to rename `{old_name}` (`{channel_id}`)."
        except discord.HTTPException as exc:
            LOGGER.warning("Failed to rename channel %s in guild %s: %s", channel_id, guild.id, exc)
            return f"Failed to rename `{old_name}` (`{channel_id}`): {exc}"
        return f"Renamed `{old_name}` (`{channel_id}`) to `{name}`."
    return None


async def rotate_all_channels(guild: discord.Guild, state, reason: str) -> list[str]:
    if not state.rotation_channel_ids or not state.candidate_names:
        return []

    channels = [
        channel
        for channel_id in state.rotation_channel_ids
        if isinstance((channel := guild.get_channel(channel_id)), discord.abc.GuildChannel)
    ]
    if not channels:
        return []

    planned_names: dict[int, str] = {}
    reserved_keys = {candidate_key(channel.name) for channel in channels}
    for channel in channels:
        name = next_candidate_name(
            state,
            channel.name,
            reserved_keys - {candidate_key(channel.name)},
            name_transform=lambda candidate: candidate_name_for_channel(channel, candidate),
        )
        if name is None:
            continue
        planned_names[channel.id] = name
        reserved_keys.add(candidate_key(name))

    changes = []
    for channel in channels:
        name = planned_names.get(channel.id)
        if name is None:
            continue
        old_name = channel.name
        try:
            await channel.edit(name=name, reason=reason)
        except discord.Forbidden:
            LOGGER.warning("Missing permissions to rename channel %s in guild %s", channel.id, guild.id)
            changes.append(f"Missing permissions to rename `{old_name}` (`{channel.id}`).")
        except discord.HTTPException as exc:
            LOGGER.warning("Failed to rename channel %s in guild %s: %s", channel.id, guild.id, exc)
            changes.append(f"Failed to rename `{old_name}` (`{channel.id}`): {exc}")
        else:
            changes.append(f"Renamed `{old_name}` (`{channel.id}`) to `{name}`.")
    return changes


def current_rotation_candidate_keys(guild: discord.Guild, channel_ids: list[int]) -> set[str]:
    return {
        candidate_key(channel.name)
        for channel_id in channel_ids
        if isinstance((channel := guild.get_channel(channel_id)), discord.abc.GuildChannel)
    }


def normalize_text_channel_name(name: str) -> str:
    normalized = re.sub(r"\s+", "-", name.strip().lower())
    normalized = re.sub(r"[^a-z0-9_-]+", "", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized.strip("-")


def candidate_key(name: str) -> str:
    return normalize_text_channel_name(name)


def candidate_name_for_channel(channel: discord.abc.GuildChannel, candidate_name: str) -> str:
    if isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
        return normalize_text_channel_name(candidate_name)
    return candidate_name


def identity_name(name: str) -> str:
    return name


def next_candidate_name(
    state,
    current_name: str,
    reserved_keys: set[str] | None = None,
    name_transform: Callable[[str], str] = identity_name,
) -> str | None:
    if not state.candidate_names:
        return None
    reserved_keys = reserved_keys or set()
    current_key = candidate_key(current_name)

    candidates = []
    for index, raw_candidate in enumerate(state.candidate_names):
        candidate = name_transform(raw_candidate)
        key = candidate_key(candidate)
        if key != current_key and key not in reserved_keys:
            candidates.append((index, candidate, key))

    if not candidates:
        return None

    if state.list_mode == LIST_MODE_EXHAUSTIVE:
        valid_keys = {
            candidate_key(name_transform(candidate)) for candidate in state.candidate_names
        }
        state.used_candidate_keys = [
            key for key in dict.fromkeys(state.used_candidate_keys) if key in valid_keys
        ]
        used_keys = set(state.used_candidate_keys)
        unused_candidates = [
            candidate for candidate in candidates if candidate[2] not in used_keys
        ]
        if not unused_candidates:
            state.used_candidate_keys = []
            unused_candidates = candidates
        index, candidate, key = random.choice(unused_candidates)
        state.used_candidate_keys.append(key)
        state.next_candidate_index = (index + 1) % len(state.candidate_names)
        return candidate

    index, candidate, _key = random.choice(candidates)
    state.next_candidate_index = (index + 1) % len(state.candidate_names)
    state.used_candidate_keys = []
    return candidate


async def send_command_channel_notice(guild: discord.Guild, state, message: str) -> None:
    if state.command_channel_id is None:
        return
    channel = guild.get_channel(state.command_channel_id)
    if isinstance(channel, discord.abc.Messageable):
        await channel.send(message)


def main() -> None:
    config = load_config()
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    bot = RemChannelBot(StateStore(config.state_file), config.guild_id)
    asyncio.run(bot.start(config.token))
