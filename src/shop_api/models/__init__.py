"""Pydantic models of the Medusa 2.22 responses the tests rely on.

Written from real responses of the pinned version. Unknown fields are allowed (``extra="allow"``);
the fields tests use are typed and required. Money is ``Decimal``: Medusa returns amounts as JSON
numbers in major units (25 = EUR 25.00), and comparing them as floats would hide rounding errors.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class MedusaError(Loose):
    type: str | None = None
    message: str = Field(min_length=1)
    code: str | None = None


class CalculatedPrice(Loose):
    calculated_amount: Decimal
    original_amount: Decimal
    currency_code: str
    is_calculated_price_tax_inclusive: bool


class Variant(Loose):
    id: str = Field(pattern=r"^variant_")
    title: str
    sku: str | None = None
    manage_inventory: bool | None = None
    allow_backorder: bool | None = None
    inventory_quantity: int | None = None
    calculated_price: CalculatedPrice | None = None


class Product(Loose):
    id: str = Field(pattern=r"^prod_")
    title: str
    handle: str
    description: str | None = None
    thumbnail: str | None = None
    variants: list[Variant] | None = None


class ProductList(BaseModel):
    products: list[Product]
    count: int = Field(ge=0)
    limit: int = Field(ge=0)
    offset: int = Field(ge=0)


class Country(Loose):
    iso_2: str


class Region(Loose):
    id: str = Field(pattern=r"^reg_")
    name: str
    currency_code: str
    countries: list[Country] | None = None


class RegionList(Loose):
    regions: list[Region]
    count: int


class RegionResponse(BaseModel):
    region: Region


class Adjustment(Loose):
    code: str | None = None
    promotion_id: str | None = None
    amount: Decimal


class LineItem(Loose):
    id: str = Field(pattern=r"^cali_")
    variant_id: str | None
    quantity: int = Field(gt=0)
    unit_price: Decimal
    adjustments: list[Adjustment] | None = None


class CartPromotion(Loose):
    id: str
    code: str | None = None


class ShippingMethod(Loose):
    id: str
    amount: Decimal


class Cart(Loose):
    id: str = Field(pattern=r"^cart_")
    region_id: str | None
    currency_code: str
    email: str | None
    completed_at: str | None = None
    items: list[LineItem]
    shipping_methods: list[ShippingMethod] | None = None
    promotions: list[CartPromotion] | None = None
    item_subtotal: Decimal
    item_total: Decimal
    item_tax_total: Decimal
    discount_total: Decimal
    shipping_subtotal: Decimal
    shipping_total: Decimal
    tax_total: Decimal
    original_total: Decimal
    subtotal: Decimal
    total: Decimal


class CartResponse(BaseModel):
    cart: Cart


class ShippingOption(Loose):
    id: str = Field(pattern=r"^so_")
    name: str
    amount: Decimal | None = None


class ShippingOptionList(BaseModel):
    shipping_options: list[ShippingOption]


class PaymentCollection(Loose):
    id: str = Field(pattern=r"^pay_col_")


class PaymentCollectionResponse(BaseModel):
    payment_collection: PaymentCollection


class OrderItem(Loose):
    variant_id: str | None = None
    quantity: Decimal
    unit_price: Decimal


class Order(Loose):
    id: str = Field(pattern=r"^order_")
    display_id: int = Field(gt=0)
    status: str
    email: str | None = None
    currency_code: str | None = None
    items: list[OrderItem] | None = None
    item_total: Decimal
    discount_total: Decimal
    shipping_total: Decimal
    tax_total: Decimal
    total: Decimal


class OrderResponse(BaseModel):
    order: Order


class CompletedOrder(BaseModel):
    type: Literal["order"]
    order: Order


class CompletedCartError(BaseModel):
    type: Literal["cart"]
    cart: Cart
    error: Loose


class OrderSummary(Loose):
    """Order as returned by list endpoints: the default fields there omit most totals."""

    id: str = Field(pattern=r"^order_")
    display_id: int = Field(gt=0)
    status: str
    total: Decimal


class OrderList(Loose):
    orders: list[OrderSummary]
    count: int


class Customer(Loose):
    id: str = Field(pattern=r"^cus_")
    email: str
    first_name: str | None = None
    last_name: str | None = None
    has_account: bool
    addresses: list[Loose] | None = None


class CustomerResponse(BaseModel):
    customer: Customer


class Token(BaseModel):
    token: str = Field(pattern=r"^[\w-]+\.[\w-]+\.[\w-]+$")


class ApplicationMethod(Loose):
    type: str
    value: Decimal
    target_type: str | None = None
    allocation: str | None = None


class Promotion(Loose):
    id: str = Field(pattern=r"^promo_")
    code: str
    status: str
    is_automatic: bool
    application_method: ApplicationMethod


class PromotionResponse(BaseModel):
    promotion: Promotion


class DeleteResponse(Loose):
    id: str
    deleted: Literal[True]
