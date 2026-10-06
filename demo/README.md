# Build AI agents that can safely act on real business systems.

## The problem this points at

Giving an agent the ability to write to a real system is easy. Making that write
*safe* is the hard part, because the dangerous cases are not the ones where
everything goes wrong loudly. They are the quiet ones:

- **The write happens before anyone approved it.** A helpful agent decides a
  refund is obviously correct and sends it.
- **The response is lost after the write committed.** The provider applied the
  refund, but the caller never saw the confirmation. Should the agent retry?
  Retrying may refund the customer twice. Not retrying may leave a refund that
  the system thinks never happened.
- **Someone retries anyway.** A timeout is treated as a failure, the agent sends
  the request again, and now the customer has two refunds.

An agent that cannot tell "this failed" apart from "I do not know what happened"
will eventually treat the second as the first and cause exactly the damage it
was supposed to prevent.

## What this demo shows

The demo refunds CNY 100.00 for a synthetic order against a fake, in-process
business system. It walks through the governed path one stage at a time, from
the scenario to the final audit trail:

1. **Scenario** — a refund of CNY 100.00 for order `DEMO-ORDER-001`. Synthetic
   data only.
2. **Governance** — the external system, the ownership ruling, the object
   mapping and the write profile must all be explicitly set up by an
   administrator before any write is even expressible.
3. **Admission** — the agent proposes the refund. The resulting write command
   carries an approval reference and an approval binding; a command without them
   cannot be built at all.
4. **Write blocked before approval** — dispatching before approval is refused by
   the framework, with zero requests reaching the adapter and an empty ledger.
5. **Approval** — a segregated approver (distinct from the requester) approves.
6. **Execution** — one dispatch. The framework commits the attempt before the
   call, makes exactly one call, and the adapter answers *ambiguous*: the refund
   was applied but the response was lost. The framework derives the outcome
   itself — it records that it does not know.
7. **Danger** — a blind retry is refused by the framework. Zero further
   requests. The ledger still holds exactly one refund.
8. **Reconcile** — the agent looks at the external system through the governed
   read boundary. With no declared freshness window the framework returns
   *unobservable*: "we looked, and we cannot certify." With a declared window it
   returns *matched*: "we looked, and we certify."
9. **Result** — two separate axes are printed and never merged: the framework's
   command truth (still `unknown`) and the derived external truth (`matched`),
   alongside the authoritative ledger (exactly one refund).

The framework's guarantees are the point. Authorization, approval binding, the
durable command and attempt ledger, result classification, the retry and
staleness rules, the read boundary and its freshness decision, the
reconciliation derivation and the audit trail are all the framework's own code.
The demo substitutes only the transport: it binds an in-process deterministic
adapter, which is the framework's documented extension point for deterministic
adapters. No HTTP adapter is constructed and no outbound connection is opened.

The framework has no built-in "refund" semantic. Refunds here are modelled as a
governed write of a `refund` object derived from an `order`; that mapping is a
demo choice, declared through the framework's integration records rather than
assumed by the framework.

## What the audit trail demonstrates

The approval task has a tamper-evident evidence chain. Each chained evidence
entry carries linkage to the preceding entry, and the demo runs the
framework's chain-verification operation for that approval-task evidence.

Separately, the demo prints framework write-store audit records for the
external-write profile, command, attempt, and observations. Those records
preserve the execution and reconciliation history, but this demo does not
claim that they are part of the same hash-linked approval evidence chain.

The distinction is intentional: the approval-task evidence chain is
hash-verified by this demo, while the external-write and reconciliation
history is presented as retained audit records.

## What this demo is not

- The opening sentence is a **design goal, not a certification**: here "safely"
  means *under explicit, operator-defined approval, evidence, and recovery
  controls*. It is not a security guarantee, and it is **not** a security,
  legal, or compliance certification — no security response SLA is implied.
- It is **not** a real transaction. The approval in stage 5 is labelled
  `DEMO HUMAN APPROVAL SIMULATION` and no human approves a real transaction
  anywhere in this demo. The business system is fake; the ledger lives in memory
  and is discarded when the run ends.
- It is **not** a claim that a human approved anything. The framework enforces
  that an approval exists and that the approver is not the requester; the demo
  supplies a scripted approver.
- It is **not** the framework's supported production assembly path. The
  production composition root requires an http(s) endpoint and would constitute
  a real network write, so this demo wires below it. That is deliberate and
  documented, not a shortcut around a guarantee.
- It is **not** a benchmark, a performance measurement or a claim about any
  specific provider. It is a small, deterministic, reproducible demonstration.
- It is **not** a substitute for your own threat model. It shows how the
  framework represents and refuses unsafe writes; it does not prove that any
  particular deployment is correct.
- It contains **no framework source code**. This directory is a demonstration
  only. A separate private, commercial edition of the framework exists; nothing
  in this directory is part of it, and nothing in this directory grants you any
  licence to it or to anything else. See `PUBLIC_DEMO_MANIFEST.md`.

## Running the demo

Requirements: Python 3.10 or newer — the same minimum the framework itself
requires — and the General Agent Framework importable by your interpreter. There
is no packaging, no dependency install and no network access involved.

The demo imports the framework directly. If it is not importable, point the
environment variable `GAF_FRAMEWORK_PATH` at the framework project root — the
directory that contains the framework's `src` package — and the demo will add
that `src` directory to its import path:

```sh
GAF_FRAMEWORK_PATH=/path/to/framework-project GAF_DEMO_MODE=auto python3 demo.py
```

Modes:

- `GAF_DEMO_MODE=auto` — runs every stage with no prompts and no TTY. Two clean
  runs produce identical output. Use this to record or review the demo.
- `GAF_DEMO_MODE=interactive` (the default when a terminal is present) — stops
  at each stage, and asks the simulated approver to confirm explicitly.
- `GAF_SHOW_IDEMPOTENT_REPLAY=1` — additionally runs the optional exactly-once
  sub-demo, where a safe, profile-approved retry is replayed with the same
  idempotency key: two requests, one refund, the same provider reference.

The demo creates a temporary database outside this directory for the run and
removes it afterwards. Apart from that temporary database and Python bytecode
caches, it writes nothing outside this directory, and it never contacts an
external system.
