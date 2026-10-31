# Shop API · pytest + httpx

_README v0 — the full README is written in stage 1.13._

API test suite for Medusa: contract, pricing oracle, access matrix, database and concurrency checks.

```bash
make -C ../shop-sut up
uv sync --frozen
make smoke
```
