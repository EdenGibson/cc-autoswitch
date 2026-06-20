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

try:  # Python 3.11+ (stdlib). Guarded so a stray import error degrades gracefully.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 and older
    tomllib = None  # type: ignore[assignment]

# ── Configuration ───────────────────────────────────────────────────
# Built-in defaults. Every value here is overridable by a config file, which is
# in turn overridable by an environment variable. Precedence, lowest to
# highest:  built-in default  <  config file  <  environment variable.
#
# Tunables:
#   switch_at        leave the active account at/above this 5h %
#   min_improvement  only switch if target is this many pts better (anti-thrash)
#   cooldown         min seconds between switches
#   unavail_grace    consecutive "unavailable" runs (~minutes) before treating
#                    the active account as maxed — the active-usage endpoint
#                    returns null intermittently even for healthy accounts, so
#                    we debounce.
# Paths default to the original devbox behaviour (state under ~/.claude, cswap
# resolved from PATH). `python` is consumed by the shell shim, not this module.
DEFAULTS = {
    "switch_at": 97.0,
    "min_improvement": 10.0,
    "cooldown": 300,
    "unavail_grace": 3,
    "state_dir": None,     # -> {home}/.claude
    "cswap": None,         # -> shutil.which("cswap") or {home}/.local/bin/cswap
    "usage_json": None,    # -> {home}/.local/share/claude-swap/cache/usage.json
    "python": "/usr/bin/python3",
}

# config key -> environment variable that overrides it.
_ENV_KEYS = {
    "switch_at": "CC_AUTOSWITCH_SWITCH_AT",
    "min_improvement": "CC_AUTOSWITCH_MIN_IMPROVEMENT",
    "cooldown": "CC_AUTOSWITCH_COOLDOWN",
    "unavail_grace": "CC_AUTOSWITCH_UNAVAIL_GRACE",
    "state_dir": "CC_AUTOSWITCH_STATE_DIR",
    "cswap": "CC_AUTOSWITCH_CSWAP",
    "usage_json": "CC_AUTOSWITCH_USAGE_JSON",
    "python": "CC_AUTOSWITCH_PYTHON",
}

# config key -> coercion for env/file string values (paths stay as-is).
_COERCE = {
    "switch_at": float,
    "min_improvement": float,
    "cooldown": int,
    "unavail_grace": int,
}

# cswap versions this tool was developed and tested against.
KNOWN_CSWAP_MAJOR = 0
KNOWN_CSWAP_MINOR = 13

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def resolve_config(env, file_cfg, *, home, cswap_default=None):
    """Resolve effective config with precedence: env var > file > default.

    env:      mapping of environment variables (e.g. os.environ).
    file_cfg: mapping parsed from the TOML config file ({} if none).
    home:     home directory used to derive default paths.
    cswap_default: resolved cswap path to use when neither env nor file set it
                   (lets the PATH lookup stay out of this pure function).

    Unknown keys in *file_cfg* are ignored. Numeric env/file values are coerced;
    a malformed numeric value is ignored (falls back to the next-lower source)
    rather than crashing the run.
    """
    cfg = {}
    for key, default in DEFAULTS.items():
        # Lowest precedence: built-in default (with derived paths).
        if key == "state_dir" and default is None:
            value = os.path.join(home, ".claude")
        elif key == "cswap" and default is None:
            value = cswap_default or os.path.join(home, ".local/bin/cswap")
        elif key == "usage_json" and default is None:
            value = os.path.join(home, ".local/share/claude-swap/cache/usage.json")
        else:
            value = default

        # Middle precedence: config file.
        if key in file_cfg:
            value = _apply(key, file_cfg[key], fallback=value)

        # Highest precedence: environment variable.
        env_name = _ENV_KEYS.get(key)
        if env_name and env.get(env_name) not in (None, ""):
            value = _apply(key, env[env_name], fallback=value)

        cfg[key] = value
    return cfg


def _apply(key, raw, *, fallback):
    """Coerce *raw* for *key*; return *fallback* if coercion fails."""
    coerce = _COERCE.get(key)
    if coerce is None:
        return raw
    try:
        return coerce(raw)
    except (TypeError, ValueError):
        return fallback


def config_path():
    """Path to the optional config file: $CC_AUTOSWITCH_CONFIG or the default."""
    return os.environ.get(
        "CC_AUTOSWITCH_CONFIG",
        os.path.join(os.path.expanduser("~"), ".config", "cc-autoswitch", "config.toml"),
    )


def read_config_file(path):
    """Parse the TOML config file. Missing/unreadable/invalid -> {} (never crash)."""
    if tomllib is None:
        return {}
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh) or {}
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def load_config():
    """Resolve the effective config from defaults, the config file, and env."""
    home = os.path.expanduser("~")
    file_cfg = read_config_file(config_path())
    cswap_default = shutil.which("cswap")
    return resolve_config(os.environ, file_cfg, home=home, cswap_default=cswap_default)


def parse_cswap_version(text):
    """Extract a (major, minor, patch) tuple from `cswap --version` output."""
    m = _VERSION.search(text or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def cswap_version_ok(version, *, known_major=KNOWN_CSWAP_MAJOR, known_minor=KNOWN_CSWAP_MINOR):
    """True if *version* is within the known-good range (same major.minor)."""
    if version is None:
        return False
    return version[0] == known_major and version[1] == known_minor


# ── Effective config (module-level constants preserve the original API) ──
_CONFIG = load_config()
SWITCH_AT = _CONFIG["switch_at"]
MIN_IMPROVEMENT = _CONFIG["min_improvement"]
COOLDOWN = _CONFIG["cooldown"]
UNAVAIL_GRACE = _CONFIG["unavail_grace"]
STATE_DIR = _CONFIG["state_dir"]
CSWAP = _CONFIG["cswap"] or os.path.join(os.path.expanduser("~"), ".local/bin/cswap")
USAGE_JSON = _CONFIG["usage_json"]
LOG = os.path.join(STATE_DIR, "cc-autoswitch.log")
STAMP = os.path.join(STATE_DIR, ".cc-autoswitch.last")


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


# ── I/O glue (validated via --dry-run and the integration tests) ────
# The helpers default their paths to the module-level constants (the effective
# config resolved at import) so the original call signatures keep working, but
# accept explicit overrides so a freshly-loaded config flows through at runtime.
UNAVAIL_STATE = os.path.join(STATE_DIR, ".cc-autoswitch.unavail")


def _state_paths(state_dir):
    """Return (log, stamp, unavail) paths under *state_dir*."""
    return (
        os.path.join(state_dir, "cc-autoswitch.log"),
        os.path.join(state_dir, ".cc-autoswitch.last"),
        os.path.join(state_dir, ".cc-autoswitch.unavail"),
    )


def log(msg: str, log_path: str = LOG) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _run(args, timeout=60, cswap=None):
    return subprocess.run([cswap or CSWAP, *args], capture_output=True, text=True, timeout=timeout)


def check_cswap_version(cswap=None, on_warn=None):
    """Warn (do not fail) if cswap is missing or outside the known-good range.

    Returns the parsed (major, minor, patch) tuple, or None if undeterminable.
    *on_warn* receives a human-readable message for each problem found.
    """
    on_warn = on_warn or (lambda m: None)
    try:
        out = _run(["--version"], timeout=10, cswap=cswap)
    except (subprocess.SubprocessError, OSError) as e:
        on_warn(f"could not run cswap --version: {e!r}")
        return None
    version = parse_cswap_version((out.stdout or "") + (out.stderr or ""))
    if version is None:
        on_warn("could not parse cswap version output")
        return None
    if not cswap_version_ok(version):
        on_warn(
            f"cswap {version[0]}.{version[1]}.{version[2]} is outside the tested "
            f"range ({KNOWN_CSWAP_MAJOR}.{KNOWN_CSWAP_MINOR}.x) — proceeding anyway"
        )
    return version


def refresh_usage_live(usage_json=None, cswap=None, log_path=None) -> None:
    """Drop the 15s cache and force a fresh all-account fetch."""
    usage_json = usage_json or USAGE_JSON
    log_path = log_path or LOG
    try:
        os.remove(usage_json)
    except FileNotFoundError:
        pass
    except OSError:
        pass
    try:
        _run(["--list"], cswap=cswap)
    except (subprocess.SubprocessError, OSError) as e:
        log(f"cswap --list failed: {e!r}", log_path)


def read_accounts(usage_json=None):
    """Return {num: 5h pct or None} from usage.json, or None on failure."""
    usage_json = usage_json or USAGE_JSON
    try:
        raw = json.loads(open(usage_json, encoding="utf-8").read())
        data = raw.get("data", {})
        return {str(num): pct_of(entry) for num, entry in data.items()}
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return None


def get_active_num(cswap=None):
    try:
        return parse_active_num(_run(["--status"], cswap=cswap).stdout)
    except (subprocess.SubprocessError, OSError):
        return None


def unavail_streak_for(active, active_pct, persist=True, state_path=None):
    """Read prior state, compute the new streak via next_streak(), persist it.

    persist=False (used by --dry-run) computes the streak without writing state.
    """
    state_path = state_path or UNAVAIL_STATE
    try:
        prev = json.loads(open(state_path, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError):
        prev = {}
    streak = next_streak(prev, active, active_pct)
    if persist:
        try:
            with open(state_path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"active": active, "streak": streak}))
        except OSError:
            pass
    return streak


def within_cooldown(cooldown=None, stamp_path=None):
    cooldown = COOLDOWN if cooldown is None else cooldown
    stamp_path = stamp_path or STAMP
    try:
        last = int(open(stamp_path, encoding="utf-8").read().strip())
    except (OSError, ValueError):
        return False, 0
    elapsed = int(time.time()) - last
    return elapsed < cooldown, elapsed


def _snapshot(accounts):
    return ", ".join(
        f"{n}={'NA' if p is None else f'{p:.0f}%'}" for n, p in sorted(accounts.items())
    )


# ── Subcommands ─────────────────────────────────────────────────────
def run_decision(config, dry_run: bool = False) -> int:
    """The cron decision run (default, no-subcommand behaviour)."""
    state_dir = config["state_dir"]
    cswap = config["cswap"]
    usage_json = config["usage_json"]
    log_path, stamp_path, unavail_path = _state_paths(state_dir)

    os.makedirs(state_dir, exist_ok=True)
    check_cswap_version(cswap=cswap, on_warn=lambda m: log(f"WARNING: {m}", log_path))
    refresh_usage_live(usage_json=usage_json, cswap=cswap, log_path=log_path)
    accounts = read_accounts(usage_json=usage_json)
    if not accounts:
        log("usage data unavailable — skipping", log_path)
        return 0
    active = get_active_num(cswap=cswap)
    if not active:
        log("could not determine active account — skipping", log_path)
        return 0

    streak = unavail_streak_for(active, accounts.get(active),
                                persist=not dry_run, state_path=unavail_path)
    action, target, reason = decide(
        active, accounts,
        switch_at=config["switch_at"],
        min_improvement=config["min_improvement"],
        unavail_streak=streak,
        unavail_grace=config["unavail_grace"],
    )
    snapshot = _snapshot(accounts)

    if dry_run:
        print(f"active={active} [{snapshot}] -> {action.upper()}"
              f"{f' to {target}' if target else ''}: {reason}")
        return 0

    if action != "switch":
        return 0

    cooling, elapsed = within_cooldown(cooldown=config["cooldown"], stamp_path=stamp_path)
    if cooling:
        log(f"would switch ({reason}) but within cooldown ({elapsed}s) — skip", log_path)
        return 0

    log(f"switching: {reason} [{snapshot}]", log_path)
    try:
        out = _run(["--switch-to", target], cswap=cswap)
        flat = " ".join((out.stdout + out.stderr).split())
        log(f"cswap --switch-to {target}: {flat[:300]}", log_path)
    except (subprocess.SubprocessError, OSError) as e:
        log(f"cswap --switch-to {target} failed: {e!r}", log_path)
        return 1
    try:
        with open(stamp_path, "w", encoding="utf-8") as fh:
            fh.write(str(int(time.time())))
    except OSError:
        pass
    return 0


def cmd_status(config) -> int:
    """Read-only snapshot: active account, each account's 5h %, and the decision.

    Never switches and never writes state files.
    """
    cswap = config["cswap"]
    usage_json = config["usage_json"]
    refresh_usage_live(usage_json=usage_json, cswap=cswap, log_path=os.devnull)
    accounts = read_accounts(usage_json=usage_json)
    active = get_active_num(cswap=cswap)

    print(f"config: switch_at={config['switch_at']:.0f}% "
          f"min_improvement={config['min_improvement']:.0f}pts "
          f"cooldown={config['cooldown']}s unavail_grace={config['unavail_grace']}")
    print(f"cswap:  {cswap}")
    print(f"usage:  {usage_json}")
    if accounts is None:
        print("accounts: <usage data unavailable>")
        return 0
    print(f"active account: {active or '<unknown>'}")
    print("accounts:")
    for num in sorted(accounts):
        pct = accounts[num]
        marker = " (active)" if num == active else ""
        shown = "unavailable" if pct is None else f"{pct:.0f}%"
        print(f"  {num}: {shown}{marker}")

    if not active or active not in accounts:
        print("would do: NOOP (active account unknown or unmanaged)")
        return 0

    # Compute the streak WITHOUT persisting (read-only).
    _, _, unavail_path = _state_paths(config["state_dir"])
    streak = unavail_streak_for(active, accounts.get(active),
                                persist=False, state_path=unavail_path)
    action, target, reason = decide(
        active, accounts,
        switch_at=config["switch_at"],
        min_improvement=config["min_improvement"],
        unavail_streak=streak,
        unavail_grace=config["unavail_grace"],
    )
    print(f"would do: {action.upper()}{f' to {target}' if target else ''} — {reason}")
    return 0


def _crontab_has_entry() -> bool:
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return False
    return "cc-autoswitch" in (out.stdout or "")


def _systemd_timer_enabled() -> bool:
    try:
        out = subprocess.run(
            ["systemctl", "--user", "is-enabled", "cc-autoswitch.timer"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return (out.stdout or "").strip() == "enabled"


def cmd_doctor(config) -> int:
    """Environment checks. Prints PASS/WARN/FAIL; exits non-zero on critical FAIL."""
    critical_failed = False

    def report(level, msg):
        nonlocal critical_failed
        print(f"[{level}] {msg}")
        if level == "FAIL":
            critical_failed = True

    # cswap present + version.
    cswap = config["cswap"]
    if not (shutil.which("cswap") or (cswap and os.path.exists(cswap))):
        report("FAIL", f"cswap not found (looked for '{cswap}' and on PATH)")
    else:
        version = check_cswap_version(cswap=cswap, on_warn=lambda m: report("WARN", m))
        if version is not None and cswap_version_ok(version):
            report("PASS", f"cswap {version[0]}.{version[1]}.{version[2]} (tested range)")
        elif version is not None:
            report("PASS", f"cswap found at {cswap}")
        else:
            report("WARN", f"cswap found at {cswap} but version undeterminable")

    # >= 2 managed accounts.
    refresh_usage_live(usage_json=config["usage_json"], cswap=cswap, log_path=os.devnull)
    accounts = read_accounts(usage_json=config["usage_json"])
    if accounts is None:
        report("FAIL", f"usage.json unreachable at {config['usage_json']}")
    elif len(accounts) < 2:
        report("FAIL", f"only {len(accounts)} managed account(s); need >= 2")
    else:
        report("PASS", f"{len(accounts)} managed accounts; usage.json reachable")

    # State dir writable.
    state_dir = config["state_dir"]
    try:
        os.makedirs(state_dir, exist_ok=True)
        probe = os.path.join(state_dir, ".cc-autoswitch.doctor")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        report("PASS", f"state dir writable: {state_dir}")
    except OSError as e:
        report("FAIL", f"state dir not writable ({state_dir}): {e}")

    # Python version.
    py = sys.version_info
    if (py.major, py.minor) >= (3, 11):
        report("PASS", f"Python {py.major}.{py.minor}.{py.micro}")
    else:
        report("FAIL", f"Python {py.major}.{py.minor} too old (need >= 3.11 for tomllib)")

    # Scheduler installed (cron OR systemd --user timer).
    if _crontab_has_entry():
        report("PASS", "cron entry for cc-autoswitch installed")
    elif _systemd_timer_enabled():
        report("PASS", "systemd --user cc-autoswitch.timer enabled")
    else:
        report("WARN", "no cron entry or systemd timer found — run install.sh")

    return 1 if critical_failed else 0


CONFIG_EXAMPLE_NAME = "cc-autoswitch.toml.example"


def cmd_init() -> int:
    """Create the config file from the bundled example if absent; print next steps."""
    path = config_path()
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    example = os.path.join(repo_dir, CONFIG_EXAMPLE_NAME)

    if os.path.exists(path):
        print(f"Config already exists: {path}")
        print("Edit it directly, or delete it and re-run `cc-autoswitch init` to recreate.")
        return 0

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError as e:
        print(f"ERROR: could not create config directory: {e}", file=sys.stderr)
        return 1

    try:
        with open(example, encoding="utf-8") as src:
            contents = src.read()
    except OSError:
        # Example missing (e.g. partial checkout): write a minimal stub instead.
        contents = (
            "# cc-autoswitch config. All keys optional; env vars override these.\n"
            f"# switch_at = {DEFAULTS['switch_at']}\n"
            f"# min_improvement = {DEFAULTS['min_improvement']}\n"
            f"# cooldown = {DEFAULTS['cooldown']}\n"
            f"# unavail_grace = {DEFAULTS['unavail_grace']}\n"
        )

    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(contents)
    except OSError as e:
        print(f"ERROR: could not write config: {e}", file=sys.stderr)
        return 1

    print(f"Created config: {path}")
    print("All keys are commented out (defaults in effect). Uncomment to override.")
    print()
    print("Next steps:")
    print(f"  1. Edit {path} to taste.")
    print(f"  2. Install the per-minute scheduler:  {os.path.join(repo_dir, 'install.sh')}")
    print("  3. Verify:  cc-autoswitch doctor")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Quota-aware Claude account auto-switcher")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the decision but do not switch (no subcommand)")
    sub = ap.add_subparsers(dest="command")
    sub.add_parser("status", help="read-only snapshot of accounts and the pending decision")
    sub.add_parser("doctor", help="environment checks (PASS/WARN/FAIL); non-zero on critical FAIL")
    sub.add_parser("init", help="create the config file from the example, then print next steps")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()

    if args.command == "status":
        return cmd_status(config)
    if args.command == "doctor":
        return cmd_doctor(config)
    if args.command == "init":
        return cmd_init()

    # No subcommand: the cron decision run (backward compatible, honours --dry-run).
    return run_decision(config, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
