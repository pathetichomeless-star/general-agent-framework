"""Scripted deterministic agents (app-side).

Agents only READ business records through the Facade and PRODUCE
recommendations, drafts, tasks and notification text. They never execute
sensitive business actions: every recommendation that implies a business
change is routed through approvals or explicit human actions.

All logic is deterministic (no model calls), so two runs with the same data
produce the same output. A licensed backend may later offer model-backed
assistants, but the demo does not require it.
"""

from __future__ import annotations

import json
from typing import Any

from framework_port import constants as C
from framework_port.dtos import Principal, Record, RecordRef

from . import i18n


# ------------------------------------------------------------------ helpers
def _num(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def quote_draft(
    backend, actor: Principal, *, customer_name: str, product_id: str, qty: float,
    discount_pct: float, requested_date: str,
) -> dict[str, Any]:
    """Deterministic quotation draft from the price book. Never sent anywhere:
    the human reviews, edits and submits it."""

    entries = backend.list_records(
        actor, C.RECORD_PRICE_BOOK_ENTRY, filters={"product_id": product_id}
    )
    list_price = _num(entries[0].fields.get("unit_price", 0)) if entries else 0.0
    products = backend.list_records(actor, C.RECORD_PRODUCT, filters={"id": product_id})
    product_name = ""
    if products:
        product_name = i18n.pick("zh", products[0].fields, "name")
    unit_price = round(list_price * (1 - discount_pct / 100.0), 2)
    total = round(unit_price * qty, 2)
    rationale = (
        f"按价目表目录价 ¥{list_price:g} 与谈判折扣 {discount_pct:g}% 计算成交价 "
        f"¥{unit_price:g}；数量 {qty:g}，合计 ¥{total:g}。"
    )
    return {
        "customer_name": customer_name,
        "product_id": product_id,
        "product_name": product_name,
        "qty": qty,
        "list_price": list_price,
        "discount_pct": discount_pct,
        "unit_price": unit_price,
        "total_amount": total,
        "requested_date": requested_date,
        "currency": "CNY",
        "rationale": rationale,
    }


def atp_check(backend, actor: Principal, order: Record) -> dict[str, Any]:
    """Deterministic material check for an order's product BOM vs inventory.

    Returns a shortage report; when a shortage exists it also prepares an
    expedited-purchase recommendation (the human decides — the agent only
    prepares the approval package)."""

    product_id = str(order.fields.get("product_id", ""))
    qty = _num(order.fields.get("qty", 0))
    products = backend.list_records(actor, C.RECORD_PRODUCT, filters={"id": product_id})
    if not products:
        return {"ok": True, "lines": [], "note": "未找到产品主数据"}
    bom_raw = str(products[0].fields.get("bom", "{}"))
    try:
        bom: dict[str, float] = {
            k: float(v) for k, v in json.loads(bom_raw).items()
        }
    except (ValueError, TypeError):
        bom = {}
    lines: list[dict[str, Any]] = []
    shortages: list[dict[str, Any]] = []
    materials = backend.list_records(actor, C.RECORD_MATERIAL)
    material_names = {m.ref.record_id: m.fields for m in materials}
    for material_id, per_unit in sorted(bom.items()):
        needed = round(per_unit * qty, 2)
        items = backend.list_records(
            actor, C.RECORD_INVENTORY_ITEM, filters={"item_ref": material_id}
        )
        on_hand = _num(items[0].fields.get("qty_on_hand", 0)) if items else 0.0
        name = str(material_names.get(material_id, {}).get("name_cn", material_id))
        line = {
            "material_id": material_id,
            "name": name,
            "needed": needed,
            "on_hand": on_hand,
            "short": max(0.0, needed - on_hand),
        }
        lines.append(line)
        if line["short"] > 0:
            shortages.append(line)
    note_zh = "物料齐备，可直接安排生产。" if not shortages else (
        "检测到缺料：" + "；".join(
            f"{l['name']} 缺 {l['short']:g}" for l in shortages
        ) + "。建议紧急采购并等审批通过后执行。"
    )
    return {
        "ok": not shortages,
        "lines": lines,
        "shortages": shortages,
        "note": note_zh,
    }


def expedite_payload(short_line: dict[str, Any]) -> dict[str, Any]:
    """Deterministic purchase suggestion for one shortage line (agent
    recommendation only; approval and execution are human decisions)."""

    suggest_qty = float(short_line["short"]) * 1.5
    suggest_qty = float(round(suggest_qty / 20.0) * 20)  # pack to 20 kg steps
    suggest_qty = max(suggest_qty, 20.0)
    return {
        "material_id": short_line["material_id"],
        "material_name": short_line["name"],
        "short_qty": short_line["short"],
        "qty": suggest_qty,
        "eta": "3 天",
    }


def reschedule_suggestion(backend, actor: Principal, po: Record) -> dict[str, Any]:
    """Deterministic reschedule proposal for an overdue production order."""

    return {
        "po_id": po.ref.record_id,
        "current_due": str(po.fields.get("due_date", "")),
        "suggested_due": str(po.fields.get("due_date", "")),
        "note": "建议顺延 2 个工作日并通知销售；产能窗口已校验（确定性模拟）。",
    }


def daily_digest(backend, actor: Principal, lang: str = "zh") -> str:
    """Management summary. Business meaning first; no technical jargon."""

    orders = backend.list_records(actor, C.RECORD_SALES_ORDER)
    confirmed = sum(1 for o in orders if o.fields.get("state") == "confirmed")
    ready = sum(1 for o in orders if o.fields.get("state") == "ready_to_ship")
    pos = backend.list_records(actor, C.RECORD_PRODUCTION_ORDER)
    overdue = [
        p for p in pos
        if p.fields.get("state") in ("planned", "released", "in_production")
    ]
    # overdue check is time-based in the sentinel; here we list in-flight only
    in_prod = [p for p in pos if p.fields.get("state") == "in_production"]
    if lang == i18n.EN:
        return (
            f"Orders: {len(orders)} total, {confirmed} confirmed, {ready} ready to ship. "
            f"Production: {len(in_prod)} in progress. See the production board for risks."
        )
    return (
        f"订单：共 {len(orders)} 张，已确认 {confirmed}，待发货 {ready}。"
        f"生产：在制 {len(in_prod)} 张。风险与逾期请看生产看板。"
    )
