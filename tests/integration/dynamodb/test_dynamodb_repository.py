"""What only DynamoDB can tell: item mapping, number types, the transaction and the GSI.

The same tests run against moto (`make test`) and against the stage's table (`make test-aws`).
They run with the developer or pipeline role, not the Lambda role, so they test the adapter,
not the Lambda's IAM policy. That is the E2E tests' job.
"""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from workshop_service_domain.errors import ConcurrentUpdateError
from workshop_service_domain.models import Workshop
from workshop_service_infra import schema

from tests.support.dynamodb import DynamoDbStateReader, DynamoDbTable, tracked_repository
from tests.support.polling import eventually

NOW = datetime.now(UTC).replace(microsecond=0)


def new_workshop(starts_in: timedelta = timedelta(days=30)) -> Workshop:
    return Workshop(title="Integration", starts_at=NOW + starts_in, capacity=5)


def test_items_have_the_documented_layout(dynamodb_table: DynamoDbTable) -> None:
    repository = tracked_repository(dynamodb_table)
    workshop = new_workshop()
    alice = workshop.register("alice", 2, NOW)
    bob = workshop.register("bob", 1, NOW)
    repository.save(workshop)

    items = {
        i[schema.SORT_KEY]: i for i in DynamoDbStateReader(dynamodb_table).raw_items(workshop.id)
    }

    assert set(items) == {schema.META_SORT_KEY, f"REG#{alice.id}", f"REG#{bob.id}"}
    meta = items[schema.META_SORT_KEY]
    assert meta[schema.PARTITION_KEY] == f"WORKSHOP#{workshop.id}"
    assert meta[schema.GSI1_PARTITION_KEY] == schema.UPCOMING_PARTITION
    assert meta[schema.GSI1_SORT_KEY] == meta["starts_at"]
    assert all(schema.GSI1_PARTITION_KEY not in i for k, i in items.items() if k != "META")


def test_timestamps_are_utc_iso_strings_and_numbers_are_numbers(
    dynamodb_table: DynamoDbTable,
) -> None:
    repository = tracked_repository(dynamodb_table)
    workshop = Workshop(
        title="Types",
        starts_at=datetime(2031, 3, 1, 10, 0, tzinfo=timezone(timedelta(hours=1))),
        capacity=5,
    )
    workshop.register("alice", 2, NOW)
    repository.save(workshop)

    items = DynamoDbStateReader(dynamodb_table).raw_items(workshop.id)
    meta = next(i for i in items if i[schema.SORT_KEY] == schema.META_SORT_KEY)
    registration = next(i for i in items if i[schema.SORT_KEY].startswith("REG#"))

    assert meta["starts_at"] == "2031-03-01T09:00:00.000000+00:00"
    assert meta["capacity"] == Decimal(5) and meta["version"] == Decimal(1)
    assert registration["seats"] == Decimal(2)
    assert datetime.fromisoformat(registration["created_at"]) == NOW


def test_save_writes_meta_and_registrations_in_one_transaction(
    dynamodb_table: DynamoDbTable,
) -> None:
    repository = tracked_repository(dynamodb_table)
    repository.save(workshop := new_workshop())
    first, second = repository.get(workshop.id), repository.get(workshop.id)
    assert first is not None and second is not None
    first.register("alice", 1, NOW)
    second.register("bob", 2, NOW)
    repository.save(first)

    with pytest.raises(ConcurrentUpdateError):
        repository.save(second)

    # The cancelled transaction must not have written bob's registration.
    state = DynamoDbStateReader(dynamodb_table).read(workshop.id)
    assert state is not None
    assert state.version == 2
    assert [(r.user_id, r.seats) for r in state.registrations] == [("alice", 1)]


def test_save_writes_only_changed_registrations(dynamodb_table: DynamoDbTable) -> None:
    repository = tracked_repository(dynamodb_table)
    workshop = new_workshop()
    kept = workshop.register("alice", 1, NOW)
    repository.save(workshop)
    # Remove alice's item behind the adapter's back: a save that rewrote every registration
    # would bring it back.
    dynamodb_table.client.delete_item(
        TableName=dynamodb_table.name,
        Key={"pk": {"S": f"WORKSHOP#{workshop.id}"}, "sk": {"S": f"REG#{kept.id}"}},
    )

    workshop.register("bob", 1, NOW)
    repository.save(workshop)

    state = DynamoDbStateReader(dynamodb_table).read(workshop.id)
    assert state is not None and [r.user_id for r in state.registrations] == ["bob"]


def test_get_returns_every_registration(dynamodb_table: DynamoDbTable) -> None:
    repository = tracked_repository(dynamodb_table)
    workshop = Workshop(title="Busy", starts_at=NOW + timedelta(days=9), capacity=200)
    for n in range(60):
        workshop.register(f"user-{n}", 1, NOW)
    repository.save(workshop)

    loaded = repository.get(workshop.id)

    assert loaded is not None and len(loaded.registrations) == 60


def test_list_upcoming_reads_the_index(dynamodb_table: DynamoDbTable) -> None:
    repository = tracked_repository(dynamodb_table)
    past, upcoming = new_workshop(-timedelta(hours=1)), new_workshop(timedelta(days=2))
    upcoming.register("alice", 1, NOW)
    for workshop in (past, upcoming):
        repository.save(workshop)

    # Against AWS the GSI lags behind the table, so poll briefly instead of expecting
    # immediate visibility. moto returns on the first try.
    found = eventually(
        lambda: [w for w in repository.list_upcoming(NOW) if w.id in {past.id, upcoming.id}],
        until=lambda ws: len(ws) == 1,
    )

    assert found == [upcoming]
