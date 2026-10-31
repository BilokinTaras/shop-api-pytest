"""Database state after API operations, read through the `qa_readonly` role."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import allure
import psycopg
import pytest
from faker import Faker

from shop_api.clients import AdminClient, StoreClient
from shop_api.config import Settings
from shop_api.db import ReadOnlyDb
from shop_api.factories import address, unique_code, unique_email
from shop_api.models import CompletedOrder
from tests.conftest import CustomerFactory

pytestmark = [pytest.mark.db, allure.epic("Database"), allure.feature("State after API calls")]


@pytest.fixture(scope="session")
def db(settings: Settings) -> ReadOnlyDb:
    return ReadOnlyDb(settings.db_readonly_url)


@pytest.fixture
def stocked_product(admin: AdminClient, settings: Settings) -> Iterator[dict[str, str]]:
    """Product with inventory management and 5 items in stock; deleted (soft) afterwards."""
    profile = admin.request("GET", "/admin/shipping-profiles").json()["shipping_profiles"][0]["id"]
    handle = unique_code("qa-db").lower()
    product = admin.request(
        "POST",
        "/admin/products",
        json={
            "title": f"QA DB {handle}",
            "handle": handle,
            "status": "published",
            "shipping_profile_id": profile,
            "sales_channels": [{"id": settings.sales_channel_id}],
            "options": [{"title": "O", "values": ["V"]}],
            "variants": [
                {
                    "title": "V",
                    "manage_inventory": True,
                    "options": {"O": "V"},
                    "prices": [{"currency_code": "eur", "amount": 7.25}],
                }
            ],
        },
    ).json()["product"]
    variant = admin.request(
        "GET", f"/admin/products/{product['id']}/variants", params={"fields": "*inventory_items"}
    ).json()["variants"][0]
    item = variant["inventory_items"][0]["inventory_item_id"]
    admin.request(
        "POST",
        f"/admin/inventory-items/{item}/location-levels",
        json={"location_id": settings.stock_location_id, "stocked_quantity": 5},
    )
    yield {"product_id": product["id"], "variant_id": variant["id"], "inventory_item_id": item}
    admin.request("DELETE", f"/admin/products/{product['id']}")


def checkout(store: StoreClient, settings: Settings, variant: str, qty: int, faker: Faker) -> CompletedOrder:
    cart = store.create_cart(settings.region_id)
    store.add_item(cart.id, variant, qty)
    store.prepare_checkout(cart.id, address(faker, "dk"), unique_email("qa-db"))
    result = store.complete_cart(cart.id)
    assert isinstance(result, CompletedOrder), result
    return result


@allure.story("Orders")
def test_order_is_stored_with_lines_and_totals(
    db: ReadOnlyDb, store: StoreClient, settings: Settings, faker: Faker, stocked_product: dict[str, str]
) -> None:
    order = checkout(store, settings, stocked_product["variant_id"], 3, faker).order
    row = db.order(order.id)
    assert row is not None
    assert (row["email"], row["currency_code"]) == (order.email, "eur")
    lines = db.order_lines(order.id)
    assert [
        (line["variant_id"], Decimal(line["unit_price"]), Decimal(line["quantity"])) for line in lines
    ] == [(stocked_product["variant_id"], Decimal("7.25"), Decimal(3))]
    assert db.order_total(order.id) == order.total == Decimal("31.75")  # 3 x 7.25 + 10 shipping


@allure.story("Inventory")
def test_order_creates_a_reservation_and_reserves_stock(
    db: ReadOnlyDb, store: StoreClient, settings: Settings, faker: Faker, stocked_product: dict[str, str]
) -> None:
    order = checkout(store, settings, stocked_product["variant_id"], 2, faker).order
    reservations = db.reservations_for_order(order.id)
    assert [(r["inventory_item_id"], Decimal(r["quantity"])) for r in reservations] == [
        (stocked_product["inventory_item_id"], Decimal(2))
    ]
    level = db.inventory_level(stocked_product["inventory_item_id"], settings.stock_location_id)
    assert level is not None
    assert (Decimal(level["stocked_quantity"]), Decimal(level["reserved_quantity"])) == (
        Decimal(5),
        Decimal(2),
    )


@allure.story("Soft delete")
def test_deleted_product_is_soft_deleted_and_hidden_from_the_store(
    db: ReadOnlyDb, admin: AdminClient, store: StoreClient, stocked_product: dict[str, str]
) -> None:
    product_id = stocked_product["product_id"]
    admin.request("DELETE", f"/admin/products/{product_id}")
    row = db.product(product_id)
    assert row is not None, "the row must stay in the table"
    assert row["deleted_at"] is not None
    assert store.request("GET", f"/store/products/{product_id}").status_code == 404


@allure.story("Carts")
def test_one_order_per_completed_cart(
    db: ReadOnlyDb, store: StoreClient, settings: Settings, faker: Faker
) -> None:
    variant = store.first_variant_id("qa-mug", settings.region_id)
    cart = store.create_cart(settings.region_id)
    store.add_item(cart.id, variant, 1)
    store.prepare_checkout(cart.id, address(faker, "dk"), unique_email())
    store.complete_cart(cart.id)
    store.complete_cart(cart.id)
    assert db.orders_for_cart(cart.id) == 1


@allure.feature("Authorization")
@allure.story("BOLA evidence in the data")
@pytest.mark.finding("BUG-API-010")
@pytest.mark.xfail(
    reason="BUG-API-010: another customer can take over a registered customer's cart", strict=True
)
def test_cart_owner_does_not_change_when_another_customer_claims_it(
    db: ReadOnlyDb, settings: Settings, make_customer: CustomerFactory
) -> None:
    owner, other = make_customer(), make_customer()
    cart = owner.store.create_cart(settings.region_id)
    other.store.request("POST", f"/store/carts/{cart.id}/customer")
    row = db.cart_owner(cart.id)
    assert row is not None
    assert (row["customer_id"], row["email"]) == (owner.profile.id, owner.email)


@allure.story("Read-only role")
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE product SET title = 'x' WHERE false",
        "CREATE TABLE qa_should_not_exist (id int)",
        "DELETE FROM cart WHERE false",
    ],
    ids=["update", "create", "delete"],
)
def test_the_test_role_cannot_write(db: ReadOnlyDb, statement: str) -> None:
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        db.one(statement)
