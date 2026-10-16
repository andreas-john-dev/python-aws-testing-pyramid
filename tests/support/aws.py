"""Credentials and stage configuration for every test that talks to real AWS.

`make test-aws`, `make test-e2e` and `make load` share this module. It does not care whether the
credentials belong to a developer role (local, e.g. via SSO) or the pipeline role (CI, via OIDC).
Missing credentials fail the run: these tests only run when started explicitly, and a silent skip
would be a false green in CI.
"""

import os
from dataclasses import dataclass

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from workshop_service_infra import parameters

REQUIRED_ENV = ("AWS_REGION", "STAGE")


@dataclass(frozen=True)
class StageConfig:
    stage: str
    api_url: str
    table_name: str
    user_pool_id: str
    test_client_id: str


class AwsSetupError(Exception):
    """Raised before any test runs. pytest fixtures turn it into a failure, Locust exits."""


def _fail(message: str) -> None:
    raise AwsSetupError(message)


def aws_session() -> boto3.Session:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        _fail(f"AWS tests need {', '.join(missing)}. Export temporary credentials and STAGE first.")
    session = boto3.Session(region_name=os.environ["AWS_REGION"])
    if session.get_credentials() is None:
        _fail(
            "No AWS credentials found. Export AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and "
            "AWS_SESSION_TOKEN, e.g. `eval $(aws configure export-credentials --format env)`."
        )
    try:
        identity = session.client("sts").get_caller_identity()
    except (ClientError, BotoCoreError) as error:
        _fail(f"AWS credentials are not usable (expired token?): {error}")
    print(f"\nAWS tests run as {identity['Arn']}")
    return session


def stage_config(session: boto3.Session) -> StageConfig:
    stage = os.environ["STAGE"]
    ssm = session.client("ssm")
    response = ssm.get_parameters_by_path(Path=parameters.prefix(stage))
    values = {
        p["Name"].removeprefix(parameters.prefix(stage)): p["Value"] for p in response["Parameters"]
    }
    keys = (
        parameters.API_URL,
        parameters.TABLE_NAME,
        parameters.USER_POOL_ID,
        parameters.TEST_CLIENT_ID,
    )
    missing = [key for key in keys if key not in values]
    if missing:
        _fail(
            f"Stage {stage!r} is not deployed: missing SSM parameters {missing} under "
            f"{parameters.prefix(stage)}"
        )
    return StageConfig(
        stage=stage,
        api_url=values[parameters.API_URL].rstrip("/"),
        table_name=values[parameters.TABLE_NAME],
        user_pool_id=values[parameters.USER_POOL_ID],
        test_client_id=values[parameters.TEST_CLIENT_ID],
    )
