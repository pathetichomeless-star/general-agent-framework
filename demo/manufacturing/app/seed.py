"""Deterministic synthetic seed for the demo.

All data is synthetic (DEMO- style business keys, fictional companies, no real
personal data). The seed drives the SAME Facade operations the application
uses, so both backends produce equivalent demo state. With a fixed clock two
seed runs produce identical business state across the records / approvals /
tasks / notifications tables (verified by the replay test; user credential
salts are random by design and excluded from that comparison).
"""

from __future__ import annotations

import json

from framework_port import constants as C
from framework_port.dtos import Principal, RecordRef, UserBootstrap

CREDENTIAL = "demo1234"

USERS: tuple[UserBootstrap, ...] = (
    UserBootstrap("owner", "林文昊（老板）", C.ROLE_OWNER, "zh", CREDENTIAL),
    UserBootstrap("factory", "王强（厂长）", C.ROLE_FACTORY, "zh", CREDENTIAL),
    UserBootstrap("sales", "李婷（销售）", C.ROLE_SALES, "zh", CREDENTIAL),
    UserBootstrap("sales2", "Chen Xiao（陈晓）", C.ROLE_SALES, "en", CREDENTIAL),
    UserBootstrap("warehouse", "张伟（仓库）", C.ROLE_WAREHOUSE, "zh", CREDENTIAL),
    UserBootstrap("admin", "系统管理员", C.ROLE_ADMIN, "zh", CREDENTIAL),
)

SALES = Principal("sales", "李婷（销售）", C.ROLE_SALES, "zh")
OWNER = Principal("owner", "林文昊（老板）", C.ROLE_OWNER, "zh")
FACTORY = Principal("factory", "王强（厂长）", C.ROLE_FACTORY, "zh")
WAREHOUSE = Principal("warehouse", "张伟（仓库）", C.ROLE_WAREHOUSE, "zh")

CUSTOMERS: tuple[dict, ...] = (
    {"id": "CUST-0001", "name_cn": "美驰汽车零部件", "name_en": "Meridian Auto Components",
     "contact": "王经理", "city": "苏州", "owner_id": "sales"},
    {"id": "CUST-0002", "name_cn": "华彩照明", "name_en": "Brightline Lighting",
     "contact": "刘经理", "city": "宁波", "owner_id": "sales"},
    {"id": "CUST-0003", "name_cn": "蓝湾家居", "name_en": "Bluebay Home",
     "contact": "陈经理", "city": "杭州", "owner_id": "sales2"},
    {"id": "CUST-0004", "name_cn": "力拓机械", "name_en": "Lituo Machinery",
     "contact": "赵经理", "city": "无锡", "owner_id": "sales"},
    {"id": "CUST-0005", "name_cn": "恒信电气", "name_en": "Hengxin Electric",
     "contact": "孙经理", "city": "南京", "owner_id": "sales2"},
    {"id": "CUST-0006", "name_cn": "优派电子", "name_en": "Upview Electronics",
     "contact": "周经理", "city": "上海", "owner_id": "sales"},
    {"id": "CUST-0007", "name_cn": "三江卫浴", "name_en": "Sanjiang Sanitary",
     "contact": "吴经理", "city": "台州", "owner_id": "sales2"},
    {"id": "CUST-0008", "name_cn": "中恒安防", "name_en": "Zhongheng Security",
     "contact": "郑经理", "city": "常州", "owner_id": "sales"},
)

PRODUCTS: tuple[dict, ...] = (
    {"id": "PROD-0001", "code": "FLG-125", "name_cn": "法兰 FLG-125", "name_en": "Flange FLG-125",
     "unit": "件", "list_price": 46.0, "bom": json.dumps({"MAT-0001": 0.13})},
    {"id": "PROD-0002", "code": "SHF-080", "name_cn": "传动轴 SHF-080", "name_en": "Shaft SHF-080",
     "unit": "件", "list_price": 88.0, "bom": json.dumps({"MAT-0002": 0.42, "MAT-0008": 0.02})},
    {"id": "PROD-0003", "code": "BRK-210", "name_cn": "支架 BRK-210", "name_en": "Bracket BRK-210",
     "unit": "件", "list_price": 32.5, "bom": json.dumps({"MAT-0003": 0.18})},
    {"id": "PROD-0004", "code": "NUT-010", "name_cn": "特殊螺母 NUT-010", "name_en": "Nut NUT-010",
     "unit": "件", "list_price": 6.8, "bom": json.dumps({"MAT-0006": 0.02})},
    {"id": "PROD-0005", "code": "PLT-330", "name_cn": "板件 PLT-330", "name_en": "Plate PLT-330",
     "unit": "件", "list_price": 21.0, "bom": json.dumps({"MAT-0005": 0.35})},
    {"id": "PROD-0006", "code": "COV-115", "name_cn": "端盖 COV-115", "name_en": "Cover COV-115",
     "unit": "件", "list_price": 12.4, "bom": json.dumps({"MAT-0002": 0.09})},
    {"id": "PROD-0007", "code": "ROD-060", "name_cn": "导杆 ROD-060", "name_en": "Rod ROD-060",
     "unit": "件", "list_price": 27.9, "bom": json.dumps({"MAT-0002": 0.22})},
    {"id": "PROD-0008", "code": "HSG-220", "name_cn": "外壳 HSG-220", "name_en": "Housing HSG-220",
     "unit": "件", "list_price": 55.0, "bom": json.dumps({"MAT-0005": 0.61})},
    {"id": "PROD-0009", "code": "PIN-015", "name_cn": "销轴 PIN-015", "name_en": "Pin PIN-015",
     "unit": "件", "list_price": 3.9, "bom": json.dumps({"MAT-0002": 0.03})},
    {"id": "PROD-0010", "code": "SPR-090", "name_cn": "隔套 SPR-090", "name_en": "Sleeve SPR-090",
     "unit": "件", "list_price": 5.6, "bom": json.dumps({"MAT-0006": 0.04})},
    {"id": "PROD-0011", "code": "CLP-140", "name_cn": "卡箍 CLP-140", "name_en": "Clamp CLP-140",
     "unit": "件", "list_price": 9.2, "bom": json.dumps({"MAT-0004": 0.12})},
    {"id": "PROD-0012", "code": "GSK-105", "name_cn": "垫片 GSK-105", "name_en": "Gasket GSK-105",
     "unit": "件", "list_price": 2.5, "bom": json.dumps({"MAT-0005": 0.02})},
)

MATERIALS: tuple[dict, ...] = (
    {"id": "MAT-0001", "name_cn": "SS304 圆钢 Ø40", "name_en": "SS304 bar Ø40", "unit": "kg"},
    {"id": "MAT-0002", "name_cn": "45# 圆钢 Ø25", "name_en": "45# steel bar Ø25", "unit": "kg"},
    {"id": "MAT-0003", "name_cn": "AL6061 板材", "name_en": "AL6061 plate", "unit": "kg"},
    {"id": "MAT-0004", "name_cn": "20# 无缝管", "name_en": "20# seamless tube", "unit": "m"},
    {"id": "MAT-0005", "name_cn": "冷轧板 SPCC", "name_en": "SPCC sheet", "unit": "kg"},
    {"id": "MAT-0006", "name_cn": "黄铜棒 H59", "name_en": "Brass rod H59", "unit": "kg"},
    {"id": "MAT-0007", "name_cn": "不锈钢焊丝 308", "name_en": "SS welding wire 308", "unit": "kg"},
    {"id": "MAT-0008", "name_cn": "五金标准件", "name_en": "Standard hardware", "unit": "套"},
    {"id": "MAT-0009", "name_cn": "出口包装箱", "name_en": "Export carton", "unit": "个"},
    {"id": "MAT-0010", "name_cn": "缓冲泡沫", "name_en": "Foam insert", "unit": "个"},
)

INVENTORY: tuple[dict, ...] = (  # item_ref = material/product id
    {"id": "INV-0001", "item_ref": "MAT-0001", "name_cn": "SS304 圆钢 Ø40",
     "name_en": "SS304 bar Ø40", "unit": "kg", "qty_on_hand": 180, "reorder_point": 300},
    {"id": "INV-0002", "item_ref": "MAT-0002", "name_cn": "45# 圆钢 Ø25",
     "name_en": "45# steel bar Ø25", "unit": "kg", "qty_on_hand": 520, "reorder_point": 200},
    {"id": "INV-0003", "item_ref": "MAT-0003", "name_cn": "AL6061 板材",
     "name_en": "AL6061 plate", "unit": "kg", "qty_on_hand": 310, "reorder_point": 150},
    {"id": "INV-0004", "item_ref": "MAT-0004", "name_cn": "20# 无缝管",
     "name_en": "20# seamless tube", "unit": "m", "qty_on_hand": 300, "reorder_point": 120},
    {"id": "INV-0005", "item_ref": "MAT-0005", "name_cn": "冷轧板 SPCC",
     "name_en": "SPCC sheet", "unit": "kg", "qty_on_hand": 900, "reorder_point": 300},
    {"id": "INV-0006", "item_ref": "MAT-0006", "name_cn": "黄铜棒 H59",
     "name_en": "Brass rod H59", "unit": "kg", "qty_on_hand": 220, "reorder_point": 80},
    {"id": "INV-0007", "item_ref": "MAT-0007", "name_cn": "不锈钢焊丝 308",
     "name_en": "SS welding wire 308", "unit": "kg", "qty_on_hand": 150, "reorder_point": 60},
    {"id": "INV-0008", "item_ref": "MAT-0008", "name_cn": "五金标准件",
     "name_en": "Standard hardware", "unit": "套", "qty_on_hand": 2000, "reorder_point": 500},
    {"id": "INV-0009", "item_ref": "MAT-0009", "name_cn": "出口包装箱",
     "name_en": "Export carton", "unit": "个", "qty_on_hand": 40, "reorder_point": 100},
    {"id": "INV-0010", "item_ref": "MAT-0010", "name_cn": "缓冲泡沫",
     "name_en": "Foam insert", "unit": "个", "qty_on_hand": 500, "reorder_point": 200},
    {"id": "INV-P001", "item_ref": "PROD-0001", "name_cn": "成品：法兰 FLG-125",
     "name_en": "FG: Flange FLG-125", "unit": "件", "qty_on_hand": 120, "reorder_point": 50},
    {"id": "INV-P003", "item_ref": "PROD-0003", "name_cn": "成品：支架 BRK-210",
     "name_en": "FG: Bracket BRK-210", "unit": "件", "qty_on_hand": 60, "reorder_point": 50},
)


def seed(backend) -> dict:
    """Populate an empty backend with the deterministic demo scenario."""

    if backend.list_records(OWNER, C.RECORD_CUSTOMER):
        return {"seeded": False, "note": "already seeded"}

    for customer in CUSTOMERS:
        fields = dict(customer)
        fields["state"] = "active"
        backend.create_record(SALES, C.RECORD_CUSTOMER, fields)
    for product in PRODUCTS:
        fields = dict(product)
        fields["state"] = "active"
        backend.create_record(OWNER, C.RECORD_PRODUCT, fields)
    for material in MATERIALS:
        fields = dict(material)
        fields["state"] = "active"
        backend.create_record(OWNER, C.RECORD_MATERIAL, fields)
    for entry_product in PRODUCTS:
        backend.create_record(OWNER, C.RECORD_PRICE_BOOK_ENTRY, {
            "id": f"PB-{entry_product['id'][-4:]}",
            "product_id": entry_product["id"],
            "unit_price": entry_product["list_price"],
            "currency": "CNY",
            "state": "active",
        })
    for item in INVENTORY:
        fields = dict(item)
        fields["state"] = "active"
        backend.create_record(WAREHOUSE, C.RECORD_INVENTORY_ITEM, fields)

    # --- quotations -------------------------------------------------------
    def add_quote(qid, customer, product, qty, discount, state, date):
        unit = round(product["list_price"] * (1 - discount / 100.0), 2)
        backend.create_record(SALES, C.RECORD_QUOTATION, {
            "id": qid, "customer_id": customer["id"], "customer_name": customer["name_cn"],
            "product_id": product["id"], "product_name": product["name_cn"],
            "qty": qty, "discount_pct": discount, "list_price": product["list_price"],
            "unit_price": unit,
            "total_amount": round(unit * qty, 2), "currency": "CNY",
            "requested_date": date, "state": state, "owner_id": "sales",
        })
        backend.create_record(SALES, C.RECORD_QUOTATION_LINE, {
            "id": qid + "-L1", "quotation_id": qid, "product_id": product["id"],
            "product_name": product["name_cn"], "qty": qty, "unit_price": unit,
        })

    add_quote("Q-2026-0119", CUSTOMERS[5], PRODUCTS[8], 4000, 0, "draft", "2026-10-25")
    add_quote("Q-2026-0121", CUSTOMERS[3], PRODUCTS[6], 900, 3, "accepted", "2026-09-18")
    add_quote("Q-2026-0125", CUSTOMERS[1], PRODUCTS[4], 1500, 2, "accepted", "2026-09-22")
    add_quote("Q-2026-0128", CUSTOMERS[4], PRODUCTS[7], 300, 12, "rejected", "2026-09-25")
    add_quote("Q-2026-0130", CUSTOMERS[6], PRODUCTS[10], 800, 4, "approved", "2026-09-28")
    add_quote("Q-2026-0132", CUSTOMERS[2], PRODUCTS[2], 1200, 10, "draft", "2026-10-12")
    # Golden-path quotation: Meridian orders 2,000 × FLG-125 with a negotiated 8%.
    add_quote("Q-2026-0148", CUSTOMERS[0], PRODUCTS[0], 2000, 8, "draft", "2026-10-20")

    # A pending owner approval (10% discount) submitted during seeding.
    backend.execute_business_action(
        SALES, RecordRef(C.RECORD_QUOTATION, "Q-2026-0132"), C.ACTION_QUOTATION_SUBMIT,
        {"discount_pct": 10, "justification": "战略客户首单，让利换取年度框架"},
    )

    # --- sales orders ------------------------------------------------------
    def add_order(oid, customer, product, qty, state, date, discount=0):
        unit = round(product["list_price"] * (1 - discount / 100.0), 2)
        backend.create_record(SALES, C.RECORD_SALES_ORDER, {
            "id": oid, "customer_id": customer["id"], "customer_name": customer["name_cn"],
            "product_id": product["id"], "product_name": product["name_cn"],
            "qty": qty, "unit_price": unit, "total_amount": round(unit * qty, 2),
            "currency": "CNY", "requested_date": date, "state": state, "owner_id": "sales",
        })
        backend.create_record(SALES, C.RECORD_SALES_ORDER_LINE, {
            "id": oid + "-L1", "order_id": oid, "product_id": product["id"],
            "product_name": product["name_cn"], "qty": qty, "unit_price": unit,
        })

    add_order("SO-2026-0135", CUSTOMERS[1], PRODUCTS[4], 1000, "confirmed", "2026-10-08")
    add_order("SO-2026-0136", CUSTOMERS[7], PRODUCTS[10], 2200, "closed", "2026-09-20")
    add_order("SO-2026-0138", CUSTOMERS[4], PRODUCTS[11], 5000, "closed", "2026-09-15")
    add_order("SO-2026-0141", CUSTOMERS[0], PRODUCTS[1], 800, "confirmed", "2026-11-05")
    add_order("SO-2026-0150", CUSTOMERS[2], PRODUCTS[2], 2000, "draft", "2026-10-28")

    # Pending owner approval: order confirmation above the amount threshold.
    backend.execute_business_action(
        SALES, RecordRef(C.RECORD_SALES_ORDER, "SO-2026-0150"), C.ACTION_SALES_ORDER_CONFIRM,
        {"justification": "客户年度采购已内部批准"},
    )
    # Pending factory approval: requested date change (no price impact).
    backend.request_approval(
        SALES, C.ACTION_SALES_ORDER_REQUEST_CHANGE,
        RecordRef(C.RECORD_SALES_ORDER, "SO-2026-0141"),
        {"price_change": False,
         "fields_delta": {"requested_date": "2026-11-12"},
         "justification": "客户产线调试顺延一周"},
        justification="客户产线调试顺延一周",
    )

    # --- production orders ---------------------------------------------------
    def add_po(pid, order_id, product, qty, state, due, progress=0):
        backend.create_record(FACTORY, C.RECORD_PRODUCTION_ORDER, {
            "id": pid, "order_id": order_id, "product_id": product["id"],
            "product_name": product["name_cn"], "qty": qty, "due_date": due,
            "progress_pct": progress, "state": state, "owner_id": "factory",
            "expedite": False, "substitute": False,
        })

    add_po("PO-2026-0090", "SO-2026-0138", PRODUCTS[11], 5000, "completed", "2026-09-28", 100)
    add_po("PO-2026-0092", "SO-2026-0136", PRODUCTS[10], 2200, "in_production", "2026-10-05", 70)
    add_po("PO-2026-0095", "SO-2026-0141", PRODUCTS[1], 800, "released", "2026-10-15")
    backend.create_record(FACTORY, C.RECORD_MATERIAL_REQUIREMENT, {
        "id": "MR-2026-0095-1", "production_id": "PO-2026-0095",
        "material_id": "MAT-0002", "material_name": "45# 圆钢 Ø25",
        "required_qty": 336, "state": "open",
    })
    backend.create_task(FACTORY, "material_issue", "领料：传动轴 SHF-080 × 800", "warehouse",
                        related=RecordRef(C.RECORD_PRODUCTION_ORDER, "PO-2026-0095"),
                        origin="system", note="生产工单已下达，请按物料需求领料")

    # --- historical shipment (closed order) ---------------------------------
    backend.create_record(SALES, C.RECORD_SHIPMENT, {
        "id": "SHIP-2026-0090", "order_id": "SO-2026-0136",
        "customer_name": CUSTOMERS[7]["name_cn"], "address": "常州中恒安防仓",
        "state": "reconciled_matched", "owner_id": "sales",
    })
    backend.create_record(WAREHOUSE, C.RECORD_INVENTORY_MOVEMENT, {
        "item_type": C.RECORD_MATERIAL, "item_id": "MAT-0002", "delta": 600,
        "movement_type": "receipt", "note": "期初采购入库", "qty_after": 520,
    })
    return {"seeded": True, "note": "demo scenario loaded"}
