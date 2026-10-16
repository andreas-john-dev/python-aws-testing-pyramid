from aws_cdk import Stack
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ssm as ssm
from constructs import Construct
from workshop_service_infra import parameters

from workshop_cdk.stage import Stage


class SharedStack(Stack):
    """Cognito user pool, plus an app client for tests in non-production stages."""

    def __init__(self, scope: Construct, stage: Stage, **kwargs: object) -> None:
        super().__init__(scope, stage.stack_name("shared"), **kwargs)

        user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"workshops-{stage.name}",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(username=True),
            removal_policy=stage.removal_policy,
        )
        ssm.StringParameter(
            self,
            "UserPoolIdParameter",
            parameter_name=parameters.name(stage.name, parameters.USER_POOL_ID),
            string_value=user_pool.user_pool_id,
        )

        if not stage.is_production:
            # Lets E2E and load tests sign in test users with AdminInitiateAuth.
            test_client = user_pool.add_client(
                "TestClient",
                user_pool_client_name=f"workshops-{stage.name}-tests",
                generate_secret=False,
                auth_flows=cognito.AuthFlow(admin_user_password=True),
            )
            ssm.StringParameter(
                self,
                "TestClientIdParameter",
                parameter_name=parameters.name(stage.name, parameters.TEST_CLIENT_ID),
                string_value=test_client.user_pool_client_id,
            )
