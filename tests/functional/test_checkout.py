"""Cart → order: shipping, system payment, completion, order history, inventory."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import allure
import pytest
from faker import Faker

from shop_api.clients import AdminClient, StoreClient
from shop_api.config import Settings
from shop_api.factories import address, unique_code, unique_email
from shop_api.models import CompletedOrder
from tests.conftest import CustomerSession

pytestmark = [pytest.mark.functional, allure.epic("Store API"), allure.feature("Checkout")]


def place_order(
    store: StoreClient, region_id: str, variant_id: str, qty: int, *, email: str, faker: Faker
) -> CompletedOrder:
    cart = store.create_cart(region_id)
    store.add_item(cart.id, variant_id, qty)
    store.prepare_checkout(cart.id, address(faker, "dk"), email)
    result = store.complete_cart(cart.id)
    assert isinstance(result, CompletedOrder), result
    return result


@allure.story("Guest checkout")
@allure.severity(allure.severity_level.BLOCKER)
def test_guest_checkout_creates_an_order_with_correct_totals(
    store: StoreClient, admin: AdminClient, settings: Settings, faker: Faker
) -> None:
    variant = store.first_variant_id("qa-tee", settings.region_id)
    email = unique_email("qa-py-guest")
    with allure.step("cart with 2 x QA Tee, standard shipping"):
        order = place_order(store, settings.region_id, variant, 2, email=email, faker=faker).order
    with allure.step("totals: 2 x 25.00 + 10.00 shipping, no tax in the seeded region"):
        assert order.item_total == Decimal("50")
        assert order.shipping_total == Decimal("10")
        assert order.total == Decimal("60")
    with allure.step("Admin API sees the same order"):
        admin_order = admin.get_order(order.id)
        assert admin_order.email == email
        assert admin_order.total == order.total


@allure.story("Shipping")
def test_shipping_options_depend_on_the_region(store: StoreClient, settings: Settings, faker: Faker) -> None:
    eu = store.create_cart(settings.region_id)
    store.update_cart(eu.id, shipping_address=address(faker, "dk"))
    us = store.create_cart(settings.region_usd_id)
    store.update_cart(us.id, shipping_address=address(faker, "us"))
    assert {o.name for o in store.shipping_options(eu.id)} == {"Standard Shipping", "Express Shipping"}
    assert {o.name for o in store.shipping_options(us.id)} == {"QA Standard Shipping (US/CA)"}


@allure.story("Shipping")
def test_shipping_method_adds_its_price_to_the_cart(
    store: StoreClient, settings: Settings, faker: Faker
) -> None:
    cart = store.create_cart(settings.region_usd_id)
    store.add_item(cart.id, store.first_variant_id("qa-mug", settings.region_usd_id), 1)
    store.update_cart(cart.id, shipping_address=address(faker, "us"))
    option = store.shipping_options(cart.id)[0]
    updated = store.add_shipping_method(cart.id, option.id)
    assert updated.shipping_total == Decimal("8")
    assert updated.total == Decimal("22")  # 14.00 USD + 8.00 USD


@allure.story("Order history")
def test_signed_in_customer_sees_own_order_in_history(
    customer: CustomerSession, settings: Settings, faker: Faker
) -> None:
    variant = customer.store.first_variant_id("qa-mug", settings.region_id)
    order = place_order(
        customer.store, settings.region_id, variant, 1, email=customer.email, faker=faker
    ).order
    history = customer.store.list_orders()
    assert [o.id for o in history.orders] == [order.id]
    assert customer.store.get_order(order.id).total == order.total


@allure.story("Completion")
def test_completed_cart_cannot_take_new_items(store: StoreClient, settings: Settings, faker: Faker) -> None:
    variant = store.first_variant_id("qa-mug", settings.region_id)
    cart = store.create_cart(settings.region_id)
    store.add_item(cart.id, variant, 1)
    store.prepare_checkout(cart.id, address(faker, "dk"), unique_email())
    assert isinstance(store.complete_cart(cart.id), CompletedOrder)
    response = store.request(
        "POST", f"/store/carts/{cart.id}/line-items", json={"variant_id": variant, "quantity": 1}
    )
    assert response.status_code == 400, response.text
    assert "completed" in response.text.lower()


@pytest.fixture
def stocked_variant(admin: AdminClient, settings: Settings) -> Iterator[tuple[str, str]]:
    """A fresh product with 5 items in stock; yields (variant_id, inventory_item_id)."""
    profile = admin.request("GET", "/admin/shipping-profiles").json()["shipping_profiles"][0]["id"]
    handle = unique_code("qa-py-stock").lower()
    product = admin.request(
        "POST",
        "/admin/products",
        json={
            "title": f"QA Stock {handle}",
            "handle": handle,
            "status": "published",
            "shipping_profile_id": profile,
            "sales_channels": [{"id": settings.sales_channel_id}],
            "options": [{"title": "Default option", "values": ["Default option value"]}],
            "variants": [
                {
                    "title": "Default",
                    "manage_inventory": True,
                    "options": {"Default option": "Default option value"},
                    "prices": [{"currency_code": "eur", "amount": 9}],
                }
            ],
        },
    ).json()["product"]
    variant = admin.request(
        "GET", f"/admin/products/{product['id']}/variants", params={"fields": "*inventory_items"}
    ).json()["variants"][0]
    item_id = variant["inventory_items"][0]["inventory_item_id"]
    admin.request(
        "POST",
        f"/admin/inventory-items/{item_id}/location-levels",
        json={"location_id": settings.stock_location_id, "stocked_quantity": 5},
    )
    yield variant["id"], item_id
    admin.request("DELETE", f"/admin/products/{product['id']}")


@allure.story("Inventory")
def test_order_reserves_stock_and_lowers_availability(
    store: StoreClient, admin: AdminClient, settings: Settings, faker: Faker, stocked_variant: tuple[str, str]
) -> None:
    variant_id, item_id = stocked_variant
    place_order(store, settings.region_id, variant_id, 2, email=unique_email(), faker=faker)
    level = admin.request("GET", f"/admin/inventory-items/{item_id}/location-levels").json()[
        "inventory_levels"
    ][0]
    assert (level["stocked_quantity"], level["reserved_quantity"], level["available_quantity"]) == (5, 2, 3)
