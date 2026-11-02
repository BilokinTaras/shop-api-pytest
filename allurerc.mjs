// Allure Report 3 configuration (ADR-002). Run: make report
import { existsSync, readFileSync } from "node:fs";

import { defineConfig } from "allure";

// Written by tests/conftest.py at session start: versions of the stand and of the tools.
const runInfo = existsSync("./reports/run-info.json")
  ? JSON.parse(readFileSync("./reports/run-info.json", "utf8"))
  : {};

export default defineConfig({
  name: "shop-api-pytest · Medusa API suite",
  output: "./allure-report",
  // Trend between runs. Locally the file stays in reports/; the nightly CI run restores it from the published
  // Pages site before generating, so the trend survives fresh runners.
  historyPath: "./reports/allure-history.jsonl",
  variables: runInfo,
  categories: {
    rules: [
      {
        name: "Known product defects (strict xfail, see docs/findings.md)",
        matchedStatuses: ["skipped"],
        messageRegex: ".*(BUG|SPEC)-API-\\d+.*",
      },
      {
        name: "Product regression: an assertion failed",
        matchedStatuses: ["failed"],
      },
      {
        name: "Test or environment broken: unexpected error",
        matchedStatuses: ["broken"],
      },
    ],
  },
  plugins: {
    awesome: {
      options: { reportName: "shop-api-pytest", reportLanguage: "en", groupBy: ["epic", "feature", "story"] },
    },
  },
});
