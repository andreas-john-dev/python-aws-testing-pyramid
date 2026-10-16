.PHONY: install test test-aws test-e2e load package synth deploy destroy deploy-ci lint format unbug

PYTEST := uv run pytest
CDK := npx --yes aws-cdk@2.1143.0
LAMBDA_PYTHON := 3.14
LAMBDA_PLATFORM := aarch64-manylinux2014
## One stage per branch, see scripts/stage.py. Override with `make deploy STAGE=...`.
STAGE ?= $(shell python3 scripts/stage.py)
export STAGE

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

## Lambda E2E tests through API Gateway with Cognito test users. Same credentials as test-aws.
test-e2e:
	$(PYTEST) -m aws tests/e2e

## 100 parallel users book a workshop with 20 seats. Only against your own stage.
load:
	mkdir -p reports
	PYTHONPATH=. uv run locust -f tests/load/locustfile.py --headless --users 100 --spawn-rate 100 \
		--run-time 1m --stop-timeout 10 --csv reports/load --html reports/load.html

## The functions package and its dependencies for arm64, no layers.
package:
	rm -rf build/lambda && mkdir -p build
	uv export --package workshop-functions --frozen --no-dev --no-editable \
		--no-emit-workspace --no-hashes --quiet -o build/requirements.txt
	uv pip install --quiet --target build/lambda --python-version $(LAMBDA_PYTHON) \
		--python-platform $(LAMBDA_PLATFORM) --only-binary :all: -r build/requirements.txt
	uv pip install --quiet --target build/lambda --python-version $(LAMBDA_PYTHON) \
		--python-platform $(LAMBDA_PLATFORM) --no-deps \
		services/workshops/workshop_service_domain services/workshops/workshop_service_infra \
		services/workshops/functions

synth: package
	cd cdk && $(CDK) synth --quiet -c stage=$(STAGE)

deploy: package
	cd cdk && $(CDK) deploy --all --require-approval never -c stage=$(STAGE)

destroy:
	cd cdk && $(CDK) destroy --all --force -c stage=$(STAGE)

## Once per account: GitHub OIDC provider and pipeline role.
## make deploy-ci GITHUB_REPOSITORY=owner/repo
## An existing provider is found and referenced; OIDC_PROVIDER_ARN=arn:... overrides that.
## The OIDC subject prefix is read from GitHub with `gh` (immutable subjects carry ids);
## GITHUB_SUBJECT_PREFIX=... overrides it.
GITHUB_SUBJECT_PREFIX ?= $(shell gh api repos/$(GITHUB_REPOSITORY)/actions/oidc/customization/sub \
	--jq '.sub_claim_prefix // empty' 2>/dev/null)
deploy-ci:
	cd cdk && $(CDK) deploy --require-approval never -c github_repository=$(GITHUB_REPOSITORY) \
		$(if $(GITHUB_SUBJECT_PREFIX),-c github_subject_prefix=$(GITHUB_SUBJECT_PREFIX)) \
		$(if $(OIDC_PROVIDER_ARN),-c oidc_provider_arn=$(OIDC_PROVIDER_ARN))

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
