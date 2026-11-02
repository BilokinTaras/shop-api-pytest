# ADR-002: Allure Report 3 instead of Allure 2

- Status: accepted
- Date: 2026-11-01

## Context

The suite needs a report with steps, attachments (HTTP exchanges on failure), Allure labels
(epic/feature/story/severity), **categories** (known defects vs regressions vs broken tests), the
**environment** (stand and tool versions) and a **trend** between runs, both locally and later on
GitHub Pages. `allure-pytest` writes the same result files for both report generators.

## Decision

Allure Report **3.22.1** (npm package `allure`), configured in `allurerc.mjs`:
categories by status and finding ID, `variables` from `reports/run-info.json` (written by `conftest.py`),
history in `reports/allure-history.jsonl`.

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| Allure 2.46 (`allure-commandline`) | Most widely known; `categories.json`, `environment.properties`, history folder | Needs a JVM on every machine and CI runner; history is copied between runs by hand | Extra runtime for no extra feature this suite needs |
| pytest-html | One file, no tooling | No steps, categories or trend | Too little for a report a reviewer explores |
| **Allure 3** | Runs on Node (already used for Newman); categories, variables and history in one config file; known-issues file; quality gates | Younger; fewer blog posts; some Allure 2 plugins not ported | **Chosen** — verified locally: 237 tests, 3 categories, 2-run trend |

## Consequences

- `make report` = `npx allure generate allure-results -c allurerc.mjs`. Java is not required.
- In CI the nightly run downloads the history file from the previous night's Pages site before generating,
  then publishes it with the report, so the trend survives fresh runners.
- If an Allure 2-only feature becomes necessary, the results directory works with Allure 2 unchanged.
