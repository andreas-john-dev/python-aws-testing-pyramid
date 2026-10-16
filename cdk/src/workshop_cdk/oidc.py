"""Finds out whether the ci stack creates the GitHub OIDC provider or references one.

An account has at most one provider per URL. If another stack or a person already created it,
creating it again fails with EntityAlreadyExists, so the ci stack references it instead. If the
ci stack created it itself, it must keep creating it: switching to a reference would make
CloudFormation delete the provider.
"""

import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

GITHUB_OIDC_HOST = "token.actions.githubusercontent.com"
GITHUB_OIDC_URL = f"https://{GITHUB_OIDC_HOST}"
PROVIDER_RESOURCE_TYPE = "Custom::AWSCDKOpenIdConnectProvider"


def choose_provider(
    explicit_arn: str | None, stack_owns_provider: bool, existing_arn: str | None
) -> str | None:
    """The ARN to reference, or None to create the provider in the stack."""
    if explicit_arn:
        return explicit_arn
    if stack_owns_provider:
        return None
    return existing_arn


def discover_provider(stack_name: str, explicit_arn: str | None) -> str | None:
    if explicit_arn:
        return explicit_arn
    region = os.environ.get("CDK_DEFAULT_REGION") or os.environ.get("AWS_REGION")
    session = boto3.Session(region_name=region)
    try:
        return choose_provider(
            explicit_arn=None,
            stack_owns_provider=_stack_owns_provider(session, stack_name),
            existing_arn=_existing_provider(session),
        )
    except (BotoCoreError, ClientError) as error:
        raise SystemExit(
            f"Cannot look up the GitHub OIDC provider ({error}). Export AWS credentials and "
            "AWS_REGION, or pass -c oidc_provider_arn=<arn>."
        ) from error


def _stack_owns_provider(session: boto3.Session, stack_name: str) -> bool:
    try:
        resources = session.client("cloudformation").describe_stack_resources(StackName=stack_name)[
            "StackResources"
        ]
    except ClientError as error:
        if "does not exist" in str(error):
            return False
        raise
    return any(
        r["ResourceType"] == PROVIDER_RESOURCE_TYPE and r["ResourceStatus"] != "DELETE_COMPLETE"
        for r in resources
    )


def _existing_provider(session: boto3.Session) -> str | None:
    providers = session.client("iam").list_open_id_connect_providers()["OpenIDConnectProviderList"]
    return next((p["Arn"] for p in providers if p["Arn"].endswith(f"/{GITHUB_OIDC_HOST}")), None)
