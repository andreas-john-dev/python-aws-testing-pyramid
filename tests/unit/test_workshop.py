"""Rules of the Workshop aggregate. No fakes, no ports, just the model."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from workshop_service_domain.errors import (
    CancellationTooLate,
    CapacityExceeded,
    RegistrationNotFound,
    RegistrationNotOwned,
    SeatLimitExceeded,
    WorkshopAlreadyStarted,
)
from workshop_service_domain.models import RegistrationStatus, Workshop

from tests.unit.builders import NOW, make_workshop


def test_starts_at_is_normalized_to_utc() -> None:
    berlin = timezone(timedelta(hours=1))
    workshop = Workshop(title="t", starts_at=datetime(2026, 12, 1, 10, tzinfo=berlin), capacity=1)

    assert workshop.starts_at == datetime(2026, 12, 1, 9, tzinfo=UTC)
    assert workshop.starts_at.tzinfo is UTC


def test_naive_starts_at_is_rejected() -> None:
    with pytest.raises(ValueError):
        Workshop(title="t", starts_at=datetime(2026, 12, 1, 10), capacity=1)


def test_registrations_are_ordered_by_creation_then_id() -> None:
    workshop = make_workshop()
    later = workshop.register("alice", 1, NOW + timedelta(minutes=1))
    same_time = [workshop.register(user, 1, NOW) for user in ("bob", "carol")]

    expected = [*sorted(same_time, key=lambda r: r.id), later]
    assert workshop.registrations == expected
    assert Workshop.model_validate(workshop.model_dump()).registrations == expected


def test_register_reduces_free_seats() -> None:
    workshop = make_workshop(capacity=3)

    registration = workshop.register("alice", 2, NOW)

    assert workshop.free_seats == 1
    assert registration.status is RegistrationStatus.ACTIVE
    assert registration.created_at == NOW


def test_pending_registrations_are_those_changed_since_the_last_save() -> None:
    workshop = make_workshop()
    old = workshop.register("alice", 1, NOW)
    workshop.version = 1  # as if saved
    new = workshop.register("bob", 1, NOW)
    workshop.cancel(old.id, "alice", NOW)

    assert {r.id for r in workshop.pending_registrations} == {old.id, new.id}
    workshop.version = 2

    assert workshop.pending_registrations == []


def test_registration_beyond_capacity_is_rejected() -> None:
    workshop = make_workshop(capacity=3)
    workshop.register("alice", 2, NOW)

    with pytest.raises(CapacityExceeded):
        workshop.register("bob", 2, NOW)


def test_cancelled_registrations_do_not_count_towards_capacity() -> None:
    workshop = make_workshop(capacity=2)
    registration = workshop.register("alice", 2, NOW)
    workshop.cancel(registration.id, "alice", NOW)

    workshop.register("bob", 2, NOW)

    assert workshop.free_seats == 0


@pytest.mark.parametrize(("first", "second"), [(1, 2), (2, 1), (2, 2)])
def test_a_person_holds_at_most_two_seats(first: int, second: int) -> None:
    workshop = make_workshop()
    workshop.register("alice", first, NOW)

    with pytest.raises(SeatLimitExceeded):
        workshop.register("alice", second, NOW)


def test_three_seats_at_once_exceed_the_limit() -> None:
    with pytest.raises(SeatLimitExceeded):
        make_workshop().register("alice", 3, NOW)


def test_seat_limit_ignores_cancelled_registrations() -> None:
    workshop = make_workshop()
    registration = workshop.register("alice", 2, NOW)
    workshop.cancel(registration.id, "alice", NOW)

    workshop.register("alice", 2, NOW)

    assert workshop.seats_held_by("alice") == 2


def test_no_registration_once_the_workshop_has_started() -> None:
    workshop = make_workshop(starts_in=timedelta(0))

    with pytest.raises(WorkshopAlreadyStarted):
        workshop.register("alice", 1, NOW)


def test_cancel_just_before_the_deadline() -> None:
    workshop = make_workshop(starts_in=timedelta(hours=48))
    registration = workshop.register("alice", 1, NOW)

    workshop.cancel(registration.id, "alice", NOW)

    assert registration.status is RegistrationStatus.CANCELLED


def test_cancel_just_after_the_deadline() -> None:
    workshop = make_workshop(starts_in=timedelta(hours=48))
    registration = workshop.register("alice", 1, NOW)

    with pytest.raises(CancellationTooLate):
        workshop.cancel(registration.id, "alice", NOW + timedelta(microseconds=1))


def test_only_the_owner_may_cancel() -> None:
    workshop = make_workshop()
    registration = workshop.register("alice", 1, NOW)

    with pytest.raises(RegistrationNotOwned):
        workshop.cancel(registration.id, "bob", NOW)


def test_cancel_unknown_registration() -> None:
    with pytest.raises(RegistrationNotFound):
        make_workshop().cancel("nope", "alice", NOW)


def test_cancelling_twice_changes_nothing() -> None:
    workshop = make_workshop()
    registration = workshop.register("alice", 1, NOW)
    workshop.cancel(registration.id, "alice", NOW)
    before = workshop.model_copy(deep=True)

    workshop.cancel(registration.id, "alice", NOW)

    assert workshop == before
