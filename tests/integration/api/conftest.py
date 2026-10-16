import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from functions.api.app import build_app
from workshop_service_domain.use_cases import RetryPolicy
from workshop_service_infra.dynamodb import DynamoDBWorkshopRepository

from tests.fakes import FakeClock
from tests.support.dynamodb import DynamoDbTable
from tests.support.moto import moto_table

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


@dataclass
class ApiResponse:
    status: int
    body: Any
    headers: dict[str, str]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def table() -> Iterator[DynamoDbTable]:
    with moto_table() as table:
        yield table


@pytest.fixture
def repository(table: DynamoDbTable) -> DynamoDBWorkshopRepository:
    return DynamoDBWorkshopRepository(table.client, table.name)


@pytest.fixture
def app(repository: DynamoDBWorkshopRepository, clock: FakeClock) -> APIGatewayRestResolver:
    return build_app(repository, clock, RetryPolicy(base_delay=0))


def api_event(
    method: str, path: str, body: Any = None, user_id: str | None = "alice"
) -> dict[str, Any]:
    """A REST API proxy event as API Gateway sends it after the Cognito authorizer."""
    authorizer = {"claims": {"sub": user_id}} if user_id else {}
    return {
        "resource": path,
        "path": path,
        "httpMethod": method,
        "headers": {"content-type": "application/json"},
        "multiValueHeaders": {},
        "queryStringParameters": None,
        "multiValueQueryStringParameters": None,
        "pathParameters": None,
        "stageVariables": None,
        "requestContext": {
            "resourcePath": path,
            "httpMethod": method,
            "path": path,
            "stage": "test",
            "requestId": "test-request",
            "authorizer": authorizer,
        },
        "body": body if isinstance(body, str) or body is None else json.dumps(body),
        "isBase64Encoded": False,
    }


@pytest.fixture
def call(app: APIGatewayRestResolver) -> Callable[..., ApiResponse]:
    def call(
        method: str, path: str, body: Any = None, user_id: str | None = "alice"
    ) -> ApiResponse:
        response = app.resolve(api_event(method, path, body, user_id), {})
        raw = response.get("body")
        return ApiResponse(
            status=response["statusCode"],
            body=json.loads(raw) if raw else None,
            headers=response.get("headers", {}),
        )

    return call
