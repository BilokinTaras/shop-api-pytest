# Test strategy — shop-api-pytest (API level)

System under test: Medusa 2.22.2 Store and Admin REST APIs on the local `shop-sut` stand.
This repository is the **deep API layer** of the portfolio. UI journeys and API-in-scenario checks live in
`shop-e2e-playwright`; security scanning in `devsecops-quality-gates`; load in `shop-performance-k6`.

## 1. What is tested here and why

| Suite (marker) | Cases | Risk it addresses | Technique |
|---|---:|---|---|
| `unit` — the pricing oracle itself | 22 | A wrong oracle would bless wrong prices | Documented examples, Hypothesis properties |
| `smoke` | 4 | Stand down, framework miswired | — |
| `functional` | 30 | Catalog, customer, checkout, stock reservation do not work | Use cases, state transitions |
| `negative` | 58 | Bad input crashes the server or is silently accepted | EP and BVA tables in YAML |
| `calculations` | 41 | Wrong totals, discounts or taxes — direct money loss | Independent oracle vs API, decision-table scenarios |
| `authz` | 59 | One customer sees or changes another's data (BOLA) | Role × operation matrix in YAML |
| `db` | 8 | API answers right but stores something else | Read-only SQL checks |
| `concurrency` | 15 | Double orders, lost updates, overselling | Parallel requests behind a barrier, 5 repeats |
| Schemathesis (not pytest) | 48 operations | Contract drift, 5xx on unexpected input | OpenAPI-driven fuzzing with triaged baselines |
| Newman | 14 requests | A Postman-based team's smoke flow | Chained collection |

## 2. Test data

- Shared seed data is read only (regions, QA products). Every test creates what it changes: customers,
  carts, promotions, products, and — for tax scenarios — whole regions with countries reserved per
  xdist worker. Everything created is deleted afterwards.
- Unique values (e-mails, codes, handles) get random suffixes; names come from Faker seeded by the test id.

## 3. Oracles

| Area | Oracle |
|---|---|
| Totals, discounts, taxes | `src/shop_api/oracle` — independent Decimal implementation of `docs/pricing-rules.md` |
| Response shapes | pydantic models written from real responses; OpenAPI spec through Schemathesis |
| Status codes and error bodies | Medusa conventions observed on sibling endpoints (e.g. 404 `not_found` for unknown IDs) |
| Access rules | Medusa documentation per route (`security` and descriptions in the spec) |
| Stored state | The database, read through a `SELECT`-only role |

## 4. Defect policy

A test always encodes the **correct** behaviour. If the product disagrees, the defect is documented in
`docs/findings.md` and the test becomes `xfail(strict=True)` with `@pytest.mark.finding("BUG-API-NNN")` —
it turns red when the product is fixed, so the mark is removed on purpose. Deliberate product behaviour
(e.g. cart IDs as capabilities) is recorded as "by design" with its risk, never as a defect.

## 5. Entry and exit criteria

- **Entry:** `make -C ../shop-sut up && make -C ../shop-sut smoke`; `make lint typecheck` green.
- **Exit:** full suite green with only documented xfails; `make contract` green (no new Schemathesis
  failures; triage reports 0 unclassified); Newman green; three parallel runs in a row without flakes.

## 6. Flaky-test policy

Parallel runs (`-n auto`) and random order (`pytest-randomly`) are the default way of running. Two
isolation bugs in the tests were found that way and fixed at the root: pagination asserted on the size of
the whole catalog while other tests created products (now pinned to the seeded "QA Picks" collection),
and tax regions collided on a country between workers (now one country pair per worker).

## 7. Metrics (local runs, 2026-11-01, Windows 11, 12 logical CPUs)

| Metric | Value |
|---|---|
| Tests | 237 = 218 passed + 19 strict xfail (10 product defects) |
| Duration | 164 s sequential · 80–95 s with `-n auto` |
| Stability | 8 consecutive parallel runs green after the isolation fixes; 3 random orders green |
| API coverage | Store 28 / 78 operations by tests (`docs/api-coverage.md`), 48 Store operations fuzzed |
| Contract | 258 Schemathesis failures triaged, 0 unclassified |
