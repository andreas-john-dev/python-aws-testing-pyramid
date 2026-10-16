# python-aws-testing-pyramid

A small hexagonal Python service on AWS (workshop registrations on DynamoDB) and a test suite
that shows which test level catches which bug. Every level is demonstrated with a bug that only
it finds.

> Status: Part 1 is in progress. Domain, adapters, Lambdalith and everything behind `make test`
> are in place. CDK, E2E tests, the load test and CI follow.

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
├── tests/
│   ├── fakes/                        # FakeWorkshopRepository, FakeClock
│   ├── support/                      # credentials, SSM config, DynamoDbStateReader, polling
│   ├── unit/                         # rules and use cases, fakes only, no patching
│   ├── contract/                     # one suite for every WorkshopRepository: fake, moto, aws
│   ├── integration/dynamodb/         # adapter against moto and against the stage's table
│   ├── integration/api/              # build_app() with the adapter on moto
│   └── architecture/                 # PyTestArch import rules
└── docs/bugs/                        # one patch per bug from the catalogue
```

Each package has its own `pyproject.toml` with only its own dependencies.
`workshop_service_infra/schema.py` holds the key names and the GSI. The adapter, the moto
fixture and (soon) CDK read them from there, so the test table and the real table cannot drift
apart.

### Data model

| Item         | `pk`             | `sk`        | Other attributes                                         |
|--------------|------------------|-------------|----------------------------------------------------------|
| Workshop     | `WORKSHOP#<id>`  | `META`      | title, starts_at, capacity, version, gsi1pk, gsi1sk       |
| Registration | `WORKSHOP#<id>`  | `REG#<id>`  | user_id, seats, status, created_at, changed_in_version   |

- `get` is a strongly consistent query on `pk`.
- `save` is one `TransactWriteItems`: a conditional update of `META` on `version`, plus a put of
  every registration changed since the load (`changed_in_version`).
- `list_upcoming` queries `gsi1` (`gsi1pk=WORKSHOPS`, `gsi1sk=<starts_at>`) for candidate ids and
  reads each workshop strongly consistent from its partition.
- Timestamps are fixed-width ISO 8601 strings in UTC, so string order equals time order.

## Running the tests

```bash
make install      # uv sync
make test         # unit, contract + integration with fake and moto, architecture
make lint
```

`make test` needs nothing but uv. Tests marked `aws` are left out.

```bash
export AWS_REGION=eu-central-1 STAGE=my-branch
eval "$(aws configure export-credentials --format env)"
make test-aws     # contract + DynamoDB integration against the stage's table
```

The AWS tests use the credentials from the environment: locally the developer role, in CI the
pipeline role. There is no separate test role. Missing or expired credentials fail the run
immediately with a clear message instead of silently skipping. A silent skip would be a false
green in CI.

## The bug catalogue

The code in the repository is correct. Each bug lives as a patch in `docs/bugs/`:

```bash
make bug-1        # apply docs/bugs/1-*.patch
make test         # watch the level that catches it fail
make unbug        # revert all applied patches
```

| # | Level                       | Bug                                                              | Why the level before misses it                        |
|---|-----------------------------|------------------------------------------------------------------|-------------------------------------------------------|
| 1 | Unit                        | Capacity counts cancelled registrations                          | First level                                           |
| 2 | Contract                    | The fake does not check `version` on save                        | Unit tests only run against the fake                  |
| 3 | Integration (moto)          | The adapter stores `starts_at` as a `timestamp()` float          | The fake stores Python objects in a dict              |
| 4 | Integration (real DynamoDB) | *to be decided, see below*                                       |                                                       |
| 5 | Integration (handler)       | `ConcurrentUpdateError` becomes 500 instead of 409               | Unit tests call use cases, not the handler            |
| 6 | Architecture                | A use case imports and catches `botocore` `ClientError`          | All tests stay green, boto3 is in the shared `.venv`  |
| 7 | E2E                         | Lambda policy allows the table but not its indexes               | *follows with CDK*                                    |
| 8 | Load                        | Only `ConditionalCheckFailed` is translated, not `TransactionConflict` | *follows with the load test*                    |

## Findings while building

- moto rejects `ConsistentRead=True` on a GSI query, just like DynamoDB. That bug is therefore
  not suited to show the difference between moto and real DynamoDB.
- moto rejects floats (`TypeError` from the serializer), so bug 3 is caught against moto.
- moto runs parallel `TransactWriteItems` one after the other and never reports
  `TransactionConflict`. Bug 8 is only visible under real load.
- PyTestArch refuses rules on modules that nothing in the scanned tree imports, which is the
  normal case for a forbidden module. `tests/architecture` passes only modules that are
  actually imported. `from unittest import mock` only shows up as an import of `unittest`,
  so the unit-test rule forbids all of `unittest`.
