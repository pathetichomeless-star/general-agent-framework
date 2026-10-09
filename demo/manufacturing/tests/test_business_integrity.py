"""GAF-04C: authoritative financial inputs and unknown inventory risk."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_contract import ContractTestBase, principal
from framework_port import constants as C, errors as FE
from framework_port.dtos import RecordRef, ApprovalPolicy


class BusinessIntegrityTests(ContractTestBase):
    QUOTE = RecordRef(C.RECORD_QUOTATION, "Q-2026-0148")
    ORDER = RecordRef(C.RECORD_SALES_ORDER, "SO-2026-0135")
    STOCK = RecordRef(C.RECORD_INVENTORY_ITEM, "INV-0001")

    def _dump(self):
        return list(self.backend._db.iterdump())

    def _reject(self, operation, error=FE.ValidationFailed):
        before = self._dump()
        with self.assertRaises(error):
            operation()
        self.assertEqual(self._dump(), before)

    def _record(self, ref):
        return self.backend.get_record(principal("owner"), ref)

    def _lines(self, rec):
        quote = rec.ref.record_type == C.RECORD_QUOTATION
        return self.backend.list_records(principal("sales"),
            C.RECORD_QUOTATION_LINE if quote else C.RECORD_SALES_ORDER_LINE,
            filters={"quotation_id" if quote else "order_id": rec.ref.record_id})

    def _create(self, kind, **extra):
        data = {"product_id": "PROD-0001", "qty": 2000, "currency": "CNY"}
        data.update({"discount_pct": 8} if kind == C.RECORD_QUOTATION else {"unit_price": 42.32})
        data.update(extra)
        rec = self.backend.create_record(principal("sales"), kind, data)
        quote = kind == C.RECORD_QUOTATION
        self.backend.create_record(principal("sales"),
            C.RECORD_QUOTATION_LINE if quote else C.RECORD_SALES_ORDER_LINE,
            {"quotation_id" if quote else "order_id": rec.ref.record_id,
             "product_id": rec.fields["product_id"], "qty": rec.fields["qty"],
             "unit_price": rec.fields["unit_price"], "currency": rec.fields["currency"]})
        return rec

    def _sql_fields(self, rec, fields, *, bump=False):
        self.backend._db.execute(
            "UPDATE records SET fields=?,version=? WHERE record_type=? AND id=?",
            (json.dumps({**rec.fields, **fields}), rec.ref.version + int(bump),
             rec.ref.record_type, rec.ref.record_id))
        self.backend._db.commit()

    def _catalog_price(self, price):
        ref = RecordRef(C.RECORD_PRICE_BOOK_ENTRY, "PB-0001")
        rec = self._record(ref)
        return self.backend.update_record(principal("owner"), rec.ref,
            {"unit_price": price}, expected_version=rec.ref.version)

    def _percent_only(self):
        # Explicit test-only policy. The application's monetary policy is never changed.
        from app import policy
        self.backend.configure_authorization(policy._RULES,
            (ApprovalPolicy(C.ACTION_INVENTORY_ADJUST,
                {"field": "adjust_pct", "op": ">", "value": 5}, C.ROLE_OWNER),),
            policy.APPROVER_ROLES)

    def _http(self, path, form, user="sales"):
        from app.http_server import DemoApp, SESSION_COOKIE
        token = self.backend.create_session(principal(user))
        return DemoApp(self.backend, "public").handle("POST", path, {}, form,
            {"Cookie": f"{SESSION_COOKIE}={token}"})

    def test_c1_client_reference_price_cannot_hide_eight_percent(self):
        self._reject(lambda: self.backend.create_record(principal("sales"), C.RECORD_QUOTATION,
            {"product_id": "PROD-0001", "qty": 2000, "list_price": 42.32,
             "unit_price": 42.32, "discount_pct": 0, "total_amount": 84640}))

    def test_c1_forged_zero_discount_with_real_reference_rejected(self):
        self._reject(lambda: self.backend.create_record(principal("sales"), C.RECORD_QUOTATION,
            {"product_id": "PROD-0001", "qty": 2000, "list_price": 46,
             "unit_price": 42.32, "discount_pct": 0, "total_amount": 84640}))

    def test_legitimate_negotiated_price_derives_owner_required_discount(self):
        quote = self._create(C.RECORD_QUOTATION, unit_price=42.32)
        self.assertEqual(quote.fields["total_amount"], 84640)
        result = self.backend.execute_business_action(principal("sales"), quote.ref,
            C.ACTION_QUOTATION_SUBMIT, {})
        self.assertEqual(result.state, "pending_approval")
        self._reject(lambda: self.backend.approve(principal("factory"), result.approval_id),
                     FE.AuthorizationDenied)
        self.backend.approve(principal("owner"), result.approval_id)
        approved = self._record(quote.ref)
        self.assertEqual(approved.fields["state"], "approved")
        accepted = self.backend.execute_business_action(principal("sales"), approved.ref,
            C.ACTION_QUOTATION_ACCEPT, {})
        order = self._record(accepted.ref)
        self.assertEqual((order.fields["qty"], order.fields["unit_price"], order.fields["total_amount"]),
                         (2000, 42.32, 84640))
        self.assertEqual([(line.fields["product_id"], line.fields["qty"], line.fields["unit_price"])
                          for line in self._lines(order)],
                         [(line.fields["product_id"], line.fields["qty"], line.fields["unit_price"])
                          for line in self._lines(approved)])

    def test_selling_price_without_declared_discount_is_supported(self):
        quote = self.backend.create_record(principal("sales"), C.RECORD_QUOTATION,
            {"product_id": "PROD-0001", "qty": 10, "unit_price": 42.32})
        self.assertEqual(quote.fields["discount_pct"], 8)
        self.assertEqual(quote.fields["list_price"], 46)

    def test_discount_threshold_exact_and_just_above(self):
        for unit, expected in ((43.70, "approved"), (43.69, "pending_approval")):
            with self.subTest(unit=unit):
                quote = self.backend.create_record(principal("sales"), C.RECORD_QUOTATION,
                    {"product_id": "PROD-0001", "qty": 10, "unit_price": unit})
                self.backend.create_record(principal("sales"), C.RECORD_QUOTATION_LINE,
                    {"quotation_id": quote.ref.record_id, "product_id": "PROD-0001",
                     "qty": 10, "unit_price": unit})
                result = self.backend.execute_business_action(principal("sales"), quote.ref,
                    C.ACTION_QUOTATION_SUBMIT, {})
                self.assertEqual(result.state, expected)

    def test_rounding_uses_actual_reduction_not_declared_percent(self):
        self._catalog_price(0.11)
        quote = self._create(C.RECORD_QUOTATION, qty=1, discount_pct=5)
        self.assertEqual(quote.fields["unit_price"], 0.10)
        result = self.backend.execute_business_action(principal("sales"), quote.ref,
            C.ACTION_QUOTATION_SUBMIT, {"discount_pct": 5})
        self.assertIsNotNone(result.approval_id)  # actual reduction is 9.09%, not 5%

    def test_half_cent_rounding_requires_owner_decision_without_mutation(self):
        self._catalog_price(1.01)
        self._reject(lambda: self._create(C.RECORD_QUOTATION, qty=3, discount_pct=50))
        self._reject(lambda: self._create(C.RECORD_SALES_ORDER, qty=0.5, unit_price=1.01))
        # Non-midpoint rounding is unambiguous under either proposed rule.
        quote = self._create(C.RECORD_QUOTATION, qty=3, discount_pct=25)
        self.assertEqual(quote.fields["unit_price"], 0.76)
        self.assertEqual(quote.fields["total_amount"], 2.28)

    def test_missing_ambiguous_or_inactive_price_authority_rejected(self):
        ref = RecordRef(C.RECORD_PRICE_BOOK_ENTRY, "PB-0001")
        catalog = self._record(ref)
        self._sql_fields(catalog, {"state": "inactive"})
        self._reject(lambda: self._create(C.RECORD_QUOTATION))
        self._sql_fields(catalog, {"state": "active"})
        self.backend.create_record(principal("owner"), C.RECORD_PRICE_BOOK_ENTRY,
            {"id": "PB-DUPLICATE", "product_id": "PROD-0001", "unit_price": 46, "currency": "CNY", "state": "active"})
        self._reject(lambda: self._create(C.RECORD_QUOTATION))

    def test_invalid_financial_numbers_missing_product_and_currency_are_atomic(self):
        base = {"product_id": "PROD-0001", "qty": 10, "list_price": 46,
                "unit_price": 42.32, "discount_pct": 8, "total_amount": 423.2}
        for field in ("qty", "list_price", "unit_price", "discount_pct", "total_amount"):
            for bad in ("bad", "NaN", "Infinity", float("nan"), float("inf"), True, None, -1):
                with self.subTest(field=field, value=bad):
                    self._reject(lambda: self.backend.create_record(principal("sales"),
                        C.RECORD_QUOTATION, {**base, field: bad}))
        for extra in ({"product_id": ""}, {"product_id": "MISSING"}, {"product_id": []}, {"currency": "USD"},
                      {"qty": 0}, {"unit_price": "42.321"}, {"total_amount": 0}):
            with self.subTest(extra=extra):
                self._reject(lambda: self.backend.create_record(principal("sales"),
                    C.RECORD_QUOTATION, {**base, **extra}))

    def test_c2_inconsistent_order_total_rejected_at_creation(self):
        self._reject(lambda: self.backend.create_record(principal("sales"), C.RECORD_SALES_ORDER,
            {"product_id": "PROD-0001", "qty": 2000, "unit_price": 42.32, "total_amount": 0}))

    def test_order_amount_threshold_uses_validated_line_total(self):
        for qty, unit, expected in ((2000, 42.32, "pending_approval"),
                                    (1000, 50, "confirmed"), (1, 50000.01, "pending_approval")):
            with self.subTest(qty=qty, unit=unit):
                order = self._create(C.RECORD_SALES_ORDER, qty=qty, unit_price=unit)
                result = self.backend.execute_business_action(principal("sales"), order.ref,
                    C.ACTION_SALES_ORDER_CONFIRM, {})
                self.assertEqual(result.state, expected)
                if result.approval_id:
                    self.backend.approve(principal("owner"), result.approval_id)
                    self.assertEqual(self._record(order.ref).fields["state"], "confirmed")

    def test_tampered_order_header_cannot_bypass_confirmation(self):
        order = self._create(C.RECORD_SALES_ORDER)
        self._sql_fields(order, {"total_amount": 0})
        self._reject(lambda: self.backend.execute_business_action(principal("sales"), order.ref,
            C.ACTION_SALES_ORDER_CONFIRM, {}))
        self._reject(lambda: self.backend.request_approval(principal("sales"),
            C.ACTION_SALES_ORDER_CONFIRM, order.ref, {}, justification="forged"))

    def test_c3_draft_edit_synchronizes_line_and_accepted_order(self):
        quote = self._record(self.QUOTE)
        old_line = self._lines(quote)[0]
        edited = self.backend.update_record(principal("sales"), quote.ref,
            {"qty": 1000, "discount_pct": 0}, expected_version=quote.ref.version)
        line = self._lines(edited)[0]
        self.assertEqual((edited.fields["qty"], edited.fields["unit_price"], edited.fields["total_amount"]),
                         (1000, 46, 46000))
        self.assertEqual((line.fields["qty"], line.fields["unit_price"]), (1000, 46))
        self.assertEqual(line.ref.version, old_line.ref.version + 1)
        self.backend.execute_business_action(principal("sales"), edited.ref, C.ACTION_QUOTATION_SUBMIT, {})
        result = self.backend.execute_business_action(principal("sales"), self._record(edited.ref).ref,
            C.ACTION_QUOTATION_ACCEPT, {})
        order = self._record(result.ref)
        accepted_line = self._lines(order)[0]
        self.assertEqual(order.fields["total_amount"], 46000)
        self.assertEqual(order.fields["unit_price"], 46)
        self.assertEqual((accepted_line.fields["qty"], accepted_line.fields["unit_price"]), (1000, 46))
        self.assertEqual(accepted_line.fields["qty"] * accepted_line.fields["unit_price"], order.fields["total_amount"])

    def test_stale_or_divergent_line_prevents_submit_edit_and_accept(self):
        quote = self._record(self.QUOTE)
        line = self._lines(quote)[0]
        self._sql_fields(line, {"qty": 1})
        self._reject(lambda: self.backend.execute_business_action(principal("sales"), quote.ref,
            C.ACTION_QUOTATION_SUBMIT, {}))
        self._reject(lambda: self.backend.update_record(principal("sales"), quote.ref,
            {"qty": 1000}, expected_version=quote.ref.version))
        self._sql_fields(quote, {"state": "approved"})
        self._reject(lambda: self.backend.execute_business_action(principal("sales"), quote.ref,
            C.ACTION_QUOTATION_ACCEPT, {}))

    def test_missing_and_extra_lines_cannot_be_guessed_or_copied(self):
        quote = self._record(self.QUOTE)
        line = self._lines(quote)[0]
        self._reject(lambda: self.backend.create_record(principal("sales"), C.RECORD_QUOTATION_LINE,
            {"quotation_id": quote.ref.record_id, "product_id": "PROD-0001", "qty": 2000, "unit_price": 42.32}))
        self.backend._db.execute("DELETE FROM records WHERE record_type=? AND id=?",
                                 (line.ref.record_type, line.ref.record_id))
        self.backend._db.commit()
        self._reject(lambda: self.backend.execute_business_action(principal("sales"), quote.ref,
            C.ACTION_QUOTATION_SUBMIT, {}))

    def test_direct_line_divergence_and_reparenting_are_rejected(self):
        rec = self.backend.create_record(principal("sales"), C.RECORD_QUOTATION,
            {"product_id": "PROD-0001", "qty": 10, "discount_pct": 8})
        for data in ({"qty": 11, "unit_price": 42.32, "product_id": "PROD-0001"},
                     {"qty": 10, "unit_price": 1, "product_id": "PROD-0001"},
                     {"qty": 10, "unit_price": 42.32, "product_id": "PROD-0002"}):
            self._reject(lambda: self.backend.create_record(principal("sales"), C.RECORD_QUOTATION_LINE,
                {"quotation_id": rec.ref.record_id, **data}))

    def test_order_draft_edit_updates_derived_total_and_line_atomically(self):
        order = self._create(C.RECORD_SALES_ORDER)
        updated = self.backend.update_record(principal("sales"), order.ref,
            {"qty": 1000}, expected_version=order.ref.version)
        self.assertEqual(updated.fields["total_amount"], 42320)
        self.assertEqual(self._lines(updated)[0].fields["qty"], 1000)
        self._reject(lambda: self.backend.update_record(principal("sales"), updated.ref,
            {"total_amount": 0}, expected_version=updated.ref.version))

    def test_owner_price_change_updates_header_and_line_with_derived_total(self):
        result = self.backend.execute_business_action(principal("sales"), self.ORDER,
            C.ACTION_SALES_ORDER_REQUEST_CHANGE,
            {"price_change": True, "fields_delta": {"unit_price": 22.01}})
        self._reject(lambda: self.backend.approve(principal("factory"), result.approval_id), FE.AuthorizationDenied)
        self.backend.approve(principal("owner"), result.approval_id)
        order = self._record(self.ORDER)
        self.assertEqual(order.fields["total_amount"], 22010)
        self.assertEqual(self._lines(order)[0].fields["unit_price"], 22.01)

    def test_arbitrary_order_change_total_is_rejected_without_weakening_role_rules(self):
        self._reject(lambda: self.backend.request_approval(principal("sales"),
            C.ACTION_SALES_ORDER_REQUEST_CHANGE, self.ORDER,
            {"price_change": True, "fields_delta": {"total_amount": 1}}, justification="invalid"))
        self._reject(lambda: self.backend.request_approval(principal("sales"),
            C.ACTION_SALES_ORDER_REQUEST_CHANGE, self.ORDER,
            {"price_change": False, "fields_delta": {"unit_price": 1}}, justification="false flag"))

    def test_catalog_and_line_versions_are_bound_through_decision_and_resume(self):
        approval = self._submit_golden_quote()
        quote = self._record(self.QUOTE)
        line = self._lines(quote)[0]
        self._sql_fields(line, {}, bump=True)
        self._reject(lambda: self.backend.approve(principal("owner"), approval))
        self._sql_fields(line, {})  # restore exact fixture, not production history
        original = self.backend._resume_approved
        def change_catalog_then_resume(view):
            row = self.backend._get_row(C.RECORD_PRICE_BOOK_ENTRY, "PB-0001")
            rec = self.backend._row_to_record(row)
            self.backend._put_record("owner", rec.ref.record_type, rec.ref.record_id,
                {**rec.fields, "unit_price": 47}, bump_version_from=rec.ref.version)
            original(view)
        with patch.object(self.backend, "_resume_approved", side_effect=change_catalog_then_resume):
            self._reject(lambda: self.backend.approve(principal("owner"), approval))

    def test_catalog_change_after_approval_prevents_stale_acceptance(self):
        approval = self._submit_golden_quote()
        self.backend.approve(principal("owner"), approval)
        self._catalog_price(47)
        self._reject(lambda: self.backend.execute_business_action(principal("sales"), self.QUOTE,
            C.ACTION_QUOTATION_ACCEPT, {}))

    def test_draft_header_line_sync_failure_rolls_back_both_versions(self):
        quote = self._record(self.QUOTE)
        original = self.backend._sync_document_line
        def fail(actor, rec):
            original(actor, rec)
            raise RuntimeError("after line write")
        before = self._dump()
        with patch.object(self.backend, "_sync_document_line", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.backend.update_record(principal("sales"), quote.ref,
                    {"qty": 1000}, expected_version=quote.ref.version)
        self.assertEqual(self._dump(), before)

    def test_negotiated_draft_unit_edit_synchronizes_derived_prices(self):
        quote = self._record(self.QUOTE)
        edited = self.backend.update_record(principal("sales"), quote.ref,
            {"unit_price": 43.70}, expected_version=quote.ref.version)
        self.assertEqual((edited.fields["discount_pct"], edited.fields["total_amount"]), (5, 87400))
        self.assertEqual(self._lines(edited)[0].fields["unit_price"], 43.70)
        self.assertIsNone(self.backend.execute_business_action(principal("sales"), edited.ref,
            C.ACTION_QUOTATION_SUBMIT, {}).approval_id)

    def test_price_change_line_failure_rolls_back_decision_and_financial_content(self):
        result = self.backend.execute_business_action(principal("sales"), self.ORDER,
            C.ACTION_SALES_ORDER_REQUEST_CHANGE,
            {"price_change": True, "fields_delta": {"unit_price": 22}})
        original = self.backend._sync_document_line
        def fail(actor, rec):
            original(actor, rec)
            raise RuntimeError("after approved line write")
        before = self._dump()
        with patch.object(self.backend, "_sync_document_line", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.backend.approve(principal("owner"), result.approval_id)
        self.assertEqual(self._dump(), before)

    def test_multiple_stored_lines_are_rejected_without_historical_reconciliation(self):
        quote = self._record(self.QUOTE)
        line = self._lines(quote)[0]
        self.backend._put_record("sales", C.RECORD_QUOTATION_LINE, "EXTRA-LINE", line.fields)
        self.backend._db.commit()
        self._reject(lambda: self.backend.execute_business_action(principal("sales"), quote.ref,
            C.ACTION_QUOTATION_SUBMIT, {}))
        self._reject(lambda: self.backend.update_record(principal("sales"), quote.ref,
            {"qty": 1000}, expected_version=quote.ref.version))

    def test_c4_forged_nan_metrics_cannot_mutate_inventory(self):
        self._reject(lambda: self.backend.execute_business_action(principal("warehouse"), self.STOCK,
            C.ACTION_INVENTORY_ADJUST, {"adjust_qty": 10000, "adjust_amount": "NaN", "adjust_pct": "NaN"}))
        self.assertEqual(self._record(self.STOCK).fields["qty_on_hand"], 180)

    def test_unknown_monetary_risk_blocks_large_small_and_direct_requests(self):
        for qty in (10000, 1, -1, 0):
            with self.subTest(qty=qty):
                self._reject(lambda: self.backend.execute_business_action(principal("warehouse"), self.STOCK,
                    C.ACTION_INVENTORY_ADJUST, {"adjust_qty": qty}))
        self._reject(lambda: self.backend.request_approval(principal("warehouse"),
            C.ACTION_INVENTORY_ADJUST, self.STOCK, {"adjust_qty": 10000}, justification="unknown amount"))
        for amount in (0, 3000):
            self._reject(lambda: self.backend.execute_business_action(principal("warehouse"), self.STOCK,
                C.ACTION_INVENTORY_ADJUST, {"adjust_qty": 1, "adjust_amount": amount}))

    def test_inventory_malformed_quantities_and_impossible_stock_are_atomic(self):
        for qty in ("bad", "NaN", "Infinity", float("nan"), float("inf"), True, None, -181):
            with self.subTest(qty=qty):
                self._reject(lambda: self.backend.execute_business_action(principal("warehouse"), self.STOCK,
                    C.ACTION_INVENTORY_ADJUST, {"adjust_qty": qty}))
        self._reject(lambda: self.backend.update_record(principal("warehouse"), self.STOCK,
            {"qty_on_hand": 10180}, expected_version=self._record(self.STOCK).ref.version))

    def test_quantity_only_policy_small_adjustment_and_exact_boundary(self):
        self._percent_only()
        for delta, expected in ((9, "no_gate"), (-9.45, "no_gate"), (10, "gate")):
            before = self._record(self.STOCK)
            result = self.backend.execute_business_action(principal("warehouse"), self.STOCK,
                C.ACTION_INVENTORY_ADJUST, {"adjust_qty": delta})
            if expected == "no_gate":
                self.assertIsNone(result.approval_id)
                self.assertEqual(self._record(self.STOCK).fields["qty_on_hand"],
                                 float(str(before.fields["qty_on_hand"] + delta)))
            else:
                self.assertIsNotNone(result.approval_id)
                self.assertEqual(self._record(self.STOCK), before)

    def test_negative_adjustment_magnitude_requires_owner_and_rejection_has_no_effect(self):
        self._percent_only()
        before = self._record(self.STOCK)
        result = self.backend.execute_business_action(principal("warehouse"), self.STOCK,
            C.ACTION_INVENTORY_ADJUST, {"adjust_qty": -10})
        self.assertIsNotNone(result.approval_id)
        self.backend.reject(principal("owner"), result.approval_id)
        self.assertEqual(self._record(self.STOCK), before)
        self._reject(lambda: self.backend.approve(principal("owner"), result.approval_id))

    def test_quantity_only_policy_approval_is_once_and_inventory_changes_stale_it(self):
        self._percent_only()
        result = self.backend.execute_business_action(principal("warehouse"), self.STOCK,
            C.ACTION_INVENTORY_ADJUST, {"adjust_qty": 10})
        self.backend.approve(principal("owner"), result.approval_id)
        self.assertEqual(self._record(self.STOCK).fields["qty_on_hand"], 190)
        self._reject(lambda: self.backend.approve(principal("owner"), result.approval_id))
        next_result = self.backend.execute_business_action(principal("warehouse"), self.STOCK,
            C.ACTION_INVENTORY_ADJUST, {"adjust_qty": 10})
        self.backend.execute_business_action(principal("warehouse"), self.STOCK, C.ACTION_INVENTORY_RECEIPT, {"qty": 1})
        self._reject(lambda: self.backend.approve(principal("owner"), next_result.approval_id), FE.VersionConflict)

    def test_client_percentage_cannot_disable_quantity_gate(self):
        self._percent_only()
        for pct in (0, -6, "NaN", "bad", float("inf")):
            self._reject(lambda: self.backend.execute_business_action(principal("warehouse"), self.STOCK,
                C.ACTION_INVENTORY_ADJUST, {"adjust_qty": 10000, "adjust_pct": pct}))
        result = self.backend.execute_business_action(principal("warehouse"), self.STOCK,
            C.ACTION_INVENTORY_ADJUST, {"adjust_qty": 10000})
        self.assertIsNotNone(result.approval_id)
        self.assertEqual(self._record(self.STOCK).fields["qty_on_hand"], 180)

    def test_zero_stock_percentage_is_not_guessed(self):
        self._percent_only()
        self._sql_fields(self._record(self.STOCK), {"qty_on_hand": 0})
        self._reject(lambda: self.backend.execute_business_action(principal("warehouse"), self.STOCK,
            C.ACTION_INVENTORY_ADJUST, {"adjust_qty": 1}))

    def test_negative_or_invalid_receipt_cannot_disguise_cycle_count(self):
        for qty in (-100, "NaN", "bad", True, 0):
            self._reject(lambda: self.backend.execute_business_action(principal("warehouse"), self.STOCK,
                C.ACTION_INVENTORY_RECEIPT, {"qty": qty}))

    def test_http_inventory_invalid_input_and_unknown_risk_are_rejected(self):
        before = self._record(self.STOCK)
        for form in ({"adjust_qty": "bad"}, {"adjust_qty": "10000", "adjust_amount": "NaN", "adjust_pct": "NaN"},
                     {"adjust_qty": "1"}):
            response = self._http("/inventory/INV-0001/adjust", form, "warehouse")
            self.assertEqual(response[0], 200)
            self.assertIn('class="flash err"', response[1])
            self.assertEqual(self._record(self.STOCK), before)

    def test_historical_approved_and_rejected_notes_do_not_rewrite_financial_lines(self):
        for quote_id in ("Q-2026-0130", "Q-2026-0128"):
            quote = self._record(RecordRef(C.RECORD_QUOTATION, quote_id))
            lines = self._lines(quote)
            updated = self.backend.update_record(principal("sales"), quote.ref,
                {"note": "audit note"}, expected_version=quote.ref.version)
            self.assertEqual(self._lines(updated), lines)
            self.assertEqual({k: v for k, v in updated.fields.items() if k != "note"}, quote.fields)

    def test_http_forged_quote_create_and_legitimate_quote_draft(self):
        form = {"product_id": "PROD-0001", "qty": "2000", "list_price": "42.32",
                "unit_price": "42.32", "discount_pct": "0", "total_amount": "84640"}
        count = len(self.backend.list_records(principal("sales"), C.RECORD_QUOTATION))
        response = self._http("/quotations", form)
        self.assertEqual(response[0], 200)
        self.assertIn('class="flash err"', response[1])
        self.assertEqual(len(self.backend.list_records(principal("sales"), C.RECORD_QUOTATION)), count)
        from app import agents
        draft = agents.quote_draft(self.backend, principal("sales"), customer_name="test",
            product_id="PROD-0001", qty="2000", discount_pct="8", requested_date="2026-12-01")
        self.assertEqual((draft["list_price"], draft["unit_price"], draft["total_amount"]), (46, 42.32, 84640))
        for invalid in ("bad", "NaN", "Infinity", "1e500"):
            with self.assertRaises(FE.ValidationFailed):
                agents.quote_draft(self.backend, principal("sales"), customer_name="test",
                    product_id="PROD-0001", qty=invalid, discount_pct="8", requested_date="")


if __name__ == "__main__":
    unittest.main(verbosity=2)
