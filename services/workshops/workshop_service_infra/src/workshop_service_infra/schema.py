"""Single source of truth for the workshops table.

The adapter, the moto fixture and the CDK stack all read these names, so the test table and
the deployed table cannot drift apart.
"""

from typing import Any

PARTITION_KEY = "pk"
SORT_KEY = "sk"

GSI1_NAME = "gsi1"
GSI1_PARTITION_KEY = "gsi1pk"
GSI1_SORT_KEY = "gsi1sk"
GSI1_PROJECTION = "ALL"

WORKSHOP_PREFIX = "WORKSHOP#"
META_SORT_KEY = "META"
REGISTRATION_PREFIX = "REG#"
UPCOMING_PARTITION = "WORKSHOPS"


def workshop_pk(workshop_id: str) -> str:
    return f"{WORKSHOP_PREFIX}{workshop_id}"


def registration_sk(registration_id: str) -> str:
    return f"{REGISTRATION_PREFIX}{registration_id}"


def create_table_kwargs(table_name: str) -> dict[str, Any]:
    """Arguments for `CreateTable`, used where no CDK runs (moto)."""
    return {
        "TableName": table_name,
        "BillingMode": "PAY_PER_REQUEST",
        "AttributeDefinitions": [
            {"AttributeName": name, "AttributeType": "S"}
            for name in (PARTITION_KEY, SORT_KEY, GSI1_PARTITION_KEY, GSI1_SORT_KEY)
        ],
        "KeySchema": [
            {"AttributeName": PARTITION_KEY, "KeyType": "HASH"},
            {"AttributeName": SORT_KEY, "KeyType": "RANGE"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": GSI1_NAME,
                "KeySchema": [
                    {"AttributeName": GSI1_PARTITION_KEY, "KeyType": "HASH"},
                    {"AttributeName": GSI1_SORT_KEY, "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": GSI1_PROJECTION},
            }
        ],
    }
