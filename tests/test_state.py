import unittest

from remchannelbot.state import DEFAULT_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES, GuildState, clean_candidate_name


class StateTests(unittest.TestCase):
    def test_guild_state_defaults_to_safe_interval(self) -> None:
        state = GuildState.from_dict({"interval_minutes": 1})

        self.assertEqual(state.interval_minutes, MIN_INTERVAL_MINUTES)

    def test_guild_state_defaults_when_empty(self) -> None:
        state = GuildState.from_dict({})

        self.assertEqual(state.interval_minutes, DEFAULT_INTERVAL_MINUTES)
        self.assertEqual(state.rotation_channel_ids, [])
        self.assertEqual(state.candidate_names, [])

    def test_clean_candidate_name_collapses_whitespace(self) -> None:
        self.assertEqual(clean_candidate_name("  alpha   beta  "), "alpha beta")

    def test_clean_candidate_name_rejects_empty(self) -> None:
        with self.assertRaisesRegex(ValueError, "1 to 100"):
            clean_candidate_name("   ")


if __name__ == "__main__":
    unittest.main()
