"""Concurrency and idempotency: parallel requests against the same cart or the same last item.

Requests are fired from a thread pool after a barrier, so they reach the server together. Each test
repeats several times (REPEATS) because a race that loses once in five runs is still a race.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any

import allure
import httpx
import pytest
from faker import Faker

from shop_api.clients import AdminClient, StoreClient
from shop_api.config import Settings
from shop_api.db import ReadOnlyDb
from shop_api.factories import address, unique_code, unique_email

pytestmark = [pytest.mark.concurrency, allure.epic("Reliability"), allure.feature("Concurrency")]
REPEATS = 5


@pytest.fixture(scope="session")
def db(settings: Settings) -> ReadOnlyDb:
    return ReadOnlyDb(settings.db_readonly_url)


def in_parallel(n: int, call: Callable[[int], httpx.Response]) -> list[httpx.Response]:
    """Runs `call` n times at once: every thread waits at a barrier, then sends its request."""
    barrier = threading.Barrier(n)

    def run(i: int) -> httpx.Response:
        barrier.wait()
        return call(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(run, range(n)))


def fresh_client(settings: Settings) -> httpx.Client:
    # One connection per thread: sharing an httpx.Client would serialise requests on one pool slot.
    return httpx.Client(
        base_url=settings.backend_url, headers={"x-publishable-api-key": settings.publishable_key}, timeout=30
    )


@allure.story("Double checkout of one cart")
@pytest.mark.parametrize("attempt", range(REPEATS))
def test_completing_one_cart_from_five_tabs_creates_exactly_one_order(
    store: StoreClient, settings: Settings, db: ReadOnlyDb, faker: Faker, attempt: int
) -> None:
    variant = store.first_variant_id("qa-mug", settings.region_id)
    cart = store.create_cart(settings.region_id)
    store.add_item(cart.id, variant, 1)
    store.prepare_checkout(cart.id, address(faker, "dk"), unique_email("qa-race"))
    clients = [fresh_client(settings) for _ in range(5)]
    responses = in_parallel(5, lambda i: clients[i].post(f"/store/carts/{cart.id}/complete"))
    bodies: list[dict[str, Any]] = [r.json() for r in responses]
    order_ids = {b["order"]["id"] for b in bodies if b.get("type") == "order"}
    allure.attach(
        "\n".join(f"{r.status_code} {r.text[:200]}" for r in responses),
        "responses",
        allure.attachment_type.TEXT,
    )
    assert len(order_ids) == 1, f"expected one order, got {order_ids}"
    assert db.orders_for_cart(cart.id) == 1
    # Every caller either sees that same order or a clean conflict — never a server error.
    assert all(r.status_code in {200, 409} for r in responses), [r.status_code for r in responses]


@allure.story("Parallel add to cart")
@pytest.mark.parametrize("attempt", range(REPEATS))
def test_ten_parallel_adds_of_the_same_variant_are_all_counted(
    store: StoreClient, settings: Settings, db: ReadOnlyDb, attempt: int
) -> None:
    variant = store.first_variant_id("qa-mug", settings.region_id)
    cart = store.create_cart(settings.region_id)
    clients = [fresh_client(settings) for _ in range(10)]
    responses = in_parallel(
        10,
        lambda i: clients[i].post(
            f"/store/carts/{cart.id}/line-items", json={"variant_id": variant, "quantity": 1}
        ),
    )
    statuses = [r.status_code for r in responses]
    final = store.get_cart(cart.id)
    total_qty = sum(item.quantity for item in final.items)
    allure.attach(
        f"statuses={statuses}\nlines={[(i.id, i.quantity) for i in final.items]}",
        "result",
        allure.attachment_type.TEXT,
    )
    accepted = statuses.count(200)
    # Whatever the server accepted must be in the cart: no lost updates.
    assert total_qty == accepted, f"{accepted} adds accepted, cart holds {total_qty}"
    assert db.line_quantity(cart.id, variant) == accepted
    assert all(s in {200, 409} for s in statuses), statuses


@pytest.fixture
def last_item(admin: AdminClient, settings: Settings) -> Iterator[dict[str, str]]:
    """A product with exactly one item in stock."""
    profile = admin.request("GET", "/admin/shipping-profiles").json()["shipping_profiles"][0]["id"]
    handle = unique_code("qa-last").lower()
    product = admin.request(
        "POST",
        "/admin/products",
        json={
            "title": f"QA Last {handle}",
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
                    "prices": [{"currency_code": "eur", "amount": 3}],
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
        json={"location_id": settings.stock_location_id, "stocked_quantity": 1},
    )
    yield {"variant_id": variant["id"], "inventory_item_id": item}
    admin.request("DELETE", f"/admin/products/{product['id']}")


@allure.story("Overselling")
@pytest.mark.parametrize("attempt", range(REPEATS))
def test_two_shoppers_racing_for_the_last_item_never_oversell(
    store: StoreClient,
    settings: Settings,
    db: ReadOnlyDb,
    faker: Faker,
    last_item: dict[str, str],
    attempt: int,
) -> None:
    carts = []
    for _ in range(2):
        cart = store.create_cart(settings.region_id)
        store.add_item(cart.id, last_item["variant_id"], 1)
        store.prepare_checkout(cart.id, address(faker, "dk"), unique_email("qa-last"))
        carts.append(cart.id)
    clients = [fresh_client(settings) for _ in range(2)]
    responses = in_parallel(2, lambda i: clients[i].post(f"/store/carts/{carts[i]}/complete"))
    orders = [r.json() for r in responses if r.status_code == 200 and r.json().get("type") == "order"]
    allure.attach(
        "\n".join(f"{r.status_code} {r.text[:200]}" for r in responses),
        "responses",
        allure.attachment_type.TEXT,
    )
    assert len(orders) == 1, f"expected exactly one order, got {len(orders)}"
    level = db.inventory_level(last_item["inventory_item_id"], settings.stock_location_id)
    assert level is not None
    assert Decimal(level["reserved_quantity"]) <= Decimal(level["stocked_quantity"]) == Decimal(1)
    assert all(r.status_code < 500 for r in responses), [r.status_code for r in responses]
