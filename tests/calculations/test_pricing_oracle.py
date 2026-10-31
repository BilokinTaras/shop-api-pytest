"""Medusa cart totals versus the independent pricing oracle (data/calculations/scenarios.yaml).

Each scenario creates its own products and promotions through the Admin API, builds the cart through
the Store API, and compares item subtotal, discounts, shipping, taxes and total with the oracle.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import allure
import pytest
from faker import Faker

from shop_api.clients import AdminClient, StoreClient
from shop_api.config import Settings
from shop_api.data import load
from shop_api.factories import address, unique_code
from shop_api.oracle import CartInput, Line, Promo, Target, calculate, to_minor_units

pytestmark = [
    pytest.mark.calculations,
    allure.epic("Pricing"),
    allure.feature("Oracle vs API"),
]

TOLERANCE = Decimal("1e-9")  # Medusa reports up to 20 significant digits; differences above this are real
COMPARED = ("item_subtotal", "item_tax_total", "discount_total", "shipping_total", "tax_total", "total")
SCENARIOS: list[dict[str, Any]] = load("calculations/scenarios.yaml")["scenarios"]
# Countries not used by the seeded regions. Each xdist worker takes its own pair, so parallel workers
# never fight over a country (a country can belong to one region only).
FREE_COUNTRIES = ["pl", "nl", "be", "at", "fi", "pt", "ie", "cz", "sk", "hu", "ro", "bg", "gr", "hr", "si", "ee",
                  "lv", "lt", "lu", "mt", "cy", "is", "no", "ch", "li", "mc"]  # fmt: skip


@dataclass(frozen=True)
class Region:
    id: str
    currency: str
    tax_rate: Decimal
    prices_tax_inclusive: bool
    country: str


@pytest.fixture(scope="session")
def regions(admin: AdminClient, settings: Settings, worker_id: str) -> Iterator[dict[str, Region]]:
    """Two dedicated 25 % tax regions per worker, removed after the session."""
    index = 0 if worker_id == "master" else int(worker_id.removeprefix("gw"))
    excl_country, incl_country = FREE_COUNTRIES[
        (2 * index) % len(FREE_COUNTRIES) : (2 * index) % len(FREE_COUNTRIES) + 2
    ]
    created: list[str] = []
    tax_regions: list[str] = []

    def release(country: str) -> None:
        """Removes leftovers of an interrupted run that still hold the country; never touches seeded regions."""
        listed = admin.request(
            "GET", "/admin/regions", params={"fields": "id,name,countries.iso_2", "limit": 200}
        )
        for old in listed.json()["regions"]:
            if country in {c["iso_2"] for c in old.get("countries") or []}:
                assert old["name"].startswith("QA Calc"), f"country {country} is used by {old['name']!r}"
                admin.request("DELETE", f"/admin/regions/{old['id']}")
        for old_tax in admin.request("GET", "/admin/tax-regions", params={"country_code": country}).json()[
            "tax_regions"
        ]:
            admin.request("DELETE", f"/admin/tax-regions/{old_tax['id']}")

    def make(name: str, country: str, inclusive: bool) -> Region:
        release(country)
        response = admin.request(
            "POST",
            "/admin/regions",
            json={
                "name": f"{name} {worker_id}",
                "currency_code": "eur",
                "countries": [country],
                "payment_providers": ["pp_system_default"],
                "automatic_taxes": True,
            },
        )
        assert response.status_code == 200, response.text
        region = response.json()["region"]
        created.append(region["id"])
        tax = admin.request(
            "POST",
            "/admin/tax-regions",
            json={
                "country_code": country,
                "provider_id": "tp_system",
                "default_tax_rate": {"rate": 25, "name": "QA VAT 25", "code": "QAVAT25"},
            },
        )
        assert tax.status_code == 200, tax.text
        tax_regions.append(tax.json()["tax_region"]["id"])
        if inclusive:
            preference = admin.request(
                "GET", "/admin/price-preferences", params={"attribute": "region_id", "value": region["id"]}
            ).json()["price_preferences"][0]
            admin.request(
                "POST", f"/admin/price-preferences/{preference['id']}", json={"is_tax_inclusive": True}
            )
        return Region(region["id"], "eur", Decimal(25), inclusive, country)

    yield {
        "eu": Region(settings.region_id, "eur", Decimal(0), False, "dk"),
        "usd": Region(settings.region_usd_id, "usd", Decimal(0), False, "us"),
        "tax25_excl": make("QA Calc Tax25 Excl", excl_country, inclusive=False),
        "tax25_incl": make("QA Calc Tax25 Incl", incl_country, inclusive=True),
    }
    for tax_id in tax_regions:
        admin.request("DELETE", f"/admin/tax-regions/{tax_id}")
    for region_id in created:
        admin.request("DELETE", f"/admin/regions/{region_id}")


@pytest.fixture(scope="session")
def shipping_profile(admin: AdminClient) -> str:
    profile: str = admin.request("GET", "/admin/shipping-profiles").json()["shipping_profiles"][0]["id"]
    return profile


class Scenario:
    """Creates the scenario's products and promotions, builds the cart, cleans up afterwards."""

    def __init__(
        self, admin: AdminClient, store: StoreClient, settings: Settings, profile: str, region: Region
    ) -> None:
        self.admin, self.store, self.settings, self.profile, self.region = (
            admin,
            store,
            settings,
            profile,
            region,
        )
        self.products: dict[str, tuple[str, str]] = {}  # tag -> (product_id, variant_id)
        self.cleanup: list[str] = []

    def product(self, tag: str, price: str, incl_region_id: str) -> tuple[str, str]:
        if tag not in self.products:
            handle = unique_code(f"qa-calc-{tag}").lower()
            prices: list[dict[str, Any]] = [
                # JSON numbers; float(str) of two-decimal prices round-trips exactly ("9.99" -> 9.99).
                {"currency_code": "eur", "amount": float(price)},
                {"currency_code": "usd", "amount": float(price)},
                # Region-scoped price: only this price is tax-inclusive (via the region's preference).
                {"currency_code": "eur", "amount": float(price), "rules": {"region_id": incl_region_id}},
            ]
            body = {
                "title": f"QA Calc {tag} {handle}",
                "handle": handle,
                "status": "published",
                "shipping_profile_id": self.profile,
                "sales_channels": [{"id": self.settings.sales_channel_id}],
                "options": [{"title": "O", "values": ["V"]}],
                "variants": [
                    {"title": "V", "manage_inventory": False, "options": {"O": "V"}, "prices": prices}
                ],
            }
            response = self.admin.request("POST", "/admin/products", json=body)
            assert response.status_code == 200, response.text
            product = response.json()["product"]
            self.cleanup.append(f"/admin/products/{product['id']}")
            self.products[tag] = (product["id"], product["variants"][0]["id"])
        return self.products[tag]

    def promotion(self, spec: dict[str, Any]) -> str:
        code = unique_code("QACALC")
        method = spec["method"]
        currency = spec.get("currency", self.region.currency if method == "fixed" else None)
        target = spec.get("target", "order")
        kwargs: dict[str, Any] = {
            "target_type": target,
            "allocation": spec.get(
                "allocation", "across" if target != "items" or "buyget" not in spec else "each"
            ),
            "currency_code": currency,
        }
        if "max_quantity" in spec:
            kwargs["max_quantity"] = spec["max_quantity"]
        rules = lambda tags: [  # noqa: E731
            {"attribute": "items.product.id", "operator": "in", "values": [self.products[t][0] for t in tags]}
        ]
        if "target_products" in spec:
            kwargs["target_rules"] = rules(spec["target_products"])
        if "min_item_subtotal" in spec:
            kwargs["rules"] = [
                {"attribute": "item_subtotal", "operator": "gte", "values": [spec["min_item_subtotal"]]}
            ]
        if spec.get("tax_inclusive"):
            kwargs["is_tax_inclusive"] = True
        if buyget := spec.get("buyget"):
            kwargs.update(
                promotion_type="buyget",
                target_type="items",
                allocation="each",
                max_quantity=buyget["apply_to_quantity"],
                apply_to_quantity=buyget["apply_to_quantity"],
                buy_rules_min_quantity=buyget["min_quantity"],
                buy_rules=rules(buyget["buy"]),
                target_rules=rules(buyget["targets"]),
            )
        promotion = self.admin.create_promotion(code, method, spec["value"], **kwargs)
        self.cleanup.append(f"/admin/promotions/{promotion.id}")
        return code

    def close(self) -> None:
        for path in reversed(self.cleanup):
            self.admin.request("DELETE", path)


def oracle_input(scenario: dict[str, Any], region: Region) -> CartInput:
    def promo(spec: dict[str, Any]) -> Promo:
        buyget = spec.get("buyget")
        target: Target = "items" if buyget else spec.get("target", "order")
        return Promo(
            method=spec["method"],
            value=Decimal(spec["value"]),
            target=target,
            allocation="each" if buyget else spec.get("allocation", "across"),
            max_quantity=(buyget or {}).get("apply_to_quantity", spec.get("max_quantity")),
            currency=spec.get("currency", region.currency if spec["method"] == "fixed" else None),
            tax_inclusive=bool(spec.get("tax_inclusive")),
            target_products=frozenset(buyget["targets"] if buyget else spec["target_products"])
            if (buyget or "target_products" in spec)
            else None,
            min_item_subtotal=Decimal(spec["min_item_subtotal"]) if "min_item_subtotal" in spec else None,
            buy_products=frozenset(buyget["buy"]) if buyget else None,
            buy_min_quantity=buyget["min_quantity"] if buyget else None,
            apply_to_quantity=buyget["apply_to_quantity"] if buyget else None,
        )

    return CartInput(
        lines=[Line(Decimal(line["price"]), line["qty"], line["product"]) for line in scenario["lines"]],
        currency=region.currency,
        tax_rate=region.tax_rate,
        prices_tax_inclusive=region.prices_tax_inclusive,
        shipping=Decimal(10) if scenario.get("shipping") else None,
        promos=[promo(p) for p in scenario.get("promos", [])],
    )


def breakdown_table(api: dict[str, Decimal], oracle: dict[str, Decimal]) -> str:
    rows = ["| field | API | oracle | diff |", "|---|---:|---:|---:|"]
    for key in COMPARED:
        rows.append(f"| {key} | {api[key]} | {oracle[key]} | {api[key] - oracle[key]} |")
    return "\n".join(rows)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_cart_totals_match_the_oracle(
    scenario: dict[str, Any],
    admin: AdminClient,
    store: StoreClient,
    settings: Settings,
    regions: dict[str, Region],
    shipping_profile: str,
    faker: Faker,
) -> None:
    region = regions[scenario["region"]]
    allure.dynamic.story(scenario["region"])
    if scenario.get("docs"):
        allure.dynamic.tag("medusa-docs-example")
    built = Scenario(admin, store, settings, shipping_profile, region)
    try:
        with allure.step("create products and promotions through the Admin API"):
            for line in scenario["lines"]:
                built.product(line["product"], line["price"], regions["tax25_incl"].id)
            codes = [built.promotion(spec) for spec in scenario.get("promos", [])]
        with allure.step("build the cart through the Store API"):
            cart = store.create_cart(region.id)
            for line in scenario["lines"]:
                store.add_item(cart.id, built.products[line["product"]][1], line["qty"])
            store.update_cart(cart.id, shipping_address=address(faker, region.country))
            if scenario.get("shipping"):
                store.add_shipping_method(cart.id, store.shipping_options(cart.id)[0].id)
            if codes:
                store.apply_promotions(cart.id, codes)
            final = store.get_cart(cart.id)
        api = {key: getattr(final, key) for key in COMPARED}
        expected = calculate(oracle_input(scenario, region)).as_dict()
        allure.attach(breakdown_table(api, expected), "API vs oracle", allure.attachment_type.TEXT)
        mismatches = {k: (api[k], expected[k]) for k in COMPARED if abs(api[k] - expected[k]) > TOLERANCE}
        assert not mismatches, f"API differs from oracle:\n{breakdown_table(api, expected)}"
    finally:
        built.close()


@allure.feature("Money precision")
@pytest.mark.finding("BUG-API-006")
@pytest.mark.xfail(
    reason="BUG-API-006: totals and payment amounts are not in currency minor units", strict=True
)
def test_order_and_payment_amounts_are_in_minor_units(
    admin: AdminClient,
    store: StoreClient,
    settings: Settings,
    faker: Faker,
    shipping_profile: str,
    regions: dict[str, Region],
) -> None:
    """15 % off 3 x 9.99 is 4.4955 EUR. Whatever the rounding rule, a charged amount must be whole cents."""
    built = Scenario(admin, store, settings, shipping_profile, regions["eu"])
    try:
        _, variant = built.product("A", "9.99", regions["tax25_incl"].id)
        code = built.promotion({"method": "percentage", "value": "15"})
        cart = store.create_cart(settings.region_id, email="minor-units@example.com")
        store.add_item(cart.id, variant, 3)
        store.apply_promotions(cart.id, [code])
        store.prepare_checkout(cart.id, address(faker, "dk"), "minor-units@example.com")
        collection = store.request("POST", "/store/payment-collections", json={"cart_id": cart.id}).json()
        amount = Decimal(json.dumps(collection["payment_collection"]["amount"]))
        allure.attach(f"payment collection amount: {amount}", "amount", allure.attachment_type.TEXT)
        assert amount == to_minor_units(amount, "eur"), f"payment amount {amount} EUR is not whole cents"
    finally:
        built.close()
