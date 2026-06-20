"""Integration tests for the cc_autoswitch switch / I-O path.

These exercise the full decision-and-act flow through ``main()`` WITHOUT a real
cswap binary and WITHOUT touching the real usage cache: the subprocess runner
(``_run``) and the usage source (``read_accounts`` / ``get_active_num``) are
monkeypatched. State files are written into a throwaway temp dir via the
CC_AUTOSWITCH_STATE_DIR environment variable, so nothing escapes the test.

Run: python3 -m unittest test_cc_autoswitch_integration -v
"""

import json
import os
import tempfile
import time
import unittest
from unittest import mock

import cc_autoswitch as a


class _FakeCompleted:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class _Harness:
    """Records cswap calls and serves canned usage/active/version responses."""

    def __init__(self, accounts, active, version="cswap 0.13.2"):
        self.accounts = accounts        # {num: pct or None}
        self.active = active            # active account number (str)
        self.version = version
        self.calls = []                 # list of arg-lists passed to _run

    def run(self, args, timeout=60, cswap=None):
        self.calls.append(list(args))
        if args and args[0] == "--version":
            return _FakeCompleted(stdout=self.version)
        if args and args[0] == "--status":
            return _FakeCompleted(stdout=f"Status: Account-{self.active} (x@y.z)")
        # --list and --switch-to: nothing to emit.
        return _FakeCompleted(stdout="ok")

    @property
    def switch_calls(self):
        return [c for c in self.calls if c and c[0] == "--switch-to"]


class _IntegrationBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cc-autoswitch-it-")
        self.addCleanup(self._cleanup_tmp)
        # Point state at the temp dir; everything else uses defaults/overrides.
        self._env = mock.patch.dict(
            os.environ,
            {"CC_AUTOSWITCH_STATE_DIR": self.tmp,
             "CC_AUTOSWITCH_CSWAP": "/nonexistent/cswap"},
            clear=False,
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    def _cleanup_tmp(self):
        for name in os.listdir(self.tmp):
            try:
                os.remove(os.path.join(self.tmp, name))
            except OSError:
                pass
        try:
            os.rmdir(self.tmp)
        except OSError:
            pass

    def _patch(self, harness):
        """Patch _run + usage source against *harness* for the duration of a test."""
        patches = [
            mock.patch.object(a, "_run", harness.run),
            mock.patch.object(a, "read_accounts", lambda usage_json=None: dict(harness.accounts)),
            mock.patch.object(a, "get_active_num", lambda cswap=None: harness.active),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _state_files(self):
        return {
            "stamp": os.path.join(self.tmp, ".cc-autoswitch.last"),
            "unavail": os.path.join(self.tmp, ".cc-autoswitch.unavail"),
            "log": os.path.join(self.tmp, "cc-autoswitch.log"),
        }


class TestSwitchPath(_IntegrationBase):
    def test_maxed_active_with_healthy_alt_switches(self):
        """(a) Active maxed + a healthy alternative -> cswap --switch-to <best>."""
        h = _Harness(accounts={"1": 100.0, "2": 30.0}, active="1")
        self._patch(h)

        rc = a.main([])

        self.assertEqual(rc, 0)
        self.assertEqual(h.switch_calls, [["--switch-to", "2"]])
        # Cooldown stamp written after a real switch.
        self.assertTrue(os.path.exists(self._state_files()["stamp"]))

    def test_picks_account_with_most_headroom(self):
        h = _Harness(accounts={"1": 99.0, "2": 70.0, "3": 15.0}, active="1")
        self._patch(h)

        a.main([])

        self.assertEqual(h.switch_calls, [["--switch-to", "3"]])

    def test_healthy_active_does_not_switch(self):
        h = _Harness(accounts={"1": 40.0, "2": 80.0}, active="1")
        self._patch(h)

        a.main([])

        self.assertEqual(h.switch_calls, [])


class TestCooldown(_IntegrationBase):
    def test_within_cooldown_suppresses_switch(self):
        """(b) A recent switch stamp suppresses another switch."""
        # Stamp "now" so we are well within the 300s default cooldown.
        with open(self._state_files()["stamp"], "w", encoding="utf-8") as fh:
            fh.write(str(int(time.time())))

        h = _Harness(accounts={"1": 100.0, "2": 20.0}, active="1")
        self._patch(h)

        rc = a.main([])

        self.assertEqual(rc, 0)
        self.assertEqual(h.switch_calls, [], "must not switch while cooling down")

    def test_expired_cooldown_allows_switch(self):
        # Stamp far in the past -> cooldown expired.
        with open(self._state_files()["stamp"], "w", encoding="utf-8") as fh:
            fh.write(str(int(time.time()) - 10_000))

        h = _Harness(accounts={"1": 100.0, "2": 20.0}, active="1")
        self._patch(h)

        a.main([])

        self.assertEqual(h.switch_calls, [["--switch-to", "2"]])


class TestDryRun(_IntegrationBase):
    def test_dry_run_no_switch_no_state(self):
        """(c) --dry-run performs no switch and writes no state files."""
        h = _Harness(accounts={"1": 100.0, "2": 20.0}, active="1")
        self._patch(h)

        rc = a.main(["--dry-run"])

        self.assertEqual(rc, 0)
        self.assertEqual(h.switch_calls, [], "dry-run must not switch")
        files = self._state_files()
        self.assertFalse(os.path.exists(files["stamp"]), "dry-run wrote a cooldown stamp")
        self.assertFalse(os.path.exists(files["unavail"]), "dry-run persisted streak state")

    def test_dry_run_still_refreshes_and_reads(self):
        # Sanity: dry-run still consults cswap (version + list + status) for a
        # truthful decision, it just doesn't act.
        h = _Harness(accounts={"1": 50.0, "2": 20.0}, active="1")
        self._patch(h)

        a.main(["--dry-run"])

        self.assertIn(["--list"], h.calls)


class TestConfigOverride(_IntegrationBase):
    def test_env_switch_at_override_changes_decision(self):
        """(d) Lowering switch_at via env makes a previously-safe account switch."""
        # 92% active: NOOP at the default 97% threshold...
        h = _Harness(accounts={"1": 92.0, "2": 20.0}, active="1")
        self._patch(h)
        a.main([])
        self.assertEqual(h.switch_calls, [], "no switch at default threshold")

        # ...but with switch_at lowered to 90 it must switch.
        h2 = _Harness(accounts={"1": 92.0, "2": 20.0}, active="1")
        self._patch(h2)
        with mock.patch.dict(os.environ, {"CC_AUTOSWITCH_SWITCH_AT": "90"}, clear=False):
            a.main([])
        self.assertEqual(h2.switch_calls, [["--switch-to", "2"]])

    def test_env_min_improvement_override_changes_decision(self):
        # Active 99, best alt 96: only a 3pt gain. Default min_improvement=10 -> NOOP.
        h = _Harness(accounts={"1": 99.0, "2": 96.0}, active="1")
        self._patch(h)
        a.main([])
        self.assertEqual(h.switch_calls, [], "marginal gain stays put by default")

        # Lower the anti-thrash margin to 1pt -> the 3pt gain now qualifies.
        h2 = _Harness(accounts={"1": 99.0, "2": 96.0}, active="1")
        self._patch(h2)
        with mock.patch.dict(os.environ, {"CC_AUTOSWITCH_MIN_IMPROVEMENT": "1"}, clear=False):
            a.main([])
        self.assertEqual(h2.switch_calls, [["--switch-to", "2"]])

    def test_file_config_override_changes_decision(self):
        # Same as the env test but the override comes from a TOML config file,
        # proving the file layer (not just env) is wired through main().
        cfg_path = os.path.join(self.tmp, "config.toml")
        with open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write("switch_at = 90.0\n")

        h = _Harness(accounts={"1": 92.0, "2": 20.0}, active="1")
        self._patch(h)
        with mock.patch.dict(os.environ, {"CC_AUTOSWITCH_CONFIG": cfg_path}, clear=False):
            a.main([])
        self.assertEqual(h.switch_calls, [["--switch-to", "2"]])

    def test_env_beats_file(self):
        # File says 90 (would switch a 92% account); env says 95 (would not).
        cfg_path = os.path.join(self.tmp, "config.toml")
        with open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write("switch_at = 90.0\n")

        h = _Harness(accounts={"1": 92.0, "2": 20.0}, active="1")
        self._patch(h)
        with mock.patch.dict(
            os.environ,
            {"CC_AUTOSWITCH_CONFIG": cfg_path, "CC_AUTOSWITCH_SWITCH_AT": "95"},
            clear=False,
        ):
            a.main([])
        self.assertEqual(h.switch_calls, [], "env switch_at=95 must win over file=90")


class TestStatusReadOnly(_IntegrationBase):
    def test_status_does_not_switch_or_write_state(self):
        h = _Harness(accounts={"1": 100.0, "2": 20.0}, active="1")
        self._patch(h)

        rc = a.main(["status"])

        self.assertEqual(rc, 0)
        self.assertEqual(h.switch_calls, [], "status must never switch")
        files = self._state_files()
        self.assertFalse(os.path.exists(files["stamp"]))
        self.assertFalse(os.path.exists(files["unavail"]))


class TestDoctor(_IntegrationBase):
    def test_doctor_fails_with_single_account(self):
        # One managed account is a critical FAIL -> non-zero exit.
        h = _Harness(accounts={"1": 50.0}, active="1")
        self._patch(h)
        # cswap "present" so the account check is the one that fails.
        with mock.patch.object(a.shutil, "which", lambda name: "/usr/bin/cswap"):
            rc = a.main(["doctor"])
        self.assertNotEqual(rc, 0)

    def test_doctor_passes_environment_checks(self):
        h = _Harness(accounts={"1": 50.0, "2": 20.0}, active="1")
        self._patch(h)
        with mock.patch.object(a.shutil, "which", lambda name: "/usr/bin/cswap"), \
             mock.patch.object(a, "_crontab_has_entry", lambda: True):
            rc = a.main(["doctor"])
        # 2 accounts, writable temp state dir, py>=3.11, cron present, cswap ok.
        self.assertEqual(rc, 0)


class TestInit(_IntegrationBase):
    def test_init_creates_config_from_example(self):
        cfg_path = os.path.join(self.tmp, "config.toml")
        with mock.patch.dict(os.environ, {"CC_AUTOSWITCH_CONFIG": cfg_path}, clear=False):
            rc = a.main(["init"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(cfg_path))
        contents = open(cfg_path, encoding="utf-8").read()
        self.assertIn("switch_at", contents)

    def test_init_is_idempotent(self):
        cfg_path = os.path.join(self.tmp, "config.toml")
        with open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write("switch_at = 88.0\n")
        with mock.patch.dict(os.environ, {"CC_AUTOSWITCH_CONFIG": cfg_path}, clear=False):
            rc = a.main(["init"])
        self.assertEqual(rc, 0)
        # Existing config must be preserved, not overwritten.
        self.assertEqual(open(cfg_path, encoding="utf-8").read(), "switch_at = 88.0\n")


if __name__ == "__main__":
    unittest.main()
