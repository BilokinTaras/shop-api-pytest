# How AI was used

- **The owner (Taras Bilokin)** set the goals and scope, chose the stack (pytest, httpx, pydantic,
  Schemathesis, Allure) and approved the strategy.
- **An AI coding assistant (Claude Code)** wrote most of the code and the documents within that plan.
- **Everything ran against the real stand**; numbers in the README come from those runs.

## Where human-style verification mattered

| Work | How it was kept honest |
|---|---|
| Pydantic models | Written from captured responses of the pinned version, then corrected when reality differed (list endpoints omit most order totals; Medusa returns money with more than two decimals) |
| Pricing oracle | Specified from Medusa's documentation **and** measured behaviour before any test compared it with the API; unit and property tests on the oracle alone. The property tests caught a precision artefact in the oracle itself, which is recorded as an oracle error, not as a product defect |
| Findings | Each one reproduced by hand with a minimal request; deliberate behaviour (cart/order IDs as capabilities) checked against Medusa's documentation and source before deciding it was not a defect |
| Fuzzing | Every one of 265 Schemathesis failures classified by a script with explicit rules; nothing accepted silently |
| Flaky tests | Two intermittent failures under parallel runs were traced to test isolation and fixed, not retried |
