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


if __name__ == "__main__":
    unittest.main()
