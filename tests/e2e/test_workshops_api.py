"""Through API Gateway, with real Cognito tokens. Every request passes the authorizer, the Lambda
and its IAM role, so this is the only level that tests the Lambda's IAM policy.

Every writing test checks two things: the API response and the items in DynamoDB.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
import requests

from tests.support.api import ApiClient, expect
from tests.support.aws import StageConfig
from tests.support.cognito import TestUser
from tests.support.dynamodb import DynamoDbStateReader, RegistrationState, WorkshopState
from tests.support.polling import eventually

pytestmark = pytest.mark.aws  # needs a deployed stage

NewWorkshop = Callable[..., dict[str, Any]]


def test_create_register_list_cancel(
    alice: ApiClient,
    users: dict[str, TestUser],
    new_workshop: NewWorkshop,
    state: DynamoDbStateReader,
) -> None:
    # save: TransactWriteItems
    workshop = new_workshop(capacity=5)
    assert workshop["free_seats"] == 5
    assert state.read(workshop["id"]) == _state(version=1)

    registration = expect(alice.register(workshop["id"], 2), 201)
    assert registration["user_id"] == users["alice"].user_id
    assert state.read(workshop["id"]) == _state(2, (users["alice"].user_id, 2, "active"))

    # get: Query on the table
    assert expect(alice.get_workshop(workshop["id"]), 200)["free_seats"] == 3

    # list_upcoming: Query on the GSI, which is eventually consistent, so poll briefly.
    listed = eventually(
        lambda: _listed(alice, workshop["id"]),
        until=lambda w: w is not None and w["free_seats"] == 3,
    )
    assert listed is not None and listed["free_seats"] == 3

    expect(alice.cancel(workshop["id"], registration["id"]), 204)
    assert state.read(workshop["id"]) == _state(3, (users["alice"].user_id, 2, "cancelled"))


def test_three_seats_are_rejected_and_change_nothing(
    alice: ApiClient, new_workshop: NewWorkshop, state: DynamoDbStateReader
) -> None:
    workshop = new_workshop()

    assert expect(alice.register(workshop["id"], 3), 422)["error"] == "SeatLimitExceeded"
    assert state.read(workshop["id"]) == _state(version=1)


def test_bob_cannot_cancel_alices_registration(
    alice: ApiClient,
    bob: ApiClient,
    users: dict[str, TestUser],
    new_workshop: NewWorkshop,
    state: DynamoDbStateReader,
) -> None:
    workshop = new_workshop()
    registration = expect(alice.register(workshop["id"], 1), 201)
    before = state.read(workshop["id"])

    expect(bob.cancel(workshop["id"], registration["id"]), 403)

    assert state.read(workshop["id"]) == before == _state(2, (users["alice"].user_id, 1, "active"))


def test_a_full_workshop_rejects_registrations(
    alice: ApiClient,
    bob: ApiClient,
    users: dict[str, TestUser],
    new_workshop: NewWorkshop,
    state: DynamoDbStateReader,
) -> None:
    workshop = new_workshop(capacity=1)
    expect(alice.register(workshop["id"], 1), 201)

    assert expect(bob.register(workshop["id"], 1), 422)["error"] == "CapacityExceeded"
    assert state.read(workshop["id"]) == _state(2, (users["alice"].user_id, 1, "active"))


def test_cancellation_deadline_without_time_travel(
    alice: ApiClient, new_workshop: NewWorkshop, state: DynamoDbStateReader
) -> None:
    tomorrow = new_workshop(starts_in=timedelta(hours=24))
    registration = expect(alice.register(tomorrow["id"], 1), 201)

    assert expect(alice.cancel(tomorrow["id"], registration["id"]), 422)["error"] == (
        "CancellationTooLate"
    )
    after = state.read(tomorrow["id"])
    assert after is not None and after.active_seats == 1


@pytest.mark.parametrize("token", [None, "not-a-token"])
def test_requests_without_a_valid_token_are_rejected_by_api_gateway(
    stage: StageConfig, token: str | None
) -> None:
    response = ApiClient(stage.api_url, token).list_workshops()

    assert response.status_code == 401
    # API Gateway answered, not the Lambda: there is no error body from our handler.
    assert "error" not in response.json()


def test_items_have_the_dynamodb_format(
    alice: ApiClient, new_workshop: NewWorkshop, state: DynamoDbStateReader
) -> None:
    workshop = new_workshop()
    registration = expect(alice.register(workshop["id"], 1), 201)

    items = {i["sk"]: i for i in state.raw_items(workshop["id"])}

    assert set(items) == {"META", f"REG#{registration['id']}"}
    assert datetime.fromisoformat(items["META"]["starts_at"]) == datetime.fromisoformat(
        workshop["starts_at"]
    )
    assert items["META"]["starts_at"].endswith("+00:00")


def _state(version: int, *registrations: tuple[str, int, str]) -> WorkshopState:
    return WorkshopState(
        version=version,
        registrations=sorted(
            (RegistrationState(*r) for r in registrations), key=lambda r: (r.user_id, r.seats)
        ),
    )


def _listed(api: ApiClient, workshop_id: str) -> dict[str, Any] | None:
    response: requests.Response = api.list_workshops()
    workshops = expect(response, 200)["workshops"]
    return next((w for w in workshops if w["id"] == workshop_id), None)
