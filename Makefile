.PHONY: install test test-aws lint format unbug

PYTEST := uv run pytest

install:
	uv sync

## Unit, contract and integration with fake and moto, architecture. Needs nothing but uv.
test:
	$(PYTEST)

## Contract and integration tests against the stage's DynamoDB table.
## Needs temporary credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN),
## AWS_REGION and STAGE.
test-aws:
	$(PYTEST) -m aws tests/contract tests/integration/dynamodb

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

## make bug-1 ... applies docs/bugs/1-*.patch. Each patch plants one bug from the catalogue.
bug-%:
	@patch=$$(ls docs/bugs/$*-*.patch 2>/dev/null); \
	if [ -z "$$patch" ]; then echo "no patch docs/bugs/$*-*.patch"; exit 1; fi; \
	git apply "$$patch" && echo "applied $$patch"

## Reverts every applied bug patch.
unbug:
	@for patch in docs/bugs/*.patch; do \
		if git apply -R --check "$$patch" 2>/dev/null; then \
			git apply -R "$$patch" && echo "reverted $$patch"; \
		fi; \
	done
