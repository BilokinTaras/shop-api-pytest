"""Typed clients for the Medusa Store, Auth and Admin APIs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

from shop_api.clients.base import BaseClient
from shop_api.models import (
    Cart,
    CartResponse,
    CompletedCartError,
    CompletedOrder,
    Customer,
    CustomerResponse,
    DeleteResponse,
    Order,
    OrderList,
    OrderResponse,
    PaymentCollectionResponse,
    Product,
    ProductList,
    Promotion,
    PromotionResponse,
    RegionList,
    ShippingOption,
    ShippingOptionList,
    Token,
)


class StoreClient(BaseClient):
    """Store API. Every request carries the publishable key; ``as_customer`` adds a bearer token."""

    def __init__(self, base_url: str, publishable_key: str) -> None:
        super().__init__(base_url, {"x-publishable-api-key": publishable_key})

    def as_customer(self, token: str) -> StoreClient:
        return self.with_headers(authorization=f"Bearer {token}")

    def list_products(self, **params: Any) -> ProductList:
        return self.call(ProductList, "GET", "/store/products", params=params)

    def product_by_handle(self, handle: str, region_id: str) -> Product:
        page = self.list_products(
            handle=handle,
            region_id=region_id,
            fields="*variants.calculated_price,+variants.inventory_quantity",
        )
        if not page.products:
            raise LookupError(f"product {handle!r} not found")
        return page.products[0]

    def first_variant_id(self, handle: str, region_id: str) -> str:
        variants = self.product_by_handle(handle, region_id).variants or []
        return variants[0].id

    def list_regions(self) -> RegionList:
        return self.call(RegionList, "GET", "/store/regions")

    def create_cart(self, region_id: str, **extra: Any) -> Cart:
        return self.call(CartResponse, "POST", "/store/carts", json={"region_id": region_id, **extra}).cart

    def get_cart(self, cart_id: str) -> Cart:
        return self.call(CartResponse, "GET", f"/store/carts/{cart_id}").cart

    def update_cart(self, cart_id: str, **data: Any) -> Cart:
        return self.call(CartResponse, "POST", f"/store/carts/{cart_id}", json=data).cart

    def add_item(self, cart_id: str, variant_id: str, quantity: int) -> Cart:
        return self.call(
            CartResponse,
            "POST",
            f"/store/carts/{cart_id}/line-items",
            json={"variant_id": variant_id, "quantity": quantity},
        ).cart

    def update_item(self, cart_id: str, line_id: str, quantity: int) -> Cart:
        return self.call(
            CartResponse, "POST", f"/store/carts/{cart_id}/line-items/{line_id}", json={"quantity": quantity}
        ).cart

    def apply_promotions(self, cart_id: str, codes: list[str]) -> Cart:
        return self.call(
            CartResponse, "POST", f"/store/carts/{cart_id}/promotions", json={"promo_codes": codes}
        ).cart

    def remove_promotions(self, cart_id: str, codes: list[str]) -> Cart:
        return self.call(
            CartResponse, "DELETE", f"/store/carts/{cart_id}/promotions", json={"promo_codes": codes}
        ).cart

    def shipping_options(self, cart_id: str) -> list[ShippingOption]:
        return self.call(
            ShippingOptionList, "GET", "/store/shipping-options", params={"cart_id": cart_id}
        ).shipping_options

    def add_shipping_method(self, cart_id: str, option_id: str) -> Cart:
        return self.call(
            CartResponse, "POST", f"/store/carts/{cart_id}/shipping-methods", json={"option_id": option_id}
        ).cart

    def init_system_payment(self, cart_id: str) -> str:
        collection = self.call(
            PaymentCollectionResponse, "POST", "/store/payment-collections", json={"cart_id": cart_id}
        ).payment_collection
        self.request(
            "POST",
            f"/store/payment-collections/{collection.id}/payment-sessions",
            json={"provider_id": "pp_system_default"},
        )
        return collection.id

    def complete_cart(self, cart_id: str) -> CompletedOrder | CompletedCartError:
        response = self.request("POST", f"/store/carts/{cart_id}/complete")
        body = response.json()
        if body.get("type") == "order":
            return CompletedOrder.model_validate(body)
        return CompletedCartError.model_validate(body)

    def prepare_checkout(self, cart_id: str, address: dict[str, str], email: str) -> Cart:
        """Address, first shipping option and system payment: a cart ready to complete."""
        self.update_cart(cart_id, email=email, shipping_address=address)
        option = self.shipping_options(cart_id)[0]
        self.add_shipping_method(cart_id, option.id)
        self.init_system_payment(cart_id)
        return self.get_cart(cart_id)

    def me(self) -> Customer:
        return self.call(CustomerResponse, "GET", "/store/customers/me").customer

    def create_customer(self, email: str, first_name: str, last_name: str) -> Customer:
        return self.call(
            CustomerResponse,
            "POST",
            "/store/customers",
            json={"email": email, "first_name": first_name, "last_name": last_name},
        ).customer

    def update_me(self, **data: Any) -> Customer:
        return self.call(CustomerResponse, "POST", "/store/customers/me", json=data).customer

    def list_orders(self) -> OrderList:
        return self.call(OrderList, "GET", "/store/orders")

    def get_order(self, order_id: str) -> Order:
        return self.call(OrderResponse, "GET", f"/store/orders/{order_id}").order


class AuthClient(BaseClient):
    def login(self, actor: str, email: str, password: str) -> str:
        return self.call(
            Token, "POST", f"/auth/{actor}/emailpass", json={"email": email, "password": password}
        ).token

    def register_customer(self, email: str, password: str) -> str:
        return self.call(
            Token, "POST", "/auth/customer/emailpass/register", json={"email": email, "password": password}
        ).token


class AdminClient(BaseClient):
    def __init__(self, base_url: str, token: str) -> None:
        super().__init__(base_url, {"authorization": f"Bearer {token}"})

    def create_promotion(
        self,
        code: str,
        method: str,
        value: Decimal | int | str,
        *,
        target_type: str = "order",
        allocation: str | None = None,
        currency_code: str | None = None,
        rules: list[dict[str, Any]] | None = None,
        target_rules: list[dict[str, Any]] | None = None,
        buy_rules: list[dict[str, Any]] | None = None,
        apply_to_quantity: int | None = None,
        buy_rules_min_quantity: int | None = None,
        promotion_type: str = "standard",
        is_automatic: bool = False,
        is_tax_inclusive: bool | None = None,
    ) -> Promotion:
        application_method: dict[str, Any] = {"type": method, "value": str(value), "target_type": target_type}
        optional = {
            "allocation": allocation,
            "currency_code": currency_code,
            "target_rules": target_rules,
            "buy_rules": buy_rules,
            "apply_to_quantity": apply_to_quantity,
            "buy_rules_min_quantity": buy_rules_min_quantity,
        }
        application_method.update({k: v for k, v in optional.items() if v is not None})
        payload: dict[str, Any] = {
            "code": code,
            "type": promotion_type,
            "status": "active",
            "is_automatic": is_automatic,
            "application_method": application_method,
        }
        if rules:
            payload["rules"] = rules
        if is_tax_inclusive is not None:
            payload["is_tax_inclusive"] = is_tax_inclusive
        return self.call(PromotionResponse, "POST", "/admin/promotions", json=payload).promotion

    def delete_promotion(self, promotion_id: str) -> httpx.Response:
        return self.request("DELETE", f"/admin/promotions/{promotion_id}")

    def get_order(self, order_id: str) -> Order:
        return self.call(
            OrderResponse,
            "GET",
            f"/admin/orders/{order_id}",
            params={"fields": "+email,+currency_code,*items"},
        ).order

    def delete(self, path: str) -> DeleteResponse:
        return self.call(DeleteResponse, "DELETE", path)
