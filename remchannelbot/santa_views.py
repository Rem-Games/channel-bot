"""Private, requester-owned Secret Santa conversations."""

from __future__ import annotations

import discord

from .santa import drawing_sort_key
from .state import SANTA_COMPLETED, SANTA_OPEN, SantaExclusion

SANTA_VIEW_TIMEOUT = 300


def details_pages(drawing) -> list[str]:
    completed = f"<t:{drawing.completed_at}:F>" if drawing.completed_at is not None else "Unknown"
    header = (
        f"Secret Santa: {discord.utils.escape_markdown(drawing.name)}\n"
        f"Completed: {completed}\nParticipants: {len(drawing.participant_ids)}\n\n"
    )
    pages = []
    page = header
    for participant in drawing.participant_ids:
        giftee = drawing.assignments.get(participant)
        line = f"Participant <@{participant}> drew "
        line += f"<@{giftee}>\n" if giftee is not None else "(assignment unavailable)\n"
        if len(page) + len(line) > 2000:
            pages.append(page.rstrip())
            page = header
        page += line
    pages.append(page.rstrip())
    return pages


class SantaConversation(discord.ui.View):
    def __init__(self, group, interaction, command: str, drawing=None):
        super().__init__(timeout=SANTA_VIEW_TIMEOUT)
        self.group = group
        self.requester_id = interaction.user.id
        self.guild_id = interaction.guild_id
        self.command = command
        self.drawing_id = drawing.drawing_id if drawing else None
        self.page = 0
        self.message = None
        self.finished = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the user who opened this conversation can use it.", ephemeral=True
            )
            return False
        if self.finished:
            await interaction.response.send_message(
                "This conversation has ended. Run the command again.", ephemeral=True
            )
            return False
        return await self.group.interaction_check(interaction)

    async def on_timeout(self):
        self.finished = True
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    def drawing(self):
        state = self.group.bot.store.get_guild(self.guild_id)
        return next(
            (d for d in state.santa_drawings.values() if d.drawing_id == self.drawing_id), None
        )

    def options(self, interaction):
        state = self.group.bot.store.get_guild(self.guild_id)
        if self.drawing_id is None:
            return self.group.command_choices(interaction, self.command)
        drawing = self.drawing()
        if self.command == "exclusion-remove":
            return sorted(drawing.exclusions, key=drawing_sort_key)
        excluded = {item.drawing_id for item in drawing.exclusions}
        return sorted(
            (
                d
                for d in state.santa_drawings.values()
                if d.state == SANTA_COMPLETED and d.drawing_id not in excluded
            ),
            key=drawing_sort_key,
        )

    def validate(self, interaction):
        if self.drawing_id is None:
            return None
        drawing = self.drawing()
        if drawing is None:
            return "That drawing was deleted."
        if self.command == "details":
            if drawing.state != SANTA_COMPLETED:
                return "Details are only available for Completed drawings."
        else:
            if not self.group.can_manage(interaction, drawing):
                return "Only the drawing creator or server admins can change exclusions."
            if drawing.state != SANTA_OPEN:
                return "Exclusions can only be changed on Open drawings."
        return None

    def finish(self):
        self.finished = True
        self.stop()
        self.clear_items()

    def render(self, interaction):
        self.clear_items()
        error = self.validate(interaction)
        if error:
            self.finish()
            return error
        if self.command == "details" and self.drawing_id:
            pages = details_pages(self.drawing())
            self.page = max(0, min(self.page, len(pages) - 1))
            self.pagination(len(pages))
            return pages[self.page]
        options = self.options(interaction)
        if self.drawing_id is None:
            state_name = self.group.command_state(self.command)
            state_text = f"{state_name} " if state_name else ""
            header = (
                f"There are multiple {state_text}drawings to run `/santa {self.command}` on. "
                "Which would you like?"
            )
            if not options:
                self.finish()
                return self.group.no_choices_message(interaction, self.command)
        else:
            drawing = self.drawing()
            count = len(drawing.exclusions)
            header = (
                f"Exclusions for {discord.utils.escape_markdown(drawing.name)}: {count} / 3. "
                f"You can add {3 - count} more.\n"
                "We will try our best to avoid repeats, relaxing exclusions oldest-first "
                "if needed to make a drawing."
            )
            if self.command == "exclusion" and count >= 3:
                self.finish()
                return header + "\nThe limit of 3 exclusions has been reached."
            if not options:
                self.finish()
                return header + (
                    "\nNo exclusions remain."
                    if self.command == "exclusion-remove"
                    else "\nNo other Completed drawings are available to add."
                )
            header += (
                "\nSelect a drawing to remove:"
                if self.command == "exclusion-remove"
                else "\nSelect a Completed drawing to add:"
            )
        max_pages = max(1, (len(options) + 4) // 5)
        self.page = max(0, min(self.page, max_pages - 1))
        visible = options[self.page * 5 : (self.page + 1) * 5]
        lines = [header]
        for number, option in enumerate(visible, start=1):
            # Numbers keep buttons unambiguous even with long or duplicate snapshot names.
            lines.append(f"{number}. {discord.utils.escape_markdown(option.name)}")
            button = discord.ui.Button(label=str(number), row=0)

            async def select(interaction, selected_id=option.drawing_id):
                await self.select(interaction, selected_id)

            button.callback = select
            self.add_item(button)
        self.pagination(max_pages)
        return "\n".join(lines)

    def pagination(self, max_pages):
        if max_pages <= 1:
            return
        previous = discord.ui.Button(label="⬅️ Previous", row=1, disabled=self.page == 0)
        indicator = discord.ui.Button(
            label=f"Page {self.page + 1} / {max_pages}", row=1, disabled=True
        )
        following = discord.ui.Button(label="Next ➡️", row=1, disabled=self.page == max_pages - 1)

        async def move_previous(interaction):
            self.page -= 1
            await self.refresh(interaction)

        async def move_next(interaction):
            self.page += 1
            await self.refresh(interaction)

        previous.callback = move_previous
        following.callback = move_next
        for button in (previous, indicator, following):
            self.add_item(button)

    async def refresh(self, interaction, notice=""):
        content = self.render(interaction)
        await interaction.response.edit_message(
            content=(notice + "\n" if notice else "") + content,
            view=None if self.finished else self,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def select(self, interaction, selected_id):
        error = self.validate(interaction)
        if error:
            self.finish()
            await interaction.response.edit_message(content=error, view=None)
            return
        selected = next((d for d in self.options(interaction) if d.drawing_id == selected_id), None)
        if selected is None:
            await self.refresh(interaction, "That option is no longer available.")
            return
        if self.drawing_id is None:
            self.finish()
            command = self.group.get_command(self.command)
            await command.callback(self.group, interaction, name=selected.name)
            if self.message:
                try:
                    await self.message.edit(view=None)
                except discord.HTTPException:
                    pass
            return
        drawing = self.drawing()
        if self.command == "exclusion":
            if len(drawing.exclusions) >= 3:
                await self.refresh(interaction)
                return
            drawing.exclusions.append(
                SantaExclusion(
                    drawing_id=selected.drawing_id,
                    name=selected.name,
                    completed_at=selected.completed_at,
                    assignments=dict(selected.assignments),
                )
            )
            verb = "Added"
        else:
            drawing.exclusions = [d for d in drawing.exclusions if d.drawing_id != selected_id]
            verb = "Removed"
        state = self.group.bot.store.get_guild(self.guild_id)
        self.group.bot.store.update_guild(self.guild_id, state)
        await self.refresh(interaction, f"{verb} {discord.utils.escape_markdown(selected.name)}.")

    async def send(self, interaction):
        content = self.render(interaction)
        options = {} if self.finished else {"view": self}
        await interaction.response.send_message(
            content,
            **options,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        if not self.finished:
            self.message = await interaction.original_response()
