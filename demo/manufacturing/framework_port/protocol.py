"""The ManufacturingBackend Facade protocol.

This is the single dependency boundary of the Hongsheng Works manufacturing
demo application. The application depends ONLY on this protocol and the DTOs
in this package — never on any concrete backend implementation or on any
external framework module.

Two backends implement this protocol:

- PublicSimulatedBackend (shipped in this repository): a deterministic,
  in-process behaviour simulator with synthetic data. It makes the demo
  independently runnable and claims nothing about any commercial runtime.
- LicensedFrameworkBackend (private, separately licensed): binds the same
  contract to the commercially licensed framework. It is NOT part of this
  repository and is not required to run the public demo.

Both backends must satisfy the same contract test suite.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from .dtos import (
    ActionResult,
    ApprovalView,
    AuditEntry,
    BackendCapabilities,
    BackendConfig,
    ConversationMessage,
    EvidenceVerification,
    GovernedActionView,
    HandoffView,
    NotificationView,
    Principal,
    Record,
    RecordRef,
    ReconciliationResult,
    RoleRule,
    TaskView,
    UserView,
    ApprovalPolicy,
    ExternalReadResult,
    ExternalApplyResult,
)


@runtime_checkable
class ExternalSystemSimulator(Protocol):
    """A demo-owned simulated external system of record (e.g. a carrier).

    It knows nothing about governance: it applies commands idempotently and
    answers reads. Whether an answer is fresh enough, or matches what was
    approved, is decided by the backend — never by the simulator.
    """

    def apply(
        self,
        *,
        kind: str,
        command_id: str,
        idempotency_key: str,
        target: RecordRef,
        payload: Mapping[str, Any],
    ) -> ExternalApplyResult: ...

    def read(self, *, kind: str, target: RecordRef) -> ExternalReadResult: ...


@runtime_checkable
class ManufacturingBackend(Protocol):
    """The minimal business-level surface the demo application needs.

    Implementations must be single-process and safe for concurrent use by the
    demo's HTTP server threads. All mutating operations are authorised,
    audited and (where policy requires) approval-gated by the backend.
    """

    # -- lifecycle & capability -------------------------------------------
    def query_capabilities(self) -> BackendCapabilities: ...
    def configure_authorization(
        self,
        rules: tuple[RoleRule, ...],
        approval_policies: tuple[ApprovalPolicy, ...] = (),
        approver_roles: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None: ...
    def close(self) -> None: ...

    # -- identity & session -------------------------------------------------
    def authenticate(self, username: str, credential: str) -> Principal | None: ...
    def create_session(self, principal: Principal) -> str: ...
    def resolve_session(self, token: str) -> Principal | None: ...
    def close_session(self, token: str) -> None: ...
    def list_users(self, actor: Principal) -> list[UserView]: ...

    # -- business records ---------------------------------------------------
    def list_records(
        self,
        actor: Principal,
        record_type: str,
        *,
        filters: Mapping[str, Any] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Record]: ...
    def get_record(self, actor: Principal, ref: RecordRef) -> Record | None: ...
    def create_record(
        self, actor: Principal, record_type: str, fields: Mapping[str, Any]
    ) -> Record: ...
    def update_record(
        self,
        actor: Principal,
        ref: RecordRef,
        fields: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> Record: ...
    def execute_business_action(
        self,
        actor: Principal,
        ref: RecordRef,
        action: str,
        payload: Mapping[str, Any] | None = None,
    ) -> ActionResult: ...

    # -- approvals -----------------------------------------------------------
    def request_approval(
        self,
        actor: Principal,
        kind: str,
        target: RecordRef,
        payload: Mapping[str, Any],
        *,
        justification: str,
    ) -> ApprovalView: ...
    def list_approvals(
        self, actor: Principal, *, pending_for_me: bool = True
    ) -> list[ApprovalView]: ...
    def get_approval(self, actor: Principal, approval_id: str) -> ApprovalView | None: ...
    def approve(
        self, actor: Principal, approval_id: str, *, comment: str = ""
    ) -> ApprovalView: ...
    def reject(
        self, actor: Principal, approval_id: str, *, comment: str = ""
    ) -> ApprovalView: ...

    # -- governed external actions -------------------------------------------
    def submit_governed_action(
        self,
        actor: Principal,
        kind: str,
        target: RecordRef,
        payload: Mapping[str, Any],
        *,
        reason: str,
    ) -> GovernedActionView: ...
    def get_governed_action(
        self, actor: Principal, action_id: str
    ) -> GovernedActionView | None: ...
    def execute_governed_action(self, actor: Principal, action_id: str) -> GovernedActionView: ...
    def observe_external_action(self, actor: Principal, action_id: str) -> GovernedActionView: ...
    def reconcile_external_action(
        self, actor: Principal, action_id: str
    ) -> ReconciliationResult: ...

    # -- tasks & handoff -------------------------------------------------------
    def list_tasks(
        self,
        actor: Principal,
        *,
        assignee: str | None = None,
        status: str | None = None,
    ) -> list[TaskView]: ...
    def create_task(
        self,
        actor: Principal,
        kind: str,
        title: str,
        assignee: str,
        *,
        due_at: str | None = None,
        related: RecordRef | None = None,
        origin: str = "human",
        note: str = "",
    ) -> TaskView: ...
    def complete_task(self, actor: Principal, task_id: str, *, note: str = "") -> TaskView: ...
    def request_handoff(
        self, actor: Principal, task_id: str, to_actor: str, *, reason: str
    ) -> HandoffView: ...
    def respond_handoff(
        self, actor: Principal, handoff_id: str, accept: bool, *, note: str = ""
    ) -> HandoffView: ...

    # -- notifications -----------------------------------------------------------
    def notify(
        self,
        actor: Principal,
        kind: str,
        recipients: tuple[str, ...],
        *,
        title: str,
        body: str,
        priority: str = "normal",
        related: RecordRef | None = None,
    ) -> None: ...
    def list_notifications(
        self, actor: Principal, *, unread_only: bool = False
    ) -> list[NotificationView]: ...
    def unread_count(self, actor: Principal) -> int: ...
    def mark_notification_read(
        self, actor: Principal, notification_id: str, *, read: bool = True
    ) -> None: ...

    # -- assistant conversation persistence (demo-owned) --------------------------
    def append_message(
        self, actor: Principal, conversation_id: str, role: str, text: str
    ) -> ConversationMessage: ...
    def list_messages(
        self, actor: Principal, conversation_id: str
    ) -> list[ConversationMessage]: ...

    # -- audit & evidence ----------------------------------------------------------
    def get_audit_timeline(self, actor: Principal, subject: RecordRef) -> list[AuditEntry]: ...
    def verify_evidence_chain(
        self, actor: Principal, subject: RecordRef
    ) -> EvidenceVerification: ...


def create_backend(config: BackendConfig):
    """Backend factory hook point.

    The public demo imports the simulated backend factory explicitly from
    ``backend_sim``. A licensed environment provides its own factory via
    configuration; this public package never references it by name.
    """
    raise NotImplementedError
