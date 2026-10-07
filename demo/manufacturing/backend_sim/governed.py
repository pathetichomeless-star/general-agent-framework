"""Pure helpers for the governed external-action simulation.

These implement the demo's OWN simplified, deterministic semantics for the
observable governed-write behaviour described in the public documentation:

- an attempt outcome may honestly be "unknown" (never rewritten);
- the external verdict is derived by comparing fresh observations with the
  approved payload — "matched (derived)" or "unobservable";
- the two axes are reported separately and never merged.

This module is authored from the demo specification and public claims only.
It deliberately does NOT reproduce any external framework implementation:
no durable command ledger internals, no approval-binding digests, no
idempotency-key machinery. Those are backend-specific behaviours; this demo
implements its own small, readable equivalents.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

VERDICT_UNOBSERVABLE = "unobservable"
VERDICT_MATCHED_DERIVED = "matched (derived)"

FRESHNESS_FRESH = "fresh"
FRESHNESS_UNKNOWN = "unknown"

OUTCOME_UNKNOWN = "unknown"


def canonical_digest(payload: Mapping[str, Any]) -> str:
    """Stable digest of a business payload for demo comparison purposes."""

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_external_verdict(
    *,
    command_state: str,
    observations: list[Mapping[str, Any]],
    approved_digest: str,
) -> tuple[str, str, str]:
    """Derive the external verdict from stored observations.

    Returns ``(external_verdict, freshness, note)``. The command state is an
    input only — this function never changes it.

    Demonstrated verdicts (per public demo claims): ``unobservable`` and
    ``matched (derived)``. Other conceivable verdicts are intentionally not
    demonstrated by this demo.
    """

    if not observations:
        return VERDICT_UNOBSERVABLE, FRESHNESS_UNKNOWN, "no observation recorded yet"
    latest = observations[-1]
    freshness = str(latest.get("freshness", FRESHNESS_UNKNOWN))
    if freshness != FRESHNESS_FRESH:
        return (
            VERDICT_UNOBSERVABLE,
            freshness,
            "the observation is not fresh enough to certify; the framework refuses to guess",
        )
    observed_digest = str(latest.get("observed_digest", ""))
    if observed_digest and observed_digest == approved_digest:
        return (
            VERDICT_MATCHED_DERIVED,
            freshness,
            "a fresh, certified read of the external system agrees with the approved content",
        )
    return (
        VERDICT_UNOBSERVABLE,
        freshness,
        "the fresh observation does not agree with the approved content",
    )
