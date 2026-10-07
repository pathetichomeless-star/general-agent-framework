# 数据模型 — 实体与状态机（demo 语义）

存储：demo 自有 SQLite 记录存储（乐观版本控制 + 更新历史）；实体经 Facade 操作读写，两个后端等价。

## 实体（13 业务类型 + 治理记录）

| 实体 | 关键字段 | 关系 |
|---|---|---|
| customer 客户 | name_cn/name_en, contact, city, owner_id | 1—n 报价/订单 |
| product 产品 | code, name_cn/en, list_price, bom(JSON) | 1—n 订单行；bom→物料 |
| material 物料 | name_cn/en, unit | ←库存；←BOM |
| price_book_entry 价格本 | product_id, unit_price, currency | →产品 |
| quotation 报价 | customer, product, qty, discount_pct, unit_price, total_amount, requested_date, state | 1—n 报价行 |
| quotation_line | product, qty, unit_price | →报价 |
| sales_order 销售订单 | customer, product, qty, total_amount, requested_date, state | 1—n 订单行；1—n 生产工单/发货单 |
| sales_order_line | product, qty, unit_price | →订单 |
| production_order 生产工单 | order_id, product, qty, due_date, progress_pct, expedite, substitute, state | 1—n 物料需求 |
| material_requirement | material_id, required_qty, state | →工单/物料 |
| inventory_item 库存 | item_ref(物料或产品), qty_on_hand, reorder_point, unit | 1—n 流水 |
| inventory_movement 流水 | item, delta, movement_type(in/out/issue/adjust), qty_after | →库存项 |
| shipment 发货单 | order_id, address, state | →订单；受治理外部动作目标 |

治理记录（demo 只读引用）：审批（含审批任务证据链）、治理外部动作、任务、交接、通知（含每收件人已读状态）、模拟邮件、助手会话、审计条目。

## 状态机

```
报价     draft → pending_approval → approved → accepted
                    └→ rejected（终态）
订单     draft → pending_approval → confirmed → in_production → ready_to_ship
              （变更）confirmed → change_pending → confirmed
                                        └→ shipped → closed
工单     planned → released → in_production → completed
              （加急/替代料创建时）pending_approval → planned；拒绝 → cancelled
库存项   状态不变，数量经流水守恒变更（不足时拒绝）
发货单   requested → dispatched_unknown（命令真相 UNKNOWN）→ reconciled_matched（对账）
审批     pending → approved | rejected（终态，拒绝后不可再批）
任务     open → done | cancelled；交接 pending → accepted | rejected
```

## 金路径种子（全部合成）

- 客户 8、产品 12、物料 10、价格本 12、库存 8 项（SS304 180kg < 订货点 300kg；包装箱 40 < 100）
- 报价 7（含金路径 Q-2026-0148：美驰 FLG-125×2000 @8% = ¥84,640）
- 订单 5（SO-2026-0150 确认审批待决、SO-2026-0141 变更审批待决）
- 工单 3（PO-2026-0092 逾期在制、PO-2026-0095 已下达待领料）
- 待决审批 3、历史发货 1、期初流水 1
