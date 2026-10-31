"""Auth and profile negative cases from data/negative/auth.yaml, plus forged and expired tokens."""

from __future__ import annotations

import os
import time
from typing import Any

import allure
import httpx
import pytest

from shop_api import jwt
from shop_api.clients import AuthClient, StoreClient
from shop_api.config import DEFAULT_ENV_FILE
from shop_api.data import cases
from shop_api.factories import TEST_PASSWORD, unique_email
from shop_api.models import MedusaError
from tests.conftest import CustomerSession

pytestmark = [pytest.mark.negative, allure.epic("Auth"), allure.feature("Authentication")]
TABLE = "negative/auth.yaml"


@allure.story("Registration rejects invalid e-mails")
@pytest.mark.parametrize("case", cases(TABLE, "registration_email"))
def test_registration_rejects_invalid_email(auth: AuthClient, case: dict[str, Any]) -> None:
    # Unique per run so a previous run's identity does not turn this into "already exists".
    email = (
        case["email"].replace("@", f"{os.getpid()}{time.time_ns()}@", 1)
        if "@" in case["email"]
        else (f"{case['email']}{time.time_ns()}")
    )
    response = auth.request(
        "POST", "/auth/customer/emailpass/register", json={"email": email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 400, response.text
    assert MedusaError.model_validate(response.json()).type == "invalid_data"


@allure.story("Customer profile rejects invalid e-mails")
@pytest.mark.parametrize("case", cases(TABLE, "profile_email"))
def test_profile_rejects_invalid_email(auth: AuthClient, store: StoreClient, case: dict[str, Any]) -> None:
    token = auth.register_customer(unique_email(), TEST_PASSWORD)
    response = store.as_customer(token).request(
        "POST", "/store/customers", json={"email": case["email"], "first_name": "A", "last_name": "B"}
    )
    assert response.status_code == 400, response.text
    error = MedusaError.model_validate(response.json())
    assert error.type == "invalid_data"
    assert "email" in error.message.lower()


@allure.story("Login with bad credentials")
@pytest.mark.parametrize("case", cases(TABLE, "login"))
def test_login_with_bad_credentials(
    auth: AuthClient, customer: CustomerSession, case: dict[str, Any]
) -> None:
    body: dict[str, str] = {
        "wrong_password": {"email": customer.email, "password": "wrong-password"},
        "unknown_email": {"email": unique_email("nobody"), "password": TEST_PASSWORD},
        "empty_password": {"email": customer.email, "password": ""},
        "missing_password": {"email": customer.email},
    }[case["kind"]]
    response = auth.request("POST", "/auth/customer/emailpass", json=body)
    assert response.status_code == case["status"], response.text
    error = MedusaError.model_validate(response.json())
    assert error.type == case["type"]
    if "message" in case:
        assert case["message"] in error.message


@pytest.fixture
def jwt_secret() -> str:
    secret = os.environ.get("SUT_JWT_SECRET") or ""
    if not secret:
        for line in DEFAULT_ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("SUT_JWT_SECRET="):
                secret = line.split("=", 1)[1]
    assert secret, "SUT_JWT_SECRET missing from the contract file; re-run make -C ../shop-sut bootstrap"
    return secret


@allure.story("Forged and expired tokens are rejected")
@pytest.mark.parametrize("case", cases(TABLE, "tokens"))
def test_profile_rejects_bad_tokens(
    store: StoreClient, customer: CustomerSession, jwt_secret: str, case: dict[str, Any]
) -> None:
    _, payload = jwt.decode_unverified(customer.token)
    token = {
        "none": None,
        "garbage": "abc.def.ghi",
        "expired": jwt.sign(
            {**payload, "iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600}, jwt_secret
        ),
        "wrong_signature": jwt.sign(payload, "not-the-server-secret"),
        "alg_none": jwt.unsigned(payload),
    }[case["token"]]
    client = store if token is None else store.as_customer(token)
    response = client.request("GET", "/store/customers/me")
    assert response.status_code == 401, response.text


@allure.story("Forged tokens are rejected")
def test_resigned_valid_token_is_accepted_control(
    store: StoreClient, customer: CustomerSession, jwt_secret: str
) -> None:
    """Control for the token tests: the same payload signed with the real secret works, so the
    rejections above are caused by expiry or signature, not by a broken helper."""
    _, payload = jwt.decode_unverified(customer.token)
    response = store.as_customer(jwt.sign(payload, jwt_secret)).request("GET", "/store/customers/me")
    assert response.status_code == 200, response.text


@allure.feature("Authorization")
@allure.story("Customer token on admin routes")
@pytest.mark.parametrize(
    "path", ["/admin/products", "/admin/orders", "/admin/customers", "/admin/promotions"]
)
def test_customer_token_cannot_use_admin_routes(
    store: StoreClient, customer: CustomerSession, path: str
) -> None:
    response = httpx.get(
        f"{store.base_url}{path}", headers={"authorization": f"Bearer {customer.token}"}, timeout=15
    )
    assert response.status_code == 401, response.text
