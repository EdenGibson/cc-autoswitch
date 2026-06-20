# cc-autoswitch

[![CI](https://github.com/EdenGibson/cc-autoswitch/actions/workflows/ci.yml/badge.svg)](https://github.com/EdenGibson/cc-autoswitch/actions/workflows/ci.yml)

Quota-aware automatic account switching for [Claude Code](https://claude.com/claude-code),
built on top of [`cswap` (claude-swap)](https://pypi.org/project/claude-swap/).

When the active Claude account is about to exhaust its 5-hour usage window,
`cc-autoswitch` rotates to the managed account with the **most headroom** — so
long-running agents keep going instead of stalling on a rate limit.

> ⚠️ **Account-policy risk.** Auto-rotating accounts to extend usage may run
> afoul of Anthropic's terms (limit evasion). Read
> **[docs/POLICY.md](docs/POLICY.md)** before using this. Use at your own risk.

## Why not just `cswap --switch`?

`cswap --switch` rotates **blindly** to the next account in sequence. That
causes two real failure modes:

- **Rotating into an exhausted account.** If account A hits its limit and the
  next account B is *also* maxed, a blind rotation lands you on B — no better
  off, and it can ping-pong.
- **Going blind exactly when it matters.** When the active account is maxed,
  Anthropic's usage API tends to return *nothing*, so a naive script that reads
  the active account's percentage gets an empty value and silently does nothing.

`cc-autoswitch` fixes both by making the **decision** smart.

## How it works

A scheduler (cron or a systemd user timer) runs it once a minute. Each run:

1. **Forces a live, all-account usage refresh** — drops `cswap`'s 15-second
   usage cache and runs `cswap --list`, so the decision never rides a stale or
   partial cached number.
2. Reads every managed account's 5-hour utilisation from `cswap`'s
   `usage.json`.
3. **Decides** (`decide()` — pure, fully unit-tested):
   - Stay put if the active account is below the switch threshold (default 97%).
   - Otherwise switch to the account with the **most headroom** — never one that
     is itself ≥ the threshold, and only if it's meaningfully better
     (anti-thrash margin).
   - Treat a **persistently** unavailable active account as a switch trigger
     (the maxed-active blind spot), but **debounce** transient `null` readings
     (seen at the 5-hour reset boundary and from the flaky active-usage
     endpoint) so it never flees a healthy, freshly-reset account.
4. Switches with `cswap --switch-to <num>` (targeted, not blind), honouring a
   cooldown to avoid thrashing.

## Install

Linux only. Requires Python 3.11+ and [`cswap`](https://pypi.org/project/claude-swap/)
with **2+ managed accounts**.

```bash
git clone https://github.com/EdenGibson/cc-autoswitch ~/code/cc-autoswitch
cd ~/code/cc-autoswitch

./install.sh              # per-minute cron job (default)
# or:
./install.sh --systemd   # per-minute systemd --user timer instead
./install.sh --uninstall # remove whichever backend is installed
```

Optionally put the CLI on your `PATH`:

```bash
pipx install .           # or: pip install --user .
```

## Usage

```bash
cc-autoswitch            # make a switch decision (what the scheduler runs)
cc-autoswitch --dry-run  # print the decision; switch nothing, write no state
cc-autoswitch status     # read-only snapshot: config, per-account 5h%, decision
cc-autoswitch doctor     # environment health check (PASS/WARN/FAIL, non-zero on fail)
cc-autoswitch init       # create ~/.config/cc-autoswitch/config.toml
```

From a clone without installing, use `./cc-autoswitch.sh <args>` or
`python3 cc_autoswitch.py <args>`.

## Configuration

Settings resolve with precedence **environment variable › config file › built-in
default**. The config file is TOML at `$CC_AUTOSWITCH_CONFIG` (default
`~/.config/cc-autoswitch/config.toml`); run `cc-autoswitch init` to create it
from [`cc-autoswitch.toml.example`](cc-autoswitch.toml.example).

| Config key | Env var | Default | Meaning |
|---|---|---|---|
| `switch_at` | `CC_AUTOSWITCH_SWITCH_AT` | `97` | Leave the active account at/above this 5h % |
| `min_improvement` | `CC_AUTOSWITCH_MIN_IMPROVEMENT` | `10` | Only switch if the target is this many points better |
| `cooldown` | `CC_AUTOSWITCH_COOLDOWN` | `300` | Minimum seconds between switches |
| `unavail_grace` | `CC_AUTOSWITCH_UNAVAIL_GRACE` | `3` | Consecutive "unavailable" runs (~min) before treating active as maxed |
| `state_dir` | `CC_AUTOSWITCH_STATE_DIR` | `~/.claude` | Log + cooldown/debounce state |
| `cswap` | `CC_AUTOSWITCH_CSWAP` | `cswap` on `PATH` | Path to the `cswap` binary |
| `usage_json` | `CC_AUTOSWITCH_USAGE_JSON` | `~/.local/share/claude-swap/cache/usage.json` | `cswap` usage cache |
| `python` | `CC_AUTOSWITCH_PYTHON` | `/usr/bin/python3` | Interpreter used by the cron/systemd shim |

Runtime artifacts written to the state dir: `cc-autoswitch.log` (only logs actual
switches and cooldown skips — no NOOP spam), `.cc-autoswitch.last` (cooldown
stamp), `.cc-autoswitch.unavail` (debounce streak).

## Does switching affect running Claude Code sessions?

**Yes — seamlessly, with no restart.** `cswap` overwrites the live
`~/.claude/.credentials.json` that Claude Code reads, so in-flight sessions pick
up the new account on their next request. (`cswap` prints a conservative
"Please restart Claude Code" message, but a restart isn't required in practice.)

## Testing

```bash
make test         # python3 -m unittest discover -p 'test_*.py'   (67 tests)
make dry-run      # show the current decision
```

CI (GitHub Actions) runs the suite on Python 3.11–3.13 plus `ruff` and `mypy`.

## Caveats & limits

- Needs **2+ managed accounts**; with one — or when *all* accounts are maxed —
  it correctly does nothing.
- Only the **5-hour** window is addressed; weekly caps are not.
- See **[docs/POLICY.md](docs/POLICY.md)** for the Terms-of-Service / account
  suspension risk.

## Documentation

- [docs/POLICY.md](docs/POLICY.md) — Terms-of-Service / account-risk (**read first**)
- [docs/FAQ.md](docs/FAQ.md) — common questions & troubleshooting
- [docs/threat-model.md](docs/threat-model.md) — security threat model
- [SECURITY.md](SECURITY.md) — vulnerability reporting
- [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup & contribution guide

## License

MIT © Eden Gibson
