"""Stdlib HTTP server for the manufacturing demo application.

Single process, no external dependencies. The app depends only on the
framework_port Facade protocol — never on a concrete backend. The backend is
selected at startup (public simulation by default).
"""

from __future__ import annotations

import datetime as _dt
import re
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from framework_port import constants as C
from framework_port import errors as FE
from framework_port.dtos import Principal, RecordRef

from . import agents, i18n, policy, views
from .views import Ctx

SESSION_COOKIE = "hsw_session"
LANG_COOKIE = "hsw_lang"

SYSTEM = Principal("system", "自动哨兵（演示）", C.ROLE_ADMIN, "zh")


class DemoApp:
    """Application assembly: backend + policy + background sentinel."""

    def __init__(self, backend: Any, mode: str, default_lang: str = i18n.ZH,
                 scan_interval: float = 20.0) -> None:
        self.backend = backend
        self.mode = mode
        self.default_lang = default_lang
        self.scan_interval = scan_interval
        self._stop = threading.Event()
        caps = backend.query_capabilities()
        self.mode = str(caps.mode) if caps.mode else mode
        backend.configure_authorization(
            policy._RULES, policy.APPROVAL_POLICIES, policy.APPROVER_ROLES
        )
        self._thread: threading.Thread | None = None

    def start_sentinel(self) -> None:
        self._thread = threading.Thread(target=self._sentinel_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _sentinel_loop(self) -> None:
        while not self._stop.wait(self.scan_interval):
            try:
                self.scan_once()
            except Exception:  # noqa: BLE001 - the sentinel must never crash the app
                pass

    # ------------------------------------------------------ scheduled scans
    def scan_once(self) -> dict[str, int]:
        b = self.backend
        now = _dt.datetime.now().date()
        counts = {"overdue": 0, "low_stock": 0, "escalated": 0}
        for po in b.list_records(SYSTEM, C.RECORD_PRODUCTION_ORDER):
            due = str(po.fields.get("due_date", ""))[:10]
            state = str(po.fields.get("state", ""))
            if state in ("planned", "released", "in_production") and due and _date(due) <= now:
                if not _has_open_task(b, "overdue_po", po.ref):
                    b.create_task(
                        SYSTEM, "overdue_po",
                        f"处置逾期生产工单 {po.ref.record_id}",
                        "factory", related=po.ref, origin="agent",
                        note=f"交期 {due} 已到，请处理（改期或升级）。",
                    )
                    b.notify(
                        SYSTEM, "production.overdue", ("factory", "owner"),
                        title=f"生产逾期 {po.ref.record_id}",
                        body=f"工单交期 {due} 已到但未完工，已生成厂长处置任务。",
                        priority=C.PRIORITY_CRITICAL, related=po.ref,
                    )
                    counts["overdue"] += 1
        for item in b.list_records(SYSTEM, C.RECORD_INVENTORY_ITEM):
            qty = _float(item.fields.get("qty_on_hand"))
            reorder = _float(item.fields.get("reorder_point"))
            if 0 < reorder and qty < reorder:
                if not _has_open_task(b, "low_stock", item.ref):
                    b.create_task(
                        SYSTEM, "low_stock",
                        f"补货：{item.fields.get('name_cn', item.ref.record_id)}",
                        "warehouse", related=item.ref, origin="agent",
                        note=f"库存 {qty:g} 已低于订货点 {reorder:g}。",
                    )
                    b.notify(
                        SYSTEM, "inventory.below_reorder", ("warehouse", "factory"),
                        title=f"库存预警 {item.fields.get('name_cn', '')}",
                        body=f"现有 {qty:g}，低于订货点 {reorder:g}，已生成补货任务。",
                        priority=C.PRIORITY_WARNING, related=item.ref,
                    )
                    counts["low_stock"] += 1
        now_iso = b.query_capabilities() and None  # keep linters calm
        for approval in b.list_approvals(SYSTEM, pending_for_me=False):
            if approval.status != "pending":
                continue
            age_hours = _hours_since(approval.requested_at)
            if age_hours >= 4 and not _has_open_task(b, "approval_escalation", approval.target):
                b.create_task(
                    SYSTEM, "approval_escalation",
                    f"审批升级：{approval.approval_id}",
                    "owner", related=approval.target, origin="agent",
                    note=f"审批 {approval.approval_id} 已等待 {age_hours:.0f} 小时未决。",
                )
                b.notify(
                    SYSTEM, "approval.escalated", ("owner",),
                    title=f"审批升级 {approval.approval_id}",
                    body=f"{approval.kind} 已等待 {age_hours:.0f} 小时，请尽快处理。",
                    priority=C.PRIORITY_CRITICAL, related=approval.target,
                )
                counts["escalated"] += 1
        return counts

    # ------------------------------------------------------------ dispatch
    def handle(self, method: str, path: str, query: dict[str, str],
               form: dict[str, str], headers: dict[str, str]) -> tuple[int, str, list[tuple[str, str]]]:
        cookies = SimpleCookie(headers.get("Cookie", ""))
        token = cookies[SESSION_COOKIE].value if SESSION_COOKIE in cookies else ""
        actor = self.backend.resolve_session(token) if token else None
        # Language precedence: explicit request > cookie > account locale > app default.
        lang = form.get("lang") or query.get("lang") or (
            cookies[LANG_COOKIE].value if LANG_COOKIE in cookies
            else (actor.locale if actor is not None else self.default_lang)
        )
        set_cookies: list[tuple[str, str]] = []
        if lang != (cookies[LANG_COOKIE].value if LANG_COOKIE in cookies else ""):
            set_cookies.append(
                ("Set-Cookie", f"{LANG_COOKIE}={lang}; Path=/; Max-Age=2592000")
            )
        if path == "/login" and method == "GET":
            ctx = Ctx(self.backend, Principal("guest", "guest", "limited", lang),
                      lang, self.mode, query)
            body = views.page_login(ctx, error=str(query.get("error", "")))
            return 200, body, set_cookies
        if path == "/login" and method == "POST":
            principal = self.backend.authenticate(
                form.get("username", ""), form.get("credential", "")
            )
            if principal is None:
                return 303, "", [("Location", "/login?error=1&lang=" + lang)]
            new_token = self.backend.create_session(principal)
            set_cookies.append(("Set-Cookie", f"{SESSION_COOKIE}={new_token}; Path=/; HttpOnly"))
            return 303, "", set_cookies + [("Location", "/dashboard?lang=" + lang)]
        if path == "/logout" and method == "POST":
            if token:
                self.backend.close_session(token)
            set_cookies.append(("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0"))
            return 303, "", set_cookies + [("Location", "/login?lang=" + lang)]
        if actor is None:
            return 303, "", [("Location", "/login?lang=" + lang)]
        ctx = Ctx(self.backend, actor, lang, self.mode, {**query, **form},
                  current_path=path)
        try:
            result = self._route(method, path, ctx, form)
        except FE.FacadeError as exc:
            status, body = views.error_page(ctx, exc)
            return status, body, set_cookies
        except Exception as exc:  # noqa: BLE001 - sanitized 500 (no internals leaked)
            body = views.layout(ctx, "Error", "", (
                f"<div class='flash err'>{esc_html(ctx.t('error'))}</div>"
                "<p class='muted'>Request failed. No internal details are shown.</p>"))
            return 500, body, set_cookies
        status, body, extra = _as_response(result, ctx)
        return status, body, set_cookies + extra

    def _route(self, method: str, path: str, ctx: Ctx, form: dict[str, str]):
        b = ctx.backend
        lang = ctx.lang
        if method == "POST" and path == "/set-lang":
            # The language cookie was already set by handle() from this form.
            next_url = form.get("next") or "/dashboard"
            return ctx.redirect(next_url)
        if method == "GET" and path == "/":
            return ctx.redirect(f"/dashboard?lang={lang}")
        if path == "/dashboard" and method == "GET":
            return views.page_dashboard(ctx)
        if path == "/customers" and method == "GET":
            return views.page_customers(ctx)
        if path == "/customers/new" and method == "POST":
            rec = b.create_record(ctx.actor, C.RECORD_CUSTOMER, {
                "name_cn": form.get("name_cn", ""),
                "name_en": form.get("name_en", ""),
                "contact": form.get("contact", ""),
                "city": form.get("city", ""),
                "state": "active",
            })
            return ctx.redirect(views.flash_link("/customers", lang, ctx.t("created")))
        if path == "/quotations" and method == "GET":
            return views.page_quotations(ctx)
        if path == "/quotations/new" and method == "GET":
            return views.page_quotation_new(ctx)
        if path == "/quotations/draft" and method == "POST":
            draft = agents.quote_draft(
                b, ctx.actor,
                customer_name=form.get("customer_name", ""),
                product_id=form.get("product_id", ""),
                qty=form.get("qty", ""),
                discount_pct=form.get("discount_pct", ""),
                requested_date=form.get("requested_date", ""),
            )
            return views.page_quotation_new(ctx, draft)
        if path == "/quotations" and method == "POST":
            rec = b.create_record(ctx.actor, C.RECORD_QUOTATION, {
                "customer_name": form.get("customer_name", ""),
                "product_id": form.get("product_id", ""),
                "product_name": form.get("product_name", ""),
                "qty": form.get("qty", "0"),
                "list_price": form.get("list_price", "0"),
                "discount_pct": form.get("discount_pct", "0"),
                "unit_price": form.get("unit_price", "0"),
                "total_amount": form.get("total_amount", "0"),
                "currency": "CNY",
                "requested_date": form.get("requested_date", ""),
                "state": "draft",
            })
            b.create_record(ctx.actor, C.RECORD_QUOTATION_LINE, {
                "quotation_id": rec.ref.record_id,
                "product_id": form.get("product_id", ""),
                "product_name": form.get("product_name", ""),
                "qty": rec.fields["qty"],
                "unit_price": rec.fields["unit_price"],
            })
            return ctx.redirect(views.flash_link(
                f"/quotations/{rec.ref.record_id}", lang, ctx.t("created")))
        match = re.fullmatch(r"/quotations/([A-Za-z0-9_\-]+)", path)
        if match and method == "GET":
            return views.page_quotation_detail(ctx, match.group(1))
        match = re.fullmatch(r"/quotations/([A-Za-z0-9_\-]+)/(submit|accept)", path)
        if match and method == "POST":
            qid, action = match.group(1), match.group(2)
            action_id = (C.ACTION_QUOTATION_SUBMIT if action == "submit"
                         else C.ACTION_QUOTATION_ACCEPT)
            if set(form) - {"lang", "justification", "discount_pct"}:
                raise FE.ValidationFailed("quotation action cannot override business fields")
            payload: dict[str, Any] = {"justification": form.get("justification", "")}
            if "discount_pct" in form:
                # Preserve the raw value: the backend validates it against the
                # stored quotation; invalid input must never become zero.
                payload["discount_pct"] = form["discount_pct"]
            result = b.execute_business_action(
                ctx.actor, RecordRef(C.RECORD_QUOTATION, qid), action_id, payload,
            )
            state_text = i18n.state_label(lang, result.state)
            return ctx.redirect(views.flash_link(
                f"/quotations/{qid}", lang,
                result.note or state_text,
                "err" if result.approval_id else "ok",
            ))
        if path == "/orders" and method == "GET":
            return views.page_orders(ctx)
        match = re.fullmatch(r"/orders/([A-Za-z0-9_\-]+)", path)
        if match and method == "GET":
            return views.page_order_detail(ctx, match.group(1))
        match = re.fullmatch(r"/orders/([A-Za-z0-9_\-]+)/confirm", path)
        if match and method == "POST":
            oid = match.group(1)
            result = b.execute_business_action(
                ctx.actor, RecordRef(C.RECORD_SALES_ORDER, oid), C.ACTION_SALES_ORDER_CONFIRM,
                {"justification": form.get("justification", "")},
            )
            return ctx.redirect(views.flash_link(f"/orders/{oid}", lang, result.note or i18n.state_label(lang, result.state)))
        match = re.fullmatch(r"/orders/([A-Za-z0-9_\-]+)/change", path)
        if match and method == "POST":
            oid = match.group(1)
            price_change = form.get("price_change", "false") == "true"
            result = b.execute_business_action(
                ctx.actor, RecordRef(C.RECORD_SALES_ORDER, oid),
                C.ACTION_SALES_ORDER_REQUEST_CHANGE,
                {"price_change": price_change,
                 "fields_delta": {"requested_date": form.get("new_date", "")},
                 "justification": form.get("justification", "")},
            )
            return ctx.redirect(views.flash_link(f"/orders/{oid}", lang, result.note or i18n.state_label(lang, result.state)))
        match = re.fullmatch(r"/orders/([A-Za-z0-9_\-]+)/create-po", path)
        if match and method == "POST":
            oid = match.group(1)
            requirements = _requirements_for(b, ctx.actor, form.get("product_id", ""),
                                             _float(form.get("qty", "0")))
            result = b.execute_business_action(
                ctx.actor, RecordRef(C.RECORD_SALES_ORDER, oid),
                C.ACTION_PRODUCTION_ORDER_CREATE,
                {"product_id": form.get("product_id", ""),
                 "product_name": form.get("product_name", ""),
                 "qty": _float(form.get("qty", "0")),
                 "due_date": form.get("due_date", ""),
                 "expedite": form.get("expedite", "false") == "true",
                 "substitute": False,
                 "requirements": requirements,
                 "justification": form.get("justification", "")},
            )
            target = result.ref.record_id if result.ref.record_type == C.RECORD_PRODUCTION_ORDER else oid
            return ctx.redirect(views.flash_link(f"/production/{target}", lang,
                                                 result.note or i18n.state_label(lang, result.state)))
        match = re.fullmatch(r"/orders/([A-Za-z0-9_\-]+)/ai-atp", path)
        if match and method == "POST":
            oid = match.group(1)
            order = b.get_record(ctx.actor, RecordRef(C.RECORD_SALES_ORDER, oid))
            if order is None:
                raise FE.NotFound(oid)
            report = agents.atp_check(b, ctx.actor, order)
            if report["ok"]:
                return ctx.redirect(views.flash_link(f"/orders/{oid}", lang, report["note"]))
            notes = []
            for line in report["shortages"]:
                suggestion = agents.expedite_payload(line)
                if ctx.actor.role == C.ROLE_OWNER:
                    notes.append(f"检测到 {line['name']} 缺 {line['short']:g}"
                                 f"（审批须由销售/厂长发起，老板只审批）")
                    continue
                b.request_approval(
                    ctx.actor, C.APPROVAL_EXPEDITE_PURCHASE, order.ref,
                    suggestion,
                    justification=f"订单 {oid} 缺料 {line['short']:g} kg，建议采购 "
                                  f"{suggestion['qty']:g} kg（AI 建议，等待审批）",
                )
                notes.append(f"已为 {line['name']} 生成紧急采购审批请求 "
                             f"（建议 {suggestion['qty']:g} kg）")
            return ctx.redirect(views.flash_link(f"/orders/{oid}", lang,
                                                 "；".join(notes), "err"))
        match = re.fullmatch(r"/orders/([A-Za-z0-9_\-]+)/ship", path)
        if match and method == "POST":
            oid = match.group(1)
            result = b.execute_business_action(
                ctx.actor, RecordRef(C.RECORD_SALES_ORDER, oid), C.ACTION_SHIPMENT_REQUEST,
                {"address": form.get("address", "")},
            )
            sid = result.ref.record_id if result.ref.record_type == C.RECORD_SHIPMENT else ""
            return ctx.redirect(views.flash_link(f"/shipments/{sid}" if sid else f"/orders/{oid}",
                                                 lang, result.note or i18n.state_label(lang, result.state)))
        match = re.fullmatch(r"/production/([A-Za-z0-9_\-]+)", path)
        if match and method == "GET":
            return views.page_production_detail(ctx, match.group(1))
        match = re.fullmatch(r"/production/([A-Za-z0-9_\-]+)/(release|issue|progress|complete|reschedule)", path)
        if match and method == "POST":
            pid, action = match.group(1), match.group(2)
            action_id = {
                "release": C.ACTION_PRODUCTION_ORDER_RELEASE,
                "issue": C.ACTION_PRODUCTION_ORDER_ISSUE_MATERIAL,
                "progress": C.ACTION_PRODUCTION_ORDER_REPORT_PROGRESS,
                "complete": C.ACTION_PRODUCTION_ORDER_COMPLETE,
            }.get(action)
            ref = RecordRef(C.RECORD_PRODUCTION_ORDER, pid)
            if action == "reschedule":
                suggestion = agents.reschedule_suggestion(b, ctx.actor, b.get_record(ctx.actor, ref))
                row = b.get_record(ctx.actor, ref)
                import datetime as _dt2
                due = str(row.fields.get("due_date", ""))[:10] if row else ""
                new_due = (_dt2.date.fromisoformat(due) + _dt2.timedelta(days=2)).isoformat() if due else ""
                b.update_record(ctx.actor, ref, {"due_date": new_due},
                                expected_version=row.ref.version if row else 1)
                b.notify(ctx.actor, "production.rescheduled", ("sales", "factory"),
                         title=f"改期通知 {pid}",
                         body=f"工单交期调整为 {new_due}（采纳 AI 建议）。" + suggestion["note"],
                         priority=C.PRIORITY_NORMAL, related=ref)
                return ctx.redirect(views.flash_link(f"/production/{pid}", lang,
                                                     f"交期调整为 {new_due}"))
            payload = {
                "progress_pct": _float(form.get("progress_pct", "0")),
            } if action == "progress" else {}
            result = b.execute_business_action(ctx.actor, ref, action_id, payload)
            return ctx.redirect(views.flash_link(f"/production/{pid}", lang,
                                                 result.note or i18n.state_label(lang, result.state)))
        match = re.fullmatch(r"/inventory/([A-Za-z0-9_\-]+)/(receipt|adjust)", path)
        if match and method == "POST":
            iid, action = match.group(1), match.group(2)
            payload = (
                {"qty": form.get("qty", "")}
                if action == "receipt"
                else {key: form[key] for key in ("adjust_qty", "adjust_amount", "adjust_pct", "justification")
                      if key in form}
            )
            action_id = (C.ACTION_INVENTORY_RECEIPT if action == "receipt"
                         else C.ACTION_INVENTORY_ADJUST)
            result = b.execute_business_action(
                ctx.actor, RecordRef(C.RECORD_INVENTORY_ITEM, iid), action_id, payload)
            return ctx.redirect(views.flash_link("/inventory", lang,
                                                 result.note or i18n.state_label(lang, result.state)))
        if path == "/production" and method == "GET":
            return views.page_production(ctx)
        if path == "/inventory" and method == "GET":
            return views.page_inventory(ctx)
        if path == "/tasks" and method == "GET":
            return views.page_tasks(ctx)
        match = re.fullmatch(r"/tasks/([A-Za-z0-9_\-]+)/complete", path)
        if match and method == "POST":
            task = b.complete_task(ctx.actor, match.group(1),
                                   note=form.get("note", ""))
            return ctx.redirect(views.flash_link("/tasks", lang, ctx.t("completed")))
        match = re.fullmatch(r"/tasks/([A-Za-z0-9_\-]+)/handoff", path)
        if match and method == "POST":
            view = b.request_handoff(ctx.actor, match.group(1), form.get("to_actor", ""),
                                     reason=form.get("reason", ""))
            return ctx.redirect(views.flash_link("/tasks", lang,
                                                 f"交接请求已发送给 {view.to_actor}"))
        match = re.fullmatch(r"/handoffs/([A-Za-z0-9_\-]+)/respond", path)
        if match and method == "POST":
            view = b.respond_handoff(ctx.actor, match.group(1),
                                     form.get("decision") == "accept",
                                     note=form.get("note", ""))
            return ctx.redirect(views.flash_link("/tasks", lang,
                                                 f"交接{('已接受' if view.status == 'accepted' else '已拒绝')}"))
        if path == "/approvals" and method == "GET":
            return views.page_approvals(ctx)
        match = re.fullmatch(r"/approvals/([A-Za-z0-9_\-]+)/(approve|reject)", path)
        if match and method == "POST":
            view = (b.approve(ctx.actor, match.group(1), comment=form.get("comment", ""))
                    if match.group(2) == "approve"
                    else b.reject(ctx.actor, match.group(1), comment=form.get("comment", "已拒绝")))
            return ctx.redirect(views.flash_link("/approvals", lang,
                                                 f"{view.approval_id} → {view.status}"))
        if path == "/notifications" and method == "GET":
            return views.page_notifications(ctx)
        match = re.fullmatch(r"/notifications/([A-Za-z0-9_\-]+)/read", path)
        if match and method == "POST":
            b.mark_notification_read(ctx.actor, match.group(1))
            return ctx.redirect(views.flash_link("/notifications", lang, ctx.t("read")))
        if path == "/audit" and method == "GET":
            return views.page_audit(ctx)
        match = re.fullmatch(r"/audit/([a-z_]+)/([A-Za-z0-9_\-]+)", path)
        if match and method == "GET":
            return views.page_audit_subject(ctx, match.group(1), match.group(2))
        if path == "/admin" and method == "GET":
            return views.page_admin(ctx)
        if path == "/assistant" and method == "GET":
            return views.page_assistant(ctx)
        if path == "/assistant" and method == "POST":
            return views.assistant_post(ctx, form.get("text", ""))
        match = re.fullmatch(r"/shipments/([A-Za-z0-9_\-]+)", path)
        if match and method == "GET":
            ship = b.get_record(ctx.actor, RecordRef(C.RECORD_SHIPMENT, match.group(1)))
            if ship is None:
                raise FE.NotFound(match.group(1))
            return ctx.redirect(f"/orders/{ship.fields.get('order_id', '')}?lang={lang}")
        match = re.fullmatch(r"/shipments/([A-Za-z0-9_\-]+)/dispatch", path)
        if match and method == "POST":
            sid = match.group(1)
            ship = b.get_record(ctx.actor, RecordRef(C.RECORD_SHIPMENT, sid))
            if ship is None:
                raise FE.NotFound(sid)
            view = b.submit_governed_action(
                ctx.actor, C.GOVERNED_CARRIER_DISPATCH,
                RecordRef(C.RECORD_SHIPMENT, sid),
                {"order_id": ship.fields.get("order_id", ""),
                 "customer": ship.fields.get("customer_name", ""),
                 "address": ship.fields.get("address", "")},
                reason="发货执行（演示治理策略：承运派发免独立审批，见 BOUNDARY 文档）",
            )
            view = b.execute_governed_action(ctx.actor, view.action_id)
            return ctx.redirect(views.flash_link(
                f"/orders/{ship.fields.get('order_id', '')}", lang,
                f"发货已执行一次；{i18n.t(lang, 'truth_command')}="
                f"{i18n.t(lang, 'truth_unknown') if view.state == 'unknown' else view.state}（诚实显示）", "err"))
        match = re.fullmatch(r"/shipments/([A-Za-z0-9_\-]+)/reconcile", path)
        if match and method == "POST":
            sid = match.group(1)
            gov = _find_latest_governed(b, ctx.actor, sid)
            if gov is None:
                raise FE.NotFound("governed action")
            result = b.reconcile_external_action(ctx.actor, gov.action_id)
            ship = b.get_record(ctx.actor, RecordRef(C.RECORD_SHIPMENT, sid))
            oid = str(ship.fields.get("order_id", "")) if ship else ""
            if result.external_verdict == C.VERDICT_MATCHED_DERIVED:
                b.notify(ctx.actor, "shipment.reconciled", ("sales", "owner"),
                         title=f"发货已对账 {sid}",
                         body=f"外部承运商账本匹配（推导）。命令真相保持 {result.command_truth}。",
                         priority=C.PRIORITY_NORMAL,
                         related=RecordRef(C.RECORD_SALES_ORDER, oid))
                task = None
                for t in b.list_tasks(ctx.actor, status=C.TASK_STATUS_OPEN):
                    if t.kind == "shipment_dispatch" and t.related and \
                            t.related.record_id == sid:
                        b.complete_task(ctx.actor, t.task_id, note="对账完成")
                        break
            return ctx.redirect(views.flash_link(
                f"/orders/{oid}", lang,
                f"对账判定={result.external_verdict}；{i18n.t(lang, 'truth_command')}="
                f"{i18n.t(lang, 'truth_unknown') if result.command_truth == 'unknown' else result.command_truth}（两轴独立）"))
        raise FE.NotFound(f"no route for {path}")


# ------------------------------------------------------------------ helpers
def esc_html(text: str) -> str:
    import html as _html
    return _html.escape(str(text), quote=True)


def _float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _date(value: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(value[:10])
    except ValueError:
        return _dt.date.max


def _hours_since(iso: str) -> float:
    try:
        then = _dt.datetime.fromisoformat(iso)
        now = _dt.datetime.now(then.tzinfo or _dt.timezone.utc)
        return max(0.0, (now - then).total_seconds() / 3600.0)
    except ValueError:
        return 0.0


def _has_open_task(b, kind: str, ref: RecordRef) -> bool:
    for task in b.list_tasks(SYSTEM, status=C.TASK_STATUS_OPEN):
        if task.kind == kind and task.related is not None \
                and task.related.record_id == ref.record_id:
            return True
    return False


def _requirements_for(b, actor: Principal, product_id: str, qty: float) -> list[dict]:
    import json as _json
    products = b.list_records(actor, C.RECORD_PRODUCT, filters={"id": product_id})
    if not products:
        return []
    try:
        bom = dict(_json.loads(str(products[0].fields.get("bom", "{}"))))
    except ValueError:
        return []
    materials = {m.ref.record_id: m.fields for m in b.list_records(actor, C.RECORD_MATERIAL)}
    return [
        {"material_id": mid, "material_name": str(materials.get(mid, {}).get("name_cn", mid)),
         "qty": round(_float(per) * qty, 2)}
        for mid, per in sorted(bom.items())
    ]


def _find_latest_governed(b, actor: Principal, shipment_id: str):
    try:
        entries = b.get_audit_timeline(actor, RecordRef(C.RECORD_SHIPMENT, shipment_id))
    except FE.FacadeError:
        return None
    for entry in reversed(entries):
        if entry.parent is not None and entry.parent.record_type == "governed_action":
            view = b.get_governed_action(actor, entry.parent.record_id)
            if view is not None:
                return view
    return None


def _as_response(result, ctx: Ctx) -> tuple[int, str, list[tuple[str, str]]]:
    if isinstance(result, tuple) and len(result) == 3 and result[0] == 303:
        return 303, "", [("Location", result[2])]
    if isinstance(result, tuple) and len(result) == 2:
        status, body = result
        return status, body, []
    status, body = result  # type: ignore[misc]
    return status, body, []


def make_handler(app: DemoApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:  # quiet
            pass

        def _dispatch(self, method: str) -> None:
            parsed = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            form: dict[str, str] = {}
            length = int(self.headers.get("Content-Length", "0") or 0)
            if method == "POST" and length:
                raw = self.rfile.read(length).decode("utf-8")
                form = {k: v[0] for k, v in parse_qs(raw).items()}
            headers = {k: v for k, v in self.headers.items()}
            try:
                status, body, extra_headers = app.handle(
                    method, parsed.path, query, form, headers
                )
            except Exception:  # noqa: BLE001 - last-resort guard
                status, body, extra_headers = 500, "internal error", []
            self.send_response(status)
            for key, value in extra_headers:
                self.send_header(key, value)
            if body:
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body.encode("utf-8"))))
            self.end_headers()
            if body:
                self.wfile.write(body.encode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

    return Handler


def serve(app: DemoApp, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(app))
    app.start_sentinel()
    try:
        server.serve_forever()
    finally:
        app.stop()
        server.server_close()
