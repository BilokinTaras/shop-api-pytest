"""Store API negative cases generated from data/negative/store.yaml (EP and BVA tables)."""

from __future__ import annotations

from typing import Any

import allure
import httpx
import pytest

from shop_api.clients import StoreClient
from shop_api.config import Settings
from shop_api.data import cases
from shop_api.models import MedusaError

pytestmark = [pytest.mark.negative, allure.epic("Store API"), allure.feature("Input validation")]
TABLE = "negative/store.yaml"


@pytest.fixture(scope="module")
def placeholders(store: StoreClient, settings: Settings) -> dict[str, str]:
    return {
        "variant_id": store.first_variant_id("qa-mug", settings.region_id),
        "sold_out_variant_id": store.first_variant_id("qa-sold-out", settings.region_id),
        "region_id": settings.region_id,
    }


def resolve(value: Any, values: dict[str, str]) -> Any:
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        return values[value[1:-1]]
    if isinstance(value, dict):
        return {k: resolve(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, values) for v in value]
    return value


def check_error(response: Any, case: dict[str, Any]) -> None:
    with allure.step(f"expect {case['status']} {case.get('type', '')}"):
        assert response.status_code == case["status"], response.text
        error = MedusaError.model_validate(response.json())
        if "type" in case:
            assert error.type == case["type"]
        if "message" in case:
            assert case["message"].lower() in error.message.lower(), error.message


@allure.story("Catalog query parameters")
@pytest.mark.parametrize("case", cases(TABLE, "catalog_query"))
def test_catalog_query_validation(store: StoreClient, case: dict[str, Any]) -> None:
    check_error(store.request("GET", "/store/products", params=case["params"]), case)


@allure.story("Line item quantity and variant")
@pytest.mark.parametrize("case", cases(TABLE, "line_item_quantity"))
def test_line_item_validation(
    store: StoreClient, settings: Settings, placeholders: dict[str, str], case: dict[str, Any]
) -> None:
    cart = store.create_cart(settings.region_id)
    response = store.request(
        "POST", f"/store/carts/{cart.id}/line-items", json=resolve(case["body"], placeholders)
    )
    check_error(response, case)


@allure.story("Cart creation")
@pytest.mark.parametrize("case", cases(TABLE, "cart_create"))
def test_cart_create_validation(
    store: StoreClient, placeholders: dict[str, str], case: dict[str, Any]
) -> None:
    check_error(store.request("POST", "/store/carts", json=resolve(case["body"], placeholders)), case)


@allure.story("Unknown resource IDs")
@pytest.mark.parametrize("case", cases(TABLE, "unknown_ids"))
def test_unknown_ids(store: StoreClient, placeholders: dict[str, str], case: dict[str, Any]) -> None:
    body = resolve(case.get("body"), placeholders)
    check_error(store.request(case["method"], case["path"], json=body), case)


@allure.story("Publishable key")
@pytest.mark.parametrize(
    ("headers", "message"),
    [
        pytest.param({}, "x-publishable-api-key", id="missing"),
        pytest.param({"x-publishable-api-key": "pk_unknown"}, "valid publishable key", id="unknown"),
        pytest.param({"x-publishable-api-key": ""}, "x-publishable-api-key", id="empty"),
    ],
)
def test_store_requires_a_valid_publishable_key(
    settings: Settings, headers: dict[str, str], message: str
) -> None:
    response = httpx.get(f"{settings.backend_url}/store/products", headers=headers, timeout=15)
    assert response.status_code == 400
    error = MedusaError.model_validate(response.json())
    assert error.type == "not_allowed"
    assert message in error.message
