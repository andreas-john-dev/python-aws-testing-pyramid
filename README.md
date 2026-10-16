# python-aws-testing-pyramid

A small hexagonal Python service on AWS (workshop registrations on DynamoDB) and a test suite
that shows which test level catches which bug. Every level is demonstrated with a bug that only
it finds.

## The example domain

A workshop has a fixed number of seats. Signed-in users book 1 or 2 of them.

- Active seats never exceed the capacity. Cancelled registrations do not count.
- A person holds at most 2 seats per workshop.
- Cancelling is possible until 48 h before the start, and only by the person who registered.
- No registrations after the start.
- Every save increments the workshop's `version`. Saving a stale version fails
  (optimistic locking). `RegisterForWorkshop` and `CancelRegistration` reload and retry up to
  3 times, with exponential backoff and full jitter.

The ports (`WorkshopRepository`, `Clock`) contain no DynamoDB terms, so a SQL adapter (Part 2)
fits behind the same port.

## Layout

```
├── pyproject.toml                    # uv workspace root, dev dependencies, pytest config
├── Makefile
├── services/workshops/
│   ├── workshop_service_domain/      # pydantic: models, rules, ports, use cases, errors
│   ├── workshop_service_infra/       # boto3: DynamoDBWorkshopRepository, SystemClock, schema.py
│   └── functions/                    # functions.api: Lambdalith with Powertools router
├── cdk/                              # shared, stateful, stateless and optional ci stack
├── scripts/stage.py                  # stage name from branch name
├── tests/
│   ├── fakes/                        # FakeWorkshopRepository, FakeClock
│   ├── support/                      # credentials, SSM config, Cognito users, API client,
│   │                                 # DynamoDbStateReader, polling
│   ├── unit/                         # rules and use cases, fakes only, no patching
│   ├── contract/                     # one suite for every WorkshopRepository: fake, moto, aws
│   ├── integration/dynamodb/         # adapter against moto and against the stage's table
│   ├── integration/api/              # build_app() with the adapter on moto
│   ├── architecture/                 # PyTestArch import rules
│   ├── e2e/                          # through API Gateway with Cognito test users
│   └── load/locustfile.py            # invariants under real parallelism
├── docs/bugs/                        # one patch per bug from the catalogue
└── .github/workflows/                # pull request pipeline, manual load test
```

Each package has its own `pyproject.toml` with only its own dependencies.
`workshop_service_infra/schema.py` holds the key names and the GSI. The adapter, the moto
fixture and the CDK stack read them from there, so the test table and the real table cannot
drift apart.

### Data model

| Item         | `pk`             | `sk`        | Other attributes                                       |
|--------------|------------------|-------------|--------------------------------------------------------|
| Workshop     | `WORKSHOP#<id>`  | `META`      | title, starts_at, capacity, version                    |
| Registration | `WORKSHOP#<id>`  | `REG#<id>`  | user_id, seats, status, created_at, changed_in_version |

Every item also carries `gsi1pk=WORKSHOPS` and `gsi1sk=<starts_at>#<id>#<sk>`.

- `get` is a strongly consistent query on `pk`.
- `save` is one `TransactWriteItems`: a conditional update of `META` on `version`, plus a put of
  every registration changed since the load (`changed_in_version`).
  `ConditionalCheckFailed` and `TransactionConflict` both become `ConcurrentUpdateError`.
- `list_upcoming` is one query on `gsi1`. It returns whole workshops, META and registrations,
  ordered by start. The index is eventually consistent, so a listing may lag behind.
- Timestamps are fixed-width ISO 8601 strings in UTC, so string order equals time order.

## Running the tests

```bash
make install      # uv sync
make test         # unit, contract + integration with fake and moto, architecture
make lint
```

`make test` needs nothing but uv. Tests marked `aws` are left out.

### Against AWS

The AWS tests use temporary credentials from the environment: locally the developer role, in CI
the pipeline role. There is no separate test role. Missing or expired credentials fail the run
immediately with a clear message instead of silently skipping. A silent skip would be a false
green in CI.

```bash
export AWS_REGION=eu-central-1
eval "$(aws configure export-credentials --format env)"

npx aws-cdk@2.1143.0 bootstrap   # once per account and region
make deploy       # STAGE defaults to the current branch, see scripts/stage.py
make test-aws     # contract + DynamoDB integration against the stage's table
make test-e2e     # through API Gateway, with Cognito test users
make load         # 100 parallel users, only against your own stage
make destroy
```

Every target accepts `STAGE=...`. API URL, table name, user pool id and test client id are read
from SSM under `/workshops/<stage>/`.

#### Permissions of the developer and pipeline role

| Action                                                                                       | Resource                                       |
|----------------------------------------------------------------------------------------------|------------------------------------------------|
| `sts:GetCallerIdentity`                                                                      | `*`                                            |
| `ssm:GetParameter*`                                                                          | `parameter/workshops/*`                        |
| `cognito-idp:AdminCreateUser`, `AdminSetUserPassword`, `AdminInitiateAuth`, `AdminDeleteUser` | `userpool/*`                                   |
| `dynamodb:GetItem`, `Query`, `PutItem`, `UpdateItem`, `DeleteItem`, `ConditionCheckItem`      | `table/workshops-*`, `table/workshops-*/index/*` |

Developer roles in a dev account usually have these anyway. The pipeline role gets them on top of
its deploy rights. `cdk/src/workshop_cdk/ci.py` has the same list as code.

The load test needs a Lambda concurrency limit of at least 100 in the account. New accounts often
start lower.

### CI

`.github/workflows/pull-request.yml` runs for every pull request:

1. `make lint` and `make test`
2. assume the pipeline role via OIDC and deploy a stage for the branch
3. `make test-aws`
4. `make test-e2e`
5. `make destroy`, also when step 3 or 4 fails

A concurrency group per branch keeps two pushes from deploying to the same stage in parallel.
`cancel-in-progress` stays off: a cancelled run would skip step 5 and leave half a stage behind.
The load test is a separate workflow that only runs manually (`workflow_dispatch`).

Setup, once per account:

```bash
make deploy-ci GITHUB_REPOSITORY=owner/repo   # add OIDC_PROVIDER_ARN=... if one exists already
```

Then set the repository variables `AWS_ROLE_ARN` (output of the ci stack, role
`workshops-pipeline`) and `AWS_REGION`. Without them the AWS job fails with a clear message.

## The bug catalogue

The code in the repository is correct. Each bug lives as a patch in `docs/bugs/`:

```bash
make bug-1        # apply docs/bugs/1-*.patch
make test         # watch the level that catches it fail
make unbug        # revert all applied patches
```

Bugs 4, 7 and 8 need a deploy after applying the patch (`make deploy`, then `make test-aws`,
`make test-e2e` or `make load`).

| # | Level                       | Bug                                                                    | Why the level before misses it                                          |
|---|-----------------------------|------------------------------------------------------------------------|-------------------------------------------------------------------------|
| 1 | Unit                        | Capacity counts cancelled registrations                                | First level                                                             |
| 2 | Contract                    | The fake does not check `version` on save                              | Unit tests only run against the fake                                    |
| 3 | Integration (moto)          | The adapter stores `starts_at` as a `timestamp()` float                | The fake stores Python objects in a dict                                |
| 4 | Integration (real DynamoDB) | CDK creates the GSI with `KEYS_ONLY` instead of the projection in `schema.py` | moto builds its table from `schema.py`, not from the CDK stack   |
| 5 | Integration (handler)       | `ConcurrentUpdateError` becomes 500 instead of 409                     | Unit tests call use cases, not the handler                              |
| 6 | Architecture                | A use case imports and catches `botocore` `ClientError`                | All tests stay green, boto3 is in the shared `.venv`                    |
| 7 | E2E                         | The Lambda policy allows the table but not `table/*/index/*`           | moto checks no IAM, and the AWS integration tests run with the developer or pipeline role |
| 8 | Load                        | Only `ConditionalCheckFailed` is translated, not `TransactionConflict` | Single requests cause no transaction conflicts, neither on moto nor on AWS |

## Findings while building

- moto rejects `ConsistentRead=True` on a GSI query, just like DynamoDB. That bug is therefore
  not suited to show the difference between moto and real DynamoDB, so bug 4 is a GSI
  projection that differs between `schema.py` and the CDK stack.
- moto rejects floats (`TypeError` from the serializer), so bug 3 is caught against moto, by the
  moto variant of the contract tests as well.
- moto runs parallel `TransactWriteItems` one after the other and never reports
  `TransactionConflict`. Bug 8 is only visible under real load.
- PyTestArch refuses rules on modules that nothing in the scanned tree imports, which is the
  normal case for a forbidden module. `tests/architecture` passes only modules that are
  actually imported. `from unittest import mock` only shows up as an import of `unittest`,
  so the unit-test rule forbids all of `unittest`.
- The contract tests found a difference between fake and adapter: with equal `created_at`, the
  order of registrations differed. The aggregate now keeps them ordered by `(created_at, id)`.

## Limitations

- The constant partition key `WORKSHOPS` in `gsi1` becomes a hot partition with many workshops.
- A save writes at most 99 changed registrations (DynamoDB allows 100 actions per transaction).
- AWS integration and E2E tests need a deployed stage and cost a deploy per run.
- Load tests against short-lived stages show no behaviour after weeks in production.
