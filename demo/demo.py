"""Public demo: an AI agent safely acting on a real business system.

This script drives the General Agent Framework's governed external-write path
end to end against a fully fake, in-process business system. It demonstrates
that an external write cannot happen without a durable approval, that a lost
response is recorded as an unknowable outcome rather than guessed, that a blind
retry is refused by the framework, and that "the refund definitely happened" is
only ever asserted after a matching, fresh reconciliation.

WHAT IS REAL HERE
Everything above the transport is the framework's own code path: authorization,
approval binding, the durable command/attempt ledger, result classification,
the retry/staleness rules, the read boundary and freshness decision, the
reconciliation derivation and the audit trail.

WHAT IS FAKE HERE
The transport and the external system are demo-owned. No HTTP adapter is
constructed and no outbound socket is opened. The demo binds an in-process,
deterministic adapter, which is the framework's documented extension point for
deterministic adapters. It wires BELOW the framework's production composition
root on purpose: that root mandates an http(s) endpoint and would constitute a
real network write.

DEVELOPMENT-ONLY FRAMEWORK RESOLUTION
The framework is imported directly. If it is not importable, set the
environment variable GAF_FRAMEWORK_PATH to the framework project root (the
directory that contains its ``src`` package) and this script will add that
``src`` directory to the import path. No private path is hard-coded anywhere in
this directory.

MODES
  GAF_DEMO_MODE=interactive   stage by stage; press enter between stages and
                              answer the approval prompt explicitly.
  GAF_DEMO_MODE=auto          no prompt, no TTY; the full run, reproducibly.
  GAF_SHOW_IDEMPOTENT_REPLAY=1  also run the optional exactly-once sub-demo.

Both modes print the same stage content; interactive only adds prompts.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

# --------------------------------------------------------------------------
# Framework resolution (development-only; no private path in this file)
# --------------------------------------------------------------------------


def _resolve_framework() -> None:
    try:
        import general_agent_framework  # noqa: F401

        return
    except ModuleNotFoundError:
        pass

    base = os.environ.get("GAF_FRAMEWORK_PATH", "").strip()
    if base:
        src = Path(base) / "src"
        if src.is_dir():
            sys.path.insert(0, str(src))
            try:
                import general_agent_framework  # noqa: F401

                return
            except ModuleNotFoundError:
                pass

    sys.stderr.write(
        "This demo could not import the General Agent Framework.\n"
        "Install the framework, or set GAF_FRAMEWORK_PATH to the framework\n"
        "project root (the directory containing its 'src' package) and retry.\n"
    )
    raise SystemExit(2)


_resolve_framework()

from general_agent_framework.approval_authority import (  # noqa: E402
    ApprovalDecisionAuthority,
    non_system_owner_fallback,
)
from general_agent_framework.authorization import (  # noqa: E402
    AuthorizationPolicy,
    PermissionRule,
    PermissionSubject,
    RoleAuthorizationPolicy,
)
from general_agent_framework.config import AgentConfig, TaskKind  # noqa: E402
from general_agent_framework.core import AgentCore  # noqa: E402
from general_agent_framework.identity_service import IdentityRuntime  # noqa: E402
from general_agent_framework.integration_adapter import (  # noqa: E402
    AdapterReadResponse,
    InProcessIntegrationAdapter,
)
from general_agent_framework.integration_read import (  # noqa: E402
    INTEGRATION_READ_ACTION,
    ExternalReadBoundary,
)
from general_agent_framework.integration_service import (  # noqa: E402
    IntegrationService,
    identity_admin_checker,
)
from general_agent_framework.integration_store import SqliteIntegrationStore  # noqa: E402
from general_agent_framework.integration_write_adapter import (  # noqa: E402
    AdapterWriteResponse,
    AdapterWriteResultClass,
)
from general_agent_framework.integration_write_contracts import (  # noqa: E402
    ExternalWriteCommandState,
)
from general_agent_framework.integration_write_dispatch_contracts import (  # noqa: E402
    IntegrationWriteDispatchError,
    IntegrationWriteRedispatchRefusedError,
)
from general_agent_framework.integration_write_dispatch_service import (  # noqa: E402
    INTEGRATION_DISPATCH_ACTION,
    ExternalWriteDispatcher,
)
from general_agent_framework.integration_write_observation import (  # noqa: E402
    ExternalWriteObserver,
    derive_reconciliation,
)
from general_agent_framework.integration_write_service import (  # noqa: E402
    INTEGRATION_WRITE_ACTION,
    INTEGRATION_WRITE_RESOURCE_TYPE,
    ExternalWriteAdmission,
    ExternalWriteApprovalCoordinator,
)
from general_agent_framework.integration_write_store import (  # noqa: E402
    SqliteIntegrationWriteStore,
)
from general_agent_framework.store import SqliteDataLayer  # noqa: E402
from general_agent_framework.web import identity_seed_from_credentials  # noqa: E402

from fake_business_system import FakeBusinessSystem  # noqa: E402

# --------------------------------------------------------------------------
# Demo constants (all synthetic)
# --------------------------------------------------------------------------

APPLICATION_ID = "DEMO-APP-001"
APPROVAL_TASK_KIND = "external_write_approval"
SYSTEM_NAME = "DEMO-REFUND-PROVIDER"
SYSTEM_KIND = "refund_provider"
LOCAL_OBJECT_TYPE = "order"
EXTERNAL_OBJECT_TYPE = "refund"
ORDER_ID = "DEMO-ORDER-001"
IDEMPOTENCY_KEY = "DEMO-IDEMPOTENCY-001"
OPERATION = "create"

# A fixed clock used everywhere the framework accepts one, so that a run is
# reproducible byte for byte.
FIXED_CLOCK = "2026-10-06T00:00:00+00:00"

# The refund intent. The same mapping object feeds both the admitted command
# and the fake system's read answer, so the two canonicalise identically and
# reconciliation compares like with like.
REFUND_PAYLOAD = {
    "order_id": ORDER_ID,
    "amount": "100.00",
    "currency": "CNY",
    "reason": "customer_request",
}

# Demo identities. Values are synthetic bootstrap inputs for the framework's
# identity authority; they are never printed and no real account is involved.
DEMO_USERS = {
    "demo-admin": ("demo-admin-input", "admin"),
    "demo-requester": ("demo-requester-input", "user"),
    "demo-approver": ("demo-approver-input", "approver"),
}


def clock() -> str:
    return FIXED_CLOCK


def subject(actor_id: str, *roles: str) -> PermissionSubject:
    return PermissionSubject(actor_id, tuple(roles))


# --------------------------------------------------------------------------
# Terminal output
# --------------------------------------------------------------------------


class Emitter:
    def __init__(self, interactive: bool) -> None:
        self.interactive = interactive

    def blank(self) -> None:
        print()

    def stage(self, code: str, title: str) -> None:
        print()
        print(f"=== {code}  {title} ===")

    def line(self, text: str = "") -> None:
        print(text)

    def pause(self, note: str = "press enter for the next stage") -> None:
        if not self.interactive:
            return
        try:
            input(f"[{note}] ")
        except EOFError:
            pass


# --------------------------------------------------------------------------
# The deterministic write adapter (transport is the only substituted layer)
# --------------------------------------------------------------------------


class DemoRefundAdapter:
    """Answers write requests against the fake business system.

    It implements the framework's write-adapter contract (an id, a supported
    kind, a declared capability and a single ``send``). It makes no governance
    decision: it does not choose command states, does not retry and does not
    know what the framework will conclude from its answer.
    """

    def __init__(self, fake_system: FakeBusinessSystem) -> None:
        self._fake = fake_system
        self.adapter_id = "DEMO-IN-PROCESS-REFUND-ADAPTER"
        self.adapter_kind = "in_process"
        self.sends: list[object] = []
        self.answers: list[AdapterWriteResponse] = []

    def capabilities(self) -> frozenset[str]:
        return frozenset({"send"})

    def send(self, request: object) -> AdapterWriteResponse:
        self.sends.append(request)
        payload = dict(request.payload)  # type: ignore[attr-defined]
        record, created = self._fake.apply_refund(
            idempotency_key=request.idempotency_key,  # type: ignore[attr-defined]
            payload=payload,
        )
        if not created:
            # The provider already holds this key: an idempotent replay. The
            # original provider reference is returned; nothing is written twice.
            answer = AdapterWriteResponse(
                result_class=AdapterWriteResultClass.ACCEPTED,
                provider_ref=record.provider_ref,
            )
        else:
            # The side effect has happened, but the response to the caller is
            # lost. The honest answer is "I cannot tell you whether this was
            # accepted" -- not a fabricated success.
            answer = AdapterWriteResponse(
                result_class=AdapterWriteResultClass.AMBIGUOUS,
                error_code="simulated_lost_response_after_commit",
            )
        self.answers.append(answer)
        return answer


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


class DemoRuntime:
    def __init__(self, db_path: str) -> None:
        self.events: list[object] = []
        self.identity = IdentityRuntime(
            db_path,
            seed=identity_seed_from_credentials(dict(DEMO_USERS)),
            clock=clock,
        )
        self.integration_store = SqliteIntegrationStore(db_path)
        self.task_store = SqliteDataLayer(db_path)
        self.write_store = SqliteIntegrationWriteStore(db_path)
        self.integration_service = IntegrationService(
            self.integration_store,
            admin_checker=identity_admin_checker(self.identity),
            clock=clock,
        )
        self.core = AgentCore(
            AgentConfig(task_kinds=[TaskKind(id=APPROVAL_TASK_KIND)]),
            clock=clock,
            on_event=self.events.append,
        )
        write_policy = RoleAuthorizationPolicy(
            {
                role: (
                    PermissionRule(
                        resource_type=INTEGRATION_WRITE_RESOURCE_TYPE,
                        action=INTEGRATION_WRITE_ACTION,
                    ),
                    PermissionRule(
                        resource_type=INTEGRATION_WRITE_RESOURCE_TYPE,
                        action=INTEGRATION_DISPATCH_ACTION,
                    ),
                )
                for role in ("user", "approver", "admin")
            }
        )
        read_policy = RoleAuthorizationPolicy(
            {
                role: (
                    PermissionRule(
                        resource_type=INTEGRATION_WRITE_RESOURCE_TYPE,
                        action=INTEGRATION_READ_ACTION,
                    ),
                )
                for role in ("user", "approver", "admin")
            }
        )
        self.write_policy: AuthorizationPolicy = write_policy
        self.coordinator = ExternalWriteApprovalCoordinator(
            self.core,
            task_kind=APPROVAL_TASK_KIND,
            decision_authority=ApprovalDecisionAuthority(
                owner_fallback=non_system_owner_fallback,
                allowed_roles=("admin", "approver"),
            ),
            task_store=self.task_store,
            clock=clock,
        )
        self.admission = ExternalWriteAdmission(
            self.write_store,
            self.integration_service,
            authorization_policy=write_policy,
            approval_coordinator=self.coordinator,
            admin_checker=identity_admin_checker(self.identity),
            clock=clock,
        )
        self.fake = FakeBusinessSystem(order_id=ORDER_ID)
        self.adapter = DemoRefundAdapter(self.fake)
        self.dispatcher = ExternalWriteDispatcher(
            self.write_store,
            adapter=self.adapter,
            approval_coordinator=self.coordinator,
            authorization_policy=write_policy,
            clock=clock,
        )
        self.read_boundary = ExternalReadBoundary(
            self.integration_service,
            authorization_policy=read_policy,
            clock=clock,
            adapter=InProcessIntegrationAdapter(records={}),
        )
        self.observer = ExternalWriteObserver(
            self.write_store, read_boundary=self.read_boundary, clock=clock
        )

    def close(self) -> None:
        for resource in (self.write_store, self.integration_store, self.task_store):
            resource.close()
        self.identity.close()


# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------


def _print_audit(emit: Emitter, runtime: DemoRuntime) -> None:
    """Print the framework's audit trail, oldest first.

    Framework-generated identifiers are intentionally not printed: they are
    generated per run and printing them would couple the transcript to a
    particular run. Only stable facts (sequence, target kind, operation, actor,
    the resulting state) are shown.
    """

    rows = runtime.admission.list_audit(APPLICATION_ID, limit=100)
    emit.line("audit trail (framework write-store audit rows, oldest first):")
    facet_keys = {
        "external_write_profile": "profile_state",
        "external_write_command": "command_state",
        "external_write_attempt": "outcome",
        "external_write_observation": "freshness",
    }
    for row in reversed(rows):
        facet_key = facet_keys.get(row.target_type, "")
        facet = ""
        if facet_key and facet_key in row.after:
            facet = f" -> {facet_key}={row.after[facet_key]}"
        emit.line(
            f"  seq={row.seq:>3}  {row.target_type:<26} {row.operation:<34} "
            f"actor={row.actor_id}{facet}"
        )


def run_demo(interactive: bool, show_replay: bool) -> int:
    emit = Emitter(interactive=interactive)
    tmpdir = tempfile.mkdtemp(prefix="gaf-public-demo-")
    db_path = str(Path(tmpdir) / "demo.sqlite")
    runtime: DemoRuntime | None = None
    try:
        runtime = DemoRuntime(db_path)
        fake = runtime.fake

        emit.line("General Agent Framework -- public demo")
        emit.line("Deterministic, network-free, synthetic data only.")
        emit.blank()
        emit.line("Build AI agents that can safely act on real business systems.")
        emit.line("That is the claim this demo exercises, and this script shows")
        emit.line("both what the framework guarantees and what it refuses to claim.")

        # ---------------- S1 SCENARIO ----------------
        emit.stage("S1", "SCENARIO")
        emit.line("A buyer asks the agent to refund an order.")
        emit.line(f"  order            : {ORDER_ID}")
        emit.line(f"  refund amount    : CNY 100.00")
        emit.line(f"  local object type: {LOCAL_OBJECT_TYPE}")
        emit.line(f"  external type    : {EXTERNAL_OBJECT_TYPE} (creating a refund record)")
        emit.line("The order fixture is synthetic. No real payment provider, no")
        emit.line("network and no real customer data are involved.")
        emit.line("Note: the framework has no built-in 'refund' semantic; mapping a")
        emit.line("refund onto a (order -> refund, create) write is a demo modelling")
        emit.line("choice, declared through the framework's integration records.")
        emit.pause()

        # ---------------- S2 GOVERNANCE ----------------
        emit.stage("S2", "GOVERNANCE")
        emit.line("Before any write is even expressible, governance must be set up:")
        system = runtime.integration_service.register_system(
            "demo-admin",
            application_id=APPLICATION_ID,
            name=SYSTEM_NAME,
            system_kind=SYSTEM_KIND,
        )
        emit.line("  [ok] external system registered by the admin identity")
        runtime.integration_service.confirm_ownership(
            "demo-admin",
            application_id=APPLICATION_ID,
            system_id=system.system_id,
            local_object_type=LOCAL_OBJECT_TYPE,
            ownership_classification="external_authoritative",
            expected_version=0,
            reason="the external provider is the system of record for refunds",
        )
        emit.line("  [ok] ownership confirmed: external_authoritative")
        emit.line("       (only an explicitly confirmed, write-eligible ownership")
        emit.line("        classification can admit a write)")
        runtime.integration_service.create_mapping(
            "demo-admin",
            application_id=APPLICATION_ID,
            system_id=system.system_id,
            local_object_type=LOCAL_OBJECT_TYPE,
            external_object_type=EXTERNAL_OBJECT_TYPE,
        )
        emit.line("  [ok] mapping registered: order -> refund")
        profile = runtime.admission.confirm_write_profile(
            "demo-admin",
            application_id=APPLICATION_ID,
            external_system_id=system.system_id,
            external_object_type=EXTERNAL_OBJECT_TYPE,
            operation=OPERATION,
            honors_idempotency_key=True,
            repeat_safe=False,
            expected_version=0,
            reason="provider honours the idempotency key, but this create is not safe to repeat blindly",
        )
        emit.line("  [ok] write profile ACTIVE, admin-confirmed for this operation")
        emit.line(f"       honors_idempotency_key={profile.honors_idempotency_key} "
                  f"repeat_safe={profile.repeat_safe}")
        emit.line("The profile starts unconfirmed; only an explicit admin decision")
        emit.line("makes it ACTIVE. A missing or revoked profile admits nothing.")
        emit.pause()

        # ---------------- S3 ADMISSION ----------------
        emit.stage("S3", "ADMISSION")
        emit.line("The agent proposes the refund as a governed external write.")
        command = runtime.admission.admit_write(
            subject("demo-requester", "user"),
            application_id=APPLICATION_ID,
            external_system_id=system.system_id,
            local_object_type=LOCAL_OBJECT_TYPE,
            external_object_type=EXTERNAL_OBJECT_TYPE,
            external_object_id=ORDER_ID,
            operation=OPERATION,
            payload=dict(REFUND_PAYLOAD),
            idempotency_key=IDEMPOTENCY_KEY,
            reason="refund requested by the buyer",
        )
        emit.line(f"  idempotency key   : {command.idempotency_key}")
        emit.line(f"  command state     : {command.state.value}")
        emit.line(f"  approval binding  : present (sha256 over app scope, external system, object")
        emit.line("                      types, target object, operation and payload)")
        emit.line("                      value omitted: it embeds a per-run framework-generated")
        emit.line("                      external system id, so printing it would make the")
        emit.line("                      transcript depend on the run rather than on the logic.")
        emit.line(f"  payload digest    : {command.payload_digest}")
        emit.line("Teaching point: an external write command cannot even be")
        emit.line("constructed without an approval reference and an approval binding.")
        emit.line("An unapproved external write is not merely forbidden here -- it is")
        emit.line("inexpressible. There is also no 'requested -> ready' edge: the")
        emit.line("state machine has no such transition.")
        emit.pause()

        # ---------------- S4 WRITE BLOCKED BEFORE APPROVAL ----------------
        emit.stage("S4", "WRITE BLOCKED BEFORE APPROVAL")
        emit.line("Try to dispatch the write before it has been approved.")
        blocked_error = ""
        try:
            runtime.dispatcher.dispatch_command(
                subject("demo-requester", "user"),
                application_id=APPLICATION_ID,
                command_id=command.command_id,
            )
            blocked_error = "<unexpectedly allowed>"
        except IntegrationWriteDispatchError as exc:
            blocked_error = type(exc).__name__
        emit.line(f"  framework refused with: {blocked_error}")
        emit.line(f"  adapter sends so far  : {len(runtime.adapter.sends)}")
        emit.line(f"  fake refunds so far   : {fake.refund_count(ORDER_ID)}")
        assert len(runtime.adapter.sends) == 0, "a write must not reach the adapter before approval"
        assert fake.refund_count(ORDER_ID) == 0, "no refund may exist before approval"
        emit.line("The refusal is a real framework guard, not a prompt. Zero adapter")
        emit.line("sends happened and the authoritative ledger is still empty.")
        emit.pause()

        # ---------------- S5 DEMO HUMAN APPROVAL SIMULATION ----------------
        emit.stage("S5", "DEMO HUMAN APPROVAL SIMULATION")
        emit.line("DEMO HUMAN APPROVAL SIMULATION")
        emit.line("This is a scripted simulation. No human approves a real")
        emit.line("transaction anywhere in this demo.")
        emit.line("Segregation of duties applies: the approver identity is distinct")
        emit.line("from the requester identity, and the framework's approval authority")
        emit.line("enforces that.")
        declined = False
        if interactive:
            answer = ""
            try:
                answer = input("Simulate the approver approving this refund? [y/N] ").strip().lower()
            except EOFError:
                answer = ""
            declined = answer not in ("y", "yes")
        if declined:
            runtime.admission.reject_command(
                subject("demo-approver", "approver"),
                application_id=APPLICATION_ID,
                command_id=command.command_id,
                expected_version=command.version,
                reason="the simulated approver declined",
            )
            rejected = runtime.write_store.get_command(APPLICATION_ID, command.command_id)
            emit.line(f"  simulated approver declined -> command state: {rejected.state.value}")
            emit.line("The demo stops here. No refund was written.")
            return 0
        approved = runtime.admission.approve_command(
            subject("demo-approver", "approver"),
            application_id=APPLICATION_ID,
            command_id=command.command_id,
            expected_version=command.version,
            reason="refund reviewed by the simulated approver",
        )
        emit.line("  requester : demo-requester (role user)")
        emit.line("  approver  : demo-approver (role approver)")
        emit.line(f"  command state after approval: {approved.state.value}")
        emit.pause()

        # ---------------- S6 EXECUTION ----------------
        emit.stage("S6", "EXECUTION")
        emit.line("The approved command is dispatched once.")
        emit.line("The framework commits the attempt to durable storage BEFORE the")
        emit.line("external call, then makes the call outside any database transaction.")
        result = runtime.dispatcher.dispatch_command(
            subject("demo-approver", "approver"),
            application_id=APPLICATION_ID,
            command_id=approved.command_id,
        )
        adapter_answer = runtime.adapter.answers[0].result_class.value
        attempt_outcome = result.attempt.outcome_enum.value
        command_now = runtime.write_store.get_command(APPLICATION_ID, approved.command_id)
        emit.line(f"  adapter sends           : {len(runtime.adapter.sends)}")
        emit.line(f"  adapter answered        : {adapter_answer}")
        emit.line(f"  attempt outcome (read back from the framework attempt record): {attempt_outcome}")
        emit.line(f"  command state (read back from the framework command record)  : {command_now.state.value}")
        emit.line(f"  refunds in fake ledger  : {fake.refund_count(ORDER_ID)}")
        emit.line("The adapter applied the refund and then answered that it could not")
        emit.line("tell whether the provider had accepted it: a lost response after a")
        emit.line("committed write. The framework did not guess. It read the adapter's")
        emit.line("answer and derived the attempt outcome itself.")
        assert adapter_answer == "ambiguous"
        assert attempt_outcome == "unknown"
        emit.pause()

        # ---------------- S7 DANGER ----------------
        emit.stage("S7", "DANGER")
        emit.line("The tempting mistake: send the refund again to be sure.")
        refuses = ""
        try:
            runtime.dispatcher.dispatch_command(
                subject("demo-approver", "approver"),
                application_id=APPLICATION_ID,
                command_id=approved.command_id,
            )
            refuses = "<unexpectedly allowed>"
        except IntegrationWriteRedispatchRefusedError as exc:
            refuses = type(exc).__name__
        emit.line(f"  framework refused with: {refuses}")
        emit.line(f"  adapter sends now     : {len(runtime.adapter.sends)}")
        emit.line(f"  refunds in fake ledger: {fake.refund_count(ORDER_ID)}")
        assert len(runtime.adapter.sends) == 1, "a blind retry must not reach the adapter"
        assert fake.refund_count(ORDER_ID) == 1, "a blind retry must not create a second refund"
        emit.line("A command whose outcome the framework could not determine may only be")
        emit.line("redispatched when the ACTIVE profile for exactly this operation confirms")
        emit.line("both that the provider honours the same idempotency key and that the")
        emit.line("operation is safe to repeat. It currently does not, so the framework")
        emit.line("refuses. A blind retry here would have been how a customer gets")
        emit.line("refunded twice.")
        emit.pause()

        # ---------------- S8 RECONCILE ----------------
        emit.stage("S8", "RECONCILE")
        emit.line("Instead of retrying, look at the external system through the")
        emit.line("framework's governed read boundary and derive a verdict.")

        def observe_with_window(window_seconds: int):
            fake.declare_freshness_window(window_seconds)
            payload = fake.read_refund(ORDER_ID)
            runtime.read_boundary.bind_adapter(
                InProcessIntegrationAdapter(
                    records={
                        (system.system_id, EXTERNAL_OBJECT_TYPE, ORDER_ID): AdapterReadResponse(
                            application_id=APPLICATION_ID,
                            external_system_id=system.system_id,
                            external_object_type=EXTERNAL_OBJECT_TYPE,
                            external_object_id=ORDER_ID,
                            payload=dict(payload) if payload is not None else {},
                            source_version="v1",
                            ttl_seconds=fake.declared_freshness_window,
                        )
                    }
                )
            )
            return runtime.observer.observe(
                subject("demo-requester", "user"),
                application_id=APPLICATION_ID,
                command_id=approved.command_id,
            )

        emit.line("")
        emit.line("(i) the producer declares NO freshness window (ttl = 0)")
        observation_i = observe_with_window(0)
        cmd_for_reconcile = runtime.write_store.get_command(APPLICATION_ID, approved.command_id)
        outcome_i = derive_reconciliation(
            cmd_for_reconcile,
            runtime.write_store.list_observations(APPLICATION_ID, command_id=approved.command_id),
        )
        emit.line(f"  framework freshness outcome : {observation_i.freshness}")
        emit.line(f"  framework reconciliation    : {outcome_i.value}")
        emit.line("  We looked, and we cannot certify. The framework refuses to turn an")
        emit.line("  observation it cannot vouch for into a conclusion. It declines to")
        emit.line("  call the unknown outcome either a failure or a success.")
        assert observation_i.freshness == "unknown"
        assert outcome_i.value == "unobservable"

        emit.line("")
        emit.line("(ii) the producer declares a freshness window (ttl = 3600)")
        observation_ii = observe_with_window(3600)
        cmd_for_reconcile = runtime.write_store.get_command(APPLICATION_ID, approved.command_id)
        outcome_ii = derive_reconciliation(
            cmd_for_reconcile,
            runtime.write_store.list_observations(APPLICATION_ID, command_id=approved.command_id),
        )
        emit.line(f"  framework freshness outcome : {observation_ii.freshness}")
        emit.line(f"  framework reconciliation    : {outcome_ii.value}")
        emit.line("  We looked, and we can certify. The observed payload digest equals")
        emit.line("  the digest of the content that was approved.")
        assert observation_ii.freshness == "fresh"
        assert outcome_ii.value == "matched"
        emit.pause()

        # ---------------- S9 RESULT ----------------
        emit.stage("S9", "RESULT")
        final_command = runtime.write_store.get_command(APPLICATION_ID, approved.command_id)
        final_outcome = derive_reconciliation(
            final_command,
            runtime.write_store.list_observations(APPLICATION_ID, command_id=approved.command_id),
        )
        emit.line("Two separate axes, never merged:")
        emit.line(f"  command truth   (framework command state)     = {final_command.state.value}")
        emit.line(f"  external truth  (reconciliation verdict)      = {final_outcome.value} (derived)")
        emit.line(
            f"  authoritative refund ledger                   = "
            f"{fake.refund_count(ORDER_ID)} x {fake.refunded_total(ORDER_ID)} {REFUND_PAYLOAD['currency']}"
        )
        emit.line("")
        emit.line("The reconciliation verdict is DERIVED by a pure function over the")
        emit.line("command and the stored observations. It is not a stored field.")
        emit.line("Meanwhile the command truth printed above is exactly what the framework")
        emit.line("recorded -- it is neither success nor failure -- because the framework")
        emit.line("has no edge from an unknowable attempt outcome to a confirmed one for")
        emit.line("this lost-response case. We do not paper over that gap: the external")
        emit.line("world says the refund is there, and the framework honestly records that")
        emit.line("it never got a confirmation for this particular attempt.")
        assert final_command.state.value == "unknown"
        assert final_outcome.value == "matched"
        assert fake.refund_count(ORDER_ID) == 1
        assert fake.refunded_total(ORDER_ID) == 100
        emit.blank()
        _print_audit(emit, runtime)
        emit.blank()
        approval_task = runtime.task_store.get_task(approved.approval_ref)
        chain_ok = bool(approval_task is not None and approval_task.evidence.verify_chain())
        emit.line(f"approval task evidence chain verifies: {chain_ok}")
        assert chain_ok, "the approval evidence hash chain must verify"

        # ---------------- S9b OPTIONAL EXACTLY-ONCE ----------------
        if show_replay:
            emit.stage("S9b", "IDEMPOTENT REPLAY (exactly-once)")
            emit.line("Now the interesting question: what if a safe retry WERE allowed?")
            emit.line("An administrator updates the profile to declare this create safe")
            emit.line("to repeat against this provider, which honours the same key.")
            emit.line("(The framework refuses to silently mutate an ACTIVE profile, so the")
            emit.line("change is an explicit revoke followed by an explicit re-confirm;")
            emit.line("both are audited.)")
            revoked = runtime.admission.revoke_write_profile(
                "demo-admin",
                application_id=APPLICATION_ID,
                external_system_id=system.system_id,
                external_object_type=EXTERNAL_OBJECT_TYPE,
                operation=OPERATION,
                expected_version=profile.version,
                reason="reconsidering the repeat-safety assumption for this operation",
            )
            emit.line(f"  profile state after revoke: {revoked.state.value}")
            reconfirmed = runtime.admission.confirm_write_profile(
                "demo-admin",
                application_id=APPLICATION_ID,
                external_system_id=system.system_id,
                external_object_type=EXTERNAL_OBJECT_TYPE,
                operation=OPERATION,
                honors_idempotency_key=True,
                repeat_safe=True,
                expected_version=revoked.version,
                reason="provider confirms this create is idempotent for a repeated key",
            )
            emit.line(
                f"  profile re-confirmed: state={reconfirmed.state.value} "
                f"honors_idempotency_key={reconfirmed.honors_idempotency_key} "
                f"repeat_safe={reconfirmed.repeat_safe}"
            )
            replay = runtime.dispatcher.dispatch_command(
                subject("demo-approver", "approver"),
                application_id=APPLICATION_ID,
                command_id=approved.command_id,
            )
            answer_2 = runtime.adapter.answers[-1].result_class.value
            emit.line(f"  adapter sends          : {len(runtime.adapter.sends)}")
            emit.line(f"  adapter answered       : {answer_2}")
            emit.line(f"  attempt outcome        : {replay.attempt.outcome_enum.value}")
            emit.line(f"  command state          : "
                      f"{runtime.write_store.get_command(APPLICATION_ID, approved.command_id).state.value}")
            emit.line(f"  refunds in fake ledger : {fake.refund_count(ORDER_ID)}")
            emit.line(f"  refunded total         : "
                      f"{fake.refunded_total(ORDER_ID)} {REFUND_PAYLOAD['currency']}")
            emit.line("Two sends, ONE refund, and the same original provider reference.")
            emit.line("The framework never derives a new idempotency key on redispatch, so")
            emit.line("the key the provider sees is identical. This is exactly-once made")
            emit.line("empirical rather than promised.")
            assert len(runtime.adapter.sends) == 2
            assert fake.refund_count(ORDER_ID) == 1
            replay_record = fake.refund_records(ORDER_ID)[0]
            assert runtime.adapter.answers[-1].provider_ref == replay_record.provider_ref

        emit.blank()
        emit.line("Demo complete. Synthetic data only; no external system was contacted.")
        return 0
    finally:
        if runtime is not None:
            runtime.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    mode = os.environ.get("GAF_DEMO_MODE", "").strip().lower()
    if mode == "auto":
        interactive = False
    elif mode == "interactive":
        interactive = True
    else:
        interactive = sys.stdin.isatty()
    show_replay = os.environ.get("GAF_SHOW_IDEMPOTENT_REPLAY", "").strip() == "1"
    return run_demo(interactive=interactive, show_replay=show_replay)


if __name__ == "__main__":
    raise SystemExit(main())
