from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import pytest

from tests.support.api import ApiClient, expect
from tests.support.aws import StageConfig
from tests.support.cognito import CognitoTestUsers, TestUser, run_id
from tests.support.dynamodb import DynamoDbStateReader, DynamoDbTable

RUN_ID = run_id()


@pytest.fixture(scope="session")
def users(aws: boto3.Session, stage: StageConfig) -> Iterator[dict[str, TestUser]]:
    """Two users, because rules depend on identity: seats per person, cancel only your own."""
    cognito = CognitoTestUsers(aws.client("cognito-idp"), stage)
    try:
        yield {name: cognito.create(f"e2e-{RUN_ID}-{name}") for name in ("alice", "bob")}
    finally:
        cognito.delete_all()


@pytest.fixture
def alice(users: dict[str, TestUser], stage: StageConfig) -> ApiClient:
    return ApiClient(stage.api_url, users["alice"].id_token)


@pytest.fixture
def bob(users: dict[str, TestUser], stage: StageConfig) -> ApiClient:
    return ApiClient(stage.api_url, users["bob"].id_token)


@pytest.fixture
def state(aws_table: DynamoDbTable) -> DynamoDbStateReader:
    """Reads the expected table directly, with the developer or pipeline role.

    If the Lambda wrote to another stage's table, the API answers would still agree with each
    other. Only a look into the expected table shows it.
    """
    return DynamoDbStateReader(aws_table)


@pytest.fixture
def new_workshop(alice: ApiClient, aws_table: DynamoDbTable) -> Callable[..., dict[str, Any]]:
    """Creates a workshop through the API. The table finalizer deletes its items afterwards."""

    def create(starts_in: timedelta = timedelta(days=7), capacity: int = 5) -> dict[str, Any]:
        response = alice.create_workshop(f"e2e {RUN_ID}", datetime.now(UTC) + starts_in, capacity)
        workshop = expect(response, 201)
        aws_table.track(workshop["id"])
        return workshop

    return create
