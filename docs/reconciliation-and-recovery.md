# Reconciliation and recovery

## The problem: a write that may already have happened

Distributed writes fail in a way that local function calls do not. When a request is sent to an
external system, three things can be true afterwards:

1. the system applied the change and returned a response;
2. the system rejected the change; or
3. **the system applied the change, and the response never arrived.**

The third case is the dangerous one. A timeout, a dropped connection, or a crash immediately after
sending all look identical to the caller, and none of them tells you whether the side effect
happened.

> **UNKNOWN is not FAILED.**

If you assume an unknown outcome means "it failed" and send the request again, you can apply the
change twice — one refund becomes two. If you assume it means "it succeeded" and do nothing, you
may be wrong in the other direction. Both assumptions are guesses.

## What the framework does instead

**It records that it does not know.** An outcome that cannot be proven accepted is never recorded
as success. That is a deliberate refusal to guess.

**It refuses a blind retry.** Re-sending an indeterminate write is not something the framework does
automatically. A re-dispatch is refused unless the operation's active, administrator-confirmed
profile asserts both that the provider will treat the same idempotency key as the same operation,
and that repeating the operation is safe. The framework records the administrator's assertion and
holds the operation to it; it makes no claim about how any third-party system behaves.

**It reconciles against authoritative external state.** Instead of guessing, the agent reads the
current state of the external object through the governed read path and derives a verdict:

| Verdict | Meaning |
|---|---|
| `unobserved` | We have not looked yet. |
| `matched` | A fresh, usable observation agrees with what we intended to write. |
| `diverged` | A fresh, usable observation disagrees. A human should look. |
| `unobservable` | We have evidence, but none of it is fresh and usable. |

"We don't know" and "it disagrees" are different answers, and neither is permitted to masquerade as
the other. A stale observation can never be counted as a match.

> The framework's vocabulary has these four verdicts. **The public demo exercises two of them** —
> `unobservable`, then `matched`. The other two are part of the vocabulary but are not demonstrated.

Reconciliation is *derived* from the recorded command plus its observations. It is not a second
source of truth and it does not rewrite history.

## Idempotency — and what it does not promise

The write carries an idempotency key that is derived once and stays stable across retries. Two
requests with the same key and the same binding are one request; the same key with a different
binding is a conflict and fails closed. Different keys are different requests. *(This paragraph
describes framework design behaviour. The public demo exercises the key-stability property; it does
not exercise the conflicting-binding path.)*

**An important limit:** whether a given external provider actually honours that key is an
**assumption an administrator confirms when configuring the operation** — it is not something the
framework can know or guarantee about a third-party system. The framework's guarantee is about its
own behaviour: it never derives a new key for a retry, so a provider that does honour the key will
not double-apply.

## The honest end state

At the end of the public demo, the framework reports two separate things, and it never merges them:

```text
command truth                            = unknown     (we never got a confirmation)
external truth (reconciliation verdict)  = matched     (external state agrees)
authoritative ledger                     = 1 x CNY 100.00
```

The command is *not* reported as succeeded. "We could not confirm" stays "we could not confirm",
even when the external world turns out to agree. That is the difference between a system that
reconciles and a system that merely retries.
