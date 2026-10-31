"""Shared fixtures: settings, API clients, per-test customers, and created data with cleanup."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import allure
import pytest
from faker import Faker

from shop_api.clients import AdminClient, AuthClient, StoreClient
from shop_api.clients.base import JOURNAL
from shop_api.config import Settings, get_settings
from shop_api.factories import TEST_PASSWORD, seeded_faker, unique_code, unique_email
from shop_api.models import Customer, Promotion


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def store(settings: Settings) -> Iterator[StoreClient]:
    client = StoreClient(settings.backend_url, settings.publishable_key)
    yield client
    client.close()


@pytest.fixture(scope="session")
def auth(settings: Settings) -> Iterator[AuthClient]:
    client = AuthClient(settings.backend_url)
    yield client
    client.close()


@pytest.fixture(scope="session")
def admin(settings: Settings, auth: AuthClient) -> Iterator[AdminClient]:
    """One admin token per worker process (pytest-xdist runs a session per worker)."""
    client = AdminClient(
        settings.backend_url, auth.login("user", settings.admin_email, settings.admin_password)
    )
    yield client
    client.close()


@pytest.fixture
def faker(request: pytest.FixtureRequest) -> Faker:
    return seeded_faker(request.node.nodeid)


@dataclass(frozen=True)
class TestCustomer:
    profile: Customer
    email: str
    password: str
    token: str
    store: StoreClient


CustomerFactory = Callable[[], TestCustomer]


@pytest.fixture
def make_customer(store: StoreClient, auth: AuthClient, faker: Faker) -> CustomerFactory:
    """Registers fresh customers that belong to the calling test only."""

    def _make() -> TestCustomer:
        email = unique_email("qa-py-customer")
        registration = auth.register_customer(email, TEST_PASSWORD)
        profile = store.as_customer(registration).create_customer(
            email, faker.first_name(), faker.last_name()
        )
        token = auth.login("customer", email, TEST_PASSWORD)
        return TestCustomer(profile, email, TEST_PASSWORD, token, store.as_customer(token))

    return _make


@pytest.fixture
def customer(make_customer: CustomerFactory) -> TestCustomer:
    return make_customer()


PromotionFactory = Callable[..., Promotion]


@pytest.fixture
def make_promotion(admin: AdminClient, settings: Settings) -> Iterator[PromotionFactory]:
    """Creates promotions through the Admin API and deletes them after the test."""
    created: list[str] = []

    def _make(method: str, value: Decimal | int | str, **kwargs: Any) -> Promotion:
        kwargs.setdefault("currency_code", settings.region_currency)
        promotion = admin.create_promotion(kwargs.pop("code", unique_code()), method, value, **kwargs)
        created.append(promotion.id)
        return promotion

    yield _make
    for promotion_id in created:
        admin.delete_promotion(promotion_id)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    JOURNAL.clear()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[None]:
    outcome = yield
    report = outcome.get_result()  # type: ignore[attr-defined]
    if report.when == "call" and report.failed and JOURNAL.items:
        text = "\n\n".join(exchange.render() for exchange in JOURNAL.items)
        allure.attach(
            text, name="HTTP exchanges (last 20, secrets masked)", attachment_type=allure.attachment_type.TEXT
        )
