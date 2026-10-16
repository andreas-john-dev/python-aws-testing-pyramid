from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

from workshop_cdk.oidc import GITHUB_OIDC_URL

CI_STACK_NAME = "workshops-ci"


def test_permissions(account: str, region: str) -> list[iam.PolicyStatement]:
    """What `make test-aws`, `make test-e2e` and `make load` need, for any stage."""
    table = f"arn:aws:dynamodb:{region}:{account}:table/workshops-*"
    return [
        iam.PolicyStatement(actions=["sts:GetCallerIdentity"], resources=["*"]),
        iam.PolicyStatement(
            actions=["ssm:GetParameter*"],
            resources=[f"arn:aws:ssm:{region}:{account}:parameter/workshops/*"],
        ),
        iam.PolicyStatement(
            actions=[
                "cognito-idp:AdminCreateUser",
                "cognito-idp:AdminSetUserPassword",
                "cognito-idp:AdminInitiateAuth",
                "cognito-idp:AdminDeleteUser",
            ],
            resources=[f"arn:aws:cognito-idp:{region}:{account}:userpool/*"],
        ),
        iam.PolicyStatement(
            actions=[
                "dynamodb:GetItem",
                "dynamodb:Query",
                "dynamodb:PutItem",
                "dynamodb:UpdateItem",
                "dynamodb:DeleteItem",
                "dynamodb:ConditionCheckItem",
            ],
            resources=[table, f"{table}/index/*"],
        ),
    ]


def subject_prefix(github_repository: str, reported_prefix: str | None) -> str:
    """The start of the `sub` claim in this repository's OIDC tokens.

    By default it is `repo:<owner>/<repo>`. Repositories with immutable subjects add the owner
    and repository ids (`repo:<owner>@<id>/<repo>@<id>`), so a deleted and re-created repository
    of the same name cannot assume the role. GitHub reports the prefix in
    `GET /repos/<owner>/<repo>/actions/oidc/customization/sub` as `sub_claim_prefix`.
    """
    return reported_prefix or f"repo:{github_repository}"


class CiStack(Stack):
    """GitHub OIDC provider and pipeline role. Once per account, not per stage.

    Optional: with an existing pipeline role, skip this stack and add `test_permissions` to it.
    `oidc_provider_arn` references an existing provider; None creates one (see oidc.py).
    `github_subject_prefix` is the `sub` claim up to the event, see `subject_prefix`.
    """

    def __init__(
        self,
        scope: Construct,
        *,
        github_subject_prefix: str,
        oidc_provider_arn: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, CI_STACK_NAME, **kwargs)

        provider = (
            iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
                self, "GitHubOidc", oidc_provider_arn
            )
            if oidc_provider_arn
            else iam.OpenIdConnectProvider(
                self, "GitHubOidc", url=GITHUB_OIDC_URL, client_ids=["sts.amazonaws.com"]
            )
        )
        role = iam.Role(
            self,
            "PipelineRole",
            role_name="workshops-pipeline",
            assumed_by=iam.WebIdentityPrincipal(
                provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                    },
                    # Only workflows of this repository may assume the role.
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": f"{github_subject_prefix}:*"
                    },
                },
            ),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::{self.account}:role/cdk-*"],
            )
        )
        for statement in test_permissions(self.account, self.region):
            role.add_to_policy(statement)
        CfnOutput(self, "PipelineRoleArn", value=role.role_arn)
