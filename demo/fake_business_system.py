"""A deterministic, network-free fake business system for the public demo.

This module stands in for "some external system of record". It owns exactly two
capabilities and nothing else:

  1. apply a refund into an append-only in-memory ledger keyed by the
     framework-supplied idempotency key, returning the ORIGINAL record (and
     ``created=False``) without a second ledger entry when the key repeats;
  2. answer reads with the authoritative state that was actually written.

It deliberately knows nothing about governance. It does not decide command
states, does not know what an "unknown" outcome means, does not enforce
approval, does not retry, does not schedule anything, and does not reconcile.
Those decisions belong to the framework, not to the external system.

There is no network, no filesystem, no environment access, no credentials and
no real customer data here. Identifiers are synthetic ``DEMO-`` values and the
whole object is re-created for every run, so two clean runs behave identically.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class RefundRecord:
    """One authoritative refund row. The ledger never mutates an existing row."""

    provider_ref: str
    idempotency_key: str
    order_id: str
    amount: Decimal
    currency: str
    payload: Mapping[str, Any]


class FakeBusinessSystem:
    """In-memory refund ledger plus an authoritative read answer."""

    def __init__(self, order_id: str) -> None:
        self._default_order_id = order_id
        # Keyed by the idempotency key the framework supplies. The demo never
        # chooses or derives this key; it only passes through whatever the
        # framework put on the request.
        self._ledger: "OrderedDict[str, RefundRecord]" = OrderedDict()
        self._sequence = 0
        # The window this producer is willing to declare for its read answers.
        # 0 means "no window declared". The framework, not this class, turns the
        # declaration into a freshness outcome.
        self._declared_freshness_window = 0

    @property
    def default_order_id(self) -> str:
        return self._default_order_id

    @property
    def declared_freshness_window(self) -> int:
        return self._declared_freshness_window

    def declare_freshness_window(self, seconds: int) -> None:
        self._declared_freshness_window = int(seconds)

    # ---- capability 1: apply a refund (idempotent by key) --------------------

    def apply_refund(self, *, idempotency_key: str, payload: Mapping[str, Any]) -> tuple[RefundRecord, bool]:
        """Record a refund. Returns ``(record, created)``.

        If the key is already present, returns the ORIGINAL record with
        ``created=False`` and makes NO new ledger entry.
        """

        existing = self._ledger.get(idempotency_key)
        if existing is not None:
            return existing, False
        self._sequence += 1
        record = RefundRecord(
            provider_ref=f"DEMO-PROVIDER-REF-{self._sequence:03d}",
            idempotency_key=idempotency_key,
            order_id=str(payload.get("order_id", self._default_order_id)),
            amount=Decimal(str(payload.get("amount", "0.00"))),
            currency=str(payload.get("currency", "")),
            payload=dict(payload),
        )
        self._ledger[idempotency_key] = record
        return record, True

    def refund_records(self, order_id: str) -> tuple[RefundRecord, ...]:
        return tuple(record for record in self._ledger.values() if record.order_id == order_id)

    def refunded_total(self, order_id: str) -> Decimal:
        total = Decimal("0.00")
        for record in self.refund_records(order_id):
            total += record.amount
        return total

    def refund_count(self, order_id: str) -> int:
        return len(self.refund_records(order_id))

    # ---- capability 2: answer a read with the authoritative state ------------

    def read_refund(self, order_id: str) -> Mapping[str, Any] | None:
        """Return the authoritative content of the refund written for ``order_id``.

        This is the fake system's answer to a read; it is NOT a governance
        decision. Whether the answer is fresh enough, or belongs to the right
        command, is decided by the framework's read boundary.
        """

        records = self.refund_records(order_id)
        if not records:
            return None
        return dict(records[-1].payload)
