"""SSM parameter names of a stage. CDK writes them, the AWS tests read them."""

API_URL = "api-url"
TABLE_NAME = "table-name"
USER_POOL_ID = "user-pool-id"
TEST_CLIENT_ID = "test-client-id"


def prefix(stage: str) -> str:
    return f"/workshops/{stage}/"


def name(stage: str, key: str) -> str:
    return f"{prefix(stage)}{key}"
