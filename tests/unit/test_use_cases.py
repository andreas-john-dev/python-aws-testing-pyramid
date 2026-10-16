"""Use cases with FakeWorkshopRepository and FakeClock, passed in through the constructor."""

from datetime import timedelta

import pytest
from workshop_service_domain.errors import (
    CancellationTooLate,
    ConcurrentUpdateError,
    WorkshopAlreadyStarted,
    WorkshopNotFound,
)
from workshop_service_domain.models import RegistrationStatus
from workshop_service_domain.use_cases import (
    CancelRegistration,
    CreateWorkshop,
    ListUpcomingWorkshops,
    RegisterForWorkshop,
)

from tests.fakes import FakeClock, FakeWorkshopRepository
from tests.unit.builders import NO_WAIT, NOW, make_workshop


def test_create_workshop_saves_it(repository: FakeWorkshopRepository, clock: FakeClock) -> None:
    workshop = CreateWorkshop(repository, clock)("Testing", NOW + timedelta(days=3), 12)

    stored = repository.get(workshop.id)
    assert stored is not None
    assert (stored.title, stored.capacity, stored.version) == ("Testing", 12, 1)
    assert workshop.version == 1


def test_create_workshop_in_the_past_is_rejected(
    repository: FakeWorkshopRepository, clock: FakeClock
) -> None:
    with pytest.raises(WorkshopAlreadyStarted):
        CreateWorkshop(repository, clock)("Testing", NOW, 12)


def test_register_persists_the_registration(
    repository: FakeWorkshopRepository, clock: FakeClock
) -> None:
    workshop = make_workshop()
    repository.save(workshop)

    registration = RegisterForWorkshop(repository, clock, NO_WAIT)(workshop.id, "alice", 2)

    stored = repository.get(workshop.id)
    assert stored is not None
    assert [r.id for r in stored.registrations] == [registration.id]
    assert stored.free_seats == workshop.capacity - 2


def test_register_for_unknown_workshop(
    repository: FakeWorkshopRepository, clock: FakeClock
) -> None:
    with pytest.raises(WorkshopNotFound):
        RegisterForWorkshop(repository, clock, NO_WAIT)("nope", "alice", 1)


def test_register_retries_after_a_conflict(
    repository: FakeWorkshopRepository, clock: FakeClock
) -> None:
    workshop = make_workshop()
    repository.save(workshop)
    repository.fail_next_save_with_conflict(times=2)

    RegisterForWorkshop(repository, clock, NO_WAIT)(workshop.id, "alice", 1)

    assert repository.save_calls == 1 + 3
    stored = repository.get(workshop.id)
    assert stored is not None and stored.seats_held_by("alice") == 1


def test_register_gives_up_after_three_attempts(
    repository: FakeWorkshopRepository, clock: FakeClock
) -> None:
    workshop = make_workshop()
    repository.save(workshop)
    repository.fail_next_save_with_conflict(times=3)

    with pytest.raises(ConcurrentUpdateError):
        RegisterForWorkshop(repository, clock, NO_WAIT)(workshop.id, "alice", 1)

    stored = repository.get(workshop.id)
    assert stored is not None and stored.registrations == []


def test_cancel_registration(repository: FakeWorkshopRepository, clock: FakeClock) -> None:
    workshop = make_workshop()
    repository.save(workshop)
    registration = RegisterForWorkshop(repository, clock, NO_WAIT)(workshop.id, "alice", 1)

    CancelRegistration(repository, clock, NO_WAIT)(workshop.id, registration.id, "alice")

    stored = repository.get(workshop.id)
    assert stored is not None
    assert stored.registrations[0].status is RegistrationStatus.CANCELLED


def test_cancelling_a_cancelled_registration_does_not_save(
    repository: FakeWorkshopRepository, clock: FakeClock
) -> None:
    workshop = make_workshop()
    repository.save(workshop)
    registration = RegisterForWorkshop(repository, clock, NO_WAIT)(workshop.id, "alice", 1)
    cancel = CancelRegistration(repository, clock, NO_WAIT)
    cancel(workshop.id, registration.id, "alice")
    saves = repository.save_calls

    cancel(workshop.id, registration.id, "alice")

    assert repository.save_calls == saves


def test_cancel_retries_after_a_conflict(
    repository: FakeWorkshopRepository, clock: FakeClock
) -> None:
    workshop = make_workshop()
    repository.save(workshop)
    registration = RegisterForWorkshop(repository, clock, NO_WAIT)(workshop.id, "alice", 1)
    repository.fail_next_save_with_conflict()

    CancelRegistration(repository, clock, NO_WAIT)(workshop.id, registration.id, "alice")

    stored = repository.get(workshop.id)
    assert stored is not None and stored.free_seats == workshop.capacity


def test_cancel_too_late_once_time_has_passed(
    repository: FakeWorkshopRepository, clock: FakeClock
) -> None:
    workshop = make_workshop(starts_in=timedelta(days=3))
    repository.save(workshop)
    registration = RegisterForWorkshop(repository, clock, NO_WAIT)(workshop.id, "alice", 1)
    clock.advance(timedelta(days=2))

    with pytest.raises(CancellationTooLate):
        CancelRegistration(repository, clock, NO_WAIT)(workshop.id, registration.id, "alice")


def test_list_upcoming_uses_the_clock(repository: FakeWorkshopRepository, clock: FakeClock) -> None:
    soon, later = (
        make_workshop(starts_in=timedelta(days=1)),
        make_workshop(starts_in=timedelta(days=5)),
    )
    for workshop in (later, soon):
        repository.save(workshop)
    clock.advance(timedelta(days=2))

    assert [w.id for w in ListUpcomingWorkshops(repository, clock)()] == [later.id]
