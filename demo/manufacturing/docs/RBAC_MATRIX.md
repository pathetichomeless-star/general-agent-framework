# RBAC 矩阵 — 角色权限（Phase 1 实现）

图例：V=查看 C=创建 E=编辑 X=执行 A=审批 ▲=仅本人相关记录（owner 匹配）。

| 对象 | 老板 owner | 厂长 factory | 销售 sales | 仓库 warehouse | 管理员 admin |
|---|---|---|---|---|---|
| 客户 | V | V | V C E | V | V |
| 报价/报价行 | V | V | V C E X | — | V |
| 销售订单/行 | V | V | V C E X ▲ | V | V |
| 生产工单 | V | V C E X | V | V X（领料） | V |
| 物料需求 | V | V C | V | V | V |
| 库存 | V A（调整审批） | V | V | V C E X | V |
| 库存流水 | V | V | — | V C | V |
| 发货单 | V | V | V C X | V X | V |
| 任务 | V 全部 | V 全部 | ▲ V X | ▲ V X | V |
| 审批 | A | A（其权限域） | ▲ V | ▲ V | V |
| 通知 | V | V | V | V | V |
| 审计时间线 | V 全量 | ▲ 参与项 | ▲ 参与项 | ▲ 参与项 | V 全量 |
| 用户与角色 | — | — | — | — | V（无业务变更权） |

## 审批权（谁审批什么）

| 审批类型 | 审批角色 | 触发条件 |
|---|---|---|
| quotation.submit（折扣） | owner | 折扣 > 5% |
| sales_order.confirm | owner | 总额 > ¥50,000 |
| sales_order.request_change | price_change → owner；否则 factory | 确认后变更 |
| production_order.create | factory | 加急 或 替代料 |
| inventory.adjust_cycle_count | owner | 金额 > ¥2,000 或 幅度 > 5% |
| material.expedite_purchase | owner | 缺料处置（AI 仅建议） |

## 动作级职责分离（谁能执行什么动作）

- 销售：报价提交/接受、订单确认/变更申请、发货申请
- 厂长：生产工单创建/下达/报工/完工
- 仓库：领料、入库、盘点调整、（治理）发货执行
- 管理员：**无任何业务动作**（治理边界即产品行为）

失败即关闭（fail-closed）：未配置 = 拒绝。契约测试逐条断言。
