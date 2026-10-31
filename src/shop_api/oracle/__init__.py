"""Independent pricing oracle for Medusa carts.

Written from the rules in ``docs/pricing-rules.md`` (Medusa documentation plus measurements on the
pinned version), not from Medusa's source code. Everything is ``Decimal``; nothing is rounded inside
the calculation because Medusa does not round either. ``to_minor_units`` applies this project's own
rounding policy (ROUND_HALF_UP to the currency's minor unit) for checks that money is chargeable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, getcontext
from typing import Literal

getcontext().prec = 34

ZERO = Decimal(0)
HUNDRED = Decimal(100)
MINOR_UNITS = {"eur": 2, "usd": 2, "jpy": 0, "kwd": 3}

Method = Literal["percentage", "fixed"]
Target = Literal["order", "items", "shipping_methods"]
Allocation = Literal["across", "each", "once"]


@dataclass(frozen=True)
class Line:
    unit_price: Decimal
    quantity: int
    product: str = "A"


@dataclass(frozen=True)
class Promo:
    method: Method
    value: Decimal
    target: Target = "order"
    allocation: Allocation = "across"
    max_quantity: int | None = None
    currency: str | None = None
    tax_inclusive: bool = False
    target_products: frozenset[str] | None = None
    min_item_subtotal: Decimal | None = None
    # buy X get Y
    buy_products: frozenset[str] | None = None
    buy_min_quantity: int | None = None
    apply_to_quantity: int | None = None


@dataclass(frozen=True)
class CartInput:
    lines: Sequence[Line]
    currency: str = "eur"
    tax_rate: Decimal = ZERO  # percent, e.g. Decimal(25)
    prices_tax_inclusive: bool = False
    shipping: Decimal | None = None
    promos: Sequence[Promo] = ()


@dataclass
class Breakdown:
    item_subtotal: Decimal
    item_tax_total: Decimal
    item_total: Decimal
    discount_total: Decimal
    shipping_total: Decimal
    tax_total: Decimal
    original_total: Decimal
    total: Decimal
    line_adjustments: list[Decimal] = field(default_factory=list)
    shipping_adjustment: Decimal = ZERO

    def as_dict(self) -> dict[str, Decimal]:
        return {
            "item_subtotal": self.item_subtotal,
            "item_tax_total": self.item_tax_total,
            "item_total": self.item_total,
            "discount_total": self.discount_total,
            "shipping_total": self.shipping_total,
            "tax_total": self.tax_total,
            "original_total": self.original_total,
            "total": self.total,
        }


def to_minor_units(amount: Decimal, currency: str) -> Decimal:
    """This project's rounding policy for chargeable amounts: half-up to the currency's minor unit."""
    exponent = Decimal(1).scaleb(-MINOR_UNITS.get(currency, 2))
    return amount.quantize(exponent, rounding=ROUND_HALF_UP)


def _eligible(promo: Promo, line: Line) -> bool:
    return promo.target_products is None or line.product in promo.target_products


def _line_adjustments(
    promo: Promo, nets: list[Decimal], units: list[Decimal], cart: CartInput
) -> list[Decimal]:
    """Net discount per line for one promotion, computed on the undiscounted amounts (no compounding)."""
    lines = cart.lines
    rate = cart.tax_rate / HUNDRED
    fixed_net = promo.value / (1 + rate) if (promo.method == "fixed" and promo.tax_inclusive) else promo.value
    adjustments = [ZERO] * len(lines)
    eligible = [i for i, line in enumerate(lines) if _eligible(promo, line)]

    if promo.allocation == "across" or promo.target == "order":
        base = sum((nets[i] for i in eligible), ZERO)
        if base == 0:
            return adjustments
        if promo.method == "percentage":
            for i in eligible:
                adjustments[i] = nets[i] * promo.value / HUNDRED
        else:
            amount = min(fixed_net, base)
            for i in eligible:
                adjustments[i] = amount * nets[i] / base
        return adjustments

    def per_unit(i: int) -> Decimal:
        return units[i] * promo.value / HUNDRED if promo.method == "percentage" else min(fixed_net, units[i])

    if promo.allocation == "each":
        cap = promo.max_quantity or 0
        for i in eligible:
            adjustments[i] = per_unit(i) * min(lines[i].quantity, cap)
        return adjustments

    # "once": cheapest eligible units first, up to max_quantity units in total.
    remaining = promo.max_quantity or 0
    for i in sorted(eligible, key=lambda j: units[j]):
        take = min(lines[i].quantity, remaining)
        adjustments[i] = per_unit(i) * take
        remaining -= take
        if remaining == 0:
            break
    return adjustments


def _buyget_adjustments(promo: Promo, units: list[Decimal], cart: CartInput) -> list[Decimal]:
    lines = cart.lines
    adjustments = [ZERO] * len(lines)
    buy = promo.buy_products or frozenset()
    bought = sum(line.quantity for line in lines if line.product in buy)
    if bought < (promo.buy_min_quantity or 0):
        return adjustments
    remaining = min(promo.apply_to_quantity or 0, promo.max_quantity or promo.apply_to_quantity or 0)
    # Highest unit price first among targets (documented selection order).
    for i in sorted((j for j, line in enumerate(lines) if _eligible(promo, line)), key=lambda j: -units[j]):
        take = min(lines[i].quantity, remaining)
        per = units[i] * promo.value / HUNDRED if promo.method == "percentage" else min(promo.value, units[i])
        adjustments[i] = per * take
        remaining -= take
        if remaining == 0:
            break
    return adjustments


def _applies(promo: Promo, cart: CartInput, item_subtotal: Decimal) -> bool:
    if promo.currency is not None and promo.currency != cart.currency:
        return False
    return promo.min_item_subtotal is None or item_subtotal >= promo.min_item_subtotal


def calculate(cart: CartInput) -> Breakdown:
    rate = cart.tax_rate / HUNDRED
    units = [
        line.unit_price / (1 + rate) if cart.prices_tax_inclusive else line.unit_price for line in cart.lines
    ]
    nets = [units[i] * line.quantity for i, line in enumerate(cart.lines)]
    item_subtotal = sum(nets, ZERO)
    gross_items = (
        sum((line.unit_price * line.quantity for line in cart.lines), ZERO)
        if cart.prices_tax_inclusive
        else (item_subtotal * (1 + rate))
    )

    line_adj = [ZERO] * len(cart.lines)
    shipping = cart.shipping or ZERO
    shipping_adj = ZERO
    for promo in cart.promos:
        if not _applies(promo, cart, item_subtotal):
            continue
        if promo.target == "shipping_methods":
            amount = shipping * promo.value / HUNDRED if promo.method == "percentage" else promo.value
            shipping_adj += amount
            continue
        adds = (
            _buyget_adjustments(promo, units, cart)
            if promo.buy_products is not None
            else _line_adjustments(promo, nets, units, cart)
        )
        line_adj = [a + b for a, b in zip(line_adj, adds, strict=True)]

    # A line can never be discounted below zero; neither can shipping.
    line_adj = [min(adj, net) for adj, net in zip(line_adj, nets, strict=True)]
    shipping_adj = min(shipping_adj, shipping)

    discounted_net = item_subtotal - sum(line_adj, ZERO)
    item_tax = discounted_net * rate
    item_total = discounted_net + item_tax
    shipping_total = shipping - shipping_adj  # shipping is untaxed in the regions used by the scenarios
    discount_total = sum(line_adj, ZERO) * (1 + rate) + shipping_adj
    return Breakdown(
        item_subtotal=item_subtotal,
        item_tax_total=item_tax,
        item_total=item_total,
        discount_total=discount_total,
        shipping_total=shipping_total,
        tax_total=item_tax,
        original_total=gross_items + shipping,
        total=item_total + shipping_total,
        line_adjustments=line_adj,
        shipping_adjustment=shipping_adj,
    )
