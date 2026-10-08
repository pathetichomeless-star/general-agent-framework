# Public showcase source map

This file documents public source material and claim scope. It is build-source documentation, excluded from the publishable artifact. Repository references below are relative public paths; no private evidence or implementation is referenced.

| Page | Public sources | Retained scope |
|---|---|---|
| Home | [README](../README.md) | Positioning, design-goal limitation, primary simulation versus secondary licensed technical demo |
| Manufacturing | [Manufacturing README](../demo/manufacturing/README.md), [expected flow](../demo/manufacturing/EXPECTED_FLOW.md) | Synthetic deterministic data, scripted assistance, approval simulation, independent public simulation; workflow snapshots are not simultaneous |
| Governed actions | [Governed actions](../docs/governed-actions.md), [technical expected flow](../demo/EXPECTED_FLOW.md) | Conceptual approval and authorization; durable attempt evidence belongs to the Framework-backed technical demo; evidence chain is approval-task-only |
| Reconciliation | [Reconciliation and recovery](../docs/reconciliation-and-recovery.md), [technical expected flow](../demo/EXPECTED_FLOW.md), [technical setup](../demo/README.md) | UNKNOWN stays distinct from MATCHED (derived); freshness, conditional retry and provider assumptions; licensed rerun requirement |
| Concepts | [Conceptual architecture](../docs/architecture.md) | Problem-space lifecycle only; no internal module map or implementation topology |
| Boundary | [README](../README.md), [LICENSE](../LICENSE), [COMMERCIAL](../COMMERCIAL.md), [SECURITY](../SECURITY.md) | Public to view, all rights reserved; commercial implementation privately licensed; existing public contact and no SLA |
| Licensing & Contact | [README](../README.md), [COMMERCIAL](../COMMERCIAL.md), [LICENSE](../LICENSE), [SECURITY](../SECURITY.md) | Evaluation, licensing, source-access and commercial-use enquiries; private licence discussion and agreement-scoped delivery only; no fixed published price or SLA; existing mailbox and WeChat; separate security category and concise Chinese summary |

## Asset scope

- `assets/manufacturing-owner-dashboard.png`: pending approvals and manufacturing risks, synthetic public simulation.
- `assets/manufacturing-ai-human-approval.png`: shortage of 80 kg and recommendation of 120 kg, demo human approval simulation.
- `assets/manufacturing-shipment-reconciliation.png`: separate UNKNOWN command truth and MATCHED (derived) external verdict, no live carrier.
- `assets/terminal-demo-overview.png`: captured technical refund S1–S3 introduction (scenario, governance, admission) only. It is not itself evidence of durable execution or UNKNOWN handling. Synthetic data, simulated approval, separately licensed Framework needed for rerun.

The ambiguous conceptual overview image is intentionally not published. No additional diagram or asset is included. Frozen source/copy checksums are recorded in `pages.json` and independently constrained by the builder's whitelist.

## Build and metadata

The seven fragments share `layout.html` and `styles.css`. `pages.json` supplies escaped metadata, navigation and explicit routes. The builder requires a centralized HTTPS project `base_url`; local validation does not authorize publication of these changes. Canonical, Open Graph and sitemap URLs use that same input. Ordinary navigation and assets use relative links.

Local validation builds only `_site/`. Its exact 14-file inventory comprises seven HTML pages (including `licensing.html`), four frozen PNG assets, `styles.css`, `sitemap.xml` and `.nojekyll`. It excludes these sources, contracts, runtime data and all other repository files. The explicit route and asset whitelists, static-content and forbidden-content checks, metadata and sitemap validation, accessibility checks, asset SHA256 verification, symlink/hardlink protection and fail-closed output inventory checks remain in force.

The existing manual Pages workflow remains unchanged and checks out frozen showcase source commit `ac586b3718d0f6b109c69b1be053900b6cf7a286`. It will not include this page until a new audited source commit is separately authorized and its source pin is updated in a later, separately controlled commit. Publication, settings, artifact uploads, commits and pushes require separate authorization.
