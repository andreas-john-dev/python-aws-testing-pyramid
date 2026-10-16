"""The Lambdalith wired to the DynamoDB adapter on moto: routing, validation, error mapping."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from workshop_service_domain.errors import ConcurrentUpdateError
from workshop_service_infra.dynamodb import DynamoDBWorkshopRepository

from tests.fakes import FakeClock
from tests.integration.api.conftest import NOW, ApiResponse

Call = Callable[..., ApiResponse]


def create(
    call: Call, starts_in: timedelta = timedelta(days=7), capacity: int = 3
) -> dict[str, Any]:
    body = {"title": "Testing", "starts_at": (NOW + starts_in).isoformat(), "capacity": capacity}
    response = call("POST", "/workshops", body)
    assert response.status == 201, response.body
    return response.body


def register(call: Call, workshop_id: str, seats: int = 1, user_id: str = "alice") -> ApiResponse:
    return call("POST", f"/workshops/{workshop_id}/registrations", {"seats": seats}, user_id)


def test_create_workshop(call: Call) -> None:
    workshop = create(call, capacity=5)

    assert set(workshop) == {"id", "title", "starts_at", "capacity", "free_seats"}
    assert workshop["free_seats"] == 5


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        {"title": "", "starts_at": "2030-01-01T10:00:00Z", "capacity": 1},
        {"title": "t", "starts_at": "2030-01-01T10:00:00", "capacity": 1},
        {"title": "t", "starts_at": "2030-01-01T10:00:00Z", "capacity": 0},
    ],
)
def test_invalid_body_is_400(call: Call, body: Any) -> None:
    assert call("POST", "/workshops", body).status == 400


def test_missing_claims_is_401(call: Call) -> None:
    assert call("GET", "/workshops", user_id=None).status == 401


def test_list_returns_only_upcoming_sorted_by_start(call: Call, clock: FakeClock) -> None:
    later = create(call, starts_in=timedelta(days=7))
    sooner = create(call, starts_in=timedelta(days=2))
    create(call, starts_in=timedelta(hours=1))
    clock.advance(timedelta(hours=2))

    response = call("GET", "/workshops")

    assert response.status == 200
    assert [w["id"] for w in response.body["workshops"]] == [sooner["id"], later["id"]]


def test_get_workshop_shows_free_seats(call: Call) -> None:
    workshop = create(call, capacity=3)
    register(call, workshop["id"], seats=2)

    response = call("GET", f"/workshops/{workshop['id']}")

    assert response.status == 200
    assert response.body["free_seats"] == 1


def test_get_unknown_workshop_is_404(call: Call) -> None:
    assert call("GET", "/workshops/nope").status == 404


def test_register(call: Call) -> None:
    workshop = create(call)

    response = register(call, workshop["id"], seats=2)

    assert response.status == 201
    assert response.body["user_id"] == "alice"
    assert (response.body["seats"], response.body["status"]) == (2, "active")


@pytest.mark.parametrize(
    ("seats", "capacity", "starts_in", "error"),
    [
        (3, 5, timedelta(days=7), "SeatLimitExceeded"),
        (2, 1, timedelta(days=7), "CapacityExceeded"),
    ],
)
def test_rule_violations_are_422(
    call: Call, seats: int, capacity: int, starts_in: timedelta, error: str
) -> None:
    workshop = create(call, capacity=capacity, starts_in=starts_in)

    response = register(call, workshop["id"], seats=seats)

    assert (response.status, response.body["error"]) == (422, error)


def test_register_after_start_is_422(call: Call, clock: FakeClock) -> None:
    workshop = create(call, starts_in=timedelta(hours=1))
    clock.advance(timedelta(hours=1))

    response = register(call, workshop["id"])

    assert (response.status, response.body["error"]) == (422, "WorkshopAlreadyStarted")


def test_register_for_unknown_workshop_is_404(call: Call) -> None:
    assert register(call, "nope").status == 404


def test_conflict_after_all_retries_is_409(
    call: Call, repository: DynamoDBWorkshopRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    workshop = create(call)

    def always_conflict(_: Any) -> None:
        raise ConcurrentUpdateError(workshop["id"])

    # Integration level: the adapter is real, only this one call is forced to lose every race.
    monkeypatch.setattr(repository, "save", always_conflict)

    response = register(call, workshop["id"])

    assert (response.status, response.body["error"]) == (409, "ConcurrentUpdateError")


def test_cancel(call: Call) -> None:
    workshop = create(call)
    registration = register(call, workshop["id"]).body

    response = call("DELETE", f"/workshops/{workshop['id']}/registrations/{registration['id']}")

    assert (response.status, response.body) == (204, None)
    assert call("GET", f"/workshops/{workshop['id']}").body["free_seats"] == workshop["capacity"]


def test_cancel_someone_elses_registration_is_403(call: Call) -> None:
    workshop = create(call)
    registration = register(call, workshop["id"], user_id="alice").body

    response = call(
        "DELETE", f"/workshops/{workshop['id']}/registrations/{registration['id']}", user_id="bob"
    )

    assert response.status == 403


def test_cancel_unknown_registration_is_404(call: Call) -> None:
    workshop = create(call)

    assert call("DELETE", f"/workshops/{workshop['id']}/registrations/nope").status == 404


def test_cancel_too_late_is_422(call: Call) -> None:
    workshop = create(call, starts_in=timedelta(hours=24))
    registration = register(call, workshop["id"]).body

    response = call("DELETE", f"/workshops/{workshop['id']}/registrations/{registration['id']}")

    assert (response.status, response.body["error"]) == (422, "CancellationTooLate")
