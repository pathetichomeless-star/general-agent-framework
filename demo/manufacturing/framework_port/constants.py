"""Stable public constants for the Hongsheng Works demo Facade.

These names are part of the public demo contract. They are deliberately
business-level: no framework internals, no storage names, no private paths.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Backend modes
# ---------------------------------------------------------------------------

MODE_PUBLIC_SIMULATION = "public_simulation"
MODE_LICENSED_FRAMEWORK = "licensed_framework"

# ---------------------------------------------------------------------------
# Record types (public business vocabulary)
# ---------------------------------------------------------------------------

RECORD_CUSTOMER = "customer"
RECORD_PRODUCT = "product"
RECORD_MATERIAL = "material"
RECORD_PRICE_BOOK_ENTRY = "price_book_entry"
RECORD_QUOTATION = "quotation"
RECORD_QUOTATION_LINE = "quotation_line"
RECORD_SALES_ORDER = "sales_order"
RECORD_SALES_ORDER_LINE = "sales_order_line"
RECORD_PRODUCTION_ORDER = "production_order"
RECORD_MATERIAL_REQUIREMENT = "material_requirement"
RECORD_INVENTORY_ITEM = "inventory_item"
RECORD_INVENTORY_MOVEMENT = "inventory_movement"
RECORD_SHIPMENT = "shipment"

RECORD_TYPES: tuple[str, ...] = (
    RECORD_CUSTOMER,
    RECORD_PRODUCT,
    RECORD_MATERIAL,
    RECORD_PRICE_BOOK_ENTRY,
    RECORD_QUOTATION,
    RECORD_QUOTATION_LINE,
    RECORD_SALES_ORDER,
    RECORD_SALES_ORDER_LINE,
    RECORD_PRODUCTION_ORDER,
    RECORD_MATERIAL_REQUIREMENT,
    RECORD_INVENTORY_ITEM,
    RECORD_INVENTORY_MOVEMENT,
    RECORD_SHIPMENT,
)

# ---------------------------------------------------------------------------
# Business actions (executed via execute_business_action)
# ---------------------------------------------------------------------------

ACTION_QUOTATION_SUBMIT = "quotation.submit"
ACTION_QUOTATION_ACCEPT = "quotation.accept"
ACTION_SALES_ORDER_CONFIRM = "sales_order.confirm"
ACTION_SALES_ORDER_REQUEST_CHANGE = "sales_order.request_change"
ACTION_PRODUCTION_ORDER_CREATE = "production_order.create"
ACTION_PRODUCTION_ORDER_RELEASE = "production_order.release"
ACTION_PRODUCTION_ORDER_ISSUE_MATERIAL = "production_order.issue_material"
ACTION_PRODUCTION_ORDER_REPORT_PROGRESS = "production_order.report_progress"
ACTION_PRODUCTION_ORDER_COMPLETE = "production_order.complete"
ACTION_INVENTORY_RECEIPT = "inventory.receipt"
ACTION_INVENTORY_ADJUST = "inventory.adjust_cycle_count"
ACTION_SHIPMENT_REQUEST = "shipment.request"

BUSINESS_ACTIONS: tuple[str, ...] = (
    ACTION_QUOTATION_SUBMIT,
    ACTION_QUOTATION_ACCEPT,
    ACTION_SALES_ORDER_CONFIRM,
    ACTION_SALES_ORDER_REQUEST_CHANGE,
    ACTION_PRODUCTION_ORDER_CREATE,
    ACTION_PRODUCTION_ORDER_RELEASE,
    ACTION_PRODUCTION_ORDER_ISSUE_MATERIAL,
    ACTION_PRODUCTION_ORDER_REPORT_PROGRESS,
    ACTION_PRODUCTION_ORDER_COMPLETE,
    ACTION_INVENTORY_RECEIPT,
    ACTION_INVENTORY_ADJUST,
    ACTION_SHIPMENT_REQUEST,
)

# Standalone approval kinds (created via request_approval; decided via approve/reject)
APPROVAL_EXPEDITE_PURCHASE = "material.expedite_purchase"

# ---------------------------------------------------------------------------
# Governed external actions (UNKNOWN / reconciliation axis)
# ---------------------------------------------------------------------------

GOVERNED_CARRIER_DISPATCH = "carrier.shipment_dispatch"

RESULT_ACCEPTED = "accepted"
RESULT_AMBIGUOUS = "ambiguous"
RESULT_REJECTED = "rejected"

FRESHNESS_FRESH = "fresh"
FRESHNESS_UNKNOWN = "unknown"

VERDICT_UNOBSERVABLE = "unobservable"
VERDICT_MATCHED_DERIVED = "matched (derived)"

# ---------------------------------------------------------------------------
# Record permissions (RoleRule.permission)
# ---------------------------------------------------------------------------

PERM_VIEW = "view"
PERM_CREATE = "create"
PERM_EDIT = "edit"
PERM_EXECUTE = "execute"
PERM_CANCEL = "cancel"

PERMISSIONS: tuple[str, ...] = (PERM_VIEW, PERM_CREATE, PERM_EDIT, PERM_EXECUTE, PERM_CANCEL)

# ---------------------------------------------------------------------------
# Roles (demo, synthetic)
# ---------------------------------------------------------------------------

ROLE_OWNER = "owner"
ROLE_FACTORY = "factory"
ROLE_SALES = "sales"
ROLE_WAREHOUSE = "warehouse"
ROLE_ADMIN = "admin"

# ---------------------------------------------------------------------------
# Task / notification vocabulary
# ---------------------------------------------------------------------------

TASK_STATUS_OPEN = "open"
TASK_STATUS_DONE = "done"
TASK_STATUS_CANCELLED = "cancelled"

PRIORITY_CRITICAL = "critical"
PRIORITY_WARNING = "warning"
PRIORITY_NORMAL = "normal"
PRIORITY_LOW = "low"

CONVERSATION_ROLE_USER = "user"
CONVERSATION_ROLE_ASSISTANT = "assistant"
