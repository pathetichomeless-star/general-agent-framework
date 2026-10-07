"""Bilingual UI dictionary. Simplified Chinese is the default language;
English is an optional switch. All UI copy goes through :func:`t` — the demo
has no other wording source, which keeps the two languages consistent."""

from __future__ import annotations

ZH = "zh"
EN = "en"

_DICT: dict[str, tuple[str, str]] = {
    # brand & chrome
    "app_name": ("宏晟智造", "Hongsheng Works"),
    "app_subtitle": ("受治理制造示范应用", "Governed Manufacturing Demo"),
    "mode_public": ("公共模拟模式 · 确定性演示（非商业框架运行时）",
                    "PUBLIC SIMULATION MODE · deterministic demo (not the licensed runtime)"),
    "mode_licensed": ("商业框架模式 · 已连接持牌框架",
                      "LICENSED FRAMEWORK MODE · bound to the licensed framework"),
    "lang_switch": ("English", "中文"),
    # nav
    "nav_dashboard": ("工作台", "Dashboard"),
    "nav_customers": ("客户", "Customers"),
    "nav_quotations": ("报价", "Quotations"),
    "nav_orders": ("销售订单", "Sales Orders"),
    "nav_production": ("生产", "Production"),
    "nav_inventory": ("库存", "Inventory"),
    "nav_tasks": ("任务", "Tasks"),
    "nav_approvals": ("审批", "Approvals"),
    "nav_notifications": ("通知", "Notifications"),
    "nav_audit": ("审计记录", "Audit Trail"),
    "nav_admin": ("用户与角色", "Users & Roles"),
    # login
    "login_title": ("登录 宏晟智造", "Sign in to Hongsheng Works"),
    "username": ("用户名", "Username"),
    "password": ("密码", "Password"),
    "login": ("登录", "Sign in"),
    "logout": ("退出", "Sign out"),
    "demo_accounts": ("演示账号（点击即填）", "Demo accounts (click to fill)"),
    "login_failed": ("用户名或密码不正确", "Incorrect username or password"),
    # generic
    "state": ("状态", "State"),
    "actions": ("操作", "Actions"),
    "detail": ("详情", "Detail"),
    "back": ("返回", "Back"),
    "submit": ("提交", "Submit"),
    "approve": ("通过", "Approve"),
    "reject": ("拒绝", "Reject"),
    "complete": ("完成", "Complete"),
    "execute": ("执行", "Execute"),
    "create": ("新建", "Create"),
    "save": ("保存", "Save"),
    "reason": ("理由", "Reason"),
    "comment": ("审批意见", "Comment"),
    "justification": ("申请理由", "Justification"),
    "none": ("无", "None"),
    "yes": ("是", "Yes"),
    "no": ("否", "No"),
    "total": ("合计", "Total"),
    "qty": ("数量", "Qty"),
    "due_date": ("交期", "Due date"),
    "requested_by": ("发起人", "Requested by"),
    "requested_at": ("发起时间", "Requested at"),
    "assignee": ("责任人", "Assignee"),
    "read": ("已读", "Read"),
    "unread": ("未读", "Unread"),
    "mark_read": ("标为已读", "Mark read"),
    "handoff": ("交接", "Handoff"),
    "to_actor": ("交接给", "Hand over to"),
    "accept": ("接受", "Accept"),
    "decline": ("拒绝", "Decline"),
    "verified": ("验证通过", "VERIFIED"),
    "failed": ("验证失败", "FAILED"),
    "verify_chain": ("验证证据链", "Verify evidence chain"),
    # states
    "st_draft": ("草稿", "Draft"),
    "st_pending_approval": ("待审批", "Pending approval"),
    "st_approved": ("已批准", "Approved"),
    "st_accepted": ("已接受", "Accepted"),
    "st_rejected": ("已拒绝", "Rejected"),
    "st_confirmed": ("已确认", "Confirmed"),
    "st_change_pending": ("变更待批", "Change pending"),
    "st_planned": ("已计划", "Planned"),
    "st_released": ("已下达", "Released"),
    "st_in_production": ("生产中", "In production"),
    "st_completed": ("已完成", "Completed"),
    "st_cancelled": ("已取消", "Cancelled"),
    "st_ready_to_ship": ("待发货", "Ready to ship"),
    "st_shipped": ("已发货", "Shipped"),
    "st_closed": ("已结案", "Closed"),
    "st_requested": ("已申请", "Requested"),
    "st_dispatched_unknown": ("已发货 · 命令真相未知", "Dispatched · command truth UNKNOWN"),
    "st_reconciled_matched": ("已对账 · 匹配（推导）", "Reconciled · MATCHED (derived)"),
    "st_open": ("进行中", "Open"),
    "st_done": ("已完成", "Done"),
    "st_pending": ("待处理", "Pending"),
    "st_dispatched": ("已发货", "Dispatched"),
    # priorities
    "p_critical": ("紧急", "Critical"),
    "p_warning": ("预警", "Warning"),
    "p_normal": ("普通", "Normal"),
    "p_low": ("低", "Low"),
    # record names
    "rec_customer": ("客户", "Customer"),
    "rec_product": ("产品", "Product"),
    "rec_material": ("物料", "Material"),
    "rec_quotation": ("报价单", "Quotation"),
    "rec_sales_order": ("销售订单", "Sales Order"),
    "rec_production_order": ("生产工单", "Production Order"),
    "rec_inventory_item": ("库存", "Inventory"),
    "rec_shipment": ("发货单", "Shipment"),
    "rec_approval": ("审批", "Approval"),
    # fields
    "f_name": ("名称", "Name"),
    "f_contact": ("联系人", "Contact"),
    "f_city": ("城市", "City"),
    "f_list_price": ("目录价", "List price"),
    "f_unit": ("单位", "Unit"),
    "f_discount_pct": ("折扣 %", "Discount %"),
    "f_unit_price": ("成交单价", "Unit price"),
    "f_total_amount": ("总金额 (¥)", "Total (¥)"),
    "f_product": ("产品", "Product"),
    "f_customer": ("客户", "Customer"),
    "f_qty_on_hand": ("现有库存", "On hand"),
    "f_reorder_point": ("订货点", "Reorder point"),
    "f_item": ("对象", "Item"),
    "f_progress": ("进度 %", "Progress %"),
    "f_overdue": ("逾期", "Overdue"),
    # dashboard cards
    "card_pending_approvals": ("待我审批", "Pending my approval"),
    "card_open_tasks": ("我的任务", "My open tasks"),
    "card_overdue_production": ("逾期生产", "Overdue production"),
    "card_low_stock": ("低于订货点", "Below reorder point"),
    "card_digest": ("今日摘要", "Today's summary"),
    "card_orders": ("订单", "Orders"),
    "card_production": ("生产", "Production"),
    "card_inventory": ("库存", "Inventory"),
    "card_notifications": ("通知", "Notifications"),
    # business verbs
    "act_submit_quote": ("提交报价（折扣 {pct}%）", "Submit quotation ({pct}% discount)"),
    "act_accept_quote": ("接受报价并生成订单", "Accept quotation → create order"),
    "act_confirm_order": ("确认订单", "Confirm order"),
    "act_request_change": ("申请订单变更", "Request order change"),
    "act_create_po": ("创建生产工单", "Create production order"),
    "act_release": ("下达工单", "Release"),
    "act_issue": ("领料", "Issue material"),
    "act_progress": ("报工", "Report progress"),
    "act_complete": ("完工", "Complete"),
    "act_receipt": ("入库", "Receipt"),
    "act_adjust": ("盘点调整", "Cycle-count adjust"),
    "act_request_shipment": ("申请发货", "Request shipment"),
    "act_dispatch": ("执行发货", "Dispatch shipment"),
    "act_reconcile": ("对账", "Reconcile"),
    "act_ai_draft": ("AI 起草报价", "AI draft quotation"),
    "act_ai_atp": ("AI 物料与产能检查", "AI material & capacity check"),
    "act_ai_reschedule": ("AI 改期建议", "AI reschedule suggestion"),
    "act_accept_suggestion": ("采纳建议", "Accept suggestion"),
    "act_expedite_purchase": ("紧急采购申请", "Expedited purchase request"),
    # governed / truth
    "truth_command": ("命令真相", "Command truth"),
    "truth_external": ("外部真相（对账判定）", "External truth (reconciliation verdict)"),
    "truth_unknown": ("未知 UNKNOWN", "UNKNOWN"),
    "truth_matched": ("匹配 MATCHED（推导）", "MATCHED (derived)"),
    "truth_unobservable": ("不可观测 UNOBSERVABLE", "UNOBSERVABLE"),
    "ledger": ("承运商账本", "Carrier ledger"),
    "retry_refused": ("盲重试被拒绝：命令真相为 UNKNOWN，框架不允许在未对账前重发。",
                      "Blind retry refused: command truth is UNKNOWN; re-sending before "
                      "reconciliation is not allowed."),
    "governed_note": ("这是一个受治理外部动作：先登记、再执行一次；响应丢失时诚实记录"
                      "为 UNKNOWN，对账给出独立的外部判定。两个真相永不合并。",
                      "This is a governed external action: recorded first, executed once; "
                      "a lost response is honestly recorded as UNKNOWN, and reconciliation "
                      "derives an independent external verdict. The two truths are never merged."),
    # assistant
    "assistant_title": ("AI 助手", "AI Assistant"),
    "assistant_placeholder": ("问我任何业务问题，例如“帮我看下缺料情况”", 
                              "Ask me anything, e.g. 'any material shortages?'"),
    "assistant_send": ("发送", "Send"),
    "assistant_limited_note": ("助手消息为演示本地持久化；商业框架模式下此能力标记为 LIMITED。",
                               "Assistant messages persist demo-locally; in licensed mode this "
                               "capability is LIMITED until a supported API exists."),
    # audit
    "audit_title": ("审计记录", "Audit Trail"),
    "audit_subject": ("对象", "Subject"),
    "audit_note": ("哈希链验证范围 = 审批任务证据；其余审计记录为保留可审计（不入链）。",
                   "Hash-chain verification scope = approval-task evidence; other audit records "
                   "are retained and auditable (not chained)."),
    # admin
    "admin_users": ("用户", "Users"),
    "admin_roles": ("角色", "Role"),
    "admin_note": ("管理员负责账号与审计，不参与业务操作——治理边界即产品行为。",
                   "Administrators manage accounts and audit; they do not operate the business — "
                   "the governance boundary is the product behaviour."),
    # misc
    "forbidden": ("没有权限执行该操作", "You are not allowed to perform this operation"),
    "error": ("操作失败", "Operation failed"),
    "welcome": ("欢迎", "Welcome"),
    "simulated_mail": ("模拟邮件（不发真实邮件）", "Simulated mailbox (no real email is sent)"),
    "sent_at": ("时间", "Sent at"),
    "eta": ("预计到货", "ETA"),
    "material": ("物料", "Material"),
    "shortage": ("缺料", "Shortage"),
    "recommendation": ("AI 建议", "AI recommendation"),
    "customer_inquiry": ("客户询价", "Customer inquiry"),
    "items": ("明细", "Items"),
    "new_quotation": ("新建报价", "New quotation"),
    "order_lines": ("订单行", "Order lines"),
    "requirements": ("物料需求", "Material requirements"),
    "shipments": ("发货", "Shipments"),
    "production_orders": ("生产工单", "Production orders"),
    "created": ("已创建", "Created"),
    "no_records": ("暂无记录", "No records"),
    # table headers & audit wording
    "h_body": ("内容", "Body"),
    "h_actor": ("操作人", "Actor"),
    "h_action": ("动作", "Action"),
    "h_kind": ("审批类型", "Kind"),
    "h_item": ("对象", "Subject"),
    "h_seq": ("#", "Seq"),
    "h_time": ("时间", "Time"),
    "other_subjects": ("其他对象", "Other subjects"),
    "entries_scope": ("条 · 范围=审批任务证据域", "entries · scope=approval-task evidence"),
    "truth_unknown_kept": ("命令真相保持未知（诚实记录）", "Command truth stays UNKNOWN (honestly recorded)"),
    "by_warehouse": ("由仓库执行", "executed by warehouse"),
    "by_factory": ("由厂长执行", "executed by factory manager"),
    "by_sales": ("由销售执行", "executed by sales"),
    "state_not_allowed": ("当前状态不允许该操作。", "This action is not allowed in the current state."),
    "no_permission_generic": ("您没有执行该操作的权限——该操作属于其他岗位职责。",
                              "You are not allowed to do this — it belongs to another role."),
    "denied_detail": ("系统备注", "System note"),
}

# 审批类型与记录类型的人话标签（zh 优先；en 用原词的友好形式）
APPROVAL_KIND_LABELS: dict[str, tuple[str, str]] = {
    "quotation.submit": ("报价折扣审批", "Quotation discount approval"),
    "quotation.accept": ("报价接受", "Quotation acceptance"),
    "sales_order.confirm": ("大额订单确认", "Order confirmation"),
    "sales_order.request_change": ("订单变更审批", "Order change approval"),
    "production_order.create": ("生产工单审批", "Production order approval"),
    "inventory.adjust_cycle_count": ("盘点调整审批", "Inventory adjustment approval"),
    "material.expedite_purchase": ("紧急采购审批", "Expedited purchase approval"),
}

RECORD_LABELS: dict[str, tuple[str, str]] = {
    "customer": ("客户", "Customer"),
    "product": ("产品", "Product"),
    "material": ("物料", "Material"),
    "price_book_entry": ("价目表", "Price book"),
    "quotation": ("报价单", "Quotation"),
    "quotation_line": ("报价明细", "Quote line"),
    "sales_order": ("销售订单", "Sales order"),
    "sales_order_line": ("订单明细", "Order line"),
    "production_order": ("生产工单", "Production order"),
    "material_requirement": ("物料需求", "Material requirement"),
    "inventory_item": ("库存", "Inventory"),
    "inventory_movement": ("库存流水", "Stock movement"),
    "shipment": ("发货单", "Shipment"),
    "approval": ("审批", "Approval"),
    "task": ("任务", "Task"),
}


def rec_label(lang: str, record_type: str) -> str:
    entry = RECORD_LABELS.get(record_type)
    if entry is None:
        return record_type
    return entry[1] if lang == EN else entry[0]


def kind_label(lang: str, kind: str) -> str:
    entry = APPROVAL_KIND_LABELS.get(kind)
    if entry is None:
        return kind
    return entry[1] if lang == EN else entry[0]


def fmt_num(value: object) -> str:
    """1000.0 → '1000'，10.5 → '10.5'（去尾零，加千分位）。"""

    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def fmt_time(iso: str) -> str:
    """2026-10-07T05:41:01+00:00 → 10-07 05:41（人话化时间）。"""

    if not iso:
        return ""
    date_part = iso[:16].replace("T", " ")
    if len(date_part) >= 16:
        return date_part[5:]
    return date_part


def t(lang: str, key: str, **kwargs: object) -> str:
    entry = _DICT.get(key)
    if entry is None:
        return key
    text = entry[0] if lang != EN else entry[1]
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text


STATE_KEYS = {
    "draft": "st_draft",
    "pending_approval": "st_pending_approval",
    "approved": "st_approved",
    "accepted": "st_accepted",
    "rejected": "st_rejected",
    "confirmed": "st_confirmed",
    "change_pending": "st_change_pending",
    "planned": "st_planned",
    "released": "st_released",
    "in_production": "st_in_production",
    "completed": "st_completed",
    "cancelled": "st_cancelled",
    "ready_to_ship": "st_ready_to_ship",
    "shipped": "st_shipped",
    "closed": "st_closed",
    "requested": "st_requested",
    "dispatched_unknown": "st_dispatched_unknown",
    "reconciled_matched": "st_reconciled_matched",
    "dispatched": "st_dispatched",
    "open": "st_open",
    "done": "st_done",
    "pending": "st_pending",
}

PRIORITY_KEYS = {
    "critical": "p_critical",
    "warning": "p_warning",
    "normal": "p_normal",
    "low": "p_low",
}


def state_label(lang: str, state: str) -> str:
    return t(lang, STATE_KEYS.get(state, state))


def priority_label(lang: str, priority: str) -> str:
    return t(lang, PRIORITY_KEYS.get(priority, priority))


def pick(lang: str, obj: object, base: str) -> str:
    """Pick a bilingual data field: ``base_cn`` / ``base_en``."""

    fields = obj if isinstance(obj, dict) else getattr(obj, "fields", {})
    suffix = "_en" if lang == EN else "_cn"
    value = fields.get(base + suffix) or fields.get(base + "_cn") or fields.get(base, "")
    return str(value)
