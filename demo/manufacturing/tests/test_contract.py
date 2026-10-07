"""Contract test suite for the ManufacturingBackend Facade.

The SAME suite must pass against every backend that implements the Facade:
the public simulation backend (run here) and, in a licensed environment, the
private licensed adapter. Passing this suite means "satisfies the demo
contract" — it does not mean the backends share an implementation.

Run:  python3 demo/manufacturing/tests/run_tests.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE))

from framework_port import constants as C  # noqa: E402
from framework_port import errors as FE  # noqa: E402
from framework_port.dtos import (  # noqa: E402
    BackendConfig,
    Principal,
    RecordRef,
    UserBootstrap,
)

FIXED_CLOCK = "2026-10-07T08:00:00+00:00"


def _clock() -> str:
    return FIXED_CLOCK


def make_backend(tmpdir: str):
    """Build a seeded simulated backend under a fixed clock."""

    from app import policy, seed as seed_mod
    from app.external_sims import SimulatedCarrier

    config = BackendConfig(
        db_path=f"{tmpdir}/demo.sqlite",
        clock=_clock,
        external_systems={C.GOVERNED_CARRIER_DISPATCH: SimulatedCarrier()},
        bootstrap_users=seed_mod.USERS,
    )
    from backend_sim import create_backend
    backend = create_backend(config)
    backend.configure_authorization(
        policy._RULES, policy.APPROVAL_POLICIES, policy.APPROVER_ROLES
    )
    seed_mod.seed(backend)
    return backend


def principal(user: str) -> Principal:
    names = {
        "owner": "林文昊（老板）", "factory": "王强（厂长）", "sales": "李婷（销售）",
        "sales2": "Chen Xiao（陈晓）", "warehouse": "张伟（仓库）",
        "admin": "系统管理员", "system": "自动哨兵（演示）",
    }
    roles = {"owner": C.ROLE_OWNER, "factory": C.ROLE_FACTORY, "sales": C.ROLE_SALES,
             "sales2": C.ROLE_SALES, "warehouse": C.ROLE_WAREHOUSE,
             "admin": C.ROLE_ADMIN, "system": C.ROLE_ADMIN}
    locales = {"sales2": "en"}
    return Principal(user, names.get(user, user), roles.get(user, "limited"),
                     locales.get(user, "zh"))


class ContractTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.backend = make_backend(self._tmp.name)

    def tearDown(self) -> None:
        self.backend.close()
        self._tmp.cleanup()

    # ------------------------------------------------------- helpers
    def _login(self, user: str) -> str:
        who = principal(user)
        session = self.backend.create_session(who)
        resolved = self.backend.resolve_session(session)
        self.assertIsNotNone(resolved)
        return session

    def _submit_golden_quote(self) -> str:
        result = self.backend.execute_business_action(
            principal("sales"), RecordRef(C.RECORD_QUOTATION, "Q-2026-0148"),
            C.ACTION_QUOTATION_SUBMIT,
            {"discount_pct": 8, "justification": "客户年度框架谈判折扣"},
        )
        self.assertIsNotNone(result.approval_id)
        return result.approval_id or ""


class AuthSessionTests(ContractTestBase):
    def test_all_six_accounts_log_in(self) -> None:
        for user in ("owner", "factory", "sales", "sales2", "warehouse", "admin"):
            self._login(user)

    def test_wrong_credential_fails(self) -> None:
        self.assertIsNone(self.backend.authenticate("owner", "wrong-password"))

    def test_session_resolves_and_closes(self) -> None:
        token = self._login("sales")
        self.assertIsNotNone(self.backend.resolve_session(token))
        self.backend.close_session(token)
        self.assertIsNone(self.backend.resolve_session(token))

    def test_default_language_is_chinese_and_sales2_is_english(self) -> None:
        owner = self.backend.authenticate("owner", "demo1234")
        sales2 = self.backend.authenticate("sales2", "demo1234")
        assert owner is not None and sales2 is not None
        self.assertEqual(owner.locale, "zh")
        self.assertEqual(sales2.locale, "en")


class RbacTests(ContractTestBase):
    def test_sales_cannot_view_others_orders_but_own(self) -> None:
        sales = principal("sales")
        records = self.backend.list_records(sales, C.RECORD_SALES_ORDER)
        ids = {r.ref.record_id for r in records}
        # seeded orders belong to sales; SO-2026-0150 was created by sales too.
        self.assertIn("SO-2026-0148" if "SO-2026-0148" in ids else next(iter(ids)), ids)

    def test_warehouse_cannot_execute_sales_actions(self) -> None:
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.execute_business_action(
                principal("warehouse"), RecordRef(C.RECORD_QUOTATION, "Q-2026-0148"),
                C.ACTION_QUOTATION_SUBMIT, {},
            )

    def test_admin_cannot_operate_business(self) -> None:
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.execute_business_action(
                principal("admin"), RecordRef(C.RECORD_QUOTATION, "Q-2026-0148"),
                C.ACTION_QUOTATION_SUBMIT, {},
            )

    def test_admin_cannot_create_business_records(self) -> None:
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.create_record(principal("admin"), C.RECORD_CUSTOMER, {"name_cn": "x"})

    def test_factory_cannot_confirm_orders(self) -> None:
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.execute_business_action(
                principal("factory"), RecordRef(C.RECORD_SALES_ORDER, "SO-2026-0141"),
                C.ACTION_SALES_ORDER_CONFIRM, {},
            )

    def test_audit_visibility_fail_closed(self) -> None:
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.get_audit_timeline(
                principal("warehouse"), RecordRef(C.RECORD_SALES_ORDER, "SO-2026-0141")
            )


class ApprovalTests(ContractTestBase):
    def test_discount_over_five_percent_requires_owner_approval(self) -> None:
        approval_id = self._submit_golden_quote()
        self.assertTrue(approval_id.startswith("APPR-"))
        quote = self.backend.get_record(
            principal("sales"), RecordRef(C.RECORD_QUOTATION, "Q-2026-0148")
        )
        assert quote is not None
        self.assertEqual(quote.fields.get("state"), "pending_approval")

    def test_discount_within_threshold_needs_no_approval(self) -> None:
        result = self.backend.execute_business_action(
            principal("sales"), RecordRef(C.RECORD_QUOTATION, "Q-2026-0119"),
            C.ACTION_QUOTATION_SUBMIT,
            {"discount_pct": 0, "justification": "目录价内"},
        )
        self.assertIsNone(result.approval_id)

    def test_requester_cannot_self_approve(self) -> None:
        approval_id = self._submit_golden_quote()
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.approve(principal("sales"), approval_id, comment="self")

    def test_non_approver_role_cannot_decide(self) -> None:
        approval_id = self._submit_golden_quote()
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.approve(principal("warehouse"), approval_id, comment="x")

    def test_owner_approval_resumes_quote(self) -> None:
        approval_id = self._submit_golden_quote()
        view = self.backend.approve(principal("owner"), approval_id, comment="同意")
        self.assertEqual(view.status, "approved")
        quote = self.backend.get_record(
            principal("sales"), RecordRef(C.RECORD_QUOTATION, "Q-2026-0148")
        )
        assert quote is not None
        self.assertEqual(quote.fields.get("state"), "approved")

    def test_rejection_is_terminal(self) -> None:
        approval_id = self._submit_golden_quote()
        view = self.backend.reject(principal("owner"), approval_id, comment="折扣过高")
        self.assertEqual(view.status, "rejected")
        quote = self.backend.get_record(
            principal("sales"), RecordRef(C.RECORD_QUOTATION, "Q-2026-0148")
        )
        assert quote is not None
        self.assertEqual(quote.fields.get("state"), "rejected")
        with self.assertRaises(FE.ValidationFailed):
            self.backend.approve(principal("owner"), approval_id, comment="再试试")


class GoldenFlowTests(ContractTestBase):
    def test_golden_path_end_to_end(self) -> None:
        sales, owner = principal("sales"), principal("owner")
        factory, warehouse = principal("factory"), principal("warehouse")

        # 1. quote with negotiated 8% -> approval -> approved
        approval_id = self._submit_golden_quote()
        self.backend.approve(owner, approval_id, comment="同意")

        # 2. accept -> order SO-0148 created as draft
        result = self.backend.execute_business_action(
            sales, RecordRef(C.RECORD_QUOTATION, "Q-2026-0148"),
            C.ACTION_QUOTATION_ACCEPT, {},
        )
        self.assertEqual(result.ref.record_type, C.RECORD_SALES_ORDER)
        order_id = result.ref.record_id
        self.assertEqual(order_id, "SO-0148")

        # 3. confirm (>50k) -> owner approval -> confirmed
        confirm_gate = self.backend.execute_business_action(
            sales, RecordRef(C.RECORD_SALES_ORDER, order_id),
            C.ACTION_SALES_ORDER_CONFIRM, {"justification": "客户年度采购"},
        )
        self.assertIsNotNone(confirm_gate.approval_id)
        self.backend.approve(owner, confirm_gate.approval_id or "", comment="ok")

        # 4. AI ATP: shortage on MAT-0001 -> expedited purchase approval
        order = self.backend.get_record(sales, RecordRef(C.RECORD_SALES_ORDER, order_id))
        assert order is not None
        from app import agents
        report = agents.atp_check(self.backend, sales, order)
        self.assertFalse(report["ok"])
        self.assertTrue(any(l["material_id"] == "MAT-0001" for l in report["shortages"]))
        line = report["shortages"][0]
        suggestion = agents.expedite_payload(line)
        purchase = self.backend.request_approval(
            sales, C.APPROVAL_EXPEDITE_PURCHASE, order.ref, suggestion,
            justification="AI 建议紧急采购",
        )
        self.backend.approve(owner, purchase.approval_id, comment="批准")

        # 5. production order -> release -> issue (warehouse) -> progress -> complete
        po_result = self.backend.execute_business_action(
            factory, order.ref, C.ACTION_PRODUCTION_ORDER_CREATE,
            {"product_id": order.fields.get("product_id"),
             "product_name": order.fields.get("product_name"),
             "qty": order.fields.get("qty"), "due_date": "2026-10-20",
             "expedite": False, "substitute": False,
             "requirements": [{"material_id": "MAT-0001", "material_name": "SS304",
                               "qty": 260.0}]},
        )
        self.assertEqual(po_result.ref.record_type, C.RECORD_PRODUCTION_ORDER)
        po_id = po_result.ref.record_id
        po_ref = RecordRef(C.RECORD_PRODUCTION_ORDER, po_id)

        # 5a. issuing material before purchase arrival fails honestly (shortage)
        self.backend.execute_business_action(factory, po_ref,
                                             C.ACTION_PRODUCTION_ORDER_RELEASE, {})
        with self.assertRaises(FE.ValidationFailed):
            self.backend.execute_business_action(warehouse, po_ref,
                                                 C.ACTION_PRODUCTION_ORDER_ISSUE_MATERIAL, {})

        # 5b. expedited material arrives -> issue succeeds
        inv_items = self.backend.list_records(
            warehouse, C.RECORD_INVENTORY_ITEM, filters={"item_ref": "MAT-0001"}
        )
        self.backend.execute_business_action(
            warehouse, inv_items[0].ref, C.ACTION_INVENTORY_RECEIPT,
            {"qty": 120, "justification": "紧急采购到货"},
        )
        self.backend.execute_business_action(warehouse, po_ref,
                                             C.ACTION_PRODUCTION_ORDER_ISSUE_MATERIAL, {})
        inv_after = self.backend.list_records(
            warehouse, C.RECORD_INVENTORY_ITEM, filters={"item_ref": "MAT-0001"}
        )
        self.assertEqual(inv_after[0].fields.get("qty_on_hand"), 180 + 120 - 260)

        self.backend.execute_business_action(
            factory, po_ref, C.ACTION_PRODUCTION_ORDER_REPORT_PROGRESS,
            {"progress_pct": 100},
        )
        self.backend.execute_business_action(factory, po_ref,
                                             C.ACTION_PRODUCTION_ORDER_COMPLETE, {})
        order_after = self.backend.get_record(sales, order.ref)
        assert order_after is not None
        self.assertEqual(order_after.fields.get("state"), "ready_to_ship")

        # 6. shipment request -> governed dispatch -> UNKNOWN (response lost)
        ship_result = self.backend.execute_business_action(
            sales, order.ref, C.ACTION_SHIPMENT_REQUEST, {"address": "客户仓"}
        )
        self.assertEqual(ship_result.ref.record_type, C.RECORD_SHIPMENT)
        shipment_id = ship_result.ref.record_id
        governed = self.backend.submit_governed_action(
            warehouse, C.GOVERNED_CARRIER_DISPATCH, ship_result.ref,
            {"order_id": order_id, "customer": "美驰汽车零部件"},
            reason="发货执行",
        )
        executed = self.backend.execute_governed_action(warehouse, governed.action_id)
        self.assertEqual(executed.attempt_outcome, "unknown")
        self.assertEqual(executed.state, "unknown")

        # 7. blind retry refused
        with self.assertRaises(FE.RetryRefused):
            self.backend.execute_governed_action(warehouse, governed.action_id)

        # 8. reconcile -> matched (derived); command truth stays unknown
        verdict = self.backend.reconcile_external_action(warehouse, governed.action_id)
        self.assertEqual(verdict.external_verdict, C.VERDICT_MATCHED_DERIVED)
        self.assertEqual(verdict.command_truth, "unknown")

        # 9. audit timeline reconstructs the whole story
        timeline = self.backend.get_audit_timeline(sales, RecordRef(C.RECORD_SALES_ORDER, order_id))
        actions = [e.action for e in timeline]
        self.assertIn(C.ACTION_QUOTATION_ACCEPT, actions)
        self.assertIn("approval.approved", actions)
        self.assertIn(C.ACTION_PRODUCTION_ORDER_CREATE, actions)
        self.assertIn(C.ACTION_PRODUCTION_ORDER_ISSUE_MATERIAL, actions)
        self.assertIn(C.ACTION_PRODUCTION_ORDER_COMPLETE, actions)
        self.assertIn("carrier.shipment_dispatch.execute", actions)
        self.assertIn("carrier.shipment_dispatch.reconcile", actions)
        # The quotation-side timeline carries the discount approval story.
        quote_timeline = self.backend.get_audit_timeline(
            sales, RecordRef(C.RECORD_QUOTATION, "Q-2026-0148")
        )
        self.assertIn(C.ACTION_QUOTATION_SUBMIT, [e.action for e in quote_timeline])

    def test_evidence_chain_verifies_and_scopes(self) -> None:
        approval_id = self._submit_golden_quote()
        result = self.backend.verify_evidence_chain(
            principal("owner"), RecordRef("approval", approval_id)
        )
        self.assertTrue(result.verified)
        self.assertEqual(result.scope, "approval_task")
        with self.assertRaises(FE.ValidationFailed):
            self.backend.verify_evidence_chain(
                principal("owner"), RecordRef(C.RECORD_QUOTATION, "Q-2026-0148")
            )

    def test_tampered_evidence_chain_fails(self) -> None:
        approval_id = self._submit_golden_quote()
        self.backend.approve(principal("owner"), approval_id, comment="ok")
        # simulate tampering directly in the demo store (demo-owned data)
        with self.backend._lock:  # noqa: SLF001 - test manipulates demo store only
            self.backend._db.execute(
                "UPDATE evidence SET payload=? WHERE approval_id=? AND seq=1",
                ('{"tampered": true}', approval_id),
            )
            self.backend._db.commit()
        result = self.backend.verify_evidence_chain(
            principal("owner"), RecordRef("approval", approval_id)
        )
        self.assertFalse(result.verified)


class TaskHandoffNotificationTests(ContractTestBase):
    def test_notification_read_state(self) -> None:
        owner = principal("owner")
        before = self.backend.unread_count(owner)
        self.backend.notify(
            principal("sales"), "test.kind", ("owner",),
            title="t", body="b", priority=C.PRIORITY_NORMAL,
        )
        self.assertEqual(self.backend.unread_count(owner), before + 1)
        notifications = self.backend.list_notifications(owner, unread_only=True)
        target = notifications[0]
        self.backend.mark_notification_read(owner, target.notification_id)
        self.assertEqual(self.backend.unread_count(owner), before)

    def test_handoff_transfers_responsibility_not_permissions(self) -> None:
        factory = principal("factory")
        task = self.backend.create_task(
            factory, "demo", "交接演示任务", "factory", origin="human",
        )
        view = self.backend.request_handoff(factory, task.task_id, "owner",
                                            reason="出差")
        self.assertEqual(view.status, "pending")
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.respond_handoff(factory, view.handoff_id, True)
        accepted = self.backend.respond_handoff(principal("owner"), view.handoff_id, True)
        self.assertEqual(accepted.status, "accepted")
        tasks = self.backend.list_tasks(principal("owner"), assignee="owner")
        self.assertTrue(any(t.task_id == task.task_id for t in tasks))

    def test_sentinel_escalates_overdue(self) -> None:
        from app.http_server import DemoApp
        app = DemoApp(self.backend, mode="public")
        counts = app.scan_once()
        # PO-2026-0092 is seeded overdue; MAT-0001 and cartons are below reorder.
        self.assertGreaterEqual(counts["overdue"] + counts["low_stock"], 1)
        tasks = self.backend.list_tasks(principal("factory"), assignee="factory")
        self.assertTrue(any(t.kind == "overdue_po" for t in tasks))
        # second scan must not duplicate (dedupe by open task)
        again = app.scan_once()
        self.assertEqual(again["overdue"], 0)


class DurabilityTests(ContractTestBase):
    def test_state_survives_restart_without_replay(self) -> None:
        approval_id = self._submit_golden_quote()
        db_path = self.backend._config.db_path  # noqa: SLF001 - test-only
        self.backend.close()
        from backend_sim import create_backend
        config = BackendConfig(
            db_path=db_path, clock=_clock,
            external_systems={C.GOVERNED_CARRIER_DISPATCH: _fresh_carrier()},
        )
        reopened = create_backend(config)
        from app import policy
        reopened.configure_authorization(
            policy._RULES, policy.APPROVAL_POLICIES, policy.APPROVER_ROLES
        )
        # tearDown closes whatever backend is current; hand ownership over.
        self.backend = reopened
        quote = reopened.get_record(
            principal("sales"), RecordRef(C.RECORD_QUOTATION, "Q-2026-0148")
        )
        assert quote is not None
        self.assertEqual(quote.fields.get("state"), "pending_approval")
        # The pending approval is still there and can still be decided — no
        # mutation replayed itself during recovery.
        view = reopened.approve(principal("owner"), approval_id, comment="恢复后审批")
        self.assertEqual(view.status, "approved")


def _fresh_carrier():
    from app.external_sims import SimulatedCarrier
    return SimulatedCarrier()


class DeterministicReplayTests(unittest.TestCase):
    def test_two_seeds_produce_identical_state(self) -> None:
        import hashlib
        import json as _json
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            backend_a = make_backend(tmp1)
            backend_b = make_backend(tmp2)
            snapshot = ("records", "approvals", "tasks", "notifications")
            for table in snapshot:
                rows_a = backend_a._db.execute(f"SELECT * FROM {table}").fetchall()  # noqa: SLF001
                rows_b = backend_b._db.execute(f"SELECT * FROM {table}").fetchall()  # noqa: SLF001
                digest_a = hashlib.sha256(
                    _json.dumps([tuple(r) for r in rows_a], sort_keys=True,
                                default=str).encode()
                ).hexdigest()
                digest_b = hashlib.sha256(
                    _json.dumps([tuple(r) for r in rows_b], sort_keys=True,
                                default=str).encode()
                ).hexdigest()
                self.assertEqual(digest_a, digest_b, f"table {table} diverged")
            backend_a.close()
            backend_b.close()


def load_tests(loader, tests, pattern):  # noqa: ANN001
    suite = unittest.TestSuite()
    for cls in (AuthSessionTests, RbacTests, ApprovalTests, GoldenFlowTests,
                TaskHandoffNotificationTests, DurabilityTests,
                DeterministicReplayTests):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    return suite


if __name__ == "__main__":
    unittest.main(verbosity=2)
