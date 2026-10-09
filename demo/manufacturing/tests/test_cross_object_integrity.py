"""GAF-04D: production admission and atomic parent-order transitions."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_contract import ContractTestBase, principal
from framework_port import constants as C, errors as FE
from framework_port.dtos import RecordRef, UserBootstrap


class CrossObjectIntegrityTests(ContractTestBase):
    ORDER = RecordRef(C.RECORD_SALES_ORDER, "SO-2026-0135")
    PENDING = RecordRef(C.RECORD_SALES_ORDER, "SO-2026-0150")

    def _record(self, ref):
        return self.backend.get_record(principal("owner"), ref)

    def _dump(self):
        return list(self.backend._db.iterdump())

    def _reject(self, operation, error=FE.FacadeError):
        before = self._dump()
        with self.assertRaises(error):
            operation()
        self.assertEqual(self._dump(), before)
        self.assertFalse(self.backend._db.in_transaction)
        self.assertEqual(self.backend._approval_depth, 0)

    def _payload(self, **extra):
        return {"product_id": "PROD-0005", "qty": 10, "expedite": False,
                "substitute": False, "due_date": "2026-10-20", **extra}

    def _create(self, parent=None, *, generic=False, **extra):
        parent = parent or self.ORDER
        data = self._payload(**extra)
        if generic:
            return self.backend.create_record(principal("factory"), C.RECORD_PRODUCTION_ORDER,
                                               {"order_id": parent.record_id, **data})
        return self.backend.execute_business_action(principal("factory"), self._record(parent).ref,
                                                     C.ACTION_PRODUCTION_ORDER_CREATE, data)

    def _action(self, ref, action, payload=None, user="factory"):
        return self.backend.execute_business_action(principal(user), self._record(ref).ref,
                                                     action, payload or {})

    def _working(self, ref):
        self._action(ref, C.ACTION_PRODUCTION_ORDER_RELEASE)
        self._action(ref, C.ACTION_PRODUCTION_ORDER_ISSUE_MATERIAL, user="warehouse")

    def _second_factory(self):
        self.backend._provision_user(UserBootstrap("factory2", "Second factory", C.ROLE_FACTORY))
        return self.backend._principal_of("factory2")

    def _pending_confirmation(self):
        return next(a for a in self.backend.list_approvals(principal("owner"), pending_for_me=False)
                    if a.kind == C.ACTION_SALES_ORDER_CONFIRM and a.target.record_id == self.PENDING.record_id)

    def test_f1_pending_parent_rejected_at_generic_and_specialized_creation(self):
        approval = self._pending_confirmation()
        for generic in (False, True):
            self._reject(lambda: self._create(self.PENDING, generic=generic), FE.ValidationFailed)
        self.assertEqual(self._record(self.PENDING).fields["state"], "pending_approval")
        self.assertEqual(self.backend.get_approval(principal("owner"), approval.approval_id).status, "pending")

    def test_rejected_confirmation_cannot_admit_production(self):
        approval = self._pending_confirmation()
        self.backend.reject(principal("owner"), approval.approval_id)
        self._reject(lambda: self._create(self.PENDING, generic=True), FE.ValidationFailed)
        self.assertEqual(self._record(self.PENDING).fields["state"], "draft")
        self.assertEqual(self.backend.get_approval(principal("owner"), approval.approval_id).status, "rejected")

    def test_creation_requires_existing_sales_order_and_action_authority(self):
        for parent in ("missing", "CUST-0001", ""):
            self._reject(lambda: self.backend.create_record(principal("factory"), C.RECORD_PRODUCTION_ORDER,
                {"order_id": parent, **self._payload()}))
        self._reject(lambda: self.backend.execute_business_action(principal("factory"),
            RecordRef(C.RECORD_CUSTOMER, "CUST-0001"), C.ACTION_PRODUCTION_ORDER_CREATE, self._payload()))
        for user in ("sales", "warehouse", "admin"):
            self._reject(lambda: self.backend.create_record(principal(user), C.RECORD_PRODUCTION_ORDER,
                {"order_id": self.ORDER.record_id, **self._payload()}), FE.AuthorizationDenied)

    def test_f2_generic_expedite_and_substitution_cannot_skip_approval(self):
        for flags in ({"expedite": True}, {"substitute": True}, {"expedite": True, "substitute": True}):
            self._reject(lambda: self._create(generic=True, **flags), FE.ValidationFailed)

    def test_creation_cannot_supply_relationship_delta_or_nonboolean_policy_flags(self):
        for data in ({"fields_delta": {"order_id": self.PENDING.record_id}},
                     {"order_id": self.PENDING.record_id}, {"expedite": "true"}, {"substitute": 1}):
            self._reject(lambda: self._create(**data), FE.ValidationFailed)

    def test_f3_progress_cannot_reparent_historical_work_order(self):
        ref = RecordRef(C.RECORD_PRODUCTION_ORDER, "PO-2026-0092")
        self._reject(lambda: self._action(ref, C.ACTION_PRODUCTION_ORDER_REPORT_PROGRESS,
            {"fields_delta": {"order_id": self.PENDING.record_id, "qty": 1, "progress_pct": 100}}), FE.ValidationFailed)
        self.assertEqual(self._record(self.PENDING).fields["state"], "pending_approval")
        self.assertEqual(self._record(ref).fields["order_id"], "SO-2026-0136")

    def test_production_identity_and_policy_content_are_immutable_publicly(self):
        po = self._create(generic=True)
        for fields in ({"order_id": self.PENDING.record_id}, {"expedite": True}, {"substitute": True},
                       {"qty": 1}, {"product_id": "PROD-0001"}, {"_production_binding": {}}):
            self._reject(lambda: self.backend.update_record(principal("factory"), po.ref, fields,
                expected_version=po.ref.version), FE.ValidationFailed)
            self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE,
                {"fields_delta": fields}), FE.ValidationFailed)

    def test_valid_generic_creation_release_progress_and_completion(self):
        po = self._create(generic=True)
        self._working(po.ref)
        progress = self._action(po.ref, C.ACTION_PRODUCTION_ORDER_REPORT_PROGRESS, {"progress_pct": 50})
        self.assertEqual(self._record(po.ref).fields["progress_pct"], 50)
        self.assertEqual(progress.ref, self._record(po.ref).ref)
        self._action(po.ref, C.ACTION_PRODUCTION_ORDER_REPORT_PROGRESS, {"fields_delta": {"progress_pct": 100}})
        done = self._action(po.ref, C.ACTION_PRODUCTION_ORDER_COMPLETE)
        self.assertEqual(done.ref, self._record(po.ref).ref)
        self.assertEqual(self._record(po.ref).fields["state"], "completed")
        self.assertEqual(self._record(self.ORDER).fields["state"], "ready_to_ship")
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_COMPLETE), FE.ValidationFailed)

    def test_owner_approved_parent_has_legitimate_specialized_workflow(self):
        approval = self._pending_confirmation()
        self.backend.approve(principal("owner"), approval.approval_id)
        po = self._create(self.PENDING)
        self._working(po.ref)
        self._action(po.ref, C.ACTION_PRODUCTION_ORDER_COMPLETE)
        self.assertEqual(self._record(self.PENDING).fields["state"], "ready_to_ship")
        self.assertEqual(self.backend.get_approval(principal("owner"), approval.approval_id).status, "approved")

    def test_expedite_and_substitute_require_independent_factory_approval(self):
        second = self._second_factory()
        po = self._create(expedite=True, substitute=True)
        self.assertEqual(po.state, "pending_approval")
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE))
        self._reject(lambda: self.backend.approve(principal("factory"), po.approval_id), FE.AuthorizationDenied)
        self._reject(lambda: self.backend.approve(principal("owner"), po.approval_id), FE.AuthorizationDenied)
        self.backend.approve(second, po.approval_id)
        self._working(po.ref)
        self._action(po.ref, C.ACTION_PRODUCTION_ORDER_COMPLETE)
        self.assertEqual(self._record(self.ORDER).fields["state"], "ready_to_ship")
        self.assertTrue(self.backend.verify_evidence_chain(second, RecordRef("approval", po.approval_id)).verified)

    def test_rejected_production_approval_cannot_release_or_advance_parent(self):
        po = self._create(substitute=True)
        self.backend.reject(self._second_factory(), po.approval_id)
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE), FE.ValidationFailed)
        self.assertEqual(self._record(po.ref).fields["state"], "cancelled")
        self.assertEqual(self._record(self.ORDER).fields["state"], "confirmed")

    def test_parent_note_version_change_stales_release(self):
        po = self._create()
        parent = self._record(self.ORDER)
        self.backend.update_record(principal("sales"), parent.ref, {"note": "new version"},
                                   expected_version=parent.ref.version)
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE), FE.VersionConflict)

    def test_parent_note_version_change_stales_completion(self):
        po = self._create()
        self._working(po.ref)
        parent = self._record(self.ORDER)
        self.backend.update_record(principal("sales"), parent.ref, {"note": "new version"},
                                   expected_version=parent.ref.version)
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_COMPLETE), FE.VersionConflict)

    def test_pending_order_change_blocks_creation_and_existing_release(self):
        po = self._create()
        self.backend.request_approval(principal("sales"), C.ACTION_SALES_ORDER_REQUEST_CHANGE,
            self.ORDER, {"price_change": False, "fields_delta": {"requested_date": "2026-12-01"}}, justification="date")
        self._reject(lambda: self._create(generic=True))
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE))

    def test_rejected_order_change_preserves_original_authorized_workflow(self):
        gate = self.backend.request_approval(principal("sales"), C.ACTION_SALES_ORDER_REQUEST_CHANGE,
            self.ORDER, {"price_change": False, "fields_delta": {"requested_date": "2026-12-01"}}, justification="date")
        self.backend.reject(principal("factory"), gate.approval_id)
        po = self._create()
        self._working(po.ref)
        self.assertEqual(self._record(self.ORDER).fields["state"], "in_production")

    def test_parent_terminal_or_invalid_states_cannot_release_or_complete(self):
        po = self._create()
        parent = self._record(self.ORDER)
        for state in ("draft", "pending_approval", "change_pending", "rejected", "cancelled", "closed", "ready_to_ship"):
            # Model an existing invalid persisted parent, without authorizing its repair.
            self.backend._put_record("system", parent.ref.record_type, parent.ref.record_id,
                                     {**parent.fields, "state": state}, bump_version_from=parent.ref.version)
            self.backend._db.commit()
            self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE))
            self.assertEqual(self._record(self.ORDER).fields["state"], state)

    def test_deleted_parent_fails_without_partial_writes(self):
        po = self._create()
        self.backend._db.execute("DELETE FROM records WHERE record_type=? AND id=?",
                                 (self.ORDER.record_type, self.ORDER.record_id))
        self.backend._db.commit()
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE))

    def test_legacy_unbound_work_orders_are_not_silently_repaired(self):
        ref = RecordRef(C.RECORD_PRODUCTION_ORDER, "PO-2026-0092")
        self.assertNotIn("_production_binding", self._record(ref).fields)
        self._reject(lambda: self._action(ref, C.ACTION_PRODUCTION_ORDER_COMPLETE), FE.ValidationFailed)

    def test_missing_parent_approval_evidence_blocks_creation(self):
        gate = self._pending_confirmation()
        self.backend.approve(principal("owner"), gate.approval_id)
        self.backend._db.execute("DELETE FROM approval_bindings WHERE approval_id=?", (gate.approval_id,))
        self.backend._db.commit()
        self._reject(lambda: self._create(self.PENDING), FE.ValidationFailed)

    def test_changed_decider_role_blocks_parent_side_effect(self):
        gate = self._pending_confirmation()
        self.backend.approve(principal("owner"), gate.approval_id)
        po = self._create(self.PENDING)
        self.backend._db.execute("UPDATE users SET role=? WHERE actor_id=?", (C.ROLE_FACTORY, "owner"))
        self.backend._db.commit()
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE), FE.AuthorizationDenied)

    def test_stale_production_ref_cannot_release(self):
        po = self._create()
        self.backend.update_record(principal("factory"), po.ref, {"note": "version"}, expected_version=po.ref.version)
        self._reject(lambda: self.backend.execute_business_action(principal("factory"), po.ref,
            C.ACTION_PRODUCTION_ORDER_RELEASE, {}), FE.VersionConflict)

    def test_parent_revalidated_immediately_before_side_effect(self):
        po = self._create()
        original = self.backend._advance_production_parent
        def change_then_apply(actor, work, action, state):
            parent = self._record(self.ORDER)
            self.backend._put_record("system", parent.ref.record_type, parent.ref.record_id,
                                     {**parent.fields, "note": "intervening"}, bump_version_from=parent.ref.version)
            return original(actor, work, action, state)
        with patch.object(self.backend, "_advance_production_parent", side_effect=change_then_apply):
            self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE), FE.VersionConflict)

    def test_failure_after_parent_and_child_writes_rolls_back_all_records_and_tasks(self):
        po = self._create()
        self._working(po.ref)
        original = self.backend.notify
        def fail(actor, kind, *args, **kwargs):
            if kind == "production.completed":
                raise RuntimeError("local test failure after cross-object writes")
            return original(actor, kind, *args, **kwargs)
        with patch.object(self.backend, "notify", side_effect=fail):
            self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_COMPLETE), RuntimeError)

    def test_concurrent_release_uses_parent_and_work_order_versions_once(self):
        po = self._create()
        ref = self._record(po.ref).ref
        barrier = threading.Barrier(3)
        results = []
        def release():
            barrier.wait(5)
            try:
                results.append(self.backend.execute_business_action(principal("factory"), ref,
                    C.ACTION_PRODUCTION_ORDER_RELEASE, {}))
            except FE.FacadeError as exc:
                results.append(exc)
        threads = [threading.Thread(target=release) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait(5)
        for thread in threads:
            thread.join(5)
        self.assertTrue(all(not t.is_alive() for t in threads))
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(not isinstance(r, Exception) for r in results), 1)
        self.assertEqual(sum(isinstance(r, FE.VersionConflict) for r in results), 1)
        self.assertEqual(self._record(self.ORDER).fields["state"], "in_production")
        count = self.backend._db.execute("SELECT COUNT(*) FROM tasks WHERE related_id=? AND kind='material_issue'",
                                        (po.ref.record_id,)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_rescheduling_and_note_edits_remain_available(self):
        po = self._create()
        updated = self.backend.update_record(principal("factory"), po.ref,
            {"due_date": "2026-11-01", "note": "schedule"}, expected_version=po.ref.version)
        self.assertEqual(updated.fields["due_date"], "2026-11-01")
        self._action(updated.ref, C.ACTION_PRODUCTION_ORDER_RELEASE)

    def test_http_release_and_progress_use_valid_production_payloads(self):
        from app.http_server import DemoApp, SESSION_COOKIE
        po = self._create()
        token = self.backend.create_session(principal("factory"))
        app = DemoApp(self.backend, "public")
        headers = {"Cookie": f"{SESSION_COOKIE}={token}"}
        response = app.handle("POST", f"/production/{po.ref.record_id}/release", {}, {}, headers)
        self.assertEqual(response[0], 303)
        self._action(po.ref, C.ACTION_PRODUCTION_ORDER_ISSUE_MATERIAL, user="warehouse")
        response = app.handle("POST", f"/production/{po.ref.record_id}/progress", {}, {"progress_pct": "100"}, headers)
        self.assertEqual(response[0], 303)
        self.assertEqual(self._record(po.ref).fields["progress_pct"], 100)
        response = app.handle("POST", f"/production/{po.ref.record_id}/complete", {}, {}, headers)
        self.assertEqual(response[0], 303)
        self.assertEqual(self._record(self.ORDER).fields["state"], "ready_to_ship")

    def test_competing_pending_production_approval_blocks_creation_and_release(self):
        ordinary = self._create()
        gated = self._create(expedite=True)
        self._reject(lambda: self._create(generic=True))
        self._reject(lambda: self._action(ordinary.ref, C.ACTION_PRODUCTION_ORDER_RELEASE))
        self.assertEqual(self.backend.get_approval(principal("owner"), gated.approval_id).status, "pending")
        self.assertEqual(self._record(self.ORDER).fields["state"], "confirmed")

    def test_new_policy_requirement_cannot_be_skipped_by_existing_planned_work(self):
        from app import policy
        from framework_port.dtos import ApprovalPolicy
        po = self._create()
        self.backend.configure_authorization(policy._RULES,
            (ApprovalPolicy(C.ACTION_PRODUCTION_ORDER_CREATE, {"op": "always"}, C.ROLE_FACTORY),)
            + policy.APPROVAL_POLICIES, policy.APPROVER_ROLES)
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE), FE.ValidationFailed)

    def test_approved_production_requires_preserved_decision_evidence(self):
        po = self._create(expedite=True)
        self.backend.approve(self._second_factory(), po.approval_id)
        self.backend._db.execute("DELETE FROM approval_bindings WHERE approval_id=?", (po.approval_id,))
        self.backend._db.commit()
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE), FE.ValidationFailed)

    def test_business_line_version_change_stales_production_dependency(self):
        po = self._create()
        line = self.backend.list_records(principal("owner"), C.RECORD_SALES_ORDER_LINE,
                                        filters={"order_id": self.ORDER.record_id})[0]
        self.backend._put_record("system", line.ref.record_type, line.ref.record_id,
                                 line.fields, bump_version_from=line.ref.version)
        self.backend._db.commit()
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE), FE.VersionConflict)

    def test_approved_owner_price_change_preserves_valid_production(self):
        gate = self.backend.request_approval(principal("sales"), C.ACTION_SALES_ORDER_REQUEST_CHANGE,
            self.ORDER, {"price_change": True, "fields_delta": {"unit_price": 12.34}}, justification="price")
        self.backend.approve(principal("owner"), gate.approval_id)
        po = self._create()
        self._working(po.ref)
        self._action(po.ref, C.ACTION_PRODUCTION_ORDER_COMPLETE)
        self.assertEqual(self._record(self.ORDER).fields["state"], "ready_to_ship")

    def test_invalid_parent_state_blocks_completion_without_any_side_effect(self):
        po = self._create()
        self._working(po.ref)
        parent = self._record(self.ORDER)
        self.backend._put_record("system", parent.ref.record_type, parent.ref.record_id,
                                 {**parent.fields, "state": "rejected"}, bump_version_from=parent.ref.version)
        self.backend._db.commit()
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_COMPLETE))
        self.assertEqual(self._record(self.ORDER).fields["state"], "rejected")

    def test_creation_revalidates_parent_before_child_write(self):
        from backend_sim.actions import get_action
        spec = get_action(C.ACTION_PRODUCTION_ORDER_CREATE)
        original = spec.creates_child
        def change_then_create(engine, actor, parent, payload, **kwargs):
            engine._put_record("system", parent.ref.record_type, parent.ref.record_id,
                               {**parent.fields, "note": "intervening"}, bump_version_from=parent.ref.version)
            return original(engine, actor, parent, payload, **kwargs)
        with patch.object(spec, "creates_child", side_effect=change_then_create):
            self._reject(lambda: self._create(), FE.VersionConflict)

    def test_work_order_relationship_revalidated_before_parent_write(self):
        po = self._create()
        original = self.backend._advance_production_parent
        def change_then_apply(actor, work, action, state):
            live = self._record(work.ref)
            self.backend._put_record("system", live.ref.record_type, live.ref.record_id,
                {**live.fields, "order_id": self.PENDING.record_id}, bump_version_from=live.ref.version)
            return original(actor, work, action, state)
        with patch.object(self.backend, "_advance_production_parent", side_effect=change_then_apply):
            self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE), FE.VersionConflict)

    def test_current_parent_confirmation_requirement_needs_authoritative_decision(self):
        from app import policy
        from framework_port.dtos import ApprovalPolicy
        po = self._create()
        self.backend.configure_authorization(policy._RULES,
            (ApprovalPolicy(C.ACTION_SALES_ORDER_CONFIRM, {"op": "always"}, C.ROLE_OWNER),)
            + policy.APPROVAL_POLICIES, policy.APPROVER_ROLES)
        self._reject(lambda: self._create(generic=True), FE.AuthorizationDenied)
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE), FE.AuthorizationDenied)

    def test_new_valid_confirmation_after_rejection_allows_production_without_rewriting_old_decision(self):
        rejected = self._pending_confirmation()
        self.backend.reject(principal("owner"), rejected.approval_id)
        approved = self.backend.execute_business_action(principal("sales"), self._record(self.PENDING).ref,
            C.ACTION_SALES_ORDER_CONFIRM, {"justification": "new authorized request"})
        self.backend.approve(principal("owner"), approved.approval_id)
        po = self._create(self.PENDING)
        self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE)
        self.assertEqual(self._record(self.PENDING).fields["state"], "in_production")
        self.assertEqual(self.backend.get_approval(principal("owner"), rejected.approval_id).status, "rejected")

    def test_revoked_parent_execute_permission_blocks_cross_object_write(self):
        from app import policy
        po = self._create()
        rules = tuple(r for r in policy._RULES if not (
            r.role == C.ROLE_FACTORY and r.permission == C.PERM_EXECUTE and r.resource_type == C.RECORD_SALES_ORDER))
        self.backend.configure_authorization(rules, policy.APPROVAL_POLICIES, policy.APPROVER_ROLES)
        self._reject(lambda: self._action(po.ref, C.ACTION_PRODUCTION_ORDER_RELEASE), FE.AuthorizationDenied)
