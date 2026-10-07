"""Public DTOs for the demo Facade.

Every DTO is a frozen dataclass whose fields are primitive, business-facing
values only. No backend may add internal identifiers, digests, schema
information or implementation names to these structures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Principal:
    """An authenticated demo user."""

    actor_id: str
    display_name: str
    role: str
    locale: str = "zh"


@dataclass(frozen=True)
class RecordRef:
    record_type: str
    record_id: str
    version: int = 0


@dataclass(frozen=True)
class Record:
    ref: RecordRef
    fields: Mapping[str, Any]
    updated_at: str = ""
    updated_by: str = ""


@dataclass(frozen=True)
class ActionResult:
    ref: RecordRef
    state: str
    approval_id: str | None = None
    note: str = ""


@dataclass(frozen=True)
class ApprovalView:
    approval_id: str
    kind: str
    target: RecordRef
    requested_by: str
    requested_at: str
    justification: str
    status: str  # pending | approved | rejected
    payload: Mapping[str, Any] = field(default_factory=dict)
    decided_by: str = ""
    decided_at: str = ""
    decision_note: str = ""


@dataclass(frozen=True)
class TaskView:
    task_id: str
    kind: str
    title: str
    assignee: str
    status: str  # open | done | cancelled
    due_at: str = ""
    related: RecordRef | None = None
    origin: str = ""  # human | agent | system
    note: str = ""


@dataclass(frozen=True)
class HandoffView:
    handoff_id: str
    task_id: str
    from_actor: str
    to_actor: str
    status: str  # pending | accepted | rejected
    reason: str = ""
    note: str = ""


@dataclass(frozen=True)
class NotificationView:
    notification_id: str
    kind: str
    priority: str  # critical | warning | normal | low
    title: str
    body: str
    created_at: str
    read_state: str  # unread | read
    related: RecordRef | None = None


@dataclass(frozen=True)
class GovernedActionView:
    action_id: str
    kind: str
    target: RecordRef
    reason: str
    state: str  # approved | dispatching | completed | unknown | failed
    submitted_by: str
    submitted_at: str
    approval_id: str | None = None
    attempt_no: int = 0
    attempt_outcome: str = ""  # accepted | unknown | rejected | ""
    dispatched_at: str = ""


@dataclass(frozen=True)
class ReconciliationResult:
    """Two independent truth axes. The external verdict NEVER rewrites the
    command truth; both are reported side by side, always."""

    action_id: str
    command_truth: str  # e.g. "unknown" — what the backend recorded about its own attempt
    external_verdict: str  # e.g. "matched (derived)" / "unobservable"
    freshness: str  # "fresh" | "unknown"
    note: str = ""


@dataclass(frozen=True)
class EvidenceVerification:
    scope: str  # always "approval_task" — the only hash-verified evidence domain
    subject: RecordRef
    verified: bool
    entries_checked: int
    note: str = ""


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    at: str
    actor_id: str
    action: str
    subject: RecordRef
    parent: RecordRef | None = None
    detail: str = ""


@dataclass(frozen=True)
class ConversationMessage:
    message_id: str
    conversation_id: str
    role: str  # user | assistant
    text: str
    created_at: str


@dataclass(frozen=True)
class UserView:
    actor_id: str
    display_name: str
    role: str
    locale: str = "zh"


@dataclass(frozen=True)
class BackendCapabilities:
    mode: str  # public_simulation | licensed_framework
    features: Mapping[str, bool | str] = field(default_factory=dict)


@dataclass(frozen=True)
class RoleRule:
    """One authorisation rule: a role may perform ``permission`` on
    ``resource_type``. When ``owner_scoped`` is true the rule only applies to
    records whose ``owner_id`` field equals the acting user."""

    role: str
    permission: str
    resource_type: str
    owner_scoped: bool = False


@dataclass(frozen=True)
class ApprovalPolicy:
    """Business policy: when ``action`` is executed and ``condition`` matches
    the submitted payload, an approval request for ``approver_role`` is created
    before the action can take effect. Conditions are data, evaluated by the
    backend; see backend docs for the supported operators."""

    action: str
    condition: Mapping[str, Any]
    approver_role: str
    justification_label: str = "reason"


@dataclass(frozen=True)
class ExternalApplyResult:
    result_class: str  # accepted | ambiguous | rejected
    payload: Mapping[str, Any] = field(default_factory=dict)
    provider_ref: str = ""


@dataclass(frozen=True)
class ExternalReadResult:
    payload: Mapping[str, Any] | None
    freshness_ttl_seconds: int = 0


@dataclass(frozen=True)
class UserBootstrap:
    """A synthetic demo user provisioned at backend construction."""

    actor_id: str
    display_name: str
    role: str
    locale: str = "zh"
    credential: str = "demo1234"


@dataclass(frozen=True)
class BackendConfig:
    """Construction inputs for a backend. ``clock`` returns an ISO-8601 UTC
    string; deterministic runs inject a fixed clock. ``external_systems`` are
    demo-owned simulated systems of record keyed by governed action kind.
    ``bootstrap_users`` are synthetic demo users created at startup."""

    db_path: str
    clock: Any = None  # Callable[[], str]; backend supplies a wall-clock default
    external_systems: Mapping[str, Any] = field(default_factory=dict)
    application_id: str = "DEMO-MFG-APP"
    bootstrap_users: tuple[Any, ...] = ()  # tuple[UserBootstrap, ...]
