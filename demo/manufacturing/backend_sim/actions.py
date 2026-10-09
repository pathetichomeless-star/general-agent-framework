"""Business action registry for the simulated backend.

Each spec describes one demo business action: which record type it applies
to, which states allow it, what state it produces, whether it creates a child
record, and what demo side effects run (inventory movements, downstream tasks,
notifications). All side effects are demo-owned simulation logic — in a
licensed environment the same contract is fulfilled by the private adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from framework_port import constants as C
from framework_port import errors as E
from framework_port.dtos import ApprovalView, Principal, Record, RecordRef
from . import financial as F


@dataclass
class BusinessActionSpec:
    action_id: str
    resource_type: str
    from_states: tuple[str, ...]  # empty tuple = allowed in any state
    to_state: str = ""
    pending_state: str = ""       # in-place approval gate: state while pending
    rejected_state: str = ""      # in-place gate: state after rejection
    creates_child: Callable | None = None
    child_pending_state: str = ""  # child-record gate: child state while pending
    child_rejected_state: str = ""
    side_effects: Callable | None = None
    resume_side_effects: Callable | None = None
    roles: tuple[str, ...] = ()   # SoD: which roles may execute this action


SPECS: dict[str, BusinessActionSpec] = {}


def _spec(**kwargs: Any) -> BusinessActionSpec:
    spec = BusinessActionSpec(**kwargs)
    SPECS[spec.action_id] = spec
    return spec


def get_action(action_id: str) -> BusinessActionSpec:
    spec = SPECS.get(action_id)
    if spec is None:
        raise E.ValidationFailed(f"unknown business action '{action_id}'")
    return spec


def get_standalone_handler(kind: str) -> Callable | None:
    return _STANDALONE_HANDLERS.get(kind)


BUSINESS_ACTION_SPECS = SPECS


# ----------------------------------------------------------------- helpers
def _move_inventory(
    engine,
    actor: Principal,
    item: Record,
    delta: float,
    movement_type: str,
    note: str,
) -> Record:
    """Apply one inventory movement with conservation checks (demo semantics)."""

    qty = F.number(item.fields.get("qty_on_hand"), "qty_on_hand")
    delta = F.quantity(delta, "inventory delta", signed=True)
    new_qty = qty + delta
    if qty < 0 or new_qty < 0:
        raise E.ValidationFailed(
            f"库存不足：{item.fields.get('name_cn', item.ref.record_id)} 现有 {qty:g}，"
            f"需要 {-delta:g}"
        )
    fields = dict(item.fields)
    fields["qty_on_hand"] = F.json_number(new_qty)
    engine._put_record(
        actor.actor_id, item.ref.record_type, item.ref.record_id, fields,
        bump_version_from=item.ref.version,
    )
    movement_fields = {
        "item_type": item.ref.record_type,
        "item_id": item.ref.record_id,
        "delta": F.json_number(delta),
        "movement_type": movement_type,
        "note": note,
        "qty_after": F.json_number(new_qty),
    }
    movement_id = engine._next_id(C.RECORD_INVENTORY_MOVEMENT)
    engine._put_record(
        actor.actor_id, C.RECORD_INVENTORY_MOVEMENT, movement_id, movement_fields
    )
    row = engine._get_row(item.ref.record_type, item.ref.record_id)
    return engine._row_to_record(row)


def _complete_related_task(engine, actor: Principal, po_ref: RecordRef, kind: str) -> str:
    tasks = engine.list_tasks(actor, status=C.TASK_STATUS_OPEN)
    for task in tasks:
        if (
            task.kind == kind
            and task.related is not None
            and task.related.record_id == po_ref.record_id
        ):
            engine.complete_task(actor, task.task_id, note="随业务动作自动完成")
            return f"任务 {task.task_id} 已完成"
    return ""


# ---------------------------------------------------------- child creators
def _create_sales_order_from_quote(
    engine, actor: Principal, quote: Record, payload: Mapping[str, Any]
) -> Record:
    fields = {
        "customer_id": quote.fields.get("customer_id", ""),
        "customer_name": quote.fields.get("customer_name", ""),
        "quotation_id": quote.ref.record_id,
        "product_id": quote.fields.get("product_id", ""),
        "product_name": quote.fields.get("product_name", ""),
        "qty": quote.fields.get("qty", 0),
        "unit_price": quote.fields["unit_price"],
        "total_amount": quote.fields.get("total_amount", 0),
        "currency": quote.fields.get("currency", "CNY"),
        "requested_date": quote.fields.get("requested_date", ""),
        "state": "draft",
        "owner_id": actor.actor_id,
    }
    suffix = quote.ref.record_id.rsplit("-", 1)[-1]
    order_id = f"SO-{suffix}"
    if engine._get_row(C.RECORD_SALES_ORDER, order_id) is not None:
        order_id = engine._next_id(C.RECORD_SALES_ORDER)
    order = engine._put_record(actor.actor_id, C.RECORD_SALES_ORDER, order_id, fields)
    lines = engine.list_records(
        actor, C.RECORD_QUOTATION_LINE, filters={"quotation_id": quote.ref.record_id}
    )
    for line in lines:
        line_fields = dict(line.fields)
        line_fields["order_id"] = order_id
        engine._put_record(
            actor.actor_id, C.RECORD_SALES_ORDER_LINE,
            engine._next_id(C.RECORD_SALES_ORDER_LINE), line_fields,
        )
    return order


def _create_production_order(
    engine, actor: Principal, order: Record, payload: Mapping[str, Any], *, record_id=None
) -> Record:
    policy_data = engine._validated_action_payload(C.ACTION_PRODUCTION_ORDER_CREATE, order, payload)
    fields = {
        "order_id": order.ref.record_id,
        "product_id": payload.get("product_id", ""),
        "product_name": payload.get("product_name", ""),
        "qty": float(payload.get("qty", 0)),
        "due_date": payload.get("due_date", ""),
        "expedite": bool(payload.get("expedite", False)),
        "substitute": bool(payload.get("substitute", False)),
        "progress_pct": 0,
        "state": "planned",
        "owner_id": actor.actor_id,
    }
    fields["_production_binding"] = {
        "parent": engine._record_binding(order),
        "content": {k: fields[k] for k in
                    ("product_id", "qty", "expedite", "substitute")},
        "policy_data": dict(policy_data),
    }
    po_id = record_id or engine._next_id(C.RECORD_PRODUCTION_ORDER)
    po = engine._put_record(actor.actor_id, C.RECORD_PRODUCTION_ORDER, po_id, fields)
    for req in payload.get("requirements", []):
        req_fields = {
            "production_id": po_id,
            "material_id": req.get("material_id", ""),
            "material_name": req.get("material_name", ""),
            "required_qty": float(req.get("qty", 0)),
            "state": "open",
        }
        engine._put_record(
            actor.actor_id, C.RECORD_MATERIAL_REQUIREMENT,
            engine._next_id(C.RECORD_MATERIAL_REQUIREMENT), req_fields,
        )
    return po


def _create_shipment(
    engine, actor: Principal, order: Record, payload: Mapping[str, Any]
) -> Record:
    fields = {
        "order_id": order.ref.record_id,
        "customer_name": order.fields.get("customer_name", ""),
        "address": payload.get("address", "客户默认地址"),
        "state": "requested",
        "owner_id": actor.actor_id,
    }
    shipment_id = engine._next_id(C.RECORD_SHIPMENT)
    return engine._put_record(actor.actor_id, C.RECORD_SHIPMENT, shipment_id, fields)


# ------------------------------------------------------------ side effects
def _after_release(engine, actor: Principal, po: Record, payload, child_ref) -> str:
    engine._advance_production_parent(actor, po, C.ACTION_PRODUCTION_ORDER_RELEASE, "in_production")
    engine.create_task(
        actor, "material_issue",
        f"领料：{po.fields.get('product_name', '')} × {po.fields.get('qty', 0):g}",
        "warehouse", related=po.ref, origin="system",
        note="生产工单已下达，请按物料需求领料",
    )
    return "已通知仓库领料"


def _after_complete(engine, actor: Principal, po: Record, payload, child_ref) -> str:
    engine._advance_production_parent(actor, po, C.ACTION_PRODUCTION_ORDER_COMPLETE, "ready_to_ship")
    engine.create_task(
        actor, "fg_receipt",
        f"成品入库：{po.fields.get('product_name', '')} × {po.fields.get('qty', 0):g}",
        "warehouse", related=po.ref, origin="system",
        note="生产已完成，请将成品入库",
    )
    order_id = str(po.fields.get("order_id", ""))
    if order_id:
        engine.notify(
            actor, "production.completed", ("sales", "owner"),
            title=f"生产完成 {po.ref.record_id}",
            body=f"{po.fields.get('product_name', '')} × {po.fields.get('qty', 0):g} 已完工，"
                 f"订单 {order_id} 可安排发货。",
            priority=C.PRIORITY_NORMAL, related=po.ref,
        )
    return "已通知销售与老板，订单可发货"


def _after_issue(engine, actor: Principal, po: Record, payload, child_ref) -> str:
    notes = []
    reqs = engine.list_records(
        actor, C.RECORD_MATERIAL_REQUIREMENT,
        filters={"production_id": po.ref.record_id},
    )
    for req in reqs:
        material_id = str(req.fields.get("material_id", ""))
        needed = float(req.fields.get("required_qty", 0))
        items = engine.list_records(
            actor, C.RECORD_INVENTORY_ITEM, filters={"item_ref": material_id}
        )
        if not items:
            raise E.ValidationFailed(f"物料 {material_id} 无库存记录，无法领料")
        _move_inventory(engine, actor, items[0], -needed, "issue",
                        f"领料 → {po.ref.record_id}")
        rrow = engine._get_row(C.RECORD_MATERIAL_REQUIREMENT, req.ref.record_id)
        rfields = dict(engine._row_to_record(rrow).fields)
        rfields["state"] = "issued"
        engine._put_record(actor.actor_id, C.RECORD_MATERIAL_REQUIREMENT,
                           req.ref.record_id, rfields, bump_version_from=int(rrow["version"]))
        notes.append(f"{material_id} -{needed:g}")
    task_note = _complete_related_task(engine, actor, po.ref, "material_issue")
    if task_note:
        notes.append(task_note)
    return "；".join(notes)


def _receipt_side_effects(engine, actor: Principal, item: Record, payload, child_ref) -> str:
    qty = float(payload.get("qty", 0))
    if qty:
        _move_inventory(engine, actor, item, qty, "receipt",
                        str(payload.get("justification", "入库")))
    return f"入库 {qty:+g}"


def _adjust_side_effects(engine, actor: Principal, item: Record, payload, child_ref) -> str:
    delta = F.quantity(payload.get("adjust_qty"), "adjust_qty", signed=True)
    if delta:
        _move_inventory(engine, actor, item, delta, "adjust",
                        str(payload.get("justification", "盘点调整")))
    return f"盘点调整 {delta:+g}"


def _after_shipment_request(engine, actor: Principal, order: Record, payload, child_ref) -> str:
    if child_ref is None:
        return ""
    engine.create_task(
        actor, "shipment_dispatch", f"执行发货：{order.ref.record_id}",
        "warehouse", related=child_ref, origin="system",
        note="客户订单已备妥，请执行发货",
    )
    return f"已通知仓库执行发货（{child_ref.record_id}）"


def _resume_confirm(engine, actor: Principal, order: Record, payload) -> None:
    engine.notify(
        actor, "order.confirmed", ("factory", "warehouse"),
        title=f"订单已确认 {order.ref.record_id}",
        body=f"{order.fields.get('customer_name', '')} 的订单已确认，可安排生产。",
        priority=C.PRIORITY_NORMAL, related=order.ref,
    )


# ---------------------------------------------------------------- registry
_spec(
    action_id=C.ACTION_QUOTATION_SUBMIT,
    resource_type=C.RECORD_QUOTATION,
    from_states=("draft",),
    to_state="approved",
    pending_state="pending_approval",
    rejected_state="rejected",
    roles=(C.ROLE_SALES,),
)
_spec(
    action_id=C.ACTION_QUOTATION_ACCEPT,
    resource_type=C.RECORD_QUOTATION,
    from_states=("approved",),
    to_state="accepted",
    creates_child=_create_sales_order_from_quote,
    roles=(C.ROLE_SALES,),
)
_spec(
    action_id=C.ACTION_SALES_ORDER_CONFIRM,
    resource_type=C.RECORD_SALES_ORDER,
    from_states=("draft",),
    to_state="confirmed",
    pending_state="pending_approval",
    rejected_state="draft",
    resume_side_effects=_resume_confirm,
    roles=(C.ROLE_SALES,),
)
_spec(
    action_id=C.ACTION_SALES_ORDER_REQUEST_CHANGE,
    resource_type=C.RECORD_SALES_ORDER,
    from_states=("confirmed",),
    to_state="confirmed",
    pending_state="change_pending",
    rejected_state="confirmed",
    roles=(C.ROLE_SALES,),
)
_spec(
    action_id=C.ACTION_PRODUCTION_ORDER_CREATE,
    resource_type=C.RECORD_SALES_ORDER,
    from_states=("confirmed",),
    to_state="planned",
    creates_child=_create_production_order,
    child_pending_state="pending_approval",
    child_rejected_state="cancelled",
    roles=(C.ROLE_FACTORY,),
)
_spec(
    action_id=C.ACTION_PRODUCTION_ORDER_RELEASE,
    resource_type=C.RECORD_PRODUCTION_ORDER,
    from_states=("planned",),
    to_state="released",
    side_effects=_after_release,
    roles=(C.ROLE_FACTORY,),
)
_spec(
    action_id=C.ACTION_PRODUCTION_ORDER_ISSUE_MATERIAL,
    resource_type=C.RECORD_PRODUCTION_ORDER,
    from_states=("released",),
    to_state="in_production",
    side_effects=_after_issue,
    roles=(C.ROLE_WAREHOUSE,),
)
_spec(
    action_id=C.ACTION_PRODUCTION_ORDER_REPORT_PROGRESS,
    resource_type=C.RECORD_PRODUCTION_ORDER,
    from_states=("in_production",),
    to_state="in_production",
    roles=(C.ROLE_FACTORY,),
)
_spec(
    action_id=C.ACTION_PRODUCTION_ORDER_COMPLETE,
    resource_type=C.RECORD_PRODUCTION_ORDER,
    from_states=("in_production",),
    to_state="completed",
    side_effects=_after_complete,
    roles=(C.ROLE_FACTORY,),
)
_spec(
    action_id=C.ACTION_INVENTORY_RECEIPT,
    resource_type=C.RECORD_INVENTORY_ITEM,
    from_states=(),
    to_state="",
    side_effects=_receipt_side_effects,
    roles=(C.ROLE_WAREHOUSE,),
)
_spec(
    action_id=C.ACTION_INVENTORY_ADJUST,
    resource_type=C.RECORD_INVENTORY_ITEM,
    from_states=(),
    to_state="",
    side_effects=_adjust_side_effects,
    roles=(C.ROLE_WAREHOUSE,),
)
_spec(
    action_id=C.ACTION_SHIPMENT_REQUEST,
    resource_type=C.RECORD_SALES_ORDER,
    from_states=("ready_to_ship",),
    to_state="ready_to_ship",
    creates_child=_create_shipment,
    side_effects=_after_shipment_request,
    roles=(C.ROLE_SALES,),
)


# ----------------------------------------------------- standalone handlers
def _expedite_purchase_handler(
    engine, actor: Principal, view: ApprovalView, payload: Mapping[str, Any]
) -> None:
    material_id = str(payload.get("material_id", ""))
    qty = float(payload.get("qty", 0))
    eta = str(payload.get("eta", "3 天"))
    engine.create_task(
        actor, "expedited_purchase",
        f"紧急采购入库：{material_id} × {qty:g} kg（ETA {eta}）",
        "warehouse", related=view.target, origin="approval",
        note=f"审批 {view.approval_id} 已通过，请执行紧急采购并入库",
    )
    engine.notify(
        actor, "purchase.approved", ("warehouse", "factory"),
        title=f"紧急采购已批准 {material_id}",
        body=f"数量 {qty:g} kg，预计 {eta} 到货。已生成仓库任务。",
        priority=C.PRIORITY_CRITICAL, related=view.target,
    )


_STANDALONE_HANDLERS = {
    C.APPROVAL_EXPEDITE_PURCHASE: _expedite_purchase_handler,
}
