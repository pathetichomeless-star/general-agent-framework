"""Demo-owned simulated external systems (no network, fully deterministic).

SimulatedCarrier stands in for "some external logistics system of record". It
owns exactly two capabilities: apply a dispatch into an append-only in-memory
ledger keyed by the backend-supplied idempotency key, and answer reads with
the authoritative state that was actually written. Its behaviour follows the
demo's published story: the first dispatch commits the write but the response
is lost (an AMBIGUOUS answer), so the honest outcome is UNKNOWN. It knows
nothing about governance.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Mapping

from framework_port import constants as C
from framework_port.dtos import ExternalApplyResult, ExternalReadResult, RecordRef


class SimulatedCarrier:
    """In-memory dispatch ledger plus an authoritative read answer."""

    def __init__(self) -> None:
        self._ledger: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._sequence = 0
        self.freshness_ttl_seconds = 3600

    def apply(
        self,
        *,
        kind: str,
        command_id: str,
        idempotency_key: str,
        target: RecordRef,
        payload: Mapping[str, Any],
    ) -> ExternalApplyResult:
        existing = self._ledger.get(idempotency_key)
        if existing is not None:
            return ExternalApplyResult(
                result_class=C.RESULT_ACCEPTED,
                payload=dict(existing["payload"]),
                provider_ref=str(existing["provider_ref"]),
            )
        self._sequence += 1
        record = {
            "provider_ref": f"DEMO-CARRIER-REF-{self._sequence:03d}",
            "idempotency_key": idempotency_key,
            "command_id": command_id,
            "target": f"{target.record_type}:{target.record_id}",
            "payload": dict(payload),
        }
        self._ledger[idempotency_key] = record
        # The write has committed, but the response to the caller is lost.
        # The honest answer is "I cannot tell you whether this was accepted" —
        # not a fabricated success.
        return ExternalApplyResult(
            result_class=C.RESULT_AMBIGUOUS,
            payload={},
            provider_ref="",
        )

    def read(self, *, kind: str, target: RecordRef) -> ExternalReadResult:
        want = f"{target.record_type}:{target.record_id}"
        for record in reversed(self._ledger.values()):
            if record["target"] == want:
                return ExternalReadResult(
                    payload=dict(record["payload"]),
                    freshness_ttl_seconds=self.freshness_ttl_seconds,
                )
        return ExternalReadResult(payload=None, freshness_ttl_seconds=0)

    def ledger_size(self) -> int:
        return len(self._ledger)
