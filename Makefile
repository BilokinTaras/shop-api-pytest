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
