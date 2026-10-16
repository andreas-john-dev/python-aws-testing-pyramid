"""Cognito test users for E2E and load tests: created per run, deleted afterwards."""

import contextlib
import secrets
import uuid
from dataclasses import dataclass

from botocore.client import BaseClient

from tests.support.aws import StageConfig


@dataclass(frozen=True)
class TestUser:
    __test__ = False  # not a pytest test class

    username: str
    user_id: str  # the `sub` claim, which the API uses as user_id
    id_token: str


def run_id() -> str:
    return uuid.uuid4().hex[:8]


class CognitoTestUsers:
    def __init__(self, cognito: BaseClient, stage: StageConfig) -> None:
        self._cognito = cognito
        self._stage = stage
        self._created: list[str] = []

    def create(self, username: str) -> TestUser:
        password = f"{secrets.token_urlsafe(24)}Aa1!"
        response = self._cognito.admin_create_user(
            UserPoolId=self._stage.user_pool_id, Username=username, MessageAction="SUPPRESS"
        )
        self._created.append(username)
        sub = next(a["Value"] for a in response["User"]["Attributes"] if a["Name"] == "sub")
        self._cognito.admin_set_user_password(
            UserPoolId=self._stage.user_pool_id,
            Username=username,
            Password=password,
            Permanent=True,
        )
        auth = self._cognito.admin_initiate_auth(
            UserPoolId=self._stage.user_pool_id,
            ClientId=self._stage.test_client_id,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
        return TestUser(username, sub, auth["AuthenticationResult"]["IdToken"])

    def delete_all(self) -> None:
        for username in self._created:
            with contextlib.suppress(self._cognito.exceptions.UserNotFoundException):
                self._cognito.admin_delete_user(
                    UserPoolId=self._stage.user_pool_id, Username=username
                )
        self._created.clear()
