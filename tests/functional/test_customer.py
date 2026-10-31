"""Customer journey: registration → profile → update → addresses CRUD."""

from __future__ import annotations

import allure
import pytest
from faker import Faker

from shop_api.factories import address
from tests.conftest import CustomerSession

pytestmark = [pytest.mark.functional, allure.epic("Store API"), allure.feature("Customer")]


@allure.story("Registration")
def test_registered_customer_reads_own_profile(customer: CustomerSession) -> None:
    me = customer.store.me()
    assert me.id == customer.profile.id
    assert me.email == customer.email
    assert me.has_account is True


@allure.story("Profile update")
def test_profile_fields_can_be_updated(customer: CustomerSession) -> None:
    updated = customer.store.update_me(first_name="Ada", last_name="Lovelace", phone="+4512345678")
    assert (updated.first_name, updated.last_name) == ("Ada", "Lovelace")
    assert customer.store.me().model_dump().get("phone") == "+4512345678"


@allure.story("Addresses")
def test_address_create_update_delete(customer: CustomerSession, faker: Faker) -> None:
    store = customer.store
    with allure.step("create"):
        created = store.request("POST", "/store/customers/me/addresses", json=address(faker, "dk"))
        assert created.status_code == 200, created.text
        addresses = created.json()["customer"]["addresses"]
        assert len(addresses) == 1
        address_id = addresses[0]["id"]
    with allure.step("update city"):
        updated = store.request(
            "POST", f"/store/customers/me/addresses/{address_id}", json={"city": "Aarhus"}
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["customer"]["addresses"][0]["city"] == "Aarhus"
    with allure.step("list"):
        listed = store.request("GET", "/store/customers/me/addresses")
        assert [a["id"] for a in listed.json()["addresses"]] == [address_id]
    with allure.step("delete"):
        deleted = store.request("DELETE", f"/store/customers/me/addresses/{address_id}")
        assert deleted.status_code == 200, deleted.text
        assert store.request("GET", "/store/customers/me/addresses").json()["addresses"] == []


@allure.story("Addresses")
def test_customer_cannot_touch_another_customers_address(
    customer: CustomerSession, make_customer: object, faker: Faker
) -> None:
    other = make_customer()  # type: ignore[operator]
    created = other.store.request("POST", "/store/customers/me/addresses", json=address(faker, "dk"))
    other_address = created.json()["customer"]["addresses"][0]["id"]
    response = customer.store.request("DELETE", f"/store/customers/me/addresses/{other_address}")
    assert response.status_code in {401, 403, 404}, response.text
    assert other.store.request("GET", "/store/customers/me/addresses").json()["count"] == 1
