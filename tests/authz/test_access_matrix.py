"""Role x operation access matrix generated from data/authz/matrix.yaml, including BOLA cases.

Every case builds its own resources owned by customer A (address, cart, order, promotion), so cases
run in parallel and in any order. Classes in the matrix separate deliberate behaviour (IDs used as
capabilities, documented by Medusa) from defects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import allure
import httpx
import pytest
from faker import Faker

from shop_api.clients import AdminClient, StoreClient
from shop_api.config import Settings
from shop_api.data import load
from shop_api.factories import address, unique_code
from shop_api.models import CompletedOrder
from tests.conftest import CustomerFactory

pytestmark = [pytest.mark.authz, allure.epic("Security"), allure.feature("Access matrix")]

MATRIX = load("authz/matrix.yaml")


def _expected(spec: Any) -> tuple[int, str, str | None]:
    if isinstance(spec, int):
        return spec, "allow" if spec < 400 else "deny", None
    return (
        int(spec["status"]),
        str(spec.get("class", "finding" if "finding" in spec else "allow")),
        spec.get("finding"),
    )


def _cases() -> list[Any]:
    params = []
    for op in MATRIX["operations"]:
        for role, spec in op["expect"].items():
            status, klass, finding = _expected(spec)
            marks = []
            if finding:
                marks += [
                    pytest.mark.finding(finding),
                    pytest.mark.xfail(reason=f"{finding}: see docs/findings.md", strict=True),
                ]
            params.append(pytest.param(op, role, status, klass, id=f"{op['id']}[{role}]", marks=marks))
    return params


@dataclass
class World:
    """Resources of customer A plus a client per role."""

    clients: dict[str, httpx.Client]
    ids: dict[str, str]


def build_world(
    settings: Settings, store: StoreClient, admin: AdminClient, make_customer: CustomerFactory, faker: Faker
) -> World:
    a, b = make_customer(), make_customer()
    key = {"x-publishable-api-key": settings.publishable_key}
    admin_token = admin._client.headers["authorization"]
    clients = {
        "anonymous": httpx.Client(base_url=settings.backend_url, headers=key, timeout=15),
        "customer_a": httpx.Client(
            base_url=settings.backend_url, headers={**key, "authorization": f"Bearer {a.token}"}, timeout=15
        ),
        "customer_b": httpx.Client(
            base_url=settings.backend_url, headers={**key, "authorization": f"Bearer {b.token}"}, timeout=15
        ),
        "admin": httpx.Client(
            base_url=settings.backend_url, headers={**key, "authorization": admin_token}, timeout=15
        ),
    }
    variant = store.first_variant_id("qa-mug", settings.region_id)
    ids = {"variant": variant}
    created = a.store.request("POST", "/store/customers/me/addresses", json=address(faker, "dk")).json()
    ids["address_a"] = created["customer"]["addresses"][0]["id"]
    cart = a.store.create_cart(settings.region_id)
    a.store.add_item(cart.id, variant, 1)
    ids["cart_a"] = cart.id
    order_cart = a.store.create_cart(settings.region_id)
    a.store.add_item(order_cart.id, variant, 1)
    a.store.prepare_checkout(order_cart.id, address(faker, "dk"), a.email)
    result = a.store.complete_cart(order_cart.id)
    assert isinstance(result, CompletedOrder)
    ids["order_a"] = result.order.id
    promotion = admin.create_promotion(unique_code("QAAUTHZ"), "percentage", 5)
    ids["promotion"] = promotion.id
    return World(clients, ids)


_SHARED: dict[str, World] = {}


@pytest.fixture
def world(
    request: pytest.FixtureRequest,
    settings: Settings,
    store: StoreClient,
    admin: AdminClient,
    make_customer: CustomerFactory,
    faker: Faker,
) -> World:
    """Fresh resources for operations that change them; one shared set per worker for read-only ones."""
    operation = request.node.callspec.params["operation"]
    if operation.get("mutates"):
        return build_world(settings, store, admin, make_customer, faker)
    if "shared" not in _SHARED:
        _SHARED["shared"] = build_world(settings, store, admin, make_customer, faker)
    return _SHARED["shared"]


def _resolve(value: Any, ids: dict[str, str]) -> Any:
    if isinstance(value, str):
        for name, real in ids.items():
            value = value.replace("{" + name + "}", real)
        return value
    if isinstance(value, dict):
        return {k: _resolve(v, ids) for k, v in value.items()}
    return value


@pytest.mark.parametrize(("operation", "role", "status", "klass"), _cases())
def test_access_matrix(world: World, operation: dict[str, Any], role: str, status: int, klass: str) -> None:
    method, path = operation["request"].split(" ", 1)
    allure.dynamic.story(operation["id"])
    allure.dynamic.tag(klass)
    if note := operation.get("note"):
        allure.dynamic.description(str(note))
    response = world.clients[role].request(
        method, _resolve(path, world.ids), json=_resolve(operation.get("body"), world.ids)
    )
    assert response.status_code == status, (
        f"{role} {method} {path}: {response.status_code} {response.text[:300]}"
    )
    if operation["id"] == "list-orders" and role == "customer_b":
        assert world.ids["order_a"] not in {o["id"] for o in response.json()["orders"]}


def test_matrix_has_at_least_forty_cases() -> None:
    assert len(_cases()) >= 40
