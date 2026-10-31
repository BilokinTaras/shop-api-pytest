"""Builds the Postman smoke collection (kept as code so the JSON is reproducible and reviewable).

Usage: uv run python postman/build_collection.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
OK = "pm.test('status 200', () => pm.response.to.have.status(200));"


def req(
    name: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    tests: tuple[str, ...] = (),
    prerequest: tuple[str, ...] = (),
    auth: str = "store",
) -> dict[str, Any]:
    headers = [{"key": "x-publishable-api-key", "value": "{{publishable_key}}"}] if auth == "store" else []
    if auth == "admin":
        headers.append({"key": "Authorization", "value": "Bearer {{admin_token}}"})
    if body is not None:
        headers.append({"key": "Content-Type", "value": "application/json"})
    raw_path, _, query = path.partition("?")
    url: dict[str, Any] = {
        "raw": "{{base_url}}" + path,
        "host": ["{{base_url}}"],
        "path": [p for p in raw_path.split("/") if p],
    }
    if query:
        url["query"] = [dict(zip(("key", "value"), q.split("=", 1), strict=True)) for q in query.split("&")]
    item: dict[str, Any] = {
        "name": name,
        "request": {"method": method, "header": headers, "url": url},
        "event": [],
    }
    if body is not None:
        item["request"]["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2)}
    if prerequest:
        item["event"].append(
            {"listen": "prerequest", "script": {"type": "text/javascript", "exec": list(prerequest)}}
        )
    if tests:
        item["event"].append({"listen": "test", "script": {"type": "text/javascript", "exec": list(tests)}})
    return item


ITEMS = [
    req(
        "Admin login",
        "POST",
        "/auth/user/emailpass",
        {"email": "{{admin_email}}", "password": "{{admin_password}}"},
        (
            OK,
            "const t = pm.response.json().token;",
            "pm.test('token is a JWT', () => pm.expect(t.split('.')).to.have.lengthOf(3));",
            "pm.collectionVariables.set('admin_token', t);",
        ),
        auth="none",
    ),
    req(
        "Create 10% promotion (admin)",
        "POST",
        "/admin/promotions",
        {
            "code": "{{promo_code}}",
            "type": "standard",
            "status": "active",
            "is_automatic": False,
            "application_method": {"type": "percentage", "value": 10, "target_type": "order"},
        },
        (OK, "pm.collectionVariables.set('promo_id', pm.response.json().promotion.id);"),
        ("pm.collectionVariables.set('promo_code', 'QA-PM-' + Date.now());",),
        auth="admin",
    ),
    req(
        "Find QA Mug",
        "GET",
        "/store/products?handle=qa-mug&fields=*variants",
        None,
        (
            OK,
            "const p = pm.response.json().products;",
            "pm.test('exactly one product', () => pm.expect(p).to.have.lengthOf(1));",
            "pm.collectionVariables.set('variant_id', p[0].variants[0].id);",
        ),
    ),
    req(
        "Create cart",
        "POST",
        "/store/carts",
        {"region_id": "{{region_id}}"},
        (
            OK,
            "const c = pm.response.json().cart;",
            "pm.test('cart in EUR and empty', () => { pm.expect(c.currency_code).to.eql('eur'); pm.expect(c.items).to.have.lengthOf(0); });",
            "pm.collectionVariables.set('cart_id', c.id);",
        ),
    ),
    req(
        "Add 2 x QA Mug",
        "POST",
        "/store/carts/{{cart_id}}/line-items",
        {"variant_id": "{{variant_id}}", "quantity": 2},
        (
            OK,
            "pm.test('item subtotal 25.00', () => pm.expect(pm.response.json().cart.item_subtotal).to.eql(25));",
        ),
    ),
    req(
        "Apply promotion",
        "POST",
        "/store/carts/{{cart_id}}/promotions",
        {"promo_codes": ["{{promo_code}}"]},
        (
            OK,
            "const c = pm.response.json().cart;",
            "pm.test('10% off: discount 2.50, total 22.50', () => { pm.expect(c.discount_total).to.eql(2.5); pm.expect(c.total).to.eql(22.5); });",
        ),
    ),
    req(
        "Set address and email",
        "POST",
        "/store/carts/{{cart_id}}",
        {
            "email": "postman@example.com",
            "shipping_address": {
                "first_name": "Post",
                "last_name": "Man",
                "address_1": "Street 1",
                "city": "Copenhagen",
                "postal_code": "1000",
                "country_code": "dk",
            },
        },
        (
            OK,
            "pm.test('address stored', () => pm.expect(pm.response.json().cart.shipping_address.country_code).to.eql('dk'));",
        ),
    ),
    req(
        "List shipping options",
        "GET",
        "/store/shipping-options?cart_id={{cart_id}}",
        None,
        (
            OK,
            "const o = pm.response.json().shipping_options.find(x => x.name === 'Standard Shipping');",
            "pm.test('Standard Shipping offered', () => pm.expect(o).to.be.an('object'));",
            "pm.collectionVariables.set('option_id', o.id);",
        ),
    ),
    req(
        "Choose shipping",
        "POST",
        "/store/carts/{{cart_id}}/shipping-methods",
        {"option_id": "{{option_id}}"},
        (
            OK,
            "pm.test('shipping 10.00, total 32.50', () => { const c = pm.response.json().cart; pm.expect(c.shipping_total).to.eql(10); pm.expect(c.total).to.eql(32.5); });",
        ),
    ),
    req(
        "Create payment collection",
        "POST",
        "/store/payment-collections",
        {"cart_id": "{{cart_id}}"},
        (
            OK,
            "pm.collectionVariables.set('payment_collection_id', pm.response.json().payment_collection.id);",
        ),
    ),
    req(
        "Start system payment session",
        "POST",
        "/store/payment-collections/{{payment_collection_id}}/payment-sessions",
        {"provider_id": "pp_system_default"},
        (OK,),
    ),
    req(
        "Complete cart",
        "POST",
        "/store/carts/{{cart_id}}/complete",
        None,
        (
            OK,
            "const r = pm.response.json();",
            "pm.test('an order was created', () => pm.expect(r.type).to.eql('order'));",
            "pm.test('order total 32.50', () => pm.expect(r.order.total).to.eql(32.5));",
            "pm.collectionVariables.set('order_id', r.order.id);",
        ),
    ),
    req(
        "Admin sees the order",
        "GET",
        "/admin/orders/{{order_id}}?fields=%2Bemail",
        None,
        (
            OK,
            "pm.test('same e-mail and total', () => { const o = pm.response.json().order; pm.expect(o.email).to.eql('postman@example.com'); pm.expect(o.total).to.eql(32.5); });",
        ),
        auth="admin",
    ),
    req(
        "Clean up the promotion",
        "DELETE",
        "/admin/promotions/{{promo_id}}",
        None,
        (OK, "pm.test('deleted', () => pm.expect(pm.response.json().deleted).to.eql(true));"),
        auth="admin",
    ),
]

VARIABLES = [
    "admin_token",
    "promo_code",
    "promo_id",
    "variant_id",
    "cart_id",
    "option_id",
    "payment_collection_id",
    "order_id",
]


def main() -> None:
    collection = {
        "info": {
            "name": "shop-api smoke: products -> cart -> promotion -> order",
            "description": "Smoke flow for the Medusa stand (shop-sut). Values come from the environment; nothing secret is stored here.",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": ITEMS,
        "variable": [{"key": k, "value": ""} for k in VARIABLES],
    }
    (HERE / "shop-smoke.postman_collection.json").write_text(
        json.dumps(collection, indent=2) + "\n", encoding="utf-8"
    )
    environment = {
        "name": "shop-sut (local)",
        "values": [
            {"key": "base_url", "value": "http://localhost:9000", "enabled": True},
            {
                "key": "publishable_key",
                "value": "<SUT_PUBLISHABLE_KEY from ../shop-sut/.generated/sut.env>",
                "enabled": True,
            },
            {"key": "region_id", "value": "<SUT_REGION_ID>", "enabled": True},
            {"key": "admin_email", "value": "<SUT_ADMIN_EMAIL>", "enabled": True},
            {"key": "admin_password", "value": "<SUT_ADMIN_PASSWORD>", "type": "secret", "enabled": True},
        ],
    }
    (HERE / "shop.postman_environment.template.json").write_text(
        json.dumps(environment, indent=2) + "\n", encoding="utf-8"
    )
    print(f"postman: {len(ITEMS)} requests written")


if __name__ == "__main__":
    main()
