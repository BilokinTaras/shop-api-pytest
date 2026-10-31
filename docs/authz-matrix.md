# Access matrix

Generated from `data/authz/matrix.yaml` by `scripts/authz_matrix_doc.py`; the same file drives
`tests/authz/test_access_matrix.py` (58 cases). Resources marked `_a` belong to customer A and are
created for every case (or once per worker for read-only operations).

Legend: ✅ allowed · ⛔ denied as expected · 🔑 allowed by design (the ID works as a capability, documented
by Medusa) · 🐞 defect — the cell shows the correct outcome, the test is a strict xfail · — not tested.

| Operation | anonymous | customer_a | customer_b | admin |
|---|---|---|---|---|
| `GET /store/products?limit=1&fields=id` | ✅ 200 | ✅ 200 | ✅ 200 | ✅ 200 |
| `GET /store/customers/me` | ⛔ 401 | ✅ 200 | ✅ 200 | ⛔ 401 |
| `GET /store/customers/me/addresses/{address_a}` | ⛔ 401 | ✅ 200 | ⛔ 404 | ⛔ 401 |
| `POST /store/customers/me/addresses/{address_a}` | ⛔ 401 | ✅ 200 | ⛔ 404 | ⛔ 401 |
| `DELETE /store/customers/me/addresses/{address_a}` | ⛔ 401 | ✅ 200 | ⛔ 404 | ⛔ 401 |
| `GET /store/orders` | ⛔ 401 | ✅ 200 | ✅ 200 | ⛔ 401 |
| `GET /store/orders/{order_a}` | 🔑 200 | ✅ 200 | 🔑 200 | 🔑 200 |
| `GET /store/carts/{cart_a}` | 🔑 200 | ✅ 200 | 🔑 200 | 🔑 200 |
| `POST /store/carts/{cart_a}/line-items` | 🔑 200 | ✅ 200 | 🔑 200 | 🔑 200 |
| `POST /store/carts/{cart_a}/customer` | ⛔ 401 | ✅ 200 | 🐞 expect 404 (BUG-API-010) | ⛔ 401 |
| `POST /store/orders/{order_a}/transfer/request` | ⛔ 401 | — | 🔑 200 | ⛔ 401 |
| `GET /admin/orders/{order_a}` | ⛔ 401 | ⛔ 401 | ⛔ 401 | ✅ 200 |
| `GET /admin/customers?limit=1` | ⛔ 401 | ⛔ 401 | ⛔ 401 | ✅ 200 |
| `DELETE /admin/promotions/{promotion}` | ⛔ 401 | ⛔ 401 | ⛔ 401 | ✅ 200 |
| `POST /admin/products` | ⛔ 401 | ⛔ 401 | ⛔ 401 | — |

## Notes

- **read-own-profile** — customer_b gets their OWN profile — `me` is always the caller
- **read-a-order-by-id** — Documented: 'doesn't require customer authentication, so that guest customers can view their order confirmation page'. The order ID (ULID) is the capability; it exposes e-mail and address to anyone holding it.
- **read-a-cart** — Carts are addressed by ID without authentication (guest checkout); the cart ID is the capability.
- **transfer-a-cart** — Documented use: move a guest cart to the customer who just logged in. A cart that already belongs to another registered customer should not be taken over.
- **request-a-order-transfer** — Creates a transfer request that the current owner must accept with a token sent by e-mail; nothing changes hands yet.
- **admin-create-product** — Admin creation is covered elsewhere; here only the denials matter.

## Design risks (not filed as defects)

- Orders and carts are readable and editable by anyone who holds their ID. Medusa documents this for guest
  checkout; the IDs are ULIDs with 80 random bits, so they cannot be guessed, but they must be treated as
  secrets: they appear in URLs (order confirmation page) and can leak through logs, referrers or support
  screenshots. An order ID exposes the customer's e-mail and shipping address.
- Mitigation options for a real shop: require a second factor (e-mail) for guest order lookup, shorten
  cart lifetime, and use Medusa's `validate` workflow hooks to enforce cart ownership.
