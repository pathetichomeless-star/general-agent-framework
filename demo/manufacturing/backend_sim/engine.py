"""PublicSimulatedBackend — a deterministic, in-process behaviour simulator.

WHAT THIS IS
The demo-owned backend that makes the Hongsheng Works manufacturing
application independently runnable: single process, SQLite, no network, no
external systems, synthetic data only. It implements the public
``framework_port.ManufacturingBackend`` protocol with small, readable
business semantics: authorisation rules, approval gating with segregation of
duties, governed external actions with an honest UNKNOWN command truth and a
separately derived external verdict, notifications with durable read state,
tasks and handoffs, and an append-only audit timeline with a demo-local
evidence chain for approval decisions.

WHAT THIS IS NOT
It is not the commercially licensed framework runtime, and it does not claim
to be. It is not a copy of any external implementation: everything here is
authored from the demo specification and public claims. It does not copy
private implementation logic, schemas or naming; where the governed behaviour
resembles the public documentation, that is because both follow the same
published, honest semantics (UNKNOWN stays UNKNOWN; "matched" is always a
derived external verdict, never a command success).

All public methods are thread-safe (single process, one lock).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from framework_port import constants as C
from framework_port import errors as E
from framework_port.dtos import (
    ActionResult,
    ApprovalPolicy,
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
)
from . import governed as G

_ID_PREFIX = {
    C.RECORD_CUSTOMER: "CUST",
    C.RECORD_PRODUCT: "PROD",
    C.RECORD_MATERIAL: "MAT",
    C.RECORD_PRICE_BOOK_ENTRY: "PB",
    C.RECORD_QUOTATION: "Q",
    C.RECORD_QUOTATION_LINE: "QL",
    C.RECORD_SALES_ORDER: "SO",
    C.RECORD_SALES_ORDER_LINE: "SOL",
    C.RECORD_PRODUCTION_ORDER: "PO",
    C.RECORD_MATERIAL_REQUIREMENT: "MR",
    C.RECORD_INVENTORY_ITEM: "INV",
    C.RECORD_INVENTORY_MOVEMENT: "MOV",
    C.RECORD_SHIPMENT: "SHIP",
    "approval": "APPR",
    "task": "TASK",
    "notification": "NTF",
    "message": "MSG",
    "conversation": "CNV",
    "governed": "GA",
    "handoff": "HO",
}

_NOTE_LABELS = {
    C.RECORD_QUOTATION: "报价单",
    C.RECORD_SALES_ORDER: "销售订单",
    C.RECORD_PRODUCTION_ORDER: "生产工单",
    C.RECORD_SHIPMENT: "发货单",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  actor_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL,
  locale TEXT NOT NULL DEFAULT 'zh', cred_salt TEXT NOT NULL, cred_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, actor_id TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
  record_type TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL,
  fields TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL,
  PRIMARY KEY (record_type, id)
);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
  requested_by TEXT NOT NULL, requested_at TEXT NOT NULL, justification TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'pending',
  decided_by TEXT DEFAULT '', decided_at TEXT DEFAULT '', decision_note TEXT DEFAULT '',
  resume_note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS evidence (
  approval_id TEXT NOT NULL, seq INTEGER NOT NULL, payload TEXT NOT NULL,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL, PRIMARY KEY (approval_id, seq)
);
CREATE TABLE IF NOT EXISTS governed_actions (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
  payload TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
  submitted_by TEXT NOT NULL, submitted_at TEXT NOT NULL, attempt_no INTEGER NOT NULL DEFAULT 0,
  attempt_outcome TEXT NOT NULL DEFAULT '', dispatched_at TEXT DEFAULT '', last_error TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, action_id TEXT NOT NULL, freshness TEXT NOT NULL,
  observed_payload TEXT NOT NULL, observed_digest TEXT NOT NULL, observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, assignee TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', due_at TEXT DEFAULT '', related_type TEXT DEFAULT '',
  related_id TEXT DEFAULT '', origin TEXT NOT NULL DEFAULT 'human', note TEXT DEFAULT '',
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS handoffs (
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL, from_actor TEXT NOT NULL, to_actor TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', reason TEXT DEFAULT '', note TEXT DEFAULT '',
  requested_at TEXT NOT NULL, decided_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, priority TEXT NOT NULL, title TEXT NOT NULL,
  body TEXT NOT NULL, related_type TEXT DEFAULT '', related_id TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notification_recipients (
  notification_id TEXT NOT NULL, recipient_id TEXT NOT NULL, read_state TEXT NOT NULL DEFAULT 'unread',
  read_at TEXT DEFAULT '', PRIMARY KEY (notification_id, recipient_id)
);
CREATE TABLE IF NOT EXISTS mail_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, recipient TEXT NOT NULL, subject TEXT NOT NULL,
  body TEXT NOT NULL, sent_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor_id TEXT NOT NULL,
  action TEXT NOT NULL, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
  parent_type TEXT DEFAULT '', parent_id TEXT DEFAULT '', detail TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_credential(salt: str, credential: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", credential.encode("utf-8"), salt.encode("utf-8"), 20000).hex()


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class PublicSimulatedBackend:
    """Deterministic demo backend implementing the public Facade protocol."""

    def __init__(self, config: BackendConfig) -> None:
        self._config = config
        self._clock: Callable[[], str] = config.clock or _utc_now
        self._lock = threading.RLock()
        self._db = sqlite3.connect(config.db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._db.commit()
        self._rules: dict[tuple[str, str, str], bool] = {}
        self._approval_policies: list[ApprovalPolicy] = []
        self._approver_roles: dict[str, tuple[str, ...]] = {}
        self._seed_counters()
        for user in config.bootstrap_users:
            self._provision_user(user)

    # ------------------------------------------------------------------ util
    def _now(self) -> str:
        return self._clock()

    def _seed_counters(self) -> None:
        cur = self._db.execute("SELECT key FROM meta WHERE key='counters'")
        if cur.fetchone() is None:
            self._db.execute(
                "INSERT INTO meta (key, value) VALUES ('counters', ?)",
                (_canonical({prefix: 0 for prefix in _ID_PREFIX.values()}),),
            )
            self._db.commit()

    def _next_id(self, record_type: str) -> str:
        prefix = _ID_PREFIX.get(record_type, "X")
        counters = json.loads(
            self._db.execute("SELECT value FROM meta WHERE key='counters'").fetchone()[0]
        )
        counters[prefix] = int(counters.get(prefix, 0)) + 1
        self._db.execute(
            "UPDATE meta SET value=? WHERE key='counters'", (_canonical(counters),)
        )
        return f"{prefix}-{counters[prefix]:04d}"

    def _audit(
        self,
        actor_id: str,
        action: str,
        subject: RecordRef,
        parent: RecordRef | None = None,
        detail: str = "",
    ) -> None:
        self._db.execute(
            "INSERT INTO audit (at, actor_id, action, subject_type, subject_id, parent_type,"
            " parent_id, detail) VALUES (?,?,?,?,?,?,?,?)",
            (
                self._now(),
                actor_id,
                action,
                subject.record_type,
                subject.record_id,
                parent.record_type if parent else "",
                parent.record_id if parent else "",
                detail,
            ),
        )

    def _evidence_append(self, approval_id: str, payload: Mapping[str, Any]) -> None:
        row = self._db.execute(
            "SELECT seq, hash FROM evidence WHERE approval_id=? ORDER BY seq DESC LIMIT 1",
            (approval_id,),
        ).fetchone()
        prev = row["hash"] if row else "GENESIS"
        seq = (row["seq"] + 1) if row else 1
        body = _canonical({"seq": seq, "payload": dict(payload)})
        digest = hashlib.sha256((prev + body).encode("utf-8")).hexdigest()
        self._db.execute(
            "INSERT INTO evidence (approval_id, seq, payload, prev_hash, hash) VALUES (?,?,?,?,?)",
            (approval_id, seq, body, prev, digest),
        )

    # ------------------------------------------------ lifecycle & capability
    def query_capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            mode=C.MODE_PUBLIC_SIMULATION,
            features={
                "live_llm": False,
                "agent_mode": "scripted_deterministic",
                "assistant_persistence": "demo_local",
                "realtime_push": False,
                "external_integration": "simulated_only",
            },
        )

    def configure_authorization(
        self,
        rules: tuple[RoleRule, ...],
        approval_policies: tuple[ApprovalPolicy, ...] = (),
        approver_roles: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        with self._lock:
            self._rules = {
                (r.role, r.permission, r.resource_type): bool(r.owner_scoped) for r in rules
            }
            self._approval_policies = list(approval_policies)
            self._approver_roles = {k: tuple(v) for k, v in (approver_roles or {}).items()}

    def close(self) -> None:
        with self._lock:
            self._db.commit()
            self._db.close()

    def _provision_user(self, user: Any) -> None:
        """Create a demo user if absent (bootstrap; demo-owned credentials)."""

        salt = secrets.token_hex(8)
        self._db.execute(
            "INSERT OR IGNORE INTO users (actor_id, display_name, role, locale, cred_salt,"
            " cred_hash) VALUES (?,?,?,?,?,?)",
            (user.actor_id, user.display_name, user.role, user.locale, salt,
             _hash_credential(salt, user.credential)),
        )
        self._db.commit()

    def _rollup_from_fields(self, record_type: str, fields: Mapping[str, Any]) -> RecordRef | None:
        """Order-centric roll-up: records that belong to a sales order audit
        into that order's timeline (demo aggregation rule, app-owned)."""

        order_id = fields.get("order_id")
        if order_id and record_type != C.RECORD_SALES_ORDER:
            return RecordRef(C.RECORD_SALES_ORDER, str(order_id))
        return None

    def _rollup_for_target(self, target: RecordRef) -> RecordRef | None:
        row = self._get_row(target.record_type, target.record_id)
        if row is None:
            return None
        return self._rollup_from_fields(target.record_type, json.loads(row["fields"]))

    # --------------------------------------------------------- authz helper
    def _check(self, actor: Principal, permission: str, record_type: str, record: Record | None = None) -> None:
        owner_scoped = self._rules.get((actor.role, permission, record_type))
        if owner_scoped is None:
            raise E.AuthorizationDenied(
                f"role '{actor.role}' may not {permission} {record_type}"
            )
        if owner_scoped and record is not None:
            fields = record.fields
            owner = str(fields.get("owner_id", fields.get("created_by", "")))
            if owner != actor.actor_id:
                raise E.AuthorizationDenied("record is outside your responsibility scope")

    def _get_row(self, record_type: str, record_id: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM records WHERE record_type=? AND id=?", (record_type, record_id)
        ).fetchone()

    def _row_to_record(self, row: sqlite3.Row) -> Record:
        return Record(
            ref=RecordRef(row["record_type"], row["id"], int(row["version"])),
            fields=json.loads(row["fields"]),
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
        )

    def _put_record(
        self,
        actor_id: str,
        record_type: str,
        record_id: str,
        fields: Mapping[str, Any],
        *,
        bump_version_from: int | None = None,
    ) -> Record:
        version = (bump_version_from + 1) if bump_version_from else 1
        now = self._now()
        self._db.execute(
            "INSERT INTO records (record_type, id, version, fields, updated_at, updated_by)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(record_type, id) DO UPDATE SET"
            " version=excluded.version, fields=excluded.fields, updated_at=excluded.updated_at,"
            " updated_by=excluded.updated_by",
            (record_type, record_id, version, _canonical(dict(fields)), now, actor_id),
        )
        return Record(RecordRef(record_type, record_id, version), dict(fields), now, actor_id)

    # ------------------------------------------------------------ identity
    def authenticate(self, username: str, credential: str) -> Principal | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM users WHERE actor_id=?", (username,)
            ).fetchone()
            if row is None:
                return None
            if _hash_credential(row["cred_salt"], credential) != row["cred_hash"]:
                return None
            return Principal(row["actor_id"], row["display_name"], row["role"], row["locale"])

    def create_session(self, principal: Principal) -> str:
        with self._lock:
            token = "sess-" + secrets.token_urlsafe(24)
            self._db.execute(
                "INSERT INTO sessions (token, actor_id, created_at) VALUES (?,?,?)",
                (token, principal.actor_id, self._now()),
            )
            self._db.commit()
            return token

    def resolve_session(self, token: str) -> Principal | None:
        with self._lock:
            row = self._db.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.actor_id=s.actor_id WHERE s.token=?",
                (token,),
            ).fetchone()
            if row is None:
                return None
            return Principal(row["actor_id"], row["display_name"], row["role"], row["locale"])

    def close_session(self, token: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE token=?", (token,))
            self._db.commit()

    def list_users(self, actor: Principal) -> list[UserView]:
        with self._lock:
            if actor.role != C.ROLE_ADMIN:
                raise E.AuthorizationDenied("user administration requires the administrator role")
            rows = self._db.execute("SELECT * FROM users ORDER BY actor_id").fetchall()
            return [
                UserView(r["actor_id"], r["display_name"], r["role"], r["locale"]) for r in rows
            ]

    def _principal_of(self, actor_id: str) -> Principal:
        row = self._db.execute("SELECT * FROM users WHERE actor_id=?", (actor_id,)).fetchone()
        if row is None:
            raise E.NotFound(f"unknown actor '{actor_id}'")
        return Principal(row["actor_id"], row["display_name"], row["role"], row["locale"])

    # ------------------------------------------------------------- records
    def list_records(
        self,
        actor: Principal,
        record_type: str,
        *,
        filters: Mapping[str, Any] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Record]:
        with self._lock:
            owner_scoped = self._rules.get((actor.role, C.PERM_VIEW, record_type))
            if owner_scoped is None:
                raise E.AuthorizationDenied(
                    f"role '{actor.role}' may not view {record_type}"
                )
            rows = self._db.execute(
                "SELECT * FROM records WHERE record_type=? ORDER BY id", (record_type,)
            ).fetchall()
            out: list[Record] = []
            for row in rows:
                rec = self._row_to_record(row)
                if owner_scoped:
                    owner = str(rec.fields.get("owner_id", rec.fields.get("created_by", "")))
                    if owner != actor.actor_id:
                        continue
                if filters:
                    if any(str(rec.fields.get(k, "")) != str(v) for k, v in filters.items()):
                        continue
                out.append(rec)
            return out[offset : offset + limit]

    def get_record(self, actor: Principal, ref: RecordRef) -> Record | None:
        with self._lock:
            row = self._get_row(ref.record_type, ref.record_id)
            if row is None:
                return None
            rec = self._row_to_record(row)
            self._check(actor, C.PERM_VIEW, ref.record_type, rec)
            return rec

    def create_record(
        self, actor: Principal, record_type: str, fields: Mapping[str, Any]
    ) -> Record:
        with self._lock:
            self._check(actor, C.PERM_CREATE, record_type)
            record_id = str(fields.get("id") or self._next_id(record_type))
            if self._get_row(record_type, record_id) is not None:
                raise E.DuplicateRequest(f"{record_type} '{record_id}' already exists")
            data = dict(fields)
            data.setdefault("owner_id", actor.actor_id)
            data.setdefault("state", "draft")
            rec = self._put_record(actor.actor_id, record_type, record_id, data)
            self._audit(actor.actor_id, f"{record_type}.create", rec.ref, detail="创建记录")
            self._db.commit()
            return rec

    def update_record(
        self,
        actor: Principal,
        ref: RecordRef,
        fields: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> Record:
        with self._lock:
            row = self._get_row(ref.record_type, ref.record_id)
            if row is None:
                raise E.NotFound(f"{ref.record_type} '{ref.record_id}' not found")
            rec = self._row_to_record(row)
            self._check(actor, C.PERM_EDIT, ref.record_type, rec)
            if int(row["version"]) != expected_version:
                raise E.VersionConflict(
                    f"expected version {expected_version}, current {row['version']}"
                )
            data = dict(rec.fields)
            data.update(fields)
            updated = self._put_record(
                actor.actor_id,
                ref.record_type,
                ref.record_id,
                data,
                bump_version_from=int(row["version"]),
            )
            self._audit(
                actor.actor_id,
                f"{ref.record_type}.update",
                updated.ref,
                detail="更新字段: " + ", ".join(sorted(fields.keys())),
            )
            self._db.commit()
            return updated

    # ---------------------------------------------------- business actions
    def execute_business_action(
        self,
        actor: Principal,
        ref: RecordRef,
        action: str,
        payload: Mapping[str, Any] | None = None,
    ) -> ActionResult:
        with self._lock:
            payload = dict(payload or {})
            from .actions import get_action
            spec = get_action(action)
            if spec.resource_type != ref.record_type:
                raise E.ValidationFailed(
                    f"action '{action}' applies to {spec.resource_type}, not {ref.record_type}"
                )
            if spec.roles and actor.role not in spec.roles:
                raise E.AuthorizationDenied(
                    f"role '{actor.role}' may not execute '{action}'"
                )
            row = self._get_row(ref.record_type, ref.record_id)
            if row is None:
                raise E.NotFound(f"{ref.record_type} '{ref.record_id}' not found")
            rec = self._row_to_record(row)
            self._check(actor, C.PERM_EXECUTE, ref.record_type, rec)
            state = str(rec.fields.get("state", ""))
            if spec.from_states and state not in spec.from_states:
                raise E.ValidationFailed(
                    f"action '{action}' is not allowed while the record is '{state}'"
                )
            policy = self._match_policy(action, {**rec.fields, **payload})
            if policy is not None:
                if spec.creates_child is not None:
                    # Child-record gate: the child record is created first and
                    # starts in the pending state; approval resumes it.
                    child = spec.creates_child(self, actor, rec, payload)
                    crow = self._get_row(child.ref.record_type, child.ref.record_id)
                    cfields = json.loads(crow["fields"])
                    cfields["state"] = spec.child_pending_state
                    self._put_record(
                        actor.actor_id, child.ref.record_type, child.ref.record_id,
                        cfields, bump_version_from=int(crow["version"]),
                    )
                    approval = self._create_approval(
                        actor, kind=action, target=child.ref, payload=dict(payload),
                        justification=str(payload.get("justification", "")),
                    )
                    self._audit(actor.actor_id, action, child.ref,
                                detail=f"需要审批 → {approval.approval_id}")
                    self._db.commit()
                    return ActionResult(child.ref, spec.child_pending_state,
                                        approval.approval_id, "已提交审批")
                approval = self._create_approval(
                    actor,
                    kind=action,
                    target=ref,
                    payload={**payload},
                    justification=str(payload.get("justification", "")),
                )
                new_fields = dict(rec.fields)
                new_fields["state"] = spec.pending_state
                updated = self._put_record(
                    actor.actor_id, ref.record_type, ref.record_id, new_fields,
                    bump_version_from=int(row["version"]),
                )
                self._audit(
                    actor.actor_id, action, updated.ref,
                    detail=f"需要审批 → {approval.approval_id}",
                )
                self._db.commit()
                return ActionResult(updated.ref, spec.pending_state, approval.approval_id,
                                    "已提交审批")
            try:
                return self._apply_action(actor, rec, row, spec, payload)
            except Exception:
                self._db.rollback()  # failed side effects must not leak state
                raise

    def _apply_action(self, actor: Principal, rec: Record, row: sqlite3.Row, spec, payload) -> ActionResult:
        """Apply an ungated action (or resume a gated one) and run side effects.

        Ungated child-creating actions (e.g. shipment request) simply create
        the child in its natural state; gating for child-record actions is
        decided by policy in ``execute_business_action``.
        """

        note_parts: list[str] = []
        child_ref: RecordRef | None = None
        if spec.creates_child is not None:
            child = spec.creates_child(self, actor, rec, payload)
            child_ref = child.ref
            note_parts.append(f"已生成 {_NOTE_LABELS.get(child.ref.record_type, child.ref.record_type)} "
                              f"{child.ref.record_id}")
            final_state = str(child.fields.get("state", spec.to_state))
        else:
            state = str(rec.fields.get("state", ""))
            final_state = spec.to_state or state
            fields = dict(rec.fields)
            if spec.to_state:
                fields["state"] = final_state
            if payload.get("fields_delta"):
                delta = payload["fields_delta"]
                if isinstance(delta, Mapping):
                    fields.update(delta)
            self._put_record(
                actor.actor_id, rec.ref.record_type, rec.ref.record_id, fields,
                bump_version_from=int(row["version"]),
            )
        if spec.side_effects is not None:
            extra = spec.side_effects(self, actor, rec, payload, child_ref)
            if extra:
                note_parts.append(extra)
        rollup = (rec.ref if child_ref is not None
                  else self._rollup_from_fields(rec.ref.record_type, rec.fields))
        self._audit(
            actor.actor_id, spec.action_id,
            child_ref or rec.ref, parent=rollup,
            detail="执行完成" + ("；" + "；".join(note_parts) if note_parts else ""),
        )
        self._db.commit()
        target_ref = child_ref or rec.ref
        state = final_state
        if child_ref is not None:
            child_row = self._get_row(child_ref.record_type, child_ref.record_id)
            state = str(json.loads(child_row["fields"]).get("state", state))
        return ActionResult(target_ref, state, None, "；".join(note_parts))

    def _match_policy(self, action: str, payload: Mapping[str, Any]) -> ApprovalPolicy | None:
        for policy in self._approval_policies:
            if policy.action == action and _eval_condition(policy.condition, payload):
                return policy
        return None

    # ----------------------------------------------------------- approvals
    def _create_approval(
        self,
        actor: Principal,
        *,
        kind: str,
        target: RecordRef,
        payload: Mapping[str, Any],
        justification: str,
    ) -> ApprovalView:
        approval_id = self._next_id("approval")
        now = self._now()
        self._db.execute(
            "INSERT INTO approvals (id, kind, target_type, target_id, requested_by, requested_at,"
            " justification, payload) VALUES (?,?,?,?,?,?,?,?)",
            (approval_id, kind, target.record_type, target.record_id,
             actor.actor_id, now, justification, _canonical(dict(payload))),
        )
        self._evidence_append(
            approval_id,
            {"event": "requested", "actor": actor.actor_id, "at": now,
             "kind": kind, "target": f"{target.record_type}:{target.record_id}",
             "justification": justification},
        )
        approvers = self._approver_roles.get(kind, ())
        self.notify(
            actor, "approval.requested", tuple(approvers),
            title=f"审批请求 {approval_id}",
            body=f"{kind} 由 {actor.display_name} 提交，等待审批。",
            priority=C.PRIORITY_CRITICAL, related=target,
        )
        return self.get_approval(actor, approval_id)  # type: ignore[return-value]

    def request_approval(
        self,
        actor: Principal,
        kind: str,
        target: RecordRef,
        payload: Mapping[str, Any],
        *,
        justification: str,
    ) -> ApprovalView:
        with self._lock:
            row = self._get_row(target.record_type, target.record_id)
            if row is None:
                raise E.NotFound(f"{target.record_type} '{target.record_id}' not found")
            rec = self._row_to_record(row)
            self._check(actor, C.PERM_VIEW, target.record_type, rec)
            if kind not in self._approver_roles:
                raise E.ValidationFailed(f"unknown approval kind '{kind}'")
            view = self._create_approval(actor, kind=kind, target=target,
                                         payload=dict(payload), justification=justification)
            self._db.commit()
            return view

    def _approval_view(self, row: sqlite3.Row) -> ApprovalView:
        target = RecordRef(row["target_type"], row["target_id"])
        return ApprovalView(
            approval_id=row["id"], kind=row["kind"], target=target,
            requested_by=row["requested_by"], requested_at=row["requested_at"],
            justification=row["justification"], status=row["status"],
            payload=json.loads(row["payload"]), decided_by=row["decided_by"],
            decided_at=row["decided_at"], decision_note=row["decision_note"],
        )

    def list_approvals(self, actor: Principal, *, pending_for_me: bool = True) -> list[ApprovalView]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM approvals ORDER BY requested_at DESC"
            ).fetchall()
            out = []
            for row in rows:
                view = self._approval_view(row)
                if pending_for_me and view.status != "pending":
                    continue
                if pending_for_me:
                    roles = self._approver_roles.get(view.kind, ())
                    if actor.role not in roles:
                        continue
                    if view.requested_by == actor.actor_id:
                        continue
                out.append(view)
            return out

    def get_approval(self, actor: Principal, approval_id: str) -> ApprovalView | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM approvals WHERE id=?", (approval_id,)
            ).fetchone()
            if row is None:
                return None
            view = self._approval_view(row)
            # Point lookup is scoped: the requester, an eligible approver role,
            # or owner/admin may read one approval; everyone else is denied
            # (the inbox list applies the same filter).
            allowed = (
                actor.role in (C.ROLE_OWNER, C.ROLE_ADMIN)
                or view.requested_by == actor.actor_id
                or actor.role in self._approver_roles.get(view.kind, ())
            )
            if not allowed:
                raise E.AuthorizationDenied("审批详情仅请求人或审批角色可见")
            return view

    def _decide(self, actor: Principal, approval_id: str, *, approve: bool, comment: str) -> ApprovalView:
        try:
            return self._decide_inner(actor, approval_id, approve=approve, comment=comment)
        except Exception:
            self._db.rollback()
            raise

    def _decide_inner(self, actor: Principal, approval_id: str, *, approve: bool, comment: str) -> ApprovalView:
        row = self._db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if row is None:
            raise E.NotFound(f"approval '{approval_id}' not found")
        if row["status"] != "pending":
            raise E.ValidationFailed(f"approval '{approval_id}' already decided")
        roles = self._approver_roles.get(row["kind"], ())
        if actor.role not in roles:
            raise E.AuthorizationDenied(
                f"role '{actor.role}' may not decide approval kind '{row['kind']}'"
            )
        if row["requested_by"] == actor.actor_id:
            raise E.AuthorizationDenied("请求者不能审批自己的请求（职责分离）")
        now = self._now()
        status = "approved" if approve else "rejected"
        self._db.execute(
            "UPDATE approvals SET status=?, decided_by=?, decided_at=?, decision_note=? WHERE id=?",
            (status, actor.actor_id, now, comment, approval_id),
        )
        self._evidence_append(
            approval_id,
            {"event": status, "actor": actor.actor_id, "at": now, "comment": comment},
        )
        view = self._approval_view(
            self._db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        )
        target = view.target
        requester = self._principal_of(row["requested_by"])
        self.notify(
            actor, "approval.decided", (requester.actor_id,),
            title=f"审批{'通过' if approve else '拒绝'} {approval_id}",
            body=f"{row['kind']}：{'通过' if approve else '拒绝'}。{comment}".strip(),
            priority=C.PRIORITY_NORMAL, related=target,
        )
        self._audit(actor.actor_id, f"approval.{status}", target,
                    detail=f"{approval_id} {row['kind']} {comment}".strip())
        if approve:
            self._resume_approved(view)
        self._db.commit()
        return view

    def _resume_approved(self, view: ApprovalView) -> None:
        """Auto-resume whatever the approval was gating."""

        from .actions import get_action, get_standalone_handler
        payload = dict(view.payload)
        payload.pop("_policy", None)
        if view.kind in BUSINESS_ACTION_SPECS:
            spec = get_action(view.kind)
            row = self._get_row(view.target.record_type, view.target.record_id)
            if row is None:
                return
            rec = self._row_to_record(row)
            actor = self._principal_of(view.decided_by)
            if spec.creates_child is not None:
                # child record already exists in pending state; finish it
                fields = dict(rec.fields)
                fields["state"] = spec.to_state
                self._put_record(actor.actor_id, rec.ref.record_type, rec.ref.record_id,
                                 fields, bump_version_from=int(row["version"]))
                if spec.side_effects is not None:
                    spec.side_effects(self, actor, rec, payload, rec.ref)
                self._audit(actor.actor_id, view.kind, rec.ref, detail="审批通过，自动继续执行")
            else:
                fields = dict(rec.fields)
                fields["state"] = spec.to_state
                if payload.get("fields_delta") and isinstance(payload["fields_delta"], Mapping):
                    fields.update(payload["fields_delta"])
                self._put_record(actor.actor_id, rec.ref.record_type, rec.ref.record_id,
                                 fields, bump_version_from=int(row["version"]))
                if spec.resume_side_effects is not None:
                    spec.resume_side_effects(self, actor, rec, payload)
                self._audit(actor.actor_id, view.kind, rec.ref, detail="审批通过，动作生效")
            return
        handler = get_standalone_handler(view.kind)
        if handler is not None:
            actor = self._principal_of(view.decided_by)
            handler(self, actor, view, payload)

    def approve(self, actor: Principal, approval_id: str, *, comment: str = "") -> ApprovalView:
        with self._lock:
            return self._decide(actor, approval_id, approve=True, comment=comment)

    def reject(self, actor: Principal, approval_id: str, *, comment: str = "") -> ApprovalView:
        with self._lock:
            view = self._decide(actor, approval_id, approve=False, comment=comment)
            # A rejected action returns its target to the pre-gate state when
            # the gate was in-place (the record currently shows the pending
            # state). For child-record gates the child stays visibly failed.
            row = self._get_row(view.target.record_type, view.target.record_id)
            if row is not None:
                from .actions import get_action
                if view.kind in BUSINESS_ACTION_SPECS:
                    spec = get_action(view.kind)
                    if spec.creates_child is None and spec.rejected_state:
                        fields = json.loads(row["fields"])
                        fields["state"] = spec.rejected_state
                        self._put_record(
                            view.decided_by or "system", view.target.record_type,
                            view.target.record_id, fields,
                            bump_version_from=int(row["version"]),
                        )
                    elif spec.creates_child is not None and spec.child_rejected_state:
                        fields = json.loads(row["fields"])
                        fields["state"] = spec.child_rejected_state
                        self._put_record(
                            view.decided_by or "system", view.target.record_type,
                            view.target.record_id, fields,
                            bump_version_from=int(row["version"]),
                        )
                    self._db.commit()
            return view

    # --------------------------------------------------- governed actions
    def submit_governed_action(
        self,
        actor: Principal,
        kind: str,
        target: RecordRef,
        payload: Mapping[str, Any],
        *,
        reason: str,
    ) -> GovernedActionView:
        with self._lock:
            if kind not in (C.GOVERNED_CARRIER_DISPATCH,):
                raise E.ValidationFailed(f"unknown governed action kind '{kind}'")
            row = self._get_row(target.record_type, target.record_id)
            if row is None:
                raise E.NotFound(f"{target.record_type} '{target.record_id}' not found")
            rec = self._row_to_record(row)
            self._check(actor, C.PERM_EXECUTE, target.record_type, rec)
            action_id = self._next_id("governed")
            now = self._now()
            self._db.execute(
                "INSERT INTO governed_actions (id, kind, target_type, target_id, payload, reason,"
                " state, submitted_by, submitted_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (action_id, kind, target.record_type, target.record_id,
                 _canonical(dict(payload)), reason, "approved", actor.actor_id, now),
            )
            self._audit(actor.actor_id, f"{kind}.submit", target,
                        parent=RecordRef("governed_action", action_id),
                        detail=f"治理外部动作已登记 {action_id}（审批绑定：{reason}）")
            self._db.commit()
            return self.get_governed_action(actor, action_id)  # type: ignore[return-value]

    def _governed_view(self, row: sqlite3.Row) -> GovernedActionView:
        return GovernedActionView(
            action_id=row["id"], kind=row["kind"],
            target=RecordRef(row["target_type"], row["target_id"]),
            reason=row["reason"], state=row["state"], submitted_by=row["submitted_by"],
            submitted_at=row["submitted_at"], attempt_no=int(row["attempt_no"]),
            attempt_outcome=row["attempt_outcome"], dispatched_at=row["dispatched_at"],
        )

    def get_governed_action(self, actor: Principal, action_id: str) -> GovernedActionView | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM governed_actions WHERE id=?", (action_id,)
            ).fetchone()
            return self._governed_view(row) if row else None

    def execute_governed_action(self, actor: Principal, action_id: str) -> GovernedActionView:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM governed_actions WHERE id=?", (action_id,)
            ).fetchone()
            if row is None:
                raise E.NotFound(f"governed action '{action_id}' not found")
            if row["state"] == "unknown":
                raise E.RetryRefused(
                    "命令真相为 UNKNOWN：框架拒绝盲目重试；请先对账"
                )
            if row["state"] in ("completed",):
                raise E.ValidationFailed("该动作已完成，不能重复执行")
            if row["state"] != "approved":
                raise E.ValidationFailed(f"cannot execute governed action in state '{row['state']}'")
            sim = self._config.external_systems.get(row["kind"])
            if sim is None:
                raise E.BackendUnavailable(f"no external system bound for kind '{row['kind']}'")
            attempt_no = int(row["attempt_no"]) + 1
            # Durable attempt record BEFORE the external call.
            self._db.execute(
                "UPDATE governed_actions SET attempt_no=?, state='dispatching', dispatched_at=?"
                " WHERE id=?",
                (attempt_no, self._now(), action_id),
            )
            self._db.commit()
            payload = json.loads(row["payload"])
            target = RecordRef(row["target_type"], row["target_id"])
            result = sim.apply(
                kind=row["kind"], command_id=action_id,
                idempotency_key=f"{action_id}:{attempt_no}",
                target=target, payload=payload,
            )
            outcome = {
                C.RESULT_ACCEPTED: "accepted",
                C.RESULT_AMBIGUOUS: G.OUTCOME_UNKNOWN,
                C.RESULT_REJECTED: "rejected",
            }[result.result_class]
            state = {"accepted": "completed", "unknown": "unknown", "rejected": "failed"}[outcome]
            self._db.execute(
                "UPDATE governed_actions SET attempt_outcome=?, state=? WHERE id=?",
                (outcome, state, action_id),
            )
            self._audit(
                actor.actor_id, f"{row['kind']}.execute", target,
                parent=self._rollup_for_target(target),
                detail=f"治理动作 {action_id} 第 {attempt_no} 次执行，命令真相={state}（诚实记录，不猜测）",
            )
            # Business projections move with the dispatch, but the audit
            # records that the command truth is unknown where applicable.
            if outcome == G.OUTCOME_UNKNOWN:
                self._project_shipment(target, "dispatched_unknown")
            elif outcome == "accepted":
                self._project_shipment(target, "dispatched")
            self._db.commit()
            return self.get_governed_action(actor, action_id)  # type: ignore[return-value]

    def _project_shipment(self, target: RecordRef, state: str) -> None:
        row = self._get_row(target.record_type, target.record_id)
        if row is None or target.record_type != C.RECORD_SHIPMENT:
            return
        fields = json.loads(row["fields"])
        fields["state"] = state
        self._put_record("system", target.record_type, target.record_id, fields,
                         bump_version_from=int(row["version"]))
        order_id = str(fields.get("order_id", ""))
        if order_id:
            orow = self._get_row(C.RECORD_SALES_ORDER, order_id)
            if orow is not None:
                ofields = json.loads(orow["fields"])
                ofields["state"] = "shipped" if "dispatched" in state else ofields["state"]
                self._put_record("system", C.RECORD_SALES_ORDER, order_id, ofields,
                                 bump_version_from=int(orow["version"]))

    def observe_external_action(self, actor: Principal, action_id: str) -> GovernedActionView:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM governed_actions WHERE id=?", (action_id,)
            ).fetchone()
            if row is None:
                raise E.NotFound(f"governed action '{action_id}' not found")
            sim = self._config.external_systems.get(row["kind"])
            if sim is None:
                raise E.BackendUnavailable(f"no external system bound for kind '{row['kind']}'")
            target = RecordRef(row["target_type"], row["target_id"])
            read = sim.read(kind=row["kind"], target=target)
            freshness = G.FRESHNESS_FRESH if read.freshness_ttl_seconds > 0 else G.FRESHNESS_UNKNOWN
            observed_payload = dict(read.payload) if read.payload is not None else {}
            self._db.execute(
                "INSERT INTO observations (action_id, freshness, observed_payload,"
                " observed_digest, observed_at) VALUES (?,?,?,?,?)",
                (action_id, freshness, _canonical(observed_payload),
                 G.canonical_digest(observed_payload) if observed_payload else "", self._now()),
            )
            self._audit(
                actor.actor_id, f"{row['kind']}.observe", target,
                parent=self._rollup_for_target(target),
                detail=f"治理读取外部系统：freshness={freshness}",
            )
            self._db.commit()
            return self.get_governed_action(actor, action_id)  # type: ignore[return-value]

    def reconcile_external_action(self, actor: Principal, action_id: str) -> ReconciliationResult:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM governed_actions WHERE id=?", (action_id,)
            ).fetchone()
            if row is None:
                raise E.NotFound(f"governed action '{action_id}' not found")
            # Reconciliation = one governed external read + a derived verdict.
            # ("We looked" comes before "we certify" — never the other way.)
            self.observe_external_action(actor, action_id)
            observations = [
                dict(r)
                for r in self._db.execute(
                    "SELECT * FROM observations WHERE action_id=? ORDER BY id", (action_id,)
                ).fetchall()
            ]
            payload = json.loads(row["payload"])
            verdict, freshness, note = G.derive_external_verdict(
                command_state=row["state"], observations=observations,
                approved_digest=G.canonical_digest(payload),
            )
            self._audit(
                actor.actor_id, f"{row['kind']}.reconcile",
                RecordRef(row["target_type"], row["target_id"]),
                parent=self._rollup_for_target(
                    RecordRef(row["target_type"], row["target_id"])),
                detail=f"治理动作 {action_id} 对账判定={verdict}；命令真相保持={row['state']}（两轴独立，永不合并）",
            )
            if verdict == G.VERDICT_MATCHED_DERIVED and row["state"] == "unknown":
                # Business projection only: the shipment/order records show the
                # reconciled business outcome, while the command record above
                # KEEPS its honest "unknown" state — the two axes are never
                # merged, and the command truth is never rewritten.
                srow = self._get_row(row["target_type"], row["target_id"])
                sfields = json.loads(srow["fields"]) if srow is not None else {}
                if sfields.get("state") != "reconciled_matched":
                    self._project_shipment(
                        RecordRef(row["target_type"], row["target_id"]),
                        "reconciled_matched",
                    )
            self._db.commit()
            final = self._db.execute(
                "SELECT state FROM governed_actions WHERE id=?", (action_id,)
            ).fetchone()
            return ReconciliationResult(
                action_id=action_id, command_truth=str(final["state"]),
                external_verdict=verdict, freshness=freshness, note=note,
            )

    # ---------------------------------------------------------------- tasks
    def list_tasks(
        self,
        actor: Principal,
        *,
        assignee: str | None = None,
        status: str | None = None,
    ) -> list[TaskView]:
        with self._lock:
            if assignee is None and actor.role not in (C.ROLE_OWNER, C.ROLE_FACTORY, C.ROLE_ADMIN):
                assignee = actor.actor_id
            sql = "SELECT * FROM tasks WHERE 1=1"
            params: list[Any] = []
            if assignee:
                sql += " AND assignee=?"
                params.append(assignee)
            if status:
                sql += " AND status=?"
                params.append(status)
            sql += " ORDER BY created_at DESC"
            return [self._task_view(r) for r in self._db.execute(sql, params).fetchall()]

    def _task_view(self, row: sqlite3.Row) -> TaskView:
        related = (
            RecordRef(row["related_type"], row["related_id"])
            if row["related_type"]
            else None
        )
        return TaskView(
            task_id=row["id"], kind=row["kind"], title=row["title"], assignee=row["assignee"],
            status=row["status"], due_at=row["due_at"], related=related, origin=row["origin"],
            note=row["note"],
        )

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
    ) -> TaskView:
        with self._lock:
            task_id = self._next_id("task")
            now = self._now()
            self._db.execute(
                "INSERT INTO tasks (id, kind, title, assignee, due_at, related_type, related_id,"
                " origin, note, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, kind, title, assignee, due_at or "",
                 related.record_type if related else "",
                 related.record_id if related else "", origin, note, actor.actor_id, now),
            )
            self._audit(actor.actor_id, "task.create",
                        RecordRef("task", task_id),
                        parent=related, detail=f"指派给 {assignee}：{title}")
            self.notify(
                actor, "task.assigned", (assignee,), title=f"新任务：{title}",
                body=f"{actor.display_name} 指派任务「{title}」",
                priority=C.PRIORITY_NORMAL, related=related,
            )
            self._db.commit()
            row = self._db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return self._task_view(row)

    def complete_task(self, actor: Principal, task_id: str, *, note: str = "") -> TaskView:
        with self._lock:
            row = self._db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise E.NotFound(f"task '{task_id}' not found")
            if row["assignee"] != actor.actor_id and actor.role not in (C.ROLE_ADMIN,):
                raise E.AuthorizationDenied("只能完成指派给自己的任务")
            self._db.execute(
                "UPDATE tasks SET status='done', completed_at=?, note=? WHERE id=?",
                (self._now(), note or row["note"], task_id),
            )
            self._audit(actor.actor_id, "task.complete", RecordRef("task", task_id),
                        detail=note)
            self._db.commit()
            return self._task_view(
                self._db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            )

    # -------------------------------------------------------------- handoff
    def request_handoff(
        self, actor: Principal, task_id: str, to_actor: str, *, reason: str
    ) -> HandoffView:
        with self._lock:
            row = self._db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise E.NotFound(f"task '{task_id}' not found")
            if row["assignee"] != actor.actor_id:
                raise E.AuthorizationDenied("只有当前责任人可以发起交接")
            if row["status"] != C.TASK_STATUS_OPEN:
                raise E.ValidationFailed("已完成的任务不能交接")
            handoff_id = self._next_id("handoff")
            self._db.execute(
                "INSERT INTO handoffs (id, task_id, from_actor, to_actor, reason, requested_at)"
                " VALUES (?,?,?,?,?,?)",
                (handoff_id, task_id, actor.actor_id, to_actor, reason, self._now()),
            )
            self.notify(
                actor, "handoff.requested", (to_actor,),
                title=f"交接请求：{row['title']}",
                body=f"{actor.display_name} 请求将任务交接给你。原因：{reason}",
                priority=C.PRIORITY_WARNING, related=RecordRef("task", task_id),
            )
            self._audit(actor.actor_id, "handoff.request", RecordRef("task", task_id),
                        detail=f"请求交接给 {to_actor}：{reason}（职责转移，权限不变）")
            self._db.commit()
            return self._handoff_view(
                self._db.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()
            )

    def _handoff_view(self, row: sqlite3.Row) -> HandoffView:
        return HandoffView(
            handoff_id=row["id"], task_id=row["task_id"], from_actor=row["from_actor"],
            to_actor=row["to_actor"], status=row["status"], reason=row["reason"],
            note=row["note"],
        )

    def respond_handoff(
        self, actor: Principal, handoff_id: str, accept: bool, *, note: str = ""
    ) -> HandoffView:
        with self._lock:
            row = self._db.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()
            if row is None:
                raise E.NotFound(f"handoff '{handoff_id}' not found")
            if row["to_actor"] != actor.actor_id:
                raise E.AuthorizationDenied("只有被指定的接收人可以响应交接")
            if row["status"] != "pending":
                raise E.ValidationFailed("该交接已处理")
            status = "accepted" if accept else "rejected"
            self._db.execute(
                "UPDATE handoffs SET status=?, note=?, decided_at=? WHERE id=?",
                (status, note, self._now(), handoff_id),
            )
            if accept:
                self._db.execute(
                    "UPDATE tasks SET assignee=? WHERE id=?", (actor.actor_id, row["task_id"])
                )
            self._audit(
                actor.actor_id, f"handoff.{status}", RecordRef("task", row["task_id"]),
                detail=("交接已接受，责任人变更为 " + actor.actor_id) if accept else "交接被拒绝",
            )
            self._db.commit()
            return self._handoff_view(
                self._db.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()
            )

    # -------------------------------------------------------- notifications
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
    ) -> None:
        with self._lock:
            if not recipients:
                return
            notification_id = self._next_id("notification")
            now = self._now()
            self._db.execute(
                "INSERT INTO notifications (id, kind, priority, title, body, related_type,"
                " related_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (notification_id, kind, priority, title, body,
                 related.record_type if related else "",
                 related.record_id if related else "", now),
            )
            for recipient in dict.fromkeys(recipients):
                # A recipient may be an actor id or a role name; role names
                # expand to every user currently holding that role.
                user_rows = self._db.execute(
                    "SELECT actor_id FROM users WHERE actor_id=? OR role=?",
                    (recipient, recipient),
                ).fetchall()
                targets = [r["actor_id"] for r in user_rows] or [recipient]
                for target_id in targets:
                    self._db.execute(
                        "INSERT OR IGNORE INTO notification_recipients (notification_id,"
                        " recipient_id) VALUES (?,?)",
                        (notification_id, target_id),
                    )
                    if priority == C.PRIORITY_CRITICAL:
                        user = self._db.execute(
                            "SELECT * FROM users WHERE actor_id=?", (target_id,)
                        ).fetchone()
                        if user is not None:
                            self._db.execute(
                                "INSERT INTO mail_outbox (recipient, subject, body, sent_at)"
                                " VALUES (?,?,?,?)",
                                (target_id, f"[模拟邮件] {title}", body, now),
                            )
            self._db.commit()

    def list_notifications(
        self, actor: Principal, *, unread_only: bool = False
    ) -> list[NotificationView]:
        with self._lock:
            sql = (
                "SELECT n.*, r.read_state FROM notifications n JOIN notification_recipients r"
                " ON r.notification_id=n.id WHERE r.recipient_id=?"
            )
            if unread_only:
                sql += " AND r.read_state='unread'"
            sql += " ORDER BY n.created_at DESC"
            out = []
            for row in self._db.execute(sql, (actor.actor_id,)).fetchall():
                related = (
                    RecordRef(row["related_type"], row["related_id"])
                    if row["related_type"]
                    else None
                )
                out.append(
                    NotificationView(
                        notification_id=row["id"], kind=row["kind"], priority=row["priority"],
                        title=row["title"], body=row["body"], created_at=row["created_at"],
                        read_state=row["read_state"], related=related,
                    )
                )
            return out

    def unread_count(self, actor: Principal) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n FROM notification_recipients WHERE recipient_id=?"
                " AND read_state='unread'",
                (actor.actor_id,),
            ).fetchone()
            return int(row["n"])

    def mark_notification_read(
        self, actor: Principal, notification_id: str, *, read: bool = True
    ) -> None:
        with self._lock:
            cur = self._db.execute(
                "UPDATE notification_recipients SET read_state=?, read_at=?"
                " WHERE notification_id=? AND recipient_id=?",
                ("read" if read else "unread", self._now() if read else "",
                 notification_id, actor.actor_id),
            )
            if cur.rowcount == 0:
                raise E.NotFound("notification not found for this recipient")
            self._db.commit()

    # ---------------------------------------------------------- messages
    def append_message(
        self, actor: Principal, conversation_id: str, role: str, text: str
    ) -> ConversationMessage:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if row is None:
                raise E.NotFound(f"conversation '{conversation_id}' not found")
            if row["actor_id"] != actor.actor_id:
                raise E.AuthorizationDenied("会话仅本人可见")
            message_id = self._next_id("message")
            now = self._now()
            self._db.execute(
                "INSERT INTO messages (id, conversation_id, role, text, created_at)"
                " VALUES (?,?,?,?,?)",
                (message_id, conversation_id, role, text, now),
            )
            self._db.commit()
            return ConversationMessage(message_id, conversation_id, role, text, now)

    def list_messages(self, actor: Principal, conversation_id: str) -> list[ConversationMessage]:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if row is None:
                raise E.NotFound(f"conversation '{conversation_id}' not found")
            if row["actor_id"] != actor.actor_id:
                raise E.AuthorizationDenied("会话仅本人可见")
            rows = self._db.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at, id",
                (conversation_id,),
            ).fetchall()
            return [
                ConversationMessage(r["id"], r["conversation_id"], r["role"], r["text"],
                                    r["created_at"])
                for r in rows
            ]

    def open_conversation(self, actor: Principal, title: str = "AI 助手") -> str:
        """Demo convenience: create (or reuse) the actor's assistant conversation."""

        with self._lock:
            row = self._db.execute(
                "SELECT id FROM conversations WHERE actor_id=? ORDER BY created_at LIMIT 1",
                (actor.actor_id,),
            ).fetchone()
            if row is not None:
                return str(row["id"])
            conversation_id = self._next_id("conversation")
            self._db.execute(
                "INSERT INTO conversations (id, actor_id, title, created_at) VALUES (?,?,?,?)",
                (conversation_id, actor.actor_id, title, self._now()),
            )
            self._db.commit()
            return conversation_id

    # ------------------------------------------------------ audit & evidence
    def get_audit_timeline(self, actor: Principal, subject: RecordRef) -> list[AuditEntry]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM audit WHERE (subject_type=? AND subject_id=?)"
                " OR (parent_type=? AND parent_id=?) ORDER BY seq",
                (subject.record_type, subject.record_id,
                 subject.record_type, subject.record_id),
            ).fetchall()
            if actor.role not in (C.ROLE_OWNER, C.ROLE_ADMIN):
                if not rows:
                    raise E.AuthorizationDenied("无权查看该对象的审计记录")
                owner_row = self._get_row(subject.record_type, subject.record_id)
                participated = any(r["actor_id"] == actor.actor_id for r in rows)
                owns = False
                if owner_row is not None:
                    fields = json.loads(owner_row["fields"])
                    owns = str(fields.get("owner_id", "")) == actor.actor_id
                if not (participated or owns):
                    raise E.AuthorizationDenied("仅可查看本人参与或负责的对象的审计记录")
            return [
                AuditEntry(
                    seq=int(r["seq"]), at=r["at"], actor_id=r["actor_id"], action=r["action"],
                    subject=RecordRef(r["subject_type"], r["subject_id"]),
                    parent=RecordRef(r["parent_type"], r["parent_id"])
                    if r["parent_type"] else None,
                    detail=r["detail"],
                )
                for r in rows
            ]

    def verify_evidence_chain(
        self, actor: Principal, subject: RecordRef
    ) -> EvidenceVerification:
        with self._lock:
            if subject.record_type != "approval":
                raise E.ValidationFailed(
                    "证据链验证仅适用于审批任务证据域（其余审计记录为保留可审计，不入链）"
                )
            rows = self._db.execute(
                "SELECT * FROM evidence WHERE approval_id=? ORDER BY seq",
                (subject.record_id,),
            ).fetchall()
            prev = "GENESIS"
            for r in rows:
                body = r["payload"]
                expected = hashlib.sha256((r["prev_hash"] + body).encode("utf-8")).hexdigest()
                if r["prev_hash"] != prev or r["hash"] != expected:
                    return EvidenceVerification(
                        scope="approval_task", subject=subject, verified=False,
                        entries_checked=len(rows),
                        note=f"chain broken at entry {r['seq']}",
                    )
                prev = r["hash"]
            return EvidenceVerification(
                scope="approval_task", subject=subject, verified=True,
                entries_checked=len(rows),
                note="demo-local approval evidence chain verifies" if rows else "no entries",
            )

    # ------------------------------------------------------------ mail sim
    def list_mail_outbox(self, actor: Principal) -> list[dict[str, str]]:
        with self._lock:
            if actor.role == C.ROLE_ADMIN:
                rows = self._db.execute(
                    "SELECT * FROM mail_outbox ORDER BY id DESC LIMIT 50"
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM mail_outbox WHERE recipient=? ORDER BY id DESC LIMIT 50",
                    (actor.actor_id,),
                ).fetchall()
            return [
                {"recipient": r["recipient"], "subject": r["subject"],
                 "body": r["body"], "sent_at": r["sent_at"]}
                for r in rows
            ]


from .actions import BUSINESS_ACTION_SPECS, get_action, get_standalone_handler  # noqa: E402


def _eval_condition(condition: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    op = str(condition.get("op", ""))
    if op == "always":
        return True
    if op == "any":
        return any(_eval_condition(c, payload) for c in condition.get("of", []))
    if op == "all":
        return all(_eval_condition(c, payload) for c in condition.get("of", []))
    field = str(condition.get("field", ""))
    target = condition.get("value")
    actual = payload.get(field)
    if actual is None:
        return False
    try:
        a, b = float(actual), float(target)
    except (TypeError, ValueError):
        a, b = str(actual), str(target)
    return {
        ">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b,
        "==": a == b, "!=": a != b,
    }[op]
