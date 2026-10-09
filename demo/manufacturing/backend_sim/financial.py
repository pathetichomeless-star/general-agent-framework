"""Exact numeric primitives for the public simulator's existing CNY model."""
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext
import math

from framework_port import errors as E

CENT = Decimal("0.01")


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise E.ValidationFailed(f"invalid number: {name}")
    try:
        result = Decimal(str(value))
        if not result.is_finite() or len(result.as_tuple().digits) > 100 or abs(result.adjusted()) > 40:
            raise ValueError()
        return result
    except (DecimalException, ValueError):
        raise E.ValidationFailed(f"invalid finite decimal: {name}") from None


def quantity(value, name="qty", *, signed=False):
    result = number(value, name)
    if not signed and result <= 0:
        raise E.ValidationFailed(f"{name} must be positive")
    json_number(result)  # quantities must round-trip through the existing JSON DTO
    return result


def money(value, name):
    result = number(value, name)
    if result < 0 or result != rounded(result):
        raise E.ValidationFailed(f"{name} must be nonnegative cents")
    json_number(result)
    return result


def rounded(value):
    try:
        with localcontext() as ctx:
            ctx.prec = 100
            if abs(value) % CENT == CENT / 2:
                raise E.ValidationFailed("currency rounding midpoint requires an owner-approved rule")
            return value.quantize(CENT, rounding=ROUND_HALF_UP)
    except DecimalException:
        raise E.ValidationFailed("financial value exceeds supported decimal precision") from None


def json_number(value):
    number(value, "numeric DTO")
    result = float(value)
    if not math.isfinite(result) or Decimal(str(result)) != value:
        raise E.ValidationFailed("number cannot round-trip through the numeric DTO")
    return result


def line_values(fields):
    if not isinstance(fields.get("product_id"), str) or not fields["product_id"]:
        raise E.ValidationFailed("financial content requires a product_id")
    qty = quantity(fields.get("qty"))
    unit = money(fields.get("unit_price"), "unit_price")
    with localcontext() as ctx:
        ctx.prec = 100
        total = rounded(qty * unit)
    json_number(total)
    if "total_amount" in fields and money(fields["total_amount"], "total_amount") != total:
        raise E.ValidationFailed("total_amount disagrees with quantity and selling price")
    currency = fields.get("currency", "CNY")
    if currency != "CNY":
        raise E.ValidationFailed("the demo financial contract supports CNY only")
    return {**fields, "qty": json_number(qty), "unit_price": json_number(unit),
            "total_amount": json_number(total), "currency": currency}
