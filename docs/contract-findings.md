# Contract testing and fuzzing — findings

Specification: the official OpenAPI files of Medusa at tag **v2.22.2** (`www/apps/api-reference/specs/`),
stored in `contracts/openapi/` with their SHA-256 (see `contracts/README.md`). Tool: Schemathesis 4.32.7,
all checks, 20 examples per operation, deterministic generation, 4 workers, against the local stand.

| Run | Scope | Operations | Test cases | Unique failures found |
|---|---|---:|---:|---:|
| `store` | Store API, all `GET` operations | 33 | 914 (seeded run) | 163 (seeded) → 193 after the deterministic runs were merged |
| `store-carts` | Store API, every operation under `/store/carts` | 15 | 305 | 42 → 60 after merging stateful-phase variants |

Every failure was triaged into one of four classes and recorded in a Schemathesis **baseline**
(`contracts/schemathesis-baseline.*.json`). With the baseline the runs are green and stay green unless a
**new** failure appears — that is the regression gate. The table at the end is generated from the
baselines by `scripts/contract_triage.py`, so no failure can stay unclassified.

## Product defects found by fuzzing (5xx)

All reproduced by hand with minimal requests and added to the regular suite as strict xfails.

| ID | Minimal reproduction | Result | Expected |
|---|---|---|---|
| BUG-API-001 (widened) | `GET /store/{products,regions,currencies,return-reasons,payment-providers}?offset=-1` (or `limit=-1`) | 500 `unknown_error` | 400 `invalid_data` |
| BUG-API-007 (new) | `GET /store/products?a.b.c=1` (any list endpoint, any parameter name with two dots) | 500 `invalid_argument "Key accessor more than 2 levels deep"` | 400 — `?a.b=1` and `?x=1` already give 400 `Unrecognized fields` |
| BUG-API-008 (new) | `GET /store/products?created_at=` or `?updated_at=not-a-date` (also collections, product-categories, product-tags, product-variants) | 500 `unknown_error` | 400 `invalid_data` |
| BUG-API-004 (widened) | `POST`/`DELETE /store/carts/cart_x/promotions`, `DELETE /store/carts/cart_x/line-items/cali_x` | 500 `unknown_error` | 404 like the other cart sub-resources |
| BUG-API-009 (new) | `DELETE /store/carts/{real cart}/line-items/cali_does_not_exist` | 200 `{"id":"cali_does_not_exist","deleted":true}` | 404 — the API reports deleting an item that never existed |

## Specification defects (the API is right, the spec is wrong or incomplete)

| ID | Problem | Example |
|---|---|---|
| SPEC-0 | The spec at tag v2.22.2 declares `info.version: 2.21.2` | header of `store.openapi.yaml` |
| SPEC-1 | Properties that are `null` in real responses are not marked `nullable` | `metadata`, `description`, `weight`, `height`, `length`, `parent_category`, option value `rank`, variant `sku` |
| SPEC-2 | Properties marked `required` are not always returned | `created_at` on currencies, `name` on regions/categories, `id` on region countries; many disappear legitimately when the client narrows `fields` |
| SPEC-4 | Documented input is rejected with 400 | an empty `locale` query parameter (`locale=` → "Unrecognized fields: 'locale'"; `locale=en` is accepted), filter operator objects (`$eq`, `$gt`, … "Unrecognized fields"), empty `order`, `region_id` documented as optional for `/store/payment-providers` but required |
| SPEC-5 | API accepts what the schema forbids | `POST /store/carts {"additional_data": null}` → 200 |
| SPEC-6 | Documented endpoints are not present in this build | `/store/gift-cards/{idOrCode}`, `/store/store-credit-accounts`, `/store/locales` → 404 HTML (modules not installed in the starter) |
| SPEC-7 | 401 responses are documented as `text/plain`, the API returns JSON | `GET /store/customers/me` without a token |

## Accepted behaviour and false positives

| ID | Why it is not a defect here |
|---|---|
| ACC-1 | `TRACE`/undeclared methods get Express's 404 HTML instead of 405. RFC 9110 prefers 405 when the resource exists, but this is framework behaviour with no user impact; noted, not filed. |
| FP-1 | A generated multi-kilobyte header is rejected by Node's HTTP parser with 431 before Medusa sees it. Infrastructure limit, not an API contract. |

## Limitation: the baselines depend on data

Schemathesis reuses real IDs it discovers (products, options, carts). Test runs create and delete such
data, so after the shared data changes a contract run can surface the **same** known defect on a new
operation/ID pair (observed once on 2026-11-01: SPEC-1 and SPEC-4 on `GET /store/product-options/{id}`).
The procedure is: `make contract-update`, then confirm that `scripts/contract_triage.py` still reports
**Unclassified: 0** — anything unclassified is a genuinely new failure and is investigated before merging.

The first nightly CI run (2026-11-02), on a freshly bootstrapped stand, hit exactly this: two failures outside
the baseline, both instances of known classes — FP-1 (`431` on a multi-kilobyte query to
`GET /store/collections`) and SPEC-4 (`locale` rejected with 400 on `GET /store/orders/{id}`, an operation the
local runs never got past 404 on). Each was read and classified by hand before it was added, and the triage
script agrees. The suite itself in that run: 218 passed, 19 expected failures, the same as locally.

The second nightly found a third: SPEC-4 on `GET /store/carts/{id}`, with `locale=` empty. Reproducing it by
hand showed the trigger is the **empty** value — `locale=en` is accepted — and that it is not specific to
one route. Rather than add one operation per night, `scripts/probe_empty_locale.py` calls every operation in
the scope of `make contract` once with `locale=` and adds the ones that reject it (2026-11-02, v1.0.0 images:
23 in the GET run, 6 in the carts run, of which 5 were new). The 17 it reports as unreachable answer 401
without a customer token, 404 HTML (module not installed) or a body validation error first, so the fuzzer
cannot produce this failure on them; the write operations among them are already in the baseline under
SPEC-4 for other inputs.

## How to run

```bash
make contract          # both runs against the baselines (green unless something new appears)
make contract-update   # merge new failures into the baselines — only after triaging them here
uv run python scripts/contract_triage.py   # regenerate the table below
uv run python scripts/probe_empty_locale.py --update-baselines   # SPEC-4 (empty locale) on every operation in scope
```

## Triage of every accepted failure (generated)

<!-- generated: triage table -->

Accepted failures: **265** across 2 runs (store, store-carts). Unclassified: **0**.

| Category | Triage | Failures | Operations |
|---|---|---:|---|
| Accepted behaviour | ACC-1: undeclared HTTP methods get 404 from Express instead of 405 | 19 | `GET /auth/customer/providers`, `GET /auth/mfa/factors`, `GET /store/collections`, `GET /store/currencies`, `GET /store/locales`, `GET /store/orders` and 12 more |
| False positive | FP-1: oversized generated header rejected by Node's parser (431) before Medusa | 2 | `GET /store/collections`, `GET /store/store-credit-accounts` |
| Product defect (5xx) | BUG-API-001 / 004 / 007 / 008 — see the reproduction table | 14 | `DELETE /store/carts/{id}/line-items/{line_id}`, `DELETE /store/carts/{id}/promotions`, `GET /store/collections`, `GET /store/currencies`, `GET /store/payment-providers`, `GET /store/product-categories` and 8 more |
| Spec defect | SPEC-1: nullable property not marked `nullable` | 150 | `DELETE /store/carts/{id}/line-items/{line_id}`, `DELETE /store/carts/{id}/promotions`, `GET /store/carts/{id}`, `GET /store/collections`, `GET /store/collections/{id}`, `GET /store/currencies` and 12 more |
| Spec defect | SPEC-4: documented input rejected by the API | 34 | `DELETE /store/carts/{id}/line-items/{line_id}`, `DELETE /store/carts/{id}/promotions`, `GET /store/carts/{id}`, `GET /store/collections`, `GET /store/collections/{id}`, `GET /store/currencies` and 27 more |
| Spec defect | SPEC-2: property marked required is not always returned | 32 | `DELETE /store/carts/{id}/line-items/{line_id}`, `DELETE /store/carts/{id}/promotions`, `GET /store/carts/{id}`, `GET /store/collections`, `GET /store/collections/{id}`, `GET /store/currencies` and 14 more |
| Spec defect | SPEC-6: documented endpoint not present in this build (404 HTML) | 7 | `DELETE /store/carts/{id}/gift-cards`, `GET /store/gift-cards/{idOrCode}`, `GET /store/locales`, `GET /store/store-credit-accounts`, `GET /store/store-credit-accounts/{id}`, `POST /store/carts/{id}/gift-cards` and 1 more |
| Spec defect | SPEC-7: 401 documented as text/plain, API returns JSON | 6 | `GET /auth/mfa/factors`, `GET /store/customers/me`, `GET /store/customers/me/addresses`, `GET /store/customers/me/addresses/{address_id}`, `GET /store/orders`, `POST /store/carts/{id}/customer` |
| Spec defect | SPEC-5: API accepts input the schema forbids (e.g. `null` objects) | 1 | `POST /store/carts` |
