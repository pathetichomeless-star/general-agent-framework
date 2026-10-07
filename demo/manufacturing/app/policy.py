"""Demo policy tables: RBAC rules, approval policies, approver roles, action
role restrictions are registered on the backend; navigation is app-side.

These tables are the manufacturing SoD/RBAC configuration (application-owned
policy, per the approved architecture). They are plain public data.
"""

from __future__ import annotations

from framework_port import constants as C
from framework_port.dtos import ApprovalPolicy, RoleRule

from . import i18n

# ---------------------------------------------------------------------------
# Record view rules: (role, permission, resource_type, owner_scoped)
# ---------------------------------------------------------------------------

_ALL_TYPES = C.RECORD_TYPES

_ROLE_VIEW: dict[str, tuple[tuple[str, bool], ...]] = {
    C.ROLE_OWNER: tuple((rt, False) for rt in _ALL_TYPES),
    C.ROLE_ADMIN: tuple((rt, False) for rt in _ALL_TYPES),
    C.ROLE_FACTORY: tuple((rt, False) for rt in _ALL_TYPES),
    C.ROLE_SALES: (
        (C.RECORD_CUSTOMER, False),
        (C.RECORD_PRODUCT, False),
        (C.RECORD_MATERIAL, False),
        (C.RECORD_PRICE_BOOK_ENTRY, False),
        (C.RECORD_QUOTATION, False),
        (C.RECORD_QUOTATION_LINE, False),
        (C.RECORD_SALES_ORDER, True),        # ▲ sales sees own orders
        (C.RECORD_SALES_ORDER_LINE, True),
        (C.RECORD_PRODUCTION_ORDER, False),
        (C.RECORD_MATERIAL_REQUIREMENT, False),
        (C.RECORD_INVENTORY_ITEM, False),
        (C.RECORD_SHIPMENT, False),
    ),
    C.ROLE_WAREHOUSE: (
        (C.RECORD_CUSTOMER, False),
        (C.RECORD_SALES_ORDER, False),
        (C.RECORD_SALES_ORDER_LINE, False),
        (C.RECORD_PRODUCTION_ORDER, False),
        (C.RECORD_MATERIAL_REQUIREMENT, False),
        (C.RECORD_INVENTORY_ITEM, False),
        (C.RECORD_INVENTORY_MOVEMENT, False),
        (C.RECORD_SHIPMENT, False),
    ),
}

_RULES: tuple[RoleRule, ...] = tuple(
    RoleRule(role=role, permission=C.PERM_VIEW, resource_type=rt, owner_scoped=scoped)
    for role, entries in _ROLE_VIEW.items()
    for rt, scoped in entries
)

# Create/edit rules. Master data (products/materials/price book) belongs to
# the owner; the warehouse manages inventory records; the admin deliberately
# has NO business mutation rights at all.
_CREATE_EDIT: tuple[tuple[str, str, str], ...] = (
    (C.ROLE_SALES, C.PERM_CREATE, C.RECORD_CUSTOMER),
    (C.ROLE_SALES, C.PERM_EDIT, C.RECORD_CUSTOMER),
    (C.ROLE_SALES, C.PERM_CREATE, C.RECORD_QUOTATION),
    (C.ROLE_SALES, C.PERM_EDIT, C.RECORD_QUOTATION),
    (C.ROLE_SALES, C.PERM_CREATE, C.RECORD_QUOTATION_LINE),
    (C.ROLE_SALES, C.PERM_EXECUTE, C.RECORD_QUOTATION),
    (C.ROLE_SALES, C.PERM_CREATE, C.RECORD_SALES_ORDER),
    (C.ROLE_SALES, C.PERM_EDIT, C.RECORD_SALES_ORDER),
    (C.ROLE_SALES, C.PERM_CREATE, C.RECORD_SALES_ORDER_LINE),
    (C.ROLE_SALES, C.PERM_EXECUTE, C.RECORD_SALES_ORDER),
    (C.ROLE_FACTORY, C.PERM_EXECUTE, C.RECORD_SALES_ORDER),
    (C.ROLE_SALES, C.PERM_EXECUTE, C.RECORD_SHIPMENT),
    (C.ROLE_SALES, C.PERM_CREATE, C.RECORD_SHIPMENT),
    (C.ROLE_WAREHOUSE, C.PERM_EXECUTE, C.RECORD_SHIPMENT),
    (C.ROLE_FACTORY, C.PERM_EXECUTE, C.RECORD_PRODUCTION_ORDER),
    (C.ROLE_WAREHOUSE, C.PERM_EXECUTE, C.RECORD_PRODUCTION_ORDER),
    (C.ROLE_WAREHOUSE, C.PERM_EXECUTE, C.RECORD_INVENTORY_ITEM),
    (C.ROLE_WAREHOUSE, C.PERM_EDIT, C.RECORD_INVENTORY_ITEM),
    (C.ROLE_WAREHOUSE, C.PERM_CREATE, C.RECORD_INVENTORY_ITEM),
    (C.ROLE_WAREHOUSE, C.PERM_CREATE, C.RECORD_INVENTORY_MOVEMENT),
    (C.ROLE_FACTORY, C.PERM_EDIT, C.RECORD_PRODUCTION_ORDER),
    (C.ROLE_FACTORY, C.PERM_CREATE, C.RECORD_PRODUCTION_ORDER),
    (C.ROLE_FACTORY, C.PERM_CREATE, C.RECORD_MATERIAL_REQUIREMENT),
    (C.ROLE_OWNER, C.PERM_CREATE, C.RECORD_PRODUCT),
    (C.ROLE_OWNER, C.PERM_EDIT, C.RECORD_PRODUCT),
    (C.ROLE_OWNER, C.PERM_CREATE, C.RECORD_MATERIAL),
    (C.ROLE_OWNER, C.PERM_EDIT, C.RECORD_MATERIAL),
    (C.ROLE_OWNER, C.PERM_CREATE, C.RECORD_PRICE_BOOK_ENTRY),
    (C.ROLE_OWNER, C.PERM_EDIT, C.RECORD_PRICE_BOOK_ENTRY),
)
_RULES += tuple(
    RoleRule(role=role, permission=perm, resource_type=rt) for role, perm, rt in _CREATE_EDIT
)

# ---------------------------------------------------------------------------
# Approval policies (first match wins) and approver roles
# ---------------------------------------------------------------------------

APPROVAL_POLICIES: tuple[ApprovalPolicy, ...] = (
    ApprovalPolicy(
        action=C.ACTION_QUOTATION_SUBMIT,
        condition={"field": "discount_pct", "op": ">", "value": 5},
        approver_role=C.ROLE_OWNER,
    ),
    ApprovalPolicy(
        action=C.ACTION_SALES_ORDER_CONFIRM,
        condition={"field": "total_amount", "op": ">", "value": 50000},
        approver_role=C.ROLE_OWNER,
    ),
    ApprovalPolicy(
        action=C.ACTION_SALES_ORDER_REQUEST_CHANGE,
        condition={"field": "price_change", "op": "==", "value": True},
        approver_role=C.ROLE_OWNER,
    ),
    ApprovalPolicy(
        action=C.ACTION_SALES_ORDER_REQUEST_CHANGE,
        condition={"op": "always"},
        approver_role=C.ROLE_FACTORY,
    ),
    ApprovalPolicy(
        action=C.ACTION_PRODUCTION_ORDER_CREATE,
        condition={"op": "any", "of": [
            {"field": "expedite", "op": "==", "value": True},
            {"field": "substitute", "op": "==", "value": True},
        ]},
        approver_role=C.ROLE_FACTORY,
    ),
    ApprovalPolicy(
        action=C.ACTION_INVENTORY_ADJUST,
        condition={"op": "any", "of": [
            {"field": "adjust_amount", "op": ">", "value": 2000},
            {"field": "adjust_pct", "op": ">", "value": 5},
        ]},
        approver_role=C.ROLE_OWNER,
    ),
)

APPROVER_ROLES: dict[str, tuple[str, ...]] = {
    C.ACTION_QUOTATION_SUBMIT: (C.ROLE_OWNER,),
    C.ACTION_SALES_ORDER_CONFIRM: (C.ROLE_OWNER,),
    C.ACTION_SALES_ORDER_REQUEST_CHANGE: (C.ROLE_FACTORY, C.ROLE_OWNER),
    C.ACTION_PRODUCTION_ORDER_CREATE: (C.ROLE_FACTORY,),
    C.ACTION_INVENTORY_ADJUST: (C.ROLE_OWNER,),
    C.APPROVAL_EXPEDITE_PURCHASE: (C.ROLE_OWNER,),
}

# ---------------------------------------------------------------------------
# Navigation per role: (route, i18n key). Order = display order.
# ---------------------------------------------------------------------------

_NAV: dict[str, tuple[tuple[str, str], ...]] = {
    C.ROLE_OWNER: (
        ("/dashboard", "nav_dashboard"),
        ("/orders", "nav_orders"),
        ("/production", "nav_production"),
        ("/approvals", "nav_approvals"),
        ("/notifications", "nav_notifications"),
        ("/audit", "nav_audit"),
    ),
    C.ROLE_FACTORY: (
        ("/dashboard", "nav_dashboard"),
        ("/orders", "nav_orders"),
        ("/production", "nav_production"),
        ("/inventory", "nav_inventory"),
        ("/tasks", "nav_tasks"),
        ("/approvals", "nav_approvals"),
        ("/notifications", "nav_notifications"),
    ),
    C.ROLE_SALES: (
        ("/dashboard", "nav_dashboard"),
        ("/customers", "nav_customers"),
        ("/quotations", "nav_quotations"),
        ("/orders", "nav_orders"),
        ("/tasks", "nav_tasks"),
        ("/notifications", "nav_notifications"),
    ),
    C.ROLE_WAREHOUSE: (
        ("/dashboard", "nav_dashboard"),
        ("/production", "nav_production"),
        ("/inventory", "nav_inventory"),
        ("/tasks", "nav_tasks"),
        ("/notifications", "nav_notifications"),
    ),
    C.ROLE_ADMIN: (
        ("/dashboard", "nav_dashboard"),
        ("/admin", "nav_admin"),
        ("/audit", "nav_audit"),
    ),
}


def nav_for(role: str) -> tuple[tuple[str, str], ...]:
    return _NAV.get(role, ())


def audit_allowed(role: str) -> bool:
    return role in (C.ROLE_OWNER, C.ROLE_ADMIN)
