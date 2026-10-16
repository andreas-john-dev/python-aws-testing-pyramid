"""Lambda entry point. Builds the production instance once per execution environment."""

import os
from typing import Any

import boto3
from aws_lambda_powertools.utilities.typing import LambdaContext
from workshop_service_infra.clock import SystemClock
from workshop_service_infra.dynamodb import DynamoDBWorkshopRepository

from functions.api.app import build_app, logger

app = build_app(
    DynamoDBWorkshopRepository(boto3.client("dynamodb"), os.environ["TABLE_NAME"]),
    SystemClock(),
)


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    return app.resolve(event, context)
