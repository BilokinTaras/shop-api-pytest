"""Smoke: the stand is up and the framework is wired correctly (clients, models, auth)."""

from __future__ import annotations

import allure
import pytest

from shop_api.clients import AuthClient, StoreClient
from shop_api.config import Settings

pytestmark = [pytest.mark.smoke, allure.epic("Store API"), allure.feature("Smoke")]


@allure.severity(allure.severity_level.BLOCKER)
def test_health_endpoint_answers_ok(store: StoreClient) -> None:
    response = store.request("GET", "/health")
    assert response.status_code == 200
    assert response.text == "OK"


@allure.severity(allure.severity_level.BLOCKER)
def test_catalog_lists_qa_products_through_the_model(store: StoreClient) -> None:
    page = store.list_products(limit=50, fields="id,handle,title")
    assert {"qa-tee", "qa-mug", "qa-sold-out"} <= {p.handle for p in page.products}


@allure.severity(allure.severity_level.CRITICAL)
def test_regions_match_the_contract(store: StoreClient, settings: Settings) -> None:
    regions = {r.id: r for r in store.list_regions().regions}
    assert regions[settings.region_id].currency_code == settings.region_currency
    assert regions[settings.region_usd_id].currency_code == "usd"


@allure.severity(allure.severity_level.CRITICAL)
def test_admin_can_log_in(auth: AuthClient, settings: Settings) -> None:
    token = auth.login("user", settings.admin_email, settings.admin_password)
    assert token.count(".") == 2
