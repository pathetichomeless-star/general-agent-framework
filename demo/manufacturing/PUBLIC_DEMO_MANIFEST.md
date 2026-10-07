# Public demo manifest — manufacturing

This file states what is in this directory, the boundary constants for review
and tooling, and the honest scope of the public simulation mode. Nothing in
this directory grants a licence of any kind.

## Files

| Path | Purpose |
|---|---|
| `run_demo.py` | Entrypoint: assembles the app, seeds demo data, serves the UI. |
| `framework_port/` | The public Facade contract (protocol, DTOs, errors, constants). |
| `backend_sim/` | The deterministic public simulation backend (in-process). |
| `app/` | Application: HTTP server, views, i18n, policy tables, scripted agents, seed. |
| `adapters/` (in `app/external_sims.py`) | Simulated external systems (carrier). In-process, no network. |
| `data/` | Reserved for fixture exports; the seed is code for determinism. |
| `docs/` | Architecture contract, boundary, demo script, RBAC, data model, terminology. |
| `tests/` | Contract test suite + boundary guard (stdlib unittest). |
| `pack/` | Placeholder documenting where a licensed Domain Pack would bind (no code). |

## Machine-readable constants

    DEMO_TRANSPORT = IN_PROCESS_DETERMINISTIC
    PRIMARY_BUSINESS_DEMO = MANUFACTURING
    PUBLIC_SIMULATION_BACKEND = DEMO_OWNED_STATE_MACHINE
    FRAMEWORK_SOURCE_COPIED = NO
    FRAMEWORK_IMPORTS_IN_DEMO_CODE = ZERO
    LICENSED_BACKEND_IN_PUBLIC_REPO = NO
    AGENT_MODE_DEFAULT = SCRIPTED_DETERMINISTIC
    NETWORK_ACCESS = NONE
    SYNTHETIC_DATA_ONLY = YES
    POSITIONING_SENTENCE_QUOTATION_RULE = MUST_NOT_BE_QUOTED_IN_ISOLATION

## Scope and honesty rules

- **Public Simulation Mode** demonstrates the business workflow with
  deterministic synthetic behaviour. It is **not** the licensed commercial
  runtime and proves nothing about it.
- **Licensed Framework Mode** (private, not in this repository) binds the same
  application contract to the privately licensed framework. Its execution
  evidence is established separately, by its own acceptance path.
- The two modes share the application contract; they are **not** the same
  implementation, and public material must never imply otherwise.
- The demo's assistant-message persistence is **demo-local**; in licensed
  mode that capability is LIMITED until a supported framework API exists.
- The evidence-chain verification shown here covers **approval-task evidence
  only**; other audit records are retained and auditable and are not claimed
  to be hash-chained. The demonstrated reconciliation verdicts are
  `unobservable` and `matched (derived)`; command truth is never rewritten.
- No credentials, no network endpoints, no real customer data, no build
  artefacts, no release evidence.
