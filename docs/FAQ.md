# FAQ

### What does cc-autoswitch actually do?

It runs once a minute (via cron or a systemd user timer) and, when your active
Claude account is about to exhaust its 5-hour usage window, switches (via
`cswap`) to the managed account with the **most headroom** — so long-running
Claude Code sessions keep working instead of stalling on a rate limit.

### Why not just use `cswap --switch`?

`cswap --switch` rotates **blindly** to the next account in sequence. It can
land you on an account that is *also* maxed (no benefit, and it ping-pongs), and
when the active account is exhausted the usage API often returns nothing — so a
naive script reads an empty value and does nothing. cc-autoswitch fetches live
all-account usage and only switches to an account that genuinely has headroom.
See the README's "Why not just `cswap --switch`?" section.

### Does switching interrupt my running Claude Code sessions?

**No — it's seamless and needs no restart.** `cswap` overwrites the live
`~/.claude/.credentials.json` that Claude Code reads, so in-flight sessions pick
up the new account on their next request. `cswap` prints a conservative "Please
restart Claude Code" message, but in practice a restart is not required.

### How do I change the switch threshold or other settings?

Settings resolve with precedence **environment variable › config file ›
default**. Run `cc-autoswitch init` to create `~/.config/cc-autoswitch/config.toml`,
then edit it — or set an env var like `CC_AUTOSWITCH_SWITCH_AT=95`. See the
README "Configuration" table for every key.

### Cron or systemd — which should I use?

Either. `./install.sh` installs a cron job (default); `./install.sh --systemd`
installs a systemd `--user` timer instead. The two are mutually exclusive —
installing one removes the other, so it never runs twice a minute.
`./install.sh --uninstall` removes whichever is active.

### How do I check it's set up correctly?

Run `cc-autoswitch doctor` — it reports PASS/WARN/FAIL for cswap + version,
having 2+ managed accounts, usage.json reachability, a writable state dir, the
Python version, and whether a cron entry or systemd timer is installed. Use
`cc-autoswitch status` for a read-only snapshot of current usage and the
decision it would make, and `cc-autoswitch --dry-run` to preview a run without
switching.

### It says "no headroom" / "usage unavailable" and isn't switching. Why?

- **"no alternative account has headroom"** — every other account is also at/above
  the threshold (or unavailable). There is nowhere better to switch; staying put
  is correct.
- **"usage unavailable (streak N/3)"** — the active account's usage briefly read
  as null (common right at the 5-hour reset boundary and from a flaky endpoint).
  cc-autoswitch debounces this for `unavail_grace` consecutive runs before
  treating the account as maxed, so it won't flee a healthy, freshly-reset
  account.
- **Within cooldown** — a switch happened recently; it waits `cooldown` seconds
  (default 300) between switches to avoid thrashing.

### Do I need more than one account?

Yes — at least **two** managed `cswap` accounts. With one account (or when all
accounts are maxed) cc-autoswitch correctly does nothing.

### Does it handle the weekly usage limit?

No. It only addresses the rolling **5-hour** window. Weekly caps are not managed.

### Is this allowed by Anthropic's terms?

Read **[POLICY.md](POLICY.md)** before using. Auto-rotating accounts to extend
usage may constitute "limit evasion" under Anthropic's Consumer Terms and carries
account-suspension risk. Use at your own risk.

### Where are logs and state kept?

Under the state dir (default `~/.claude`): `cc-autoswitch.log` (logs only actual
switches and cooldown skips — no NOOP spam), `.cc-autoswitch.last` (cooldown
stamp), and `.cc-autoswitch.unavail` (debounce streak). Override with
`CC_AUTOSWITCH_STATE_DIR`.
