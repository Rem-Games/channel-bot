import unittest
from unittest.mock import patch

from remchannelbot.state import (
    DEFAULT_INTERVAL_MINUTES,
    LIST_MODE_EXHAUSTIVE,
    LIST_MODE_RANDOM,
    MIN_INTERVAL_MINUTES,
    ROTATION_MODE_ONE,
    GuildState,
    clean_candidate_name,
)
from remchannelbot.bot import candidate_key, next_candidate_name, normalize_text_channel_name


class StateTests(unittest.TestCase):
    def test_guild_state_defaults_to_safe_interval(self) -> None:
        state = GuildState.from_dict({"interval_minutes": 1})

        self.assertEqual(state.interval_minutes, MIN_INTERVAL_MINUTES)

    def test_guild_state_defaults_when_empty(self) -> None:
        state = GuildState.from_dict({})

        self.assertEqual(state.interval_minutes, DEFAULT_INTERVAL_MINUTES)
        self.assertEqual(state.rotation_mode, ROTATION_MODE_ONE)
        self.assertEqual(state.list_mode, LIST_MODE_RANDOM)
        self.assertFalse(state.quiet_mode)
        self.assertEqual(state.rotation_channel_ids, [])
        self.assertEqual(state.candidate_names, [])
        self.assertEqual(state.used_candidate_keys, [])

    def test_guild_state_defaults_unknown_rotation_mode_to_one(self) -> None:
        state = GuildState.from_dict({"rotation_mode": "bad"}).normalized()

        self.assertEqual(state.rotation_mode, ROTATION_MODE_ONE)

    def test_guild_state_defaults_unknown_list_mode_to_random(self) -> None:
        state = GuildState.from_dict({"list_mode": "bad"}).normalized()

        self.assertEqual(state.list_mode, LIST_MODE_RANDOM)

    def test_guild_state_prunes_used_candidate_keys(self) -> None:
        state = GuildState.from_dict(
            {
                "candidate_names": ["alpha"],
                "used_candidate_keys": ["alpha", "beta", "alpha"],
            }
        ).normalized()

        self.assertEqual(state.used_candidate_keys, ["alpha"])

    def test_clean_candidate_name_collapses_whitespace(self) -> None:
        self.assertEqual(clean_candidate_name("  alpha   beta  "), "alpha beta")

    def test_clean_candidate_name_rejects_empty(self) -> None:
        with self.assertRaisesRegex(ValueError, "1 to 100"):
            clean_candidate_name("   ")

    def test_next_candidate_name_skips_reserved_names(self) -> None:
        state = GuildState(candidate_names=["alpha", "beta", "gamma"])

        self.assertEqual(next_candidate_name(state, "old", {"alpha", "beta"}), "gamma")

    def test_next_candidate_name_returns_none_when_all_candidates_reserved(self) -> None:
        state = GuildState(candidate_names=["alpha", "beta"])

        self.assertIsNone(next_candidate_name(state, "old", {"alpha", "beta"}))

    def test_normalize_text_channel_name_matches_discord_text_style(self) -> None:
        self.assertEqual(normalize_text_channel_name("  Spicy   Channel  "), "spicy-channel")

    def test_normalize_text_channel_name_strips_punctuation(self) -> None:
        self.assertEqual(normalize_text_channel_name("ooo, banana"), "ooo-banana")

    def test_next_candidate_name_uses_transformed_names_for_reserved_check(self) -> None:
        state = GuildState(candidate_names=["Peaches Peaches", "Spicy Channel"])

        self.assertEqual(
            next_candidate_name(
                state,
                "old",
                {"peaches-peaches"},
                name_transform=normalize_text_channel_name,
            ),
            "spicy-channel",
        )

    def test_next_candidate_name_uses_transformed_names_for_current_check(self) -> None:
        state = GuildState(candidate_names=["Mild Channel"])

        self.assertIsNone(
            next_candidate_name(
                state,
                "mild-channel",
                name_transform=normalize_text_channel_name,
            )
        )

    def test_candidate_key_treats_spaces_and_hyphens_as_same_candidate(self) -> None:
        self.assertEqual(candidate_key("peaches peaches"), candidate_key("peaches-peaches"))

    def test_candidate_key_treats_comma_variants_as_same_candidate(self) -> None:
        self.assertEqual(candidate_key("ooo, banana"), candidate_key("ooo-banana"))

    def test_next_candidate_name_skips_reserved_candidate_key(self) -> None:
        state = GuildState(candidate_names=["peaches peaches", "saucy channel"])

        self.assertEqual(next_candidate_name(state, "old", {"peaches-peaches"}), "saucy channel")

    def test_exhaustive_list_mode_uses_all_names_before_repeating(self) -> None:
        state = GuildState(
            candidate_names=["alpha", "beta", "gamma"],
            list_mode=LIST_MODE_EXHAUSTIVE,
        )

        with patch("remchannelbot.bot.random.choice", side_effect=lambda values: values[0]):
            self.assertEqual(next_candidate_name(state, "old"), "alpha")
            self.assertEqual(next_candidate_name(state, "old"), "beta")
            self.assertEqual(next_candidate_name(state, "old"), "gamma")
            self.assertEqual(next_candidate_name(state, "old"), "alpha")

    def test_exhaustive_list_mode_resets_during_multi_channel_selection(self) -> None:
        state = GuildState(
            candidate_names=["alpha", "beta", "gamma"],
            list_mode=LIST_MODE_EXHAUSTIVE,
            used_candidate_keys=["alpha", "beta"],
        )

        with patch("remchannelbot.bot.random.choice", side_effect=lambda values: values[0]):
            self.assertEqual(next_candidate_name(state, "old"), "gamma")
            self.assertEqual(next_candidate_name(state, "old", {"gamma"}), "alpha")

        self.assertEqual(state.used_candidate_keys, ["alpha"])


if __name__ == "__main__":
    unittest.main()
