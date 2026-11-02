# Findings

Defects in Medusa 2.22.2 found by this suite. Each is encoded as a test that asserts the **correct**
behaviour and is marked `xfail(strict=True)` with the finding ID (`pytest.mark.finding`): it passes as
"xfailed" while the defect exists and turns the suite red the moment the defect is fixed, so the mark
is removed deliberately. Tests are never bent to match the current behaviour.

Environment: `shop-sut` (Medusa `@medusajs/*` 2.22.2, dtc-starter `d4e4dae`, production mode,
PostgreSQL 17.11, Redis 7.4.12), Python 3.12.9, httpx 0.28.1. Found 2026-10-31 and 2026-11-01.
BUG-API-007…009 were found by Schemathesis fuzzing (see contract-findings.md); BUG-API-010 by the access matrix.

| ID | Finding | Severity | Priority | Tests |
|---|---|---|---|---|
| BUG-API-001 | Negative `limit`/`offset` on `GET /store/products` → `500 unknown_error` instead of `400 invalid_data` (also reported by the UI suite as BUG-E2E-001) | Minor | Medium | `test_catalog_query_validation[limit-minus-one, offset-minus-one]` |
| BUG-API-002 | `POST /auth/customer/emailpass/register` issues a token for strings that are not e-mails (`plainaddress`, `user@`, `@example.com`, `user name@example.com`) | Minor | Low | `test_registration_rejects_invalid_email[*]` |
| BUG-API-003 | Login or registration without `password` → `401 unauthorized "Password should be a string"` instead of `400 invalid_data` | Trivial | Low | `test_login_with_bad_credentials[missing-password]` |
| BUG-API-004 | `POST` and `DELETE /store/carts/{id}/promotions` on an unknown cart → `500 unknown_error`; every other cart sub-resource answers `404 not_found` | Minor | Medium | `test_unknown_ids[add-/remove-promotion-on-unknown-cart]` |
| BUG-API-005 | Fractional numbers are accepted and silently coerced, differently per field: `limit=1.5` → 1 product (truncated), line item `quantity: 1.5` → **2 units charged** (rounded up) | Minor | Medium | `test_catalog_query_validation[limit-decimal]`, `test_line_item_validation[quantity-decimal]` |
| BUG-API-006 | Cart totals, order totals and payment collection amounts are not rounded to the currency's minor unit: 15 % off 3 × 9.99 + shipping gives a payment of **35.4745 EUR** | Major | High | `test_order_and_payment_amounts_are_in_minor_units` |
| BUG-API-007 | Any query parameter whose name has two or more dots (`?a.b.c=1`) → `500 invalid_argument "Key accessor more than 2 levels deep"` on every Store list endpoint; `?a.b=1` gives a proper 400 | Minor | Medium | `test_catalog_query_validation[unknown-param-two-dots]` |
| BUG-API-008 | Empty or invalid date filter (`?created_at=`, `?updated_at=not-a-date`) → `500 unknown_error` on products, collections, categories, tags, variants | Minor | Medium | `test_catalog_query_validation[created-at-empty, updated-at-not-a-date]` |
| BUG-API-009 | `DELETE /store/carts/{id}/line-items/{unknown}` on a real cart → `200 {"deleted": true}` for an item that never existed | Trivial | Low | `test_deleting_a_line_item_that_does_not_exist_is_404` |
| BUG-API-010 | A customer holding another registered customer's cart ID can take the cart over with `POST /store/carts/{id}/customer` (owner and e-mail change). OWASP API1:2023 BOLA; mitigated by unguessable cart IDs | Minor | Medium | `test_access_matrix[transfer-a-cart[customer_b]]`, `test_cart_owner_does_not_change_when_another_customer_claims_it` |
## Details

### BUG-API-004 — 500 on promotions of an unknown cart

```
POST   /store/carts/cart_does_not_exist/promotions  {"promo_codes":["X"]}  → 500 {"type":"unknown_error"}
DELETE /store/carts/cart_does_not_exist/promotions  {"promo_codes":["X"]}  → 500 {"type":"unknown_error"}
POST   /store/carts/cart_does_not_exist/line-items        → 404 {"type":"not_found","message":"Cart with id ... not found"}
POST   /store/carts/cart_does_not_exist/shipping-methods  → 404 {"type":"not_found","message":"Cart id not found: cart_does_not_exist"}
POST   /store/carts/cart_does_not_exist/complete          → 404 {"type":"not_found"}
```

Expected: `404 not_found` like the sibling endpoints. Impact: an expired cart cookie on the storefront
produces a server error in monitoring instead of a clean "cart not found".

### BUG-API-005 — silent coercion of fractional numbers

```
GET  /store/products?limit=1.5                                  → 200, "limit": 1, one product
POST /store/carts/{id}/line-items {"variant_id":"…","quantity":1.5} → 200, item quantity 2, item_subtotal 25.00 (2 × 12.50)
```

Expected: `400 invalid_data` for a non-integer quantity or page size (the error for `quantity: "two"`
already says the field must be a number; an integer is implied by the domain). Impact: a client bug that
sends a fraction buys more than requested; the two endpoints coerce in opposite directions.

### BUG-API-006 — money is not rounded to minor units

```
cart: 3 × 9.99 EUR, 15 % off order, standard shipping 10.00
GET  /store/carts/{id}                      → discount_total 4.4955, total 35.4745
POST /store/payment-collections             → amount 35.4745
POST /store/carts/{id}/complete             → order.total 35.4745
GET  /admin/orders/{id}                     → summary.pending_difference 35.4745
```

Expected (this project's rounding policy, `docs/pricing-rules.md` §7): every amount that will be charged
is expressed in whole minor units of the currency (EUR cents), so the order's books equal what a card
processor can actually charge. Medusa's documentation does not define where rounding happens.
Impact: with a real payment provider that charges whole cents, captured amounts and order totals can
differ by up to half a cent per order; reconciliation and refunds inherit the difference.  Severity Major because it
concerns money and accounting, even though each difference is tiny.

### BUG-API-010 — cart takeover

```
customer A: POST /store/carts {region}             → cart_a (customer_id = A, email = a@…)
customer B: POST /store/carts/{cart_a}/customer    → 200, cart now customer_id = B, email = b@…   (DB confirms)
```

The route is documented for one case: "you create the cart for a guest customer, then they log in". The
workflow (`transferCartCustomerWorkflow`) transfers whenever the customer differs and offers a `validate`
hook for custom checks, so the default build performs no ownership check. Expected: 403/404 when the cart
already belongs to another registered customer. Severity Minor because the attacker must already know the
cart ID — which, by design, also lets them read and edit the cart.

## Observed, not a defect

- Re-registering an existing e-mail with the **same** password returns a token (one e-mail can hold
  several actor types); with a different password it is refused (`401 "Identity with email already exists"`).
- Completing the same cart twice returns the same order (idempotent).
- `quantity` above available stock → `400 not_allowed "Some variant does not have the required inventory"`.
- Concurrency (5 repeats each, plus 3 observed runs): 10 parallel adds of the same variant →
  8 accepted, 2 answered `409` (the cart lock waits about 2 s), and the cart holds exactly 8 — no lost
  update, same split every run. 5 parallel completions of one cart → all `200` with the same order, one
  row in `order_cart`. Two carts racing for the last item → exactly one order, `reserved ≤ stocked`.
  Clients must retry on `409`; the storefront does not, so a fast double-click can drop an add.
