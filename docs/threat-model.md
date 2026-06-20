# cc-autoswitch — Threat Model

An honest accounting of what cc-autoswitch touches, what is at risk, the
realistic threats, and how to mitigate them. The goal is calibration, not alarm:
cc-autoswitch is a ~260-line Python script with no runtime dependencies that
makes **no network calls of its own** and runs entirely as the invoking user.
Most of the real risk lives in the data it sits next to — the plaintext Claude
OAuth credentials owned by the external `cswap` tool — not in cc-autoswitch
itself.

Account-policy / Terms-of-Service considerations for automated switching are a
separate concern and are covered in [`POLICY.md`](POLICY.md). This document is
limited to **security**.

---

## 1. What it touches

cc-autoswitch runs once a minute (via cron or a systemd timer) as the invoking
user. On each run it:

| Resource | Access | Notes |
|---|---|---|
| `cswap` CLI binary | **executes** | Resolved from `$CC_AUTOSWITCH_CSWAP`, else `cswap` on `$PATH`, else `~/.local/bin/cswap`. Invoked with `--list`, `--status`, `--switch-to <n>`. |
| `~/.local/share/claude-swap/cache/usage.json` | **deletes, then reads** | cswap's usage cache (override: `$CC_AUTOSWITCH_USAGE_JSON`). Deleted to force a live refresh, then re-read after `cswap --list` regenerates it. |
| `~/.claude/cc-autoswitch.log` | **appends** | Switch + cooldown-skip events. May contain account numbers and, depending on what cswap prints, **account email addresses** (see §2). |
| `~/.claude/.cc-autoswitch.last` | **reads/writes** | Cooldown timestamp. |
| `~/.claude/.cc-autoswitch.unavail` | **reads/writes** | Debounce streak state (JSON: active account + consecutive-unavailable count). |
| `~/.claude` (state dir) | **creates** | `os.makedirs(STATE_DIR, exist_ok=True)`. Override: `$CC_AUTOSWITCH_STATE_DIR`. |
| Python interpreter | **executes** | The shim runs `${CC_AUTOSWITCH_PYTHON:-/usr/bin/python3}`. |

What it touches only **indirectly**, through `cswap`:

- **`~/.claude/.credentials.json`** — the Claude Code OAuth tokens. cswap
  reads/writes this; on Linux cswap stores it **in plaintext** by design.
  cc-autoswitch never opens this file itself — but every `--switch-to` it issues
  causes cswap to rewrite it, and the credentials live in the same default state
  directory cc-autoswitch writes its own files to.
- **Anthropic's usage / auth APIs** — all network I/O is performed by `cswap`,
  not by cc-autoswitch. cc-autoswitch has **no network code**.

### Trust boundaries

- cc-autoswitch and `cswap` run with the **full privileges of the invoking
  user** — no sandbox, no privilege drop. Anything the user can read/write/run,
  this tool can.
- The security of the OAuth tokens reduces to **filesystem permissions** on the
  user's home directory plus whatever at-rest protection (e.g. full-disk
  encryption) the host provides.

---

## 2. Assets at risk

1. **Claude OAuth credentials** (`~/.claude/.credentials.json`) — the highest-value
   asset. Plaintext on Linux (cswap's storage model). Anyone who can read this
   file can impersonate the account(s) to Anthropic until the tokens are revoked
   or expire. cc-autoswitch does not create this exposure, but it operates in the
   same directory and drives the tool that maintains it.

2. **The log file** (`~/.claude/cc-autoswitch.log`) — a lower-value but real
   asset. It records switch events and the raw first ~300 chars of cswap's
   `--switch-to` stdout/stderr. Depending on cswap's output, that can include
   **account email addresses** and account numbers — i.e. it can leak *which
   accounts you manage* and *when you switch between them*, even though it does
   not contain token material.

3. **State files** (`.cc-autoswitch.last`, `.cc-autoswitch.unavail`) — low value;
   timestamps and a small JSON streak counter. No secrets, but they reveal switch
   timing/activity.

---

## 3. Threats & attack surface

### T1 — Local credential theft (other local users / processes)
On a shared or multi-user host, any other user who can read your home directory
can read the **plaintext credentials** and the log. This is the dominant risk and
it is largely inherited from cswap's plaintext storage, not introduced by
cc-autoswitch. A malicious or compromised process running **as your own user**
already has full access and is outside what file permissions can stop.

### T2 — Log-based information disclosure
The log can contain account emails/numbers and switch timing (§2.2). Risk arises
if the log is world-readable, copied off the box, or **pasted into a bug report
or shared transcript** without redaction.

### T3 — `cswap` binary / PATH tampering
cc-autoswitch resolves `cswap` from `$CC_AUTOSWITCH_CSWAP`, then `$PATH`, then
`~/.local/bin/cswap`, and **executes it every minute as you**. If an attacker can
write to any directory that appears earlier on your `$PATH` than the real cswap,
to `~/.local/bin/cswap`, or can set `$CC_AUTOSWITCH_CSWAP` in the cron/systemd
environment, they get **arbitrary command execution as your user, once a
minute**. The same applies to `$CC_AUTOSWITCH_PYTHON` (the shim execs it
directly) and to write access to the repo files themselves
(`cc_autoswitch.py`, `cc-autoswitch.sh`). Note that command arguments are passed
as a list (no shell), so there is no shell-injection surface in how cc-autoswitch
invokes cswap — the risk is *which binary* gets resolved, not argument quoting.

### T4 — World-readable / over-permissive files
If `.credentials.json`, the log, or the state dir are group/world-readable, the
exposure in T1/T2 widens from "your user" to "anyone on the box." cc-autoswitch
does **not** set restrictive permissions on the files it creates — they inherit
the process umask — so this depends on host configuration.

### T5 — Supply chain
cc-autoswitch itself has **no third-party runtime dependencies** (standard
library only), which keeps its own supply-chain surface minimal. The meaningful
supply-chain dependency is **external**: `cswap` (claude-swap) is installed from
PyPI and handles your credentials and all network traffic. A compromised cswap
release would compromise the tokens regardless of cc-autoswitch.

### T6 — Tampered usage cache (decision manipulation)
cc-autoswitch deletes and re-reads `usage.json`, then **trusts its contents** to
decide which account to switch to. An attacker who can write that file (already a
local-user-level capability) could steer switches — e.g. force rotation onto a
specific account or suppress switching. Impact is limited to *which managed
account is active*; it does not by itself disclose tokens. Worth noting as a
trust assumption rather than a high-severity flaw.

### Non-threats (what is *not* a meaningful surface here)
- **Shell injection** in cswap invocation — arguments are passed as an argv list,
  not through a shell.
- **Remote attackers** — cc-autoswitch opens no sockets and exposes no service.
- **Privilege escalation by the tool** — it never elevates; it runs as you.

---

## 4. Mitigations & recommendations

For the user / operator:

1. **Lock down the credential and state files (single most important step).**
   Ensure `~/.claude/.credentials.json` is `0600` and `~/.claude` is `0700`
   (`chmod 700 ~/.claude && chmod 600 ~/.claude/.credentials.json`). Apply the
   same `0600` to `cc-autoswitch.log` and the `.cc-autoswitch.*` state files.
   Re-check after cswap updates rewrite the credential file.
2. **Use full-disk / home-directory encryption.** Because the tokens are
   plaintext at rest, encryption-at-rest is the backstop if the disk is lost,
   imaged, or backed up insecurely.
3. **Avoid shared / multi-user hosts** for accounts you care about. File
   permissions reduce, but do not eliminate, exposure to other local users; the
   safest posture is a single-user machine.
4. **Trust and pin the `cswap` install.** Install cswap from a trusted source,
   keep it updated, and prefer setting `$CC_AUTOSWITCH_CSWAP` to an **absolute
   path** to a known-good binary rather than relying on `$PATH` resolution. Keep
   `~/.local/bin` and every earlier `$PATH` entry writable only by you (T3).
5. **Protect the repo / scripts.** Keep `cc_autoswitch.py`, `cc-autoswitch.sh`,
   and `install.sh` writable only by your user — they execute every minute.
6. **Scrub before sharing.** Redact account emails, account numbers, and any
   token material from `cc-autoswitch.log` before pasting it into issues,
   transcripts, or screenshots (T2). The log is the realistic accidental-leak
   vector.
7. **Harden the systemd unit if you use it.** The shipped
   `cc-autoswitch.service` is a bare `Type=oneshot` with no sandboxing. Because
   it legitimately needs to read/write `~/.claude`, full `ProtectHome` is not an
   option, but you can still add defense-in-depth — e.g. `NoNewPrivileges=true`,
   `PrivateTmp=true`, `ProtectSystem=strict`, and a tight `ReadWritePaths=` /
   `BindReadOnlyPaths=` — to limit blast radius if cswap is compromised.
8. **Audit the log periodically** for unexpected switches, which could indicate a
   tampered `usage.json` (T6) or a misbehaving cswap.

What cc-autoswitch already does well, security-wise:

- No network code of its own; no third-party runtime dependencies.
- Invokes cswap via an argv list (no shell), so no shell-injection surface.
- Never reads or writes the credential file directly; never elevates privileges.
- Bounds and flattens captured subprocess output before logging (first ~300
  chars), limiting accidental log bloat.

---

## 5. Explicitly out of scope

- **Data transmission by this tool.** cc-autoswitch transmits **nothing** off the
  host. All Anthropic network I/O is performed by `cswap`. If you are evaluating
  where account/usage data goes over the wire, that is a cswap question.
- **Plaintext credential storage as a "bug."** It is cswap's storage model on
  Linux, documented here so you can mitigate it (encryption, permissions) — it is
  not something cc-autoswitch can or does change.
- **Account-policy / Terms-of-Service risk** of automated account switching. That
  is a policy concern, not a security one — see [`POLICY.md`](POLICY.md).
- **Vulnerabilities inside `cswap` itself.** Report those to the
  [claude-swap](https://pypi.org/project/claude-swap/) project.
