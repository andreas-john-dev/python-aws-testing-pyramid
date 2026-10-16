"""Behaviour every WorkshopRepository must have: the fake, DynamoDB via moto, and real DynamoDB.

Unit tests trust the fake. These tests are why that trust is justified: the `aws` variant proves
the fake behaves like real DynamoDB, not just like moto.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from workshop_service_domain.errors import ConcurrentUpdateError
from workshop_service_domain.models import RegistrationStatus, Workshop
from workshop_service_domain.ports import WorkshopRepository

from tests.support.polling import eventually

NOW = datetime.now(UTC).replace(microsecond=0)
BERLIN = timezone(timedelta(hours=2))


def workshop(starts_in: timedelta = timedelta(days=30), capacity: int = 10) -> Workshop:
    return Workshop(title="Contract", starts_at=NOW + starts_in, capacity=capacity)


def test_round_trip_keeps_all_fields_and_the_instant(repository: WorkshopRepository) -> None:
    original = Workshop(
        title="Round trip",
        starts_at=datetime(2031, 5, 1, 18, 30, 15, 123456, tzinfo=BERLIN),
        capacity=7,
    )
    original.register("alice", 2, NOW)
    repository.save(original)

    loaded = repository.get(original.id)

    assert loaded == original
    assert loaded is not None and loaded.starts_at.tzinfo == UTC


def test_get_unknown_id_returns_none(repository: WorkshopRepository) -> None:
    assert repository.get("does-not-exist") is None


def test_save_with_stale_version_raises(repository: WorkshopRepository) -> None:
    repository.save(original := workshop())
    first, second = repository.get(original.id), repository.get(original.id)
    assert first is not None and second is not None
    first.register("alice", 1, NOW)
    second.register("bob", 1, NOW)
    repository.save(first)

    with pytest.raises(ConcurrentUpdateError):
        repository.save(second)

    stored = repository.get(original.id)
    assert stored is not None
    assert [r.user_id for r in stored.registrations] == ["alice"]


def test_save_increments_the_version(repository: WorkshopRepository) -> None:
    repository.save(new := workshop())
    new.register("alice", 1, NOW)
    new.register("bob", 1, NOW)
    repository.save(new)

    stored = repository.get(new.id)

    assert new.version == 2
    assert stored is not None and stored.version == 2


def test_two_new_workshops_with_the_same_id_conflict(repository: WorkshopRepository) -> None:
    first = workshop()
    second = first.model_copy(deep=True)
    repository.save(first)

    with pytest.raises(ConcurrentUpdateError):
        repository.save(second)


def test_changes_to_a_loaded_workshop_need_a_save(repository: WorkshopRepository) -> None:
    repository.save(original := workshop())
    loaded = repository.get(original.id)
    assert loaded is not None

    loaded.register("alice", 1, NOW)

    assert repository.get(original.id) == original


def test_cancelled_registrations_are_kept(repository: WorkshopRepository) -> None:
    repository.save(original := workshop())
    loaded = repository.get(original.id)
    assert loaded is not None
    registration = loaded.register("alice", 2, NOW)
    loaded.cancel(registration.id, "alice", NOW)
    repository.save(loaded)

    stored = repository.get(original.id)

    assert stored is not None
    assert [(r.id, r.status) for r in stored.registrations] == [
        (registration.id, RegistrationStatus.CANCELLED)
    ]
    assert stored.free_seats == stored.capacity


def test_list_upcoming_skips_past_workshops_and_sorts(repository: WorkshopRepository) -> None:
    past = workshop(starts_in=-timedelta(days=1))
    later, sooner, soonest = (workshop(starts_in=timedelta(days=d)) for d in (3, 2, 1))
    for w in (past, later, sooner, soonest):
        repository.save(w)
    ours = {w.id for w in (past, later, sooner, soonest)}

    # A deployed stage holds other tests' workshops, and the index is eventually consistent.
    found = eventually(
        lambda: [w.id for w in repository.list_upcoming(NOW) if w.id in ours],
        until=lambda ids: len(ids) == 3,
    )

    assert found == [soonest.id, sooner.id, later.id]
