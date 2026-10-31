# shop-api-pytest — GNU Make 3.81+ (macOS default) compatible.
SHELL := /bin/sh
SUT_DIR ?= ../shop-sut
IMAGE := qa-shop-api-pytest:local

.PHONY: help sut-up install lint format typecheck smoke test test-seq unit report docker-build docker-test newman

help: ## Show targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-13s %s\n", $$1, $$2}'

sut-up: ## Start the shop from the sibling repository
	$(MAKE) -C $(SUT_DIR) up

install: ## Install locked dependencies with uv
	uv sync --frozen

lint: ## ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

format: ## Apply ruff formatting
	uv run ruff format .

typecheck: ## mypy --strict
	uv run mypy

unit: ## Tests of the framework itself (no stand needed)
	uv run pytest -m unit -q

smoke: ## Smoke tests
	uv run pytest -m smoke -q

test: ## Full suite in parallel
	uv run pytest -n auto -q

test-seq: ## Full suite sequentially
	uv run pytest -q

report: ## Build and open the Allure report (needs allure CLI)
	allure generate allure-results -o allure-report --clean && allure open allure-report

docker-build: ## Build the test runner image
	docker build -f docker/Dockerfile -t $(IMAGE) .

docker-test: docker-build ## Run the suite in Docker on network qa-shop-net
	docker run --rm --network qa-shop-net -v "$(abspath $(SUT_DIR))/.generated:/sut:ro" $(IMAGE) -n auto -q -p no:cacheprovider

PK = $(shell grep '^SUT_PUBLISHABLE_KEY=' $(SUT_DIR)/.generated/sut.env | cut -d= -f2)
ST = uv run schemathesis run contracts/openapi/store.openapi.yaml --url http://localhost:9000 \
     -H x-publishable-api-key:$(PK) --checks all --max-examples 20 --workers 4 --generation-deterministic
ST_STORE = $(ST) --include-method GET --baseline contracts/schemathesis-baseline.store.json
ST_CARTS = $(ST) --include-path-regex ^/store/carts --baseline contracts/schemathesis-baseline.store-carts.json

.PHONY: contract contract-update coverage
contract: ## Schemathesis against the triaged baselines (fails only on NEW contract failures)
	PYTHONUTF8=1 $(ST_STORE) --report junit,html --report-dir reports/schemathesis/store
	PYTHONUTF8=1 $(ST_CARTS) --report junit,html --report-dir reports/schemathesis/store-carts

contract-update: ## Merge new failures into the baselines (only after triage in docs/contract-findings.md)
	PYTHONUTF8=1 $(ST_STORE) --baseline-update || true
	PYTHONUTF8=1 $(ST_CARTS) --baseline-update || true
	uv run python scripts/contract_triage.py

coverage: ## Run the suite with call recording and write docs/api-coverage.md
	rm -rf reports/calls && mkdir -p reports/calls
	SHOP_API_RECORD_DIR=reports/calls uv run pytest -n auto -q -p no:randomly || true
	uv run python scripts/api_coverage.py reports/calls

newman: ## Postman smoke collection via Newman (HTML + JUnit in reports/newman)
	cd postman && npm ci --no-audit --no-fund && sh run-newman.sh
