# Contributing to cc-autoswitch

Thanks for your interest in improving **cc-autoswitch** — the quota-aware
account switcher for [Claude Code](https://claude.com/claude-code) built on top
of [`cswap` (claude-swap)](https://pypi.org/project/claude-swap/).

This is a small, deliberately simple project: a single flat Python module
(`cc_autoswitch.py`) with a matching test file (`test_cc_autoswitch.py`), no
runtime dependencies, and a shell shim for cron/systemd. Keep contributions in
that spirit — small, well-tested, stdlib-only.

## Scope: Linux only

cc-autoswitch targets **Linux** and only Linux. The whole design leans on a
Linux fact: Claude Code stores its credentials in a plain file
(`~/.claude/.credentials.json`) and re-reads it whenever it changes, so an
in-place swap takes effect on the next message. macOS keeps credentials in the
Keychain and behaves differently; Windows is out of scope.

Please don't add macOS/Windows branches, Keychain handling, or cross-platform
shims. If you need that, `cswap` itself is the right layer for it. Bug reports
and features that only make sense off Linux will be closed as out of scope.

## Prerequisites

- **Python 3.11+** (the code uses `from __future__ import annotations` and
  targets 3.11/3.12/3.13).
- A Linux environment (a container or VM is fine).
- For end-to-end manual testing only: [`cswap`](https://pypi.org/project/claude-swap/)
  installed with **2 or more managed accounts**. You do **not** need `cswap` to
  run the unit tests — the decision logic is pure and fully mocked.

## Dev setup

```bash
git clone https://github.com/EdenGibson/cc-autoswitch ~/code/cc-autoswitch
cd ~/code/cc-autoswitch

# Optional: a venv just for tooling (ruff/mypy). The code itself is stdlib-only.
python3 -m venv .venv && . .venv/bin/activate
pip install ruff mypy        # only needed if you want to run lint / type checks locally
```

There is nothing to "build" — it's a single script.

## Running the tests

Tests run via the stdlib `unittest` runner. No network, no `cswap`, no real
account switching.

```bash
make test
# equivalent to:
python3 -m unittest test_cc_autoswitch -v
```

All tests must pass before you open a PR.

## Test-driven development (required)

**Write the test first.** This project practices TDD, and it's enforced by
convention in review:

1. Write the failing test that captures the intended behaviour (for a bugfix,
   the test must first **reproduce the symptom**).
2. Run `make test` and watch it fail for the right reason.
3. Implement the smallest change that makes it pass.
4. Run `make test` again and confirm green.

The interesting logic — `decide()`, `pct_of()`, `parse_active_num()`,
`next_streak()` and friends — is intentionally pure so it can be unit-tested
without touching the filesystem or shelling out. Keep new logic that way:
factor pure decisions out of the I/O glue, and test the pure part. The thin I/O
layer (`main()`, the `cswap` subprocess calls) is exercised manually via
`--dry-run` rather than mocked to death.

## Trying changes safely

The single safest way to see what the tool *would* do without switching
anything is `--dry-run`:

```bash
python3 cc_autoswitch.py --dry-run
# active=1 [1=12%, 2=64%] -> NOOP: active acct 1 at 12% < 97%
```

`--dry-run` reads live usage and prints the decision, but never calls
`cswap --switch-to`, never writes the cooldown stamp, and never advances the
unavailable-debounce streak. Use it freely against a real `cswap` install — it
cannot rotate your account.

If you don't have `cswap` configured, you can still develop and test the
decision logic entirely through the unit tests.

## Code style

- **Linter/formatter: [ruff](https://docs.astral.sh/ruff/).** Config lives in
  `ruff.toml`. Run both before committing:

  ```bash
  ruff check .
  ruff format --check .
  ```

  The config is deliberately lenient (it's a stdlib CLI), but keep it clean —
  no new lint errors.

- **Type checking: mypy** (config in `mypy.ini`), if you have it installed:

  ```bash
  mypy cc_autoswitch.py
  ```

- **stdlib only.** Do not add runtime dependencies. `cc-autoswitch` shells out
  to `cswap`; it does not import it. If you think you need a third-party
  package, open an issue first — the answer is almost certainly no.

- **Match the surrounding code.** Mirror the existing naming, comment density,
  and the "pure logic vs. I/O glue" split. Read the neighbouring function
  before adding one.

## Pull request process

1. Fork and branch from `main` (e.g. `fix/unavail-streak-reset`).
2. Follow TDD: test first, then implementation.
3. Run `make test` (green), `ruff check .`, and `ruff format --check .`.
4. Update the docs if behaviour, constants, env vars, or install steps change —
   `README.md`, `docs/FAQ.md`, and any config table that drifted.
5. Open the PR using the template and fill in the checklist. Describe the
   behaviour change and the failure mode it addresses.
6. CI runs the test suite and lint on Linux; keep it green.

Small, focused PRs get reviewed fastest. If a change is large or speculative,
open an issue or a Discussion first so we can agree on the approach.

## Commit style

- One logical change per commit; keep the history readable.
- Imperative mood subject line, ~72 chars, e.g.
  `fix: don't flee a freshly-reset active account on transient null`.
- Reference the issue it closes in the body (`Closes #12`) when applicable.
- Explain *why* in the body when the *what* isn't self-evident.

## Reporting bugs and requesting features

Use the issue templates (Bug report / Feature request). For the
"does this affect running sessions / ToS / account-risk" kind of question,
read [`docs/FAQ.md`](docs/FAQ.md) and [`docs/POLICY.md`](docs/POLICY.md) first.

## Code of conduct

Participation in this project is governed by our
[Code of Conduct](CODE_OF_CONDUCT.md).
