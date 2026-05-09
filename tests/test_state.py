import unittest

from remchannelbot.state import (
    DEFAULT_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    ROTATION_MODE_ONE,
    GuildState,
    clean_candidate_name,
)
from remchannelbot.bot import next_candidate_name


class StateTests(unittest.TestCase):
    def test_guild_state_defaults_to_safe_interval(self) -> None:
        state = GuildState.from_dict({"interval_minutes": 1})

        self.assertEqual(state.interval_minutes, MIN_INTERVAL_MINUTES)

    def test_guild_state_defaults_when_empty(self) -> None:
        state = GuildState.from_dict({})

        self.assertEqual(state.interval_minutes, DEFAULT_INTERVAL_MINUTES)
        self.assertEqual(state.rotation_mode, ROTATION_MODE_ONE)
        self.assertFalse(state.quiet_mode)
        self.assertEqual(state.rotation_channel_ids, [])
        self.assertEqual(state.candidate_names, [])

    def test_guild_state_defaults_unknown_rotation_mode_to_one(self) -> None:
        state = GuildState.from_dict({"rotation_mode": "bad"}).normalized()

        self.assertEqual(state.rotation_mode, ROTATION_MODE_ONE)

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


if __name__ == "__main__":
    unittest.main()
