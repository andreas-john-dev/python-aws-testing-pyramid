from pathlib import Path

from aws_cdk import Duration, Stack
from aws_cdk import aws_apigateway as apigateway
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_ssm as ssm
from constructs import Construct
from workshop_service_infra import parameters, schema

from workshop_cdk.stage import Stage

# Built by `make package`: the functions package and its dependencies, no layers.
LAMBDA_ASSET = Path(__file__).resolve().parents[3] / "build" / "lambda"


class StatelessStack(Stack):
    """The Lambdalith behind a REST API with a Cognito authorizer.

    It finds the table and the user pool through SSM, so it can be replaced at any time without
    touching the stateful resources.
    """

    def __init__(self, scope: Construct, stage: Stage, **kwargs: object) -> None:
        super().__init__(scope, stage.stack_name("stateless"), **kwargs)

        table_name = ssm.StringParameter.value_for_string_parameter(
            self, parameters.name(stage.name, parameters.TABLE_NAME)
        )
        table = dynamodb.Table.from_table_attributes(
            self, "Table", table_name=table_name, global_indexes=[schema.GSI1_NAME]
        )
        user_pool = cognito.UserPool.from_user_pool_id(
            self,
            "UserPool",
            ssm.StringParameter.value_for_string_parameter(
                self, parameters.name(stage.name, parameters.USER_POOL_ID)
            ),
        )

        function = lambda_.Function(
            self,
            "ApiFunction",
            function_name=f"workshops-{stage.name}-api",
            runtime=lambda_.Runtime.PYTHON_3_14,
            architecture=lambda_.Architecture.ARM_64,
            code=lambda_.Code.from_asset(str(LAMBDA_ASSET)),
            handler="functions.api.handler.handler",
            memory_size=512,
            timeout=Duration.seconds(10),
            environment={
                "TABLE_NAME": table_name,
                "POWERTOOLS_SERVICE_NAME": "workshops",
            },
            log_group=logs.LogGroup(
                self,
                "ApiLogs",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=stage.removal_policy,
            ),
        )
        table.grant_read_write_data(function)

        api = apigateway.LambdaRestApi(
            self,
            "Api",
            rest_api_name=f"workshops-{stage.name}",
            handler=function,
            proxy=False,
            default_method_options=apigateway.MethodOptions(
                authorizer=apigateway.CognitoUserPoolsAuthorizer(
                    self, "Authorizer", cognito_user_pools=[user_pool]
                ),
                authorization_type=apigateway.AuthorizationType.COGNITO,
            ),
            deploy_options=apigateway.StageOptions(stage_name="api"),
        )
        workshops = api.root.add_resource("workshops")
        workshops.add_method("GET")
        workshops.add_method("POST")
        workshop = workshops.add_resource("{workshop_id}")
        workshop.add_method("GET")
        registrations = workshop.add_resource("registrations")
        registrations.add_method("POST")
        registrations.add_resource("{registration_id}").add_method("DELETE")

        ssm.StringParameter(
            self,
            "ApiUrlParameter",
            parameter_name=parameters.name(stage.name, parameters.API_URL),
            string_value=api.url,
        )
