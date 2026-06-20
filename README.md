# cc-autoswitch

Quota-aware automatic account switching for [Claude Code](https://claude.com/claude-code),
built on top of [`cswap` (claude-swap)](https://pypi.org/project/claude-swap/).

When the active Claude account is about to exhaust its 5-hour usage window,
`cc-autoswitch` rotates to the managed account with the **most headroom** — so
long-running agents keep going instead of stalling on a rate limit.

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

A cron job runs once a minute. Each run:

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

Requires Python 3 and `cswap` with **2+ managed accounts**.

```bash
git clone <this-repo> ~/code/cc-autoswitch
cd ~/code/cc-autoswitch
./install.sh        # adds the per-minute cron entry (idempotent)
```

Check what it would do right now, without switching:

```bash
./cc-autoswitch.sh --dry-run
# active=1 [1=12%, 2=64%] -> NOOP: active acct 1 at 12% < 97%
```

## Configuration

Tunables live at the top of [`cc_autoswitch.py`](cc_autoswitch.py):

| Constant | Default | Meaning |
|---|---|---|
| `SWITCH_AT` | `97.0` | Leave the active account at/above this 5h % |
| `MIN_IMPROVEMENT` | `10.0` | Only switch if the target is this many points better |
| `COOLDOWN` | `300` | Minimum seconds between switches |
| `UNAVAIL_GRACE` | `3` | Consecutive "unavailable" runs (~minutes) before treating the active account as maxed |

Paths are environment-overridable (defaults preserve the original behaviour —
state under `~/.claude`, `cswap` resolved from `PATH`):

| Env var | Default |
|---|---|
| `CC_AUTOSWITCH_STATE_DIR` | `~/.claude` (log + cooldown/debounce state) |
| `CC_AUTOSWITCH_CSWAP` | `cswap` on `PATH`, else `~/.local/bin/cswap` |
| `CC_AUTOSWITCH_USAGE_JSON` | `~/.local/share/claude-swap/cache/usage.json` |
| `CC_AUTOSWITCH_PYTHON` | `/usr/bin/python3` (used by the shim) |

Runtime artifacts written to the state dir: `cc-autoswitch.log` (only logs
actual switches and cooldown skips — no NOOP spam), `.cc-autoswitch.last`
(cooldown stamp), `.cc-autoswitch.unavail` (debounce streak).

## Testing

Pure decision logic is covered by unit tests (no `cswap` calls, no real
switching):

```bash
make test         # or: python3 -m unittest test_cc_autoswitch -v
```

## Caveats

- **Switching can't rescue already-running sessions.** `cswap` itself notes
  *"Please restart Claude Code to use the new authentication."* In-flight
  sessions keep their old token until restarted; new/restarted sessions pick up
  the switched account.
- Needs at least **two managed accounts**; with one (or with all accounts
  maxed) it correctly does nothing.

## License

MIT © Eden Gibson
