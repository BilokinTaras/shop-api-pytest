"""Catalog and regions: pagination boundaries, field selection, filters, sorting, currencies."""

from __future__ import annotations

from decimal import Decimal

import allure
import pytest

from shop_api.clients import StoreClient
from shop_api.config import Settings

pytestmark = [pytest.mark.functional, allure.epic("Store API"), allure.feature("Catalog")]

FIELDS = "id,handle,title"


@pytest.fixture(scope="module")
def stable(store: StoreClient) -> dict[str, str]:
    """Pagination is checked inside the seeded "QA Picks" collection (3 products). Other tests create and
    delete products in parallel, so the size of the whole catalog is not a stable oracle."""
    collection = store.request("GET", "/store/collections", params={"handle": "qa-picks"}).json()[
        "collections"
    ][0]
    return {"collection_id[]": collection["id"], "fields": FIELDS}


@pytest.fixture(scope="module")
def total(store: StoreClient, stable: dict[str, str]) -> int:
    count = store.list_products(limit=1, **stable).count
    assert count == 3, "QA Picks collection should hold qa-tee, qa-mug and qa-sold-out"
    return count


@allure.story("Pagination boundaries")
@pytest.mark.parametrize("limit", [0, 1, 2, 50], ids=lambda v: f"limit={v}")
def test_limit_returns_at_most_limit_products(
    store: StoreClient, stable: dict[str, str], total: int, limit: int
) -> None:
    page = store.list_products(limit=limit, **stable)
    assert page.limit == limit
    assert len(page.products) == min(limit, total)
    assert page.count == total


@allure.story("Pagination boundaries")
@pytest.mark.parametrize("delta", [-1, 0, 1], ids=["last-item", "count", "past-count"])
def test_offset_around_the_end_of_the_catalog(
    store: StoreClient, stable: dict[str, str], total: int, delta: int
) -> None:
    page = store.list_products(offset=total + delta, **stable)
    assert len(page.products) == (1 if delta == -1 else 0)
    assert page.count == total


@allure.story("Pagination boundaries")
def test_pages_do_not_overlap_and_cover_the_catalog(
    store: StoreClient, stable: dict[str, str], total: int
) -> None:
    seen: list[str] = []
    for offset in range(0, total, 2):
        seen += [p.id for p in store.list_products(limit=2, offset=offset, order="handle", **stable).products]
    assert len(seen) == total
    assert len(set(seen)) == total


@allure.story("Field selection")
def test_fields_parameter_limits_the_response(store: StoreClient) -> None:
    response = store.request("GET", "/store/products", params={"fields": "id,handle", "limit": 3})
    for product in response.json()["products"]:
        assert set(product) <= {"id", "handle"}


@allure.story("Field selection")
def test_plus_prefix_adds_relations_to_default_fields(store: StoreClient, settings: Settings) -> None:
    product = store.product_by_handle("qa-tee", settings.region_id)
    assert product.title == "QA Tee"
    assert product.variants is not None
    assert {v.sku for v in product.variants} == {"QA-TEE-S", "QA-TEE-M", "QA-TEE-L"}


@allure.story("Filters")
def test_filter_by_several_handles(store: StoreClient) -> None:
    page = store.list_products(**{"handle[]": ["qa-tee", "qa-mug"]}, fields=FIELDS)
    assert {p.handle for p in page.products} == {"qa-tee", "qa-mug"}


@allure.story("Filters")
def test_full_text_search(store: StoreClient) -> None:
    page = store.list_products(q="QA Mug", fields=FIELDS)
    assert "qa-mug" in {p.handle for p in page.products}


@allure.story("Filters")
def test_filter_by_ids(store: StoreClient, stable: dict[str, str]) -> None:
    ids = [p.id for p in store.list_products(limit=2, order="handle", **stable).products]
    page = store.list_products(**{"id[]": ids}, fields=FIELDS)
    assert sorted(p.id for p in page.products) == sorted(ids)


@allure.story("Sorting")
@pytest.mark.parametrize("order", ["title", "-title"])
def test_sort_by_title(store: StoreClient, order: str) -> None:
    titles = [p.title for p in store.list_products(order=order, limit=50, fields=FIELDS).products]
    expected = sorted(titles, key=str.lower, reverse=order.startswith("-"))
    assert titles == expected


@allure.story("Sorting")
def test_sort_by_created_at_descending(store: StoreClient) -> None:
    response = store.request(
        "GET", "/store/products", params={"order": "-created_at", "fields": "id,created_at"}
    )
    stamps = [p["created_at"] for p in response.json()["products"]]
    assert stamps == sorted(stamps, reverse=True)


@allure.feature("Regions and currencies")
@pytest.mark.parametrize(
    ("region", "currency", "price"),
    [("region_id", "eur", Decimal("25")), ("region_usd_id", "usd", Decimal("30"))],
    ids=["europe-eur", "north-america-usd"],
)
def test_price_follows_the_region(
    store: StoreClient, settings: Settings, region: str, currency: str, price: Decimal
) -> None:
    product = store.product_by_handle("qa-tee", getattr(settings, region))
    calculated = (product.variants or [])[0].calculated_price
    assert calculated is not None
    assert calculated.currency_code == currency
    assert calculated.calculated_amount == price


@allure.feature("Regions and currencies")
def test_regions_and_their_countries(store: StoreClient, settings: Settings) -> None:
    regions = {r.id: r for r in store.list_regions().regions}
    europe = {c.iso_2 for c in regions[settings.region_id].countries or []}
    usd = {c.iso_2 for c in regions[settings.region_usd_id].countries or []}
    assert europe == {"gb", "de", "dk", "se", "fr", "es", "it"}
    assert usd == {"us", "ca"}
    assert not europe & usd


@allure.feature("Regions and currencies")
def test_cart_currency_follows_region(store: StoreClient, settings: Settings) -> None:
    assert store.create_cart(settings.region_usd_id).currency_code == "usd"
    assert store.create_cart(settings.region_id).currency_code == "eur"
