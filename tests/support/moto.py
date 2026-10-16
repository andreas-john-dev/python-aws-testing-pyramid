from collections.abc import Iterator
from contextlib import contextmanager

import boto3
from moto import mock_aws
from workshop_service_infra import schema

from tests.support.dynamodb import DynamoDbTable

MOTO_REGION = "eu-central-1"
MOTO_TABLE = "workshops-moto"


@contextmanager
def moto_table() -> Iterator[DynamoDbTable]:
    """A moto table built from schema.py, with its own session and dummy credentials.

    No environment variable is touched, so real credentials for the `aws` variant stay intact.
    """
    with mock_aws():
        session = boto3.Session(
            aws_access_key_id="testing", aws_secret_access_key="testing", region_name=MOTO_REGION
        )
        client = session.client("dynamodb")
        client.create_table(**schema.create_table_kwargs(MOTO_TABLE))
        yield DynamoDbTable(client=client, name=MOTO_TABLE)
