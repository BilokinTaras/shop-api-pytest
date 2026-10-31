"""The oracle is tested on its own before it is trusted to judge the API.

Examples come from Medusa's documentation (tax-inclusive promotions) and from rules measured on the
pinned version; properties are checked with Hypothesis.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from shop_api.oracle import CartInput, Line, Promo, calculate, to_minor_units

pytestmark = pytest.mark.unit

# Decimal arithmetic at 34 digits leaves noise in the last digits after divide-then-multiply by
# (1 + rate). Medusa itself works at 20 significant digits, so 1e-20 is far below anything it reports.
EPS = D("1e-20")


def close(a: D, b: D) -> bool:
    return abs(a - b) <= EPS


# ---------------------------------------------------------------- documented examples


@pytest.mark.parametrize(
    ("prices_incl", "promo_incl", "total"),
    [
        pytest.param(False, False, D("112.50"), id="doc-tax-exclusive-promo"),
        pytest.param(False, True, D("115"), id="doc-tax-inclusive-promo"),
        pytest.param(True, True, D("90"), id="doc-tax-inclusive-promo-and-prices"),
    ],
)
def test_medusa_documentation_tax_examples(prices_incl: bool, promo_incl: bool, total: D) -> None:
    """https://docs.medusajs.com/resources/commerce-modules/promotion/promotion-taxes — $100 cart, 25 %, $10 off."""
    cart = CartInput(
        lines=[Line(D(100), 1)],
        tax_rate=D(25),
        prices_tax_inclusive=prices_incl,
        promos=[Promo("fixed", D(10), currency="eur", tax_inclusive=promo_incl)],
    )
    assert calculate(cart).total == total


def test_percentage_keeps_full_precision() -> None:
    result = calculate(CartInput(lines=[Line(D("9.99"), 3)], promos=[Promo("percentage", D(15))]))
    assert result.discount_total == D("4.4955")
    assert result.total == D("25.4745")
    assert to_minor_units(result.total, "eur") == D("25.47")


def test_fixed_amount_is_split_in_proportion_to_line_subtotals() -> None:
    cart = CartInput(lines=[Line(D("3.33"), 1, "A"), Line(D("9.99"), 1, "B")], promos=[Promo("fixed", D(10))])
    assert calculate(cart).line_adjustments == [D("2.5"), D("7.5")]


def test_fixed_amount_is_capped_at_the_cart() -> None:
    result = calculate(CartInput(lines=[Line(D("9.99"), 1)], promos=[Promo("fixed", D(50))]))
    assert result.discount_total == D("9.99")
    assert result.total == 0


def test_once_allocation_discounts_cheapest_units_first() -> None:
    cart = CartInput(
        lines=[Line(D(20), 3, "A"), Line(D(5), 4, "B")],
        promos=[Promo("fixed", D(1), target="items", allocation="once", max_quantity=2)],
    )
    assert calculate(cart).line_adjustments == [0, 2]


def test_buy_two_get_one_free() -> None:
    promo = Promo(
        "percentage",
        D(100),
        target="items",
        allocation="each",
        max_quantity=1,
        target_products=frozenset({"B"}),
        buy_products=frozenset({"A"}),
        buy_min_quantity=2,
        apply_to_quantity=1,
    )
    assert calculate(CartInput(lines=[Line(D(20), 2, "A"), Line(D(5), 1, "B")], promos=[promo])).total == 40
    assert calculate(CartInput(lines=[Line(D(20), 1, "A"), Line(D(5), 1, "B")], promos=[promo])).total == 25


@pytest.mark.parametrize(
    ("subtotal", "applies"),
    [(D("19.99"), False), (D("20.00"), True), (D("20.01"), True)],
    ids=["threshold-minus-0.01", "threshold", "threshold-plus-0.01"],
)
def test_minimum_spend_boundary(subtotal: D, applies: bool) -> None:
    promo = Promo("percentage", D(10), min_item_subtotal=D(20))
    result = calculate(CartInput(lines=[Line(subtotal, 1)], promos=[promo]))
    assert (result.discount_total > 0) is applies


def test_currency_mismatch_gives_no_discount() -> None:
    result = calculate(
        CartInput(lines=[Line(D(14), 1)], currency="usd", promos=[Promo("fixed", D(5), currency="eur")])
    )
    assert result.discount_total == 0


def test_free_shipping() -> None:
    result = calculate(
        CartInput(
            lines=[Line(D("9.99"), 1)],
            shipping=D(10),
            promos=[Promo("percentage", D(100), target="shipping_methods")],
        )
    )
    assert (result.shipping_total, result.discount_total, result.total) == (D(0), D(10), D("9.99"))


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (D("25.4745"), "eur", D("25.47")),
        (D("0.005"), "eur", D("0.01")),
        (D("0.0049"), "eur", D("0.00")),
        (D("1.5"), "jpy", D("2")),
        (D("1.2345"), "kwd", D("1.235")),
    ],
)
def test_rounding_policy_is_half_up_to_minor_units(amount: D, currency: str, expected: D) -> None:
    assert to_minor_units(amount, currency) == expected


# ---------------------------------------------------------------- properties

money = st.decimals(min_value=D("0.01"), max_value=D(10_000), places=2)
lines = st.lists(
    st.builds(Line, money, st.integers(min_value=1, max_value=20), st.sampled_from(["A", "B", "C"])),
    min_size=1,
    max_size=4,
)
promos = st.lists(
    st.one_of(
        st.builds(Promo, st.just("percentage"), st.decimals(min_value=0, max_value=100, places=2)),
        st.builds(Promo, st.just("fixed"), money),
        st.builds(
            Promo,
            st.just("fixed"),
            money,
            target=st.just("items"),
            allocation=st.sampled_from(["each", "once"]),
            max_quantity=st.integers(min_value=1, max_value=10),
        ),
    ),
    max_size=3,
)
rates = st.sampled_from([D(0), D(25), D(21), D("7.5")])


@settings(max_examples=300, deadline=None)
@given(lines, promos, rates, st.booleans(), st.one_of(st.none(), money))
def test_total_is_never_negative_and_discount_never_exceeds_the_cart(
    cart_lines: list[Line], cart_promos: list[Promo], rate: D, incl: bool, shipping: D | None
) -> None:
    result = calculate(
        CartInput(cart_lines, tax_rate=rate, prices_tax_inclusive=incl, shipping=shipping, promos=cart_promos)
    )
    assert result.total >= -EPS
    assert result.discount_total <= result.original_total + EPS
    assert close(result.total, result.item_total + result.shipping_total)


@settings(max_examples=200, deadline=None)
@given(
    lines,
    st.decimals(min_value=0, max_value=100, places=2),
    st.decimals(min_value=0, max_value=100, places=2),
)
def test_percentage_discount_is_monotonic(cart_lines: list[Line], low: D, high: D) -> None:
    low, high = min(low, high), max(low, high)
    total_low = calculate(CartInput(cart_lines, promos=[Promo("percentage", low)])).total
    total_high = calculate(CartInput(cart_lines, promos=[Promo("percentage", high)])).total
    assert total_high <= total_low


@settings(max_examples=200, deadline=None)
@given(lines, promos, rates)
def test_removing_all_promotions_restores_the_original_total(
    cart_lines: list[Line], cart_promos: list[Promo], rate: D
) -> None:
    with_promos = calculate(CartInput(cart_lines, tax_rate=rate, promos=cart_promos))
    without = calculate(CartInput(cart_lines, tax_rate=rate))
    assert close(without.total, without.original_total)
    assert close(without.original_total, with_promos.original_total)
    assert without.discount_total == 0


@settings(max_examples=200, deadline=None)
@given(lines, promos)
def test_promotion_order_does_not_matter(cart_lines: list[Line], cart_promos: list[Promo]) -> None:
    """Measured on Medusa 2.22.2: stacked promotions do not compound (10 % + 5 off gives 7.50 either way)."""
    forward = calculate(CartInput(cart_lines, promos=cart_promos)).as_dict()
    backward = calculate(CartInput(cart_lines, promos=list(reversed(cart_promos)))).as_dict()
    assert all(close(forward[k], backward[k]) for k in forward)
