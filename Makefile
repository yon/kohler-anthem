-include .env
export

VENV := .venv
PYTHON := $(VENV)/bin/python3

.PHONY: build check clean deps format health-check help lint publish test test-integration typecheck
.DEFAULT_GOAL := help

# =============================================================================
# Environment
# =============================================================================

$(VENV):
	python3 -m venv $(VENV)

deps: $(VENV) ## Install Python dev dependencies
	@$(PYTHON) -m pip install -e ".[dev]"

# =============================================================================
# Development
# =============================================================================

build: deps ## Build the package
	$(PYTHON) -m build

check: lint typecheck test ## Run all checks

clean: ## Remove build artifacts and caches
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

format: deps ## Format code with ruff
	$(PYTHON) -m ruff format .

help: ## Show this help message
	@echo "Available targets:"
	@echo ""
	@grep -hE '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'
	@echo ""
	@echo "For credential extraction, see: credential-extraction/"

lint: deps ## Run ruff linter
	$(PYTHON) -m ruff check .

publish: clean build ## Publish to PyPI
	$(PYTHON) -m twine upload dist/*

test: deps ## Run unit tests (skips integration suite without credentials)
	$(PYTHON) -m pytest --ignore=tests/integration

test-integration: deps ## Run live-API health checks (requires credentials)
	$(PYTHON) -m pytest tests/integration -v -s

health-check: deps ## One-shot CLI diagnostic against the live Kohler API
	$(PYTHON) dev/scripts/health_check.py

typecheck: deps ## Run mypy type checking
	$(PYTHON) -m mypy src
