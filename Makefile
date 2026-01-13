.PHONY: build check clean deps format help lint publish test typecheck
.DEFAULT_GOAL := help

build: ## Build the package
	python3 -m build

check: lint typecheck test ## Run all checks

clean: ## Remove build artifacts and caches
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

deps: ## Install dev dependencies
	python3 -m pip install -e ".[dev]"

format: ## Format code with ruff
	python3 -m ruff format .

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

lint: ## Run ruff linter
	python3 -m ruff check .

publish: clean build ## Publish to PyPI
	@test -f .env && . ./.env; python3 -m twine upload dist/*

test: ## Run tests
	python3 -m pytest

typecheck: ## Run mypy type checking
	python3 -m mypy src
