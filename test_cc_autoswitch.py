"""Unit tests for cc_autoswitch decision logic.

Pure-function tests only: no cswap invocation, no real account switching.
Run: python3 -m unittest test_cc_autoswitch -v
"""

import unittest

import cc_autoswitch as a


class TestPctOf(unittest.TestCase):
    def test_five_hour_pct_extracted(self):
        self.assertEqual(a.pct_of({"five_hour": {"pct": 83.0}}), 83.0)

    def test_integer_pct_coerced_to_float(self):
        self.assertEqual(a.pct_of({"five_hour": {"pct": 100}}), 100.0)

    def test_none_entry_is_none(self):
        self.assertIsNone(a.pct_of(None))

    def test_string_entry_is_none(self):
        self.assertIsNone(a.pct_of("no credentials"))

    def test_missing_dimension_is_none(self):
        self.assertIsNone(a.pct_of({}))

    def test_null_dimension_is_none(self):
        self.assertIsNone(a.pct_of({"five_hour": None}))

    def test_seven_day_dimension(self):
        self.assertEqual(a.pct_of({"seven_day": {"pct": 36}}, "seven_day"), 36.0)


class TestParseActiveNum(unittest.TestCase):
    def test_plain_status_line(self):
        text = "Status: Account-2 (matthewjmartin06@gmail.com [Org])\n  Total managed accounts: 2"
        self.assertEqual(a.parse_active_num(text), "2")

    def test_status_line_with_ansi(self):
        text = "\x1b[1mStatus:\x1b[0m \x1b[38;5;173mAccount-1\x1b[0m (edengibson355@gmail.com)"
        self.assertEqual(a.parse_active_num(text), "1")

    def test_no_active_account(self):
        self.assertIsNone(a.parse_active_num("Status: No active Claude account"))

    def test_empty(self):
        self.assertIsNone(a.parse_active_num(""))


class TestNextStreak(unittest.TestCase):
    def test_first_unavailable_is_one(self):
        self.assertEqual(a.next_streak({}, "1", None), 1)

    def test_consecutive_unavailable_increments(self):
        self.assertEqual(a.next_streak({"active": "1", "streak": 1}, "1", None), 2)

    def test_available_resets_to_zero(self):
        self.assertEqual(a.next_streak({"active": "1", "streak": 5}, "1", 50.0), 0)

    def test_zero_pct_still_resets(self):
        self.assertEqual(a.next_streak({"active": "1", "streak": 3}, "1", 0.0), 0)

    def test_active_account_change_restarts_streak(self):
        self.assertEqual(a.next_streak({"active": "2", "streak": 3}, "1", None), 1)


class TestDecide(unittest.TestCase):
    # Normal operation: active account has headroom -> stay put.
    def test_active_below_threshold_noop(self):
        action, target, _ = a.decide("1", {"1": 83.0, "2": 100.0})
        self.assertEqual(action, "noop")
        self.assertIsNone(target)

    # The 21:26 incident: active near full, ONLY other account is maxed.
    # Must NOT rotate into a 100% account.
    def test_other_account_maxed_does_not_switch(self):
        action, target, _ = a.decide("1", {"1": 99.0, "2": 100.0})
        self.assertEqual(action, "noop")
        self.assertIsNone(target)

    # Active maxed, a genuinely fresh account exists -> switch to it.
    def test_switch_to_account_with_headroom(self):
        action, target, _ = a.decide("1", {"1": 99.0, "2": 50.0})
        self.assertEqual(action, "switch")
        self.assertEqual(target, "2")

    # Active usage unavailable that PERSISTS (the maxed-active blind spot) ->
    # treat as a trigger and fail over to a healthy account, not bail.
    def test_active_unavailable_persistent_triggers_failover(self):
        action, target, _ = a.decide("2", {"1": 40.0, "2": None},
                                     unavail_streak=2, unavail_grace=2)
        self.assertEqual(action, "switch")
        self.assertEqual(target, "1")

    # Below the grace threshold (e.g. transient null at the 5h reset boundary,
    # or the flaky active-usage endpoint) must NOT flee a possibly-healthy acct.
    def test_active_unavailable_below_grace_waits(self):
        action, target, _ = a.decide("2", {"1": 40.0, "2": None},
                                     unavail_streak=1, unavail_grace=2)
        self.assertEqual(action, "noop")
        self.assertIsNone(target)

    # A numeric maxed reading is trustworthy (not a transient null) -> switch
    # immediately, no debounce needed.
    def test_active_maxed_switches_without_debounce(self):
        action, target, _ = a.decide("1", {"1": 100.0, "2": 30.0}, unavail_streak=0)
        self.assertEqual(action, "switch")
        self.assertEqual(target, "2")

    # Active unavailable (persistent) AND only other account also unavailable
    # -> stay put (don't blind-jump into an unknown account).
    def test_active_unavailable_no_known_alternative_noop(self):
        action, target, _ = a.decide("2", {"1": None, "2": None},
                                     unavail_streak=2, unavail_grace=2)
        self.assertEqual(action, "noop")
        self.assertIsNone(target)

    # Both accounts near full: switching buys nothing -> stay put (anti-thrash).
    def test_marginal_improvement_does_not_switch(self):
        action, target, _ = a.decide("1", {"1": 98.0, "2": 96.0})
        self.assertEqual(action, "noop")
        self.assertIsNone(target)

    # Picks the account with the MOST headroom among several alternatives.
    def test_picks_lowest_usage_target(self):
        action, target, _ = a.decide("1", {"1": 99.0, "2": 70.0, "3": 20.0})
        self.assertEqual(action, "switch")
        self.assertEqual(target, "3")

    def test_single_account_noop(self):
        action, target, _ = a.decide("1", {"1": 99.0})
        self.assertEqual(action, "noop")
        self.assertIsNone(target)

    def test_all_accounts_maxed_noop(self):
        action, target, _ = a.decide("1", {"1": 100.0, "2": 100.0})
        self.assertEqual(action, "noop")
        self.assertIsNone(target)

    def test_active_account_not_in_set_noop(self):
        action, target, _ = a.decide("9", {"1": 10.0, "2": 20.0})
        self.assertEqual(action, "noop")
        self.assertIsNone(target)

    # Reason string is human-meaningful for the log.
    def test_reason_mentions_target_on_switch(self):
        _, _, reason = a.decide("1", {"1": 99.0, "2": 30.0})
        self.assertIn("2", reason)


class TestResolveConfig(unittest.TestCase):
    """Config precedence: environment variable > config file value > default."""

    HOME = "/home/tester"

    def _resolve(self, env=None, file_cfg=None):
        return a.resolve_config(env or {}, file_cfg or {}, home=self.HOME)

    def test_defaults_when_no_env_no_file(self):
        cfg = self._resolve()
        self.assertEqual(cfg["switch_at"], a.DEFAULTS["switch_at"])
        self.assertEqual(cfg["min_improvement"], a.DEFAULTS["min_improvement"])
        self.assertEqual(cfg["cooldown"], a.DEFAULTS["cooldown"])
        self.assertEqual(cfg["unavail_grace"], a.DEFAULTS["unavail_grace"])

    def test_default_paths_derive_from_home(self):
        cfg = self._resolve()
        self.assertEqual(cfg["state_dir"], "/home/tester/.claude")
        self.assertEqual(
            cfg["usage_json"],
            "/home/tester/.local/share/claude-swap/cache/usage.json",
        )

    def test_file_overrides_default(self):
        cfg = self._resolve(file_cfg={"switch_at": 90.0, "cooldown": 600})
        self.assertEqual(cfg["switch_at"], 90.0)
        self.assertEqual(cfg["cooldown"], 600)
        # Untouched key still falls back to default.
        self.assertEqual(cfg["min_improvement"], a.DEFAULTS["min_improvement"])

    def test_env_overrides_file(self):
        cfg = self._resolve(
            env={"CC_AUTOSWITCH_SWITCH_AT": "85"},
            file_cfg={"switch_at": 90.0},
        )
        self.assertEqual(cfg["switch_at"], 85.0)

    def test_env_overrides_default_without_file(self):
        cfg = self._resolve(env={"CC_AUTOSWITCH_COOLDOWN": "120"})
        self.assertEqual(cfg["cooldown"], 120)

    def test_numeric_env_coerced_to_correct_types(self):
        cfg = self._resolve(env={
            "CC_AUTOSWITCH_SWITCH_AT": "88.5",
            "CC_AUTOSWITCH_MIN_IMPROVEMENT": "5",
            "CC_AUTOSWITCH_COOLDOWN": "450",
            "CC_AUTOSWITCH_UNAVAIL_GRACE": "4",
        })
        self.assertIsInstance(cfg["switch_at"], float)
        self.assertEqual(cfg["switch_at"], 88.5)
        self.assertIsInstance(cfg["min_improvement"], float)
        self.assertEqual(cfg["min_improvement"], 5.0)
        self.assertIsInstance(cfg["cooldown"], int)
        self.assertEqual(cfg["cooldown"], 450)
        self.assertIsInstance(cfg["unavail_grace"], int)
        self.assertEqual(cfg["unavail_grace"], 4)

    def test_path_env_overrides_file_and_default(self):
        cfg = self._resolve(
            env={"CC_AUTOSWITCH_STATE_DIR": "/env/state",
                 "CC_AUTOSWITCH_USAGE_JSON": "/env/usage.json"},
            file_cfg={"state_dir": "/file/state",
                      "usage_json": "/file/usage.json"},
        )
        self.assertEqual(cfg["state_dir"], "/env/state")
        self.assertEqual(cfg["usage_json"], "/env/usage.json")

    def test_path_file_overrides_default(self):
        cfg = self._resolve(file_cfg={"state_dir": "/file/state"})
        self.assertEqual(cfg["state_dir"], "/file/state")

    def test_cswap_default_uses_supplied_fallback(self):
        cfg = a.resolve_config({}, {}, home=self.HOME,
                               cswap_default="/usr/bin/cswap")
        self.assertEqual(cfg["cswap"], "/usr/bin/cswap")

    def test_cswap_env_overrides_fallback(self):
        cfg = a.resolve_config(
            {"CC_AUTOSWITCH_CSWAP": "/custom/cswap"}, {},
            home=self.HOME, cswap_default="/usr/bin/cswap",
        )
        self.assertEqual(cfg["cswap"], "/custom/cswap")

    def test_python_env_overrides_file_and_default(self):
        cfg = self._resolve(
            env={"CC_AUTOSWITCH_PYTHON": "/env/python3"},
            file_cfg={"python": "/file/python3"},
        )
        self.assertEqual(cfg["python"], "/env/python3")

    def test_unknown_file_keys_ignored(self):
        # A config file with a stray/unsupported key must not crash or leak in.
        cfg = self._resolve(file_cfg={"bogus": 123, "switch_at": 91.0})
        self.assertNotIn("bogus", cfg)
        self.assertEqual(cfg["switch_at"], 91.0)

    def test_malformed_numeric_env_falls_back(self):
        # A non-numeric env value must not crash; falls back to file/default.
        cfg = self._resolve(
            env={"CC_AUTOSWITCH_SWITCH_AT": "not-a-number"},
            file_cfg={"switch_at": 92.0},
        )
        self.assertEqual(cfg["switch_at"], 92.0)


class TestParseCswapVersion(unittest.TestCase):
    def test_standard_version_line(self):
        self.assertEqual(a.parse_cswap_version("cswap 0.13.2"), (0, 13, 2))

    def test_version_with_trailing_whitespace(self):
        self.assertEqual(a.parse_cswap_version("cswap 0.13.2\n"), (0, 13, 2))

    def test_bare_version_number(self):
        self.assertEqual(a.parse_cswap_version("0.14.0"), (0, 14, 0))

    def test_unparseable_is_none(self):
        self.assertIsNone(a.parse_cswap_version("not a version"))

    def test_empty_is_none(self):
        self.assertIsNone(a.parse_cswap_version(""))
        self.assertIsNone(a.parse_cswap_version(None))


class TestCswapVersionOk(unittest.TestCase):
    def test_known_good_minor_ok(self):
        self.assertTrue(a.cswap_version_ok((0, 13, 0)))
        self.assertTrue(a.cswap_version_ok((0, 13, 99)))

    def test_different_minor_not_ok(self):
        self.assertFalse(a.cswap_version_ok((0, 12, 0)))
        self.assertFalse(a.cswap_version_ok((0, 14, 0)))

    def test_different_major_not_ok(self):
        self.assertFalse(a.cswap_version_ok((1, 13, 0)))

    def test_none_not_ok(self):
        self.assertFalse(a.cswap_version_ok(None))


if __name__ == "__main__":
    unittest.main()
