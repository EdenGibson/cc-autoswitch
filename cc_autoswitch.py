#!/usr/bin/env python3
"""Quota-aware Claude account auto-switcher (devbox).

Replaces the blind `cswap --switch` rotation. Each run:
  1. Forces a LIVE all-account usage refresh (deletes cswap's 15s cache, runs
     `cswap --list`), so the decision never rides a stale/partial cached value.
  2. Reads every account's 5h utilisation from cswap's usage.json.
  3. Decides via decide() — switch only to the account with the MOST headroom,
     never into one that is itself >= the switch threshold, and treat an
     "unavailable" active account (the maxed-active blind spot) as a trigger.
  4. Switches with `cswap --switch-to <num>` (targeted, not blind rotate),
     honouring a cooldown to avoid thrash.

Pure decision logic (pct_of / parse_active_num / decide) is unit-tested in
test_cc_autoswitch.py. The I/O glue is validated with --dry-run.

Run from cron every minute (via the cc-autoswitch.sh shim). Use --dry-run to
print the decision without switching.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

# ── Tunables ────────────────────────────────────────────────────────
SWITCH_AT = 97.0        # leave the active account at/above this 5h %
MIN_IMPROVEMENT = 10.0  # only switch if target is this many pts better (anti-thrash)
COOLDOWN = 300          # min seconds between switches
UNAVAIL_GRACE = 3       # consecutive "unavailable" runs (~minutes) before treating
                        # active as maxed — the active-usage endpoint returns null
                        # intermittently even for healthy accounts, so debounce.

# Paths — env-overridable so the tool is relocatable; defaults preserve the
# original devbox behaviour (state under ~/.claude, cswap from PATH).
HOME = os.path.expanduser("~")
STATE_DIR = os.environ.get("CC_AUTOSWITCH_STATE_DIR", os.path.join(HOME, ".claude"))
CSWAP = (os.environ.get("CC_AUTOSWITCH_CSWAP")
         or shutil.which("cswap")
         or os.path.join(HOME, ".local/bin/cswap"))
USAGE_JSON = os.environ.get(
    "CC_AUTOSWITCH_USAGE_JSON",
    os.path.join(HOME, ".local/share/claude-swap/cache/usage.json"))
LOG = os.path.join(STATE_DIR, "cc-autoswitch.log")
STAMP = os.path.join(STATE_DIR, ".cc-autoswitch.last")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


# ── Pure logic (unit-tested) ────────────────────────────────────────
def pct_of(entry, dimension: str = "five_hour"):
    """Return the float utilisation % for *dimension* in a usage.json entry.

    Entries may be a dict, ``None`` (usage unavailable), or a status string
    like "no credentials". Anything but a well-formed dict -> None.
    """
    if isinstance(entry, dict):
        dim = entry.get(dimension)
        if isinstance(dim, dict) and isinstance(dim.get("pct"), (int, float)):
            return float(dim["pct"])
    return None


def parse_active_num(status_text: str):
    """Extract the active account number from `cswap --status` output."""
    m = re.search(r"Account-(\d+)", _ANSI.sub("", status_text or ""))
    return m.group(1) if m else None


def decide(active_num, accounts, switch_at=SWITCH_AT, min_improvement=MIN_IMPROVEMENT,
           unavail_streak=0, unavail_grace=UNAVAIL_GRACE):
    """Decide whether to switch accounts.

    accounts: dict of account-number (str) -> 5h pct (float) or None (unavailable).
    unavail_streak: consecutive runs the active account's 5h has been unavailable.
        A single unavailable reading is treated as transient (e.g. the null seen
        right at a 5h reset boundary) and does NOT trigger failover until it has
        persisted for unavail_grace runs.
    Returns (action, target, reason) where action is "noop" or "switch".
    """
    if len(accounts) < 2:
        return ("noop", None, "fewer than 2 managed accounts")
    if active_num not in accounts:
        return ("noop", None, f"active account {active_num} not in managed set")

    active_pct = accounts[active_num]
    if active_pct is None:
        if unavail_streak < unavail_grace:
            return ("noop", None,
                    f"active acct {active_num} usage unavailable "
                    f"(streak {unavail_streak}/{unavail_grace}) — waiting before failover")
        need_to_leave = True
    else:
        need_to_leave = active_pct >= switch_at
    if not need_to_leave:
        return ("noop", None, f"active acct {active_num} at {active_pct:.0f}% < {switch_at:.0f}%")

    others = [(n, p) for n, p in accounts.items() if n != active_num]
    viable = [(n, p) for n, p in others if p is not None and p < switch_at]
    if not viable:
        return ("noop", None,
                "no alternative account has headroom (all >=97% or unavailable) — staying put")

    best_num, best_pct = min(viable, key=lambda np: np[1])
    if active_pct is not None and best_pct > active_pct - min_improvement:
        return ("noop", None,
                f"best alt acct {best_num} at {best_pct:.0f}% not >{min_improvement:.0f}pts "
                f"better than active {active_pct:.0f}% — staying put")

    active_desc = "unavailable" if active_pct is None else f"{active_pct:.0f}%"
    return ("switch", best_num,
            f"active acct {active_num} {active_desc} -> acct {best_num} at {best_pct:.0f}% (most headroom)")


def next_streak(prev_state, active, active_pct):
    """Compute the new consecutive-unavailable streak for the active account.

    prev_state: the persisted {"active": num, "streak": n} (or {}).
    Resets to 0 when usage is available; restarts at 1 when the active account
    changed; otherwise increments.
    """
    if active_pct is not None:
        return 0
    if prev_state.get("active") == active:
        return int(prev_state.get("streak", 0)) + 1
    return 1


# ── I/O glue (validated via --dry-run) ──────────────────────────────
def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _run(args, timeout=60):
    return subprocess.run([CSWAP, *args], capture_output=True, text=True, timeout=timeout)


def refresh_usage_live() -> None:
    """Drop the 15s cache and force a fresh all-account fetch."""
    try:
        os.remove(USAGE_JSON)
    except FileNotFoundError:
        pass
    except OSError:
        pass
    try:
        _run(["--list"])
    except (subprocess.SubprocessError, OSError) as e:
        log(f"cswap --list failed: {e!r}")


def read_accounts():
    """Return {num: 5h pct or None} from usage.json, or None on failure."""
    try:
        raw = json.loads(open(USAGE_JSON, encoding="utf-8").read())
        data = raw.get("data", {})
        return {str(num): pct_of(entry) for num, entry in data.items()}
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return None


def get_active_num():
    try:
        return parse_active_num(_run(["--status"]).stdout)
    except (subprocess.SubprocessError, OSError):
        return None


UNAVAIL_STATE = os.path.join(STATE_DIR, ".cc-autoswitch.unavail")


def unavail_streak_for(active, active_pct, persist=True):
    """Read prior state, compute the new streak via next_streak(), persist it.

    persist=False (used by --dry-run) computes the streak without writing state.
    """
    try:
        prev = json.loads(open(UNAVAIL_STATE, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError):
        prev = {}
    streak = next_streak(prev, active, active_pct)
    if persist:
        try:
            with open(UNAVAIL_STATE, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"active": active, "streak": streak}))
        except OSError:
            pass
    return streak


def within_cooldown():
    try:
        last = int(open(STAMP, encoding="utf-8").read().strip())
    except (OSError, ValueError):
        return False, 0
    elapsed = int(time.time()) - last
    return elapsed < COOLDOWN, elapsed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Quota-aware Claude account auto-switcher")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the decision but do not switch")
    args = ap.parse_args(argv)

    os.makedirs(STATE_DIR, exist_ok=True)
    refresh_usage_live()
    accounts = read_accounts()
    if not accounts:
        log("usage data unavailable — skipping")
        return 0
    active = get_active_num()
    if not active:
        log("could not determine active account — skipping")
        return 0

    streak = unavail_streak_for(active, accounts.get(active), persist=not args.dry_run)
    action, target, reason = decide(active, accounts, unavail_streak=streak)
    snapshot = ", ".join(
        f"{n}={'NA' if p is None else f'{p:.0f}%'}" for n, p in sorted(accounts.items())
    )

    if args.dry_run:
        print(f"active={active} [{snapshot}] -> {action.upper()}"
              f"{f' to {target}' if target else ''}: {reason}")
        return 0

    if action != "switch":
        return 0

    cooling, elapsed = within_cooldown()
    if cooling:
        log(f"would switch ({reason}) but within cooldown ({elapsed}s) — skip")
        return 0

    log(f"switching: {reason} [{snapshot}]")
    try:
        out = _run(["--switch-to", target])
        flat = " ".join((out.stdout + out.stderr).split())
        log(f"cswap --switch-to {target}: {flat[:300]}")
    except (subprocess.SubprocessError, OSError) as e:
        log(f"cswap --switch-to {target} failed: {e!r}")
        return 1
    try:
        with open(STAMP, "w", encoding="utf-8") as fh:
            fh.write(str(int(time.time())))
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
