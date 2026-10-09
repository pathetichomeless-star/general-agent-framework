# Architecture contract — 公共 Facade 契约（public-safe）

This document describes the public architecture. It deliberately excludes
private implementation mapping details (see BOUNDARY.md).

## 1. 依赖图 Dependency graph

```
公共仓库（本目录）
┌─────────────────────────────────────────────┐
│  app/      HTTP 服务 · UI · i18n · 策略表   │
│  agents/   脚本化确定性 AI（仅建议，不执行）│
│  seed      确定性合成数据（经 Facade 灌入） │
│        │ 仅依赖                              │
│        ▼                                     │
│  framework_port/   ManufacturingBackend 协议 │
│        │ import                              │
│        └──► backend_sim/  公共确定性模拟后端 │
└─────────────────────────────────────────────┘
            ▲ 运行期经配置注入（私有仓库交付）
   持牌后端适配器（LicensedFrameworkBackend，私有）
            │
   私有商业框架（Licensed Framework 0.4）
```

## 2. Facade 契约（30 个业务级操作）

| 组 | 操作 |
|---|---|
| 能力/配置 | query_capabilities · configure_authorization · close |
| 身份/会话 | authenticate · create_session · resolve_session · close_session · list_users |
| 业务记录 | list_records · get_record · create_record · update_record · execute_business_action |
| 审批 | request_approval · list_approvals · get_approval · approve · reject |
| 治理外部动作 | submit_governed_action · get_governed_action · execute_governed_action · observe_external_action · reconcile_external_action |
| 任务/交接 | list_tasks · create_task · complete_task · request_handoff · respond_handoff |
| 通知 | notify · list_notifications · unread_count · mark_notification_read |
| 助手会话 | append_message · list_messages |
| 审计/证据 | get_audit_timeline · verify_evidence_chain |

关键语义（两个后端都必须满足，契约测试强制）：

- **职责分离**：审批决定人 ≠ 请求人；决定权按审批类型配置的角色表执行。
- **审批续跑**：业务动作审批通过后由后端自动完成该动作；治理外部动作审批通过后停在 approved，等待人工执行。
- **治理外部动作**：登记（含理由）→ 执行一次 → 若响应丢失，命令真相 = **UNKNOWN**；盲重试被拒绝；对账 = 一次治理外部读取 + 纯函数推导判定（`匹配（推导）` / `不可观测`）。**命令真相与外部判定两轴并列，永不合并、永不改写。**
- **RBAC**：规则为公共数据（角色×权限×对象类型×是否仅本人记录），由后端 fail-closed 强制；管理角色无业务变更权。
- **审计**：全部变更按序留痕；订单中心时间线由父子链接聚合。
- **证据**：哈希链验证范围 = **审批任务证据域**；其余审计记录如实称为“保留可审计”。

## 3. 双后端责任划分

| 职责 | 公共模拟后端（本仓库） | 持牌后端（私有） |
|---|---|---|
| 身份/会话 | demo 自有用户表+会话表 | 绑定框架身份/会话能力 |
| RBAC/审批/通知/任务 | demo 自有等价语义实现 | 绑定框架对应能力 |
| 业务实体 | demo 自有 SQLite 记录存储（乐观版本+历史） | 绑定框架实体持久化 |
| 外部系统 | 注入的进程内确定性模拟（承运商账本） | 绑定框架外部写治理 + 模拟适配器 |
| UNKNOWN/对账 | demo 简版诚实实现 | 框架原生机制 |
| 助手消息持久化 | demo 本地 | **LIMITED**（待受支持框架 API） |

## 4. 确定性

- 默认脚本化 AI（无模型调用）；测试注入固定时钟；历史种子由独立的可信初始化入口在隔离 staging 数据库灌入，普通 Facade 不具备历史写入权限；两次种子重放内容哈希一致（契约测试验证）。
- 演示运行默认墙钟时间；业务结果不依赖时钟（逾期判断除外，属演示特性）。
