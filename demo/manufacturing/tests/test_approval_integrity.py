"""GAF-04B approval binding, authorization, concurrency and atomicity tests."""

from __future__ import annotations

import json
import sys
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_contract import ContractTestBase, principal
from framework_port import constants as C, errors as FE
from framework_port.dtos import RecordRef, UserBootstrap


class ApprovalIntegrityTests(ContractTestBase):
    QUOTE = RecordRef(C.RECORD_QUOTATION, "Q-2026-0148")
    ORDER = RecordRef(C.RECORD_SALES_ORDER, "SO-2026-0135")

    def _dump(self):
        return list(self.backend._db.iterdump())

    def _approval(self, approval_id):
        return self.backend.get_approval(principal("owner"), approval_id)

    def _change(self, *, price=True):
        return self.backend.request_approval(
            principal("sales"), C.ACTION_SALES_ORDER_REQUEST_CHANGE, self.ORDER,
            {"price_change": price, "fields_delta": (
                {"unit_price": 12.34, "total_amount": 12340} if price else {"requested_date": "2026-12-01"})},
            justification="binding regression",
        )

    def _mutate_approval(self, approval_id, column, value):
        # Column names come only from the test's fixed cases, never user input.
        self.backend._db.execute(f"UPDATE approvals SET {column}=? WHERE id=?",
                                 (value, approval_id))
        self.backend._db.commit()

    def _assert_failed_decision_is_atomic(self, approval_id, error=FE.ValidationFailed):
        before = self._dump()
        for method in (self.backend.approve, self.backend.reject):
            with self.assertRaises(error):
                method(principal("owner"), approval_id)
            self.assertEqual(self._dump(), before)

    def _parallel(self, operations):
        ready = threading.Barrier(len(operations) + 1)
        results = [None] * len(operations)

        def call(index, operation):
            try:
                ready.wait(5)
                results[index] = operation()
            except Exception as exc:
                results[index] = exc

        threads = [threading.Thread(target=call, args=(i, op), daemon=True)
                   for i, op in enumerate(operations)]
        for thread in threads:
            thread.start()
        ready.wait(5)
        for thread in threads:
            thread.join(5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        return results

    def test_wrong_object_type_rejected_at_both_admission_paths(self):
        before = self._dump()
        for method in (self.backend.request_approval, self.backend.execute_business_action):
            with self.subTest(method=method.__name__), self.assertRaises(FE.ValidationFailed):
                if method == self.backend.request_approval:
                    method(principal("sales"), C.ACTION_SALES_ORDER_REQUEST_CHANGE,
                           RecordRef(C.RECORD_CUSTOMER, "CUST-0001"),
                           {"price_change": False, "fields_delta": {"name_cn": "forged"}},
                           justification="wrong type")
                else:
                    method(principal("sales"), RecordRef(C.RECORD_CUSTOMER, "CUST-0001"),
                           C.ACTION_SALES_ORDER_REQUEST_CHANGE, {"price_change": False})
            self.assertEqual(self._dump(), before)

    def test_wrong_or_out_of_scope_object_id_rejected(self):
        before = self._dump()
        with self.assertRaises(FE.NotFound):
            self.backend.request_approval(principal("sales"), C.ACTION_SALES_ORDER_REQUEST_CHANGE,
                                          RecordRef(C.RECORD_SALES_ORDER, "MISSING"), {}, justification="x")
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.request_approval(principal("sales2"), C.ACTION_SALES_ORDER_REQUEST_CHANGE,
                                          self.ORDER, {}, justification="another owner's order")
        self.assertEqual(self._dump(), before)

    def test_unsupported_action_object_and_unauthorized_admission(self):
        before = self._dump()
        for kind, ref, user, error in (
            ("unsupported", self.ORDER, "sales", FE.ValidationFailed),
            (C.ACTION_SALES_ORDER_CONFIRM, self.QUOTE, "sales", FE.ValidationFailed),
            (C.ACTION_QUOTATION_SUBMIT, self.QUOTE, "owner", FE.AuthorizationDenied),
            (C.ACTION_SALES_ORDER_REQUEST_CHANGE, self.ORDER, "admin", FE.AuthorizationDenied),
            (C.APPROVAL_EXPEDITE_PURCHASE, self.QUOTE, "sales", FE.ValidationFailed),
        ):
            with self.subTest(kind=kind, user=user), self.assertRaises(error):
                self.backend.request_approval(principal(user), kind, ref, {}, justification="x")
            self.assertEqual(self._dump(), before)

    def test_binding_captures_operation_identity_payload_policy_and_versions(self):
        source = self.backend.get_record(principal("sales"), self.ORDER)
        approval = self._change()
        binding = json.loads(self.backend._db.execute(
            "SELECT binding FROM approval_bindings WHERE approval_id=?", (approval.approval_id,),
        ).fetchone()[0])
        target = self.backend.get_record(principal("sales"), self.ORDER)
        self.assertEqual(binding["source"]["id"], self.ORDER.record_id)
        self.assertEqual(binding["source"]["type"], C.RECORD_SALES_ORDER)
        self.assertEqual(binding["source"]["version"], source.ref.version)
        self.assertEqual(binding["source"]["state"], "confirmed")
        self.assertEqual(binding["target"]["version"], target.ref.version)
        self.assertEqual(target.ref.version, source.ref.version + 1)
        self.assertEqual(binding["target"]["state"], "change_pending")
        self.assertEqual(binding["kind"], C.ACTION_SALES_ORDER_REQUEST_CHANGE)
        self.assertEqual(binding["payload"], approval.payload)
        self.assertEqual(binding["roles"], [C.ROLE_OWNER])
        self.assertEqual(binding["policy"]["approver_role"], C.ROLE_OWNER)

    def test_factory_cannot_decide_owner_price_change_and_owner_can(self):
        approval = self._change()
        before = self._dump()
        for method in (self.backend.approve, self.backend.reject):
            with self.assertRaises(FE.AuthorizationDenied):
                method(principal("factory"), approval.approval_id)
            self.assertEqual(self._dump(), before)
        self.assertNotIn(approval.approval_id,
                         [a.approval_id for a in self.backend.list_approvals(principal("factory"))])
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.get_approval(principal("factory"), approval.approval_id)
        self.backend.approve(principal("owner"), approval.approval_id)
        order = self.backend.get_record(principal("sales"), self.ORDER)
        self.assertEqual(order.fields["state"], "confirmed")
        self.assertEqual(order.fields["total_amount"], 12340)
        self.assertEqual(order.fields["qty"], 1000)
        self.assertEqual(order.fields["unit_price"], 12.34)
        lines = self.backend.list_records(principal("sales"), C.RECORD_SALES_ORDER_LINE,
                                          filters={"order_id": self.ORDER.record_id})
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].fields["unit_price"], 12.34)

    def test_matched_factory_policy_does_not_inherit_generic_owner_override(self):
        approval = self._change(price=False)
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.approve(principal("owner"), approval.approval_id)
        self.backend.approve(principal("factory"), approval.approval_id)
        order = self.backend.get_record(principal("sales"), self.ORDER)
        self.assertEqual(order.fields["requested_date"], "2026-12-01")
        self.assertEqual(order.fields["state"], "confirmed")

    def test_requester_cannot_self_approve_with_new_or_forged_role(self):
        approval_id = self._submit_golden_quote()
        forged = replace(principal("sales"), role=C.ROLE_OWNER)
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.approve(forged, approval_id)
        self.backend._db.execute("UPDATE users SET role=? WHERE actor_id='sales'", (C.ROLE_OWNER,))
        self.backend._db.commit()
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.approve(self.backend._principal_of("sales"), approval_id)
        self.assertEqual(self._approval(approval_id).status, "pending")

    def test_payload_substitution_is_rejected_before_any_decision(self):
        approval = self._change()
        self._mutate_approval(approval.approval_id, "payload",
                              json.dumps({"price_change": True, "fields_delta": {"total_amount": 1}}))
        self._assert_failed_decision_is_atomic(approval.approval_id)

    def test_target_identity_action_and_requester_substitution_rejected(self):
        approval = self._change()
        for column, value in (("target_id", "SO-2026-0141"),
                              ("target_type", C.RECORD_CUSTOMER),
                              ("kind", C.ACTION_SALES_ORDER_CONFIRM),
                              ("requested_by", "sales2")):
            row = self.backend._db.execute("SELECT * FROM approvals WHERE id=?",
                                            (approval.approval_id,)).fetchone()
            with self.subTest(column=column):
                self._mutate_approval(approval.approval_id, column, value)
                self._assert_failed_decision_is_atomic(approval.approval_id)
                self._mutate_approval(approval.approval_id, column, row[column])

    def test_binding_role_substitution_and_missing_or_malformed_binding_fail_closed(self):
        approval = self._change()
        original = self.backend._db.execute(
            "SELECT binding FROM approval_bindings WHERE approval_id=?", (approval.approval_id,),
        ).fetchone()[0]
        forged = json.loads(original)
        forged["roles"] = [C.ROLE_FACTORY]
        for encoded in (json.dumps(forged), "[]", "{}", "bad"):
            with self.subTest(binding=encoded):
                self.backend._db.execute("UPDATE approval_bindings SET binding=? WHERE approval_id=?",
                                         (encoded, approval.approval_id))
                self.backend._db.commit()
                self._assert_failed_decision_is_atomic(approval.approval_id)
        self.backend._db.execute("DELETE FROM approval_bindings WHERE approval_id=?", (approval.approval_id,))
        self.backend._db.commit()
        self._assert_failed_decision_is_atomic(approval.approval_id)

    def test_public_payload_cannot_supply_binding_or_policy(self):
        before = self._dump()
        for field in ("approval_binding", "approved_by", "_policy"):
            with self.subTest(field=field), self.assertRaises(FE.ValidationFailed):
                self.backend.request_approval(principal("sales"), C.ACTION_QUOTATION_SUBMIT,
                                              self.QUOTE, {field: "forged"}, justification="x")
        self.assertEqual(self._dump(), before)

    def test_stale_admission_ref_rejected(self):
        quote = self.backend.get_record(principal("sales"), self.QUOTE)
        self.backend.update_record(principal("sales"), quote.ref, {"note": "new version"},
                                    expected_version=quote.ref.version)
        before = self._dump()
        with self.assertRaises(FE.VersionConflict):
            self.backend.request_approval(principal("sales"), C.ACTION_QUOTATION_SUBMIT,
                                          quote.ref, {}, justification="stale")
        self.assertEqual(self._dump(), before)

    def test_stale_decision_cannot_overwrite_newer_target(self):
        approval_id = self._submit_golden_quote()
        quote = self.backend.get_record(principal("sales"), self.QUOTE)
        self.backend.update_record(principal("sales"), quote.ref, {"note": "newer edit"},
                                    expected_version=quote.ref.version)
        self._assert_failed_decision_is_atomic(approval_id, FE.VersionConflict)

    def test_changed_terminal_state_or_missing_target_rejected_without_rewrite(self):
        approval_id = self._submit_golden_quote()
        row = self.backend._get_row(self.QUOTE.record_type, self.QUOTE.record_id)
        fields = json.loads(row["fields"])
        fields["state"] = "rejected"
        self.backend._db.execute("UPDATE records SET fields=? WHERE record_type=? AND id=?",
                                 (json.dumps(fields), self.QUOTE.record_type, self.QUOTE.record_id))
        self.backend._db.commit()
        self._assert_failed_decision_is_atomic(approval_id)
        self.backend._db.execute("DELETE FROM records WHERE record_type=? AND id=?",
                                 (self.QUOTE.record_type, self.QUOTE.record_id))
        self.backend._db.commit()
        self._assert_failed_decision_is_atomic(approval_id)

    def test_duplicate_requests_and_rejected_quote_cannot_be_resurrected(self):
        approval = self.backend.request_approval(principal("sales"), C.ACTION_QUOTATION_SUBMIT,
                                                 self.QUOTE, {}, justification="first")
        before = self._dump()
        for method in (self.backend.request_approval, self.backend.execute_business_action):
            with self.assertRaises((FE.ValidationFailed, FE.DuplicateRequest)):
                if method == self.backend.request_approval:
                    method(principal("sales"), C.ACTION_QUOTATION_SUBMIT, self.QUOTE, {}, justification="second")
                else:
                    method(principal("sales"), self.QUOTE, C.ACTION_QUOTATION_SUBMIT, {})
            self.assertEqual(self._dump(), before)
        self.backend.reject(principal("owner"), approval.approval_id)
        with self.assertRaises(FE.ValidationFailed):
            self.backend.approve(principal("owner"), approval.approval_id)
        with self.assertRaises(FE.ValidationFailed):
            self.backend.request_approval(principal("sales"), C.ACTION_QUOTATION_SUBMIT,
                                          self.QUOTE, {}, justification="revive")
        self.assertEqual(self.backend.get_record(principal("sales"), self.QUOTE).fields["state"], "rejected")

    def test_concurrent_admissions_leave_one_gate_and_no_resurrection(self):
        def request():
            return self.backend.request_approval(principal("sales"), C.ACTION_QUOTATION_SUBMIT,
                                                  self.QUOTE, {}, justification="competing")
        results = self._parallel([request, request])
        admitted = [r for r in results if not isinstance(r, Exception)]
        denied = [r for r in results if isinstance(r, Exception)]
        self.assertEqual(len(admitted), 1)
        self.assertEqual(len(denied), 1)
        self.assertIsInstance(denied[0], (FE.ValidationFailed, FE.DuplicateRequest))
        self.backend.reject(principal("owner"), admitted[0].approval_id)
        with self.assertRaises(FE.ValidationFailed):
            self.backend.approve(principal("owner"), admitted[0].approval_id)
        rows = self.backend._db.execute("SELECT status FROM approvals WHERE target_id=?",
                                         (self.QUOTE.record_id,)).fetchall()
        self.assertEqual([r[0] for r in rows], ["rejected"])

    def test_concurrent_approve_reject_decides_exactly_once(self):
        approval_id = self._submit_golden_quote()
        pending = self.backend.get_record(principal("sales"), self.QUOTE)
        results = self._parallel([
            lambda: self.backend.approve(principal("owner"), approval_id),
            lambda: self.backend.reject(principal("owner"), approval_id),
        ])
        successful = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        self.assertEqual(len(successful), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], FE.ValidationFailed)
        quote = self.backend.get_record(principal("sales"), self.QUOTE)
        self.assertEqual(quote.fields["state"], successful[0].status)
        self.assertEqual(quote.ref.version, pending.ref.version + 1)
        self.assertEqual(self.backend._db.execute("SELECT COUNT(*) FROM evidence WHERE approval_id=?",
                                                  (approval_id,)).fetchone()[0], 2)

    def test_admission_failure_rolls_back_notifications_gate_binding_and_counters(self):
        original = self.backend.notify
        before = self._dump()

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected admission failure")

        with patch.object(self.backend, "notify", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "admission failure"):
                self._submit_golden_quote()
        self.assertEqual(self._dump(), before)

    def test_approve_and_reject_failure_roll_back_entire_decision(self):
        approval_id = self._submit_golden_quote()
        for helper, method in (("_resume_approved", self.backend.approve),
                               ("_apply_rejection", self.backend.reject)):
            original = getattr(self.backend, helper)
            before = self._dump()

            def fail(view):
                original(view)
                raise RuntimeError("injected after business writes")

            with self.subTest(helper=helper), patch.object(self.backend, helper, side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, "after business writes"):
                    method(principal("owner"), approval_id)
            self.assertEqual(self._dump(), before)

    def test_authority_and_target_are_rechecked_immediately_before_resume(self):
        approval_id = self._submit_golden_quote()
        original = self.backend._resume_approved
        before = self._dump()

        def revoke_then_resume(view):
            self.backend._db.execute("UPDATE users SET role=? WHERE actor_id='owner'", (C.ROLE_FACTORY,))
            original(view)

        with patch.object(self.backend, "_resume_approved", side_effect=revoke_then_resume):
            with self.assertRaises(FE.AuthorizationDenied):
                self.backend.approve(principal("owner"), approval_id)
        self.assertEqual(self._dump(), before)

        def alter_then_resume(view):
            rec = self.backend.get_record(principal("sales"), self.QUOTE)
            self.backend._put_record("sales", self.QUOTE.record_type, self.QUOTE.record_id,
                                      rec.fields, bump_version_from=rec.ref.version)
            original(view)

        with patch.object(self.backend, "_resume_approved", side_effect=alter_then_resume):
            with self.assertRaises(FE.VersionConflict):
                self.backend.approve(principal("owner"), approval_id)
        self.assertEqual(self._dump(), before)

    def test_standalone_purchase_binding_and_task_side_effects_are_atomic(self):
        approval = self.backend.request_approval(principal("sales"), C.APPROVAL_EXPEDITE_PURCHASE,
                                                 self.ORDER, {"material_id": "MAT-0001", "qty": 20},
                                                 justification="purchase")
        original = self.backend._resume_approved
        before = self._dump()

        def fail(view):
            original(view)
            raise RuntimeError("injected after task creation")

        with patch.object(self.backend, "_resume_approved", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.backend.approve(principal("owner"), approval.approval_id)
        self.assertEqual(self._dump(), before)
        count = self.backend._db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        self.backend.approve(principal("owner"), approval.approval_id)
        self.assertEqual(self.backend._db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], count + 1)
        with self.assertRaises(FE.ValidationFailed):
            self.backend.approve(principal("owner"), approval.approval_id)
        self.assertEqual(self.backend._db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], count + 1)

    def test_child_production_approval_binds_parent_and_child_and_enforces_sod(self):
        self.backend._provision_user(UserBootstrap("factory2", "Second factory approver", C.ROLE_FACTORY))
        result = self.backend.execute_business_action(principal("factory"), self.ORDER,
            C.ACTION_PRODUCTION_ORDER_CREATE, {"expedite": True, "qty": 10})
        self.assertEqual(result.ref.record_type, C.RECORD_PRODUCTION_ORDER)
        self.assertEqual(result.state, "pending_approval")
        with self.assertRaises(FE.AuthorizationDenied):
            self.backend.approve(principal("factory"), result.approval_id)
        second = self.backend._principal_of("factory2")
        self.backend.approve(second, result.approval_id)
        child = self.backend.get_record(principal("owner"), result.ref)
        self.assertEqual(child.fields["state"], "planned")
        self.assertEqual(child.fields["order_id"], self.ORDER.record_id)
        other = self.backend.execute_business_action(principal("factory"), self.ORDER,
            C.ACTION_PRODUCTION_ORDER_CREATE, {"expedite": True, "qty": 10})
        self.backend.reject(second, other.approval_id)
        self.assertEqual(self.backend.get_record(principal("owner"), other.ref).fields["state"], "cancelled")

    def test_child_approval_cannot_resume_after_parent_version_changes(self):
        self.backend._provision_user(UserBootstrap("factory2", "Second factory approver", C.ROLE_FACTORY))
        result = self.backend.execute_business_action(principal("factory"), self.ORDER,
            C.ACTION_PRODUCTION_ORDER_CREATE, {"expedite": True, "qty": 10})
        order = self.backend.get_record(principal("sales"), self.ORDER)
        self.backend.update_record(principal("sales"), order.ref, {"note": "parent changed"},
                                    expected_version=order.ref.version)
        before = self._dump()
        with self.assertRaises(FE.VersionConflict):
            self.backend.approve(self.backend._principal_of("factory2"), result.approval_id)
        self.assertEqual(self._dump(), before)

    def test_inventory_approval_resumes_once_without_erasing_active_state(self):
        # Lifecycle/role coverage uses an explicit percentage-only policy.
        # Default monetary-risk functionality is blocked without owner-approved valuation.
        from app import policy
        from framework_port.dtos import ApprovalPolicy
        self.backend.configure_authorization(policy._RULES,
            (ApprovalPolicy(C.ACTION_INVENTORY_ADJUST,
                            {"field": "adjust_pct", "op": ">", "value": 5}, C.ROLE_OWNER),),
            policy.APPROVER_ROLES)
        ref = RecordRef(C.RECORD_INVENTORY_ITEM, "INV-0001")
        item = self.backend.get_record(principal("warehouse"), ref)
        result = self.backend.execute_business_action(principal("warehouse"), ref,
            C.ACTION_INVENTORY_ADJUST, {"adjust_qty": 10})
        self.assertIsNotNone(result.approval_id)
        self.assertEqual(self.backend.get_record(principal("warehouse"), ref), item)
        self.backend.approve(principal("owner"), result.approval_id)
        after = self.backend.get_record(principal("warehouse"), ref)
        self.assertEqual(after.fields["qty_on_hand"], item.fields["qty_on_hand"] + 10)
        self.assertEqual(after.fields["state"], item.fields["state"])
        with self.assertRaises(FE.ValidationFailed):
            self.backend.approve(principal("owner"), result.approval_id)
        self.assertEqual(self.backend.get_record(principal("warehouse"), ref), after)

    def test_current_requester_authority_and_policy_are_rechecked(self):
        approval = self._change()
        from app import policy
        from framework_port.dtos import ApprovalPolicy
        self.backend.configure_authorization(policy._RULES,
            (ApprovalPolicy(C.ACTION_SALES_ORDER_REQUEST_CHANGE, {"op": "always"}, C.ROLE_FACTORY),),
            policy.APPROVER_ROLES)
        self._assert_failed_decision_is_atomic(approval.approval_id, FE.AuthorizationDenied)
        self.backend.configure_authorization(policy._RULES, policy.APPROVAL_POLICIES, policy.APPROVER_ROLES)
        self.backend._db.execute("UPDATE users SET role=? WHERE actor_id='sales'", (C.ROLE_WAREHOUSE,))
        self.backend._db.commit()
        self._assert_failed_decision_is_atomic(approval.approval_id, FE.AuthorizationDenied)

    def test_payload_is_frozen_and_resume_rejects_substituted_view_and_replay(self):
        payload = {"price_change": False, "fields_delta": {"requested_date": "2026-12-01"}}
        approval = self.backend.request_approval(principal("sales"), C.ACTION_SALES_ORDER_REQUEST_CHANGE,
                                                 self.ORDER, payload, justification="freeze")
        payload["fields_delta"]["requested_date"] = "2099-01-01"
        decided = self.backend.approve(principal("factory"), approval.approval_id)
        self.assertEqual(self.backend.get_record(principal("sales"), self.ORDER).fields["requested_date"], "2026-12-01")
        before = self._dump()
        with self.assertRaises(FE.ValidationFailed):
            self.backend._resume_approved(decided)
        with self.backend._lock, self.backend._approval_transaction():
            with self.assertRaises(FE.ValidationFailed):
                self.backend._resume_approved(replace(decided, target=self.QUOTE))
            with self.assertRaises(FE.VersionConflict):
                self.backend._resume_approved(decided)
        self.assertEqual(self._dump(), before)

    def test_rejected_or_unproven_decisions_cannot_be_resumed(self):
        approval_id = self._submit_golden_quote()
        rejected = self.backend.reject(principal("owner"), approval_id)
        before = self._dump()
        with self.backend._lock, self.backend._approval_transaction():
            with self.assertRaises(FE.ValidationFailed):
                self.backend._resume_approved(rejected)
        self.assertEqual(self._dump(), before)
        other = self._change()
        self.backend._db.execute("UPDATE approvals SET status='approved',decided_by='owner',decided_at=? WHERE id=?",
                                 (other.requested_at, other.approval_id))
        self.backend._db.commit()
        before = self._dump()
        with self.backend._lock, self.backend._approval_transaction():
            with self.assertRaises(FE.ValidationFailed):
                self.backend._resume_approved(self._approval(other.approval_id))
        self.assertEqual(self._dump(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
