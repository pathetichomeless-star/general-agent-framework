# Public demo manifest

This file lists what is in this directory, states the import mode used, and
records machine-readable constants for review and tooling. Nothing in this
directory grants a licence of any kind.

## Files

| Path | Purpose |
|---|---|
| `README.md` | Buyer-facing narrative and run instructions. |
| `demo.py` | Orchestration: resolves the framework, wires the governed write path, runs the stages. |
| `fake_business_system.py` | Fake, in-process refund ledger and authoritative read answer. |
| `fixtures/order.json` | Synthetic order `DEMO-ORDER-001`. |
| `EXPECTED_FLOW.md` | Stage-by-stage expected public behaviour. |
| `PUBLIC_DEMO_MANIFEST.md` | This file. |
| `.gitignore` | Ignores caches and local run artefacts. |

## Machine-readable constants

    PUBLIC_SHOWCASE_LICENSE_DECISION = PENDING_OWNER_DECISION
    POSITIONING_SENTENCE_QUOTATION_RULE = MUST_NOT_BE_QUOTED_IN_ISOLATION
    FRAMEWORK_API_IMPORT_MODE = DIRECT_SUBMODULE_PUBLIC_SYMBOLS
    FRAMEWORK_SOURCE_COPIED = NO
    DEMO_TRANSPORT = IN_PROCESS_DETERMINISTIC_ADAPTER
    PRODUCTION_COMPOSITION_PATH_USED = NO

Notes that belong with the constants:

- `PUBLIC_SHOWCASE_LICENSE_DECISION = PENDING_OWNER_DECISION` — No licence of
  any kind is granted by this directory.
- `POSITIONING_SENTENCE_QUOTATION_RULE = MUST_NOT_BE_QUOTED_IN_ISOLATION` — Any
  reproduction of the positioning sentence in external material must be
  accompanied by the "What this demo is not" qualifications.
- `FRAMEWORK_API_IMPORT_MODE = DIRECT_SUBMODULE_PUBLIC_SYMBOLS` — The demo
  imports the framework's external-write symbols directly from their public
  submodules, because they are module-level public APIs that the package
  `__init__` does not re-export. No framework source is modified to obtain them.
- `FRAMEWORK_SOURCE_COPIED = NO` — This directory contains no framework source
  code, in whole or in part, and no governance, durable-execution or
  reconciliation implementation.
- `DEMO_TRANSPORT = IN_PROCESS_DETERMINISTIC_ADAPTER` — The transport is
  substituted with a deterministic in-process adapter. No HTTP adapter is
  constructed and no outbound connection is opened.
- `PRODUCTION_COMPOSITION_PATH_USED = NO` — The demo wires below the production
  composition boundary, because that boundary mandates an http(s) endpoint and
  would constitute a real network write. This is the framework's documented
  deterministic-adapter extension point, not the supported production assembly
  path. Every guarantee above the transport is the framework's own code path.

## Scope of the directory

- Synthetic identifiers only (`DEMO-` values). No real customer data.
- No credentials, connection strings, private keys or network endpoints.
- No packaging, no build artefacts, no validation harnesses, no release
  evidence, and no certification material.
- A separate private, commercial edition of the framework exists. This
  directory is a demonstration that accompanies it; it is not part of it and
  grants no rights to it.
