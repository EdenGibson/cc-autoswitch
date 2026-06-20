# Security Policy

## Supported versions

cc-autoswitch is a small single-file tool distributed from this repository. There
are no release branches: **only the latest commit on the default branch is
supported.** Fixes are applied there; please update before reporting an issue you
hit on an older checkout.

| Version            | Supported |
|--------------------|-----------|
| Latest `main`      | ✅        |
| Any older commit   | ❌        |

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue, and do
not include sensitive details (paths, logs, tokens) in any public discussion.

Preferred channel:

- **GitHub Security Advisories** — open a private report via the repository's
  **Security → Report a vulnerability** ("Advisories") page. This keeps the
  report confidential until a fix is available.

If you cannot use GitHub advisories, contact the maintainer directly:

- **Maintainer:** Eden Gibson
- **Email:** `matthewjmartin06@gmail.com`

When reporting, please include:

- A description of the issue and its impact.
- Steps to reproduce (a `--dry-run` transcript is ideal — but **redact account
  numbers, emails, and any token material** first).
- The commit SHA you are running and your OS / Python version.

### Response timeline

This is a personal, best-effort project maintained by a single person. Expected
turnaround:

- **Acknowledgement:** within ~7 days.
- **Assessment & fix plan:** within ~30 days, depending on severity and
  complexity.
- **Disclosure:** coordinated with the reporter once a fix is available (or a
  mitigation is documented). Credit is offered unless you prefer to remain
  anonymous.

These are targets, not guarantees.

## Scope

**In scope** — defects in this repository that affect the security of the host or
the user's credentials, for example:

- Bugs in `cc_autoswitch.py`, `cc-autoswitch.sh`, `install.sh`, or the systemd
  unit files that could lead to arbitrary command execution, privilege
  escalation, or unsafe file handling.
- Unsafe permissions or unsafe path resolution introduced by this tool's own
  install/runtime behaviour.
- Exposure of sensitive data (e.g. account emails) through this tool's log or
  state files **beyond** what is already documented as expected behaviour.

**Out of scope:**

- **`cswap` / claude-swap.** cc-autoswitch shells out to the external
  [`cswap`](https://pypi.org/project/claude-swap/) CLI. cswap owns the OAuth
  credential store (`~/.claude/.credentials.json`, **plaintext on Linux by
  cswap's design**) and performs all Anthropic network calls. Vulnerabilities in
  cswap belong to that project. See [`docs/threat-model.md`](docs/threat-model.md).
- **Plaintext credential storage on Linux.** This is cswap's storage model, not
  something cc-autoswitch can change; it is documented, not a vulnerability in
  this tool.
- **Account-policy / Terms-of-Service questions** about automated account
  switching. These are not security issues; see `docs/POLICY.md`.
- General hardening of the host OS, cron/systemd, or the user's home directory
  permissions, beyond the recommendations in
  [`docs/threat-model.md`](docs/threat-model.md).

For a full picture of what this tool touches and the recommended mitigations,
read [`docs/threat-model.md`](docs/threat-model.md).
