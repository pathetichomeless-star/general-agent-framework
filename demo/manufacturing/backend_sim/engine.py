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
from contextlib import contextmanager
from decimal import localcontext
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
from . import financial as F

# Public record edits cannot impersonate workflow or approval decisions.
_CONTROLLED_FIELDS = frozenset({
    "state", "status", "id", "owner_id", "version", "created_by", "created_at",
    "updated_by", "updated_at", "requested_by", "requested_at", "decided_by",
    "decided_at", "decision_note", "approval_binding", "_policy", "_production_binding",
})
_INITIAL_STATES = {
    C.RECORD_QUOTATION: "draft", C.RECORD_SALES_ORDER: "draft",
    C.RECORD_PRODUCTION_ORDER: "planned", C.RECORD_SHIPMENT: "requested",
    C.RECORD_MATERIAL_REQUIREMENT: "open",
}


def _validate_public_fields(
    fields: Mapping[str, Any], *, creating: bool = False, workflow: bool = True
) -> None:
    if not isinstance(fields, Mapping):
        raise E.ValidationFailed("fields must be a mapping")
    for name in fields:
        if not isinstance(name, str):
            raise E.ValidationFailed("field names must be strings")
        if creating and name in {"id", "owner_id", "state"}:
            continue
        if name == "state" and not workflow:
            continue  # master-data activation is not an approval decision
        if name in _CONTROLLED_FIELDS or name.startswith(("approval_", "approved_")):
            raise E.ValidationFailed(f"workflow-controlled field: {name}")


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
CREATE TABLE IF NOT EXISTS approval_bindings (
  approval_id TEXT PRIMARY KEY, binding TEXT NOT NULL
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


class _SeedWriter:
    """Short-lived fixture capability, bound only to an isolated staging DB."""

    def __init__(self, backend: PublicSimulatedBackend) -> None:
        self.__backend = backend
        self.__thread = threading.get_ident()
        self.__active = True

    def _close(self) -> None:
        self.__active = False

    def create_record(
        self, actor: Principal, record_type: str, fields: Mapping[str, Any]
    ) -> Record:
        if not self.__active or threading.get_ident() != self.__thread:
            raise E.AuthorizationDenied("fixture writer is outside its initialization scope")
        return self.__backend._create_record(actor, record_type, fields, historical=True)

    def __getattr__(self, name):
        if name not in {"list_records", "execute_business_action", "request_approval", "create_task"}:
            raise AttributeError(name)
        return getattr(self.__backend, name)


class PublicSimulatedBackend:
    """Deterministic demo backend implementing the public Facade protocol."""

    def __init__(self, config: BackendConfig) -> None:
        self._config = config
        self._clock: Callable[[], str] = config.clock or _utc_now
        self._lock = threading.RLock()
        self._approval_depth = 0
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

    def _commit_business(self) -> None:
        if not self._approval_depth:
            self._db.commit()

    @contextmanager
    def _approval_transaction(self):
        """Keep nested notifications/tasks inside the admission or decision."""
        outer = self._approval_depth == 0
        if outer:
            if self._db.in_transaction:
                raise E.ValidationFailed("approval requires a settled database")
            self._db.execute("BEGIN IMMEDIATE")
        self._approval_depth += 1
        try:
            yield
            if outer:
                self._db.commit()
        except Exception:
            if outer:
                self._db.rollback()
            raise
        finally:
            self._approval_depth -= 1

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

    def _initialize_demo_seed(
        self, loader: Callable[[_SeedWriter], dict], rules: tuple[RoleRule, ...],
        approval_policies: tuple[ApprovalPolicy, ...],
        approver_roles: Mapping[str, tuple[str, ...]],
    ) -> dict:
        """Trusted application bootstrap, never an actor-authorized operation.

        Business calls and policy changes serialize on the live lock. The
        fixture writer uses a separate database and separate authorization
        objects; neither its historical write capability nor its policies are
        installed on this backend. Failed staging is discarded in full.
        """
        with self._lock:
            if self._db.in_transaction:
                raise E.ValidationFailed("initialization requires a settled database")
            staged = PublicSimulatedBackend(BackendConfig(
                db_path=":memory:", clock=self._clock,
                application_id=self._config.application_id,
            ))
            writer = _SeedWriter(staged)
            try:
                self._db.backup(staged._db)
                staged.configure_authorization(rules, approval_policies, approver_roles)
                result = loader(writer)
                if result.get("seeded"):
                    staged._db.backup(self._db)
                return result
            finally:
                writer._close()
                staged.close()

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
        return self._create_record(actor, record_type, fields)

    def _create_record(
        self, actor: Principal, record_type: str, fields: Mapping[str, Any],
        *, historical: bool = False,
    ) -> Record:
        with self._lock, self._approval_transaction():
            self._check(actor, C.PERM_CREATE, record_type)
            _validate_public_fields(fields, creating=True)
            initial = _INITIAL_STATES.get(record_type, "draft")
            if (record_type in _INITIAL_STATES and fields.get("state", initial) != initial
                    and not historical):
                raise E.AuthorizationDenied("historical states require trusted initialization")
            data = dict(fields)
            if record_type == C.RECORD_PRODUCTION_ORDER and not historical:
                actor = self._approval_actor(actor)
                parent_id = data.get("order_id")
                if not isinstance(parent_id, str) or not parent_id:
                    raise E.ValidationFailed("production requires a sales order identity")
                spec, parent, _ = self._action_source(
                    actor, RecordRef(C.RECORD_SALES_ORDER, parent_id), C.ACTION_PRODUCTION_ORDER_CREATE)
                self._ensure_no_pending(parent, spec.action_id, {})
                if data.get("owner_id", actor.actor_id) != actor.actor_id:
                    raise E.AuthorizationDenied("production owner must be the requester")
                if data.get("progress_pct", 0) != 0:
                    raise E.ValidationFailed("new production must start at zero progress")
                payload = {k: v for k, v in data.items()
                           if k not in {"id", "owner_id", "state", "order_id", "progress_pct"}}
                values = self._validated_action_payload(spec.action_id, parent, payload)
                if self._match_policy(spec.action_id, values) is not None:
                    raise E.ValidationFailed("production requires approval through the business action")
                record_id = str(data.get("id") or self._next_id(record_type))
                if self._get_row(record_type, record_id) is not None:
                    raise E.DuplicateRequest(f"production_order '{record_id}' already exists")
                rec = spec.creates_child(self, actor, parent, payload, record_id=record_id)
                self._audit(actor.actor_id, f"{record_type}.create", rec.ref, detail="创建记录")
                return rec
            if record_type == C.RECORD_QUOTATION:
                data = self._quote_values(data)
            elif record_type == C.RECORD_SALES_ORDER:
                data = F.line_values(data)
                self._require_product(data["product_id"])
            elif record_type in (C.RECORD_QUOTATION_LINE, C.RECORD_SALES_ORDER_LINE):
                data = self._validate_new_line(actor, record_type, data, historical=historical)
            record_id = str(fields.get("id") or self._next_id(record_type))
            if self._get_row(record_type, record_id) is not None:
                raise E.DuplicateRequest(f"{record_type} '{record_id}' already exists")
            data.setdefault("owner_id", actor.actor_id)
            data.setdefault("state", initial)
            rec = self._put_record(actor.actor_id, record_type, record_id, data)
            self._audit(actor.actor_id, f"{record_type}.create", rec.ref, detail="创建记录")
            self._commit_business()
            return rec

    def update_record(
        self,
        actor: Principal,
        ref: RecordRef,
        fields: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> Record:
        with self._lock, self._approval_transaction():
            row = self._get_row(ref.record_type, ref.record_id)
            if row is None:
                raise E.NotFound(f"{ref.record_type} '{ref.record_id}' not found")
            rec = self._row_to_record(row)
            self._check(actor, C.PERM_EDIT, ref.record_type, rec)
            if isinstance(expected_version, bool) or not isinstance(expected_version, int):
                raise E.ValidationFailed("expected_version must be an integer")
            if int(row["version"]) != expected_version:
                raise E.VersionConflict(
                    f"expected version {expected_version}, current {row['version']}"
                )
            _validate_public_fields(fields, workflow=ref.record_type in _INITIAL_STATES)
            if ref.record_type in (C.RECORD_QUOTATION, C.RECORD_SALES_ORDER):
                if rec.fields.get("state") != "draft" and set(fields) - {"note"}:
                    raise E.ValidationFailed("submitted business content cannot be edited directly")
            if ref.record_type == C.RECORD_INVENTORY_ITEM and {"qty_on_hand", "item_ref"}.intersection(fields):
                raise E.ValidationFailed("inventory quantity and identity require a business operation")
            if ref.record_type == C.RECORD_PRODUCTION_ORDER and set(fields) - {"note", "due_date"}:
                raise E.ValidationFailed("production content and relationships require a business operation")
            data = dict(rec.fields)
            data.update(fields)
            if (ref.record_type in (C.RECORD_QUOTATION, C.RECORD_SALES_ORDER)
                    and rec.fields.get("state") == "draft"):
                # Check the old line before changing a draft; never repair divergent history.
                lines = self._document_lines(rec)
                if lines:
                    self._document_values(rec)
                if ref.record_type == C.RECORD_QUOTATION:
                    if {"qty", "discount_pct", "list_price", "product_id"}.intersection(fields):
                        for name in ("unit_price", "total_amount"):
                            if name not in fields:
                                data.pop(name, None)
                    elif "unit_price" in fields and "discount_pct" not in fields:
                        data.pop("discount_pct", None)
                    if "unit_price" in fields and "total_amount" not in fields:
                        data.pop("total_amount", None)
                    if "product_id" in fields and "list_price" not in fields:
                        data.pop("list_price", None)
                    data = self._quote_values(data)
                else:
                    if {"qty", "unit_price"}.intersection(fields) and "total_amount" not in fields:
                        data.pop("total_amount", None)
                    data = F.line_values(data)
                    self._require_product(data["product_id"])
            elif ref.record_type in (C.RECORD_QUOTATION_LINE, C.RECORD_SALES_ORDER_LINE):
                raise E.ValidationFailed("edit financial content through its draft document")
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
            if (ref.record_type in (C.RECORD_QUOTATION, C.RECORD_SALES_ORDER)
                    and rec.fields.get("state") == "draft"
                    and {"product_id", "product_name", "qty", "unit_price", "discount_pct", "list_price", "currency"}.intersection(fields)):
                self._sync_document_line(actor, updated)
            self._commit_business()
            return updated

    # ---------------------------------------------------- business actions
    def _require_product(self, product_id):
        if not isinstance(product_id, str) or not product_id:
            raise E.ValidationFailed("financial content requires a product_id")
        row = self._get_row(C.RECORD_PRODUCT, product_id)
        if row is None or self._row_to_record(row).fields.get("state") != "active":
            raise E.ValidationFailed("financial content requires an active product")
        return self._row_to_record(row)

    def _catalog(self, product_id, currency):
        product = self._require_product(product_id)
        records = (self._row_to_record(r) for r in self._db.execute(
            "SELECT * FROM records WHERE record_type=? ORDER BY id", (C.RECORD_PRICE_BOOK_ENTRY,)))
        entries = [rec for rec in records if rec.fields.get("product_id") == product_id
                   and rec.fields.get("currency") == currency and rec.fields.get("state") == "active"]
        if len(entries) != 1:
            raise E.ValidationFailed("quotation needs exactly one active currency-matched price-book entry")
        price = F.money(entries[0].fields.get("unit_price"), "catalog price")
        if price <= 0:
            raise E.ValidationFailed("catalog price must be positive")
        return price, [product, entries[0]]

    def _quote_values(self, fields):
        currency = fields.get("currency", "CNY")
        catalog, _ = self._catalog(fields.get("product_id"), currency)
        if "list_price" in fields and F.money(fields["list_price"], "list_price") != catalog:
            raise E.ValidationFailed("reference price disagrees with the authoritative price book")
        discount = None
        if "discount_pct" in fields:
            discount = F.number(fields["discount_pct"], "discount_pct")
            if not 0 <= discount <= 100:
                raise E.ValidationFailed("discount_pct must be between 0 and 100")
        with localcontext() as ctx:
            ctx.prec = 100
            if "unit_price" in fields:
                unit = F.money(fields["unit_price"], "unit_price")
                if discount is not None and unit != F.rounded(catalog * (1 - discount / 100)):
                    if not (discount == 0 and unit >= catalog):
                        raise E.ValidationFailed("selling price and declared discount disagree")
            elif discount is not None:
                unit = F.rounded(catalog * (1 - discount / 100))
            else:
                raise E.ValidationFailed("quotation requires a selling price or discount")
            effective = max(0, (catalog - unit) * 100 / catalog)
        data = F.line_values({**fields, "unit_price": F.json_number(unit)})
        data["list_price"] = F.json_number(catalog)
        # Declared percent is retained for display; policy uses the exact effective ratio.
        data["discount_pct"] = float(effective) if discount is None else F.json_number(discount)
        return data

    def _document_lines(self, rec):
        is_quote = rec.ref.record_type == C.RECORD_QUOTATION
        line_type = C.RECORD_QUOTATION_LINE if is_quote else C.RECORD_SALES_ORDER_LINE
        parent_key = "quotation_id" if is_quote else "order_id"
        records = (self._row_to_record(r) for r in self._db.execute(
            "SELECT * FROM records WHERE record_type=? ORDER BY id", (line_type,)))
        return [line for line in records if line.fields.get(parent_key) == rec.ref.record_id]

    def _document_values(self, rec):
        is_quote = rec.ref.record_type == C.RECORD_QUOTATION
        values = self._quote_values(rec.fields) if is_quote else F.line_values(rec.fields)
        product = self._require_product(values["product_id"])
        lines = self._document_lines(rec)
        # The existing UI/agent contract quotes one product and creates one L1.
        # Unspecified multi-line pricing is rejected, never guessed or reconciled.
        if len(lines) != 1:
            raise E.ValidationFailed("the single-product demo requires exactly one matching business line")
        line = F.line_values(lines[0].fields)
        for name in ("product_id", "qty", "unit_price", "total_amount", "currency"):
            if line[name] != values[name]:
                raise E.ValidationFailed("document header and business line disagree")
        dependencies = [product, lines[0]]
        if is_quote:
            catalog, catalog_records = self._catalog(values["product_id"], values["currency"])
            with localcontext() as ctx:
                ctx.prec = 100
                effective = max(0, (catalog - F.money(values["unit_price"], "unit_price")) * 100 / catalog)
            values["discount_pct"] = str(effective)
            dependencies = catalog_records + [lines[0]]
        # Totals come from the validated line, not a separately submitted header total.
        values["total_amount"] = line["total_amount"]
        values["_business_dependencies"] = [self._record_binding(r) for r in dependencies]
        return values

    def _validate_new_line(self, actor, line_type, fields, *, historical=False):
        is_quote = line_type == C.RECORD_QUOTATION_LINE
        parent_type = C.RECORD_QUOTATION if is_quote else C.RECORD_SALES_ORDER
        key = "quotation_id" if is_quote else "order_id"
        row = self._get_row(parent_type, str(fields.get(key, "")))
        if row is None:
            raise E.ValidationFailed("business line requires an existing parent")
        parent = self._row_to_record(row)
        self._check(actor, C.PERM_VIEW, parent_type, parent)
        self._check(actor, C.PERM_EDIT, parent_type, parent)
        if parent.fields.get("state") != "draft" and not historical:
            raise E.AuthorizationDenied("submitted business lines require trusted initialization")
        if self._document_lines(parent):
            raise E.ValidationFailed("the existing single-product document already has its business line")
        values = F.line_values(fields)
        header = F.line_values(parent.fields)
        for name in ("product_id", "qty", "unit_price", "total_amount", "currency"):
            if values[name] != header[name]:
                raise E.ValidationFailed("business line must match its document")
        values.pop("total_amount", None)  # derived on demand; existing line DTO shape
        return values

    def _sync_document_line(self, actor, rec):
        lines = self._document_lines(rec)
        if not lines:
            return  # draft may await its first validated line
        if len(lines) != 1:
            raise E.ValidationFailed("cannot synchronize an ambiguous multi-line document")
        line = lines[0]
        fields = dict(line.fields)
        for name in ("product_id", "product_name", "qty", "unit_price", "currency"):
            if name in rec.fields:
                fields[name] = rec.fields[name]
        if "total_amount" in fields:
            fields["total_amount"] = rec.fields["total_amount"]
        if fields != line.fields:
            self._put_record(actor.actor_id, line.ref.record_type, line.ref.record_id,
                             fields, bump_version_from=line.ref.version)

    def _inventory_adjustment(self, rec, payload):
        if set(payload) - {"adjust_qty", "adjust_amount", "adjust_pct", "justification"}:
            raise E.ValidationFailed("unsupported inventory adjustment input")
        delta = F.quantity(payload.get("adjust_qty"), "adjust_qty", signed=True)
        on_hand = F.number(rec.fields.get("qty_on_hand"), "qty_on_hand")
        if on_hand < 0 or on_hand + delta < 0:
            raise E.ValidationFailed("inventory adjustment would produce invalid stock")
        F.json_number(on_hand + delta)
        if on_hand == 0 and delta != 0:
            raise E.ValidationFailed("adjustment percentage is undefined for zero stock")
        with localcontext() as ctx:
            ctx.prec = 100
            pct = abs(delta) * 100 / on_hand if on_hand else F.number(0, "zero")
        if "adjust_pct" in payload and F.number(payload["adjust_pct"], "adjust_pct") != pct:
            raise E.ValidationFailed("client adjustment percentage disagrees with stored stock")
        if "adjust_amount" in payload:
            F.money(payload["adjust_amount"], "adjust_amount")
            raise E.ValidationFailed("no authoritative inventory valuation is configured")
        # Owner decision: no costs, client amounts or zero fallback. A configured
        # monetary predicate cannot be evaluated safely for this data model.
        def monetary(condition):
            return condition.get("field") == "adjust_amount" or any(
                monetary(c) for c in condition.get("of", []))
        if any(p.action == C.ACTION_INVENTORY_ADJUST and monetary(p.condition)
               for p in self._approval_policies):
            raise E.ValidationFailed("inventory monetary risk is unknown; adjustment blocked")
        return {**rec.fields, **payload, "adjust_qty": F.json_number(delta), "adjust_pct": str(pct)}

    def _production_decision(self, row):
        """Validate a completed decision as authority, never replay its effects."""
        try:
            binding, payload = self._approval_evidence_binding(row)
            if row["status"] not in ("approved", "rejected"):
                raise E.ValidationFailed("production cannot use an unresolved approval")
            policy, roles = self._policy_binding(row["kind"], binding["policy_data"])
            requester = self._principal_of(row["requested_by"])
            decider = self._principal_of(row["decided_by"])
            spec = get_action(row["kind"])
            if (policy != binding["policy"] or roles != binding["roles"]
                    or decider.role not in roles or decider.actor_id == requester.actor_id
                    or requester.role not in spec.roles):
                raise E.AuthorizationDenied("production approval authority is no longer valid")
            event_row = self._db.execute(
                "SELECT payload FROM evidence WHERE approval_id=? ORDER BY seq DESC LIMIT 1",
                (row["id"],)).fetchone()
            event = json.loads(event_row["payload"])["payload"]
            if (event.get("event"), event.get("actor"), event.get("at"), event.get("comment")) != (
                    row["status"], row["decided_by"], row["decided_at"], row["decision_note"]):
                raise E.ValidationFailed("production approval decision evidence is invalid")
            return binding, payload
        except (ValueError, KeyError, TypeError, AttributeError):
            raise E.ValidationFailed("malformed production approval evidence") from None

    def _production_parent(self, order, states):
        row = self._get_row(C.RECORD_SALES_ORDER, order.ref.record_id)
        if order.ref.record_type != C.RECORD_SALES_ORDER or row is None:
            raise E.ValidationFailed("production parent must be an existing sales order")
        live = self._row_to_record(row)
        if self._record_binding(live) != self._record_binding(order):
            raise E.VersionConflict("production parent has changed")
        if live.fields.get("state") not in states:
            raise E.ValidationFailed("sales order is not authorized for this production stage")
        data = self._document_values(live)
        confirmation_policy = self._match_policy(C.ACTION_SALES_ORDER_CONFIRM, data)
        has_confirmation_authority = confirmation_policy is None
        approvals = self._db.execute(
            "SELECT * FROM approvals WHERE target_type=? AND target_id=? AND kind IN (?,?) ORDER BY rowid",
            (C.RECORD_SALES_ORDER, live.ref.record_id, C.ACTION_SALES_ORDER_CONFIRM,
             C.ACTION_SALES_ORDER_REQUEST_CHANGE)).fetchall()
        latest = None
        for approval in approvals:
            binding, payload = self._production_decision(approval)
            source, target = binding["source"], binding["target"]
            spec = get_action(approval["kind"])
            if ((source["type"], source["id"]) != (C.RECORD_SALES_ORDER, live.ref.record_id)
                    or (target["type"], target["id"]) != (source["type"], source["id"])
                    or source["state"] not in spec.from_states):
                raise E.ValidationFailed("invalid production parent approval binding")
            pending = {**source["fields"], "state": spec.pending_state}
            if target["fields"] != pending or target["version"] != source["version"] + 1:
                raise E.ValidationFailed("invalid production parent pending transition")
            if approval["status"] == "approved":
                expected = {**target["fields"], **payload.get("fields_delta", {}), "state": spec.to_state}
                if approval["kind"] == C.ACTION_SALES_ORDER_REQUEST_CHANGE:
                    expected.update({k: binding["policy_data"][k] for k in
                                     ("product_id", "qty", "unit_price", "total_amount", "currency")})
                if (confirmation_policy is not None
                        and self._principal_of(approval["decided_by"]).role == confirmation_policy.approver_role
                        and all(binding["policy_data"].get(k) == data[k] for k in
                                ("product_id", "qty", "unit_price", "total_amount", "currency"))):
                    has_confirmation_authority = True
            else:
                # A rejected change preserves the original authorized order;
                # a rejected confirmation restores draft and cannot admit production.
                expected = {**target["fields"], "state": spec.rejected_state}
            latest = expected, target["version"] + 1
        if latest:
            expected, version = latest
            if expected["state"] != "confirmed" or live.ref.version < version:
                raise E.ValidationFailed("sales order approval has no valid completed effect")
            if {k: v for k, v in live.fields.items() if k not in {"state", "note"}} != {
                    k: v for k, v in expected.items() if k not in {"state", "note"}}:
                raise E.VersionConflict("sales order content differs from its last approval")
        if not has_confirmation_authority:
            raise E.AuthorizationDenied("sales order lacks the required authoritative confirmation decision")
        return live

    def _production_context(self, po, action):
        try:
            binding = po.fields["_production_binding"]
            snapshot = binding["parent"]
            if (snapshot["type"] != C.RECORD_SALES_ORDER
                    or snapshot["id"] != po.fields.get("order_id")
                    or binding["content"] != {k: po.fields.get(k) for k in
                                               ("product_id", "qty", "expedite", "substitute")}):
                raise E.ValidationFailed("production relationship or approved content has changed")
            parent = Record(RecordRef(snapshot["type"], snapshot["id"], snapshot["version"]), snapshot["fields"])
            states = ("confirmed",) if action == C.ACTION_PRODUCTION_ORDER_RELEASE else ("in_production",)
            self._production_parent(parent, states)
            self._ensure_no_pending(parent, C.ACTION_PRODUCTION_ORDER_CREATE, {})
            if self._document_values(parent)["_business_dependencies"] != binding["policy_data"]["_production_dependencies"]:
                raise E.VersionConflict("production parent business dependencies have changed")
            approvals = self._db.execute(
                "SELECT * FROM approvals WHERE target_type=? AND target_id=? AND kind=? ORDER BY rowid",
                (C.RECORD_PRODUCTION_ORDER, po.ref.record_id, C.ACTION_PRODUCTION_ORDER_CREATE)).fetchall()
            for row in approvals:
                evidence, _ = self._production_decision(row)
                initial = evidence["target"]["fields"].get("_production_binding", {})
                if (row["status"] != "approved"
                        or (evidence["target"]["type"], evidence["target"]["id"]) != (
                            C.RECORD_PRODUCTION_ORDER, po.ref.record_id)
                        or evidence["target"]["state"] != "pending_approval"
                        or evidence["source"]["type"] != C.RECORD_SALES_ORDER
                        or evidence["source"]["state"] != "confirmed"
                        or initial.get("parent") != evidence["source"]
                        or initial.get("content") != binding["content"]
                        or initial.get("policy_data") != binding["policy_data"]
                        or po.ref.version < evidence["target"]["version"] + 1
                        or evidence["source"]["id"] != po.fields["order_id"]
                        or evidence["policy_data"] != binding["policy_data"]):
                    raise E.ValidationFailed("production creation approval is not valid for this work order")
            current_data = {**binding["policy_data"], "due_date": po.fields.get("due_date", "")}
            if self._match_policy(C.ACTION_PRODUCTION_ORDER_CREATE, current_data) and not approvals:
                raise E.ValidationFailed("production has no required creation approval")
            if approvals and self._policy_binding(C.ACTION_PRODUCTION_ORDER_CREATE, current_data) != (
                    evidence["policy"], evidence["roles"]):
                raise E.AuthorizationDenied("production changes require a new policy decision")
            return parent
        except (ValueError, KeyError, TypeError, AttributeError):
            raise E.ValidationFailed("production has no valid trusted parent binding") from None

    def _advance_production_parent(self, actor, po, action, state):
        if not self._approval_depth:
            raise E.ValidationFailed("production side effects require a business transaction")
        actor = self._approval_actor(actor)
        spec = get_action(action)
        if actor.role not in spec.roles:
            raise E.AuthorizationDenied("production side effect no longer has action authority")
        row = self._get_row(po.ref.record_type, po.ref.record_id)
        if row is None:
            raise E.ValidationFailed("production work order disappeared before its side effect")
        live = self._row_to_record(row)
        self._check(actor, C.PERM_VIEW, live.ref.record_type, live)
        self._check(actor, C.PERM_EXECUTE, live.ref.record_type, live)
        if (live.ref.version != po.ref.version + 1 or
                live.fields.get("state") != spec.to_state or
                live.fields.get("_production_binding") != po.fields.get("_production_binding")
                or live.fields.get("order_id") != po.fields.get("order_id")):
            raise E.VersionConflict("production changed before its parent side effect")
        parent = self._production_context(live, action)
        self._check(actor, C.PERM_VIEW, parent.ref.record_type, parent)
        self._check(actor, C.PERM_EXECUTE, parent.ref.record_type, parent)
        fields = {**parent.fields, "state": state}
        updated = self._put_record(actor.actor_id, parent.ref.record_type, parent.ref.record_id,
                                   fields, bump_version_from=parent.ref.version)
        fields = dict(live.fields)
        fields["_production_binding"] = {**fields["_production_binding"], "parent": self._record_binding(updated)}
        self._put_record(actor.actor_id, live.ref.record_type, live.ref.record_id,
                         fields, bump_version_from=live.ref.version)

    def execute_business_action(
        self,
        actor: Principal,
        ref: RecordRef,
        action: str,
        payload: Mapping[str, Any] | None = None,
    ) -> ActionResult:
        with self._lock, self._approval_transaction():
            payload = self._approval_payload({} if payload is None else payload)
            actor = self._approval_actor(actor)
            spec, rec, row = self._action_source(actor, ref, action)
            if action == C.ACTION_PRODUCTION_ORDER_CREATE:
                self._ensure_no_pending(rec, action, payload)
            policy_data = self._validated_action_payload(action, rec, payload)
            policy = self._match_policy(action, policy_data)
            if policy is not None:
                view = self._admit_business_approval(
                    actor, spec, rec, payload, policy_data,
                    justification=str(payload.get("justification", "")),
                )
                target = self._row_to_record(self._get_row(view.target.record_type, view.target.record_id))
                return ActionResult(target.ref, str(target.fields.get("state", "")),
                                    view.approval_id, "已提交审批")
            return self._apply_action(actor, rec, row, spec, payload)

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
            if spec.action_id == C.ACTION_PRODUCTION_ORDER_REPORT_PROGRESS and "progress_pct" in payload:
                fields["progress_pct"] = payload["progress_pct"]
            if spec.action_id == C.ACTION_SALES_ORDER_REQUEST_CHANGE:
                values = self._validated_action_payload(spec.action_id, rec, payload)
                fields.update({name: values[name] for name in
                               ("product_id", "qty", "unit_price", "total_amount", "currency")})
            updated = self._put_record(
                actor.actor_id, rec.ref.record_type, rec.ref.record_id, fields,
                bump_version_from=int(row["version"]),
            )
            if spec.action_id == C.ACTION_SALES_ORDER_REQUEST_CHANGE:
                self._sync_document_line(actor, updated)
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
        self._commit_business()
        target_ref = child_ref or rec.ref
        if rec.ref.record_type == C.RECORD_PRODUCTION_ORDER:
            target_ref = self._row_to_record(self._get_row(rec.ref.record_type, rec.ref.record_id)).ref
        state = final_state
        if child_ref is not None:
            child_row = self._get_row(child_ref.record_type, child_ref.record_id)
            state = str(json.loads(child_row["fields"]).get("state", state))
        return ActionResult(target_ref, state, None, "；".join(note_parts))

    def _validated_action_payload(
        self, action: str, rec: Record, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        _validate_public_fields(payload)
        if "fields_delta" in payload:
            if not isinstance(payload["fields_delta"], Mapping):
                raise E.ValidationFailed("fields_delta must be a mapping")
            _validate_public_fields(payload["fields_delta"])
        if action in (C.ACTION_QUOTATION_SUBMIT, C.ACTION_QUOTATION_ACCEPT):
            if set(payload) - {"justification", "discount_pct"}:
                raise E.ValidationFailed("quotation action cannot override business fields")
            data = self._document_values(rec)
            if "discount_pct" in payload and F.number(payload["discount_pct"], "discount_pct") != F.number(rec.fields["discount_pct"], "discount_pct"):
                raise E.ValidationFailed("discount must match the stored quotation")
            return data
        if action == C.ACTION_SALES_ORDER_CONFIRM:
            if set(payload) - {"justification"}:
                raise E.ValidationFailed("order confirmation cannot override business fields")
            return self._document_values(rec)
        if action == C.ACTION_SALES_ORDER_REQUEST_CHANGE:
            if set(payload) - {"justification", "price_change", "fields_delta"}:
                raise E.ValidationFailed("unsupported order-change input")
            current = self._document_values(rec)
            delta = payload.get("fields_delta", {})
            financial = {"product_id", "qty", "unit_price", "total_amount", "currency"}
            if financial.intersection(delta) and payload.get("price_change") is not True:
                raise E.ValidationFailed("price changes require the price-change approval path")
            proposed = dict(rec.fields)
            proposed.update(delta)
            if {"qty", "unit_price"}.intersection(delta) and "total_amount" not in delta:
                proposed.pop("total_amount", None)
            proposed = F.line_values(proposed)
            self._require_product(proposed["product_id"])
            return {**proposed, **payload, "_business_dependencies": current["_business_dependencies"]}
        if action == C.ACTION_INVENTORY_ADJUST:
            return self._inventory_adjustment(rec, payload)
        if action == C.ACTION_INVENTORY_RECEIPT:
            if set(payload) - {"qty", "justification"}:
                raise E.ValidationFailed("unsupported inventory receipt input")
            qty = F.quantity(payload.get("qty"), "receipt quantity")
            return {**rec.fields, **payload, "qty": F.json_number(qty)}
        if action == C.ACTION_PRODUCTION_ORDER_CREATE:
            allowed = {"product_id", "product_name", "qty", "due_date", "expedite",
                       "substitute", "requirements", "justification"}
            if set(payload) - allowed:
                raise E.ValidationFailed("unsupported production creation input")
            if any(type(payload.get(k, False)) is not bool for k in ("expedite", "substitute")):
                raise E.ValidationFailed("production approval flags must be booleans")
            self._production_parent(rec, ("confirmed",))
            return {**rec.fields, **payload, "expedite": payload.get("expedite", False),
                    "substitute": payload.get("substitute", False),
                    "_production_dependencies": self._document_values(rec)["_business_dependencies"]}
        if rec.ref.record_type == C.RECORD_PRODUCTION_ORDER:
            delta = payload.get("fields_delta", {})
            allowed = {"progress_pct"} if action == C.ACTION_PRODUCTION_ORDER_REPORT_PROGRESS else set()
            if set(payload) - allowed - {"justification", "fields_delta"} or set(delta) - allowed:
                raise E.ValidationFailed("production action cannot replace business relationships or content")
            self._production_context(rec, action)
        return {**rec.fields, **payload}

    def _match_policy(self, action: str, payload: Mapping[str, Any]) -> ApprovalPolicy | None:
        for policy in self._approval_policies:
            if policy.action == action and _eval_condition(policy.condition, payload):
                return policy
        return None

    # ----------------------------------------------------------- approvals
    def _approval_actor(self, actor: Principal) -> Principal:
        trusted = self._principal_of(actor.actor_id)
        if trusted.role != actor.role:
            raise E.AuthorizationDenied("approval actor role does not match the current identity")
        return trusted

    @staticmethod
    def _approval_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        _validate_public_fields(payload)
        try:
            # Freeze nested inputs before validating, binding or persisting them.
            return json.loads(json.dumps(dict(payload), sort_keys=True, allow_nan=False))
        except (TypeError, ValueError):
            raise E.ValidationFailed("approval payload must be finite JSON data") from None

    def _action_source(self, actor: Principal, ref: RecordRef, action: str):
        spec = get_action(action)
        if spec.resource_type != ref.record_type:
            raise E.ValidationFailed("approval action does not apply to this object type")
        if spec.roles and actor.role not in spec.roles:
            raise E.AuthorizationDenied("requester may not perform this action")
        row = self._get_row(ref.record_type, ref.record_id)
        if row is None:
            raise E.NotFound("approval business object not found")
        rec = self._row_to_record(row)
        self._check(actor, C.PERM_VIEW, ref.record_type, rec)
        self._check(actor, C.PERM_EXECUTE, ref.record_type, rec)
        if isinstance(ref.version, bool) or not isinstance(ref.version, int) or ref.version < 0:
            raise E.ValidationFailed("invalid business object version")
        if ref.version and ref.version != rec.ref.version:
            raise E.VersionConflict("approval source version has changed")
        if spec.from_states and rec.fields.get("state") not in spec.from_states:
            raise E.ValidationFailed("action is not allowed in the source workflow state")
        return spec, rec, row

    @staticmethod
    def _record_binding(rec: Record) -> dict[str, Any]:
        return {"type": rec.ref.record_type, "id": rec.ref.record_id,
                "version": rec.ref.version, "state": rec.fields.get("state", ""),
                "fields": dict(rec.fields)}

    def _policy_binding(self, kind: str, policy_data: Mapping[str, Any]):
        configured = self._approver_roles.get(kind, ())
        policy = self._match_policy(kind, policy_data)
        roles = (policy.approver_role,) if policy else tuple(configured)
        if not roles or any(role not in configured for role in roles):
            raise E.AuthorizationDenied("no eligible approver for the matched policy")
        bound_policy = None if policy is None else {
            "action": policy.action, "condition": dict(policy.condition),
            "approver_role": policy.approver_role,
            "justification_label": policy.justification_label,
        }
        return bound_policy, list(roles)

    def _ensure_no_pending(self, source: Record, kind: str, payload: Mapping[str, Any]) -> None:
        rows = self._db.execute(
            "SELECT a.*, b.binding FROM approvals a LEFT JOIN approval_bindings b"
            " ON b.approval_id=a.id WHERE a.status='pending' AND a.kind=?", (kind,),
        ).fetchall()
        for row in rows:
            same = (row["target_type"], row["target_id"]) == (source.ref.record_type, source.ref.record_id)
            if row["binding"]:
                try:
                    origin = json.loads(row["binding"])["source"]
                    same = same or (origin["type"], origin["id"]) == (source.ref.record_type, source.ref.record_id)
                except (ValueError, KeyError, TypeError):
                    raise E.ValidationFailed("malformed pending approval binding") from None
            if same:
                # Independent material purchases may share an order; competing
                # requests for the same material are still refused.
                if kind == C.APPROVAL_EXPEDITE_PURCHASE:
                    previous = json.loads(row["payload"])
                    if previous.get("material_id") != payload.get("material_id"):
                        continue
                raise E.DuplicateRequest("a pending approval already binds this operation")

    def _admit_business_approval(self, actor, spec, source, payload, policy_data, *, justification):
        if spec.creates_child is not None and spec.action_id != C.ACTION_PRODUCTION_ORDER_CREATE:
            raise E.ValidationFailed("action has no child approval contract")
        if spec.creates_child is None and not (spec.pending_state or spec.action_id == C.ACTION_INVENTORY_ADJUST):
            raise E.ValidationFailed("action has no approval lifecycle contract")
        self._policy_binding(spec.action_id, policy_data)
        self._ensure_no_pending(source, spec.action_id, payload)
        target = source
        if spec.creates_child is not None:
            child = spec.creates_child(self, actor, source, payload)
            fields = dict(child.fields)
            fields["state"] = spec.child_pending_state
            target = self._put_record(actor.actor_id, child.ref.record_type, child.ref.record_id,
                                      fields, bump_version_from=child.ref.version)
        elif spec.pending_state:
            fields = dict(source.fields)
            fields["state"] = spec.pending_state
            target = self._put_record(actor.actor_id, source.ref.record_type, source.ref.record_id,
                                      fields, bump_version_from=source.ref.version)
        view = self._create_approval(actor, kind=spec.action_id, source=source, target=target,
                                     payload=payload, policy_data=policy_data, justification=justification)
        self._audit(actor.actor_id, spec.action_id, target.ref,
                    detail=f"需要审批 → {view.approval_id}")
        return view

    def _create_approval(
        self, actor: Principal, *, kind: str, source: Record, target: Record,
        payload: Mapping[str, Any], policy_data: Mapping[str, Any], justification: str,
    ) -> ApprovalView:
        policy, roles = self._policy_binding(kind, policy_data)
        approval_id = self._next_id("approval")
        now = self._now()
        binding = {"schema": 1, "id": approval_id, "kind": kind,
                   "requested_by": actor.actor_id, "requested_at": now,
                   "justification": justification,
                   "source": self._record_binding(source), "target": self._record_binding(target),
                   "payload": dict(payload), "policy_data": dict(policy_data),
                   "policy": policy, "roles": roles}
        encoded = _canonical(binding)
        self._db.execute(
            "INSERT INTO approvals (id, kind, target_type, target_id, requested_by, requested_at,"
            " justification, payload) VALUES (?,?,?,?,?,?,?,?)",
            (approval_id, kind, target.ref.record_type, target.ref.record_id,
             actor.actor_id, now, justification, _canonical(dict(payload))),
        )
        self._db.execute("INSERT INTO approval_bindings (approval_id, binding) VALUES (?,?)",
                         (approval_id, encoded))
        self._evidence_append(
            approval_id, {"event": "requested", "actor": actor.actor_id, "at": now,
                          "kind": kind, "target": f"{target.ref.record_type}:{target.ref.record_id}",
                          "justification": justification,
                          "binding_digest": hashlib.sha256(encoded.encode("utf-8")).hexdigest()},
        )
        self.notify(actor, "approval.requested", tuple(roles),
                    title=f"审批请求 {approval_id}",
                    body=f"{kind} 由 {actor.display_name} 提交，等待审批。",
                    priority=C.PRIORITY_CRITICAL, related=target.ref)
        return self._approval_view(self._db.execute(
            "SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone())

    def _purchase_source(self, actor, ref):
        if ref.record_type != C.RECORD_SALES_ORDER:
            raise E.ValidationFailed("purchase approval requires a sales order")
        if actor.role not in (C.ROLE_SALES, C.ROLE_FACTORY):
            raise E.AuthorizationDenied("requester may not request a purchase")
        row = self._get_row(ref.record_type, ref.record_id)
        if row is None:
            raise E.NotFound("purchase order not found")
        rec = self._row_to_record(row)
        self._check(actor, C.PERM_VIEW, ref.record_type, rec)
        self._check(actor, C.PERM_EXECUTE, ref.record_type, rec)
        if isinstance(ref.version, bool) or not isinstance(ref.version, int) or ref.version < 0:
            raise E.ValidationFailed("invalid purchase source version")
        if ref.version and ref.version != rec.ref.version:
            raise E.VersionConflict("purchase source has changed")
        if rec.fields.get("state") not in ("confirmed", "in_production", "ready_to_ship"):
            raise E.ValidationFailed("purchase approval is not allowed in this state")
        return rec

    def request_approval(
        self, actor: Principal, kind: str, target: RecordRef, payload: Mapping[str, Any],
        *, justification: str,
    ) -> ApprovalView:
        with self._lock, self._approval_transaction():
            actor = self._approval_actor(actor)
            payload = self._approval_payload(payload)
            if kind in BUSINESS_ACTION_SPECS:
                spec, rec, _ = self._action_source(actor, target, kind)
                policy_data = self._validated_action_payload(kind, rec, payload)
                return self._admit_business_approval(actor, spec, rec, payload, policy_data,
                                                     justification=justification)
            if kind != C.APPROVAL_EXPEDITE_PURCHASE:
                raise E.ValidationFailed("unsupported approval operation")
            rec = self._purchase_source(actor, target)
            policy_data = self._validated_action_payload(kind, rec, payload)
            self._ensure_no_pending(rec, kind, payload)
            return self._create_approval(actor, kind=kind, source=rec, target=rec,
                                         payload=payload, policy_data=policy_data,
                                         justification=justification)

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
                    roles = self._actionable_approval_roles(row)
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
                or actor.role in self._actionable_approval_roles(row)
            )
            if not allowed:
                raise E.AuthorizationDenied("审批详情仅请求人或审批角色可见")
            return view

    def _validate_approval_binding(self, row: sqlite3.Row):
        """Validate immutable evidence, live objects and current authority."""
        try:
            return self._validate_approval_binding_inner(row)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise E.ValidationFailed("malformed approval binding or evidence") from None

    def _approval_evidence_binding(self, row: sqlite3.Row):
        """Read immutable approval evidence without requiring a still-pending target."""
        stored = self._db.execute("SELECT binding FROM approval_bindings WHERE approval_id=?",
                                  (row["id"],)).fetchone()
        if stored is None:
            raise E.ValidationFailed("approval has no trusted binding; submit a new request")
        try:
            binding = json.loads(stored["binding"])
            if type(binding["schema"]) is not int or binding["schema"] != 1:
                raise ValueError()
            for key in ("id", "kind", "requested_by", "requested_at", "justification"):
                if binding[key] != row[key]:
                    raise ValueError()
            payload = self._approval_payload(json.loads(row["payload"]))
            if _canonical(payload) != _canonical(binding["payload"]):
                raise ValueError()
            source, target = binding["source"], binding["target"]
            for snapshot in (source, target):
                if (isinstance(snapshot["version"], bool) or not isinstance(snapshot["version"], int)
                        or snapshot["version"] <= 0 or not isinstance(snapshot["fields"], dict)
                        or not isinstance(snapshot["type"], str) or not snapshot["type"]
                        or not isinstance(snapshot["id"], str) or not snapshot["id"]
                        or snapshot["state"] != snapshot["fields"].get("state", "")):
                    raise ValueError()
            if (target["type"], target["id"]) != (row["target_type"], row["target_id"]):
                raise ValueError()
            first = self._db.execute(
                "SELECT payload FROM evidence WHERE approval_id=? AND seq=1", (row["id"],),
            ).fetchone()
            event = json.loads(first["payload"])["payload"] if first else {}
            if (event.get("event") != "requested" or event.get("binding_digest") !=
                    hashlib.sha256(stored["binding"].encode("utf-8")).hexdigest()):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise E.ValidationFailed("approval payload, target or binding was substituted") from None
        chain = self.verify_evidence_chain(self._principal_of(row["requested_by"]),
                                           RecordRef("approval", row["id"]))
        if not chain.verified:
            raise E.ValidationFailed("approval evidence is invalid")
        return binding, payload

    def _validate_approval_binding_inner(self, row: sqlite3.Row):
        binding, payload = self._approval_evidence_binding(row)
        source, target = binding["source"], binding["target"]
        requester = self._principal_of(row["requested_by"])
        origin = Record(RecordRef(source["type"], source["id"], source["version"]), source["fields"])
        live_row = self._get_row(target["type"], target["id"])
        if live_row is None:
            raise E.ValidationFailed("bound approval target no longer exists")
        live = self._row_to_record(live_row)
        if live.ref.version != target["version"]:
            raise E.VersionConflict("approval target version has changed")
        if self._record_binding(live) != target:
            raise E.ValidationFailed("approval target no longer has the bound content or state")
        if row["kind"] in BUSINESS_ACTION_SPECS:
            spec = get_action(row["kind"])
            if source["type"] != spec.resource_type or (spec.from_states and source["state"] not in spec.from_states):
                raise E.ValidationFailed("invalid approval source/action binding")
            if spec.roles and requester.role not in spec.roles:
                raise E.AuthorizationDenied("requester no longer has action authority")
            self._check(requester, C.PERM_VIEW, source["type"], origin)
            self._check(requester, C.PERM_EXECUTE, source["type"], origin)
            if spec.creates_child is not None:
                if (spec.action_id != C.ACTION_PRODUCTION_ORDER_CREATE
                        or target["type"] != C.RECORD_PRODUCTION_ORDER
                        or target["state"] != spec.child_pending_state
                        or target["fields"].get("order_id") != source["id"]):
                    raise E.ValidationFailed("invalid child approval binding")
                parent_row = self._get_row(source["type"], source["id"])
                if parent_row is None or self._record_binding(self._row_to_record(parent_row)) != source:
                    raise E.VersionConflict("approval parent has changed")
            else:
                if (target["type"], target["id"]) != (source["type"], source["id"]):
                    raise E.ValidationFailed("in-place approval target differs from its source")
                expected = dict(source["fields"])
                if spec.pending_state:
                    expected["state"] = spec.pending_state
                if target["fields"] != expected:
                    raise E.ValidationFailed("approval is not in the expected pending state")
                if not (spec.pending_state or spec.action_id == C.ACTION_INVENTORY_ADJUST):
                    raise E.ValidationFailed("unsupported approval lifecycle")
        elif row["kind"] == C.APPROVAL_EXPEDITE_PURCHASE:
            self._purchase_source(requester, origin.ref)
            if source != target:
                raise E.ValidationFailed("purchase approval target differs from its source")
        else:
            raise E.ValidationFailed("unsupported bound approval kind")
        data = self._validated_action_payload(row["kind"], origin, payload)
        if _canonical(data) != _canonical(binding["policy_data"]):
            raise E.ValidationFailed("approval effective inputs have changed")
        policy, roles = self._policy_binding(row["kind"], data)
        if policy != binding["policy"] or roles != binding["roles"]:
            raise E.AuthorizationDenied("approval policy or required roles have changed")
        return binding, live, payload

    def _actionable_approval_roles(self, row: sqlite3.Row) -> tuple[str, ...]:
        try:
            binding, _, _ = self._validate_approval_binding(row)
            return tuple(binding["roles"])
        except E.FacadeError:
            return ()

    def _decide(self, actor: Principal, approval_id: str, *, approve: bool, comment: str) -> ApprovalView:
        with self._approval_transaction():
            return self._decide_inner(actor, approval_id, approve=approve, comment=comment)

    def _decide_inner(self, actor: Principal, approval_id: str, *, approve: bool, comment: str) -> ApprovalView:
        actor = self._approval_actor(actor)
        row = self._db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if row is None:
            raise E.NotFound(f"approval '{approval_id}' not found")
        if row["status"] != "pending":
            raise E.ValidationFailed(f"approval '{approval_id}' already decided")
        if row["requested_by"] == actor.actor_id:
            raise E.AuthorizationDenied("请求者不能审批自己的请求（职责分离）")
        binding, _, _ = self._validate_approval_binding(row)
        if actor.role not in binding["roles"]:
            raise E.AuthorizationDenied("role may not decide this policy-bound approval")
        now = self._now()
        status = "approved" if approve else "rejected"
        changed = self._db.execute(
            "UPDATE approvals SET status=?, decided_by=?, decided_at=?, decision_note=?"
            " WHERE id=? AND status='pending'",
            (status, actor.actor_id, now, comment, approval_id),
        )
        if changed.rowcount != 1:
            raise E.VersionConflict("approval was decided concurrently")
        self._evidence_append(approval_id,
                              {"event": status, "actor": actor.actor_id, "at": now, "comment": comment})
        view = self._approval_view(self._db.execute(
            "SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone())
        self.notify(actor, "approval.decided", (row["requested_by"],),
                    title=f"审批{'通过' if approve else '拒绝'} {approval_id}",
                    body=f"{row['kind']}：{'通过' if approve else '拒绝'}。{comment}".strip(),
                    priority=C.PRIORITY_NORMAL, related=view.target)
        self._audit(actor.actor_id, f"approval.{status}", view.target,
                    detail=f"{approval_id} {row['kind']} {comment}".strip())
        if approve:
            self._resume_approved(view)
        else:
            self._apply_rejection(view)
        return view

    def _decision_binding(self, view: ApprovalView, status: str):
        if not self._approval_depth:
            raise E.ValidationFailed("approval side effects require the decision transaction")
        row = self._db.execute("SELECT * FROM approvals WHERE id=?", (view.approval_id,)).fetchone()
        if row is None or row["status"] != status or self._approval_view(row) != view:
            raise E.ValidationFailed("decision view does not match the stored approval")
        binding, rec, payload = self._validate_approval_binding(row)
        actor = self._principal_of(view.decided_by)
        if actor.actor_id == view.requested_by or actor.role not in binding["roles"]:
            raise E.AuthorizationDenied("decision no longer has independent approval authority")
        evidence = self._db.execute(
            "SELECT payload FROM evidence WHERE approval_id=? ORDER BY seq DESC LIMIT 1",
            (view.approval_id,),
        ).fetchone()
        event = json.loads(evidence["payload"])["payload"]
        if (event.get("event"), event.get("actor"), event.get("at"), event.get("comment")) != (
                status, view.decided_by, view.decided_at, view.decision_note):
            raise E.ValidationFailed("approval decision has no matching evidence")
        return rec, payload, actor

    def _resume_approved(self, view: ApprovalView) -> None:
        rec, payload, actor = self._decision_binding(view, "approved")
        if view.kind in BUSINESS_ACTION_SPECS:
            spec = get_action(view.kind)
            fields = dict(rec.fields)
            if spec.to_state:
                fields["state"] = spec.to_state
            if spec.creates_child is None:
                fields.update(payload.get("fields_delta", {}))
            if view.kind == C.ACTION_SALES_ORDER_REQUEST_CHANGE:
                values = self._validated_action_payload(view.kind, rec, payload)
                fields.update({name: values[name] for name in
                               ("product_id", "qty", "unit_price", "total_amount", "currency")})
            updated = self._put_record(actor.actor_id, rec.ref.record_type, rec.ref.record_id,
                                        fields, bump_version_from=rec.ref.version)
            if view.kind == C.ACTION_SALES_ORDER_REQUEST_CHANGE:
                self._sync_document_line(actor, updated)
            if spec.side_effects is not None:
                spec.side_effects(self, actor, updated, payload,
                                  rec.ref if spec.creates_child is not None else None)
            if spec.resume_side_effects is not None:
                spec.resume_side_effects(self, actor, updated, payload)
            self._audit(actor.actor_id, view.kind, rec.ref, detail="审批通过，动作生效")
        else:
            handler = get_standalone_handler(view.kind)
            if handler is None:
                raise E.ValidationFailed("approval has no supported resume handler")
            handler(self, actor, view, payload)

    def _apply_rejection(self, view: ApprovalView) -> None:
        rec, _, actor = self._decision_binding(view, "rejected")
        if view.kind in BUSINESS_ACTION_SPECS:
            spec = get_action(view.kind)
            state = spec.child_rejected_state if spec.creates_child is not None else spec.rejected_state
            if state:
                fields = dict(rec.fields)
                fields["state"] = state
                self._put_record(actor.actor_id, rec.ref.record_type, rec.ref.record_id,
                                 fields, bump_version_from=rec.ref.version)

    def approve(self, actor: Principal, approval_id: str, *, comment: str = "") -> ApprovalView:
        with self._lock:
            return self._decide(actor, approval_id, approve=True, comment=comment)

    def reject(self, actor: Principal, approval_id: str, *, comment: str = "") -> ApprovalView:
        with self._lock:
            return self._decide(actor, approval_id, approve=False, comment=comment)

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
            self._commit_business()
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
            self._commit_business()
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
            self._commit_business()

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
    if isinstance(actual, bool) or isinstance(target, bool):
        a, b = actual, target
    else:
        try:
            a, b = F.number(actual, field), F.number(target, "policy threshold")
        except E.ValidationFailed:
            if op not in ("==", "!="):
                raise E.ValidationFailed("policy comparison requires finite numeric inputs") from None
            a, b = str(actual), str(target)
    return {
        ">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b,
        "==": a == b, "!=": a != b,
    }[op]
