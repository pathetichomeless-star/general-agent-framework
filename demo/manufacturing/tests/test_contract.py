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


class ApprovalBypassRegressionTests(ContractTestBase):
    """GAF-04: reject forged approval inputs without changing business state."""

    def _quote(self):
        return self.backend.get_record(principal("sales"),
                                       RecordRef(C.RECORD_QUOTATION, "Q-2026-0148"))

    def _http(self, form, *, path="/quotations/Q-2026-0148/submit"):
        from app.http_server import DemoApp, SESSION_COOKIE
        token = self.backend.create_session(principal("sales"))
        return DemoApp(self.backend, "public").handle(
            "POST", path, {}, form, {"Cookie": f"{SESSION_COOKIE}={token}"}
        )

    def _assert_quote_unchanged(self, before):
        self.assertEqual(self._quote(), before)
        approvals = self.backend.list_approvals(principal("owner"), pending_for_me=False)
        self.assertFalse(any(a.target.record_id == before.ref.record_id for a in approvals))

    def _assert_http_rejected(self, form, *, path="/quotations/Q-2026-0148/submit"):
        status, body, headers = self._http(form, path=path)
        # The existing UI renders business errors with HTTP 200, not redirects.
        self.assertEqual(status, 200)
        self.assertIn('class="flash err"', body)
        self.assertFalse(any(name == "Location" for name, _ in headers))

    def test_http_discount_override_rejected(self):
        before = self._quote()
        self._assert_http_rejected({"discount_pct": "0", "justification": "override"})
        self._assert_quote_unchanged(before)

    def test_direct_approval_state_update_rejected(self):
        before = self._quote()
        with self.assertRaises(FE.ValidationFailed):
            self.backend.update_record(principal("sales"), before.ref,
                                       {"state": "approved"}, expected_version=before.ref.version)
        self._assert_quote_unchanged(before)

    def test_http_invalid_or_extra_parameters_rejected(self):
        before = self._quote()
        forms = [{"discount_pct": v} for v in ("", "bad", "NaN", "inf", "-1", "101")]
        forms += [{k: "0"} for k in ("total_amount", "unit_price", "qty", "state", "approval_id")]
        for form in forms:
            with self.subTest(form=form):
                self._assert_http_rejected(form)
                self._assert_quote_unchanged(before)

    def test_backend_invalid_or_overriding_action_payload_rejected(self):
        before = self._quote()
        payloads = [{"discount_pct": v} for v in (0, True, None, float("nan"), float("inf"), "bad")]
        payloads += [{"total_amount": 0}, {"fields_delta": {"discount_pct": 0}}, []]
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(FE.ValidationFailed):
                self.backend.execute_business_action(principal("sales"), before.ref,
                                                     C.ACTION_QUOTATION_SUBMIT, payload)
        self._assert_quote_unchanged(before)

    def test_matching_discount_still_requires_owner_approval(self):
        result = self.backend.execute_business_action(
            principal("sales"), self._quote().ref, C.ACTION_QUOTATION_SUBMIT,
            {"discount_pct": "8", "justification": "stored value"},
        )
        self.assertEqual(result.state, "pending_approval")
        self.assertIsNotNone(result.approval_id)
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.approve(principal("factory"), result.approval_id)
        self.backend.approve(principal("owner"), result.approval_id)
        self.assertEqual(self._quote().fields["discount_pct"], 8)
        self.assertEqual(self._quote().fields["state"], "approved")

    def test_http_normal_approval_and_acceptance_work(self):
        self.assertEqual(self._http({"justification": "normal"})[0], 303)
        self.assertEqual(self._quote().fields["state"], "pending_approval")
        approval = next(a for a in self.backend.list_approvals(principal("owner"))
                        if a.target.record_id == "Q-2026-0148")
        self.backend.approve(principal("owner"), approval.approval_id)
        self.assertEqual(self._http({}, path="/quotations/Q-2026-0148/accept")[0], 303)
        self.assertIsNotNone(self.backend.get_record(principal("sales"),
                                                    RecordRef(C.RECORD_SALES_ORDER, "SO-0148")))

    def test_http_normal_rejection_remains_terminal(self):
        self.assertEqual(self._http({"justification": "normal"})[0], 303)
        approval = next(a for a in self.backend.list_approvals(principal("owner"))
                        if a.target.record_id == "Q-2026-0148")
        self.backend.reject(principal("owner"), approval.approval_id)
        self.assertEqual(self._quote().fields["state"], "rejected")
        self._assert_http_rejected({}, path="/quotations/Q-2026-0148/accept")
        with self.assertRaises(FE.ValidationFailed):
            self.backend.approve(principal("owner"), approval.approval_id)

    def test_requester_cannot_decide_even_with_approver_role(self):
        # Admission requires sales authority. Later gaining the approver role
        # must still not let that same actor decide their own request.
        approval = self.backend.request_approval(principal("sales"), C.ACTION_QUOTATION_SUBMIT,
                                                self._quote().ref, {}, justification="self")
        self.backend._db.execute("UPDATE users SET role=? WHERE actor_id='sales'", (C.ROLE_OWNER,))
        self.backend._db.commit()
        owner = self.backend._principal_of("sales")
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.approve(owner, approval.approval_id)
        self.assertEqual(self.backend.get_approval(owner, approval.approval_id).status, "pending")

    def test_protected_field_updates_are_atomic(self):
        before = self._quote()
        for field in ("state", "status", "approval_id", "approval_status", "approval_binding",
                      "approved_by", "approved_at", "decided_by", "decided_at", "owner_id",
                      "id", "version", "created_by", "updated_at"):
            with self.subTest(field=field), self.assertRaises(FE.ValidationFailed):
                self.backend.update_record(principal("sales"), before.ref,
                                           {"note": "must not persist", field: "forged"},
                                           expected_version=before.ref.version)
        self._assert_quote_unchanged(before)

    def test_authorized_draft_edit_and_price_recalculation(self):
        before = self._quote()
        edited = self.backend.update_record(
            principal("sales"), before.ref, {"requested_date": "2026-11-01", "qty": 1000},
            expected_version=before.ref.version,
        )
        self.assertEqual(edited.fields["requested_date"], "2026-11-01")
        self.assertEqual(edited.fields["unit_price"], 42.32)
        self.assertEqual(edited.fields["total_amount"], 42320)
        self.assertEqual(edited.ref.version, before.ref.version + 1)
        self.assertEqual(self.backend.execute_business_action(
            principal("sales"), edited.ref, C.ACTION_QUOTATION_SUBMIT, {}
        ).state, "pending_approval")

    def test_version_conflict_preserved(self):
        before = self._quote()
        edited = self.backend.update_record(principal("sales"), before.ref, {"note": "first"},
                                             expected_version=before.ref.version)
        with self.assertRaises(FE.VersionConflict):
            self.backend.update_record(principal("sales"), before.ref, {"note": "stale"},
                                       expected_version=before.ref.version)
        self.assertEqual(self._quote(), edited)

    def test_edit_rbac_preserved(self):
        before = self._quote()
        for user in ("warehouse", "admin"):
            with self.subTest(user=user), self.assertRaises(FE.AuthorizationDenied):
                self.backend.update_record(principal(user), before.ref, {"note": "denied"},
                                           expected_version=before.ref.version)
        self._assert_quote_unchanged(before)

    def test_workflow_state_cannot_be_forged_on_creation(self):
        cases = (("sales", C.RECORD_QUOTATION, "approved"),
                 ("sales", C.RECORD_SALES_ORDER, "confirmed"),
                 ("factory", C.RECORD_PRODUCTION_ORDER, "completed"),
                 ("sales", C.RECORD_SHIPMENT, "reconciled_matched"))
        for user, record_type, state in cases:
            with self.subTest(record_type=record_type), self.assertRaises(FE.AuthorizationDenied):
                self.backend.create_record(principal(user), record_type,
                                           {"id": "FORGED", "state": state})
            self.assertIsNone(self.backend.get_record(principal("owner"),
                                                     RecordRef(record_type, "FORGED")))

    def test_quotation_creation_validates_and_derives_prices(self):
        fields = {"product_id": "PROD-0001", "qty": 10, "list_price": 46, "discount_pct": 8}
        q = self.backend.create_record(principal("sales"), C.RECORD_QUOTATION, fields)
        self.assertEqual(q.fields["state"], "draft")
        self.assertEqual(q.fields["unit_price"], 42.32)
        self.assertEqual(q.fields["total_amount"], 423.2)
        for override in ({"discount_pct": float("nan")}, {"discount_pct": -1},
                         {"discount_pct": 101}, {"qty": 0}, {"qty": True},
                         {"list_price": "bad"}, {"unit_price": 1},
                         {"total_amount": 0}, {"approval_id": "forged"}):
            with self.subTest(override=override), self.assertRaises(FE.ValidationFailed):
                self.backend.create_record(principal("sales"), C.RECORD_QUOTATION,
                                           {**fields, **override})

    def test_invalid_http_quote_creation_does_not_coerce_to_zero(self):
        form = {"product_id": "PROD-0001", "qty": "10", "list_price": "46", "discount_pct": "8",
                "unit_price": "42.32", "total_amount": "423.2"}
        count = len(self.backend.list_records(principal("sales"), C.RECORD_QUOTATION))
        for key in ("qty", "list_price", "discount_pct", "unit_price", "total_amount"):
            with self.subTest(key=key):
                self._assert_http_rejected({**form, key: "bad"}, path="/quotations")
        self.assertEqual(len(self.backend.list_records(principal("sales"), C.RECORD_QUOTATION)), count)
        self.assertEqual(self._http(form, path="/quotations")[0], 303)

    def test_submitted_quote_content_and_lines_cannot_be_changed(self):
        approval_id = self._submit_golden_quote()
        for phase in ("pending", "approved"):
            before = self._quote()
            with self.subTest(phase=phase), self.assertRaises(FE.ValidationFailed):
                self.backend.update_record(principal("sales"), before.ref, {"discount_pct": 0},
                                           expected_version=before.ref.version)
            with self.assertRaises(FE.AuthorizationDenied):
                self.backend.create_record(principal("sales"), C.RECORD_QUOTATION_LINE,
                                           {"quotation_id": before.ref.record_id, "qty": 1})
            self.assertEqual(self._quote(), before)
            if phase == "pending":
                self.backend.approve(principal("owner"), approval_id)

    def test_protected_fields_delta_rejected_on_both_admission_paths(self):
        ref = RecordRef(C.RECORD_SALES_ORDER, "SO-2026-0141")
        before = self.backend.get_record(principal("sales"), ref)
        for delta in ({"state": "approved"}, {"approval_id": "forged"}, []):
            payload = {"price_change": False, "fields_delta": delta}
            with self.subTest(delta=delta):
                with self.assertRaises(FE.ValidationFailed):
                    self.backend.execute_business_action(principal("sales"), ref,
                                                         C.ACTION_SALES_ORDER_REQUEST_CHANGE, payload)
                with self.assertRaises(FE.ValidationFailed):
                    self.backend.request_approval(principal("sales"), C.ACTION_SALES_ORDER_REQUEST_CHANGE,
                                                  ref, payload, justification="forged")
        self.assertEqual(self.backend.get_record(principal("sales"), ref), before)

    def test_order_total_override_rejected_and_real_total_gates(self):
        order = self.backend.create_record(principal("sales"), C.RECORD_SALES_ORDER,
                                           {"product_id": "PROD-0001", "qty": 2000,
                                            "unit_price": 50, "total_amount": 100000})
        self.backend.create_record(principal("sales"), C.RECORD_SALES_ORDER_LINE,
                                   {"order_id": order.ref.record_id, "product_id": "PROD-0001",
                                    "qty": 2000, "unit_price": 50})
        with self.assertRaises(FE.ValidationFailed):
            self.backend.execute_business_action(principal("sales"), order.ref,
                                                 C.ACTION_SALES_ORDER_CONFIRM, {"total_amount": 0})
        self.assertEqual(self.backend.execute_business_action(
            principal("sales"), order.ref, C.ACTION_SALES_ORDER_CONFIRM, {}
        ).state, "pending_approval")

    def test_legacy_unsafe_approval_payload_rejected_before_decision(self):
        approval_id = self._submit_golden_quote()
        before = self._quote()
        # Simulate an old demo-local approval admitted before GAF-04 was fixed.
        self.backend._db.execute(
            "UPDATE approvals SET payload=? WHERE id=?",
            ('{"fields_delta":{"state":"accepted"}}', approval_id),
        )
        self.backend._db.commit()
        with self.assertRaises(FE.ValidationFailed):
            self.backend.approve(principal("owner"), approval_id)
        self.assertEqual(self.backend.get_approval(principal("owner"), approval_id).status, "pending")
        self.assertEqual(self._quote(), before)

    def test_invalid_quote_edit_is_atomic(self):
        before = self._quote()
        for fields in ({"discount_pct": float("nan")}, {"qty": 0},
                       {"discount_pct": 0, "unit_price": 42.32}, {"total_amount": 0}):
            with self.subTest(fields=fields), self.assertRaises(FE.ValidationFailed):
                self.backend.update_record(principal("sales"), before.ref, fields,
                                           expected_version=before.ref.version)
        self._assert_quote_unchanged(before)

    def test_inventory_and_production_normal_edits_remain_available(self):
        inventory = self.backend.list_records(principal("warehouse"), C.RECORD_INVENTORY_ITEM)[0]
        edited = self.backend.update_record(principal("warehouse"), inventory.ref,
                                             {"reorder_point": 350}, expected_version=inventory.ref.version)
        self.assertEqual(edited.fields["reorder_point"], 350)
        production = self.backend.list_records(principal("factory"), C.RECORD_PRODUCTION_ORDER)[0]
        edited = self.backend.update_record(principal("factory"), production.ref,
                                             {"due_date": "2026-11-10"}, expected_version=production.ref.version)
        self.assertEqual(edited.fields["due_date"], "2026-11-10")

    def test_master_data_activation_edit_is_not_a_workflow_transition(self):
        customer = self.backend.list_records(principal("sales"), C.RECORD_CUSTOMER)[0]
        edited = self.backend.update_record(principal("sales"), customer.ref,
                                             {"state": "inactive"}, expected_version=customer.ref.version)
        self.assertEqual(edited.fields["state"], "inactive")

    def test_approved_date_change_resumes_without_state_override(self):
        # SO-0141 already has a pending seed approval; use an unbound order.
        ref = RecordRef(C.RECORD_SALES_ORDER, "SO-2026-0135")
        result = self.backend.execute_business_action(
            principal("sales"), ref, C.ACTION_SALES_ORDER_REQUEST_CHANGE,
            {"price_change": False, "fields_delta": {"requested_date": "2026-12-01"}},
        )
        self.backend.approve(principal("factory"), result.approval_id)
        order = self.backend.get_record(principal("sales"), ref)
        self.assertEqual(order.fields["state"], "confirmed")
        self.assertEqual(order.fields["requested_date"], "2026-12-01")

    def test_seed_history_permissions_revoked_even_on_failure(self):
        from unittest.mock import patch
        from app import seed
        with patch("app.seed._seed", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                seed.seed(self.backend)
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.create_record(principal("sales"), C.RECORD_SALES_ORDER,
                                       {"state": "confirmed", "total_amount": 1})

    def test_invalid_mapping_and_version_parameters_rejected(self):
        before = self._quote()
        for version in (True, 1.0, "1"):
            with self.subTest(version=version), self.assertRaises(FE.ValidationFailed):
                self.backend.update_record(principal("sales"), before.ref, {"note": "invalid"},
                                           expected_version=version)
        with self.assertRaises(FE.ValidationFailed):
            self.backend.update_record(principal("sales"), before.ref, [],
                                       expected_version=before.ref.version)
        with self.assertRaises(FE.ValidationFailed):
            self.backend.create_record(principal("sales"), C.RECORD_QUOTATION, [])
        self._assert_quote_unchanged(before)


class SeedIsolationTests(unittest.TestCase):
    """GAF-04A: fixture authority never becomes business authority."""

    def setUp(self):
        from backend_sim import create_backend
        from app import policy, seed
        self._tmp = tempfile.TemporaryDirectory()
        self.backend = create_backend(BackendConfig(
            db_path=f"{self._tmp.name}/seed.sqlite", clock=_clock,
            bootstrap_users=seed.USERS,
        ))
        self.backend.configure_authorization(
            policy._RULES, policy.APPROVAL_POLICIES, policy.APPROVER_ROLES
        )

    def tearDown(self):
        self.backend.close()
        self._tmp.cleanup()

    def _configuration(self):
        return (self.backend._rules, self.backend._approval_policies,
                self.backend._approver_roles)

    def _assert_configuration(self, original, values):
        for before, after in zip(original, self._configuration()):
            self.assertIs(before, after)
        self.assertEqual(self._configuration(), values)

    def _custom_configuration(self):
        from framework_port.dtos import RoleRule, ApprovalPolicy
        self.backend.configure_authorization(
            (RoleRule(C.ROLE_OWNER, C.PERM_VIEW, C.RECORD_CUSTOMER, True),),
            (ApprovalPolicy(C.ACTION_QUOTATION_SUBMIT,
                            {"field": "discount_pct", "op": ">", "value": 1}, C.ROLE_FACTORY),),
            {C.ACTION_QUOTATION_SUBMIT: (C.ROLE_FACTORY,)},
        )

    def _run_paused_seed(self, attempts, *, fail=False):
        import threading
        from unittest.mock import patch
        from app import seed

        entered, release = threading.Event(), threading.Event()
        attempted = [threading.Event() for _ in attempts]
        original_lock, original_loader = self.backend._lock, seed._seed
        results, seed_errors = {}, []

        class ObservedLock:
            # Observe each caller at lock acquisition, without sleeps or a
            # scheduling assumption about whether its public call has started.
            def __enter__(self):
                name = threading.current_thread().name
                if name.startswith("seed-caller-"):
                    attempted[int(name.rsplit("-", 1)[1])].set()
                original_lock.acquire()
                return self

            def __exit__(self, *args):
                original_lock.release()

        def loader(writer):
            result = original_loader(writer)
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test synchronization timeout")
            if fail:
                raise RuntimeError("injected after fixture writes")
            return result

        def initialize():
            try:
                seed.seed(self.backend)
            except Exception as exc:
                seed_errors.append(exc)

        def call(index, operation):
            try:
                operation()
                results[index] = "ACCEPTED"
            except Exception as exc:
                results[index] = exc

        self.backend._lock = ObservedLock()
        initializer = threading.Thread(target=initialize, name="seed-initializer", daemon=True)
        callers = []
        try:
            with patch("app.seed._seed", side_effect=loader):
                initializer.start()
                try:
                    self.assertTrue(entered.wait(5), "seed did not reach pause")
                    self.assertFalse(any(key[1] == "seed_history" for key in self.backend._rules))
                    for index, operation in enumerate(attempts):
                        thread = threading.Thread(target=call, args=(index, operation),
                                                  name=f"seed-caller-{index}", daemon=True)
                        callers.append(thread)
                        thread.start()
                    for event in attempted:
                        self.assertTrue(event.wait(5), "caller did not enter public operation")
                    self.assertEqual(results, {}, "business call escaped initialization lock")
                finally:
                    release.set()
                    initializer.join(5)
                    for thread in callers:
                        thread.join(5)
        finally:
            self.backend._lock = original_lock
        self.assertFalse(initializer.is_alive())
        self.assertTrue(all(not thread.is_alive() for thread in callers))
        if fail:
            self.assertEqual(len(seed_errors), 1)
            self.assertEqual(str(seed_errors[0]), "injected after fixture writes")
        else:
            self.assertEqual(seed_errors, [])
        self.assertEqual(len(results), len(attempts))
        for value in results.values():
            self.assertIsInstance(value, FE.AuthorizationDenied)

    def _historical_quote(self, user="sales2", record_id="FORGED-SEED"):
        return self.backend.create_record(principal(user), C.RECORD_QUOTATION, {
            "id": record_id, "state": "approved", "qty": 1,
            "list_price": 46, "discount_pct": 8,
        })

    def test_concurrent_sales2_cannot_create_approved_quote(self):
        self._run_paused_seed([self._historical_quote])
        self.assertIsNone(self.backend.get_record(
            principal("owner"), RecordRef(C.RECORD_QUOTATION, "FORGED-SEED")))

    def test_concurrent_callers_cannot_inherit_fixture_authority(self):
        self._run_paused_seed([
            lambda: self._historical_quote("sales", "FORGED-SALES"),
            lambda: self.backend.create_record(principal("factory"), C.RECORD_PRODUCTION_ORDER,
                                                {"id": "FORGED-PO", "state": "completed"}),
            lambda: self.backend.create_record(principal("sales2"), C.RECORD_QUOTATION_LINE,
                                                {"quotation_id": "Q-2026-0130", "qty": 1}),
        ])
        self.assertFalse(self.backend._db.execute(
            "SELECT 1 FROM records WHERE id IN ('FORGED-SALES','FORGED-PO')").fetchall())
        self.assertEqual(len(self.backend.list_records(
            principal("owner"), C.RECORD_QUOTATION_LINE)), 7)

    def test_custom_configuration_survives_success_and_repeat_seed(self):
        import copy
        from app import seed
        self._custom_configuration()
        original, values = self._configuration(), copy.deepcopy(self._configuration())
        self.assertTrue(seed.seed(self.backend)["seeded"])
        self._assert_configuration(original, values)
        self.assertFalse(seed.seed(self.backend)["seeded"])
        self._assert_configuration(original, values)
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.create_record(principal("sales"), C.RECORD_CUSTOMER, {"id": "DENIED"})

    def test_deny_all_configuration_remains_unchanged(self):
        from app import seed
        self.backend.configure_authorization((), (), {})
        original = self._configuration()
        self.assertTrue(seed.seed(self.backend)["seeded"])
        self._assert_configuration(original, ({}, [], {}))
        self.assertEqual(self.backend._db.execute("SELECT COUNT(*) FROM records").fetchone()[0], 84)
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.create_record(principal("sales"), C.RECORD_CUSTOMER, {"id": "DENIED"})

    def test_failure_preserves_configuration_and_discards_staged_writes(self):
        import copy
        from unittest.mock import patch
        from app import seed
        self._custom_configuration()
        original, values = self._configuration(), copy.deepcopy(self._configuration())
        before = list(self.backend._db.iterdump())
        loader = seed._seed
        saved = []

        def fail_after_writes(writer):
            saved.append(writer)
            loader(writer)
            raise RuntimeError("injected after all fixture writes")

        with patch("app.seed._seed", side_effect=fail_after_writes):
            with self.assertRaisesRegex(RuntimeError, "after all fixture writes"):
                seed.seed(self.backend)
        self._assert_configuration(original, values)
        self.assertEqual(list(self.backend._db.iterdump()), before)
        with self.assertRaises(FE.AuthorizationDenied):
            saved[0].create_record(principal("sales"), C.RECORD_SALES_ORDER,
                                   {"state": "confirmed"})
        self.assertTrue(seed.seed(self.backend)["seeded"])
        self._assert_configuration(original, values)

    def test_concurrent_requests_denied_after_seed_failure(self):
        before = list(self.backend._db.iterdump())
        self._run_paused_seed([self._historical_quote], fail=True)
        self.assertEqual(list(self.backend._db.iterdump()), before)

    def test_fixture_writer_is_thread_bound_and_revoked(self):
        import threading
        from unittest.mock import patch
        from app import seed
        saved, errors = [], []
        loader = seed._seed

        def capture(writer):
            saved.append(writer)

            def cross_thread():
                try:
                    writer.create_record(principal("sales2"), C.RECORD_QUOTATION,
                                         {"id": "LEAKED", "state": "approved"})
                except Exception as exc:
                    errors.append(exc)

            thread = threading.Thread(target=cross_thread, daemon=True)
            thread.start()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            # Even a reentrant call into the live Facade gets no privilege.
            with self.assertRaises(FE.AuthorizationDenied):
                self._historical_quote()
            return loader(writer)

        with patch("app.seed._seed", side_effect=capture):
            seed.seed(self.backend)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], FE.AuthorizationDenied)
        with self.assertRaises(FE.AuthorizationDenied):
            saved[0].create_record(principal("sales"), C.RECORD_SALES_ORDER,
                                   {"state": "confirmed"})

    def test_public_facade_cannot_enable_historical_writes(self):
        from app import policy
        from framework_port.dtos import RoleRule
        from framework_port.protocol import ManufacturingBackend
        self.assertFalse(hasattr(ManufacturingBackend, "_initialize_demo_seed"))
        self.backend.configure_authorization(
            policy._RULES + (RoleRule(C.ROLE_SALES, "seed_history", C.RECORD_QUOTATION),),
            policy.APPROVAL_POLICIES, policy.APPROVER_ROLES,
        )
        with self.assertRaises(FE.AuthorizationDenied):
            self._historical_quote()
        with self.assertRaises(TypeError):
            self.backend.create_record(principal("sales"), C.RECORD_QUOTATION,
                                       {"state": "approved"}, historical=True)

    def test_expected_historical_fixtures_and_pending_approvals(self):
        from app import seed
        self.assertTrue(seed.seed(self.backend)["seeded"])
        for record_type, record_id, state in (
            (C.RECORD_QUOTATION, "Q-2026-0121", "accepted"),
            (C.RECORD_QUOTATION, "Q-2026-0128", "rejected"),
            (C.RECORD_QUOTATION, "Q-2026-0130", "approved"),
            (C.RECORD_SALES_ORDER, "SO-2026-0136", "closed"),
            (C.RECORD_PRODUCTION_ORDER, "PO-2026-0090", "completed"),
            (C.RECORD_SHIPMENT, "SHIP-2026-0090", "reconciled_matched"),
        ):
            with self.subTest(record_id=record_id):
                record = self.backend.get_record(principal("owner"), RecordRef(record_type, record_id))
                self.assertEqual(record.fields["state"], state)
        counts = dict(self.backend._db.execute(
            "SELECT record_type, COUNT(*) FROM records GROUP BY record_type").fetchall())
        self.assertEqual(counts, {
            C.RECORD_CUSTOMER: 8, C.RECORD_PRODUCT: 12, C.RECORD_MATERIAL: 10,
            C.RECORD_PRICE_BOOK_ENTRY: 12, C.RECORD_INVENTORY_ITEM: 12,
            C.RECORD_QUOTATION: 7, C.RECORD_QUOTATION_LINE: 7,
            C.RECORD_SALES_ORDER: 5, C.RECORD_SALES_ORDER_LINE: 5,
            C.RECORD_PRODUCTION_ORDER: 3, C.RECORD_MATERIAL_REQUIREMENT: 1,
            C.RECORD_SHIPMENT: 1, C.RECORD_INVENTORY_MOVEMENT: 1,
        })
        self.assertEqual(len(self.backend.list_records(principal("owner"), C.RECORD_QUOTATION_LINE)), 7)
        self.assertEqual(len(self.backend.list_approvals(principal("owner"), pending_for_me=False)), 3)
        self.assertFalse(any(key[1] == "seed_history" for key in self.backend._rules))

    def test_unsupported_backend_fails_closed_without_configuration_change(self):
        from unittest.mock import Mock
        from app import seed
        backend = Mock(spec=["configure_authorization"])
        with self.assertRaises(FE.NotSupportedInBackend):
            seed.seed(backend)
        backend.configure_authorization.assert_not_called()


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
            sales, order_after.ref, C.ACTION_SHIPMENT_REQUEST, {"address": "客户仓"}
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
    for cls in (AuthSessionTests, RbacTests, ApprovalTests, ApprovalBypassRegressionTests,
                SeedIsolationTests, GoldenFlowTests,
                TaskHandoffNotificationTests, DurabilityTests,
                DeterministicReplayTests):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    return suite


if __name__ == "__main__":
    unittest.main(verbosity=2)
