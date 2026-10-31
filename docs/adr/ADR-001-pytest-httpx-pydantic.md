# ADR-001: pytest + httpx + pydantic for the API suite

- Status: accepted
- Date: 2026-10-31

## Context

The API suite must express business rules (pricing, access control, inventory) as code, generate many
data-driven cases from tables, check database state, run in parallel, and produce a report a reviewer
can read. Vacancies ask for Python, pytest, REST and Postman.

## Decision

Python 3.12, **pytest** (fixtures, parametrisation, markers, xdist), **httpx** (typed sync client,
timeouts, event hooks), **pydantic v2** (response models, settings), Allure for reports, Hypothesis for
property tests, Schemathesis for OpenAPI fuzzing, psycopg for read-only SQL checks. uv locks the
dependency tree; ruff and mypy `--strict` keep the code clean.

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| `requests` instead of httpx | Ubiquitous | No built-in timeouts by default, no async, no event hooks | httpx gives the request journal and timeouts cleanly |
| Tavern (YAML API tests) | Declarative, quick for CRUD | Logic such as a pricing oracle or concurrency tests does not fit YAML | Too limited for computed expectations |
| Robot Framework | Readable keywords, non-programmers | Extra DSL layer, weaker typing, verbose for data-driven math | The audience is engineers; Python reads better |
| Karate (Java) | Strong API DSL, built-in parallelism | JVM toolchain, different language from the rest of the portfolio | Python is a target skill here |
| Postman/Newman only | Familiar to many teams | Hard to version, review and compute expectations | Kept as a small smoke collection next to pytest |

## Consequences

- Business rules live in plain Python (the pricing oracle), testable on their own with unit and
  property tests, independent from the product code.
- Every response is validated by a pydantic model; money is `Decimal`, never `float`.
- The same suite runs on a laptop and in a container (`make docker-test`) against the same stand.

## References

- https://docs.pytest.org · https://www.python-httpx.org · https://docs.pydantic.dev
