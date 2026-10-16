"""Fixtures shared by contract, integration, E2E and load tests."""

from collections.abc import Iterator

import boto3
import pytest

from tests.support.aws import StageConfig, aws_session, stage_config
from tests.support.dynamodb import DynamoDbTable
from tests.support.moto import moto_table

MOTO = "moto"
AWS = "aws"
DYNAMODB_BACKENDS = [MOTO, pytest.param(AWS, marks=pytest.mark.aws)]


@pytest.fixture(scope="session")
def aws() -> boto3.Session:
    return aws_session()


@pytest.fixture(scope="session")
def stage(aws: boto3.Session) -> StageConfig:
    return stage_config(aws)


@pytest.fixture
def aws_table(aws: boto3.Session, stage: StageConfig) -> Iterator[DynamoDbTable]:
    """The table CDK actually created for the stage, GSI projection included."""
    table = DynamoDbTable(client=aws.client("dynamodb"), name=stage.table_name)
    yield table
    table.cleanup()


@pytest.fixture(params=DYNAMODB_BACKENDS)
def dynamodb_table(request: pytest.FixtureRequest) -> Iterator[DynamoDbTable]:
    if request.param == AWS:
        yield request.getfixturevalue("aws_table")
    else:
        with moto_table() as table:
            yield table
