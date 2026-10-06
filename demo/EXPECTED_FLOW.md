# Expected flow

This is the stage-by-stage behaviour the demo is expected to produce. It is a
description of the public behaviour, not a copy of any framework source. Both
`GAF_DEMO_MODE=auto` and `GAF_DEMO_MODE=interactive` print the same stage
content; interactive only adds prompts between stages and asks the simulated
approver to confirm.

All data is synthetic. The order is `DEMO-ORDER-001`, the refund is CNY 100.00,
and the idempotency key is `DEMO-IDEMPOTENCY-001`.

## S1 SCENARIO

The agent is asked to refund CNY 100.00 for a synthetic order. The demo states
that the framework has no built-in "refund" semantic and that mapping a refund
onto a `(order -> refund, create)` write is a modelling choice declared through
the framework's integration records, not a framework feature.

## S2 GOVERNANCE

An administrator establishes the prerequisites, and each step is independently
required:

- the external system is registered;
- an ownership ruling of `external_authoritative` is confirmed for the
  `(application, external system, local object type)` scope;
- the object mapping `order -> refund` is registered;
- a write profile for exactly this operation is confirmed and becomes `ACTIVE`.

Expected: the profile starts unconfirmed; only the explicit administrator
decision makes it active. A missing or revoked profile admits nothing.

## S3 ADMISSION

The agent proposes the refund. Expected:

- the command is admitted in state `awaiting_approval`;
- the command carries an approval reference and an approval binding (a digest
  over the application scope, external system, object types, target object,
  operation and payload);
- the payload digest is shown.

Teaching point printed by the demo: an external write command cannot be
constructed without an approval binding, and the state machine has no
`requested -> ready` transition. An unapproved external write is inexpressible,
not merely forbidden.

## S4 WRITE BLOCKED BEFORE APPROVAL

The demo attempts to dispatch the write before approval. Expected:

- the framework refuses with a dispatch error;
- **zero** requests reach the adapter;
- the authoritative fake ledger is still empty.

## S5 DEMO HUMAN APPROVAL SIMULATION

The demo prints the label `DEMO HUMAN APPROVAL SIMULATION` and states that no
human approves a real transaction. The approver identity is distinct from the
requester identity, and the framework's approval authority enforces that
separation.

- In `auto` mode: the simulation grants the approval automatically so the run is
  reproducible.
- In `interactive` mode: the demo asks for an explicit decision. Declining moves
  the command to `rejected` through the framework's rejection path, and the demo
  stops with no refund written.

On approval, the command state becomes `ready`.

## S6 EXECUTION

The approved command is dispatched once. Expected:

- the framework commits the attempt to durable storage before the external call
  and makes the call outside any database transaction;
- exactly one request reaches the adapter;
- the adapter applies the refund and answers `ambiguous` (a lost response after a
  committed write);
- the attempt outcome, read back from the framework's attempt record, is
  `unknown`;
- the command state, read back from the framework's command record, is `unknown`;
- the fake ledger now holds exactly one refund.

The demo does not print the string "unknown" as its own conclusion. It reads the
value back from the framework's records.

## S7 DANGER

The demo attempts a blind retry. Expected:

- the framework refuses to redispatch an `unknown` command whose operation
  profile does not confirm both that the provider honours the same idempotency
  key and that the repeat is safe;
- **zero** further requests reach the adapter;
- the fake ledger still holds exactly one refund.

## S8 RECONCILE

The demo resolves the `unknown` state by reading the external system through the
framework's governed read boundary and deriving a verdict with the framework's
pure reconciliation function.

(i) The producer declares **no** freshness window (`ttl = 0`). Expected:

- the framework's freshness outcome is `unknown`;
- the framework's reconciliation verdict is `unobservable` ("we looked, and we
  cannot certify").

(ii) The producer declares a freshness window (`ttl = 3600`). Expected:

- the framework's freshness outcome is `fresh`;
- the framework's reconciliation verdict is `matched` ("we looked, and we
  certify"), because the observed payload digest equals the digest of the
  content that was approved.

Both verdicts are derived by the framework, not stored and not hard-coded by the
demo.

## S9 RESULT

Two axes are printed separately and never merged:

- command truth (the framework's command state) = `unknown`;
- external truth (the reconciliation verdict) = `matched` (derived);
- the authoritative fake ledger = exactly one refund of CNY 100.00, never two.

The demo states that the reconciliation verdict is derived rather than stored,
and that the command remains `unknown` because there is no edge from `unknown`
to `succeeded` for this lost-response case.

The framework's write-store audit trail is then printed, oldest first, showing
each audited step (profile confirmed, command admitted, command ready, dispatch
claimed, attempt dispatched, attempt terminalised, command settled, observations
recorded) with the resulting state. Finally the demo verifies the approval
task's evidence hash chain.

The demo prints stable facts only: sequence numbers, target kinds, audit
operation names, actors and resulting states. Framework-generated identifiers
are not printed, so two clean runs produce identical output.

## S9b IDEMPOTENT REPLAY (optional)

Enabled by `GAF_SHOW_IDEMPOTENT_REPLAY=1`. An administrator changes the write
profile to declare this create safe to repeat against this provider. The
framework refuses to silently mutate an active profile, so the change is an
explicit revoke followed by an explicit re-confirm; both are audited.

A permitted redispatch then occurs. Expected:

- two requests reach the adapter in total;
- the second request carries the same idempotency key (the framework never
  derives a new key on redispatch);
- the adapter detects the repeated key and returns the **original** provider
  reference without a second ledger entry;
- the fake ledger still holds exactly one refund of CNY 100.00.

This makes exactly-once empirical: two sends, one refund, one provider
reference.

## Determinism

From a clean state, two `GAF_DEMO_MODE=auto` runs produce byte-identical output.
The demo uses a fixed clock everywhere the framework accepts one, a fresh
temporary database and a fresh fake ledger per run, and it prints no
per-run identifiers.
