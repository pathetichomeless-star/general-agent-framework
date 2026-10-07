"""Server-rendered HTML views (stdlib only, no template engine).

Simplified Chinese is the default language; English is a switch. All copy
comes from app.i18n. The mode banner is present on every page: the public
simulation mode never claims to be a licensed framework runtime.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import quote

from framework_port import constants as C
from framework_port import errors as FE
from framework_port.dtos import Principal, Record, RecordRef

from . import agents, i18n, policy


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


@dataclass
class Ctx:
    backend: Any
    actor: Principal
    lang: str
    mode: str
    params: dict[str, str] = field(default_factory=dict)
    current_path: str = ""

    def t(self, key: str, **kwargs: object) -> str:
        return i18n.t(self.lang, key, **kwargs)

    def redirect(self, location: str) -> tuple[int, str, str]:
        return 303, "", location


def _qs(params: Mapping[str, str]) -> str:
    if not params:
        return ""
    return "?" + "&".join(f"{k}={quote(v)}" for k, v in params.items())


def flash_link(path: str, lang: str, message: str, level: str = "ok") -> str:
    return f"{path}?flash={quote(message)}&level={level}&lang={lang}"


# ------------------------------------------------------------------ chrome
_CSS = """
:root{--ink:#1c2b3a;--mut:#6b7c8f;--line:#dfe7ef;--bg:#f6f9fc;--card:#fff;
--brand:#2d5097;--ok:#15803f;--warn:#a86406;--bad:#bb2f3d;--chip:#eef3f9}
*{box-sizing:border-box}body{margin:0;font:15px/1.55 -apple-system,'PingFang SC',
'Microsoft YaHei',sans-serif;color:var(--ink);background:var(--bg)}
a{color:var(--brand);text-decoration:none}a:hover{text-decoration:underline}
header{background:#10233a;color:#fff;padding:10px 22px;display:flex;gap:18px;align-items:center}
header .brand{font-weight:700;font-size:17px}
header .sub{color:#b9c9dc;font-size:12px}
header .sp{flex:1}
header form{display:inline}
.modebar{background:#fdf3e7;color:#7a5200;border-bottom:1px solid #f0e2c8;
padding:6px 22px;font-size:12.5px;font-weight:600}
.modebar.licensed{background:#e9f2fd;color:#1c4d8f;border-color:#cfe0f4}
nav{background:#fff;border-bottom:1px solid var(--line);padding:0 22px;display:flex;gap:4px;flex-wrap:wrap}
nav a{padding:10px 12px;color:var(--ink);font-size:14px;border-bottom:2px solid transparent}
nav a.on{border-color:var(--brand);color:var(--brand);font-weight:600}
nav .badge{background:var(--bad);color:#fff;border-radius:9px;padding:0 6px;font-size:11px;margin-left:3px}
main{max-width:1180px;margin:18px auto;padding:0 22px}
.flash{padding:9px 14px;border-radius:8px;margin-bottom:14px;font-size:14px}
.flash.ok{background:#e8f5ec;color:var(--ok);border:1px solid #cde8d5}
.flash.err{background:#fbeaea;color:var(--bad);border:1px solid #f2cfcf}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card h3{margin:0 0 8px;font-size:14px;color:var(--mut);font-weight:600}
.card .big{font-size:26px;font-weight:700}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:10px;overflow:hidden}
th{background:var(--chip);text-align:left;font-size:13px;color:var(--mut);padding:8px 12px}
td{padding:8px 12px;border-top:1px solid var(--line);font-size:14px}
tr:hover td{background:#fafcff}
.chip{display:inline-block;border-radius:9px;padding:1px 9px;font-size:12px;background:var(--chip)}
.chip.st-pending_approval,.chip.st_change_pending,.chip.st_shipped{background:#fdf3e7;color:#7a5200}
.chip.st_approved,.chip.st_completed,.chip.st_accepted,.chip.st_confirmed,
.chip.st_reconciled_matched,.chip.st_closed{background:#e8f5ec;color:var(--ok)}
.chip.st_rejected,.chip.st_cancelled,.chip.st_dispatched_unknown{background:#fbeaea;color:var(--bad)}
.chip.p_critical{background:#fbeaea;color:var(--bad)}
.chip.p_warning{background:#fdf3e7;color:#7a5200}
.btn{display:inline-block;background:var(--brand);color:#fff;border:0;border-radius:7px;
padding:6px 13px;font-size:13.5px;cursor:pointer}
.btn.gray{background:#5b6b7c}.btn.green{background:var(--ok)}.btn.red{background:var(--bad)}
.btn.sm{padding:3px 9px;font-size:12.5px}
form.inline{display:inline}
input,select,textarea{border:1px solid var(--line);border-radius:7px;padding:6px 9px;font-size:14px;width:100%}
label{display:block;font-size:12.5px;color:var(--mut);margin:10px 0 4px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}
.detail{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.kv{display:grid;grid-template-columns:160px 1fr;gap:4px 12px;font-size:14px}
.kv .k{color:var(--mut)}
.banner{border-radius:10px;padding:12px 16px;margin:12px 0;font-size:14px;border:1px solid}
.banner.unknown{background:#fdf3e7;border-color:#f0d9ad;color:#7a5200}
.banner.matched{background:#e8f5ec;border-color:#cde8d5;color:var(--ok)}
h1{font-size:20px;margin:4px 0 14px}
h2{font-size:16px;margin:22px 0 8px}
.muted{color:var(--mut);font-size:12.5px}
.login-wrap{max-width:410px;margin:8vh auto;background:var(--card);border:1px solid var(--line);
border-radius:12px;padding:26px}
.demo-chip{display:inline-block;margin:3px 4px 0 0;background:var(--chip);border:1px solid var(--line);
border-radius:7px;padding:4px 10px;font-size:12.5px;cursor:pointer}
footer{color:var(--mut);text-align:center;font-size:12px;padding:20px 0 30px}
.msg{padding:8px 0;border-bottom:1px dashed var(--line);font-size:14px}
.msg .who{font-weight:600;margin-right:8px}
"""


def _nav_html(ctx: Ctx, active: str) -> str:
    items = []
    unread = 0
    try:
        unread = ctx.backend.unread_count(ctx.actor)
    except FE.FacadeError:
        unread = 0
    for route, key in policy.nav_for(ctx.actor.role):
        badge = ""
        if route == "/notifications" and unread:
            badge = f'<span class="badge">{unread}</span>'
        cls = ' class="on"' if route == active else ""
        items.append(f'<a href="{route}?lang={ctx.lang}"{cls}>{ctx.t(key)}{badge}</a>')
    return "".join(items)


def layout(ctx: Ctx, title: str, active: str, content: str) -> str:
    licensed = ctx.mode == C.MODE_LICENSED_FRAMEWORK
    mode_cls = "modebar licensed" if licensed else "modebar"
    mode_text = ctx.t("mode_licensed") if licensed else ctx.t("mode_public")
    lang_q = "zh" if ctx.lang == i18n.EN else "en"
    next_path = ctx.current_path or "/dashboard"
    is_guest = ctx.actor.actor_id == "guest"
    user_area = (
        f'<span style="font-size:13px">{ctx.t("welcome")}，{esc(ctx.actor.display_name)}</span>'
        f'<form method="post" action="/set-lang">'
        f'<input type="hidden" name="lang" value="{lang_q}">'
        f'<input type="hidden" name="next" value="{esc(next_path)}">'
        f'<button class="btn gray sm" type="submit">{ctx.t("lang_switch")}</button></form>'
        f'<form method="post" action="/logout"><button class="btn sm" type="submit">'
        f'{ctx.t("logout")}</button></form>'
    ) if not is_guest else (
        f'<a href="/login?lang={ctx.lang}" style="color:#cfe0f4;font-size:13px">'
        f'{ctx.t("login")}</a>'
    )
    flash = ""
    msg = ctx.params.get("flash", "")
    if msg:
        level = "ok" if ctx.params.get("level", "ok") == "ok" else "err"
        flash = f'<div class="flash {level}">{esc(msg)}</div>'
    nav_html = "" if is_guest else _nav_html(ctx, active)
    return f"""<!DOCTYPE html>
<html lang="{ctx.lang}"><head><meta charset="utf-8">
<title>{esc(title)} · {ctx.t('app_name')}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{_CSS}</style></head><body>
<header>
  <span class="brand">{ctx.t('app_name')}</span>
  <span class="sub">{ctx.t('app_subtitle')}</span>
  <span class="sp"></span>
  {user_area}
</header>
<div class="{mode_cls}">{mode_text}</div>
<nav>{nav_html}</nav>
<main>{flash}{content}</main>
<footer>{ctx.t('app_name')} · {ctx.t('app_subtitle')} · 合成演示数据 Synthetic demo data only</footer>
</body></html>"""


def state_chip(ctx: Ctx, state: str) -> str:
    return f'<span class="chip st-{esc(state)}">{i18n.state_label(ctx.lang, state)}</span>'


def error_page(ctx: Ctx, err: Exception) -> tuple[int, str]:
    """Business-friendly error rendering: never leak raw framework-style
    messages as the primary text; keep the raw detail as a muted note."""

    raw = str(err)
    if isinstance(err, FE.AuthorizationDenied):
        title = ctx.t("forbidden")
        primary = ctx.t("no_permission_generic")
    elif isinstance(err, FE.ValidationFailed) and "not allowed while the record is" in raw:
        title = ctx.t("error")
        primary = ctx.t("state_not_allowed")
    elif isinstance(err, FE.ValidationFailed):
        title = ctx.t("error")
        primary = raw  # inventory wording is already business Chinese
    elif isinstance(err, FE.RetryRefused):
        title = ctx.t("error")
        primary = ctx.t("retry_refused")
    else:
        title = ctx.t("error")
        primary = ctx.t("error")
    content = (
        f'<div class="flash err"><b>{esc(title)}</b>　{esc(primary)}</div>'
        f'<p class="muted">{ctx.t("denied_detail")}：{esc(raw)}</p>'
        f'<p><a href="/dashboard?lang={ctx.lang}">{ctx.t("back")}</a></p>'
    )
    return 200, layout(ctx, title, "", content)


def _table(ctx: Ctx, headers: list[str], rows: list[str]) -> str:
    if not rows:
        return f"<p class='muted'>{ctx.t('no_records')}</p>"
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join(f"<tr>{''.join(f'<td>{c}</td>' for c in row)}</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _kv(ctx: Ctx, pairs: list[tuple[str, str]]) -> str:
    rows = "".join(f'<span class="k">{esc(k)}</span><span>{v}</span>' for k, v in pairs)
    return f'<div class="kv">{rows}</div>'


# ------------------------------------------------------------------- login
def page_login(ctx: Ctx, error: str = "") -> str:
    lang_q = "zh" if ctx.lang == i18n.EN else "en"
    accounts = [
        ("owner", "林文昊 · 老板"), ("factory", "王强 · 厂长"), ("sales", "李婷 · 销售"),
        ("sales2", "Chen Xiao · Sales"), ("warehouse", "张伟 · 仓库"), ("admin", "系统管理员"),
    ]
    chips = "".join(
        f'<span class="demo-chip" onclick="fill(\'{u}\')">{esc(label)}</span>'
        for u, label in accounts
    )
    err = f'<div class="flash err">{esc(ctx.t("login_failed"))}</div>' if error else ""
    content = f"""
<div class="login-wrap">
  <h1 style="margin-top:0">{ctx.t('app_name')}</h1>
  <p class="muted">{ctx.t('app_subtitle')} · {ctx.t('mode_public')}</p>
  {err}
  <form method="post" action="/login">
    <label>{ctx.t('username')}</label><input id="u" name="username" required>
    <label>{ctx.t('password')}</label><input id="p" name="credential" type="password" value="demo1234" required>
    <p><button class="btn" type="submit">{ctx.t('login')}</button></p>
  </form>
  <p style="margin-bottom:4px"><b>{ctx.t('demo_accounts')}</b></p>
  {chips}
  <p class="muted" style="margin-top:14px">密码统一 demo1234 · Password: demo1234 ·
     <a href="/login?lang={lang_q}">{ctx.t('lang_switch')}</a></p>
</div>
<script>function fill(u){{document.getElementById('u').value=u;
document.getElementById('p').value='demo1234';}}</script>"""
    return layout(ctx, ctx.t("login_title"), "", content)


# --------------------------------------------------------------- dashboard
def page_dashboard(ctx: Ctx) -> str:
    b, actor = ctx.backend, ctx.actor
    role = actor.role
    cards: list[str] = []
    role_name = {"owner": "老板", "factory": "厂长", "sales": "销售",
                 "warehouse": "仓库", "admin": "管理员"}.get(role, role)
    digest = agents.daily_digest(b, actor, ctx.lang)
    cards.append(
        f'<div class="card"><h3>{ctx.t("card_digest")} · {role_name}</h3>'
        f'<p>{esc(digest)}</p></div>'
    )
    if role in (C.ROLE_OWNER, C.ROLE_FACTORY):
        pending = b.list_approvals(actor, pending_for_me=True)
        cards.append(
            f'<div class="card"><h3>{ctx.t("card_pending_approvals")}</h3>'
            f'<div class="big">{len(pending)}</div>'
            f'<p><a href="/approvals?lang={ctx.lang}">{ctx.t("nav_approvals")} →</a></p></div>'
        )
    if role in (C.ROLE_OWNER, C.ROLE_FACTORY):
        pos = b.list_records(actor, C.RECORD_PRODUCTION_ORDER)
        overdue = [p for p in pos if _is_overdue(p) and
                   p.fields.get("state") in ("planned", "released", "in_production")]
        rows = [
            f"<a href='/production/{esc(p.ref.record_id)}?lang={ctx.lang}'>"
            f"{esc(p.ref.record_id)}</a> {state_chip(ctx, str(p.fields.get('state')))}"
            for p in overdue[:5]
        ]
        cards.append(
            f'<div class="card"><h3>{ctx.t("card_overdue_production")}</h3>'
            f'<div class="big">{len(overdue)}</div><p>{"<br>".join(rows)}</p></div>'
        )
    if role in (C.ROLE_OWNER, C.ROLE_FACTORY, C.ROLE_WAREHOUSE):
        items = b.list_records(actor, C.RECORD_INVENTORY_ITEM)
        low = [i for i in items
               if _num(i.fields.get("qty_on_hand")) < _num(i.fields.get("reorder_point"))]
        rows = [
            f"{esc(i18n.pick(ctx.lang, i.fields, 'name'))} "
            f"({_num(i.fields.get('qty_on_hand')):g}/{_num(i.fields.get('reorder_point')):g})"
            for i in low[:5]
        ]
        cards.append(
            f'<div class="card"><h3>{ctx.t("card_low_stock")}</h3>'
            f'<div class="big">{len(low)}</div><p>{"<br>".join(rows)}</p>'
            f'<p><a href="/inventory?lang={ctx.lang}">{ctx.t("nav_inventory")} →</a></p></div>'
        )
    if role == C.ROLE_SALES:
        quotes = b.list_records(actor, C.RECORD_QUOTATION)
        mine = [q for q in quotes if q.fields.get("state") in ("draft", "pending_approval")]
        cards.append(
            f'<div class="card"><h3>{ctx.t("nav_quotations")}</h3>'
            f'<div class="big">{len(mine)}</div>'
            f'<p><a class="btn" href="/quotations/new?lang={ctx.lang}">'
            f'{ctx.t("new_quotation")}</a></p></div>'
        )
    tasks = b.list_tasks(actor, assignee=actor.actor_id, status=C.TASK_STATUS_OPEN)
    cards.append(
        f'<div class="card"><h3>{ctx.t("card_open_tasks")}</h3>'
        f'<div class="big">{len(tasks)}</div>'
        f'<p><a href="/tasks?lang={ctx.lang}">{ctx.t("nav_tasks")} →</a></p></div>'
    )
    content = f"<h1>{ctx.t('nav_dashboard')}</h1><div class='cards'>{''.join(cards)}</div>"
    if role in (C.ROLE_SALES, C.ROLE_OWNER, C.ROLE_FACTORY):
        content += (
            f"<h2>{ctx.t('assistant_title')}</h2>"
            f"<p><a class='btn gray' href='/assistant?lang={ctx.lang}'>"
            f"{ctx.t('assistant_title')} →</a></p>"
        )
    return 200, layout(ctx, ctx.t("nav_dashboard"), "/dashboard", content)


def _num(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _is_overdue(po: Record) -> bool:
    import datetime as _dt
    due = str(po.fields.get("due_date", ""))
    if not due:
        return False
    try:
        return _dt.date.fromisoformat(due[:10]) <= _dt.date.today()
    except ValueError:
        return False


# --------------------------------------------------------------- customers
def page_customers(ctx: Ctx) -> str | tuple[int, str, str]:
    rows = []
    for c in ctx.backend.list_records(ctx.actor, C.RECORD_CUSTOMER):
        rows.append([
            esc(c.ref.record_id),
            esc(i18n.pick(ctx.lang, c.fields, "name")),
            esc(str(c.fields.get("contact", ""))),
            esc(str(c.fields.get("city", ""))),
        ])
    new_form = ""
    if ctx.actor.role == C.ROLE_SALES:
        new_form = f"""
<h2>{ctx.t('create')}</h2>
<form method="post" action="/customers/new" class="detail">
  <div class="grid2">
    <div><label>{ctx.t('f_name')} (中文)</label><input name="name_cn" required></div>
    <div><label>{ctx.t('f_name')} (EN)</label><input name="name_en"></div>
    <div><label>{ctx.t('f_contact')}</label><input name="contact"></div>
    <div><label>{ctx.t('f_city')}</label><input name="city"></div>
  </div>
  <p><button class="btn" type="submit">{ctx.t('save')}</button></p>
</form>"""
    content = f"""
<h1>{ctx.t('nav_customers')}</h1>
{_table(ctx, ["ID", ctx.t("f_name"), ctx.t("f_contact"), ctx.t("f_city")], rows)}
{new_form}"""
    return 200, layout(ctx, ctx.t("nav_customers"), "/customers", content)


# -------------------------------------------------------------- quotations
def page_quotations(ctx: Ctx) -> str:
    rows = []
    for q in ctx.backend.list_records(ctx.actor, C.RECORD_QUOTATION):
        rows.append([
            f"<a href='/quotations/{esc(q.ref.record_id)}?lang={ctx.lang}'>"
            f"{esc(q.ref.record_id)}</a>",
            esc(i18n.pick(ctx.lang, q.fields, "customer_name")),
            esc(i18n.pick(ctx.lang, q.fields, "product_name")),
            f"{_num(q.fields.get('qty')):g}",
            f"{_num(q.fields.get('discount_pct')):g}%",
            f"¥{_num(q.fields.get('total_amount')):g}",
            state_chip(ctx, str(q.fields.get("state"))),
        ])
    content = f"""
<h1>{ctx.t('nav_quotations')}
  <a class="btn" style="float:right" href="/quotations/new?lang={ctx.lang}">{ctx.t('new_quotation')}</a></h1>
{_table(ctx, ["ID", ctx.t("f_customer"), ctx.t("f_product"), ctx.t("qty"),
              ctx.t("f_discount_pct"), ctx.t("total"), ctx.t("state")], rows)}"""
    return 200, layout(ctx, ctx.t("nav_quotations"), "/quotations", content)


def page_quotation_new(ctx: Ctx, draft: dict[str, Any] | None = None) -> str:
    products = ctx.backend.list_records(ctx.actor, C.RECORD_PRODUCT)
    options = "".join(
        f"<option value='{esc(p.ref.record_id)}'>"
        f"{esc(i18n.pick(ctx.lang, p.fields, 'name'))}</option>"
        for p in products
    )
    customers = ctx.backend.list_records(ctx.actor, C.RECORD_CUSTOMER)
    cust_options = "".join(
        f"<option value='{esc(c.fields.get('name_cn', ''))}'>"
        f"{esc(i18n.pick(ctx.lang, c.fields, 'name'))}</option>"
        for c in customers
    )
    d = draft or {}
    rationale = ""
    if d:
        rationale = f"<div class='banner matched'><b>{ctx.t('recommendation')}</b>：{esc(d.get('rationale',''))}</div>"
    content = f"""
<h1>{ctx.t('new_quotation')}</h1>
<div class="detail">{rationale}
<form method="post" action="/quotations/draft">
  <div class="grid2">
    <div><label>{ctx.t('f_customer')}</label>
      <select name="customer_name">{cust_options}</select></div>
    <div><label>{ctx.t('f_product')}</label>
      <select name="product_id">{options}</select></div>
    <div><label>{ctx.t('qty')}</label>
      <input name="qty" type="number" step="1" min="1" value="{esc(i18n.fmt_num(d.get('qty', 1000)))}"></div>
    <div><label>{ctx.t('f_discount_pct')}</label>
      <input name="discount_pct" type="number" step="0.5" min="0" max="30"
             value="{esc(i18n.fmt_num(d.get('discount_pct', 0)))}"></div>
    <div><label>{ctx.t('due_date')}</label>
      <input name="requested_date" type="date" value="{esc(d.get('requested_date', ''))}"></div>
  </div>
  <p><button class="btn gray" type="submit">{ctx.t('act_ai_draft')}</button></p>
</form>
<form method="post" action="/quotations">
  <input type="hidden" name="customer_name" value="{esc(d.get('customer_name', ''))}">
  <input type="hidden" name="product_id" value="{esc(d.get('product_id', ''))}">
  <input type="hidden" name="product_name" value="{esc(d.get('product_name', ''))}">
  <input type="hidden" name="qty" value="{esc(d.get('qty', ''))}">
  <input type="hidden" name="discount_pct" value="{esc(d.get('discount_pct', 0))}">
  <input type="hidden" name="unit_price" value="{esc(d.get('unit_price', ''))}">
  <input type="hidden" name="list_price" value="{esc(d.get('list_price', ''))}">
  <input type="hidden" name="total_amount" value="{esc(d.get('total_amount', ''))}">
  <input type="hidden" name="requested_date" value="{esc(d.get('requested_date', ''))}">
  <input type="hidden" name="rationale" value="{esc(d.get('rationale', ''))}">
  <label>{ctx.t('justification')}</label>
  <input name="justification" value="">
  <p><button class="btn" type="submit">{ctx.t('save')}（{ctx.t('st_draft')}）</button></p>
</form></div>"""
    return 200, layout(ctx, ctx.t("new_quotation"), "/quotations", content)


def page_quotation_detail(ctx: Ctx, qid: str) -> str:
    q = ctx.backend.get_record(ctx.actor, RecordRef(C.RECORD_QUOTATION, qid))
    if q is None:
        raise FE.NotFound(f"quotation '{qid}' not found")
    state = str(q.fields.get("state"))
    acts: list[str] = []
    if state == "draft":
        acts.append(_action_form(
            f"/quotations/{qid}/submit", ctx.t("act_submit_quote",
            pct=_num(q.fields.get("discount_pct"))),
            justification=True, lang=ctx.lang))
    if state == "approved":
        acts.append(_action_form(f"/quotations/{qid}/accept", ctx.t("act_accept_quote"),
                                 lang=ctx.lang))
    timeline_link = (f"<a href='/audit/quotation/{esc(qid)}?lang={ctx.lang}'>"
                     f"{ctx.t('nav_audit')} →</a>")
    pairs = [
        ("ID", esc(qid)), (ctx.t("f_customer"), esc(i18n.pick(ctx.lang, q.fields, "customer_name"))),
        (ctx.t("f_product"), esc(i18n.pick(ctx.lang, q.fields, "product_name"))),
        (ctx.t("qty"), i18n.fmt_num(q.fields.get("qty"))),
        (ctx.t("f_list_price"), f"¥{i18n.fmt_num(q.fields.get('list_price'))}"),
        (ctx.t("f_discount_pct"), f"{i18n.fmt_num(q.fields.get('discount_pct'))}%"),
        (ctx.t("f_unit_price"), f"¥{i18n.fmt_num(q.fields.get('unit_price'))}"),
        (ctx.t("total"), f"¥{i18n.fmt_num(q.fields.get('total_amount'))}"),
        (ctx.t("due_date"), esc(str(q.fields.get("requested_date", "")))),
        (ctx.t("state"), state_chip(ctx, state)),
        (ctx.t("nav_audit"), timeline_link),
    ]
    content = f"<h1>{ctx.t('rec_quotation')} {esc(qid)}</h1><div class='detail'>{_kv(ctx, pairs)}</div>" \
              f"<h2>{ctx.t('actions')}</h2>{''.join(acts) or f'<p class=muted>{ctx.t("none")}</p>'}"
    return 200, layout(ctx, f"{ctx.t('rec_quotation')} {qid}", "/quotations", content)


def _action_form(action_url: str, label: str, *, justification: bool = False,
                 lang: str = "zh", hidden: str = "", button_cls: str = "btn") -> str:
    just = ""
    if justification:
        just = (f"<label>{i18n.t(lang, 'justification')}</label>"
                f"<input name='justification' required>")
    return (f"<form method='post' action='{action_url}?lang={lang}' class='inline'>{hidden}"
            f"{just}<button class='{button_cls}' type='submit'>{esc(label)}</button></form>")


# ------------------------------------------------------------------- orders
def page_orders(ctx: Ctx) -> str:
    rows = []
    for o in ctx.backend.list_records(ctx.actor, C.RECORD_SALES_ORDER):
        rows.append([
            f"<a href='/orders/{esc(o.ref.record_id)}?lang={ctx.lang}'>{esc(o.ref.record_id)}</a>",
            esc(i18n.pick(ctx.lang, o.fields, "customer_name")),
            esc(i18n.pick(ctx.lang, o.fields, "product_name")),
            f"{_num(o.fields.get('qty')):g}",
            f"¥{_num(o.fields.get('total_amount')):g}",
            state_chip(ctx, str(o.fields.get("state"))),
        ])
    content = f"<h1>{ctx.t('nav_orders')}</h1>" + _table(
        ctx, ["ID", ctx.t("f_customer"), ctx.t("f_product"), ctx.t("qty"),
              ctx.t("total"), ctx.t("state")], rows)
    return 200, layout(ctx, ctx.t("nav_orders"), "/orders", content)


def page_order_detail(ctx: Ctx, oid: str) -> str:
    b, lang = ctx.backend, ctx.lang
    o = b.get_record(ctx.actor, RecordRef(C.RECORD_SALES_ORDER, oid))
    if o is None:
        raise FE.NotFound(f"order '{oid}' not found")
    state = str(o.fields.get("state"))
    acts: list[str] = []
    if state == "draft":
        acts.append(_action_form(f"/orders/{oid}/confirm", ctx.t("act_confirm_order"),
                                 justification=True, lang=lang))
    if state == "confirmed":
        acts.append(_action_form(f"/orders/{oid}/change", ctx.t("act_request_change"),
                                 justification=True, lang=lang,
                                 hidden=("<label>新交期 New date</label>"
                                         "<input name='new_date' type='date'>"
                                         "<label>价格变更 Price change?</label>"
                                         "<select name='price_change'>"
                                         "<option value='false'>否 No</option>"
                                         "<option value='true'>是 Yes</option></select>")))
        acts.append(_action_form(f"/orders/{oid}/create-po", ctx.t("act_create_po"),
                                 lang=lang,
                                 hidden=(f"<input type='hidden' name='product_id' "
                                         f"value='{esc(str(o.fields.get('product_id')))}'>"
                                         f"<input type='hidden' name='product_name' "
                                         f"value='{esc(str(o.fields.get('product_name')))}'>"
                                         f"<input type='hidden' name='qty' "
                                         f"value='{_num(o.fields.get('qty')):g}'>"
                                         "<label>交期 Due</label><input name='due_date' type='date'>"
                                         "<label>加急 Expedite?</label>"
                                         "<select name='expedite'><option value='false'>否</option>"
                                         "<option value='true'>是</option></select>")))
        acts.append(f"<form method='post' action='/orders/{oid}/ai-atp?lang={lang}' class='inline'>"
                    f"<button class='btn gray' type='submit'>{ctx.t('act_ai_atp')}</button></form>")
    if state == "ready_to_ship":
        acts.append(_action_form(f"/orders/{oid}/ship", ctx.t("act_request_shipment"),
                                 lang=lang, hidden="<label>地址 Address</label>"
                                                  "<input name='address' value='客户默认地址'>"))
    ship_section = ""
    shipments = b.list_records(ctx.actor, C.RECORD_SHIPMENT, filters={"order_id": oid})
    if shipments:
        ship = shipments[0]
        sid = ship.ref.record_id
        sstate = str(ship.fields.get("state"))
        ship_actions = ""
        if sstate in ("requested",):
            ship_actions = _action_form(f"/shipments/{sid}/dispatch", ctx.t("act_dispatch"),
                                        lang=lang, button_cls="btn")
        gov_view = _latest_governed(b, ctx.actor, sid)
        if gov_view is not None and gov_view.state == "unknown" and sstate != "reconciled_matched":
            ship_actions += " " + _action_form(f"/shipments/{sid}/reconcile",
                                               ctx.t("act_reconcile"), lang=lang,
                                               button_cls="btn green")
        banner = ""
        if gov_view is not None:
            if gov_view.attempt_outcome == "unknown" and sstate != "reconciled_matched":
                banner = (f"<div class='banner unknown'><b>{ctx.t('truth_command')}</b>："
                          f"{ctx.t('truth_unknown')}　|　<b>{ctx.t('truth_external')}</b>："
                          f"{ctx.t('truth_unobservable')}</div>"
                          f"<p class='muted'>{ctx.t('governed_note')}</p>")
            if sstate == "reconciled_matched":
                banner = (f"<div class='banner matched'><b>{ctx.t('truth_command')}</b>："
                          f"{ctx.t('truth_unknown_kept')}　|　"
                          f"<b>{ctx.t('truth_external')}</b>：{ctx.t('truth_matched')}</div>"
                          f"<p class='muted'>{ctx.t('governed_note')}</p>")
        ship_section = (f"<h2>{ctx.t('rec_shipment')} {esc(sid)}</h2>"
                        f"{state_chip(ctx, sstate)} {banner}"
                        f"<p>{ship_actions}</p>")
    pairs = [
        ("ID", esc(oid)),
        (ctx.t("f_customer"), esc(i18n.pick(ctx.lang, o.fields, "customer_name"))),
        (ctx.t("f_product"), esc(i18n.pick(ctx.lang, o.fields, "product_name"))),
        (ctx.t("qty"), i18n.fmt_num(o.fields.get("qty"))),
        (ctx.t("total"), f"¥{i18n.fmt_num(o.fields.get('total_amount'))}"),
        (ctx.t("due_date"), esc(str(o.fields.get("requested_date", "")))),
        (ctx.t("state"), state_chip(ctx, state)),
        (ctx.t("nav_audit"),
         f"<a href='/audit/sales_order/{esc(oid)}?lang={lang}'>{ctx.t('nav_audit')} →</a>"),
    ]
    pos = b.list_records(ctx.actor, C.RECORD_PRODUCTION_ORDER, filters={"order_id": oid})
    po_rows = [
        f"<a href='/production/{esc(p.ref.record_id)}?lang={lang}'>{esc(p.ref.record_id)}</a> "
        + str(state_chip(ctx, str(p.fields.get("state"))))
        for p in pos
    ]
    content = (f"<h1>{ctx.t('rec_sales_order')} {esc(oid)}</h1>"
               f"<div class='detail'>{_kv(ctx, pairs)}</div>"
               f"<h2>{ctx.t('production_orders')}</h2>"
               f"<p>{'<br>'.join(po_rows) if po_rows else ctx.t('none')}</p>"
               f"<h2>{ctx.t('actions')}</h2>{''.join(acts) or f'<p class=muted>{ctx.t("none")}</p>'}"
               f"{ship_section}")
    return 200, layout(ctx, f"{ctx.t('rec_sales_order')} {oid}", "/orders", content)


def _latest_governed(b, actor: Principal, shipment_id: str):
    # The demo app finds the governed action via the audit trail of the shipment.
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


# -------------------------------------------------------------- production
def page_production(ctx: Ctx) -> str:
    rows = []
    for p in ctx.backend.list_records(ctx.actor, C.RECORD_PRODUCTION_ORDER):
        overdue = "⚠ " + ctx.t("f_overdue") if (
            _is_overdue(p) and p.fields.get("state") in
            ("planned", "released", "in_production")) else ""
        rows.append([
            f"<a href='/production/{esc(p.ref.record_id)}?lang={ctx.lang}'>"
            f"{esc(p.ref.record_id)}</a>",
            esc(str(p.fields.get("order_id", ""))),
            esc(i18n.pick(ctx.lang, p.fields, "product_name")),
            f"{_num(p.fields.get('qty')):g}",
            esc(str(p.fields.get("due_date", ""))) + " " + overdue,
            f"{_num(p.fields.get('progress_pct')):g}%",
            state_chip(ctx, str(p.fields.get("state"))),
        ])
    content = f"<h1>{ctx.t('nav_production')}</h1>" + _table(
        ctx, ["ID", ctx.t("nav_orders"), ctx.t("f_product"), ctx.t("qty"),
              ctx.t("due_date"), ctx.t("f_progress"), ctx.t("state")], rows)
    return 200, layout(ctx, ctx.t("nav_production"), "/production", content)


def page_production_detail(ctx: Ctx, pid: str) -> str:
    b, lang = ctx.backend, ctx.lang
    p = b.get_record(ctx.actor, RecordRef(C.RECORD_PRODUCTION_ORDER, pid))
    if p is None:
        raise FE.NotFound(f"production order '{pid}' not found")
    state = str(p.fields.get("state"))
    role = ctx.actor.role
    acts: list[str] = []
    if state == "planned" and role == C.ROLE_FACTORY:
        acts.append(_action_form(f"/production/{pid}/release", ctx.t("act_release"), lang=lang))
    if state == "released" and role == C.ROLE_WAREHOUSE:
        acts.append(_action_form(f"/production/{pid}/issue", ctx.t("act_issue"),
                                 lang=lang) +
                    f" <span class='muted'>({ctx.t('by_warehouse')})</span>")
    if state == "in_production" and role == C.ROLE_FACTORY:
        acts.append(_action_form(f"/production/{pid}/progress", ctx.t("act_progress"),
                                 lang=lang, hidden="<label>" + ctx.t("f_progress") +
                                                   "</label><input name='progress_pct' "
                                                   "type='number' min='0' max='100' value='90'>"))
        acts.append(_action_form(f"/production/{pid}/complete", ctx.t("act_complete"),
                                 lang=lang, button_cls="btn green"))
        if _is_overdue(p):
            acts.append(_action_form(f"/production/{pid}/reschedule", ctx.t("act_ai_reschedule"),
                                     lang=lang, button_cls="btn gray"))
    hint = ""
    if not acts and state in ("released", "in_production"):
        hint = (f"<p class='muted'>"
                f"{ctx.t('act_issue') if state == 'released' else ctx.t('act_progress')}："
                f"{ctx.t('by_warehouse') if state == 'released' else ctx.t('by_factory')}"
                f"</p>")
    reqs = b.list_records(ctx.actor, C.RECORD_MATERIAL_REQUIREMENT,
                          filters={"production_id": pid})
    req_rows = [
        f"{esc(str(r.fields.get('material_name', r.fields.get('material_id'))))} × "
        f"{_num(r.fields.get('required_qty')):g}　"
        f"<span class='chip'>{i18n.state_label(lang, str(r.fields.get('state','open')))}</span>"
        for r in reqs
    ]
    pairs = [
        ("ID", esc(pid)),
        (ctx.t("nav_orders"),
         f"<a href='/orders/{esc(str(p.fields.get('order_id')))}?lang={lang}'>"
         f"{esc(str(p.fields.get('order_id')))}</a>"),
        (ctx.t("f_product"), esc(i18n.pick(ctx.lang, p.fields, "product_name"))),
        (ctx.t("qty"), f"{_num(p.fields.get('qty')):g}"),
        (ctx.t("due_date"), esc(str(p.fields.get("due_date", "")))),
        (ctx.t("f_progress"), f"{_num(p.fields.get('progress_pct')):g}%"),
        (ctx.t("state"), state_chip(ctx, state)),
        (ctx.t("requirements"), "<br>".join(req_rows) or ctx.t("none")),
        (ctx.t("nav_audit"),
         f"<a href='/audit/production_order/{esc(pid)}?lang={lang}'>{ctx.t('nav_audit')} →</a>"),
    ]
    content = (f"<h1>{ctx.t('rec_production_order')} {esc(pid)}</h1>"
               f"<div class='detail'>{_kv(ctx, pairs)}</div>"
               f"<h2>{ctx.t('actions')}</h2>{''.join(acts) or hint or f'<p class=muted>{ctx.t("none")}</p>'}")
    return 200, layout(ctx, f"{ctx.t('rec_production_order')} {pid}", "/production", content)


# --------------------------------------------------------------- inventory
def page_inventory(ctx: Ctx) -> str:
    rows = []
    for it in ctx.backend.list_records(ctx.actor, C.RECORD_INVENTORY_ITEM):
        qty, reorder = _num(it.fields.get("qty_on_hand")), _num(it.fields.get("reorder_point"))
        mark = " ⚠" if qty < reorder else ""
        adjust = ""
        if ctx.actor.role == C.ROLE_WAREHOUSE:
            adjust = (
                f"<form method='post' action='/inventory/{esc(it.ref.record_id)}/adjust'"
                f" class='inline'><input name='adjust_qty' type='number' step='1' value='0'"
                f" style='width:80px'><input type='hidden' name='adjust_amount' value='0'>"
                f"<input type='hidden' name='adjust_pct' value='0'>"
                f"<button class='btn gray sm' type='submit'>{ctx.t('act_adjust')}</button></form>"
                f" <form method='post' action='/inventory/{esc(it.ref.record_id)}/receipt'"
                f" class='inline'><input name='qty' type='number' step='1' value='10'"
                f" style='width:80px'><button class='btn sm' type='submit'>"
                f"{ctx.t('act_receipt')}</button></form>"
            )
        rows.append([
            esc(it.ref.record_id),
            esc(i18n.pick(ctx.lang, it.fields, "name")),
            f"{qty:g} {esc(str(it.fields.get('unit', '')))}",
            f"{reorder:g}{mark}",
            adjust,
        ])
    content = f"<h1>{ctx.t('nav_inventory')}</h1>" + _table(
        ctx, ["ID", ctx.t("f_name"), ctx.t("f_qty_on_hand"), ctx.t("f_reorder_point"),
              ctx.t("actions")], rows)
    return 200, layout(ctx, ctx.t("nav_inventory"), "/inventory", content)


# ------------------------------------------------------------------- tasks
def page_tasks(ctx: Ctx) -> str:
    users = ctx.backend.list_users(ctx.actor) if ctx.actor.role == C.ROLE_ADMIN else []
    rows = []
    for task in ctx.backend.list_tasks(ctx.actor, status=C.TASK_STATUS_OPEN):
        handoff = ""
        if task.assignee == ctx.actor.actor_id and ctx.actor.role != C.ROLE_ADMIN:
            candidates = {"sales": "sales2", "sales2": "sales"}.get(
                ctx.actor.actor_id, "owner" if ctx.actor.role == C.ROLE_FACTORY else "factory")
            handoff = (f"<form method='post' action='/tasks/{esc(task.task_id)}/handoff'"
                       f" class='inline'><input type='hidden' name='to_actor' value='{candidates}'>"
                       f"<input name='reason' placeholder='{esc(ctx.t('reason'))}'"
                       f" style='width:130px'>"
                       f"<button class='btn gray sm' type='submit'>{ctx.t('handoff')}</button>"
                       f"</form>")
        rows.append([
            esc(task.task_id),
            esc(task.title),
            esc(task.assignee),
            esc(str(task.due_at or "")),
            state_chip(ctx, task.status),
            _action_form(f"/tasks/{task.task_id}/complete", ctx.t("complete"), lang=ctx.lang,
                         button_cls="btn green sm") + " " + handoff,
        ])
    content = f"<h1>{ctx.t('nav_tasks')}</h1>" + _table(
        ctx, ["ID", ctx.t("f_name"), ctx.t("assignee"), ctx.t("due_date"), ctx.t("state"),
              ctx.t("actions")], rows)
    return 200, layout(ctx, ctx.t("nav_tasks"), "/tasks", content)


# --------------------------------------------------------------- approvals
def page_approvals(ctx: Ctx) -> str:
    rows = []
    for a in ctx.backend.list_approvals(ctx.actor, pending_for_me=True):
        decide = ""
        if a.status == "pending":
            decide = (
                _action_form(f"/approvals/{a.approval_id}/approve", ctx.t("approve"),
                             lang=ctx.lang, button_cls="btn green sm",
                             hidden="<input name='comment' placeholder='"
                                    + esc(ctx.t("comment")) + "' style='width:140px'>")
                + " " + _action_form(f"/approvals/{a.approval_id}/reject", ctx.t("reject"),
                                     lang=ctx.lang, button_cls="btn red sm")
            )
        kind = i18n.kind_label(ctx.lang, a.kind)
        target_text = f"{i18n.rec_label(ctx.lang, a.target.record_type)} {a.target.record_id}"
        rows.append([
            f"<a href='/audit/approval/{esc(a.approval_id)}?lang={ctx.lang}'>"
            f"{esc(a.approval_id)}</a>",
            esc(kind),
            esc(target_text),
            esc(a.requested_by),
            esc(str(a.justification or ""))[:120],
            state_chip(ctx, a.status),
            decide,
        ])
    content = f"<h1>{ctx.t('nav_approvals')}</h1>" + _table(
        ctx, ["ID", ctx.t("h_kind"), ctx.t("h_item"), ctx.t("requested_by"),
              ctx.t("justification"), ctx.t("state"), ctx.t("actions")], rows)
    content += (f"<p class='muted'>{ctx.t('audit_note')}</p>")
    return 200, layout(ctx, ctx.t("nav_approvals"), "/approvals", content)


# ----------------------------------------------------------- notifications
def page_notifications(ctx: Ctx) -> str:
    rows = []
    for n in ctx.backend.list_notifications(ctx.actor):
        mark = ""
        if n.read_state == "unread":
            mark = _action_form(f"/notifications/{n.notification_id}/read",
                                ctx.t("mark_read"), lang=ctx.lang, button_cls="btn gray sm")
        link = ""
        if n.related is not None and n.related.record_id:
            base = {"sales_order": "/orders", "production_order": "/production",
                    "quotation": "/quotations", "shipment": "/shipments",
                    "task": "/tasks"}.get(n.related.record_type, "")
            if base and n.related.record_type != "task":
                link = f"<a href='{base}/{esc(n.related.record_id)}?lang={ctx.lang}'>→</a>"
        rows.append([
            f"<span class='chip p_{esc(n.priority)}'>{i18n.priority_label(ctx.lang, n.priority)}"
            f"</span>",
            esc(n.title),
            esc(n.body),
            esc(i18n.fmt_time(n.created_at)),
            ctx.t("read") if n.read_state == "read" else
            f"<b style='color:var(--bad)'>{ctx.t('unread')}</b>",
            mark + " " + link,
        ])
    mails = ctx.backend.list_mail_outbox(ctx.actor)
    mail_rows = [
        f"[{esc(i18n.fmt_time(m['sent_at']))}] {esc(m['recipient'])}：{esc(m['subject'])}"
        for m in mails[:8]
    ]
    content = (f"<h1>{ctx.t('nav_notifications')}</h1>"
               + _table(ctx, ["", ctx.t("f_name"), ctx.t("h_body"), ctx.t("h_time"),
                              ctx.t("state"), ctx.t("actions")], rows)
               + f"<h2>{ctx.t('simulated_mail')}</h2>"
               + ("<p class='muted'>" + "<br>".join(mail_rows) + "</p>"
                  if mail_rows else f"<p class='muted'>{ctx.t('no_records')}</p>"))
    return 200, layout(ctx, ctx.t("nav_notifications"), "/notifications", content)


# ------------------------------------------------------------------- audit
def page_audit(ctx: Ctx) -> str:
    subjects = []
    for rt, _base in ((C.RECORD_SALES_ORDER, "/orders"), (C.RECORD_QUOTATION, "/quotations"),
                      (C.RECORD_PRODUCTION_ORDER, "/production")):
        for rec in ctx.backend.list_records(ctx.actor, rt)[:8]:
            subjects.append((rt, rec.ref.record_id))
    approvals = ctx.backend.list_approvals(ctx.actor, pending_for_me=False)[:8]
    for a in approvals:
        subjects.append(("approval", a.approval_id))
    rows = [
        f"<a href='/audit/{esc(rt)}/{esc(rid)}?lang={ctx.lang}'>"
        f"{esc(i18n.rec_label(ctx.lang, rt))} {esc(rid)}</a>"
        for rt, rid in subjects[:20]
    ]
    content = (f"<h1>{ctx.t('nav_audit')}</h1>"
               f"<p class='muted'>{ctx.t('audit_note')}</p>"
               + "<p>" + "<br>".join(rows) + "</p>")
    return 200, layout(ctx, ctx.t("nav_audit"), "/audit", content)


def page_audit_subject(ctx: Ctx, rtype: str, rid: str) -> str:
    b, lang = ctx.backend, ctx.lang
    subject = RecordRef(rtype, rid)
    entries = b.get_audit_timeline(ctx.actor, subject)
    rows = [[str(e.seq), esc(i18n.fmt_time(e.at)), esc(e.actor_id), esc(e.action),
             esc(e.detail)] for e in entries]
    verify = ""
    if rtype == "approval":
        result = b.verify_evidence_chain(ctx.actor, subject)
        cls = "matched" if result.verified else "unknown"
        label = ctx.t("verified") if result.verified else ctx.t("failed")
        verify = (f"<div class='banner {cls}'><b>{ctx.t('verify_chain')}</b>：{label}"
                  f"　（{result.entries_checked} {ctx.t('entries_scope').split(' · ')[0]}"
                  f" · {ctx.t('entries_scope').split(' · ')[1] if ' · ' in ctx.t('entries_scope') else ''}）</div>")
    recent = [
        (C.RECORD_SALES_ORDER,), (C.RECORD_QUOTATION,), (C.RECORD_PRODUCTION_ORDER,),
    ]
    others = []
    for (rt,) in recent:
        for rec in b.list_records(ctx.actor, rt)[:5]:
            if not (rt == rtype and rec.ref.record_id == rid):
                others.append(f"<a href='/audit/{rt}/{rec.ref.record_id}?lang={lang}'>"
                              f"{esc(i18n.rec_label(lang, rt))} {esc(rec.ref.record_id)}</a>")
    content = (f"<h1>{ctx.t('nav_audit')}：{esc(i18n.rec_label(lang, rtype))} {esc(rid)}</h1>"
               f"{verify}"
               + _table(ctx, [ctx.t("h_seq"), ctx.t("h_time"), ctx.t("h_actor"),
                              ctx.t("h_action"), "Detail"], rows)
               + f"<h2>{ctx.t('other_subjects')}</h2><p>"
               + "<br>".join(others) + "</p>")
    return 200, layout(ctx, ctx.t("nav_audit"), "/audit", content)


# ------------------------------------------------------------------- admin
def page_admin(ctx: Ctx) -> str:
    rows = [
        [esc(u.actor_id), esc(u.display_name), esc(u.role), esc(u.locale)]
        for u in ctx.backend.list_users(ctx.actor)
    ]
    content = (f"<h1>{ctx.t('nav_admin')}</h1>"
               + _table(ctx, [ctx.t("username"), ctx.t("f_name"), ctx.t("admin_roles"),
                              "Locale"], rows)
               + f"<p class='muted'>{ctx.t('admin_note')}</p>")
    return 200, layout(ctx, ctx.t("nav_admin"), "/admin", content)


# --------------------------------------------------------------- assistant
def page_assistant(ctx: Ctx) -> str:
    b = ctx.backend
    conversation_id = _open_conversation(b, ctx.actor)
    messages = b.list_messages(ctx.actor, conversation_id)
    msgs = "".join(
        f"<div class='msg'><span class='who'>"
        f"{'🧑 ' + ctx.t('welcome') if m.role == C.CONVERSATION_ROLE_USER else '🤖 ' + ctx.t('assistant_title')}"
        f"</span>{esc(m.text)}</div>"
        for m in messages
    ) or f"<p class='muted'>{ctx.t('none')}</p>"
    content = (f"<h1>{ctx.t('assistant_title')}</h1>"
               f"<div class='detail'>{msgs}</div>"
               f"<form method='post' action='/assistant' style='margin-top:12px'>"
               f"<input name='text' placeholder='{esc(ctx.t('assistant_placeholder'))}' required>"
               f"<p><button class='btn' type='submit'>{ctx.t('assistant_send')}</button></p></form>"
               f"<p class='muted'>{ctx.t('assistant_limited_note')}</p>")
    return 200, layout(ctx, ctx.t("assistant_title"), "/dashboard", content)


def _open_conversation(b, actor: Principal) -> str:
    opener = getattr(b, "open_conversation", None)
    if opener is not None:
        return str(opener(actor))
    conversation_id = f"conv-{actor.actor_id}"
    b.append_message(actor, conversation_id, C.CONVERSATION_ROLE_ASSISTANT, "…")
    return conversation_id


def assistant_post(ctx: Ctx, text: str) -> tuple[int, str, str]:
    b = ctx.backend
    conversation_id = _open_conversation(b, ctx.actor)
    b.append_message(ctx.actor, conversation_id, C.CONVERSATION_ROLE_USER, text)
    reply = _assistant_reply(ctx, text)
    b.append_message(ctx.actor, conversation_id, C.CONVERSATION_ROLE_ASSISTANT, reply)
    return ctx.redirect(f"/assistant?lang={ctx.lang}")


def _assistant_reply(ctx: Ctx, text: str) -> str:
    b, actor = ctx.backend, ctx.actor
    if any(k in text for k in ("缺料", "库存", "shortage", "stock")):
        orders = b.list_records(actor, C.RECORD_SALES_ORDER,
                                filters={"state": "confirmed"})
        parts = []
        for order in orders[:3]:
            report = agents.atp_check(b, actor, order)
            if not report["ok"]:
                parts.append(f"{order.ref.record_id}：" + report["note"])
        return "；".join(parts) if parts else "当前已确认订单物料齐备。"
    if any(k in text for k in ("摘要", "今天", "digest", "today")):
        return agents.daily_digest(b, actor, ctx.lang)
    if any(k in text for k in ("报价", "quote", "draft")):
        return ("我可以在“新建报价”页为你起草报价：填客户、产品和数量后点“AI 起草报价”，"
                "折扣超过 5% 会自动送审批。")
    return ("我可以：① 汇总今日经营摘要（输入“摘要”）；② 检查订单缺料（输入“缺料”）；"
            "③ 指导报价起草（输入“报价”）。所有业务执行仍由相应角色的人完成。")
