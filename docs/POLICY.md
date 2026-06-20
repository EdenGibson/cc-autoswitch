# cc-autoswitch — Terms of Service & Acceptable-Use Policy

> **Read this before you use `cc-autoswitch`.** This document exists to be
> *candid about risk*, not to sell you on the tool. `cc-autoswitch`
> automatically rotates between multiple Claude accounts (via
> [`cswap`](https://pypi.org/project/claude-swap/)) so that long-running
> Claude Code sessions keep working past a single account's 5-hour usage
> window. That behaviour sits close to a line Anthropic actively enforces, and
> using it carries real account-suspension risk. The sections below explain
> what we know, what we're inferring, and what you should verify yourself.

---

## 0. The one-paragraph version

Owning more than one Claude account is **not** itself a Terms violation.
Automatically rotating between those accounts *specifically to keep working
after one account hits its cap* is **limit-evasion-flavoured**, and the usage
pattern it produces — many sessions across rotating accounts — is exactly the
kind of signal Anthropic's **partly automated** enforcement is built to catch.
`cc-autoswitch` feeds credentials back into the **official** Claude Code client
(not a third-party harness), which most likely keeps it clear of the separate,
higher-risk "token arbitrage" prohibition — but that does not make it safe.
**Use at your own risk.** See §6.

---

## 1. Scope & authoritative source

This is a community policy/disclaimer for an unofficial tool. It is **not** legal
advice and **not** an Anthropic document.

**The authoritative, controlling truth is Anthropic's *current* official
policies**, which change over time:

- Anthropic [Consumer Terms of Service](https://www.anthropic.com/legal/consumer-terms)
- Anthropic [Usage Policy / Acceptable Use Policy](https://www.anthropic.com/aup)

Read those **before** using this tool. Where this document and Anthropic's
current Terms disagree, **Anthropic's Terms win**. Some sources cited here are
**secondary** (third-party blogs, user bug reports) and are flagged as such —
treat them as leads to verify, not as ground truth.

---

## 2. What is and isn't a violation

### Not a violation on its own

- **Holding multiple Claude accounts.** Merely having more than one account —
  for example a personal account and a work account — is not, by itself, a
  breach of Anthropic's Terms. A secondary analysis puts it plainly: *"holding
  more than one Claude Max account is not a violation of Anthropic's Terms of
  Service."* ([grandlinux, secondary](https://www.grandlinux.com/en/blogs/claude-account-ban-risk.html))
  The risk is in *how* the accounts are used, not how many you have.

### Documented suspension / ban triggers

Anthropic's policies and reporting around them point to several behaviours that
are cited as grounds for suspension:

1. **Limit evasion.** Hitting the cap on one account and switching to another to
   keep going — repeatedly, as a way around the limit — is described as a
   medium-to-high-risk behaviour that *"potentially trigger[s] detection
   systems."* ([grandlinux, secondary](https://www.grandlinux.com/en/blogs/claude-account-ban-risk.html))
   This is the category `cc-autoswitch`'s core behaviour most resembles.

2. **Account sharing / reselling.** Sharing one account among many people, or
   reselling access/quota, is flagged as a very-high-risk behaviour.
   ([grandlinux, secondary](https://www.grandlinux.com/en/blogs/claude-account-ban-risk.html))
   Anthropic's own framing of why these limits exist cites *"power users…
   sharing credentials across teams."*
   ([truefoundry, secondary](https://www.truefoundry.com/blog/claude-code-limits-explained))

3. **Token arbitrage — routing subscription OAuth tokens into third-party
   tools.** Taking the OAuth tokens issued to a Free / Pro / Max **subscription**
   and using them in *another* product, tool, harness, or the Agent SDK — to get
   API-equivalent work at subscription prices — is described as the single most
   significant ban trigger. ([grandlinux, secondary](https://www.grandlinux.com/en/blogs/claude-account-ban-risk.html))
   The key distinction the same source draws: using the **official** Claude
   products (Claude.ai, Claude Desktop, Claude Code) remains compliant; the
   violation is routing those subscription credentials through **unauthorized
   third-party tools**.

### Enforcement is partly automated

Enforcement is not purely manual review. Signals such as **concurrent sessions**
and **unusual usage patterns** feed automated systems, and visibility into how
those systems work is deliberately limited — developers get *"only… basic
countdown timers for usage visibility."*
([truefoundry, secondary](https://www.truefoundry.com/blog/claude-code-limits-explained))
Reporting indicates large-scale suspension activity (on the order of ~1.45M
accounts suspended July–December 2025, mostly for spam/prohibited content rather
than paying subscribers). ([grandlinux, secondary](https://www.grandlinux.com/en/blogs/claude-account-ban-risk.html))

---

## 3. Where cc-autoswitch actually sits

This is the part that matters, stated honestly.

- **It uses the official client.** `cc-autoswitch` does not pipe your tokens into
  a third-party harness or the Agent SDK. It rotates which managed account
  `cswap` makes active, and the **official Claude Code client** then authenticates
  with that account. That design most likely keeps it **clear of the
  "token arbitrage" prohibition** in §2.3 — which is the highest-risk category.
  *(This is our inference about how the prohibition applies, not an Anthropic
  ruling. We could be wrong.)*

- **But its purpose is limit-adjacent.** The tool's reason for existing is to
  keep an agent working **past a single account's 5-hour cap** by moving to an
  account with headroom. Whatever the mechanism, *automatically rotating
  accounts to extend past the cap* is **limit-evasion-flavoured** (§2.1), and it
  carries **real account-suspension risk**.

- **The usage pattern it generates is the detection target.** Many sessions,
  switching across rotating accounts, is precisely the *"concurrent sessions /
  unusual usage patterns"* signal that §2's automated enforcement is built to
  flag. In other words: even though the mechanism is benign-looking, the
  *fingerprint* it leaves is the risky one.

- **Rotation may not even work the way you hope.** There are credible **user
  reports** that Anthropic rate-limits **across multiple accounts used
  together** — i.e. usage on one account can be reflected against another.
  ([claude-code issue #54464, user reports — secondary](https://github.com/anthropics/claude-code/issues/54464))
  In that report, two accounts showed *"identical weekly percentages… despite Pro
  and Max having different absolute limits,"* and the issue was closed
  **"not planned."** If cross-account accounting like this applies to the 5-hour
  window in your situation, rotation could be **detected and/or simply
  ineffective** — you may burn both accounts instead of extending your runway.
  *(This is a single user report about weekly usage and is not confirmed
  Anthropic behaviour; verify against your own accounts before relying on
  rotation.)*

**Bottom line:** the mechanism is probably not "token arbitrage," but the
*intent and the resulting usage pattern* are the risky parts, and the payoff is
uncertain. Going in with eyes open is the whole point of this document.

---

## 4. Legitimate, lower-risk framings

If you want to use account-switching tooling while staying as far as possible
from the lines above, these framings are more defensible:

- **Separating distinct accounts you legitimately hold.** Switching between a
  **work**, **personal**, and **client** account that you genuinely own and use
  for their own purposes — i.e. using `cswap`/`cc-autoswitch` as a *convenience
  for managing real, separate accounts* — rather than as a mechanism to evade a
  single account's cap.

- **Orchestrating Anthropic API keys / workspaces where usage is metered and
  billed.** If your work is on the **API** (pay-as-you-go keys, workspaces) where
  you are actually paying for what you consume, you aren't evading a
  subscription cap at all — you're scaling metered usage you're billed for. That
  is a fundamentally different posture from rotating **subscription** accounts to
  dodge the 5-hour window.

These framings reduce — but do not eliminate — risk. Automated detection keys on
*patterns*, not stated intent, so a benign reason won't necessarily prevent a
flag.

---

## 5. The 5-hour window & weekly caps (for context)

`cc-autoswitch` reacts to the **5-hour rolling usage window**: a counter that
starts at your first prompt and resets five hours later. There is also a
**weekly cap** on active compute hours, and *"once either boundary is reached,
all new prompts are blocked, even if the other counter remains under its
limit."* ([truefoundry, secondary](https://www.truefoundry.com/blog/claude-code-limits-explained))
Anthropic's own support material notes Max plans have *"two weekly usage
limits"* and that *"weekly limits reset at a fixed time each week that is
assigned to your account,"* and that Anthropic *"may limit your usage in other
ways… at our discretion."*
([Anthropic support — Max plan](https://support.claude.com/en/articles/11049741-what-is-the-max-plan))
Switching accounts addresses the **5-hour** window only; it does nothing about
weekly caps, and (per §3) cross-account accounting may blunt even the 5-hour
benefit.

---

## 6. Disclaimer — USE AT YOUR OWN RISK

- **You assume all risk.** Using `cc-autoswitch` may result in **rate limiting,
  account suspension, or account termination** of one or more of your Claude
  accounts. You use it entirely at your own risk.

- **The maintainers are not responsible** for any action Anthropic takes against
  your account(s) — including suspension, termination, loss of access, or loss of
  paid subscription value — arising from your use of this tool.

- **Read Anthropic's current policies first.** Before using `cc-autoswitch`, read
  and comply with the current
  [Consumer Terms of Service](https://www.anthropic.com/legal/consumer-terms)
  and [Usage Policy](https://www.anthropic.com/aup). They are the controlling
  authority and they change.

- **No warranty.** This tool is provided "as is" under its
  [MIT license](../LICENSE), without warranty of any kind. Nothing here is legal
  advice.

- **Verify the claims in this doc.** Several statements above rely on **secondary
  sources** (third-party blogs and a user-filed GitHub issue), explicitly tagged
  *(secondary)* / *(user reports)*. Confirm anything load-bearing against
  Anthropic's official Terms before depending on it.

---

## 7. Sources

| Source | Type | Used for |
|---|---|---|
| [Anthropic — Consumer Terms of Service updates](https://privacy.claude.com/en/articles/9264813-consumer-terms-of-service-updates) | Anthropic (official-ish; points to the full Terms) | Pointer to controlling Consumer Terms |
| [Anthropic — What is the Max plan?](https://support.claude.com/en/articles/11049741-what-is-the-max-plan) | Anthropic support (official) | Usage limits, weekly caps, reset timing, "at our discretion" |
| [truefoundry — Claude Code limits explained](https://www.truefoundry.com/blog/claude-code-limits-explained) | Secondary (blog) | 5-hour window, dual caps, concurrent-session signals, limited visibility |
| [grandlinux — Claude account ban risk](https://www.grandlinux.com/en/blogs/claude-account-ban-risk.html) | Secondary (blog) | Multiple accounts not a violation; limit-evasion / sharing / token-arbitrage triggers; official-client distinction |
| [claude-code issue #54464](https://github.com/anthropics/claude-code/issues/54464) | Secondary (user reports) | Reports of rate-limiting across multiple accounts used together |

*Authoritative, controlling sources are Anthropic's current
[Consumer Terms](https://www.anthropic.com/legal/consumer-terms) and
[Usage Policy](https://www.anthropic.com/aup). Everything else is supporting
context — verify it.*
