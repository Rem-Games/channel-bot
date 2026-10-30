import itertools
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from remchannelbot.bot import SantaDeleteConfirm, SantaGroup
from remchannelbot.santa import (
    close_santa_drawing,
    complete_santa_drawing,
    constrained_assignment,
    drawing_sort_key,
)
from remchannelbot.santa_views import SantaConversation, details_pages
from remchannelbot.state import (
    SANTA_CLOSED,
    SANTA_COMPLETED,
    SANTA_OPEN,
    GuildState,
    SantaExclusion,
    SecretSantaDrawing,
    StateStore,
)


def drawing(name="Game", **kwargs):
    return SecretSantaDrawing(name=name, creator_id=1, **kwargs)


class SantaLifecycleTests(unittest.TestCase):
    def test_legacy_migration_retains_assignments_without_inventing_times(self):
        state = GuildState.from_dict(
            {
                "santa_drawings": {
                    "old": {
                        "name": "Old",
                        "closed": True,
                        "participant_ids": [1, 2],
                        "assignments": {"1": 2, "2": 1},
                    },
                    "open": {"name": "Open", "closed": False},
                }
            }
        ).normalized()
        old = state.santa_drawings["old"]
        self.assertEqual(old.state, SANTA_CLOSED)
        self.assertEqual(old.assignments, {1: 2, 2: 1})
        self.assertEqual((old.created_at, old.closed_at, old.completed_at), (None, None, None))
        self.assertEqual(state.santa_drawings["open"].state, SANTA_OPEN)

    @patch("remchannelbot.santa.timestamp", return_value=100)
    def test_close_backfills_only_missing_created_timestamp(self, _clock):
        for created, expected in [(None, 100), (10, 10)]:
            game = drawing(participant_ids=[1, 2], created_at=created)
            close_santa_drawing(game)
            self.assertEqual(
                (game.state, game.created_at, game.closed_at), (SANTA_CLOSED, expected, 100)
            )

    @patch("remchannelbot.santa.timestamp", return_value=100)
    def test_completion_backfills_only_missing_times(self, _clock):
        for created, closed in [(None, None), (10, None), (None, 20), (10, 20)]:
            game = drawing(state=SANTA_CLOSED, created_at=created, closed_at=closed)
            complete_santa_drawing(game)
            self.assertEqual(game.created_at, created if created is not None else 100)
            self.assertEqual(game.closed_at, closed if closed is not None else 100)
            self.assertEqual(game.completed_at, 100)
            self.assertEqual(game.state, SANTA_COMPLETED)

    def test_invalid_transitions_do_not_mutate(self):
        for status in [SANTA_OPEN, SANTA_COMPLETED]:
            game = drawing(state=status)
            with self.assertRaises(ValueError):
                complete_santa_drawing(game)
            self.assertEqual(game.state, status)
            self.assertIsNone(game.completed_at)
        with self.assertRaises(ValueError):
            close_santa_drawing(drawing(state=SANTA_COMPLETED))

    def test_redraw_preserves_closed_timestamp(self):
        game = drawing(state=SANTA_CLOSED, participant_ids=[1, 2], created_at=10, closed_at=20)
        close_santa_drawing(game)
        self.assertEqual((game.created_at, game.closed_at), (10, 20))
        legacy = drawing(state=SANTA_CLOSED, participant_ids=[1, 2])
        close_santa_drawing(legacy)
        self.assertIsNone(legacy.closed_at)

    def test_sort_uses_current_state_time_then_name_with_unknown_last(self):
        games = [
            drawing("Unknown"),
            drawing("Z", created_at=20),
            drawing("A", created_at=20),
            drawing("Closed", state=SANTA_CLOSED, created_at=100, closed_at=10),
            drawing("Done", state=SANTA_COMPLETED, completed_at=30),
        ]
        self.assertEqual(
            [d.name for d in sorted(games, key=drawing_sort_key)],
            ["Done", "A", "Z", "Closed", "Unknown"],
        )

    def test_snapshot_survives_source_deletion_and_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(path)
            source = drawing(
                "Old",
                state=SANTA_COMPLETED,
                participant_ids=[1, 2],
                assignments={1: 2, 2: 1},
                completed_at=50,
            )
            target = drawing(
                exclusions=[
                    SantaExclusion(
                        source.drawing_id,
                        source.name,
                        source.completed_at,
                        dict(source.assignments),
                    )
                ]
            )
            state = store.get_guild(1)
            state.santa_drawings = {"game": target, "old": source}
            del state.santa_drawings["old"]
            state.santa_drawings["old"] = drawing("Old")
            store.update_guild(1, state)
            loaded = StateStore(path).get_guild(1)
            snapshot = loaded.santa_drawings["game"].exclusions[0]
            self.assertEqual(snapshot.assignments, {1: 2, 2: 1})
            self.assertEqual(snapshot.completed_at, 50)
            self.assertNotEqual(snapshot.drawing_id, loaded.santa_drawings["old"].drawing_id)
            self.assertNotIn('"closed":', path.read_text())


class SantaMatchingTests(unittest.TestCase):
    def test_matching_matches_brute_force_feasibility(self):
        rng = random.Random(42)
        for count in range(2, 7):
            participants = list(range(count))
            pairs = list(itertools.product(participants, repeat=2))
            for _ in range(40):
                forbidden = {pair for pair in pairs if rng.random() < 0.5}
                feasible = any(
                    all(
                        a != b and (a, b) not in forbidden
                        for a, b in zip(participants, permutation, strict=True)
                    )
                    for permutation in itertools.permutations(participants)
                )
                result = constrained_assignment(participants, forbidden)
                self.assertEqual(result is not None, feasible)
                if result is not None:
                    self.assertEqual(set(result), set(participants))
                    self.assertEqual(set(result.values()), set(participants))
                    self.assertTrue(
                        all(a != b and (a, b) not in forbidden for a, b in result.items())
                    )

    def test_respects_all_exclusions_when_possible(self):
        old = {1: 2, 2: 3, 3: 4, 4: 1}
        recent = {1: 3, 2: 4, 3: 1, 4: 2}
        game = drawing(
            participant_ids=[1, 2, 3, 4],
            exclusions=[
                SantaExclusion("old", "Old", 10, old),
                SantaExclusion("recent", "Recent", 20, recent),
            ],
        )
        self.assertEqual(close_santa_drawing(game), [])
        self.assertTrue(
            all(
                giftee not in {old[giver], recent[giver]}
                for giver, giftee in game.assignments.items()
            )
        )

    def test_relaxes_oldest_first_regardless_of_add_order(self):
        old = {1: 2, 2: 3, 3: 1}
        recent = {1: 3, 2: 1, 3: 2}
        game = drawing(
            participant_ids=[1, 2, 3],
            exclusions=[
                SantaExclusion("recent", "Recent", 20, recent),
                SantaExclusion("old", "Old", 10, old),
            ],
        )
        self.assertEqual(close_santa_drawing(game), ["Old"])
        self.assertEqual(game.assignments, old)
        self.assertEqual(len(game.exclusions), 2)

    def test_relaxes_every_exclusion_if_necessary(self):
        game = drawing(
            participant_ids=[1, 2],
            exclusions=[
                SantaExclusion(str(time), str(time), time, {1: 2, 2: 1}) for time in [30, 10, 20]
            ],
        )
        self.assertEqual(close_santa_drawing(game), ["10", "20", "30"])
        self.assertEqual(game.assignments, {1: 2, 2: 1})

    def test_ignores_excluded_participants_not_in_new_drawing(self):
        game = drawing(
            participant_ids=[1, 2], exclusions=[SantaExclusion("old", "Old", 10, {1: 3, 3: 1})]
        )
        self.assertEqual(close_santa_drawing(game), [])
        self.assertEqual(game.assignments, {1: 2, 2: 1})


class SantaCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / "state.json")
        self.group = SantaGroup(SimpleNamespace(store=self.store))
        self.state = self.store.get_guild(10)
        self.state.santa_channel_id = 20
        self.interaction = self.make_interaction()

    def make_interaction(self, user_id=1, admin=False):
        member = MagicMock(spec=discord.Member)
        member.id = user_id
        member.mention = f"<@{user_id}>"
        member.guild.owner_id = 999
        member.guild_permissions.administrator = admin
        interaction = MagicMock()
        interaction.user = member
        interaction.guild_id = 10
        interaction.channel_id = 20
        interaction.response.send_message = AsyncMock()
        interaction.response.edit_message = AsyncMock()
        interaction.original_response = AsyncMock()
        interaction.message.edit = AsyncMock()
        return interaction

    def add(self, game):
        self.state.santa_drawings[game.name.casefold()] = game
        return game

    async def run_command(self, command, name=None, interaction=None):
        await self.group.get_command(command).callback(
            self.group, interaction or self.interaction, name=name
        )

    def test_all_requested_command_names_are_optional(self):
        for name in [
            "delete",
            "join",
            "leave",
            "close",
            "giftee",
            "completed",
            "details",
            "exclusion",
            "exclusion-remove",
        ]:
            self.assertFalse(self.group.get_command(name).parameters[0].required)

    async def test_create_records_timestamp(self):
        with patch("remchannelbot.bot.timestamp", return_value=123):
            await self.run_command("create", "New")
        self.assertEqual(self.state.santa_drawings["new"].created_at, 123)

    async def test_singleton_join_preserves_already_joined_message(self):
        self.add(drawing(participant_ids=[1]))
        await self.run_command("join")
        self.assertIn("already in", self.interaction.response.send_message.call_args.args[0])

    async def test_multiple_join_filters_down_to_one_and_executes(self):
        self.add(drawing("Joined", participant_ids=[1]))
        other = self.add(drawing("Other"))
        await self.run_command("join")
        self.assertEqual(other.participant_ids, [1])

    async def test_joined_all_and_leave_none_messages(self):
        a = self.add(drawing("A", participant_ids=[1]))
        b = self.add(drawing("B", participant_ids=[1]))
        await self.run_command("join")
        self.assertIn("joined all Open", self.interaction.response.send_message.call_args.args[0])
        a.participant_ids = b.participant_ids = []
        await self.run_command("leave")
        self.assertIn("not in any Open", self.interaction.response.send_message.call_args.args[0])

    async def test_singleton_leave_preserves_not_joined_message(self):
        self.add(drawing())
        await self.run_command("leave")
        self.assertIn("not in", self.interaction.response.send_message.call_args.args[0])

    def test_manage_filter_and_admin_override(self):
        mine = self.add(drawing("Mine"))
        theirs = self.add(SecretSantaDrawing("Theirs", creator_id=2))
        for command in ["close", "delete", "exclusion", "exclusion-remove"]:
            self.assertEqual(self.group.command_choices(self.interaction, command), [mine])
            choices = self.group.command_choices(self.make_interaction(admin=True), command)
            self.assertEqual(
                set(d.drawing_id for d in choices), {mine.drawing_id, theirs.drawing_id}
            )

    async def test_completed_permission_and_state_checks(self):
        game = self.add(drawing(state=SANTA_CLOSED))
        await self.run_command("completed", "Game", self.make_interaction(user_id=2))
        self.assertEqual(game.state, SANTA_CLOSED)
        await self.run_command("completed", "Game")
        self.assertEqual(game.state, SANTA_COMPLETED)
        completed_at = game.completed_at
        await self.run_command("completed", "Game")
        self.assertEqual(game.completed_at, completed_at)

    async def test_named_completed_giftee_works_but_no_name_ignores_completed(self):
        self.add(drawing(state=SANTA_COMPLETED, participant_ids=[1, 2], assignments={1: 2, 2: 1}))
        await self.run_command("giftee", "Game")
        self.assertIn("you drew", self.interaction.response.send_message.call_args.args[0])
        self.assertTrue(self.interaction.response.send_message.call_args.kwargs["ephemeral"])
        await self.run_command("giftee")
        self.assertIn(
            "No eligible Closed", self.interaction.response.send_message.call_args.args[0]
        )

    async def test_admin_leave_blocks_completed_and_preserves_closed_time(self):
        game = self.add(
            drawing(
                state=SANTA_COMPLETED,
                participant_ids=[1, 2, 3],
                assignments={1: 2, 2: 3, 3: 1},
                closed_at=10,
            )
        )
        interaction = self.make_interaction(admin=True)
        member = SimpleNamespace(id=3, mention="<@3>")
        await self.group.admin_leave.callback(self.group, interaction, "Game", member)
        self.assertEqual(game.participant_ids, [1, 2, 3])
        game.state = SANTA_CLOSED
        await self.group.admin_leave.callback(self.group, interaction, "Game", member)
        self.assertEqual(game.participant_ids, [1, 2])
        self.assertEqual(game.assignments, {1: 2, 2: 1})
        self.assertEqual(game.closed_at, 10)

    async def test_details_available_to_nonparticipant_only_when_completed(self):
        game = self.add(drawing())
        visitor = self.make_interaction(user_id=2)
        await self.run_command("details", "Game", visitor)
        self.assertIn("only available", visitor.response.send_message.call_args.args[0])
        game.state = SANTA_COMPLETED
        game.completed_at = 123
        await self.run_command("details", "Game", visitor)
        self.assertIn("<t:123:F>", visitor.response.send_message.call_args.args[0])
        self.assertTrue(visitor.response.send_message.call_args.kwargs["ephemeral"])

    def test_details_pagination_preserves_every_participant_within_limit(self):
        ids = list(range(100000000000000000, 100000000000000100))
        game = drawing(
            state=SANTA_COMPLETED,
            completed_at=123,
            participant_ids=ids,
            assignments=dict(zip(ids, ids[1:] + ids[:1], strict=True)),
        )
        pages = details_pages(game)
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page) <= 2000 for page in pages))
        self.assertEqual(sum(page.count("Participant <@") for page in pages), 100)
        self.assertTrue(all("<t:123:F>" in page for page in pages))

    async def test_selection_pagination_and_execution(self):
        for index in range(7):
            self.add(drawing(str(index), created_at=index))
        await self.run_command("join")
        view = self.interaction.response.send_message.call_args.kwargs["view"]
        self.assertEqual(len(view.children), 8)
        self.assertEqual(view.children[6].label, "Page 1 / 2")
        self.assertTrue(view.children[5].disabled)
        await view.children[7].callback(self.interaction)
        self.assertEqual(len(view.children), 5)
        self.assertEqual(view.children[3].label, "Page 2 / 2")
        await view.children[0].callback(self.interaction)
        self.assertEqual(self.state.santa_drawings["1"].participant_ids, [1])
        self.assertTrue(view.finished)

    async def test_exclusions_refresh_until_three_and_remove_snapshot(self):
        target = self.add(drawing())
        sources = [
            self.add(
                drawing(
                    f"Old {i}",
                    state=SANTA_COMPLETED,
                    completed_at=i,
                    participant_ids=[1, 2],
                    assignments={1: 2, 2: 1},
                )
            )
            for i in range(4)
        ]
        view = SantaConversation(self.group, self.interaction, "exclusion", target)
        content = view.render(self.interaction)
        self.assertIn("add 3 more", content)
        for index in range(3):
            await view.select(self.interaction, sources[index].drawing_id)
            self.assertEqual(len(target.exclusions), index + 1)
        self.assertTrue(view.finished)
        self.assertIn(
            "limit of 3", self.interaction.response.edit_message.call_args.kwargs["content"]
        )
        del self.state.santa_drawings["old 0"]
        remove = SantaConversation(self.group, self.interaction, "exclusion-remove", target)
        self.assertIn("Old 0", remove.render(self.interaction))
        self.assertEqual(len(remove.children), 3)
        await remove.select(self.interaction, sources[0].drawing_id)
        self.assertEqual(len(target.exclusions), 2)
        self.assertFalse(remove.finished)

    async def test_exclusions_omit_already_added_and_paginate(self):
        target = self.add(drawing())
        for index in range(8):
            self.add(drawing(f"Old {index}", state=SANTA_COMPLETED, completed_at=index))
        view = SantaConversation(self.group, self.interaction, "exclusion", target)
        first = view.options(self.interaction)[0]
        await view.select(self.interaction, first.drawing_id)
        self.assertNotIn(first, view.options(self.interaction))
        self.assertEqual(len(view.children), 8)
        self.assertEqual(view.children[6].label, "Page 1 / 2")

    async def test_stale_exclusion_buttons_recheck_state_and_permissions(self):
        target = self.add(drawing())
        source = self.add(drawing("Old", state=SANTA_COMPLETED))
        for change in ["closed", "permission"]:
            target.state = SANTA_OPEN
            target.creator_id = 1
            view = SantaConversation(self.group, self.interaction, "exclusion", target)
            view.render(self.interaction)
            if change == "closed":
                target.state = SANTA_CLOSED
            else:
                target.creator_id = 2
            await view.select(self.interaction, source.drawing_id)
            self.assertFalse(target.exclusions)
            self.assertTrue(view.finished)

    async def test_stale_selection_cannot_target_recreated_drawing(self):
        original = self.add(drawing())
        self.add(drawing("Other"))
        view = SantaConversation(self.group, self.interaction, "join")
        view.render(self.interaction)
        replacement = self.add(drawing())
        await view.select(self.interaction, original.drawing_id)
        self.assertEqual(replacement.participant_ids, [])
        self.assertIn(
            "no longer available",
            self.interaction.response.edit_message.call_args.kwargs["content"],
        )

    async def test_deletion_confirmation_cannot_delete_replacement(self):
        self.add(drawing())
        view = SantaDeleteConfirm(self.group.bot, 10, "game", 1)
        replacement = self.add(drawing())
        await view.delete.callback(self.interaction)
        self.assertIs(self.state.santa_drawings["game"], replacement)

    async def test_finished_conversation_uses_real_discord_response_without_a_view(self):
        from discord.webhook.async_ import async_context

        target = self.add(drawing())
        interaction = self.make_interaction()
        interaction._state.allowed_mentions = None
        interaction.type = discord.InteractionType.application_command
        interaction.response = discord.InteractionResponse(interaction)
        adapter = SimpleNamespace(create_interaction_response=AsyncMock())
        token = async_context.set(adapter)
        try:
            await SantaConversation(self.group, interaction, "exclusion", target).send(interaction)
        finally:
            async_context.reset(token)
        self.assertTrue(interaction.response.is_done())
        payload = adapter.create_interaction_response.call_args.kwargs["params"].payload
        self.assertEqual(payload["data"]["flags"], 64)
        self.assertNotIn("components", payload["data"])

    async def test_two_conversations_cannot_exceed_exclusion_limit(self):
        target = self.add(drawing())
        sources = [self.add(drawing(f"Old {i}", state=SANTA_COMPLETED)) for i in range(4)]
        first = SantaConversation(self.group, self.interaction, "exclusion", target)
        second = SantaConversation(self.group, self.interaction, "exclusion", target)
        first.render(self.interaction)
        second.render(self.interaction)
        for source in sources[:3]:
            await first.select(self.interaction, source.drawing_id)
        await second.select(self.interaction, sources[3].drawing_id)
        self.assertEqual(len(target.exclusions), 3)
        self.assertTrue(second.finished)

    async def test_removing_last_exclusion_finishes_conversation(self):
        target = self.add(drawing(exclusions=[SantaExclusion("old", "Old", 1, {})]))
        view = SantaConversation(self.group, self.interaction, "exclusion-remove", target)
        await view.select(self.interaction, "old")
        self.assertEqual(target.exclusions, [])
        self.assertTrue(view.finished)

    async def test_details_buttons_paginate_all_results(self):
        ids = list(range(100000000000000000, 100000000000000100))
        target = self.add(
            drawing(
                state=SANTA_COMPLETED,
                completed_at=123,
                participant_ids=ids,
                assignments=dict(zip(ids, ids[1:] + ids[:1], strict=True)),
            )
        )
        view = SantaConversation(self.group, self.interaction, "details", target)
        view.render(self.interaction)
        self.assertEqual(len(view.children), 3)
        self.assertTrue(view.children[0].disabled)
        await view.children[2].callback(self.interaction)
        self.assertEqual(view.page, 1)
        self.assertIn(f"Page 2 / {len(details_pages(target))}", view.children[1].label)
        self.assertLessEqual(
            len(self.interaction.response.edit_message.call_args.kwargs["content"]), 2000
        )

    async def test_requester_channel_and_timeout_checks(self):
        self.add(drawing())
        view = SantaConversation(self.group, self.interaction, "join")
        self.assertFalse(await view.interaction_check(self.make_interaction(user_id=2)))
        wrong_channel = self.make_interaction()
        wrong_channel.channel_id = 30
        self.assertFalse(await view.interaction_check(wrong_channel))
        self.assertEqual(view.timeout, 300)
        view.message = MagicMock()
        view.message.edit = AsyncMock()
        await view.on_timeout()
        view.message.edit.assert_awaited_once_with(view=None)
        self.assertTrue(view.finished)
